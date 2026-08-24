import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from scripts.live_acceptance import (
    EXPECTED_PLATE_MM,
    build_parametric_plate_arguments,
    dimensions_match,
    summarize_tool_result,
)


class LiveAcceptanceHarnessTests(unittest.TestCase):
    def test_explicit_plate_arguments_define_four_parameter_driven_holes(self):
        arguments = build_parametric_plate_arguments()

        self.assertEqual("MountingPlate", arguments["name"])
        self.assertEqual("plate", arguments["parameter_prefix"])
        self.assertEqual("100 mm", arguments["width_expression"])
        self.assertEqual("60 mm", arguments["height_expression"])
        self.assertEqual("5 mm", arguments["thickness_expression"])
        self.assertEqual(4, len(arguments["holes"]))
        self.assertEqual(
            {"type": "fillet", "size_expression": "3 mm"},
            arguments["edge_finish"],
        )
        self.assertNotIn("code", arguments)

    def test_dimensions_match_in_any_axis_order_with_tolerance(self):
        self.assertTrue(dimensions_match([60.0, 5.0, 100.0], EXPECTED_PLATE_MM, 0.01))
        self.assertFalse(dimensions_match([60.0, 6.0, 100.0], EXPECTED_PLATE_MM, 0.01))

    def test_summary_removes_base64_image_payload(self):
        result = {
            "isError": False,
            "content": [{"type": "image", "data": "very-large-base64", "mimeType": "image/png"}],
        }

        summary = summarize_tool_result(result)

        self.assertNotIn("very-large-base64", repr(summary))
        self.assertEqual("[IMAGE_DATA_REMOVED]", summary["content"][0]["data"])


if __name__ == "__main__":
    unittest.main()
