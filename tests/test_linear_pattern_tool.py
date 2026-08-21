import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.tools.create_linear_pattern import tool


class LinearPatternToolTests(unittest.TestCase):
    def test_schema_requires_pattern_target_axis_quantity_and_spacing(self):
        schema = tool.to_dict()["inputSchema"]

        self.assertEqual(
            [
                "name",
                "target_feature_name",
                "axis",
                "quantity",
                "spacing_expression",
            ],
            schema["required"],
        )
        self.assertEqual(["x", "y", "z"], schema["properties"]["axis"]["enum"])
        self.assertEqual(2, schema["properties"]["quantity"]["minimum"])
        self.assertFalse(schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
