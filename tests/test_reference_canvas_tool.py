import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.tools.create_reference_canvas import tool


class ReferenceCanvasToolTests(unittest.TestCase):
    def test_schema_exposes_strict_calibrated_reference_canvas_contract(self):
        schema = tool.to_dict()["inputSchema"]

        self.assertEqual(
            ["name", "image_path", "plane", "width_expression"],
            schema["required"],
        )
        self.assertEqual(["xy", "xz", "yz"], schema["properties"]["plane"]["enum"])
        self.assertEqual(50, schema["properties"]["opacity"]["default"])
        self.assertEqual(0, schema["properties"]["opacity"]["minimum"])
        self.assertEqual(100, schema["properties"]["opacity"]["maximum"])
        self.assertEqual(
            "0 mm",
            schema["properties"]["center_x_expression"]["default"],
        )
        self.assertFalse(schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
