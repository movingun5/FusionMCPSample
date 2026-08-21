import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.tools.create_rectangle_sketch import tool


class RectangleToolTests(unittest.TestCase):
    def test_schema_requires_name_and_size_expressions_and_is_strict(self):
        schema = tool.to_dict()["inputSchema"]

        self.assertEqual(
            ["name", "width_expression", "height_expression"],
            schema["required"],
        )
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            ["xy", "xz", "yz"],
            schema["properties"]["plane"]["enum"],
        )


if __name__ == "__main__":
    unittest.main()
