"""Pure validation for drawing-derived modeling plans."""

import math
import re

from .plate_geometry import (
    PlateValidation,
    evaluate_plate_request,
    validate_plate_request,
)
from .profile_geometry import (
    ProfileValidation,
    evaluate_profile_request,
    validate_profile_request,
)


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PLANES = {"xy", "xz", "yz"}
_PLANE_AXES = {"xy": ("x", "y"), "xz": ("x", "z"), "yz": ("y", "z")}
_SOURCES = {"stated", "estimated", "missing"}
_VIEW_KEYS = {
    "plane",
    "width_mm",
    "height_mm",
    "width_source",
    "height_source",
}
_PLATE_KEYS = {
    "type",
    "width_mm",
    "height_mm",
    "thickness_mm",
    "holes",
    "edge_finish",
}
_HOLE_KEYS = {"key", "x_mm", "y_mm", "diameter_mm"}
_PROFILE_KEYS = {"type", "vertices", "depth_mm"}
_VERTEX_KEYS = {"key", "x_mm", "y_mm"}


class DrawingPlanValidation(ValueError):
    """Structured drawing-plan failure raised before Fusion mutation."""

    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class _MillimeterUnitsManager:
    """Evaluate the planner's own normalized millimeter literals."""

    _LITERAL = re.compile(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+)) mm$")

    def evaluateExpression(self, expression, unit):
        if unit != "cm":
            raise ValueError("drawing-plan expressions are evaluated only to cm")
        match = self._LITERAL.fullmatch(expression)
        if match is None:
            raise ValueError("drawing-plan expression must be a millimeter literal")
        return float(match.group(1)) / 10.0


def _invalid(message, details=None):
    raise DrawingPlanValidation("INVALID_REQUEST", message, details)


def _required_string(value, field):
    if not isinstance(value, str) or not value.strip():
        _invalid(f"{field} must be a non-empty string.", {"field": field})
    return value.strip()


def _finite_number(value, field, *, positive=False, nullable=False):
    if value is None and nullable:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        _invalid(f"{field} must be a finite number.", {"field": field})
    normalized = float(value)
    if positive and normalized <= 0:
        _invalid(f"{field} must be greater than zero.", {"field": field})
    return normalized


def _mm_expression(value):
    rounded = round(float(value), 6)
    text = f"{rounded:.6f}".rstrip("0").rstrip(".")
    if text == "-0":
        text = "0"
    return f"{text} mm"


def _missing_blocker(field):
    return {
        "code": "MISSING_DIMENSION",
        "field": field,
        "message": "A required drawing dimension is missing.",
    }


def _normalize_views(views, tolerance_mm):
    if not isinstance(views, list) or not 1 <= len(views) <= 3:
        _invalid("views must contain one through three principal views.")
    tolerance = _finite_number(
        tolerance_mm,
        "dimension_tolerance_mm",
        positive=True,
    )
    if tolerance > 10.0:
        _invalid("dimension_tolerance_mm must not exceed 10.0.")

    normalized = []
    seen_planes = set()
    evidence = {"stated": 0, "estimated": 0, "missing": 0}
    blockers = []
    axis_values = {"x": [], "y": [], "z": []}
    stated_axis_values = {"x": [], "y": [], "z": []}
    for index, source_view in enumerate(views):
        if not isinstance(source_view, dict) or set(source_view) != _VIEW_KEYS:
            keys = set(source_view) if isinstance(source_view, dict) else set()
            _invalid(
                "Each view must contain only the five supported fields.",
                {
                    "view_index": index,
                    "missing": sorted(_VIEW_KEYS - keys),
                    "unknown": sorted(keys - _VIEW_KEYS),
                },
            )
        plane = _required_string(source_view["plane"], f"views[{index}].plane").lower()
        if plane not in _PLANES:
            _invalid("plane must be one of: xy, xz, yz.", {"view_index": index})
        if plane in seen_planes:
            _invalid("Each principal view plane may appear only once.", {"plane": plane})
        seen_planes.add(plane)

        view = {"plane": plane}
        axes = _PLANE_AXES[plane]
        for local_name, axis in zip(("width", "height"), axes):
            value_field = f"{local_name}_mm"
            source_field = f"{local_name}_source"
            dimension_source = _required_string(
                source_view[source_field],
                f"views[{index}].{source_field}",
            ).lower()
            if dimension_source not in _SOURCES:
                _invalid(
                    f"{source_field} must be stated, estimated, or missing.",
                    {"view_index": index, "field": source_field},
                )
            value = _finite_number(
                source_view[value_field],
                f"views[{index}].{value_field}",
                positive=True,
                nullable=dimension_source == "missing",
            )
            if dimension_source == "missing" and value is not None:
                _invalid(
                    "A missing dimension must use a null value.",
                    {"view_index": index, "field": value_field},
                )
            if dimension_source != "missing" and value is None:
                _invalid(
                    "A stated or estimated dimension requires a numeric value.",
                    {"view_index": index, "field": value_field},
                )
            view[value_field] = value
            view[source_field] = dimension_source
            evidence[dimension_source] += 1
            field_path = f"views[{index}].{value_field}"
            if dimension_source == "estimated":
                blockers.append(
                    {
                        "code": "ESTIMATED_DIMENSION",
                        "field": field_path,
                        "message": "Estimated dimensions cannot drive exact modeling.",
                    }
                )
            elif dimension_source == "missing":
                blockers.append(_missing_blocker(field_path))
            if value is not None:
                axis_values[axis].append((plane, value))
                if dimension_source == "stated":
                    stated_axis_values[axis].append((plane, value))
        normalized.append(view)

    axes_mm = {}
    checks = []
    for axis in ("x", "y", "z"):
        values = axis_values[axis]
        if not values:
            continue
        numeric = [item[1] for item in values]
        axes_mm[axis] = round(sum(numeric) / len(numeric), 6)
        if len(values) > 1:
            difference = max(numeric) - min(numeric)
            check = {
                "axis": axis,
                "planes": [item[0] for item in values],
                "values_mm": [round(value, 6) for value in numeric],
                "difference_mm": round(difference, 6),
                "tolerance_mm": round(tolerance, 6),
                "matched": difference <= tolerance,
            }
            checks.append(check)
            if not check["matched"]:
                raise DrawingPlanValidation(
                    "DRAWING_DIMENSION_MISMATCH",
                    f"Drawing views disagree on the shared {axis.upper()} dimension.",
                    check,
                )
    stated_axes_mm = {
        axis: round(sum(item[1] for item in values) / len(values), 6)
        for axis, values in stated_axis_values.items()
        if values
    }
    return normalized, tolerance, evidence, blockers, axes_mm, stated_axes_mm, checks


def _normalize_unsupported_features(features):
    requested = [] if features is None else features
    if not isinstance(requested, list) or len(requested) > 16:
        _invalid("unsupported_features must be an array with at most 16 items.")
    normalized = []
    for index, value in enumerate(requested):
        feature = _required_string(value, f"unsupported_features[{index}]")
        if feature not in normalized:
            normalized.append(feature)
    return normalized


def _normalize_plate(geometry, blockers):
    if set(geometry) != _PLATE_KEYS:
        _invalid(
            "Plate geometry fields do not match the drawing-plan contract.",
            {
                "missing": sorted(_PLATE_KEYS - set(geometry)),
                "unknown": sorted(set(geometry) - _PLATE_KEYS),
            },
        )
    normalized = {"type": "plate"}
    for field in ("width_mm", "height_mm", "thickness_mm"):
        value = _finite_number(geometry[field], f"geometry.{field}", positive=True, nullable=True)
        normalized[field] = value
        if value is None:
            blockers.append(_missing_blocker(f"geometry.{field}"))

    holes = geometry["holes"]
    if not isinstance(holes, list) or len(holes) > 32:
        _invalid("geometry.holes must be an array with at most 32 items.")
    normalized_holes = []
    seen_keys = set()
    for index, source_hole in enumerate(holes):
        if not isinstance(source_hole, dict) or set(source_hole) != _HOLE_KEYS:
            _invalid("Each drawing-plan hole must contain only the supported fields.", {"hole_index": index})
        key = _required_string(source_hole["key"], f"geometry.holes[{index}].key")
        if not _IDENTIFIER.fullmatch(key) or key in seen_keys:
            _invalid("Hole keys must be unique safe identifiers.", {"hole_index": index})
        seen_keys.add(key)
        hole = {"key": key}
        for field in ("x_mm", "y_mm", "diameter_mm"):
            value = _finite_number(
                source_hole[field],
                f"geometry.holes[{index}].{field}",
                positive=field == "diameter_mm",
                nullable=True,
            )
            hole[field] = value
            if value is None:
                blockers.append(_missing_blocker(f"geometry.holes[{index}].{field}"))
        normalized_holes.append(hole)
    normalized["holes"] = normalized_holes

    edge = geometry["edge_finish"]
    if not isinstance(edge, dict) or edge.get("type") not in {"none", "fillet", "chamfer"}:
        _invalid("geometry.edge_finish.type must be none, fillet, or chamfer.")
    edge_type = edge["type"]
    expected = {"type"} if edge_type == "none" else {"type", "size_mm"}
    if set(edge) != expected:
        _invalid("Drawing-plan edge-finish fields do not match its type.")
    normalized_edge = {"type": edge_type}
    if edge_type != "none":
        size = _finite_number(edge["size_mm"], "geometry.edge_finish.size_mm", positive=True, nullable=True)
        normalized_edge["size_mm"] = size
        if size is None:
            blockers.append(_missing_blocker("geometry.edge_finish.size_mm"))
    normalized["edge_finish"] = normalized_edge
    return normalized


def _normalize_profile(geometry, blockers):
    if set(geometry) != _PROFILE_KEYS:
        _invalid(
            "Straight-profile geometry fields do not match the drawing-plan contract.",
            {
                "missing": sorted(_PROFILE_KEYS - set(geometry)),
                "unknown": sorted(set(geometry) - _PROFILE_KEYS),
            },
        )
    vertices = geometry["vertices"]
    if not isinstance(vertices, list) or not 3 <= len(vertices) <= 32:
        _invalid("geometry.vertices must contain between 3 and 32 items.")
    normalized_vertices = []
    seen_keys = set()
    for index, source_vertex in enumerate(vertices):
        if not isinstance(source_vertex, dict) or set(source_vertex) != _VERTEX_KEYS:
            _invalid("Each drawing-plan vertex must contain only the supported fields.", {"vertex_index": index})
        key = _required_string(source_vertex["key"], f"geometry.vertices[{index}].key")
        if not _IDENTIFIER.fullmatch(key) or key in seen_keys:
            _invalid("Vertex keys must be unique safe identifiers.", {"vertex_index": index})
        seen_keys.add(key)
        vertex = {"key": key}
        for field in ("x_mm", "y_mm"):
            value = _finite_number(source_vertex[field], f"geometry.vertices[{index}].{field}", nullable=True)
            vertex[field] = value
            if value is None:
                blockers.append(_missing_blocker(f"geometry.vertices[{index}].{field}"))
        normalized_vertices.append(vertex)
    depth = _finite_number(geometry["depth_mm"], "geometry.depth_mm", positive=True, nullable=True)
    if depth is None:
        blockers.append(_missing_blocker("geometry.depth_mm"))
    return {"type": "straight_profile", "vertices": normalized_vertices, "depth_mm": depth}


def _check_model_axes(stated_axes_mm, model_axes_mm, tolerance_mm):
    for axis, drawing_value in stated_axes_mm.items():
        model_value = model_axes_mm.get(axis)
        if model_value is None:
            continue
        difference = abs(float(drawing_value) - float(model_value))
        if difference > tolerance_mm:
            raise DrawingPlanValidation(
                "DRAWING_MODEL_DIMENSION_MISMATCH",
                f"The proposed model disagrees with the stated {axis.upper()} drawing dimension.",
                {
                    "axis": axis,
                    "drawing_mm": round(drawing_value, 6),
                    "model_mm": round(model_value, 6),
                    "difference_mm": round(difference, 6),
                    "tolerance_mm": round(tolerance_mm, 6),
                },
            )


def _plate_tool_call(name, prefix, geometry):
    holes = [
        {
            "key": hole["key"],
            "x_expression": _mm_expression(hole["x_mm"]),
            "y_expression": _mm_expression(hole["y_mm"]),
            "diameter_expression": _mm_expression(hole["diameter_mm"]),
        }
        for hole in geometry["holes"]
    ]
    edge = {"type": geometry["edge_finish"]["type"]}
    if edge["type"] != "none":
        edge["size_expression"] = _mm_expression(geometry["edge_finish"]["size_mm"])
    arguments = {
        "name": name,
        "parameter_prefix": prefix,
        "width_expression": _mm_expression(geometry["width_mm"]),
        "height_expression": _mm_expression(geometry["height_mm"]),
        "thickness_expression": _mm_expression(geometry["thickness_mm"]),
        "holes": holes,
        "edge_finish": edge,
    }
    try:
        normalized = validate_plate_request(**arguments)
        evaluated = evaluate_plate_request(normalized, _MillimeterUnitsManager())
    except PlateValidation as error:
        raise DrawingPlanValidation(error.code, error.message, error.details) from error
    return arguments, {
        "type": "plate",
        "size_mm": [
            evaluated["values_mm"]["width"],
            evaluated["values_mm"]["height"],
            evaluated["values_mm"]["thickness"],
        ],
        "hole_count": len(evaluated["holes"]),
        "edge_finish": evaluated["edge_finish"]["type"],
    }


def _profile_tool_call(name, prefix, geometry):
    vertices = [
        {
            "key": vertex["key"],
            "x_expression": _mm_expression(vertex["x_mm"]),
            "y_expression": _mm_expression(vertex["y_mm"]),
        }
        for vertex in geometry["vertices"]
    ]
    arguments = {
        "name": name,
        "parameter_prefix": prefix,
        "vertices": vertices,
        "depth_expression": _mm_expression(geometry["depth_mm"]),
    }
    try:
        normalized = validate_profile_request(**arguments)
        evaluated = evaluate_profile_request(normalized, _MillimeterUnitsManager())
    except ProfileValidation as error:
        raise DrawingPlanValidation(error.code, error.message, error.details) from error
    x_values = [vertex["point_mm"][0] for vertex in evaluated["vertices"]]
    y_values = [vertex["point_mm"][1] for vertex in evaluated["vertices"]]
    size_mm = [max(x_values) - min(x_values), max(y_values) - min(y_values), evaluated["depth_mm"]]
    return arguments, {
        "type": "straight_profile",
        "size_mm": [round(value, 6) for value in size_mm],
        "vertex_count": len(vertices),
        "profile_area_mm2": evaluated["area_mm2"],
    }


def validate_drawing_modeling_plan(
    name,
    parameter_prefix,
    views,
    geometry,
    dimension_tolerance_mm=0.25,
    unsupported_features=None,
):
    """Validate a drawing plan without reading images or mutating Fusion."""

    normalized_name = _required_string(name, "name")
    normalized_prefix = _required_string(parameter_prefix, "parameter_prefix")
    if not _IDENTIFIER.fullmatch(normalized_prefix):
        _invalid("parameter_prefix must be a safe Fusion identifier.")
    (
        normalized_views,
        tolerance,
        evidence,
        blockers,
        axes_mm,
        stated_axes_mm,
        checks,
    ) = _normalize_views(views, dimension_tolerance_mm)
    features = _normalize_unsupported_features(unsupported_features)
    for feature in features:
        blockers.append(
            {
                "code": "UNSUPPORTED_FEATURE",
                "feature": feature,
                "message": "The proposed drawing feature has no approved explicit modeling route.",
            }
        )

    if not isinstance(geometry, dict):
        _invalid("geometry must be an object.")
    geometry_type = geometry.get("type")
    if geometry_type == "plate":
        normalized_geometry = _normalize_plate(geometry, blockers)
    elif geometry_type == "straight_profile":
        normalized_geometry = _normalize_profile(geometry, blockers)
    else:
        _invalid("geometry.type must be plate or straight_profile.")

    for axis in ("x", "y", "z"):
        if axis not in stated_axes_mm:
            blockers.append(_missing_blocker(f"drawing.axes.{axis}"))

    target_tool = None
    tool_arguments = None
    geometry_summary = None
    if not blockers:
        if geometry_type == "plate":
            tool_arguments, geometry_summary = _plate_tool_call(
                normalized_name,
                normalized_prefix,
                normalized_geometry,
            )
            target_tool = "create_parametric_plate"
        else:
            tool_arguments, geometry_summary = _profile_tool_call(
                normalized_name,
                normalized_prefix,
                normalized_geometry,
            )
            target_tool = "create_parametric_profile_extrusion"
        size = geometry_summary["size_mm"]
        _check_model_axes(
            stated_axes_mm,
            {"x": size[0], "y": size[1], "z": size[2]},
            tolerance,
        )

    return {
        "action": "validated",
        "name": normalized_name,
        "parameter_prefix": normalized_prefix,
        "ready_for_modeling": not blockers,
        "mutation_performed": False,
        "views": normalized_views,
        "dimension_evidence": evidence,
        "axes_mm": axes_mm,
        "shared_dimension_checks": checks,
        "blockers": blockers,
        "target_tool": target_tool,
        "tool_arguments": tool_arguments,
        "geometry_summary": geometry_summary,
    }
