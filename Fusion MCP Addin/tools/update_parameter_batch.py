"""MCP tool for atomic updates to existing Fusion parameters."""

import adsk.core

from ..fusion.parameter_batch import update_parameter_batch
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ..mcp_primitives.tool import Tool


def handler(updates):
    return update_parameter_batch(adsk.core.Application.get(), updates)


_USER_UPDATE = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["user"]},
        "name": {"type": "string", "minLength": 1},
        "expression": {"type": "string", "minLength": 1},
        "expected_old_expression": {"type": "string", "minLength": 1},
    },
    "required": ["kind", "name", "expression", "expected_old_expression"],
    "additionalProperties": False,
}
_MODEL_UPDATE = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["model"]},
        "feature_name": {"type": "string", "minLength": 1},
        "role": {"type": "string", "minLength": 1},
        "expression": {"type": "string", "minLength": 1},
        "expected_old_expression": {"type": "string", "minLength": 1},
    },
    "required": [
        "kind",
        "feature_name",
        "role",
        "expression",
        "expected_old_expression",
    ],
    "additionalProperties": False,
}


tool = (
    Tool.create_simple(
        name="update_parameter_batch",
        description=(
            "Atomically update one through sixteen existing Fusion user or model "
            "parameters after validating every target, old expression, and new expression."
        ),
    )
    .add_input_property(
        "updates",
        {
            "type": "array",
            "minItems": 1,
            "maxItems": 16,
            "items": {"oneOf": [_USER_UPDATE, _MODEL_UPDATE]},
        },
    )
    .add_required_input("updates")
    .strict_schema()
)

register(Item.create_tool_item(tool=tool, handler=handler))
