"""MCP tool for a named new-body extrusion from a named sketch."""

import adsk.core

from ..fusion.extrusions import create_extrusion
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ..mcp_primitives.tool import Tool


def handler(name, sketch_name, distance_expression):
    return create_extrusion(
        adsk.core.Application.get(),
        name,
        sketch_name,
        distance_expression,
    )


tool = (
    Tool.create_simple(
        name="create_extrusion",
        description=(
            "Create one named solid New Body extrusion from the largest closed "
            "profile in a named sketch using a Fusion distance expression."
        ),
    )
    .add_input_property(
        "name",
        {
            "type": "string",
            "minLength": 1,
            "description": "Unique extrusion feature name in the active component.",
        },
    )
    .add_input_property(
        "sketch_name",
        {
            "type": "string",
            "minLength": 1,
            "description": "Existing sketch name in the active component.",
        },
    )
    .add_input_property(
        "distance_expression",
        {
            "type": "string",
            "minLength": 1,
            "description": (
                "Non-zero Fusion length expression. A negative value reverses direction."
            ),
        },
    )
    .add_required_input("name")
    .add_required_input("sketch_name")
    .add_required_input("distance_expression")
    .strict_schema()
)

register(Item.create_tool_item(tool=tool, handler=handler))
