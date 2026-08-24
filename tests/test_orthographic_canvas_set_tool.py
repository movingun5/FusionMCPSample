import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.tools.create_orthographic_canvas_set import tool


class OrthographicCanvasSetToolTests(unittest.TestCase):
    def test_schema_requires_name_and_two_to_three_strict_views(self):
        schema = tool.to_dict()["inputSchema"]

        self.assertEqual(["name", "views"], schema["required"])
        self.assertFalse(schema["additionalProperties"])
        views = schema["properties"]["views"]
        self.assertEqual(2, views["minItems"])
        self.assertEqual(3, views["maxItems"])
        self.assertEqual(
            ["image_path", "plane", "width_expression"],
            views["items"]["required"],
        )
        self.assertFalse(views["items"]["additionalProperties"])
        self.assertEqual(
            ["xy", "xz", "yz"],
            views["items"]["properties"]["plane"]["enum"],
        )
        self.assertEqual(
            "0 mm",
            views["items"]["properties"]["center_x_expression"]["default"],
        )
        self.assertEqual(50, views["items"]["properties"]["opacity"]["default"])
        tolerance = schema["properties"]["dimension_tolerance_mm"]
        self.assertEqual(0.001, tolerance["minimum"])
        self.assertEqual(10.0, tolerance["maximum"])
        self.assertEqual(0.25, tolerance["default"])


if __name__ == "__main__":
    unittest.main()
