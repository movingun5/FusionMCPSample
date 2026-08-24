"""MCP tool for one atomic parameter-driven straight-line profile extrusion."""

import adsk.core

from ..fusion.parametric_profiles import create_parametric_profile_extrusion
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ..mcp_primitives.tool import Tool


def handler(name, parameter_prefix, vertices, depth_expression):
    return create_parametric_profile_extrusion(
        adsk.core.Application.get(),
        name,
        parameter_prefix,
        vertices,
        depth_expression,
    )


_VERTEX_SCHEMA = {
    "type": "object",
    "properties": {
        "key": {
            "type": "string",
            "pattern": "^[A-Za-z_][A-Za-z0-9_]*$",
            "description": "Unique safe identifier used in vertex parameter names.",
        },
        "x_expression": {
            "type": "string",
            "minLength": 1,
            "description": "Signed X coordinate as a Fusion length expression.",
        },
        "y_expression": {
            "type": "string",
            "minLength": 1,
            "description": "Signed Y coordinate as a Fusion length expression.",
        },
    },
    "required": ["key", "x_expression", "y_expression"],
    "additionalProperties": False,
}


tool = (
    Tool.create_simple(
        name="create_parametric_profile_extrusion",
        description=(
            "Atomically create one closed, non-self-intersecting straight-line XY "
            "profile from named driving vertex parameters and extrude it in +Z as "
            "a new body. Use explicit drawing dimensions; do not pass image data."
        ),
    )
    .add_input_property(
        "name",
        {
            "type": "string",
            "minLength": 1,
            "description": "Display base name for the component, body, sketch, and extrusion.",
        },
    )
    .add_input_property(
        "parameter_prefix",
        {
            "type": "string",
            "pattern": "^[A-Za-z_][A-Za-z0-9_]*$",
            "description": "Safe prefix for every generated Fusion user parameter.",
        },
    )
    .add_input_property(
        "vertices",
        {
            "type": "array",
            "minItems": 3,
            "maxItems": 32,
            "items": _VERTEX_SCHEMA,
            "description": (
                "Ordered boundary vertices. The final vertex is closed back to the first "
                "automatically; do not repeat the first vertex."
            ),
        },
    )
    .add_input_property(
        "depth_expression",
        {
            "type": "string",
            "minLength": 1,
            "description": "Positive +Z NewBody extrusion depth.",
        },
    )
    .add_required_input("name")
    .add_required_input("parameter_prefix")
    .add_required_input("vertices")
    .add_required_input("depth_expression")
    .strict_schema()
)

register(Item.create_tool_item(tool=tool, handler=handler))
