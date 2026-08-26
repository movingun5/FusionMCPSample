"""MCP tool for preflighting a drawing-derived modeling plan."""

from ..core.errors import MCPError
from ..core.results import tool_success
from ..fusion.drawing_plan import (
    DrawingPlanValidation,
    validate_drawing_modeling_plan,
)
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ..mcp_primitives.tool import Tool


def handler(
    name,
    parameter_prefix,
    views,
    geometry,
    dimension_tolerance_mm=0.25,
    unsupported_features=None,
):
    try:
        return tool_success(
            validate_drawing_modeling_plan(
                name,
                parameter_prefix,
                views,
                geometry,
                dimension_tolerance_mm,
                unsupported_features,
            )
        )
    except DrawingPlanValidation as error:
        return MCPError(
            error.code,
            error.message,
            retryable=False,
            details=error.details,
        ).to_result()


_NULLABLE_NUMBER = {"type": ["number", "null"]}
_SOURCE_SCHEMA = {"type": "string", "enum": ["stated", "estimated", "missing"]}
_VIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "plane": {"type": "string", "enum": ["xy", "xz", "yz"]},
        "width_mm": {**_NULLABLE_NUMBER, "description": "Horizontal model dimension in mm."},
        "height_mm": {**_NULLABLE_NUMBER, "description": "Vertical model dimension in mm."},
        "width_source": {
            **_SOURCE_SCHEMA,
            "description": "Whether width is explicitly stated, visually estimated, or missing.",
        },
        "height_source": {
            **_SOURCE_SCHEMA,
            "description": "Whether height is explicitly stated, visually estimated, or missing.",
        },
    },
    "required": ["plane", "width_mm", "height_mm", "width_source", "height_source"],
    "additionalProperties": False,
}
_HOLE_SCHEMA = {
    "type": "object",
    "properties": {
        "key": {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]*$"},
        "x_mm": _NULLABLE_NUMBER,
        "y_mm": _NULLABLE_NUMBER,
        "diameter_mm": _NULLABLE_NUMBER,
    },
    "required": ["key", "x_mm", "y_mm", "diameter_mm"],
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
                "size_mm": _NULLABLE_NUMBER,
            },
            "required": ["type", "size_mm"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["chamfer"]},
                "size_mm": _NULLABLE_NUMBER,
            },
            "required": ["type", "size_mm"],
            "additionalProperties": False,
        },
    ]
}
_PLATE_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["plate"]},
        "width_mm": _NULLABLE_NUMBER,
        "height_mm": _NULLABLE_NUMBER,
        "thickness_mm": _NULLABLE_NUMBER,
        "holes": {"type": "array", "minItems": 0, "maxItems": 32, "items": _HOLE_SCHEMA},
        "edge_finish": _EDGE_FINISH_SCHEMA,
    },
    "required": ["type", "width_mm", "height_mm", "thickness_mm", "holes", "edge_finish"],
    "additionalProperties": False,
}
_VERTEX_SCHEMA = {
    "type": "object",
    "properties": {
        "key": {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]*$"},
        "x_mm": _NULLABLE_NUMBER,
        "y_mm": _NULLABLE_NUMBER,
    },
    "required": ["key", "x_mm", "y_mm"],
    "additionalProperties": False,
}
_PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["straight_profile"]},
        "vertices": {"type": "array", "minItems": 3, "maxItems": 32, "items": _VERTEX_SCHEMA},
        "depth_mm": _NULLABLE_NUMBER,
    },
    "required": ["type", "vertices", "depth_mm"],
    "additionalProperties": False,
}


tool = (
    Tool.create_simple(
        name="validate_drawing_modeling_plan",
        description=(
            "Validate dimensions extracted by Codex from one to three drawing views, "
            "separate stated evidence from estimates or missing values, and return a "
            "normalized explicit plate or straight-profile tool call without mutating Fusion."
        ),
    )
    .add_input_property("name", {"type": "string", "minLength": 1})
    .add_input_property(
        "parameter_prefix",
        {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]*$"},
    )
    .add_input_property(
        "views",
        {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": _VIEW_SCHEMA,
            "description": "Principal views with millimeter dimensions and evidence source.",
        },
    )
    .add_input_property(
        "geometry",
        {
            "oneOf": [_PLATE_SCHEMA, _PROFILE_SCHEMA],
            "description": "Structured geometry extracted from the drawing; null marks missing dimensions.",
        },
    )
    .add_input_property(
        "dimension_tolerance_mm",
        {"type": "number", "exclusiveMinimum": 0, "maximum": 10.0, "default": 0.25},
    )
    .add_input_property(
        "unsupported_features",
        {
            "type": "array",
            "maxItems": 16,
            "items": {"type": "string", "minLength": 1},
            "default": [],
            "description": "Visible features that have no approved explicit modeling route.",
        },
    )
    .add_required_input("name")
    .add_required_input("parameter_prefix")
    .add_required_input("views")
    .add_required_input("geometry")
    .strict_schema()
)

register(Item.create_tool_item(tool=tool, handler=handler))
