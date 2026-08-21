"""MCP tool for safe Fusion user-parameter creation and updates."""

import adsk.core

from ..fusion.parameters import upsert_parameter
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ..mcp_primitives.tool import Tool


def handler(
    name,
    expression,
    unit=None,
    comment=None,
    expected_old_expression=None,
):
    return upsert_parameter(
        adsk.core.Application.get(),
        name,
        expression,
        unit=unit,
        comment=comment,
        expected_old_expression=expected_old_expression,
    )


tool = (
    Tool.create_simple(
        name="upsert_user_parameter",
        description=(
            "Create a named Fusion user parameter or update it in place. "
            "Use expected_old_expression to prevent overwriting a concurrent change."
        ),
    )
    .add_input_property(
        "name",
        {
            "type": "string",
            "pattern": "^[A-Za-z_][A-Za-z0-9_]*$",
            "description": "Stable Fusion user-parameter name.",
        },
    )
    .add_input_property(
        "expression",
        {
            "type": "string",
            "minLength": 1,
            "description": "Fusion expression such as '50 mm' or 'plate_width / 2'.",
        },
    )
    .add_input_property(
        "unit",
        {
            "type": "string",
            "description": "Unit for a new parameter or compatibility check for an existing one.",
        },
    )
    .add_input_property(
        "comment",
        {
            "type": "string",
            "description": "Optional comment. An empty string clears an existing comment.",
        },
    )
    .add_input_property(
        "expected_old_expression",
        {
            "type": "string",
            "description": "Exact current expression required before an update is applied.",
        },
    )
    .add_required_input("name")
    .add_required_input("expression")
    .strict_schema()
)

register(Item.create_tool_item(tool=tool, handler=handler))
