"""Structured errors returned by Codex-facing MCP tools."""


class MCPError(Exception):
    """An error with a stable machine-readable code."""

    def __init__(self, code, message, retryable=False, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = bool(retryable)
        self.details = details or {}

    def to_dict(self):
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details,
        }

    def to_result(self):
        return {
            "isError": True,
            "error": self.to_dict(),
            "content": [{"type": "text", "text": f"{self.code}: {self.message}"}],
        }
