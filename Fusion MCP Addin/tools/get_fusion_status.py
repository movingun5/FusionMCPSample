"""MCP tool exposing local Fusion and active-design status."""

import adsk.core

from ..core.results import tool_success
from ..fusion.context import get_status
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ..mcp_primitives.tool import Tool


SERVER_VERSION = "2.1.0"


def handler():
    return tool_success(get_status(adsk.core.Application.get(), SERVER_VERSION))


tool = Tool.create_simple(
    name="get_fusion_status",
    description=(
        "Check whether Fusion, the localhost MCP add-in, and an active design are "
        "available. This never returns bearer-token values."
    ),
).strict_schema()

register(Item.create_tool_item(tool=tool, handler=handler))
