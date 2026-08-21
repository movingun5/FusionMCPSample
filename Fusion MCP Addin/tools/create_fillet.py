"""MCP tool for a named constant-radius fillet on a named body."""

import adsk.core

from ..fusion.fillets import create_fillet
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ..mcp_primitives.tool import Tool


def handler(
    name,
    body_name,
    radius_expression,
    edge_selector="all",
    tangent_chain=True,
):
    return create_fillet(
        adsk.core.Application.get(),
        name,
        body_name,
        radius_expression,
        edge_selector=edge_selector,
        tangent_chain=tangent_chain,
    )


tool = (
    Tool.create_simple(
        name="create_fillet",
        description=(
            "Create one named constant-radius fillet on all, top, bottom, or "
            "vertical edges of a named solid body using a Fusion expression."
        ),
    )
    .add_input_property(
        "name",
        {
            "type": "string",
            "minLength": 1,
            "description": "Unique fillet feature name in the active component.",
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
        "radius_expression",
        {
            "type": "string",
            "minLength": 1,
            "description": "Positive Fusion length expression for fillet radius.",
        },
    )
    .add_input_property(
        "edge_selector",
        {
            "type": "string",
            "enum": ["all", "top", "bottom", "vertical"],
            "default": "all",
            "description": "Stable body-edge group to fillet.",
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
    .add_required_input("radius_expression")
    .strict_schema()
)

register(Item.create_tool_item(tool=tool, handler=handler))
