"""
LiteLLM custom callback: strip unanchored 'pattern' fields from tool JSON schemas.

llama-server b8590 rejects JSON schema patterns that don't start with '^'
and end with '$'. Claude Code's built-in tool schemas often have unanchored
patterns (e.g. ".*\\.py$"). This callback removes all pattern fields before
the request reaches llama-server.
"""

from litellm.integrations.custom_logger import CustomLogger


def _strip_patterns(obj):
    """Recursively remove 'pattern' fields from any JSON-like structure."""
    if isinstance(obj, dict):
        return {k: _strip_patterns(v) for k, v in obj.items() if k != "pattern"}
    if isinstance(obj, list):
        return [_strip_patterns(item) for item in obj]
    return obj


class StripSchemaPatterns(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        if isinstance(data, dict):
            if "tools" in data:
                data["tools"] = _strip_patterns(data["tools"])
            if "functions" in data:
                data["functions"] = _strip_patterns(data["functions"])
        return data


proxy_handler_instance = StripSchemaPatterns()
