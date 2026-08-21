import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.tools.create_simple_hole import tool


class SimpleHoleToolTests(unittest.TestCase):
    def test_schema_requires_target_position_and_size(self):
        schema = tool.to_dict()["inputSchema"]

        self.assertEqual(
            [
                "name",
                "body_name",
                "x_expression",
                "y_expression",
                "diameter_expression",
                "depth_expression",
            ],
            schema["required"],
        )
        self.assertFalse(schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
