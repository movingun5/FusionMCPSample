"""MCP tool for a named, dimensioned center-point rectangle sketch."""

import adsk.core

from ..fusion.sketches import create_rectangle_sketch
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ..mcp_primitives.tool import Tool


def handler(
    name,
    width_expression,
    height_expression,
    plane="xy",
    center_x_expression="0 mm",
    center_y_expression="0 mm",
):
    return create_rectangle_sketch(
        adsk.core.Application.get(),
        name,
        width_expression,
        height_expression,
        plane=plane,
        center_x_expression=center_x_expression,
        center_y_expression=center_y_expression,
    )


tool = (
    Tool.create_simple(
        name="create_rectangle_sketch",
        description=(
            "Create one named center-point rectangle sketch on an XY, XZ, or YZ "
            "construction plane with Fusion expressions as driving width and height dimensions."
        ),
    )
    .add_input_property(
        "name",
        {
            "type": "string",
            "minLength": 1,
            "description": "Unique sketch name in the active component.",
        },
    )
    .add_input_property(
        "width_expression",
        {
            "type": "string",
            "minLength": 1,
            "description": "Positive Fusion length expression for rectangle width.",
        },
    )
    .add_input_property(
        "height_expression",
        {
            "type": "string",
            "minLength": 1,
            "description": "Positive Fusion length expression for rectangle height.",
        },
    )
    .add_input_property(
        "plane",
        {
            "type": "string",
            "enum": ["xy", "xz", "yz"],
            "default": "xy",
        },
    )
    .add_input_property(
        "center_x_expression",
        {
            "type": "string",
            "minLength": 1,
            "default": "0 mm",
            "description": "Rectangle center in the sketch plane's local X direction.",
        },
    )
    .add_input_property(
        "center_y_expression",
        {
            "type": "string",
            "minLength": 1,
            "default": "0 mm",
            "description": "Rectangle center in the sketch plane's local Y direction.",
        },
    )
    .add_required_input("name")
    .add_required_input("width_expression")
    .add_required_input("height_expression")
    .strict_schema()
)

register(Item.create_tool_item(tool=tool, handler=handler))
