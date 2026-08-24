"""MCP tool for an atomic calibrated orthographic canvas set."""

import adsk.core

from ..fusion.canvas_sets import create_orthographic_canvas_set
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ..mcp_primitives.tool import Tool


def handler(name, views, dimension_tolerance_mm=0.25):
    return create_orthographic_canvas_set(
        adsk.core.Application.get(),
        name,
        views,
        dimension_tolerance_mm,
    )


_VIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "image_path": {
            "type": "string",
            "minLength": 1,
            "description": "Absolute local PNG, JPEG, or TIFF path.",
        },
        "plane": {
            "type": "string",
            "enum": ["xy", "xz", "yz"],
            "description": "Unique principal construction plane for this view.",
        },
        "width_expression": {
            "type": "string",
            "minLength": 1,
            "description": "Positive Fusion length expression for image width.",
        },
        "center_x_expression": {
            "type": "string",
            "minLength": 1,
            "default": "0 mm",
            "description": "Horizontal center offset in plane coordinates.",
        },
        "center_y_expression": {
            "type": "string",
            "minLength": 1,
            "default": "0 mm",
            "description": "Vertical center offset in plane coordinates.",
        },
        "opacity": {
            "type": "integer",
            "minimum": 0,
            "maximum": 100,
            "default": 50,
            "description": "Canvas opacity percentage.",
        },
        "flip_horizontal": {
            "type": "boolean",
            "default": False,
            "description": "Mirror this view horizontally.",
        },
        "flip_vertical": {
            "type": "boolean",
            "default": False,
            "description": "Mirror this view vertically.",
        },
    },
    "required": ["image_path", "plane", "width_expression"],
    "additionalProperties": False,
}


tool = (
    Tool.create_simple(
        name="create_orthographic_canvas_set",
        description=(
            "Atomically create two or three calibrated reference canvases on unique "
            "XY, XZ, or YZ planes after validating shared model dimensions."
        ),
    )
    .add_input_property(
        "name",
        {
            "type": "string",
            "minLength": 1,
            "description": "Base name used to generate <name>_<PLANE> canvas names.",
        },
    )
    .add_input_property(
        "views",
        {
            "type": "array",
            "minItems": 2,
            "maxItems": 3,
            "items": _VIEW_SCHEMA,
            "description": "Two or three unique principal orthographic views.",
        },
    )
    .add_input_property(
        "dimension_tolerance_mm",
        {
            "type": "number",
            "minimum": 0.001,
            "maximum": 10.0,
            "default": 0.25,
            "description": "Maximum allowed difference between shared dimensions.",
        },
    )
    .add_required_input("name")
    .add_required_input("views")
    .strict_schema()
)

register(Item.create_tool_item(tool=tool, handler=handler))
