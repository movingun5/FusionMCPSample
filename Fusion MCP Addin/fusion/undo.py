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


def _undo_reference_canvas_set(app, design, document, checkpoint):
    root = safe_value(design, "rootComponent")
    component = safe_value(design, "activeComponent") or root
    expected_component = checkpoint.get("component_entity_token")
    if expected_component and entity_token(component) != expected_component:
        return _error(
            "CHECKPOINT_COMPONENT_MISMATCH",
            "The active component is not the component associated with the canvas-set checkpoint.",
            retryable=True,
        )
    canvases = safe_value(component, "canvases")
    expected_canvases = checkpoint.get("canvases")
    if canvases is None or not isinstance(expected_canvases, list) or not expected_canvases:
        return _error(
            "CHECKPOINT_ENTITY_NOT_FOUND",
            "The orthographic canvases associated with the checkpoint were not found.",
            retryable=True,
        )

    candidates = list(iter_collection(canvases))
    resolved = []
    resolved_ids = set()
    for expected in expected_canvases:
        if not isinstance(expected, dict):
            return _error(
                "CHECKPOINT_ENTITY_NOT_FOUND",
                "The orthographic canvas checkpoint is incomplete.",
                retryable=True,
            )
        expected_token = expected.get("entity_token")
        expected_name = expected.get("name")
        target = next(
            (
                candidate
                for candidate in candidates
                if (
                    expected_token
                    and entity_token(candidate) == expected_token
                )
                or (
                    not expected_token
                    and expected_name
                    and safe_value(candidate, "name") == expected_name
                )
            ),
            None,
        )
        target_id = id(target) if target is not None else None
        if target is None or target_id in resolved_ids:
            return _error(
                "CHECKPOINT_ENTITY_NOT_FOUND",
                "Every orthographic canvas in the checkpoint must still exist before Undo.",
                retryable=True,
            )
        resolved.append(target)
        resolved_ids.add(target_id)

    transaction_started = False
    try:
        if document is not None:
            app.executeTextCommand(
                'PTransaction.Start "Codex Undo Orthographic Canvas Set"'
            )
            transaction_started = True
        for canvas in reversed(resolved):
            if canvas.deleteMe() is False:
                raise RuntimeError("Fusion rejected an orthographic canvas deletion.")
        if design.computeAll() is False:
            raise RuntimeError("Fusion could not recompute after deleting the canvas set.")
        canvas_count = int(safe_value(canvases, "count", 0))
        starting_canvas_count = checkpoint.get("starting_canvas_count")
        if (
            isinstance(starting_canvas_count, int)
            and canvas_count != starting_canvas_count
        ):
            raise RuntimeError("The canvas collection did not return to its checkpoint count.")
        if transaction_started:
            app.executeTextCommand("PTransaction.Commit")
        return {
            "isError": False,
            "message": "The most recent Codex orthographic canvas set was removed.",
            "undone_request_id": checkpoint.get("request_id"),
            "undo_mode": "canvas_set_deleted",
            "canvas_count": canvas_count,
            "content": [
                {
                    "type": "text",
                    "text": "Orthographic canvas set removed and the design recomputed.",
                }
            ],
        }
    except Exception:
        _abort_transaction(app, transaction_started)
        return _error(
            "FUSION_API_ERROR",
            "Fusion could not remove the checkpoint orthographic canvas set.",
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

    if checkpoint.get("mutation") == "create_orthographic_canvas_set":
        return _undo_reference_canvas_set(app, design, document, checkpoint)
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
