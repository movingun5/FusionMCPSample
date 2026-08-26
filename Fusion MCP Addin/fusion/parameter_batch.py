"""Atomic updates for existing Fusion user and model parameters."""

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


_USER_KEYS = {"kind", "name", "expression", "expected_old_expression"}
_MODEL_KEYS = {
    "kind",
    "feature_name",
    "role",
    "expression",
    "expected_old_expression",
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
    return MCPError(code, message, retryable=retryable, details=details).to_result()


def _required_string(value, field):
    if not isinstance(value, str) or not value.strip():
        return None, _error("INVALID_REQUEST", f"{field} must be a non-empty string")
    return value.strip(), None


def _abort_transaction(app, started):
    if not started:
        return
    try:
        app.executeTextCommand("PTransaction.Abort")
    except Exception:
        pass


def _user_parameter_data(parameter):
    return {
        "name": safe_value(parameter, "name", ""),
        "expression": safe_value(parameter, "expression", ""),
        "unit": safe_value(parameter, "unit", ""),
        "value": safe_value(parameter, "value"),
        "comment": safe_value(parameter, "comment", ""),
    }


def _model_parameter_data(parameter):
    owner = safe_value(parameter, "createdBy")
    component = safe_value(parameter, "component")
    return {
        "name": safe_value(parameter, "name", ""),
        "expression": safe_value(parameter, "expression", ""),
        "unit": safe_value(parameter, "unit", ""),
        "value": safe_value(parameter, "value"),
        "role": safe_value(parameter, "role", ""),
        "component": safe_value(component, "name", ""),
        "created_by": {
            "name": safe_value(owner, "name", ""),
            "type": safe_value(owner, "objectType") or type(owner).__name__,
            "entity_token": entity_token(owner),
        },
    }


def _resolve_model_parameter(component, feature_name, role):
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


def _normalize_and_resolve(updates, design, component):
    if not isinstance(updates, list) or not 1 <= len(updates) <= 16:
        return None, _error("INVALID_REQUEST", "updates must contain between 1 and 16 items")

    user_parameters = safe_value(design, "userParameters")
    units_manager = safe_value(design, "unitsManager")
    if user_parameters is None or units_manager is None:
        return None, _error(
            "FUSION_API_ERROR",
            "The active design does not expose parameters or units.",
            retryable=True,
        )

    resolved = []
    target_keys = set()
    for index, source in enumerate(updates):
        if not isinstance(source, dict):
            return None, _error("INVALID_REQUEST", f"updates[{index}] must be an object")
        kind = source.get("kind")
        expected_keys = _USER_KEYS if kind == "user" else _MODEL_KEYS if kind == "model" else None
        if expected_keys is None or set(source) != expected_keys:
            return None, _error(
                "INVALID_REQUEST",
                f"updates[{index}] fields do not match a supported parameter kind",
                details={"index": index},
            )

        expression, failure = _required_string(source["expression"], f"updates[{index}].expression")
        if failure:
            return None, failure
        expected_old, failure = _required_string(
            source["expected_old_expression"],
            f"updates[{index}].expected_old_expression",
        )
        if failure:
            return None, failure

        if kind == "user":
            name, failure = _required_string(source["name"], f"updates[{index}].name")
            if failure:
                return None, failure
            target_key = ("user", name.casefold())
            parameter = user_parameters.itemByName(name)
            if parameter is None:
                return None, _error(
                    "PARAMETER_NOT_FOUND",
                    "No existing user parameter matched the requested name.",
                    details={"name": name},
                )
            previous = _user_parameter_data(parameter)
            normalized = {"kind": "user", "name": name, "expression": expression}
            conflict_code = "PARAMETER_CONFLICT"
            expression_code = "PARAMETER_EVALUATION_FAILED"
        else:
            feature_name, failure = _required_string(
                source["feature_name"],
                f"updates[{index}].feature_name",
            )
            if failure:
                return None, failure
            role, failure = _required_string(source["role"], f"updates[{index}].role")
            if failure:
                return None, failure
            target_key = ("model", feature_name, role.casefold())
            matches = _resolve_model_parameter(component, feature_name, role)
            if not matches:
                return None, _error(
                    "MODEL_PARAMETER_NOT_FOUND",
                    "No model parameter matched the requested feature name and role.",
                    details={"feature_name": feature_name, "role": role},
                )
            if len(matches) > 1:
                return None, _error(
                    "MODEL_PARAMETER_AMBIGUOUS",
                    "More than one model parameter matched the requested feature name and role.",
                    details={
                        "feature_name": feature_name,
                        "role": role,
                        "parameter_names": [safe_value(item, "name", "") for item in matches],
                    },
                )
            parameter = matches[0]
            previous = _model_parameter_data(parameter)
            normalized = {
                "kind": "model",
                "feature_name": feature_name,
                "role": role,
                "expression": expression,
            }
            conflict_code = "MODEL_PARAMETER_CONFLICT"
            expression_code = "MODEL_PARAMETER_EXPRESSION_INVALID"

        if target_key in target_keys:
            return None, _error(
                "DUPLICATE_PARAMETER_TARGET",
                "A parameter target may appear only once in a batch.",
                details={"index": index},
            )
        target_keys.add(target_key)

        if previous["expression"] != expected_old:
            details = {
                "expected_old_expression": expected_old,
                "actual_expression": previous["expression"],
            }
            details.update({key: value for key, value in normalized.items() if key != "expression"})
            return None, _error(
                conflict_code,
                "The parameter changed since it was last read.",
                details=details,
            )
        try:
            units_manager.evaluateExpression(expression, previous["unit"])
        except Exception:
            details = {
                "expression": expression,
                "unit": previous["unit"],
            }
            details.update({key: value for key, value in normalized.items() if key != "expression"})
            return None, _error(
                expression_code,
                "Fusion could not evaluate the parameter expression.",
                details=details,
            )

        resolved.append(
            {
                "kind": kind,
                "parameter": parameter,
                "previous": previous,
                "expression": expression,
                "target": {key: value for key, value in normalized.items() if key != "expression"},
            }
        )
    return resolved, None


def update_parameter_batch(app, updates, audit_logger=None):
    """Update existing user and model parameters as one atomic operation."""

    started_at = time.time()
    request_id = hashlib.sha256(f"{time.time_ns()}:parameter-batch".encode("utf-8")).hexdigest()[:16]
    logger = audit_logger or _default_audit_logger()
    design = safe_value(app, "activeProduct") if app is not None else None
    root = safe_value(design, "rootComponent")
    if design is None or root is None:
        return _error("NO_ACTIVE_DESIGN", "Open or create a Fusion design first.", retryable=True)
    component = safe_value(design, "activeComponent") or root

    resolved, failure = _normalize_and_resolve(updates, design, component)
    if failure:
        return failure

    result_items = []
    for item in resolved:
        result_items.append(
            {
                "kind": item["kind"],
                **item["target"],
                "previous": item["previous"],
                "parameter": item["previous"],
                "action": (
                    "unchanged"
                    if item["previous"]["expression"] == item["expression"]
                    else "updated"
                ),
            }
        )
    if all(item["action"] == "unchanged" for item in result_items):
        payload = {
            "action": "unchanged",
            "updates": result_items,
            "recomputed": True,
            "checkpoint_recorded": False,
        }
        payload["audit_logged"] = _audit(
            logger,
            {
                "request_id": request_id,
                "mutation": "update_parameter_batch",
                "result": payload,
                "duration_ms": int((time.time() - started_at) * 1000),
            },
        )
        return tool_success(payload)

    document = safe_value(app, "activeDocument")
    timeline = safe_value(design, "timeline")
    document_id = safe_value(document, "id") or safe_value(safe_value(design, "parentDocument"), "id")
    timeline_marker = safe_value(timeline, "markerPosition")
    transaction_started = False
    try:
        if document is not None:
            app.executeTextCommand('PTransaction.Start "Codex Parameter Batch"')
            transaction_started = True
        for item in resolved:
            item["parameter"].expression = item["expression"]
        if design.computeAll() is False:
            raise _RecomputeFailure("Fusion could not recompute after the parameter batch update.")
        if transaction_started:
            app.executeTextCommand("PTransaction.Commit")

        record_checkpoint(
            {
                "request_id": request_id,
                "mutation": "update_parameter_batch",
                "document_id": document_id,
                "timeline_marker": timeline_marker,
            }
        )
        for result_item, item in zip(result_items, resolved):
            data = (
                _user_parameter_data(item["parameter"])
                if item["kind"] == "user"
                else _model_parameter_data(item["parameter"])
            )
            result_item["parameter"] = data
        payload = {
            "action": "updated",
            "updates": result_items,
            "recomputed": True,
            "checkpoint_recorded": True,
            "undo_label": "Update Parameter Batch",
        }
        payload["audit_logged"] = _audit(
            logger,
            {
                "request_id": request_id,
                "mutation": "update_parameter_batch",
                "result": payload,
                "duration_ms": int((time.time() - started_at) * 1000),
            },
        )
        return tool_success(payload)
    except Exception as error:
        _abort_transaction(app, transaction_started)
        for item in resolved:
            try:
                item["parameter"].expression = item["previous"]["expression"]
            except Exception:
                pass
        code = "RECOMPUTE_FAILED" if isinstance(error, _RecomputeFailure) else "PARAMETER_BATCH_WRITE_FAILED"
        message = str(error) if isinstance(error, _RecomputeFailure) else "Fusion could not write the parameter batch."
        result = _error(
            code,
            message,
            retryable=True,
            details={"undo_result": "transaction_aborted" if transaction_started else "restored"},
        )
        _audit(
            logger,
            {
                "request_id": request_id,
                "mutation": "update_parameter_batch",
                "result": result,
                "local_traceback": traceback.format_exc(),
                "duration_ms": int((time.time() - started_at) * 1000),
            },
        )
        return result
