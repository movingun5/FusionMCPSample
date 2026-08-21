"""Safe explicit simple-hole operations for Fusion MCP tools."""

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


def _item_by_name(collection, name):
    getter = safe_value(collection, "itemByName")
    if callable(getter):
        return getter(name)
    return next(
        (item for item in iter_collection(collection) if safe_value(item, "name") == name),
        None,
    )


def _face_normal(face):
    evaluator = safe_value(face, "evaluator")
    point = safe_value(face, "pointOnFace")
    get_normal = safe_value(evaluator, "getNormalAtPoint")
    if not callable(get_normal) or point is None:
        return None
    try:
        success, normal = get_normal(point)
    except Exception:
        return None
    return normal if success else None


def _is_planar(face):
    geometry = safe_value(face, "geometry")
    object_type = str(safe_value(geometry, "objectType", type(geometry).__name__))
    return "plane" in object_type.lower()


def _top_planar_face(body):
    candidates = []
    for face in iter_collection(safe_value(body, "faces")):
        if not _is_planar(face):
            continue
        normal = _face_normal(face)
        point = safe_value(face, "pointOnFace")
        if normal is None or point is None:
            continue
        if (
            abs(float(safe_value(normal, "x", 0.0))) <= 1e-6
            and abs(float(safe_value(normal, "y", 0.0))) <= 1e-6
            and float(safe_value(normal, "z", 0.0)) >= 0.999999
        ):
            candidates.append((float(safe_value(point, "z", 0.0)), face))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _fusion_helpers(point_factory, value_input_factory, orientations):
    if (
        point_factory is not None
        and value_input_factory is not None
        and orientations is not None
    ):
        return point_factory, value_input_factory, orientations

    import adsk.core
    import adsk.fusion

    return (
        point_factory or adsk.core.Point3D.create,
        value_input_factory or adsk.core.ValueInput.createByString,
        orientations
        or {
            "horizontal": adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation,
            "vertical": adsk.fusion.DimensionOrientations.VerticalDimensionOrientation,
        },
    )


def _positive_dimension_expression(expression, evaluated):
    return f"-({expression})" if evaluated < 0 else expression


def _add_position_dimensions(
    sketch,
    point,
    x_expression,
    y_expression,
    x_value,
    y_value,
    point_factory,
    orientations,
):
    origin = safe_value(sketch, "originPoint")
    dimensions = safe_value(sketch, "sketchDimensions")
    constraints = safe_value(sketch, "geometricConstraints")
    if origin is None or dimensions is None:
        raise RuntimeError("The placement sketch does not expose its origin or dimensions.")

    span = max(abs(x_value), abs(y_value), 1.0)
    if abs(x_value) > 1e-9:
        horizontal = dimensions.addDistanceDimension(
            origin,
            point,
            orientations["horizontal"],
            point_factory(x_value / 2.0, y_value - (span * 0.15), 0.0),
        )
        horizontal.parameter.expression = _positive_dimension_expression(
            x_expression,
            x_value,
        )
    else:
        add_vertical = safe_value(constraints, "addVerticalPoints")
        if not callable(add_vertical) or add_vertical(origin, point) is None:
            raise RuntimeError("Fusion could not constrain the hole X position to zero.")

    if abs(y_value) > 1e-9:
        vertical = dimensions.addDistanceDimension(
            origin,
            point,
            orientations["vertical"],
            point_factory(x_value + (span * 0.15), y_value / 2.0, 0.0),
        )
        vertical.parameter.expression = _positive_dimension_expression(
            y_expression,
            y_value,
        )
    else:
        add_horizontal = safe_value(constraints, "addHorizontalPoints")
        if not callable(add_horizontal) or add_horizontal(origin, point) is None:
            raise RuntimeError("Fusion could not constrain the hole Y position to zero.")


def create_simple_hole(
    app,
    name,
    body_name,
    x_expression,
    y_expression,
    diameter_expression,
    depth_expression,
    point_factory=None,
    value_input_factory=None,
    dimension_orientations=None,
    audit_logger=None,
):
    """Create one parametrically positioned simple hole from a body's +Z top face."""

    started_at = time.time()
    request_id = hashlib.sha256(
        f"{time.time_ns()}:{name}:{body_name}".encode("utf-8")
    ).hexdigest()[:16]
    logger = audit_logger or _default_audit_logger()

    string_inputs = {
        "name": name,
        "body_name": body_name,
        "x_expression": x_expression,
        "y_expression": y_expression,
        "diameter_expression": diameter_expression,
        "depth_expression": depth_expression,
    }
    if any(not isinstance(value, str) or not value.strip() for value in string_inputs.values()):
        return _error("INVALID_REQUEST", "all hole inputs must be non-empty strings")
    string_inputs = {key: value.strip() for key, value in string_inputs.items()}
    name = string_inputs["name"]
    body_name = string_inputs["body_name"]
    placement_sketch_name = f"{name} Placement"

    design = safe_value(app, "activeProduct") if app is not None else None
    root = safe_value(design, "rootComponent")
    if design is None or root is None:
        return _error(
            "NO_ACTIVE_DESIGN",
            "Open or create a Fusion design first.",
            retryable=True,
        )
    component = safe_value(design, "activeComponent") or root
    bodies = safe_value(component, "bRepBodies")
    sketches = safe_value(component, "sketches")
    features = safe_value(component, "features")
    holes = safe_value(features, "holeFeatures")
    units_manager = safe_value(design, "unitsManager")
    if bodies is None or sketches is None or holes is None or units_manager is None:
        return _error(
            "FUSION_API_ERROR",
            "The active component does not expose bodies, sketches, holes, or units.",
            retryable=True,
        )

    body = _item_by_name(bodies, body_name)
    if body is None:
        return _error(
            "BODY_NOT_FOUND",
            "The requested body was not found in the active component.",
            details={"body_name": body_name},
        )
    if not bool(safe_value(body, "isSolid", False)):
        return _error(
            "BODY_NOT_SOLID",
            "The requested body must be a solid.",
            details={"body_name": body_name},
        )
    if _item_by_name(holes, name) is not None:
        return _error(
            "FEATURE_NAME_CONFLICT",
            "A hole feature with the requested name already exists.",
            details={"name": name},
        )
    if _item_by_name(sketches, placement_sketch_name) is not None:
        return _error(
            "SKETCH_NAME_CONFLICT",
            "The generated placement sketch name already exists.",
            details={"sketch_name": placement_sketch_name},
        )

    top_face = _top_planar_face(body)
    if top_face is None:
        return _error(
            "TOP_FACE_NOT_FOUND",
            "The body has no planar +Z top face suitable for this hole tool.",
            details={"body_name": body_name},
        )

    target_unit = safe_value(units_manager, "defaultLengthUnits", "mm")
    evaluated = {}
    try:
        for key in (
            "x_expression",
            "y_expression",
            "diameter_expression",
            "depth_expression",
        ):
            evaluated[key] = float(
                units_manager.evaluateExpression(string_inputs[key], target_unit)
            )
    except Exception:
        return _error(
            "HOLE_EXPRESSION_INVALID",
            "Fusion could not evaluate one of the hole expressions.",
            details={**string_inputs, "unit": target_unit},
        )
    if evaluated["diameter_expression"] <= 0 or evaluated["depth_expression"] <= 0:
        return _error(
            "HOLE_DIMENSION_INVALID",
            "Hole diameter and depth must both be greater than zero.",
            details={
                "diameter_mm": evaluated["diameter_expression"] * 10.0,
                "depth_mm": evaluated["depth_expression"] * 10.0,
            },
        )

    point_factory, value_input_factory, orientations = _fusion_helpers(
        point_factory,
        value_input_factory,
        dimension_orientations,
    )
    base_audit = {
        "request_id": request_id,
        "mutation": "create_simple_hole",
        **string_inputs,
        "placement_face": "positive_z_top",
    }
    document = safe_value(app, "activeDocument")
    timeline = safe_value(design, "timeline")
    document_id = safe_value(document, "id") or safe_value(
        safe_value(design, "parentDocument"), "id"
    )
    timeline_marker = safe_value(timeline, "markerPosition")
    transaction_started = False
    sketch = None
    feature = None
    try:
        if document is not None:
            app.executeTextCommand('PTransaction.Start "Codex Simple Hole"')
            transaction_started = True

        sketch = sketches.add(top_face)
        sketch.name = placement_sketch_name
        sketch.isComputeDeferred = True
        x_value = evaluated["x_expression"]
        y_value = evaluated["y_expression"]
        if abs(x_value) <= 1e-9 and abs(y_value) <= 1e-9:
            point = sketch.originPoint
        else:
            point = sketch.sketchPoints.add(point_factory(x_value, y_value, 0.0))
            _add_position_dimensions(
                sketch,
                point,
                string_inputs["x_expression"],
                string_inputs["y_expression"],
                x_value,
                y_value,
                point_factory,
                orientations,
            )
        sketch.isComputeDeferred = False

        hole_input = holes.createSimpleInput(
            value_input_factory(string_inputs["diameter_expression"])
        )
        if hole_input is None:
            raise RuntimeError("Fusion did not create a simple-hole input.")
        if hole_input.setPositionBySketchPoint(point) is False:
            raise RuntimeError("Fusion rejected the hole placement point.")
        if hole_input.setDistanceExtent(
            value_input_factory(string_inputs["depth_expression"])
        ) is False:
            raise RuntimeError("Fusion rejected the hole depth.")
        hole_input.participantBodies = [body]
        feature = holes.add(hole_input)
        if feature is None:
            raise RuntimeError("Fusion did not create the hole feature.")
        feature.name = name
        sketch.isVisible = False

        if design.computeAll() is False:
            raise _RecomputeFailure(
                "Fusion could not recompute the design after creating the hole."
            )
        if transaction_started:
            app.executeTextCommand("PTransaction.Commit")

        record_checkpoint(
            {
                "request_id": request_id,
                "mutation": "create_simple_hole",
                "document_id": document_id,
                "timeline_marker": timeline_marker,
            }
        )
        payload = {
            "action": "created",
            "feature": {
                "name": safe_value(feature, "name", name),
                "entity_token": entity_token(feature),
                "type": "simple_hole",
            },
            "target_body": {
                "name": safe_value(body, "name", body_name),
                "entity_token": entity_token(body),
            },
            "placement": {
                "face": "positive_z_top",
                "sketch_name": placement_sketch_name,
                "x_expression": string_inputs["x_expression"],
                "y_expression": string_inputs["y_expression"],
                "evaluated_xy_mm": [
                    round(evaluated["x_expression"] * 10.0, 6),
                    round(evaluated["y_expression"] * 10.0, 6),
                ],
            },
            "diameter_expression": string_inputs["diameter_expression"],
            "depth_expression": string_inputs["depth_expression"],
            "evaluated_diameter_mm": round(
                evaluated["diameter_expression"] * 10.0,
                6,
            ),
            "evaluated_depth_mm": round(evaluated["depth_expression"] * 10.0, 6),
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
        if not transaction_started:
            for entity in (feature, sketch):
                if entity is not None:
                    try:
                        entity.deleteMe()
                    except Exception:
                        pass
        code = (
            "RECOMPUTE_FAILED"
            if isinstance(error, _RecomputeFailure)
            else "HOLE_WRITE_FAILED"
        )
        message = (
            str(error)
            if isinstance(error, _RecomputeFailure)
            else "Fusion could not create the simple hole."
        )
        result = _error(
            code,
            message,
            retryable=True,
            details={
                "name": name,
                "body_name": body_name,
                "undo_result": (
                    "transaction_aborted" if transaction_started else "entities_deleted"
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
