"""Calibrated local reference-image canvases for Fusion MCP tools."""

import hashlib
import math
from pathlib import Path
import tempfile
import time
import traceback

from ..core.audit import AuditLogger
from ..core.errors import MCPError
from ..core.results import tool_success
from .checkpoints import record_checkpoint
from .snapshot import entity_token, safe_value


_ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
_MAX_IMAGE_BYTES = 25 * 1024 * 1024
_PLANES = {
    "xy": "xYConstructionPlane",
    "xz": "xZConstructionPlane",
    "yz": "yZConstructionPlane",
}


class _RecomputeFailure(RuntimeError):
    pass


class CanvasValidation(ValueError):
    def __init__(self, code, message, retryable=False, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = bool(retryable)
        self.details = details or {}


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


def _geometry_factories(point_factory, vector_factory):
    if point_factory is not None and vector_factory is not None:
        return point_factory, vector_factory

    import adsk.core

    return (
        point_factory or adsk.core.Point2D.create,
        vector_factory or adsk.core.Vector2D.create,
    )


def _validate_image_path(image_path):
    if not isinstance(image_path, str) or not image_path.strip():
        return None, _error(
            "IMAGE_PATH_INVALID",
            "image_path must be a non-empty absolute local file path.",
        )
    candidate = Path(image_path.strip())
    if not candidate.is_absolute():
        return None, _error(
            "IMAGE_PATH_INVALID",
            "image_path must be an absolute local file path.",
        )
    if candidate.suffix.lower() not in _ALLOWED_EXTENSIONS:
        return None, _error(
            "IMAGE_FORMAT_UNSUPPORTED",
            "The reference image must be PNG, JPEG, or TIFF.",
            details={"image_name": candidate.name},
        )
    try:
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, OSError):
        return None, _error(
            "IMAGE_NOT_FOUND",
            "The reference image file was not found.",
            details={"image_name": candidate.name},
        )
    if not resolved.is_file():
        return None, _error(
            "IMAGE_NOT_FOUND",
            "The reference image path must identify a regular file.",
            details={"image_name": candidate.name},
        )
    try:
        size_bytes = resolved.stat().st_size
    except OSError:
        return None, _error(
            "IMAGE_NOT_FOUND",
            "The reference image file could not be inspected.",
            details={"image_name": candidate.name},
        )
    if size_bytes > _MAX_IMAGE_BYTES:
        return None, _error(
            "IMAGE_TOO_LARGE",
            "The reference image must not exceed 25 MiB.",
            details={"image_name": candidate.name, "size_bytes": size_bytes},
        )
    return (resolved, size_bytes), None


def _evaluate_length(units_manager, expression, target_unit):
    return float(units_manager.evaluateExpression(expression, target_unit))


def _raise_result_error(result):
    error = result["error"]
    raise CanvasValidation(
        error["code"],
        error["message"],
        retryable=error["retryable"],
        details=error["details"],
    )


def prepare_reference_canvas(
    design,
    component,
    name,
    image_path,
    plane,
    width_expression,
    center_x_expression="0 mm",
    center_y_expression="0 mm",
    opacity=50,
    flip_horizontal=False,
    flip_vertical=False,
    point_factory=None,
    vector_factory=None,
):
    """Validate and calibrate one canvas input without adding it to Fusion."""

    string_fields = {
        "name": name,
        "width_expression": width_expression,
        "center_x_expression": center_x_expression,
        "center_y_expression": center_y_expression,
    }
    for field, value in string_fields.items():
        if not isinstance(value, str) or not value.strip():
            raise CanvasValidation(
                "INVALID_REQUEST",
                f"{field} must be a non-empty string.",
            )
    if plane not in _PLANES:
        raise CanvasValidation(
            "INVALID_REQUEST",
            "plane must be one of: xy, xz, yz.",
            details={"plane": plane},
        )
    if (
        not isinstance(opacity, int)
        or isinstance(opacity, bool)
        or not 0 <= opacity <= 100
    ):
        raise CanvasValidation(
            "INVALID_REQUEST",
            "opacity must be an integer from 0 through 100.",
        )
    if not isinstance(flip_horizontal, bool) or not isinstance(flip_vertical, bool):
        raise CanvasValidation(
            "INVALID_REQUEST",
            "flip_horizontal and flip_vertical must be booleans.",
        )

    image, image_error = _validate_image_path(image_path)
    if image_error is not None:
        _raise_result_error(image_error)
    resolved_image, image_size = image
    name = name.strip()
    width_expression = width_expression.strip()
    center_x_expression = center_x_expression.strip()
    center_y_expression = center_y_expression.strip()

    if design is None or component is None:
        raise CanvasValidation(
            "NO_ACTIVE_DESIGN",
            "Open or create a Fusion design first.",
            retryable=True,
        )
    canvases = safe_value(component, "canvases")
    units_manager = safe_value(design, "unitsManager")
    construction_plane = safe_value(component, _PLANES[plane])
    if canvases is None or units_manager is None or construction_plane is None:
        raise CanvasValidation(
            "FUSION_API_ERROR",
            "The active component does not expose canvases, units, or the requested plane.",
            retryable=True,
        )
    if safe_value(canvases, "itemByName") is not None:
        existing = canvases.itemByName(name)
    else:
        existing = next(
            (item for item in canvases if safe_value(item, "name") == name),
            None,
        )
    if existing is not None:
        raise CanvasValidation(
            "CANVAS_NAME_CONFLICT",
            "A canvas with the requested name already exists.",
            details={"name": name},
        )

    target_unit = safe_value(units_manager, "defaultLengthUnits", "mm")
    expressions = (
        ("width_expression", width_expression),
        ("center_x_expression", center_x_expression),
        ("center_y_expression", center_y_expression),
    )
    values = {}
    try:
        for field, expression in expressions:
            values[field] = _evaluate_length(units_manager, expression, target_unit)
    except Exception as error:
        raise CanvasValidation(
            "CANVAS_EXPRESSION_INVALID",
            "Fusion could not evaluate one of the canvas length expressions.",
            details={"unit": target_unit},
        ) from error
    if not all(math.isfinite(value) for value in values.values()):
        raise CanvasValidation(
            "CANVAS_EXPRESSION_INVALID",
            "Canvas length expressions must evaluate to finite values.",
            details={"unit": target_unit},
        )
    width = values["width_expression"]
    if width <= 1e-9:
        raise CanvasValidation(
            "CANVAS_WIDTH_INVALID",
            "Canvas width must be greater than zero.",
            details={"width_expression": width_expression},
        )

    point_factory, vector_factory = _geometry_factories(
        point_factory,
        vector_factory,
    )
    try:
        canvas_input = canvases.createInput(str(resolved_image), construction_plane)
        if canvas_input is None:
            raise RuntimeError("Fusion did not create a canvas input.")
        transform = safe_value(canvas_input, "transform")
        if transform is None:
            raise RuntimeError("Fusion did not provide the canvas transform.")
        _, default_x, default_y = transform.getAsCoordinateSystem()
        x_length = float(safe_value(default_x, "length", 0.0))
        y_length = float(safe_value(default_y, "length", 0.0))
        if not math.isfinite(x_length) or not math.isfinite(y_length) or y_length <= 0:
            raise RuntimeError("Fusion returned an invalid image aspect ratio.")
        aspect_ratio = x_length / y_length
        if aspect_ratio <= 0:
            raise RuntimeError("Fusion returned an invalid image aspect ratio.")
        height = width / aspect_ratio
        x_sign = -1.0 if flip_horizontal else 1.0
        y_sign = -1.0 if flip_vertical else 1.0
        origin = point_factory(
            values["center_x_expression"],
            values["center_y_expression"],
        )
        x_axis = vector_factory(x_sign * width, 0.0)
        y_axis = vector_factory(0.0, y_sign * height)
        if transform.setWithCoordinateSystem(origin, x_axis, y_axis) is False:
            raise RuntimeError("Fusion rejected the calibrated canvas transform.")
        canvas_input.transform = transform
        canvas_input.opacity = opacity
        canvas_input.isSelectable = True
        canvas_input.isDisplayedThrough = True
        canvas_input.isRenderable = False
    except CanvasValidation:
        raise
    except Exception as error:
        raise CanvasValidation(
            "CANVAS_PREPARATION_FAILED",
            "Fusion could not prepare the reference canvas.",
            retryable=True,
            details={"name": name, "image_name": resolved_image.name, "plane": plane},
        ) from error

    return {
        "name": name,
        "image_name": resolved_image.name,
        "image_size_bytes": image_size,
        "plane": plane,
        "width_expression": width_expression,
        "center_x_expression": center_x_expression,
        "center_y_expression": center_y_expression,
        "width_mm": round(width * 10.0, 6),
        "height_mm": round(height * 10.0, 6),
        "center_mm": [
            round(values["center_x_expression"] * 10.0, 6),
            round(values["center_y_expression"] * 10.0, 6),
        ],
        "opacity": opacity,
        "flip_horizontal": flip_horizontal,
        "flip_vertical": flip_vertical,
        "canvas_input": canvas_input,
        "component": component,
        "canvases": canvases,
    }


def add_prepared_canvas(canvases, prepared):
    """Add one already-validated canvas input and assign its stable name."""

    canvas = canvases.add(prepared["canvas_input"])
    if canvas is None:
        raise RuntimeError("Fusion did not create the reference canvas.")
    canvas.name = prepared["name"]
    return canvas


def create_reference_canvas(
    app,
    name,
    image_path,
    plane,
    width_expression,
    center_x_expression="0 mm",
    center_y_expression="0 mm",
    opacity=50,
    flip_horizontal=False,
    flip_vertical=False,
    point_factory=None,
    vector_factory=None,
    audit_logger=None,
):
    """Create one aspect-preserving, physically calibrated principal-plane canvas."""

    started_at = time.time()
    request_id = hashlib.sha256(
        f"{time.time_ns()}:{name}:{plane}".encode("utf-8")
    ).hexdigest()[:16]
    logger = audit_logger or _default_audit_logger()

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
        prepared = prepare_reference_canvas(
            design,
            component,
            name,
            image_path,
            plane,
            width_expression,
            center_x_expression=center_x_expression,
            center_y_expression=center_y_expression,
            opacity=opacity,
            flip_horizontal=flip_horizontal,
            flip_vertical=flip_vertical,
            point_factory=point_factory,
            vector_factory=vector_factory,
        )
    except CanvasValidation as error:
        if error.code == "CANVAS_PREPARATION_FAILED":
            return _error(
                "CANVAS_WRITE_FAILED",
                "Fusion could not create the reference canvas.",
                retryable=True,
                details=error.details,
            )
        return _error(
            error.code,
            error.message,
            retryable=error.retryable,
            details=error.details,
        )

    name = prepared["name"]
    canvases = prepared["canvases"]
    base_audit = {
        "request_id": request_id,
        "mutation": "create_reference_canvas",
        "name": name,
        "image_name": prepared["image_name"],
        "image_size_bytes": prepared["image_size_bytes"],
        "plane": prepared["plane"],
        "width_expression": prepared["width_expression"],
        "center_x_expression": prepared["center_x_expression"],
        "center_y_expression": prepared["center_y_expression"],
        "opacity": prepared["opacity"],
        "flip_horizontal": prepared["flip_horizontal"],
        "flip_vertical": prepared["flip_vertical"],
    }
    document = safe_value(app, "activeDocument")
    timeline = safe_value(design, "timeline")
    document_id = safe_value(document, "id") or safe_value(
        safe_value(design, "parentDocument"), "id"
    )
    timeline_marker = safe_value(timeline, "markerPosition")
    transaction_started = False
    canvas = None
    try:
        if document is not None:
            app.executeTextCommand('PTransaction.Start "Codex Reference Canvas"')
            transaction_started = True
        canvas = add_prepared_canvas(canvases, prepared)
        if design.computeAll() is False:
            raise _RecomputeFailure(
                "Fusion could not recompute the design after creating the canvas."
            )
        if transaction_started:
            app.executeTextCommand("PTransaction.Commit")

        record_checkpoint(
            {
                "request_id": request_id,
                "mutation": "create_reference_canvas",
                "document_id": document_id,
                "timeline_marker": timeline_marker,
                "component_entity_token": entity_token(component),
                "canvas_name": safe_value(canvas, "name", name),
                "canvas_entity_token": entity_token(canvas),
            }
        )
        payload = {
            "action": "created",
            "canvas": {
                "name": safe_value(canvas, "name", name),
                "entity_token": entity_token(canvas),
                "image_name": prepared["image_name"],
                "image_size_bytes": prepared["image_size_bytes"],
                "plane": prepared["plane"],
                "width_expression": prepared["width_expression"],
                "center_x_expression": prepared["center_x_expression"],
                "center_y_expression": prepared["center_y_expression"],
                "width_mm": prepared["width_mm"],
                "height_mm": prepared["height_mm"],
                "center_mm": prepared["center_mm"],
                "opacity": prepared["opacity"],
                "flip_horizontal": prepared["flip_horizontal"],
                "flip_vertical": prepared["flip_vertical"],
            },
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
        if canvas is not None and not transaction_started:
            try:
                canvas.deleteMe()
            except Exception:
                pass
        code = (
            "RECOMPUTE_FAILED"
            if isinstance(error, _RecomputeFailure)
            else "CANVAS_WRITE_FAILED"
        )
        message = (
            str(error)
            if isinstance(error, _RecomputeFailure)
            else "Fusion could not create the reference canvas."
        )
        result = _error(
            code,
            message,
            retryable=True,
            details={
                "name": name,
                "image_name": prepared["image_name"],
                "plane": prepared["plane"],
                "undo_result": (
                    "transaction_aborted" if transaction_started else "canvas_deleted"
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
