"""Fusion API adapters kept separate from MCP transport concerns."""

from .context import build_design_context, get_status
from .snapshot import capture_snapshot, compare_snapshots

__all__ = ["build_design_context", "get_status", "capture_snapshot", "compare_snapshots"]
