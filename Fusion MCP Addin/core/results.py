"""Helpers for MCP-compatible tool results."""

import json


def tool_success(data):
    """Return structured data together with the required text content block."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(data, ensure_ascii=False),
            }
        ],
        "structuredContent": data,
        "isError": False,
    }
