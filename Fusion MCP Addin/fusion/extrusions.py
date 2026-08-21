"""Safe explicit solid extrusion operations for Fusion MCP tools."""

import hashlib
from pathlib import Path
import tempfile
import time
import traceback

from ..core.audit import AuditLogger
from ..core.errors import MCPError
from ..core.results import tool_success
from .checkpoints import record_checkpoint
from .snapshot import body_summary, entity_token, iter_collection, safe_value


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


def _profile_area(profile):
    area_properties = safe_value(profile, "areaProperties")
    if not callable(area_properties):
        return 0.0
    try:
        return float(safe_value(area_properties(), "area", 0.0))
    except Exception:
        return 0.0


def _largest_profile(profiles):
    candidates = list(iter_collection(profiles))
    if not candidates:
        return None, None
    indexed = list(enumerate(candidates))
    index, profile = max(indexed, key=lambda item: _profile_area(item[1]))
    return profile, index


def _fusion_helpers(value_input_factory, new_body_operation):
    if value_input_factory is not None and new_body_operation is not None:
        return value_input_factory, new_body_operation

    import adsk.core
    import adsk.fusion

    return (
        value_input_factory or adsk.core.ValueInput.createByString,
        new_body_operation
        if new_body_operation is not None
        else adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
    )


def create_extrusion(
    app,
    name,
    sketch_name,
    distance_expression,
    value_input_factory=None,
    new_body_operation=None,
    audit_logger=None,
):
    """Extrude the largest profile in one named sketch as a new solid body."""

    started_at = time.time()
    request_id = hashlib.sha256(
        f"{time.time_ns()}:{name}:{sketch_name}".encode("utf-8")
    ).hexdigest()[:16]
    logger = audit_logger or _default_audit_logger()

    if not isinstance(name, str) or not name.strip():
        return _error("INVALID_REQUEST", "name must be a non-empty string")
    if not isinstance(sketch_name, str) or not sketch_name.strip():
        return _error("INVALID_REQUEST", "sketch_name must be a non-empty string")
    if not isinstance(distance_expression, str) or not distance_expression.strip():
        return _error(
            "INVALID_REQUEST",
            "distance_expression must be a non-empty string",
        )
    name = name.strip()
    sketch_name = sketch_name.strip()

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
    features = safe_value(component, "features")
    extrudes = safe_value(features, "extrudeFeatures")
    units_manager = safe_value(design, "unitsManager")
    if sketches is None or extrudes is None or units_manager is None:
        return _error(
            "FUSION_API_ERROR",
            "The active component does not expose sketches, extrusion features, or units.",
            retryable=True,
        )

    sketch = _item_by_name(sketches, sketch_name)
    if sketch is None:
        return _error(
            "SKETCH_NOT_FOUND",
            "The requested sketch was not found in the active component.",
            details={"sketch_name": sketch_name},
        )
    if _item_by_name(extrudes, name) is not None:
        return _error(
            "FEATURE_NAME_CONFLICT",
            "An extrusion with the requested name already exists.",
            details={"name": name},
        )
    profile, profile_index = _largest_profile(safe_value(sketch, "profiles"))
    if profile is None:
        return _error(
            "SKETCH_HAS_NO_PROFILE",
            "The requested sketch has no closed profile to extrude.",
            details={"sketch_name": sketch_name},
        )

    target_unit = safe_value(units_manager, "defaultLengthUnits", "mm")
    try:
        distance = float(
            units_manager.evaluateExpression(distance_expression, target_unit)
        )
    except Exception:
        return _error(
            "EXTRUSION_EXPRESSION_INVALID",
            "Fusion could not evaluate the extrusion distance expression.",
            details={"distance_expression": distance_expression, "unit": target_unit},
        )
    if abs(distance) <= 1e-9:
        return _error(
            "EXTRUSION_DISTANCE_INVALID",
            "Extrusion distance must not be zero.",
            details={"distance_expression": distance_expression},
        )

    value_input_factory, new_body_operation = _fusion_helpers(
        value_input_factory,
        new_body_operation,
    )
    base_audit = {
        "request_id": request_id,
        "mutation": "create_extrusion",
        "name": name,
        "sketch_name": sketch_name,
        "distance_expression": distance_expression,
        "operation": "new_body",
    }
    document = safe_value(app, "activeDocument")
    timeline = safe_value(design, "timeline")
    document_id = safe_value(document, "id") or safe_value(
        safe_value(design, "parentDocument"), "id"
    )
    timeline_marker = safe_value(timeline, "markerPosition")
    transaction_started = False
    feature = None
    try:
        if document is not None:
            app.executeTextCommand('PTransaction.Start "Codex New Body Extrusion"')
            transaction_started = True

        feature = extrudes.addSimple(
            profile,
            value_input_factory(distance_expression),
            new_body_operation,
        )
        if feature is None:
            raise RuntimeError("Fusion did not create an extrusion feature.")
        feature.name = name
        bodies = list(iter_collection(safe_value(feature, "bodies")))
        if not bodies:
            raise RuntimeError("The extrusion did not create a solid body.")

        if design.computeAll() is False:
            raise _RecomputeFailure(
                "Fusion could not recompute the design after creating the extrusion."
            )
        if transaction_started:
            app.executeTextCommand("PTransaction.Commit")

        record_checkpoint(
            {
                "request_id": request_id,
                "mutation": "create_extrusion",
                "document_id": document_id,
                "timeline_marker": timeline_marker,
            }
        )
        payload = {
            "action": "created",
            "feature": {
                "name": safe_value(feature, "name", name),
                "entity_token": entity_token(feature),
                "operation": "new_body",
            },
            "source_sketch": sketch_name,
            "selected_profile_index": profile_index,
            "distance_expression": distance_expression,
            "evaluated_distance_mm": round(distance * 10.0, 6),
            "bodies": [body_summary(body) for body in bodies],
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
        if feature is not None and not transaction_started:
            try:
                feature.deleteMe()
            except Exception:
                pass
        code = (
            "RECOMPUTE_FAILED"
            if isinstance(error, _RecomputeFailure)
            else "EXTRUSION_WRITE_FAILED"
        )
        message = (
            str(error)
            if isinstance(error, _RecomputeFailure)
            else "Fusion could not create the extrusion."
        )
        result = _error(
            code,
            message,
            retryable=True,
            details={
                "name": name,
                "sketch_name": sketch_name,
                "undo_result": (
                    "transaction_aborted" if transaction_started else "feature_deleted"
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
