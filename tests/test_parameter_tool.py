import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.tools.upsert_user_parameter import tool


class ParameterToolTests(unittest.TestCase):
    def test_schema_requires_name_and_expression_and_is_strict(self):
        schema = tool.to_dict()["inputSchema"]

        self.assertEqual(["name", "expression"], schema["required"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            "string",
            schema["properties"]["expected_old_expression"]["type"],
        )


if __name__ == "__main__":
    unittest.main()
