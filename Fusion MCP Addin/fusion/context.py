"""Fusion status and bounded active-design context serialization."""

from .snapshot import body_summary, entity_token, iter_collection, safe_value


_SCOPES = {"summary", "components", "parameters", "all"}


class _Limiter:
    def __init__(self, limit):
        self.limit = limit
        self.used = 0
        self.truncated = False

    def take(self):
        if self.used >= self.limit:
            self.truncated = True
            return False
        self.used += 1
        return True


def _app_version(app):
    version = safe_value(app, "version")
    if version:
        return str(version)
    getter = safe_value(app, "getVersion")
    if callable(getter):
        try:
            return str(getter())
        except Exception:
            return None
    return None


def get_status(app, server_version="1.6.0"):
    if app is None:
        return {
            "fusion_available": False,
            "active_design": False,
            "server_version": server_version,
            "error": {
                "code": "FUSION_UNAVAILABLE",
                "message": "Fusion 360 is not available.",
                "retryable": True,
            },
        }

    design = safe_value(app, "activeProduct")
    has_design = design is not None and safe_value(design, "rootComponent") is not None
    return {
        "fusion_available": True,
        "fusion_version": _app_version(app),
        "server_version": server_version,
        "active_design": has_design,
        "document_name": safe_value(safe_value(app, "activeDocument"), "name"),
        "product_type": type(design).__name__ if design is not None else None,
        "transport": "streamable-http",
        "bind": "127.0.0.1:9100",
        "authenticated": True,
    }


def _parameter_summary(parameter):
    return {
        "name": safe_value(parameter, "name", ""),
        "expression": safe_value(parameter, "expression", ""),
        "unit": safe_value(parameter, "unit", ""),
    }


def _component_summary(component, limiter):
    bodies = []
    for body in iter_collection(safe_value(component, "bRepBodies")):
        if not limiter.take():
            break
        bodies.append(body_summary(body))
    return {
        "name": safe_value(component, "name", ""),
        "entity_token": entity_token(component),
        "bodies": bodies,
        "sketch_count": safe_value(safe_value(component, "sketches"), "count", 0),
        "feature_count": safe_value(safe_value(component, "features"), "count", 0),
    }


def build_design_context(app, scope="summary", limit=200):
    """Return a bounded, serializable view of the current active design."""

    if scope not in _SCOPES:
        raise ValueError("scope must be one of: summary, components, parameters, all")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
        raise ValueError("limit must be an integer from 1 through 1000")
    if app is None:
        raise ValueError("FUSION_UNAVAILABLE")
    design = safe_value(app, "activeProduct")
    if design is None or safe_value(design, "rootComponent") is None:
        raise ValueError("NO_ACTIVE_DESIGN")

    limiter = _Limiter(limit)
    components = []
    parameters = []

    if scope in {"summary", "components", "all"}:
        for component in iter_collection(safe_value(design, "allComponents")):
            if not limiter.take():
                break
            components.append(_component_summary(component, limiter))

    if scope in {"summary", "parameters", "all"}:
        for parameter in iter_collection(safe_value(design, "userParameters")):
            if not limiter.take():
                break
            parameters.append(_parameter_summary(parameter))

    units_manager = safe_value(design, "unitsManager")
    return {
        "document": {
            "id": safe_value(safe_value(app, "activeDocument"), "id"),
            "name": safe_value(safe_value(app, "activeDocument"), "name"),
            "saved": bool(safe_value(safe_value(app, "activeDocument"), "isSaved", False)),
        },
        "design_type": str(safe_value(design, "designType", "unknown")),
        "units": safe_value(units_manager, "defaultLengthUnits", "mm"),
        "active_component": safe_value(safe_value(design, "activeComponent"), "name"),
        "components": components,
        "parameters": parameters,
        "scope": scope,
        "limit": limit,
        "truncated": limiter.truncated,
    }
