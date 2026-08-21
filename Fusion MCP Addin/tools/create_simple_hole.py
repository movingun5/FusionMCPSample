"""MCP tool for one parametrically positioned simple hole."""

import adsk.core

from ..fusion.holes import create_simple_hole
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ..mcp_primitives.tool import Tool


def handler(
    name,
    body_name,
    x_expression,
    y_expression,
    diameter_expression,
    depth_expression,
):
    return create_simple_hole(
        adsk.core.Application.get(),
        name,
        body_name,
        x_expression,
        y_expression,
        diameter_expression,
        depth_expression,
    )


tool = (
    Tool.create_simple(
        name="create_simple_hole",
        description=(
            "Create one named simple hole on a named solid body's planar +Z top "
            "face. X, Y, diameter, and depth are driving Fusion expressions."
        ),
    )
    .add_input_property(
        "name",
        {
            "type": "string",
            "minLength": 1,
            "description": "Unique hole feature name in the active component.",
        },
    )
    .add_input_property(
        "body_name",
        {
            "type": "string",
            "minLength": 1,
            "description": "Existing solid body name in the active component.",
        },
    )
    .add_input_property(
        "x_expression",
        {
            "type": "string",
            "minLength": 1,
            "description": "Hole-center X coordinate in the top-face sketch.",
        },
    )
    .add_input_property(
        "y_expression",
        {
            "type": "string",
            "minLength": 1,
            "description": "Hole-center Y coordinate in the top-face sketch.",
        },
    )
    .add_input_property(
        "diameter_expression",
        {
            "type": "string",
            "minLength": 1,
            "description": "Positive Fusion length expression for hole diameter.",
        },
    )
    .add_input_property(
        "depth_expression",
        {
            "type": "string",
            "minLength": 1,
            "description": "Positive Fusion length expression for hole depth.",
        },
    )
    .add_required_input("name")
    .add_required_input("body_name")
    .add_required_input("x_expression")
    .add_required_input("y_expression")
    .add_required_input("diameter_expression")
    .add_required_input("depth_expression")
    .strict_schema()
)

register(Item.create_tool_item(tool=tool, handler=handler))
