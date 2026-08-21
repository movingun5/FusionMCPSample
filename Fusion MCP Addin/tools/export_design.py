"""MCP tool for verified STEP and STL exports."""

import adsk.core

from ..fusion.exporting import export_with
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ..mcp_primitives.tool import Tool


def handler(format, path, entity_token=None, overwrite=False):
    app = adsk.core.Application.get()
    ui = app.userInterface if app else None
    return export_with(app, ui, format, path, entity_token=entity_token, overwrite=overwrite)


tool = Tool.create_simple(
    name="export_design",
    description=(
        "Export the active component or an entity token as STEP or STL and verify the file. "
        "Writing a new file is automatic; overwriting an existing file requires Fusion approval."
    ),
).add_input_property(
    "format",
    {"type": "string", "enum": ["step", "stl"]},
).add_required_input("format").add_input_property(
    "path",
    {"type": "string", "minLength": 1, "description": "Absolute output path with matching extension."},
).add_required_input("path").add_input_property(
    "entity_token",
    {"type": ["string", "null"], "default": None},
).add_input_property(
    "overwrite",
    {"type": "boolean", "default": False},
).strict_schema()

register(Item.create_tool_item(tool=tool, handler=handler))
