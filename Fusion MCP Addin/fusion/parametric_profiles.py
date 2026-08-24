"""Atomic orchestration for one parameter-driven profile extrusion."""

import hashlib
from pathlib import Path
import tempfile
import time
import traceback

from ..core.audit import AuditLogger
from ..core.errors import MCPError
from ..core.results import tool_success
from .checkpoints import record_checkpoint
from .profile_builder import FusionProfileBuilder, ProfileBuildFailure
from .profile_geometry import (
    ProfileValidation,
    all_profile_parameter_names,
    evaluate_profile_request,
    validate_profile_request,
)
from .snapshot import (
    body_summary,
    capture_snapshot,
    compare_snapshots,
    entity_token,
    safe_value,
)


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


def _abort_transaction(app, started):
    if not started:
        return
    try:
        app.executeTextCommand("PTransaction.Abort")
    except Exception:
        pass


def _state_counts(design):
    snapshot = capture_snapshot(design)
    counts = dict(snapshot["counts"])
    counts["user_parameters"] = int(
        safe_value(safe_value(design, "userParameters"), "count", 0)
    )
    return counts, snapshot


def _audit_failure(logger, base_audit, result, started_at, include_traceback=False):
    event = {
        **base_audit,
        "result": result,
        "duration_ms": int((time.time() - started_at) * 1000),
    }
    if include_traceback:
        event["local_traceback"] = traceback.format_exc()
    _audit(logger, event)
    return result


def create_parametric_profile_extrusion(
    app,
    name,
    parameter_prefix,
    vertices,
    depth_expression,
    *,
    builder_factory=FusionProfileBuilder,
    audit_logger=None,
):
    """Create one complete profile extrusion from named driving parameters."""

    started_at = time.time()
    request_id = hashlib.sha256(
        f"{time.time_ns()}:{name}:{parameter_prefix}".encode("utf-8")
    ).hexdigest()[:16]
    logger = audit_logger or _default_audit_logger()
    base_audit = {
        "request_id": request_id,
        "mutation": "create_parametric_profile_extrusion",
        "name": name if isinstance(name, str) else "",
        "parameter_prefix": parameter_prefix if isinstance(parameter_prefix, str) else "",
        "vertex_count": len(vertices) if isinstance(vertices, list) else 0,
        "depth_expression": depth_expression if isinstance(depth_expression, str) else "",
    }

    design = safe_value(app, "activeProduct") if app is not None else None
    root = safe_value(design, "rootComponent")
    if design is None or root is None:
        result = _error(
            "NO_ACTIVE_DESIGN",
            "Open or create a Fusion design first.",
            retryable=True,
        )
        return _audit_failure(logger, base_audit, result, started_at)
    parameters = safe_value(design, "userParameters")
    units_manager = safe_value(design, "unitsManager")
    if parameters is None or units_manager is None:
        result = _error(
            "FUSION_API_ERROR",
            "The active design does not expose user parameters and units.",
            retryable=True,
        )
        return _audit_failure(logger, base_audit, result, started_at)

    try:
        normalized = validate_profile_request(
            name,
            parameter_prefix,
            vertices,
            depth_expression,
        )
        evaluated = evaluate_profile_request(normalized, units_manager)
    except ProfileValidation as error:
        result = _error(error.code, error.message, details=error.details)
        return _audit_failure(logger, base_audit, result, started_at)

    generated_names = all_profile_parameter_names(evaluated)
    collisions = [
        parameter_name
        for parameter_name in generated_names
        if parameters.itemByName(parameter_name) is not None
    ]
    if collisions:
        result = _error(
            "PROFILE_PARAMETER_CONFLICT",
            "One or more generated user parameter names already exist.",
            details={"names": sorted(collisions)},
        )
        return _audit_failure(logger, base_audit, result, started_at)

    document = safe_value(app, "activeDocument")
    document_id = safe_value(document, "id") or safe_value(
        safe_value(design, "parentDocument"), "id"
    )
    timeline_marker = safe_value(safe_value(design, "timeline"), "markerPosition")
    starting_counts, before_snapshot = _state_counts(design)
    builder = builder_factory(design, root)
    transaction_started = False
    created = None
    try:
        if document is not None:
            app.executeTextCommand('PTransaction.Start "Create Parametric Profile Extrusion"')
            transaction_started = True

        created = builder.build(normalized["name"], evaluated)
        if design.computeAll() is False:
            raise _RecomputeFailure(
                "Fusion could not recompute the parametric profile extrusion."
            )

        created_counts, after_snapshot = _state_counts(design)
        comparison = compare_snapshots(
            before_snapshot,
            after_snapshot,
            expected={
                "components_created": 0 if created["container_mode"] == "root_part" else 1,
                "bodies_created": 1,
            },
        )
        if not comparison["expectations_met"]:
            raise ProfileBuildFailure(
                "verification",
                "PROFILE_VERIFICATION_FAILED",
                "; ".join(comparison["mismatches"]),
            )

        if transaction_started:
            app.executeTextCommand("PTransaction.Commit")

        created_delta = {
            key: created_counts.get(key, 0) - starting_counts.get(key, 0)
            for key in sorted(set(starting_counts) | set(created_counts))
        }
        record_checkpoint(
            {
                "request_id": request_id,
                "mutation": "create_parametric_profile_extrusion",
                "container_mode": created["container_mode"],
                "document_id": document_id,
                "timeline_marker": timeline_marker,
                "occurrence_entity_token": entity_token(created["occurrence"]),
                "component_entity_token": entity_token(created["component"]),
                "body_entity_token": entity_token(created["body"]),
                "feature_entity_tokens": [entity_token(created["extrusion"])],
                "sketch_entity_tokens": [entity_token(created["profile_sketch"])],
                "parameter_names": generated_names,
                "starting_counts": starting_counts,
                "created_counts": created_delta,
            }
        )

        vertices_result = [
            {"key": vertex["key"], "point_mm": list(vertex["point_mm"])}
            for vertex in evaluated["vertices"]
        ]
        payload = {
            "action": "created",
            "container_mode": created["container_mode"],
            "component": safe_value(created["component"], "name", normalized["name"]),
            "component_entity_token": entity_token(created["component"]),
            "body": safe_value(created["body"], "name", normalized["name"]),
            "body_summary": body_summary(created["body"]),
            "depth_mm": evaluated["depth_mm"],
            "profile_area_mm2": evaluated["area_mm2"],
            "vertices_mm": vertices_result,
            "parameters_created": generated_names,
            "recomputed": True,
            "checkpoint_recorded": True,
            "undo_label": "Create Parametric Profile Extrusion",
        }
        payload["audit_logged"] = _audit(
            logger,
            {
                **base_audit,
                "depth_mm": payload["depth_mm"],
                "vertices_mm": vertices_result,
                "before_counts": starting_counts,
                "after_counts": created_counts,
                "result": payload,
                "duration_ms": int((time.time() - started_at) * 1000),
            },
        )
        return tool_success(payload)
    except Exception as error:
        _abort_transaction(app, transaction_started)
        current_counts, _snapshot = _state_counts(design)
        if transaction_started and current_counts == starting_counts:
            rollback = {
                "clean": True,
                "transaction_restored": True,
                "deleted_occurrence": False,
                "deleted_features": [],
                "deleted_sketches": [],
                "deleted_parameters": [],
                "errors": [],
            }
        else:
            rollback = builder.rollback()
            rollback["transaction_restored"] = False
            try:
                design.computeAll()
            except Exception:
                pass
            current_counts, _snapshot = _state_counts(design)
        counts_restored = current_counts == starting_counts
        if not rollback.get("clean") or not counts_restored:
            result = _error(
                "ROLLBACK_FAILED",
                "Fusion could not completely remove the failed parametric profile extrusion.",
                retryable=True,
                details={
                    "stage": safe_value(error, "stage", "rollback"),
                    "rollback": rollback,
                    "starting_counts": starting_counts,
                    "current_counts": current_counts,
                },
            )
        elif isinstance(error, _RecomputeFailure):
            result = _error(
                "RECOMPUTE_FAILED",
                str(error),
                retryable=True,
                details={"stage": "recompute", "rollback": rollback},
            )
        elif isinstance(error, ProfileBuildFailure):
            result = _error(
                error.code,
                error.message,
                retryable=True,
                details={"stage": error.stage, "rollback": rollback},
            )
        else:
            result = _error(
                "PROFILE_COMPONENT_WRITE_FAILED",
                "Fusion could not create the parametric profile extrusion.",
                retryable=True,
                details={"stage": "unknown", "rollback": rollback},
            )
        return _audit_failure(
            logger,
            {
                **base_audit,
                "before_counts": starting_counts,
                "after_counts": current_counts,
            },
            result,
            started_at,
            include_traceback=True,
        )
