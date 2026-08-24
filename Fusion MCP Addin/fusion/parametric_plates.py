"""Atomic orchestration for one parameter-driven rectangular plate."""

import hashlib
from pathlib import Path
import tempfile
import time
import traceback

from ..core.audit import AuditLogger
from ..core.errors import MCPError
from ..core.results import tool_success
from .checkpoints import record_checkpoint
from .plate_builder import FusionPlateBuilder, PlateBuildFailure
from .plate_geometry import (
    PlateValidation,
    all_parameter_names,
    evaluate_plate_request,
    validate_plate_request,
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


def create_parametric_plate(
    app,
    name,
    parameter_prefix,
    width_expression,
    height_expression,
    thickness_expression,
    holes=None,
    edge_finish=None,
    *,
    builder_factory=FusionPlateBuilder,
    audit_logger=None,
):
    """Create a complete plate atomically from named driving parameters."""

    started_at = time.time()
    request_id = hashlib.sha256(
        f"{time.time_ns()}:{name}:{parameter_prefix}".encode("utf-8")
    ).hexdigest()[:16]
    logger = audit_logger or _default_audit_logger()
    base_audit = {
        "request_id": request_id,
        "mutation": "create_parametric_plate",
        "name": name if isinstance(name, str) else "",
        "parameter_prefix": parameter_prefix if isinstance(parameter_prefix, str) else "",
        "hole_count": len(holes) if isinstance(holes, list) else 0,
        "edge_finish": (
            edge_finish.get("type")
            if isinstance(edge_finish, dict)
            else "none"
        ),
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
        normalized = validate_plate_request(
            name,
            parameter_prefix,
            width_expression,
            height_expression,
            thickness_expression,
            holes=holes,
            edge_finish=edge_finish,
        )
        evaluated = evaluate_plate_request(normalized, units_manager)
    except PlateValidation as error:
        result = _error(error.code, error.message, details=error.details)
        return _audit_failure(logger, base_audit, result, started_at)

    generated_names = all_parameter_names(evaluated)
    collisions = [
        parameter_name
        for parameter_name in generated_names
        if parameters.itemByName(parameter_name) is not None
    ]
    if collisions:
        result = _error(
            "PLATE_PARAMETER_CONFLICT",
            "One or more generated user parameter names already exist.",
            details={"names": sorted(collisions)},
        )
        return _audit_failure(logger, base_audit, result, started_at)

    document = safe_value(app, "activeDocument")
    document_id = safe_value(document, "id") or safe_value(
        safe_value(design, "parentDocument"),
        "id",
    )
    timeline = safe_value(design, "timeline")
    timeline_marker = safe_value(timeline, "markerPosition")
    starting_counts, before_snapshot = _state_counts(design)
    builder = builder_factory(design, root)
    transaction_started = False
    created = None
    try:
        if document is not None:
            app.executeTextCommand('PTransaction.Start "Create Parametric Plate"')
            transaction_started = True

        created = builder.build(normalized["name"], evaluated)
        if design.computeAll() is False:
            raise _RecomputeFailure("Fusion could not recompute the parametric plate.")

        created_counts, after_snapshot = _state_counts(design)
        comparison = compare_snapshots(
            before_snapshot,
            after_snapshot,
            expected={
                "components_created": (
                    0 if created["container_mode"] == "root_part" else 1
                ),
                "bodies_created": 1,
            },
        )
        if not comparison["expectations_met"]:
            raise PlateBuildFailure(
                "verification",
                "PLATE_VERIFICATION_FAILED",
                "; ".join(comparison["mismatches"]),
            )

        if transaction_started:
            app.executeTextCommand("PTransaction.Commit")

        created_delta = {
            key: created_counts.get(key, 0) - starting_counts.get(key, 0)
            for key in sorted(set(starting_counts) | set(created_counts))
        }
        checkpoint = {
            "request_id": request_id,
            "mutation": "create_parametric_plate",
            "container_mode": created["container_mode"],
            "document_id": document_id,
            "timeline_marker": timeline_marker,
            "occurrence_entity_token": entity_token(created["occurrence"]),
            "component_entity_token": entity_token(created["component"]),
            "body_entity_token": entity_token(created["body"]),
            "feature_entity_tokens": [
                entity_token(feature)
                for feature in (
                    [created["extrusion"]]
                    + list(created["hole_features"])
                    + ([created["edge_feature"]] if created["edge_feature"] is not None else [])
                )
            ],
            "sketch_entity_tokens": [
                entity_token(sketch)
                for sketch in (
                    [created["profile_sketch"]]
                    + list(created["hole_sketches"])
                )
            ],
            "parameter_names": generated_names,
            "starting_counts": starting_counts,
            "created_counts": created_delta,
        }
        record_checkpoint(checkpoint)

        holes_result = []
        for hole, feature in zip(evaluated["holes"], created["hole_features"]):
            holes_result.append(
                {
                    "key": hole["key"],
                    "feature": safe_value(feature, "name", ""),
                    "entity_token": entity_token(feature),
                    "center_mm": [hole["x_mm"], hole["y_mm"]],
                    "diameter_mm": hole["diameter_mm"],
                }
            )
        edge_result = {"type": evaluated["edge_finish"]["type"]}
        if evaluated["edge_finish"]["type"] != "none":
            edge_result["size_mm"] = evaluated["edge_finish"]["size_mm"]
            edge_result["feature"] = safe_value(created["edge_feature"], "name", "")

        payload = {
            "action": "created",
            "container_mode": created["container_mode"],
            "component": safe_value(created["component"], "name", normalized["name"]),
            "component_entity_token": entity_token(created["component"]),
            "body": safe_value(created["body"], "name", normalized["name"]),
            "body_summary": body_summary(created["body"]),
            "dimensions_mm": dict(evaluated["values_mm"]),
            "parameters_created": generated_names,
            "holes": holes_result,
            "edge_finish": edge_result,
            "recomputed": True,
            "checkpoint_recorded": True,
            "undo_label": "Create Parametric Plate",
        }
        payload["audit_logged"] = _audit(
            logger,
            {
                **base_audit,
                "dimensions_mm": payload["dimensions_mm"],
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
                "Fusion could not completely remove the failed parametric plate.",
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
        elif isinstance(error, PlateBuildFailure):
            result = _error(
                error.code,
                error.message,
                retryable=True,
                details={"stage": error.stage, "rollback": rollback},
            )
        else:
            result = _error(
                "PLATE_COMPONENT_WRITE_FAILED",
                "Fusion could not create the parametric plate.",
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
