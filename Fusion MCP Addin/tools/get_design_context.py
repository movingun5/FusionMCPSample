"""MCP tool exposing bounded active-design context."""

import adsk.core

from ..core.errors import MCPError
from ..fusion.context import build_design_context
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ..mcp_primitives.tool import Tool


def handler(scope="summary", limit=200):
    try:
        return build_design_context(adsk.core.Application.get(), scope=scope, limit=limit)
    except ValueError as error:
        code = str(error)
        if code not in {"FUSION_UNAVAILABLE", "NO_ACTIVE_DESIGN"}:
            code = "INVALID_REQUEST"
        return MCPError(code, str(error), retryable=code != "INVALID_REQUEST").to_result()


tool = Tool.create_simple(
    name="get_design_context",
    description=(
        "Read the active Fusion design's units, components, bodies, parameters, "
        "and stable entity tokens before generating or editing geometry."
    ),
).add_input_property(
    "scope",
    {
        "type": "string",
        "enum": ["summary", "components", "parameters", "all"],
        "default": "summary",
    },
).add_input_property(
    "limit",
    {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
).strict_schema()

register(Item.create_tool_item(tool=tool, handler=handler))
