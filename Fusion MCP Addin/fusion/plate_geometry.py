"""Pure request and geometry validation for parametric plate creation."""

import math
import re
import unicodedata

from .units import parse_length_expression


IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
HOLE_KEYS = {"key", "x_expression", "y_expression", "diameter_expression"}
EDGE_KEYS = {
    "none": {"type"},
    "fillet": {"type", "size_expression"},
    "chamfer": {"type", "size_expression"},
}
_GEOMETRY_TOLERANCE_CM = 1e-9


class PlateValidation(ValueError):
    """Structured validation failure raised before Fusion mutation."""

    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _invalid(message, details=None):
    raise PlateValidation("INVALID_REQUEST", message, details)


def _required_string(value, field):
    if not isinstance(value, str) or not value.strip():
        _invalid(f"{field} must be a non-empty string", {"field": field})
    return value.strip()


def validate_plate_request(
    name,
    parameter_prefix,
    width_expression,
    height_expression,
    thickness_expression,
    holes=None,
    edge_finish=None,
):
    """Normalize and strictly validate the JSON-shaped tool request."""

    normalized_name = _required_string(name, "name")
    if any(unicodedata.category(character) == "Cc" for character in normalized_name):
        _invalid("name must not contain control characters", {"field": "name"})

    normalized_prefix = _required_string(parameter_prefix, "parameter_prefix")
    if not IDENTIFIER.fullmatch(normalized_prefix):
        _invalid(
            "parameter_prefix must be a safe Fusion identifier",
            {"field": "parameter_prefix"},
        )

    expressions = {
        "width_expression": _required_string(width_expression, "width_expression"),
        "height_expression": _required_string(height_expression, "height_expression"),
        "thickness_expression": _required_string(
            thickness_expression,
            "thickness_expression",
        ),
    }

    requested_holes = [] if holes is None else holes
    if not isinstance(requested_holes, list):
        _invalid("holes must be an array", {"field": "holes"})
    if len(requested_holes) > 32:
        _invalid("holes must contain at most 32 items", {"hole_count": len(requested_holes)})

    normalized_holes = []
    seen_keys = set()
    for index, hole in enumerate(requested_holes):
        if not isinstance(hole, dict):
            _invalid("each hole must be an object", {"hole_index": index})
        if set(hole) != HOLE_KEYS:
            _invalid(
                "each hole must contain only key, x_expression, y_expression, and diameter_expression",
                {
                    "hole_index": index,
                    "missing": sorted(HOLE_KEYS - set(hole)),
                    "unknown": sorted(set(hole) - HOLE_KEYS),
                },
            )
        key = _required_string(hole.get("key"), f"holes[{index}].key")
        if not IDENTIFIER.fullmatch(key):
            _invalid("hole key must be a safe Fusion identifier", {"hole_index": index})
        if key in seen_keys:
            _invalid("hole keys must be unique", {"key": key})
        seen_keys.add(key)
        normalized_holes.append(
            {
                "key": key,
                "x_expression": _required_string(
                    hole.get("x_expression"),
                    f"holes[{index}].x_expression",
                ),
                "y_expression": _required_string(
                    hole.get("y_expression"),
                    f"holes[{index}].y_expression",
                ),
                "diameter_expression": _required_string(
                    hole.get("diameter_expression"),
                    f"holes[{index}].diameter_expression",
                ),
            }
        )

    requested_edge = {"type": "none"} if edge_finish is None else edge_finish
    if not isinstance(requested_edge, dict):
        _invalid("edge_finish must be an object", {"field": "edge_finish"})
    edge_type = requested_edge.get("type")
    if edge_type not in EDGE_KEYS:
        _invalid(
            "edge_finish.type must be one of: none, fillet, chamfer",
            {"edge_type": edge_type},
        )
    if set(requested_edge) != EDGE_KEYS[edge_type]:
        _invalid(
            "edge_finish fields do not match its type",
            {
                "edge_type": edge_type,
                "missing": sorted(EDGE_KEYS[edge_type] - set(requested_edge)),
                "unknown": sorted(set(requested_edge) - EDGE_KEYS[edge_type]),
            },
        )
    normalized_edge = {"type": edge_type}
    if edge_type != "none":
        normalized_edge["size_expression"] = _required_string(
            requested_edge.get("size_expression"),
            "edge_finish.size_expression",
        )

    return {
        "name": normalized_name,
        "parameter_prefix": normalized_prefix,
        **expressions,
        "holes": normalized_holes,
        "edge_finish": normalized_edge,
    }


def generated_parameter_names(normalized):
    """Return every generated parameter name without touching Fusion."""

    prefix = normalized["parameter_prefix"]
    edge_type = normalized["edge_finish"]["type"]
    result = {
        "width": f"{prefix}_width",
        "height": f"{prefix}_height",
        "thickness": f"{prefix}_thickness",
        "holes": {
            hole["key"]: {
                "x": f"{prefix}_{hole['key']}_x",
                "y": f"{prefix}_{hole['key']}_y",
                "diameter": f"{prefix}_{hole['key']}_diameter",
            }
            for hole in normalized["holes"]
        },
    }
    if edge_type != "none":
        result["edge_size"] = f"{prefix}_edge_size"
    return result


def _evaluate(expression, field, units_manager):
    try:
        return parse_length_expression(expression, units_manager)
    except Exception as error:
        raise PlateValidation(
            "PLATE_EXPRESSION_INVALID",
            "Fusion could not evaluate a plate length expression.",
            {"field": field, "expression": expression},
        ) from error


def _positive(value, field):
    if value <= 0:
        raise PlateValidation(
            "PLATE_DIMENSION_INVALID",
            "Plate sizes, hole diameters, and edge sizes must be greater than zero.",
            {"field": field, "evaluated_mm": round(value * 10.0, 6)},
        )


def evaluate_plate_request(normalized, units_manager):
    """Evaluate dimensions and reject impossible rectangle/hole geometry."""

    values_cm = {
        "width": _evaluate(normalized["width_expression"], "width_expression", units_manager),
        "height": _evaluate(normalized["height_expression"], "height_expression", units_manager),
        "thickness": _evaluate(
            normalized["thickness_expression"],
            "thickness_expression",
            units_manager,
        ),
    }
    for field, value in values_cm.items():
        _positive(value, field)

    evaluated_holes = []
    for index, hole in enumerate(normalized["holes"]):
        x_cm = _evaluate(hole["x_expression"], f"holes[{index}].x_expression", units_manager)
        y_cm = _evaluate(hole["y_expression"], f"holes[{index}].y_expression", units_manager)
        diameter_cm = _evaluate(
            hole["diameter_expression"],
            f"holes[{index}].diameter_expression",
            units_manager,
        )
        _positive(diameter_cm, f"holes[{index}].diameter_expression")
        evaluated_holes.append(
            {
                **hole,
                "x_cm": x_cm,
                "y_cm": y_cm,
                "diameter_cm": diameter_cm,
                "x_mm": round(x_cm * 10.0, 6),
                "y_mm": round(y_cm * 10.0, 6),
                "diameter_mm": round(diameter_cm * 10.0, 6),
            }
        )

    half_width = values_cm["width"] / 2.0
    half_height = values_cm["height"] / 2.0
    for hole in evaluated_holes:
        radius = hole["diameter_cm"] / 2.0
        if (
            abs(hole["x_cm"]) + radius >= half_width - _GEOMETRY_TOLERANCE_CM
            or abs(hole["y_cm"]) + radius >= half_height - _GEOMETRY_TOLERANCE_CM
        ):
            raise PlateValidation(
                "PLATE_HOLE_OUT_OF_BOUNDS",
                "Every circular hole must remain strictly inside the rectangular plate.",
                {"key": hole["key"]},
            )

    for index, left in enumerate(evaluated_holes):
        left_radius = left["diameter_cm"] / 2.0
        for right in evaluated_holes[index + 1 :]:
            right_radius = right["diameter_cm"] / 2.0
            distance = math.hypot(
                left["x_cm"] - right["x_cm"],
                left["y_cm"] - right["y_cm"],
            )
            if distance <= left_radius + right_radius + _GEOMETRY_TOLERANCE_CM:
                raise PlateValidation(
                    "PLATE_HOLES_OVERLAP",
                    "Circular holes must not overlap or touch.",
                    {"keys": [left["key"], right["key"]]},
                )

    edge = dict(normalized["edge_finish"])
    if edge["type"] != "none":
        size_cm = _evaluate(
            edge["size_expression"],
            "edge_finish.size_expression",
            units_manager,
        )
        _positive(size_cm, "edge_finish.size_expression")
        if size_cm >= min(values_cm["width"], values_cm["height"]) / 2.0:
            raise PlateValidation(
                "PLATE_DIMENSION_INVALID",
                "Edge size must be less than half the smaller plate side.",
                {"field": "edge_finish.size_expression", "evaluated_mm": round(size_cm * 10.0, 6)},
            )
        edge["size_cm"] = size_cm
        edge["size_mm"] = round(size_cm * 10.0, 6)

    parameter_names = generated_parameter_names(normalized)
    return {
        **normalized,
        "expressions": {
            "width": normalized["width_expression"],
            "height": normalized["height_expression"],
            "thickness": normalized["thickness_expression"],
        },
        "values_cm": values_cm,
        "values_mm": {
            field: round(value * 10.0, 6)
            for field, value in values_cm.items()
        },
        "holes": evaluated_holes,
        "edge_finish": edge,
        "parameter_names": parameter_names,
    }


def all_parameter_names(evaluated):
    """Flatten generated names in deterministic dependency order."""

    names = evaluated["parameter_names"]
    flattened = [names["width"], names["height"], names["thickness"]]
    for hole in evaluated["holes"]:
        hole_names = names["holes"][hole["key"]]
        flattened.extend([hole_names["x"], hole_names["y"], hole_names["diameter"]])
    if "edge_size" in names:
        flattened.append(names["edge_size"])
    return flattened
