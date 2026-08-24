"""Pure request and geometry validation for parametric profile extrusion."""

import math
import re
import unicodedata

from .units import parse_length_expression


IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
VERTEX_KEYS = {"key", "x_expression", "y_expression"}
_GEOMETRY_TOLERANCE_CM = 1e-9


class ProfileValidation(ValueError):
    """Structured validation failure raised before Fusion mutation."""

    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _invalid(message, details=None):
    raise ProfileValidation("INVALID_REQUEST", message, details)


def _required_string(value, field):
    if not isinstance(value, str) or not value.strip():
        _invalid(f"{field} must be a non-empty string", {"field": field})
    return value.strip()


def validate_profile_request(name, parameter_prefix, vertices, depth_expression):
    """Normalize and strictly validate the JSON-shaped profile request."""

    normalized_name = _required_string(name, "name")
    if any(unicodedata.category(character) == "Cc" for character in normalized_name):
        _invalid("name must not contain control characters", {"field": "name"})

    normalized_prefix = _required_string(parameter_prefix, "parameter_prefix")
    if not IDENTIFIER.fullmatch(normalized_prefix):
        _invalid(
            "parameter_prefix must be a safe Fusion identifier",
            {"field": "parameter_prefix"},
        )

    if not isinstance(vertices, list):
        _invalid("vertices must be an array", {"field": "vertices"})
    if not 3 <= len(vertices) <= 32:
        _invalid(
            "vertices must contain between 3 and 32 items",
            {"vertex_count": len(vertices)},
        )

    normalized_vertices = []
    seen_keys = set()
    for index, vertex in enumerate(vertices):
        if not isinstance(vertex, dict):
            _invalid("each vertex must be an object", {"vertex_index": index})
        if set(vertex) != VERTEX_KEYS:
            _invalid(
                "each vertex must contain only key, x_expression, and y_expression",
                {
                    "vertex_index": index,
                    "missing": sorted(VERTEX_KEYS - set(vertex)),
                    "unknown": sorted(set(vertex) - VERTEX_KEYS),
                },
            )
        key = _required_string(vertex.get("key"), f"vertices[{index}].key")
        if not IDENTIFIER.fullmatch(key):
            _invalid("vertex key must be a safe Fusion identifier", {"vertex_index": index})
        if key in seen_keys:
            _invalid("vertex keys must be unique", {"key": key})
        seen_keys.add(key)
        normalized_vertices.append(
            {
                "key": key,
                "x_expression": _required_string(
                    vertex.get("x_expression"),
                    f"vertices[{index}].x_expression",
                ),
                "y_expression": _required_string(
                    vertex.get("y_expression"),
                    f"vertices[{index}].y_expression",
                ),
            }
        )

    return {
        "name": normalized_name,
        "parameter_prefix": normalized_prefix,
        "vertices": normalized_vertices,
        "depth_expression": _required_string(depth_expression, "depth_expression"),
    }


def generated_profile_parameter_names(normalized):
    """Return every generated profile parameter name in request order."""

    prefix = normalized["parameter_prefix"]
    return {
        "depth": f"{prefix}_depth",
        "vertices": {
            vertex["key"]: {
                "x": f"{prefix}_{vertex['key']}_x",
                "y": f"{prefix}_{vertex['key']}_y",
            }
            for vertex in normalized["vertices"]
        },
    }


def _evaluate(expression, field, units_manager):
    try:
        return parse_length_expression(expression, units_manager)
    except Exception as error:
        raise ProfileValidation(
            "PROFILE_EXPRESSION_INVALID",
            "Fusion could not evaluate a profile length expression.",
            {"field": field, "expression": expression},
        ) from error


def _points_equal(left, right):
    return math.isclose(left[0], right[0], abs_tol=_GEOMETRY_TOLERANCE_CM) and math.isclose(
        left[1], right[1], abs_tol=_GEOMETRY_TOLERANCE_CM
    )


def _orientation(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a, b, point):
    return (
        min(a[0], b[0]) - _GEOMETRY_TOLERANCE_CM
        <= point[0]
        <= max(a[0], b[0]) + _GEOMETRY_TOLERANCE_CM
        and min(a[1], b[1]) - _GEOMETRY_TOLERANCE_CM
        <= point[1]
        <= max(a[1], b[1]) + _GEOMETRY_TOLERANCE_CM
    )


def _segments_intersect(a, b, c, d):
    orientations = (
        _orientation(a, b, c),
        _orientation(a, b, d),
        _orientation(c, d, a),
        _orientation(c, d, b),
    )
    signs = [
        0 if abs(value) <= _GEOMETRY_TOLERANCE_CM else (1 if value > 0 else -1)
        for value in orientations
    ]
    if signs[0] != signs[1] and signs[2] != signs[3]:
        return True
    return any(
        sign == 0 and _on_segment(start, end, point)
        for sign, start, end, point in (
            (signs[0], a, b, c),
            (signs[1], a, b, d),
            (signs[2], c, d, a),
            (signs[3], c, d, b),
        )
    )


def _validate_simple_polygon(points):
    count = len(points)
    for index, point in enumerate(points):
        next_point = points[(index + 1) % count]
        if _points_equal(point, next_point):
            raise ProfileValidation(
                "PROFILE_VERTEX_DUPLICATE",
                "Adjacent profile vertices must have distinct coordinates.",
                {"edge_index": index},
            )

    for left_index in range(count):
        left_next = (left_index + 1) % count
        for right_index in range(left_index + 1, count):
            right_next = (right_index + 1) % count
            if (
                left_index == right_index
                or left_next == right_index
                or right_next == left_index
            ):
                continue
            if _segments_intersect(
                points[left_index],
                points[left_next],
                points[right_index],
                points[right_next],
            ):
                raise ProfileValidation(
                    "PROFILE_SELF_INTERSECTION",
                    "Nonadjacent profile edges must not intersect or touch.",
                    {"edge_indices": [left_index, right_index]},
                )

    signed_double_area = sum(
        point[0] * points[(index + 1) % count][1]
        - points[(index + 1) % count][0] * point[1]
        for index, point in enumerate(points)
    )
    area_cm2 = abs(signed_double_area) / 2.0
    if area_cm2 <= _GEOMETRY_TOLERANCE_CM:
        raise ProfileValidation(
            "PROFILE_AREA_INVALID",
            "The closed profile must have a nonzero area.",
            {"evaluated_area_mm2": round(area_cm2 * 100.0, 6)},
        )
    return area_cm2


def evaluate_profile_request(normalized, units_manager):
    """Evaluate dimensions and reject invalid or self-intersecting polygons."""

    depth_cm = _evaluate(
        normalized["depth_expression"],
        "depth_expression",
        units_manager,
    )
    if depth_cm <= 0:
        raise ProfileValidation(
            "PROFILE_DEPTH_INVALID",
            "Profile extrusion depth must be greater than zero.",
            {"evaluated_depth_mm": round(depth_cm * 10.0, 6)},
        )

    evaluated_vertices = []
    points = []
    for index, vertex in enumerate(normalized["vertices"]):
        x_cm = _evaluate(
            vertex["x_expression"],
            f"vertices[{index}].x_expression",
            units_manager,
        )
        y_cm = _evaluate(
            vertex["y_expression"],
            f"vertices[{index}].y_expression",
            units_manager,
        )
        points.append((x_cm, y_cm))
        evaluated_vertices.append(
            {
                **vertex,
                "x_cm": x_cm,
                "y_cm": y_cm,
                "point_mm": [round(x_cm * 10.0, 6), round(y_cm * 10.0, 6)],
            }
        )

    area_cm2 = _validate_simple_polygon(points)
    return {
        **normalized,
        "depth_cm": depth_cm,
        "depth_mm": round(depth_cm * 10.0, 6),
        "area_cm2": area_cm2,
        "area_mm2": round(area_cm2 * 100.0, 6),
        "vertices": evaluated_vertices,
        "parameter_names": generated_profile_parameter_names(normalized),
    }


def all_profile_parameter_names(evaluated):
    """Flatten generated names in deterministic dependency order."""

    names = evaluated["parameter_names"]
    flattened = [names["depth"]]
    for vertex in evaluated["vertices"]:
        vertex_names = names["vertices"][vertex["key"]]
        flattened.extend([vertex_names["x"], vertex_names["y"]])
    return flattened
