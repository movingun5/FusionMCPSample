"""MCP tool for a named single-direction feature pattern."""

import adsk.core

from ..fusion.patterns import create_linear_pattern
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ..mcp_primitives.tool import Tool


def handler(
    name,
    target_feature_name,
    axis,
    quantity,
    spacing_expression,
):
    return create_linear_pattern(
        adsk.core.Application.get(),
        name,
        target_feature_name,
        axis,
        quantity,
        spacing_expression,
    )


tool = (
    Tool.create_simple(
        name="create_linear_pattern",
        description=(
            "Create one named single-direction pattern of an existing named "
            "Fusion feature along the X, Y, or Z construction axis."
        ),
    )
    .add_input_property(
        "name",
        {
            "type": "string",
            "minLength": 1,
            "description": "Unique pattern feature name in the active component.",
        },
    )
    .add_input_property(
        "target_feature_name",
        {
            "type": "string",
            "minLength": 1,
            "description": "Existing feature name to repeat.",
        },
    )
    .add_input_property(
        "axis",
        {
            "type": "string",
            "enum": ["x", "y", "z"],
            "description": "Principal construction axis for the pattern direction.",
        },
    )
    .add_input_property(
        "quantity",
        {
            "type": "integer",
            "minimum": 2,
            "maximum": 1000,
            "description": "Total instance count including the original feature.",
        },
    )
    .add_input_property(
        "spacing_expression",
        {
            "type": "string",
            "minLength": 1,
            "description": (
                "Non-zero Fusion length expression between adjacent instances; "
                "use a negative value to reverse direction."
            ),
        },
    )
    .add_required_input("name")
    .add_required_input("target_feature_name")
    .add_required_input("axis")
    .add_required_input("quantity")
    .add_required_input("spacing_expression")
    .strict_schema()
)

register(Item.create_tool_item(tool=tool, handler=handler))
