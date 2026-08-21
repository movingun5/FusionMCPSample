"""Safe explicit equal-distance chamfer operations for Fusion MCP tools."""

import hashlib
from pathlib import Path
import tempfile
import time
import traceback

from ..core.audit import AuditLogger
from ..core.errors import MCPError
from ..core.results import tool_success
from .checkpoints import record_checkpoint
from .fillets import _fusion_helpers, _item_by_name, _select_edges
from .snapshot import body_summary, entity_token, safe_value


_EDGE_SELECTORS = {"all", "top", "bottom", "vertical"}


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


def create_chamfer(
    app,
    name,
    body_name,
    distance_expression,
    edge_selector="all",
    tangent_chain=True,
    value_input_factory=None,
    object_collection_factory=None,
    audit_logger=None,
):
    """Create one equal-distance chamfer on a stable edge group of a named body."""

    started_at = time.time()
    request_id = hashlib.sha256(
        f"{time.time_ns()}:{name}:{body_name}".encode("utf-8")
    ).hexdigest()[:16]
    logger = audit_logger or _default_audit_logger()

    if not isinstance(name, str) or not name.strip():
        return _error("INVALID_REQUEST", "name must be a non-empty string")
    if not isinstance(body_name, str) or not body_name.strip():
        return _error("INVALID_REQUEST", "body_name must be a non-empty string")
    if not isinstance(distance_expression, str) or not distance_expression.strip():
        return _error(
            "INVALID_REQUEST",
            "distance_expression must be a non-empty string",
        )
    if edge_selector not in _EDGE_SELECTORS:
        return _error(
            "INVALID_REQUEST",
            "edge_selector must be one of: all, top, bottom, vertical",
            details={"edge_selector": edge_selector},
        )
    if not isinstance(tangent_chain, bool):
        return _error("INVALID_REQUEST", "tangent_chain must be a boolean")
    name = name.strip()
    body_name = body_name.strip()
    distance_expression = distance_expression.strip()

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
    features = safe_value(component, "features")
    chamfers = safe_value(features, "chamferFeatures")
    units_manager = safe_value(design, "unitsManager")
    if bodies is None or chamfers is None or units_manager is None:
        return _error(
            "FUSION_API_ERROR",
            "The active component does not expose bodies, chamfers, or units.",
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
    if _item_by_name(chamfers, name) is not None:
        return _error(
            "FEATURE_NAME_CONFLICT",
            "A chamfer feature with the requested name already exists.",
            details={"name": name},
        )

    target_unit = safe_value(units_manager, "defaultLengthUnits", "mm")
    try:
        distance = float(
            units_manager.evaluateExpression(distance_expression, target_unit)
        )
    except Exception:
        return _error(
            "CHAMFER_EXPRESSION_INVALID",
            "Fusion could not evaluate the chamfer distance expression.",
            details={
                "distance_expression": distance_expression,
                "unit": target_unit,
            },
        )
    if distance <= 0:
        return _error(
            "CHAMFER_DISTANCE_INVALID",
            "Chamfer distance must be greater than zero.",
            details={"distance_expression": distance_expression},
        )

    selected_edges = _select_edges(body, edge_selector)
    if not selected_edges:
        return _error(
            "CHAMFER_EDGES_NOT_FOUND",
            "No body edges matched the requested selector.",
            details={"body_name": body_name, "edge_selector": edge_selector},
        )

    value_input_factory, object_collection_factory = _fusion_helpers(
        value_input_factory,
        object_collection_factory,
    )
    base_audit = {
        "request_id": request_id,
        "mutation": "create_chamfer",
        "name": name,
        "body_name": body_name,
        "distance_expression": distance_expression,
        "edge_selector": edge_selector,
        "tangent_chain": tangent_chain,
        "selected_edge_count": len(selected_edges),
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
        edge_collection = object_collection_factory()
        for edge in selected_edges:
            if edge_collection.add(edge) is False:
                raise RuntimeError("Fusion rejected a selected chamfer edge.")

        if document is not None:
            app.executeTextCommand('PTransaction.Start "Codex Equal Distance Chamfer"')
            transaction_started = True

        chamfer_input = chamfers.createInput2()
        if chamfer_input is None:
            raise RuntimeError("Fusion did not create a chamfer input.")
        edge_set_added = (
            chamfer_input.chamferEdgeSets.addEqualDistanceChamferEdgeSet(
                edge_collection,
                value_input_factory(distance_expression),
                tangent_chain,
            )
        )
        if edge_set_added is False:
            raise RuntimeError("Fusion rejected the equal-distance chamfer edge set.")
        feature = chamfers.add(chamfer_input)
        if feature is None:
            raise RuntimeError("Fusion did not create the chamfer feature.")
        feature.name = name

        if design.computeAll() is False:
            raise _RecomputeFailure(
                "Fusion could not recompute the design after creating the chamfer."
            )
        if transaction_started:
            app.executeTextCommand("PTransaction.Commit")

        record_checkpoint(
            {
                "request_id": request_id,
                "mutation": "create_chamfer",
                "document_id": document_id,
                "timeline_marker": timeline_marker,
            }
        )
        payload = {
            "action": "created",
            "feature": {
                "name": safe_value(feature, "name", name),
                "entity_token": entity_token(feature),
                "type": "equal_distance_chamfer",
            },
            "target_body": body_summary(body),
            "distance_expression": distance_expression,
            "evaluated_distance_mm": round(distance * 10.0, 6),
            "edge_selector": edge_selector,
            "selected_edge_count": len(selected_edges),
            "tangent_chain": tangent_chain,
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
            else "CHAMFER_WRITE_FAILED"
        )
        message = (
            str(error)
            if isinstance(error, _RecomputeFailure)
            else "Fusion could not create the chamfer."
        )
        result = _error(
            code,
            message,
            retryable=True,
            details={
                "name": name,
                "body_name": body_name,
                "edge_selector": edge_selector,
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
