"""Pure-Python contracts shared by the Fusion MCP add-in."""

from .errors import MCPError
from .policy import RiskDecision, classify_code

__all__ = ["MCPError", "RiskDecision", "classify_code"]
