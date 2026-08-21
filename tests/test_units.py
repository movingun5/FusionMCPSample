import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.fusion.units import format_internal_length, parse_length_expression
from tests.fakes import FakeUnitsManager


class UnitTests(unittest.TestCase):
    def test_centimeters_render_as_requested_millimeters(self):
        result = format_internal_length(10.0, "mm")

        self.assertEqual(100.0, result["value"])
        self.assertEqual("mm", result["unit"])
        self.assertEqual(10.0, result["internal_cm"])

    def test_centimeters_render_as_inches(self):
        self.assertAlmostEqual(1.0, format_internal_length(2.54, "in")["value"], places=8)

    def test_expression_uses_fusion_units_manager(self):
        value = parse_length_expression("25.4 mm", FakeUnitsManager())

        self.assertAlmostEqual(2.54, value)

    def test_unsupported_display_unit_is_rejected(self):
        with self.assertRaises(ValueError):
            format_internal_length(1.0, "m")


if __name__ == "__main__":
    unittest.main()
