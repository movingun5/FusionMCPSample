"""MCP tool for a calibrated local reference-image canvas."""

import adsk.core

from ..fusion.canvases import create_reference_canvas
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ..mcp_primitives.tool import Tool


def handler(
    name,
    image_path,
    plane,
    width_expression,
    center_x_expression="0 mm",
    center_y_expression="0 mm",
    opacity=50,
    flip_horizontal=False,
    flip_vertical=False,
):
    return create_reference_canvas(
        adsk.core.Application.get(),
        name,
        image_path,
        plane,
        width_expression,
        center_x_expression,
        center_y_expression,
        opacity,
        flip_horizontal,
        flip_vertical,
    )


tool = (
    Tool.create_simple(
        name="create_reference_canvas",
        description=(
            "Create a named Fusion reference canvas from an existing absolute local "
            "PNG, JPEG, or TIFF path. Calibrate its physical width, preserve the "
            "image aspect ratio, and place it on an XY, XZ, or YZ construction plane."
        ),
    )
    .add_input_property(
        "name",
        {
            "type": "string",
            "minLength": 1,
            "description": "Unique canvas name in the active component.",
        },
    )
    .add_input_property(
        "image_path",
        {
            "type": "string",
            "minLength": 1,
            "description": (
                "Absolute local path to a PNG, JPEG, or TIFF image no larger than 25 MiB."
            ),
        },
    )
    .add_input_property(
        "plane",
        {
            "type": "string",
            "enum": ["xy", "xz", "yz"],
            "description": "Principal construction plane that receives the canvas.",
        },
    )
    .add_input_property(
        "width_expression",
        {
            "type": "string",
            "minLength": 1,
            "description": "Positive Fusion length expression for calibrated image width.",
        },
    )
    .add_input_property(
        "center_x_expression",
        {
            "type": "string",
            "minLength": 1,
            "default": "0 mm",
            "description": "Horizontal canvas-center offset in plane coordinates.",
        },
    )
    .add_input_property(
        "center_y_expression",
        {
            "type": "string",
            "minLength": 1,
            "default": "0 mm",
            "description": "Vertical canvas-center offset in plane coordinates.",
        },
    )
    .add_input_property(
        "opacity",
        {
            "type": "integer",
            "minimum": 0,
            "maximum": 100,
            "default": 50,
            "description": "Canvas opacity percentage.",
        },
    )
    .add_input_property(
        "flip_horizontal",
        {
            "type": "boolean",
            "default": False,
            "description": "Mirror the image horizontally in plane coordinates.",
        },
    )
    .add_input_property(
        "flip_vertical",
        {
            "type": "boolean",
            "default": False,
            "description": "Mirror the image vertically in plane coordinates.",
        },
    )
    .add_required_input("name")
    .add_required_input("image_path")
    .add_required_input("plane")
    .add_required_input("width_expression")
    .strict_schema()
)

register(Item.create_tool_item(tool=tool, handler=handler))
