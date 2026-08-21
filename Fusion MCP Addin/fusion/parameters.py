"""Safe creation and in-place updates for Fusion user parameters."""

import hashlib
from pathlib import Path
import re
import tempfile
import time
import traceback

from ..core.audit import AuditLogger
from ..core.errors import MCPError
from ..core.results import tool_success
from .checkpoints import record_checkpoint
from .snapshot import safe_value


_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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


def _parameter_data(parameter):
    if parameter is None:
        return None
    return {
        "name": safe_value(parameter, "name", ""),
        "expression": safe_value(parameter, "expression", ""),
        "unit": safe_value(parameter, "unit", ""),
        "value": safe_value(parameter, "value"),
        "comment": safe_value(parameter, "comment", ""),
    }


def _value_input(expression, factory):
    if factory is not None:
        return factory(expression)
    import adsk.core

    return adsk.core.ValueInput.createByString(expression)


def _abort_transaction(app, started):
    if not started:
        return
    try:
        app.executeTextCommand("PTransaction.Abort")
    except Exception:
        pass


def upsert_parameter(
    app,
    name,
    expression,
    unit=None,
    comment=None,
    expected_old_expression=None,
    value_input_factory=None,
    audit_logger=None,
):
    """Create or update one named Fusion user parameter atomically."""

    started_at = time.time()
    request_id = hashlib.sha256(
        f"{time.time_ns()}:{name}".encode("utf-8")
    ).hexdigest()[:16]
    logger = audit_logger or _default_audit_logger()

    if not isinstance(name, str) or not _NAME.fullmatch(name):
        return _error(
            "INVALID_REQUEST",
            "name must start with a letter or underscore and contain only letters, digits, or underscores",
        )
    if not isinstance(expression, str) or not expression.strip():
        return _error("INVALID_REQUEST", "expression must be a non-empty string")
    if unit is not None and not isinstance(unit, str):
        return _error("INVALID_REQUEST", "unit must be a string")
    if comment is not None and not isinstance(comment, str):
        return _error("INVALID_REQUEST", "comment must be a string")
    if expected_old_expression is not None and not isinstance(
        expected_old_expression, str
    ):
        return _error(
            "INVALID_REQUEST",
            "expected_old_expression must be a string",
        )

    design = safe_value(app, "activeProduct") if app is not None else None
    if design is None or safe_value(design, "rootComponent") is None:
        return _error(
            "NO_ACTIVE_DESIGN",
            "Open or create a Fusion design first.",
            retryable=True,
        )

    parameters = safe_value(design, "userParameters")
    units_manager = safe_value(design, "unitsManager")
    if parameters is None or units_manager is None:
        return _error(
            "FUSION_API_ERROR",
            "The active product does not expose user parameters.",
            retryable=True,
        )

    existing = parameters.itemByName(name)
    previous = _parameter_data(existing)
    if (
        existing is not None
        and expected_old_expression is not None
        and previous["expression"] != expected_old_expression
    ):
        return _error(
            "PARAMETER_CONFLICT",
            "The parameter changed since it was last read.",
            details={
                "name": name,
                "expected_old_expression": expected_old_expression,
                "actual_expression": previous["expression"],
            },
        )

    if existing is not None:
        target_unit = previous["unit"]
        if unit:
            try:
                units_manager.evaluateExpression(f"1 {unit}", target_unit)
            except Exception:
                return _error(
                    "PARAMETER_UNIT_MISMATCH",
                    "The requested unit is incompatible with the existing parameter.",
                    details={
                        "name": name,
                        "requested_unit": unit,
                        "existing_unit": target_unit,
                    },
                )
    else:
        target_unit = unit or safe_value(units_manager, "defaultLengthUnits", "mm")

    try:
        units_manager.evaluateExpression(expression, target_unit)
    except Exception:
        return _error(
            "PARAMETER_EVALUATION_FAILED",
            "Fusion could not evaluate the parameter expression for the target unit.",
            details={"name": name, "expression": expression, "unit": target_unit},
        )

    next_comment = (
        previous["comment"]
        if existing is not None and comment is None
        else (comment or "")
    )
    base_audit = {
        "request_id": request_id,
        "mutation": "upsert_user_parameter",
        "name": name,
        "expression": expression,
        "unit": target_unit,
    }

    if (
        existing is not None
        and previous["expression"] == expression
        and previous["comment"] == next_comment
    ):
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
    created = None
    try:
        if document is not None:
            app.executeTextCommand('PTransaction.Start "Codex User Parameter"')
            transaction_started = True

        if existing is None:
            created = parameters.add(
                name,
                _value_input(expression, value_input_factory),
                target_unit,
                next_comment,
            )
            parameter = created
            action = "created"
        else:
            existing.expression = expression
            existing.comment = next_comment
            parameter = existing
            action = "updated"

        if design.computeAll() is False:
            raise _RecomputeFailure(
                "Fusion could not recompute the design after the parameter change."
            )

        if transaction_started:
            app.executeTextCommand("PTransaction.Commit")

        record_checkpoint(
            {
                "request_id": request_id,
                "mutation": "upsert_user_parameter",
                "document_id": document_id,
                "timeline_marker": timeline_marker,
            }
        )
        payload = {
            "action": action,
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
        if existing is not None and previous is not None:
            try:
                existing.expression = previous["expression"]
                existing.comment = previous["comment"]
            except Exception:
                pass
        elif created is not None:
            try:
                created.deleteMe()
            except Exception:
                pass

        code = (
            "RECOMPUTE_FAILED"
            if isinstance(error, _RecomputeFailure)
            else "PARAMETER_WRITE_FAILED"
        )
        message = (
            str(error)
            if isinstance(error, _RecomputeFailure)
            else "Fusion could not write the user parameter."
        )
        result = _error(
            code,
            message,
            retryable=True,
            details={
                "name": name,
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
