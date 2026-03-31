"""
agentdx-bridge: Langfuse poller → agentdx Diagnoser → Prometheus metrics.

Architecture:
  1. Poll Langfuse for completed traces (cursor-based, persisted across restarts)
  2. Convert each trace via langfuse_converter.convert()
  3. Run agentdx.Diagnoser.diagnose() → DiagnosticReport
  4. Expose pathology counts + health scores as Prometheus metrics
  5. Serve metrics on :METRICS_PORT/metrics

Environment variables:
  LANGFUSE_HOST              Langfuse server URL (default: http://langfuse:3000)
  LANGFUSE_PUBLIC_KEY        Langfuse project public key
  LANGFUSE_SECRET_KEY        Langfuse project secret key
  AGENTDX_POLL_INTERVAL      Seconds between polls (default: 30)
  METRICS_PORT               Port for Prometheus metrics endpoint (default: 7700)
  CURSOR_FILE                Path to persist poll cursor (default: /tmp/agentdx_cursor.txt)
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

# ── Config ────────────────────────────────────────────────────────────────────

LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "http://langfuse:3000")
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")
POLL_INTERVAL = int(os.environ.get("AGENTDX_POLL_INTERVAL", "30"))
METRICS_PORT = int(os.environ.get("METRICS_PORT", "7700"))
CURSOR_FILE = Path(os.environ.get("CURSOR_FILE", "/tmp/agentdx_cursor.txt"))

# ── Prometheus metrics ────────────────────────────────────────────────────────

try:
    from prometheus_client import (
        Counter, Gauge, start_http_server, generate_latest, CONTENT_TYPE_LATEST,
    )
    _PROM_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PROM_AVAILABLE = False
    log.warning("prometheus_client not installed — metrics endpoint will be unavailable")

if _PROM_AVAILABLE:
    PATHOLOGY_COUNTER = Counter(
        "agentdx_pathology_detections_total",
        "Total pathology detections by type",
        ["pathology"],
    )
    HEALTH_SCORE = Gauge(
        "agentdx_health_score",
        "Agent health score per session (0–1)",
        ["session_id"],
    )
    TRACES_PROCESSED = Counter(
        "agentdx_traces_processed_total",
        "Total traces processed by the bridge",
    )
    TRACES_ERRORED = Counter(
        "agentdx_traces_errored_total",
        "Total traces that failed processing",
    )
    POLL_DURATION = Gauge(
        "agentdx_poll_duration_seconds",
        "Duration of the last Langfuse poll cycle",
    )

# ── Cursor persistence ────────────────────────────────────────────────────────

def _load_cursor() -> str:
    """Load the last-processed timestamp from disk."""
    if CURSOR_FILE.exists():
        val = CURSOR_FILE.read_text().strip()
        if val:
            return val
    # Default: start from 24h ago to catch recent traces
    since = datetime.now(tz=timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    return since


def _save_cursor(ts: str) -> None:
    CURSOR_FILE.write_text(ts)


# ── Langfuse polling ──────────────────────────────────────────────────────────

def _poll_langfuse(from_ts: str) -> tuple[list[dict], str]:
    """
    Fetch traces from Langfuse created after from_ts.
    Returns (traces, next_cursor_ts).
    Uses Langfuse Python SDK if available, falls back to raw HTTP.
    """
    try:
        from langfuse import Langfuse  # type: ignore[import]
        client = Langfuse(
            host=LANGFUSE_HOST,
            public_key=LANGFUSE_PUBLIC_KEY,
            secret_key=LANGFUSE_SECRET_KEY,
        )
        result = client.get_traces(
            from_timestamp=from_ts,
            order_by="timestamp.asc",
            limit=50,
        )
        traces_raw = [t.dict() if hasattr(t, "dict") else vars(t) for t in result.data]
        # Advance cursor to the latest timestamp seen
        next_ts = from_ts
        if traces_raw:
            last_ts = traces_raw[-1].get("timestamp") or traces_raw[-1].get("createdAt") or from_ts
            if isinstance(last_ts, datetime):
                next_ts = last_ts.isoformat()
            elif isinstance(last_ts, str):
                next_ts = last_ts
        return traces_raw, next_ts

    except ImportError:
        log.error("langfuse SDK not installed — cannot poll traces")
        return [], from_ts
    except Exception as exc:
        log.warning("Langfuse poll failed: %s", exc)
        return [], from_ts


def _fetch_full_trace(trace_id: str) -> dict | None:
    """Fetch a single trace with full observation details."""
    try:
        from langfuse import Langfuse  # type: ignore[import]
        client = Langfuse(
            host=LANGFUSE_HOST,
            public_key=LANGFUSE_PUBLIC_KEY,
            secret_key=LANGFUSE_SECRET_KEY,
        )
        trace = client.get_trace(trace_id)
        return trace.dict() if hasattr(trace, "dict") else vars(trace)
    except Exception as exc:
        log.warning("Failed to fetch full trace %s: %s", trace_id, exc)
        return None


# ── agentdx diagnosis ─────────────────────────────────────────────────────────

def _diagnose(trace_dict: dict) -> None:
    """Convert trace, run Diagnoser, update Prometheus metrics."""
    from agentdx_bridge.langfuse_converter import convert  # type: ignore[import]

    agentdx_trace = convert(trace_dict)
    if agentdx_trace is None:
        return

    try:
        from agentdx import Diagnoser  # type: ignore[import]
        report = Diagnoser().diagnose(agentdx_trace)
    except ImportError:
        log.error("agentdx not installed — cannot run diagnosis")
        return
    except Exception as exc:
        log.warning("Diagnoser failed for trace %s: %s", agentdx_trace.trace_id, exc)
        if _PROM_AVAILABLE:
            TRACES_ERRORED.inc()
        return

    if _PROM_AVAILABLE:
        TRACES_PROCESSED.inc()

        # Health score
        score = getattr(report, "health_score", None)
        if score is not None:
            HEALTH_SCORE.labels(session_id=agentdx_trace.session_id).set(score)

        # Pathology detections
        detections = getattr(report, "detections", []) or []
        for detection in detections:
            pathology = getattr(detection, "pathology", None) or str(detection)
            PATHOLOGY_COUNTER.labels(pathology=str(pathology)).inc()

    log.info(
        "trace %s — health=%.2f detections=%d",
        agentdx_trace.trace_id,
        getattr(report, "health_score", 0.0) or 0.0,
        len(getattr(report, "detections", []) or []),
    )


# ── Poll loop ─────────────────────────────────────────────────────────────────

def run_poll_loop() -> None:
    cursor = _load_cursor()
    log.info("Starting poll loop — Langfuse=%s interval=%ds from=%s",
             LANGFUSE_HOST, POLL_INTERVAL, cursor)

    while True:
        t0 = time.monotonic()
        try:
            traces, next_cursor = _poll_langfuse(cursor)
            for trace_stub in traces:
                trace_id = trace_stub.get("id")
                if not trace_id:
                    continue
                full_trace = _fetch_full_trace(trace_id)
                if full_trace:
                    _diagnose(full_trace)

            if next_cursor != cursor:
                cursor = next_cursor
                _save_cursor(cursor)
                log.debug("cursor advanced to %s", cursor)

        except Exception as exc:
            log.error("Poll cycle error: %s", exc)

        elapsed = time.monotonic() - t0
        if _PROM_AVAILABLE:
            POLL_DURATION.set(elapsed)

        sleep_for = max(0, POLL_INTERVAL - elapsed)
        time.sleep(sleep_for)


# ── Metrics HTTP server (fallback if prometheus_client not available) ─────────

class _MetricsHandler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass

    def do_GET(self):
        if self.path == "/metrics":
            if _PROM_AVAILABLE:
                data = generate_latest()
                self.send_response(200)
                self.send_header("Content-Type", CONTENT_TYPE_LATEST)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                body = b"# prometheus_client not available\n"
                self.send_response(503)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()


def start_metrics_server() -> None:
    if _PROM_AVAILABLE:
        # prometheus_client's built-in HTTP server
        start_http_server(METRICS_PORT)
        log.info("Prometheus metrics on :%d/metrics", METRICS_PORT)
    else:
        server = HTTPServer(("0.0.0.0", METRICS_PORT), _MetricsHandler)
        t = Thread(target=server.serve_forever, daemon=True)
        t.start()
        log.info("Fallback metrics server on :%d/metrics", METRICS_PORT)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    start_metrics_server()
    run_poll_loop()


if __name__ == "__main__":
    main()
