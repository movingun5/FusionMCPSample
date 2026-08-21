"""Safe explicit single-direction feature pattern operations for Fusion MCP tools."""

import hashlib
from pathlib import Path
import tempfile
import time
import traceback

from ..core.audit import AuditLogger
from ..core.errors import MCPError
from ..core.results import tool_success
from .checkpoints import record_checkpoint
from .fillets import _item_by_name
from .snapshot import entity_token, safe_value


_AXES = {"x", "y", "z"}


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


def _fusion_helpers(
    value_input_factory,
    object_collection_factory,
    spacing_pattern_distance_type,
):
    if (
        value_input_factory is not None
        and object_collection_factory is not None
        and spacing_pattern_distance_type is not None
    ):
        return (
            value_input_factory,
            object_collection_factory,
            spacing_pattern_distance_type,
        )

    import adsk.core
    import adsk.fusion

    return (
        value_input_factory or adsk.core.ValueInput.createByString,
        object_collection_factory or adsk.core.ObjectCollection.create,
        spacing_pattern_distance_type
        if spacing_pattern_distance_type is not None
        else adsk.fusion.PatternDistanceType.SpacingPatternDistanceType,
    )


def create_linear_pattern(
    app,
    name,
    target_feature_name,
    axis,
    quantity,
    spacing_expression,
    value_input_factory=None,
    object_collection_factory=None,
    spacing_pattern_distance_type=None,
    audit_logger=None,
):
    """Pattern one named feature along a principal construction axis."""

    started_at = time.time()
    request_id = hashlib.sha256(
        f"{time.time_ns()}:{name}:{target_feature_name}".encode("utf-8")
    ).hexdigest()[:16]
    logger = audit_logger or _default_audit_logger()

    if not isinstance(name, str) or not name.strip():
        return _error("INVALID_REQUEST", "name must be a non-empty string")
    if not isinstance(target_feature_name, str) or not target_feature_name.strip():
        return _error(
            "INVALID_REQUEST",
            "target_feature_name must be a non-empty string",
        )
    if axis not in _AXES:
        return _error(
            "INVALID_REQUEST",
            "axis must be one of: x, y, z",
            details={"axis": axis},
        )
    if (
        not isinstance(quantity, int)
        or isinstance(quantity, bool)
        or not 2 <= quantity <= 1000
    ):
        return _error(
            "PATTERN_QUANTITY_INVALID",
            "quantity must be an integer from 2 through 1000",
            details={"quantity": quantity},
        )
    if not isinstance(spacing_expression, str) or not spacing_expression.strip():
        return _error(
            "INVALID_REQUEST",
            "spacing_expression must be a non-empty string",
        )
    name = name.strip()
    target_feature_name = target_feature_name.strip()
    spacing_expression = spacing_expression.strip()

    design = safe_value(app, "activeProduct") if app is not None else None
    root = safe_value(design, "rootComponent")
    if design is None or root is None:
        return _error(
            "NO_ACTIVE_DESIGN",
            "Open or create a Fusion design first.",
            retryable=True,
        )
    component = safe_value(design, "activeComponent") or root
    features = safe_value(component, "features")
    patterns = safe_value(features, "rectangularPatternFeatures")
    units_manager = safe_value(design, "unitsManager")
    direction_axis = safe_value(component, f"{axis}ConstructionAxis")
    if patterns is None or units_manager is None or direction_axis is None:
        return _error(
            "FUSION_API_ERROR",
            "The active component does not expose feature patterns, units, or the requested axis.",
            retryable=True,
        )

    target_feature = _item_by_name(features, target_feature_name)
    if target_feature is None:
        return _error(
            "FEATURE_NOT_FOUND",
            "The requested feature was not found in the active component.",
            details={"target_feature_name": target_feature_name},
        )
    if _item_by_name(patterns, name) is not None:
        return _error(
            "FEATURE_NAME_CONFLICT",
            "A linear pattern with the requested name already exists.",
            details={"name": name},
        )

    target_unit = safe_value(units_manager, "defaultLengthUnits", "mm")
    try:
        spacing = float(
            units_manager.evaluateExpression(spacing_expression, target_unit)
        )
    except Exception:
        return _error(
            "PATTERN_EXPRESSION_INVALID",
            "Fusion could not evaluate the pattern spacing expression.",
            details={"spacing_expression": spacing_expression, "unit": target_unit},
        )
    if abs(spacing) <= 1e-9:
        return _error(
            "PATTERN_SPACING_INVALID",
            "Pattern spacing must not be zero.",
            details={"spacing_expression": spacing_expression},
        )

    (
        value_input_factory,
        object_collection_factory,
        spacing_pattern_distance_type,
    ) = _fusion_helpers(
        value_input_factory,
        object_collection_factory,
        spacing_pattern_distance_type,
    )
    base_audit = {
        "request_id": request_id,
        "mutation": "create_linear_pattern",
        "name": name,
        "target_feature_name": target_feature_name,
        "axis": axis,
        "quantity": quantity,
        "spacing_expression": spacing_expression,
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
        input_entities = object_collection_factory()
        if input_entities.add(target_feature) is False:
            raise RuntimeError("Fusion rejected the target feature for patterning.")

        if document is not None:
            app.executeTextCommand('PTransaction.Start "Codex Linear Feature Pattern"')
            transaction_started = True

        pattern_input = patterns.createInput(
            input_entities,
            direction_axis,
            value_input_factory(str(quantity)),
            value_input_factory(spacing_expression),
            spacing_pattern_distance_type,
        )
        if pattern_input is None:
            raise RuntimeError("Fusion did not create a linear pattern input.")
        feature = patterns.add(pattern_input)
        if feature is None:
            raise RuntimeError("Fusion did not create the linear pattern feature.")
        feature.name = name

        if design.computeAll() is False:
            raise _RecomputeFailure(
                "Fusion could not recompute the design after creating the pattern."
            )
        if transaction_started:
            app.executeTextCommand("PTransaction.Commit")

        record_checkpoint(
            {
                "request_id": request_id,
                "mutation": "create_linear_pattern",
                "document_id": document_id,
                "timeline_marker": timeline_marker,
            }
        )
        payload = {
            "action": "created",
            "feature": {
                "name": safe_value(feature, "name", name),
                "entity_token": entity_token(feature),
                "type": "linear_feature_pattern",
            },
            "target_feature": {
                "name": safe_value(target_feature, "name", target_feature_name),
                "entity_token": entity_token(target_feature),
            },
            "axis": axis,
            "quantity": quantity,
            "spacing_expression": spacing_expression,
            "evaluated_spacing_mm": round(spacing * 10.0, 6),
            "distance_type": "spacing",
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
            else "PATTERN_WRITE_FAILED"
        )
        message = (
            str(error)
            if isinstance(error, _RecomputeFailure)
            else "Fusion could not create the linear pattern."
        )
        result = _error(
            code,
            message,
            retryable=True,
            details={
                "name": name,
                "target_feature_name": target_feature_name,
                "axis": axis,
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
