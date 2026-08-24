"""Undo adapter for the most recent executor checkpoint."""

from ..core.errors import MCPError
from .snapshot import entity_token, iter_collection, safe_value


def _error(code, message, retryable=False):
    return MCPError(code, message, retryable=retryable).to_result()


def _abort_transaction(app, started):
    if not started:
        return
    try:
        app.executeTextCommand("PTransaction.Abort")
    except Exception:
        pass


def _undo_reference_canvas(app, design, document, checkpoint):
    root = safe_value(design, "rootComponent")
    component = safe_value(design, "activeComponent") or root
    expected_component = checkpoint.get("component_entity_token")
    if expected_component and entity_token(component) != expected_component:
        return _error(
            "CHECKPOINT_COMPONENT_MISMATCH",
            "The active component is not the component associated with the canvas checkpoint.",
            retryable=True,
        )
    canvases = safe_value(component, "canvases")
    expected_token = checkpoint.get("canvas_entity_token")
    expected_name = checkpoint.get("canvas_name")
    canvas = None
    for candidate in iter_collection(canvases):
        if expected_token and entity_token(candidate) == expected_token:
            canvas = candidate
            break
        if not expected_token and expected_name and safe_value(candidate, "name") == expected_name:
            canvas = candidate
            break
    if canvas is None:
        return _error(
            "CHECKPOINT_ENTITY_NOT_FOUND",
            "The reference canvas associated with the checkpoint was not found.",
            retryable=True,
        )

    transaction_started = False
    try:
        if document is not None:
            app.executeTextCommand('PTransaction.Start "Codex Undo Reference Canvas"')
            transaction_started = True
        if canvas.deleteMe() is False:
            raise RuntimeError("Fusion rejected the reference canvas deletion.")
        if design.computeAll() is False:
            raise RuntimeError("Fusion could not recompute after deleting the canvas.")
        if transaction_started:
            app.executeTextCommand("PTransaction.Commit")
        return {
            "isError": False,
            "message": "The most recent Codex reference canvas was removed.",
            "undone_request_id": checkpoint.get("request_id"),
            "undo_mode": "canvas_deleted",
            "content": [
                {
                    "type": "text",
                    "text": "Reference canvas removed and the design recomputed.",
                }
            ],
        }
    except Exception:
        _abort_transaction(app, transaction_started)
        return _error(
            "FUSION_API_ERROR",
            "Fusion could not remove the checkpoint reference canvas.",
            retryable=True,
        )


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

    if checkpoint.get("mutation") == "create_reference_canvas":
        return _undo_reference_canvas(app, design, document, checkpoint)

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
