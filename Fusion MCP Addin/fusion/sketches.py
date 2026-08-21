"""Safe explicit sketch operations for Fusion MCP tools."""

import hashlib
from pathlib import Path
import tempfile
import time
import traceback

from ..core.audit import AuditLogger
from ..core.errors import MCPError
from ..core.results import tool_success
from .checkpoints import record_checkpoint
from .snapshot import entity_token, iter_collection, safe_value


_PLANES = {
    "xy": "xYConstructionPlane",
    "xz": "xZConstructionPlane",
    "yz": "yZConstructionPlane",
}


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


def _fusion_geometry_helpers(point_factory, dimension_orientations):
    if point_factory is not None and dimension_orientations is not None:
        return point_factory, dimension_orientations

    import adsk.core
    import adsk.fusion

    return (
        point_factory or adsk.core.Point3D.create,
        dimension_orientations
        or {
            "horizontal": adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation,
            "vertical": adsk.fusion.DimensionOrientations.VerticalDimensionOrientation,
        },
    )


def _line_delta(line):
    start = line.startSketchPoint.geometry
    end = line.endSketchPoint.geometry
    return abs(end.x - start.x), abs(end.y - start.y)


def _dimension_lines(lines):
    horizontal = None
    vertical = None
    for line in iter_collection(lines):
        delta_x, delta_y = _line_delta(line)
        if horizontal is None and delta_x >= delta_y:
            horizontal = line
        if vertical is None and delta_y > delta_x:
            vertical = line
    if horizontal is None or vertical is None:
        raise RuntimeError("The rectangle did not contain horizontal and vertical lines.")
    return horizontal, vertical


def _existing_sketch(sketches, name):
    item_by_name = safe_value(sketches, "itemByName")
    if callable(item_by_name):
        return item_by_name(name)
    return next(
        (sketch for sketch in iter_collection(sketches) if safe_value(sketch, "name") == name),
        None,
    )


def create_rectangle_sketch(
    app,
    name,
    width_expression,
    height_expression,
    plane="xy",
    center_x_expression="0 mm",
    center_y_expression="0 mm",
    point_factory=None,
    dimension_orientations=None,
    audit_logger=None,
):
    """Create one named, center-point rectangle with driving dimensions."""

    started_at = time.time()
    request_id = hashlib.sha256(
        f"{time.time_ns()}:{name}".encode("utf-8")
    ).hexdigest()[:16]
    logger = audit_logger or _default_audit_logger()

    if not isinstance(name, str) or not name.strip():
        return _error("INVALID_REQUEST", "name must be a non-empty string")
    name = name.strip()
    expressions = {
        "width_expression": width_expression,
        "height_expression": height_expression,
        "center_x_expression": center_x_expression,
        "center_y_expression": center_y_expression,
    }
    if any(not isinstance(value, str) or not value.strip() for value in expressions.values()):
        return _error("INVALID_REQUEST", "all dimension expressions must be non-empty strings")
    if plane not in _PLANES:
        return _error(
            "INVALID_REQUEST",
            "plane must be one of: xy, xz, yz",
            details={"plane": plane},
        )

    design = safe_value(app, "activeProduct") if app is not None else None
    root = safe_value(design, "rootComponent")
    if design is None or root is None:
        return _error(
            "NO_ACTIVE_DESIGN",
            "Open or create a Fusion design first.",
            retryable=True,
        )
    component = safe_value(design, "activeComponent") or root
    sketches = safe_value(component, "sketches")
    units_manager = safe_value(design, "unitsManager")
    if sketches is None or units_manager is None:
        return _error(
            "FUSION_API_ERROR",
            "The active design does not expose sketches or units.",
            retryable=True,
        )
    if _existing_sketch(sketches, name) is not None:
        return _error(
            "SKETCH_NAME_CONFLICT",
            "A sketch with the requested name already exists in the active component.",
            details={"name": name},
        )

    target_unit = safe_value(units_manager, "defaultLengthUnits", "mm")
    evaluated = {}
    try:
        for key, expression in expressions.items():
            evaluated[key] = float(
                units_manager.evaluateExpression(expression, target_unit)
            )
    except Exception:
        return _error(
            "SKETCH_EXPRESSION_INVALID",
            "Fusion could not evaluate one of the rectangle expressions.",
            details={**expressions, "unit": target_unit},
        )
    if evaluated["width_expression"] <= 0 or evaluated["height_expression"] <= 0:
        return _error(
            "SKETCH_DIMENSION_INVALID",
            "Rectangle width and height must both be greater than zero.",
            details={
                "evaluated_width_mm": evaluated["width_expression"] * 10.0,
                "evaluated_height_mm": evaluated["height_expression"] * 10.0,
            },
        )

    point_factory, orientations = _fusion_geometry_helpers(
        point_factory,
        dimension_orientations,
    )
    width = evaluated["width_expression"]
    height = evaluated["height_expression"]
    center_x = evaluated["center_x_expression"]
    center_y = evaluated["center_y_expression"]
    base_audit = {
        "request_id": request_id,
        "mutation": "create_rectangle_sketch",
        "name": name,
        "plane": plane,
        **expressions,
    }

    document = safe_value(app, "activeDocument")
    timeline = safe_value(design, "timeline")
    document_id = safe_value(document, "id") or safe_value(
        safe_value(design, "parentDocument"), "id"
    )
    timeline_marker = safe_value(timeline, "markerPosition")
    transaction_started = False
    sketch = None
    try:
        if document is not None:
            app.executeTextCommand('PTransaction.Start "Codex Rectangle Sketch"')
            transaction_started = True

        construction_plane = safe_value(component, _PLANES[plane])
        if construction_plane is None:
            raise RuntimeError(f"Construction plane {plane!r} is unavailable.")
        sketch = sketches.add(construction_plane)
        sketch.name = name
        sketch.isComputeDeferred = True

        center_point = point_factory(center_x, center_y, 0.0)
        corner_point = point_factory(
            center_x + (width / 2.0),
            center_y + (height / 2.0),
            0.0,
        )
        lines = sketch.sketchCurves.sketchLines.addCenterPointRectangle(
            center_point,
            corner_point,
        )
        if lines is None or safe_value(lines, "count", 0) != 4:
            raise RuntimeError("Fusion did not create four rectangle lines.")
        horizontal, vertical = _dimension_lines(lines)

        offset = max(width, height) * 0.15
        width_text = point_factory(center_x, center_y - (height / 2.0) - offset, 0.0)
        height_text = point_factory(center_x + (width / 2.0) + offset, center_y, 0.0)
        width_dimension = sketch.sketchDimensions.addDistanceDimension(
            horizontal.startSketchPoint,
            horizontal.endSketchPoint,
            orientations["horizontal"],
            width_text,
        )
        height_dimension = sketch.sketchDimensions.addDistanceDimension(
            vertical.startSketchPoint,
            vertical.endSketchPoint,
            orientations["vertical"],
            height_text,
        )
        if width_dimension is None or height_dimension is None:
            raise RuntimeError("Fusion did not create the rectangle dimensions.")
        width_dimension.parameter.expression = width_expression
        height_dimension.parameter.expression = height_expression
        sketch.isComputeDeferred = False

        if design.computeAll() is False:
            raise _RecomputeFailure(
                "Fusion could not recompute the design after creating the rectangle sketch."
            )
        if transaction_started:
            app.executeTextCommand("PTransaction.Commit")

        record_checkpoint(
            {
                "request_id": request_id,
                "mutation": "create_rectangle_sketch",
                "document_id": document_id,
                "timeline_marker": timeline_marker,
            }
        )
        payload = {
            "action": "created",
            "sketch": {
                "name": safe_value(sketch, "name", name),
                "entity_token": entity_token(sketch),
                "plane": plane,
                "line_count": safe_value(lines, "count", 4),
                "profile_count": safe_value(safe_value(sketch, "profiles"), "count", 0),
            },
            "width_expression": width_expression,
            "height_expression": height_expression,
            "center_expressions": [center_x_expression, center_y_expression],
            "evaluated_size_mm": [round(width * 10.0, 6), round(height * 10.0, 6)],
            "evaluated_center_mm": [round(center_x * 10.0, 6), round(center_y * 10.0, 6)],
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
        if sketch is not None:
            try:
                sketch.isComputeDeferred = False
            except Exception:
                pass
        _abort_transaction(app, transaction_started)
        if sketch is not None:
            try:
                sketch.deleteMe()
            except Exception:
                pass
        code = (
            "RECOMPUTE_FAILED"
            if isinstance(error, _RecomputeFailure)
            else "SKETCH_WRITE_FAILED"
        )
        message = (
            str(error)
            if isinstance(error, _RecomputeFailure)
            else "Fusion could not create the rectangle sketch."
        )
        result = _error(
            code,
            message,
            retryable=True,
            details={
                "name": name,
                "undo_result": (
                    "transaction_aborted" if transaction_started else "deleted"
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
