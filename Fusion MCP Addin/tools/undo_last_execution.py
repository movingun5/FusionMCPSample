"""MCP tool to undo the most recent successful Codex execution."""

import adsk.core

from ..fusion.executor import clear_last_checkpoint, get_last_checkpoint
from ..fusion.undo import undo_with
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ..mcp_primitives.tool import Tool


def handler():
    result = undo_with(adsk.core.Application.get(), get_last_checkpoint())
    if not result.get("isError"):
        clear_last_checkpoint()
    return result


tool = Tool.create_simple(
    name="undo_last_execution",
    description=(
        "Undo the latest successful execute_fusion_python transaction in the same active document. "
        "Arbitrary Python cannot be promised universal rollback beyond Fusion's undo support."
    ),
).strict_schema()

register(Item.create_tool_item(tool=tool, handler=handler))
