"""Safe explicit constant-radius fillet operations for Fusion MCP tools."""

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


def _item_by_name(collection, name):
    getter = safe_value(collection, "itemByName")
    if callable(getter):
        return getter(name)
    return next(
        (item for item in iter_collection(collection) if safe_value(item, "name") == name),
        None,
    )


def _axis_values(point):
    if point is None:
        return None
    try:
        return tuple(float(safe_value(point, axis)) for axis in ("x", "y", "z"))
    except (TypeError, ValueError):
        return None


def _bounds(entity):
    box = safe_value(entity, "boundingBox")
    minimum = _axis_values(safe_value(box, "minPoint"))
    maximum = _axis_values(safe_value(box, "maxPoint"))
    return minimum, maximum


def _body_tolerance(body):
    minimum, maximum = _bounds(body)
    if minimum is None or maximum is None:
        return 1e-6
    span = max(abs(maximum[index] - minimum[index]) for index in range(3))
    return max(span * 1e-7, 1e-6)


def _matches_selector(edge, body_minimum, body_maximum, selector, tolerance):
    if selector == "all":
        return True
    edge_minimum, edge_maximum = _bounds(edge)
    if edge_minimum is None or edge_maximum is None:
        return False
    if selector == "top":
        return (
            abs(edge_minimum[2] - body_maximum[2]) <= tolerance
            and abs(edge_maximum[2] - body_maximum[2]) <= tolerance
        )
    if selector == "bottom":
        return (
            abs(edge_minimum[2] - body_minimum[2]) <= tolerance
            and abs(edge_maximum[2] - body_minimum[2]) <= tolerance
        )
    delta_x = abs(edge_maximum[0] - edge_minimum[0])
    delta_y = abs(edge_maximum[1] - edge_minimum[1])
    delta_z = abs(edge_maximum[2] - edge_minimum[2])
    return delta_x <= tolerance and delta_y <= tolerance and delta_z > tolerance


def _select_edges(body, selector):
    body_minimum, body_maximum = _bounds(body)
    if selector != "all" and (body_minimum is None or body_maximum is None):
        return []
    tolerance = _body_tolerance(body)
    return [
        edge
        for edge in iter_collection(safe_value(body, "edges"))
        if _matches_selector(
            edge,
            body_minimum,
            body_maximum,
            selector,
            tolerance,
        )
    ]


def _fusion_helpers(value_input_factory, object_collection_factory):
    if value_input_factory is not None and object_collection_factory is not None:
        return value_input_factory, object_collection_factory

    import adsk.core

    return (
        value_input_factory or adsk.core.ValueInput.createByString,
        object_collection_factory or adsk.core.ObjectCollection.create,
    )


def create_fillet(
    app,
    name,
    body_name,
    radius_expression,
    edge_selector="all",
    tangent_chain=True,
    value_input_factory=None,
    object_collection_factory=None,
    audit_logger=None,
):
    """Create one constant-radius fillet on a stable edge group of a named body."""

    started_at = time.time()
    request_id = hashlib.sha256(
        f"{time.time_ns()}:{name}:{body_name}".encode("utf-8")
    ).hexdigest()[:16]
    logger = audit_logger or _default_audit_logger()

    if not isinstance(name, str) or not name.strip():
        return _error("INVALID_REQUEST", "name must be a non-empty string")
    if not isinstance(body_name, str) or not body_name.strip():
        return _error("INVALID_REQUEST", "body_name must be a non-empty string")
    if not isinstance(radius_expression, str) or not radius_expression.strip():
        return _error(
            "INVALID_REQUEST",
            "radius_expression must be a non-empty string",
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
    radius_expression = radius_expression.strip()

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
    fillets = safe_value(features, "filletFeatures")
    units_manager = safe_value(design, "unitsManager")
    if bodies is None or fillets is None or units_manager is None:
        return _error(
            "FUSION_API_ERROR",
            "The active component does not expose bodies, fillets, or units.",
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
    if _item_by_name(fillets, name) is not None:
        return _error(
            "FEATURE_NAME_CONFLICT",
            "A fillet feature with the requested name already exists.",
            details={"name": name},
        )

    target_unit = safe_value(units_manager, "defaultLengthUnits", "mm")
    try:
        radius = float(
            units_manager.evaluateExpression(radius_expression, target_unit)
        )
    except Exception:
        return _error(
            "FILLET_EXPRESSION_INVALID",
            "Fusion could not evaluate the fillet radius expression.",
            details={"radius_expression": radius_expression, "unit": target_unit},
        )
    if radius <= 0:
        return _error(
            "FILLET_RADIUS_INVALID",
            "Fillet radius must be greater than zero.",
            details={"radius_expression": radius_expression},
        )

    selected_edges = _select_edges(body, edge_selector)
    if not selected_edges:
        return _error(
            "FILLET_EDGES_NOT_FOUND",
            "No body edges matched the requested selector.",
            details={"body_name": body_name, "edge_selector": edge_selector},
        )

    value_input_factory, object_collection_factory = _fusion_helpers(
        value_input_factory,
        object_collection_factory,
    )
    base_audit = {
        "request_id": request_id,
        "mutation": "create_fillet",
        "name": name,
        "body_name": body_name,
        "radius_expression": radius_expression,
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
                raise RuntimeError("Fusion rejected a selected fillet edge.")

        if document is not None:
            app.executeTextCommand('PTransaction.Start "Codex Constant Radius Fillet"')
            transaction_started = True

        fillet_input = fillets.createInput()
        if fillet_input is None:
            raise RuntimeError("Fusion did not create a fillet input.")
        edge_set = fillet_input.edgeSetInputs.addConstantRadiusEdgeSet(
            edge_collection,
            value_input_factory(radius_expression),
            tangent_chain,
        )
        if edge_set is None:
            raise RuntimeError("Fusion rejected the constant-radius fillet edge set.")
        feature = fillets.add(fillet_input)
        if feature is None:
            raise RuntimeError("Fusion did not create the fillet feature.")
        feature.name = name

        if design.computeAll() is False:
            raise _RecomputeFailure(
                "Fusion could not recompute the design after creating the fillet."
            )
        if transaction_started:
            app.executeTextCommand("PTransaction.Commit")

        record_checkpoint(
            {
                "request_id": request_id,
                "mutation": "create_fillet",
                "document_id": document_id,
                "timeline_marker": timeline_marker,
            }
        )
        payload = {
            "action": "created",
            "feature": {
                "name": safe_value(feature, "name", name),
                "entity_token": entity_token(feature),
                "type": "constant_radius_fillet",
            },
            "target_body": body_summary(body),
            "radius_expression": radius_expression,
            "evaluated_radius_mm": round(radius * 10.0, 6),
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
            else "FILLET_WRITE_FAILED"
        )
        message = (
            str(error)
            if isinstance(error, _RecomputeFailure)
            else "Fusion could not create the fillet."
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
