"""MCP tool for safe updates to feature-owned model parameters."""

import adsk.core

from ..fusion.model_parameters import update_model_parameter
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ..mcp_primitives.tool import Tool


def handler(feature_name, role, expression, expected_old_expression):
    return update_model_parameter(
        adsk.core.Application.get(),
        feature_name,
        role,
        expression,
        expected_old_expression,
    )


tool = (
    Tool.create_simple(
        name="update_model_parameter",
        description=(
            "Update one existing Fusion model parameter by exact feature name and "
            "parameter role, refusing stale or ambiguous edits."
        ),
    )
    .add_input_property(
        "feature_name",
        {
            "type": "string",
            "minLength": 1,
            "description": "Exact owning feature name from get_design_context.",
        },
    )
    .add_input_property(
        "role",
        {
            "type": "string",
            "minLength": 1,
            "description": "Model-parameter role from get_design_context, such as Distance.",
        },
    )
    .add_input_property(
        "expression",
        {
            "type": "string",
            "minLength": 1,
            "description": "New Fusion expression compatible with the current parameter unit.",
        },
    )
    .add_input_property(
        "expected_old_expression",
        {
            "type": "string",
            "minLength": 1,
            "description": "Exact current expression required before the edit is applied.",
        },
    )
    .add_required_input("feature_name")
    .add_required_input("role")
    .add_required_input("expression")
    .add_required_input("expected_old_expression")
    .strict_schema()
)

register(Item.create_tool_item(tool=tool, handler=handler))
