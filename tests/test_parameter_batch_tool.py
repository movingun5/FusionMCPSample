import importlib
import importlib.util
import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.tools import update_parameter_batch as batch_tool


class ParameterBatchToolTests(unittest.TestCase):
    def test_exposes_a_strict_discriminated_batch_schema(self):
        module_name = "fusion_mcp_addin.tools.update_parameter_batch"
        self.assertIsNotNone(importlib.util.find_spec(module_name))
        module = importlib.import_module(module_name)
        self.assertEqual("update_parameter_batch", module.tool.name)

        schema = module.tool.to_dict()["inputSchema"]
        self.assertEqual(["updates"], schema["required"])
        self.assertFalse(schema["additionalProperties"])
        updates = schema["properties"]["updates"]
        self.assertEqual(1, updates["minItems"])
        self.assertEqual(16, updates["maxItems"])
        options = updates["items"]["oneOf"]
        self.assertEqual(
            [["user"], ["model"]],
            [option["properties"]["kind"]["enum"] for option in options],
        )
        self.assertTrue(all(option["additionalProperties"] is False for option in options))


if __name__ == "__main__":
    unittest.main()
