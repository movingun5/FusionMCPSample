"""Pure validation and shared-axis checks for orthographic canvas sets."""

import math


_PLANES = {"xy", "xz", "yz"}
_PLANE_AXES = {
    "xy": ("x", "y"),
    "xz": ("x", "z"),
    "yz": ("y", "z"),
}
_VIEW_KEYS = {
    "image_path",
    "plane",
    "width_expression",
    "center_x_expression",
    "center_y_expression",
    "opacity",
    "flip_horizontal",
    "flip_vertical",
}
_REQUIRED_VIEW_KEYS = {"image_path", "plane", "width_expression"}
_STRING_VIEW_KEYS = {
    "image_path",
    "plane",
    "width_expression",
    "center_x_expression",
    "center_y_expression",
}
_VIEW_DEFAULTS = {
    "center_x_expression": "0 mm",
    "center_y_expression": "0 mm",
    "opacity": 50,
    "flip_horizontal": False,
    "flip_vertical": False,
}


class OrthographicValidation(ValueError):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _invalid(message, details=None):
    raise OrthographicValidation("INVALID_REQUEST", message, details)


def validate_orthographic_request(name, views, dimension_tolerance_mm):
    """Validate and normalize a two- or three-view orthographic request."""

    if not isinstance(name, str) or not name.strip():
        _invalid("name must be a non-empty string.")
    if not isinstance(views, list) or not 2 <= len(views) <= 3:
        _invalid("views must be a list containing two or three view objects.")
    if (
        isinstance(dimension_tolerance_mm, bool)
        or not isinstance(dimension_tolerance_mm, (int, float))
        or not math.isfinite(float(dimension_tolerance_mm))
        or not 0.001 <= float(dimension_tolerance_mm) <= 10.0
    ):
        _invalid("dimension_tolerance_mm must be a number from 0.001 through 10.0.")

    normalized_views = []
    seen_planes = set()
    for index, source in enumerate(views):
        if not isinstance(source, dict):
            _invalid("Each view must be an object.", {"view_index": index})
        unknown = set(source) - _VIEW_KEYS
        missing = _REQUIRED_VIEW_KEYS - set(source)
        if unknown or missing:
            _invalid(
                "Each view must contain only the supported fields and all required fields.",
                {
                    "view_index": index,
                    "unknown_fields": sorted(unknown),
                    "missing_fields": sorted(missing),
                },
            )

        view = {**_VIEW_DEFAULTS, **source}
        for field in _STRING_VIEW_KEYS:
            value = view.get(field)
            if not isinstance(value, str) or not value.strip():
                _invalid(
                    f"{field} must be a non-empty string.",
                    {"view_index": index, "field": field},
                )
            view[field] = value.strip()

        plane = view["plane"]
        if plane not in _PLANES:
            _invalid(
                "plane must be one of: xy, xz, yz.",
                {"view_index": index, "plane": plane},
            )
        if plane in seen_planes:
            _invalid(
                "Each orthographic plane may appear only once.",
                {"view_index": index, "plane": plane},
            )
        seen_planes.add(plane)

        opacity = view["opacity"]
        if (
            not isinstance(opacity, int)
            or isinstance(opacity, bool)
            or not 0 <= opacity <= 100
        ):
            _invalid(
                "opacity must be an integer from 0 through 100.",
                {"view_index": index},
            )
        if not isinstance(view["flip_horizontal"], bool) or not isinstance(
            view["flip_vertical"], bool
        ):
            _invalid(
                "flip_horizontal and flip_vertical must be booleans.",
                {"view_index": index},
            )
        normalized_views.append(view)

    return name.strip(), normalized_views, float(dimension_tolerance_mm)


def compare_shared_dimensions(measurements, tolerance_mm):
    """Map view dimensions onto model axes and reject inconsistent overlaps."""

    axis_values = {"x": [], "y": [], "z": []}
    for measurement in measurements:
        plane = measurement["plane"]
        horizontal_axis, vertical_axis = _PLANE_AXES[plane]
        axis_values[horizontal_axis].append((plane, float(measurement["width_mm"])))
        axis_values[vertical_axis].append((plane, float(measurement["height_mm"])))

    axes_mm = {}
    checks = []
    for axis in ("x", "y", "z"):
        values = axis_values[axis]
        if not values:
            continue
        numeric_values = [item[1] for item in values]
        axes_mm[axis] = round(sum(numeric_values) / len(numeric_values), 6)
        if len(values) < 2:
            continue

        difference = abs(numeric_values[0] - numeric_values[1])
        check = {
            "axis": axis,
            "planes": [item[0] for item in values],
            "values_mm": [round(value, 6) for value in numeric_values],
            "difference_mm": round(difference, 6),
            "tolerance_mm": round(float(tolerance_mm), 6),
            "matched": difference <= float(tolerance_mm),
        }
        checks.append(check)
        if not check["matched"]:
            raise OrthographicValidation(
                "ORTHOGRAPHIC_DIMENSION_MISMATCH",
                f"Orthographic views disagree on the shared {axis.upper()} dimension.",
                check,
            )

    return axes_mm, checks
