FROM python:3.11-slim

WORKDIR /app

# Install dependencies first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Non-root user for security
RUN useradd -m bridge && chown -R bridge:bridge /app
USER bridge

# Prometheus metrics port
EXPOSE 7700

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7700/health')"

CMD ["python", "-m", "agentdx_bridge.main"]
