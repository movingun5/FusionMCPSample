"""Deprecated compatibility alias for Autodesk's original script tool."""

from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ..mcp_primitives.tool import Tool
from .execute_fusion_python import handler as execute_fusion_python


def handler(script):
    return execute_fusion_python(
        intent="Legacy execute_api_script call",
        code=script,
        expected_changes={},
    )


tool = Tool.create_with_string_input(
    name="execute_api_script",
    description=(
        "Deprecated compatibility alias. Prefer execute_fusion_python, which includes an "
        "explicit intent and expected_changes contract. The same risk and approval policy applies."
    ),
    input_param_name="script",
    input_param_description="Python source defining run(context).",
)

register(Item.create_tool_item(tool=tool, handler=handler))
