import unittest
from unittest.mock import patch

import tests  # noqa: F401 - installs the Fusion package test bootstrap
import fusion_mcp_addin.tools  # noqa: F401 - registers the complete catalog
from fusion_mcp_addin.mcp_primitives.registry import get_registry
from fusion_mcp_addin.tools import create_parametric_profile_extrusion as profile_tool


class ParametricProfileToolTests(unittest.TestCase):
    def test_schema_requires_strict_named_polyline_vertices(self):
        schema = profile_tool.tool.to_dict()["inputSchema"]

        self.assertEqual(
            ["name", "parameter_prefix", "vertices", "depth_expression"],
            schema["required"],
        )
        self.assertFalse(schema["additionalProperties"])
        vertices = schema["properties"]["vertices"]
        self.assertEqual(3, vertices["minItems"])
        self.assertEqual(32, vertices["maxItems"])
        self.assertEqual(
            ["key", "x_expression", "y_expression"],
            vertices["items"]["required"],
        )
        self.assertFalse(vertices["items"]["additionalProperties"])

    def test_complete_catalog_contains_twenty_three_unique_tools(self):
        names = get_registry().get_tool_names()

        self.assertEqual(23, len(names))
        self.assertEqual(23, len(set(names)))
        self.assertIn("create_parametric_profile_extrusion", names)
        self.assertIn("validate_drawing_modeling_plan", names)

    def test_handler_forwards_the_active_app_and_all_arguments(self):
        app = object()
        vertices = [
            {"key": "a", "x_expression": "0 mm", "y_expression": "0 mm"},
            {"key": "b", "x_expression": "40 mm", "y_expression": "0 mm"},
            {"key": "c", "x_expression": "10 mm", "y_expression": "20 mm"},
        ]
        expected = {"isError": False}

        with patch.object(
            profile_tool.adsk.core.Application,
            "get",
            return_value=app,
        ), patch.object(
            profile_tool,
            "create_parametric_profile_extrusion",
            return_value=expected,
        ) as create:
            result = profile_tool.handler(
                "Bracket",
                "bracket",
                vertices,
                "8 mm",
            )

        self.assertIs(expected, result)
        create.assert_called_once_with(
            app,
            "Bracket",
            "bracket",
            vertices,
            "8 mm",
        )


if __name__ == "__main__":
    unittest.main()
