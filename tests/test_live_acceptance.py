import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from scripts.live_acceptance import (
    EXPECTED_PLATE_MM,
    build_mounting_plate_code,
    dimensions_match,
    summarize_tool_result,
)


class LiveAcceptanceHarnessTests(unittest.TestCase):
    def test_generated_script_creates_rectangle_holes_and_five_mm_extrusion(self):
        code = build_mounting_plate_code()

        self.assertIn("addTwoPointRectangle", code)
        self.assertEqual(4, code.count("addByCenterRadius"))
        self.assertIn('createByString("5 mm")', code)
        self.assertIn("Codex_Mounting_Plate", code)
        self.assertIn("def run(context):", code)

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
