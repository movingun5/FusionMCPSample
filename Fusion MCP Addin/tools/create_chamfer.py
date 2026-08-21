"""MCP tool for a named equal-distance chamfer on a named body."""

import adsk.core

from ..fusion.chamfers import create_chamfer
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ..mcp_primitives.tool import Tool


def handler(
    name,
    body_name,
    distance_expression,
    edge_selector="all",
    tangent_chain=True,
):
    return create_chamfer(
        adsk.core.Application.get(),
        name,
        body_name,
        distance_expression,
        edge_selector=edge_selector,
        tangent_chain=tangent_chain,
    )


tool = (
    Tool.create_simple(
        name="create_chamfer",
        description=(
            "Create one named equal-distance chamfer on all, top, bottom, or "
            "vertical edges of a named solid body using a Fusion expression."
        ),
    )
    .add_input_property(
        "name",
        {
            "type": "string",
            "minLength": 1,
            "description": "Unique chamfer feature name in the active component.",
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
        "distance_expression",
        {
            "type": "string",
            "minLength": 1,
            "description": "Positive Fusion length expression for chamfer distance.",
        },
    )
    .add_input_property(
        "edge_selector",
        {
            "type": "string",
            "enum": ["all", "top", "bottom", "vertical"],
            "default": "all",
            "description": "Stable body-edge group to chamfer.",
        },
    )
    .add_input_property(
        "tangent_chain",
        {
            "type": "boolean",
            "default": True,
            "description": "Include tangentially connected edges.",
        },
    )
    .add_required_input("name")
    .add_required_input("body_name")
    .add_required_input("distance_expression")
    .strict_schema()
)

register(Item.create_tool_item(tool=tool, handler=handler))
