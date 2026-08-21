"""Undo adapter for the most recent executor checkpoint."""

from ..core.errors import MCPError
from .snapshot import safe_value


def undo_with(app, checkpoint):
    if app is None:
        return MCPError("FUSION_UNAVAILABLE", "Fusion 360 is not available.", True).to_result()
    if not checkpoint:
        return MCPError(
            "NO_EXECUTION_CHECKPOINT",
            "There is no successful Codex execution to undo.",
        ).to_result()

    document = safe_value(app, "activeDocument")
    if safe_value(document, "id") != checkpoint.get("document_id"):
        return MCPError(
            "CHECKPOINT_DOCUMENT_MISMATCH",
            "The active document is not the document associated with the checkpoint.",
            retryable=True,
        ).to_result()
    design = safe_value(app, "activeProduct")
    if design is None:
        return MCPError("NO_ACTIVE_DESIGN", "Open the checkpoint design first.", True).to_result()

    try:
        app.executeTextCommand("Commands.Start UndoCommand")
        recomputed = design.computeAll()
        if recomputed is False:
            return MCPError(
                "RECOMPUTE_FAILED",
                "Fusion undo completed but the design did not recompute cleanly.",
                retryable=True,
            ).to_result()
        return {
            "isError": False,
            "message": "The most recent Codex Fusion execution was undone.",
            "undone_request_id": checkpoint.get("request_id"),
            "content": [{"type": "text", "text": "Undo completed and the design recomputed."}],
        }
    except Exception as exception:
        return MCPError("FUSION_API_ERROR", str(exception), retryable=True).to_result()
