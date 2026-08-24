"""Fusion status and bounded active-design context serialization."""

from pathlib import Path

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


def get_status(app, server_version="2.0.0"):
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


def _model_parameter_summary(parameter, component):
    owner = safe_value(parameter, "createdBy")
    return {
        "name": safe_value(parameter, "name", ""),
        "expression": safe_value(parameter, "expression", ""),
        "unit": safe_value(parameter, "unit", ""),
        "role": safe_value(parameter, "role", ""),
        "component": safe_value(component, "name", ""),
        "created_by": {
            "name": safe_value(owner, "name", ""),
            "type": safe_value(owner, "objectType") or type(owner).__name__,
            "entity_token": entity_token(owner),
        },
    }


def _canvas_plane(canvas, component):
    planar_entity = safe_value(canvas, "planarEntity")
    for plane, attribute in (
        ("xy", "xYConstructionPlane"),
        ("xz", "xZConstructionPlane"),
        ("yz", "yZConstructionPlane"),
    ):
        if planar_entity is safe_value(component, attribute):
            return plane
    return "unknown"


def _canvas_summary(canvas, component):
    transform = safe_value(canvas, "transform")
    center_x = center_y = width = height = None
    if transform is not None:
        try:
            origin, x_axis, y_axis = transform.getAsCoordinateSystem()
            center_x = round(float(safe_value(origin, "x", 0.0)) * 10.0, 6)
            center_y = round(float(safe_value(origin, "y", 0.0)) * 10.0, 6)
            width = round(abs(float(safe_value(x_axis, "length", 0.0))) * 10.0, 6)
            height = round(abs(float(safe_value(y_axis, "length", 0.0))) * 10.0, 6)
        except Exception:
            pass
    image_filename = safe_value(canvas, "imageFilename", "")
    return {
        "name": safe_value(canvas, "name", ""),
        "entity_token": entity_token(canvas),
        "image_name": Path(str(image_filename)).name if image_filename else "",
        "plane": _canvas_plane(canvas, component),
        "width_mm": width,
        "height_mm": height,
        "center_x_mm": center_x,
        "center_y_mm": center_y,
        "opacity": safe_value(canvas, "opacity"),
        "selectable": bool(safe_value(canvas, "isSelectable", False)),
    }


def _component_summary(component, limiter):
    bodies = []
    for body in iter_collection(safe_value(component, "bRepBodies")):
        if not limiter.take():
            break
        bodies.append(body_summary(body))
    canvases_collection = safe_value(component, "canvases")
    canvases = []
    for canvas in iter_collection(canvases_collection):
        if not limiter.take():
            break
        canvases.append(_canvas_summary(canvas, component))
    return {
        "name": safe_value(component, "name", ""),
        "entity_token": entity_token(component),
        "bodies": bodies,
        "canvases": canvases,
        "canvas_count": safe_value(canvases_collection, "count", 0),
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
    model_parameters = []

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

    if scope in {"parameters", "all"}:
        for component in iter_collection(safe_value(design, "allComponents")):
            for parameter in iter_collection(safe_value(component, "modelParameters")):
                if not limiter.take():
                    break
                model_parameters.append(
                    _model_parameter_summary(parameter, component)
                )
            if limiter.truncated:
                break

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
        "model_parameters": model_parameters,
        "scope": scope,
        "limit": limit,
        "truncated": limiter.truncated,
    }
