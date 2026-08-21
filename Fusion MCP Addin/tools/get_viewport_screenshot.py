"""Codex-facing screenshot tool with conventional view names."""

from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ..mcp_primitives.tool import Tool
from .get_screenshot import handler as legacy_screenshot


_VIEW_ALIASES = {"isometric": "iso-top-left"}
_VIEWS = ["current", "isometric", "top", "bottom", "front", "back", "left", "right"]


def handler(view="isometric", width=768, height=768):
    if view not in _VIEWS:
        return {
            "isError": True,
            "error": {"code": "INVALID_REQUEST", "message": f"unsupported view: {view}", "retryable": False},
            "content": [{"type": "text", "text": f"unsupported view: {view}"}],
        }
    if not isinstance(width, int) or isinstance(width, bool) or not 1 <= width <= 4096:
        return {
            "isError": True,
            "error": {"code": "INVALID_REQUEST", "message": "width must be 1 through 4096", "retryable": False},
            "content": [{"type": "text", "text": "width must be 1 through 4096"}],
        }
    if not isinstance(height, int) or isinstance(height, bool) or not 1 <= height <= 4096:
        return {
            "isError": True,
            "error": {"code": "INVALID_REQUEST", "message": "height must be 1 through 4096", "retryable": False},
            "content": [{"type": "text", "text": "height must be 1 through 4096"}],
        }
    result = legacy_screenshot(_VIEW_ALIASES.get(view, view), width, height)
    if not result.get("isError"):
        result["screenshot"] = {
            "view": view,
            "width": width,
            "height": height,
            "mime_type": "image/png",
        }
    return result


tool = Tool.create_simple(
    name="get_viewport_screenshot",
    description=(
        "Capture the current Fusion viewport or a named orthographic/isometric view. "
        "Use after geometry changes and compare the image with numeric design context."
    ),
).add_input_property(
    "view",
    {"type": "string", "enum": _VIEWS, "default": "isometric"},
).add_input_property(
    "width",
    {"type": "integer", "minimum": 1, "maximum": 4096, "default": 768},
).add_input_property(
    "height",
    {"type": "integer", "minimum": 1, "maximum": 4096, "default": 768},
).strict_schema()

register(Item.create_tool_item(tool=tool, handler=handler))
