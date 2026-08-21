import json
import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.core.results import tool_success


class ToolResultTests(unittest.TestCase):
    def test_structured_success_includes_required_text_content(self):
        data = {"fusion_available": True, "active_design": True}

        result = tool_success(data)

        self.assertFalse(result["isError"])
        self.assertEqual(data, result["structuredContent"])
        self.assertEqual("text", result["content"][0]["type"])
        self.assertEqual(data, json.loads(result["content"][0]["text"]))


if __name__ == "__main__":
    unittest.main()
