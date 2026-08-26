import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
import fusion_mcp_addin.tools  # noqa: F401 - registers the complete catalog
from fusion_mcp_addin.mcp_primitives.registry import get_registry
from fusion_mcp_addin.tools.create_parametric_plate import tool


class ParametricPlateToolTests(unittest.TestCase):
    def test_schema_requires_named_dimensions_and_strict_holes(self):
        schema = tool.to_dict()["inputSchema"]

        self.assertEqual(
            [
                "name",
                "parameter_prefix",
                "width_expression",
                "height_expression",
                "thickness_expression",
            ],
            schema["required"],
        )
        self.assertFalse(schema["additionalProperties"])
        holes = schema["properties"]["holes"]
        self.assertEqual(0, holes["minItems"])
        self.assertEqual(32, holes["maxItems"])
        self.assertEqual(
            ["key", "x_expression", "y_expression", "diameter_expression"],
            holes["items"]["required"],
        )
        self.assertFalse(holes["items"]["additionalProperties"])

    def test_schema_exposes_three_mutually_exclusive_edge_finish_shapes(self):
        edge_finish = tool.to_dict()["inputSchema"]["properties"]["edge_finish"]

        self.assertEqual(3, len(edge_finish["oneOf"]))
        self.assertEqual(
            ["none", "fillet", "chamfer"],
            [shape["properties"]["type"]["enum"][0] for shape in edge_finish["oneOf"]],
        )
        self.assertEqual({"type": "none"}, edge_finish["default"])

    def test_complete_catalog_contains_twenty_three_unique_tools(self):
        names = get_registry().get_tool_names()

        self.assertEqual(24, len(names))
        self.assertEqual(24, len(set(names)))
        self.assertIn("update_parameter_batch", names)
        self.assertIn("create_parametric_plate", names)


if __name__ == "__main__":
    unittest.main()
