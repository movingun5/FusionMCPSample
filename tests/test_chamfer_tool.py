import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.tools.create_chamfer import tool


class ChamferToolTests(unittest.TestCase):
    def test_schema_requires_feature_body_and_distance(self):
        schema = tool.to_dict()["inputSchema"]

        self.assertEqual(
            ["name", "body_name", "distance_expression"],
            schema["required"],
        )
        self.assertEqual(
            ["all", "top", "bottom", "vertical"],
            schema["properties"]["edge_selector"]["enum"],
        )
        self.assertFalse(schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
