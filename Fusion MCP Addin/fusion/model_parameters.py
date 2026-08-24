"""Safe updates for Fusion model parameters owned by named features."""

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


def _created_by_data(owner):
    return {
        "name": safe_value(owner, "name", ""),
        "type": safe_value(owner, "objectType") or type(owner).__name__,
        "entity_token": entity_token(owner),
    }


def _parameter_data(parameter):
    owner = safe_value(parameter, "createdBy")
    component = safe_value(parameter, "component")
    return {
        "name": safe_value(parameter, "name", ""),
        "expression": safe_value(parameter, "expression", ""),
        "unit": safe_value(parameter, "unit", ""),
        "value": safe_value(parameter, "value"),
        "role": safe_value(parameter, "role", ""),
        "component": safe_value(component, "name", ""),
        "created_by": _created_by_data(owner),
    }


def _matching_parameters(component, feature_name, role):
    matches = []
    wanted_role = role.casefold()
    for parameter in iter_collection(safe_value(component, "modelParameters")):
        owner = safe_value(parameter, "createdBy")
        if safe_value(owner, "name") != feature_name:
            continue
        if str(safe_value(parameter, "role", "")).casefold() != wanted_role:
            continue
        matches.append(parameter)
    return matches


def update_model_parameter(
    app,
    feature_name,
    role,
    expression,
    expected_old_expression,
    audit_logger=None,
):
    """Update one model parameter selected by feature name and parameter role."""

    started_at = time.time()
    request_id = hashlib.sha256(
        f"{time.time_ns()}:{feature_name}:{role}".encode("utf-8")
    ).hexdigest()[:16]
    logger = audit_logger or _default_audit_logger()

    inputs = {
        "feature_name": feature_name,
        "role": role,
        "expression": expression,
        "expected_old_expression": expected_old_expression,
    }
    for key, value in inputs.items():
        if not isinstance(value, str) or not value.strip():
            return _error(
                "INVALID_REQUEST",
                f"{key} must be a non-empty string",
            )
    feature_name = feature_name.strip()
    role = role.strip()
    expression = expression.strip()

    design = safe_value(app, "activeProduct") if app is not None else None
    root = safe_value(design, "rootComponent")
    if design is None or root is None:
        return _error(
            "NO_ACTIVE_DESIGN",
            "Open or create a Fusion design first.",
            retryable=True,
        )
    component = safe_value(design, "activeComponent") or root
    parameters = safe_value(component, "modelParameters")
    units_manager = safe_value(design, "unitsManager")
    if parameters is None or units_manager is None:
        return _error(
            "FUSION_API_ERROR",
            "The active component does not expose model parameters or units.",
            retryable=True,
        )

    matches = _matching_parameters(component, feature_name, role)
    if not matches:
        return _error(
            "MODEL_PARAMETER_NOT_FOUND",
            "No model parameter matched the requested feature name and role.",
            details={"feature_name": feature_name, "role": role},
        )
    if len(matches) > 1:
        return _error(
            "MODEL_PARAMETER_AMBIGUOUS",
            "More than one model parameter matched the requested feature name and role.",
            details={
                "feature_name": feature_name,
                "role": role,
                "parameter_names": [safe_value(item, "name", "") for item in matches],
            },
        )

    parameter = matches[0]
    previous = _parameter_data(parameter)
    if previous["expression"] != expected_old_expression:
        return _error(
            "MODEL_PARAMETER_CONFLICT",
            "The model parameter changed since it was last read.",
            details={
                "feature_name": feature_name,
                "role": role,
                "expected_old_expression": expected_old_expression,
                "actual_expression": previous["expression"],
            },
        )

    target_unit = previous["unit"]
    try:
        units_manager.evaluateExpression(expression, target_unit)
    except Exception:
        return _error(
            "MODEL_PARAMETER_EXPRESSION_INVALID",
            "Fusion could not evaluate the model-parameter expression.",
            details={
                "feature_name": feature_name,
                "role": role,
                "expression": expression,
                "unit": target_unit,
            },
        )

    base_audit = {
        "request_id": request_id,
        "mutation": "update_model_parameter",
        "feature_name": feature_name,
        "role": role,
        "expression": expression,
        "expected_old_expression": expected_old_expression,
    }
    if previous["expression"] == expression:
        payload = {
            "action": "unchanged",
            "parameter": previous,
            "previous": previous,
            "recomputed": True,
            "checkpoint_recorded": False,
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

    document = safe_value(app, "activeDocument")
    timeline = safe_value(design, "timeline")
    document_id = safe_value(document, "id") or safe_value(
        safe_value(design, "parentDocument"), "id"
    )
    timeline_marker = safe_value(timeline, "markerPosition")
    transaction_started = False
    try:
        if document is not None:
            app.executeTextCommand('PTransaction.Start "Codex Model Parameter"')
            transaction_started = True

        parameter.expression = expression
        if design.computeAll() is False:
            raise _RecomputeFailure(
                "Fusion could not recompute the design after the model-parameter change."
            )

        if transaction_started:
            app.executeTextCommand("PTransaction.Commit")

        record_checkpoint(
            {
                "request_id": request_id,
                "mutation": "update_model_parameter",
                "document_id": document_id,
                "timeline_marker": timeline_marker,
            }
        )
        payload = {
            "action": "updated",
            "parameter": _parameter_data(parameter),
            "previous": previous,
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
        try:
            parameter.expression = previous["expression"]
            design.computeAll()
        except Exception:
            pass

        code = (
            "RECOMPUTE_FAILED"
            if isinstance(error, _RecomputeFailure)
            else "MODEL_PARAMETER_WRITE_FAILED"
        )
        message = (
            str(error)
            if isinstance(error, _RecomputeFailure)
            else "Fusion could not write the model parameter."
        )
        result = _error(
            code,
            message,
            retryable=True,
            details={
                "feature_name": feature_name,
                "role": role,
                "undo_result": (
                    "transaction_aborted" if transaction_started else "restored"
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
