"""Explicit conversions between Fusion's internal centimeters and display units."""


_DISPLAY_FACTORS = {
    "mm": 10.0,
    "cm": 1.0,
    "in": 1.0 / 2.54,
}


def format_internal_length(value_cm, unit="mm"):
    """Return a Fusion internal length with an explicit display unit."""

    normalized = str(unit).lower()
    if normalized not in _DISPLAY_FACTORS:
        raise ValueError("unit must be one of: mm, cm, in")
    value_cm = float(value_cm)
    return {
        "value": round(value_cm * _DISPLAY_FACTORS[normalized], 9),
        "unit": normalized,
        "internal_cm": value_cm,
    }


def parse_length_expression(expression, units_manager):
    """Use Fusion's UnitsManager to evaluate a length expression to centimeters."""

    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("expression must be a non-empty string")
    if units_manager is None:
        raise ValueError("units_manager is required")
    return float(units_manager.evaluateExpression(expression, "cm"))
