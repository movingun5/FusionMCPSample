"""Atomic calibrated canvas sets for orthographic reference drawings."""

import hashlib
from pathlib import Path
import tempfile
import time
import traceback

from ..core.audit import AuditLogger
from ..core.errors import MCPError
from ..core.results import tool_success
from .canvases import CanvasValidation, add_prepared_canvas, prepare_reference_canvas
from .checkpoints import record_checkpoint
from .orthographic import (
    OrthographicValidation,
    compare_shared_dimensions,
    validate_orthographic_request,
)
from .snapshot import entity_token, safe_value


class _RecomputeFailure(RuntimeError):
    pass


def _default_audit_logger():
    path = Path(tempfile.gettempdir()) / "fusion-codex-mcp" / "audit.jsonl"
    return AuditLogger(path)


def _audit(logger, payload):
    try:
        logger.write(payload)
    except Exception:
        return False
    return True


def _error(code, message, retryable=False, details=None):
    return MCPError(
        code,
        message,
        retryable=retryable,
        details=details,
    ).to_result()


def _abort_transaction(app, started):
    if not started:
        return
    try:
        app.executeTextCommand("PTransaction.Abort")
    except Exception:
        pass


def _safe_prepared_view(prepared, canvas=None):
    result = {
        "name": prepared["name"],
        "image_name": prepared["image_name"],
        "image_size_bytes": prepared["image_size_bytes"],
        "plane": prepared["plane"],
        "width_expression": prepared["width_expression"],
        "center_x_expression": prepared["center_x_expression"],
        "center_y_expression": prepared["center_y_expression"],
        "width_mm": prepared["width_mm"],
        "height_mm": prepared["height_mm"],
        "center_mm": list(prepared["center_mm"]),
        "opacity": prepared["opacity"],
        "flip_horizontal": prepared["flip_horizontal"],
        "flip_vertical": prepared["flip_vertical"],
    }
    if canvas is not None:
        result["name"] = safe_value(canvas, "name", prepared["name"])
        result["entity_token"] = entity_token(canvas)
    return result


def _delete_created_canvases(created):
    for canvas in reversed(created):
        try:
            canvas.deleteMe()
        except Exception:
            pass


def create_orthographic_canvas_set(
    app,
    name,
    views,
    dimension_tolerance_mm=0.25,
    point_factory=None,
    vector_factory=None,
    audit_logger=None,
):
    """Create two or three calibrated principal-plane canvases atomically."""

    started_at = time.time()
    request_id = hashlib.sha256(
        f"{time.time_ns()}:{name}:orthographic-set".encode("utf-8")
    ).hexdigest()[:16]
    logger = audit_logger or _default_audit_logger()

    try:
        name, normalized_views, tolerance = validate_orthographic_request(
            name,
            views,
            dimension_tolerance_mm,
        )
    except OrthographicValidation as error:
        return _error(error.code, error.message, details=error.details)

    design = safe_value(app, "activeProduct") if app is not None else None
    root = safe_value(design, "rootComponent")
    if design is None or root is None:
        return _error(
            "NO_ACTIVE_DESIGN",
            "Open or create a Fusion design first.",
            retryable=True,
        )
    component = safe_value(design, "activeComponent") or root

    try:
        prepared = [
            prepare_reference_canvas(
                design,
                component,
                f"{name}_{view['plane'].upper()}",
                view["image_path"],
                view["plane"],
                view["width_expression"],
                center_x_expression=view["center_x_expression"],
                center_y_expression=view["center_y_expression"],
                opacity=view["opacity"],
                flip_horizontal=view["flip_horizontal"],
                flip_vertical=view["flip_vertical"],
                point_factory=point_factory,
                vector_factory=vector_factory,
            )
            for view in normalized_views
        ]
        axes_mm, checks = compare_shared_dimensions(prepared, tolerance)
    except (CanvasValidation, OrthographicValidation) as error:
        result = _error(
            error.code,
            error.message,
            retryable=getattr(error, "retryable", False),
            details=error.details,
        )
        _audit(
            logger,
            {
                "request_id": request_id,
                "mutation": "create_orthographic_canvas_set",
                "set_name": name,
                "planes": [view["plane"] for view in normalized_views],
                "result": result,
                "duration_ms": int((time.time() - started_at) * 1000),
            },
        )
        return result

    canvases = prepared[0]["canvases"]
    document = safe_value(app, "activeDocument")
    document_id = safe_value(document, "id") or safe_value(
        safe_value(design, "parentDocument"), "id"
    )
    starting_canvas_count = int(safe_value(canvases, "count", 0))
    base_audit = {
        "request_id": request_id,
        "mutation": "create_orthographic_canvas_set",
        "set_name": name,
        "views": [_safe_prepared_view(item) for item in prepared],
        "dimension_tolerance_mm": tolerance,
        "axes_mm": axes_mm,
        "shared_dimension_checks": checks,
    }
    transaction_started = False
    created = []
    try:
        if document is not None:
            app.executeTextCommand('PTransaction.Start "Codex Orthographic Canvas Set"')
            transaction_started = True
        for item in prepared:
            created.append(add_prepared_canvas(canvases, item))
        if design.computeAll() is False:
            raise _RecomputeFailure(
                "Fusion could not recompute the design after creating the canvas set."
            )
        if transaction_started:
            app.executeTextCommand("PTransaction.Commit")

        checkpoint_canvases = [
            {
                "name": safe_value(canvas, "name", item["name"]),
                "entity_token": entity_token(canvas),
            }
            for item, canvas in zip(prepared, created)
        ]
        record_checkpoint(
            {
                "request_id": request_id,
                "mutation": "create_orthographic_canvas_set",
                "document_id": document_id,
                "component_entity_token": entity_token(component),
                "set_name": name,
                "starting_canvas_count": starting_canvas_count,
                "canvases": checkpoint_canvases,
            }
        )
        payload = {
            "action": "created",
            "set": {
                "name": name,
                "views": [
                    _safe_prepared_view(item, canvas)
                    for item, canvas in zip(prepared, created)
                ],
                "axes_mm": axes_mm,
                "dimension_tolerance_mm": tolerance,
            },
            "shared_dimension_checks": checks,
            "recomputed": True,
            "checkpoint_recorded": True,
        }
        payload["audit_logged"] = _audit(
            logger,
            {
                **base_audit,
                "result": payload,
                "duration_ms": int((time.time() - started_at) * 1000),
            },
        )
        return tool_success(payload)
    except Exception as error:
        _abort_transaction(app, transaction_started)
        _delete_created_canvases(created)
        code = (
            "RECOMPUTE_FAILED"
            if isinstance(error, _RecomputeFailure)
            else "CANVAS_SET_WRITE_FAILED"
        )
        message = (
            str(error)
            if isinstance(error, _RecomputeFailure)
            else "Fusion could not create the orthographic canvas set."
        )
        result = _error(
            code,
            message,
            retryable=True,
            details={
                "set_name": name,
                "created_count": len(created),
                "undo_result": (
                    "transaction_aborted_and_canvases_deleted"
                    if transaction_started
                    else "canvases_deleted"
                ),
            },
        )
        _audit(
            logger,
            {
                **base_audit,
                "result": result,
                "local_traceback": traceback.format_exc(),
                "duration_ms": int((time.time() - started_at) * 1000),
            },
        )
        return result
