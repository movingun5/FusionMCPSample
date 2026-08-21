"""Codex-oriented risk-gated arbitrary Fusion Python MCP tool."""

import adsk.core

from ..fusion.executor import execute_code
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ..mcp_primitives.tool import Tool


def handler(intent, code, expected_changes):
    app = adsk.core.Application.get()
    ui = app.userInterface if app else None
    return execute_code(app, ui, intent, code, expected_changes)


tool = Tool.create_simple(
    name="execute_fusion_python",
    description=(
        "Execute a Python module defining run(context) inside Fusion. The server independently "
        "classifies risk, requires Fusion UI approval for destructive or external effects, "
        "recomputes the design, and compares expected_changes with actual geometry changes. "
        "Static classification reduces risk but is not a complete sandbox."
    ),
).add_input_property(
    "intent",
    {"type": "string", "minLength": 1, "description": "Short description of the requested CAD change."},
).add_required_input("intent").add_input_property(
    "code",
    {"type": "string", "minLength": 1, "description": "Python source defining run(context)."},
).add_required_input("code").add_input_property(
    "expected_changes",
    {
        "type": "object",
        "description": "Expected count deltas such as features_created or bodies_created.",
        "additionalProperties": True,
    },
).add_required_input("expected_changes").strict_schema()

register(Item.create_tool_item(tool=tool, handler=handler))
