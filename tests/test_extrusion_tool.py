import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.tools.create_extrusion import tool


class ExtrusionToolTests(unittest.TestCase):
    def test_schema_requires_feature_sketch_and_distance(self):
        schema = tool.to_dict()["inputSchema"]

        self.assertEqual(
            ["name", "sketch_name", "distance_expression"],
            schema["required"],
        )
        self.assertFalse(schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
