import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.tools.update_model_parameter import tool


class ModelParameterToolTests(unittest.TestCase):
    def test_schema_requires_exact_owner_role_expression_and_old_value(self):
        schema = tool.to_dict()["inputSchema"]

        self.assertEqual(
            [
                "feature_name",
                "role",
                "expression",
                "expected_old_expression",
            ],
            schema["required"],
        )
        self.assertFalse(schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
