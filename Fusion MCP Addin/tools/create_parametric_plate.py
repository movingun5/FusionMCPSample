"""MCP tool for one atomic parameter-driven rectangular plate."""

import adsk.core

from ..fusion.parametric_plates import create_parametric_plate
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ..mcp_primitives.tool import Tool


def handler(
    name,
    parameter_prefix,
    width_expression,
    height_expression,
    thickness_expression,
    holes=None,
    edge_finish=None,
):
    return create_parametric_plate(
        adsk.core.Application.get(),
        name,
        parameter_prefix,
        width_expression,
        height_expression,
        thickness_expression,
        holes=holes,
        edge_finish=edge_finish,
    )


_HOLE_SCHEMA = {
    "type": "object",
    "properties": {
        "key": {
            "type": "string",
            "pattern": "^[A-Za-z_][A-Za-z0-9_]*$",
            "description": "Unique safe identifier used in hole feature and parameter names.",
        },
        "x_expression": {
            "type": "string",
            "minLength": 1,
            "description": "Signed hole-center X coordinate from the plate center.",
        },
        "y_expression": {
            "type": "string",
            "minLength": 1,
            "description": "Signed hole-center Y coordinate from the plate center.",
        },
        "diameter_expression": {
            "type": "string",
            "minLength": 1,
            "description": "Positive Fusion length expression for the hole diameter.",
        },
    },
    "required": ["key", "x_expression", "y_expression", "diameter_expression"],
    "additionalProperties": False,
}

_EDGE_FINISH_SCHEMA = {
    "oneOf": [
        {
            "type": "object",
            "properties": {"type": {"type": "string", "enum": ["none"]}},
            "required": ["type"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["fillet"]},
                "size_expression": {"type": "string", "minLength": 1},
            },
            "required": ["type", "size_expression"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["chamfer"]},
                "size_expression": {"type": "string", "minLength": 1},
            },
            "required": ["type", "size_expression"],
            "additionalProperties": False,
        },
    ],
    "default": {"type": "none"},
    "description": "Optional outer vertical-edge finish applied after all holes.",
}


tool = (
    Tool.create_simple(
        name="create_parametric_plate",
        description=(
            "Atomically create one centered XY rectangular plate with named driving "
            "user parameters, up to 32 circular through-holes, and one optional "
            "vertical-edge fillet or chamfer."
        ),
    )
    .add_input_property(
        "name",
        {
            "type": "string",
            "minLength": 1,
            "description": "Display base name for the component, body, sketches, and features.",
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
        "width_expression",
        {"type": "string", "minLength": 1, "description": "Positive plate X width."},
    )
    .add_input_property(
        "height_expression",
        {"type": "string", "minLength": 1, "description": "Positive plate Y height."},
    )
    .add_input_property(
        "thickness_expression",
        {"type": "string", "minLength": 1, "description": "Positive +Z plate thickness."},
    )
    .add_input_property(
        "holes",
        {
            "type": "array",
            "minItems": 0,
            "maxItems": 32,
            "items": _HOLE_SCHEMA,
            "default": [],
            "description": "Circular through-holes positioned from the plate center.",
        },
    )
    .add_input_property("edge_finish", _EDGE_FINISH_SCHEMA)
    .add_required_input("name")
    .add_required_input("parameter_prefix")
    .add_required_input("width_expression")
    .add_required_input("height_expression")
    .add_required_input("thickness_expression")
    .strict_schema()
)

register(Item.create_tool_item(tool=tool, handler=handler))
