import importlib
import importlib.util
import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.tools import validate_drawing_modeling_plan as drawing_tool


class DrawingPlanToolTests(unittest.TestCase):
    def test_exposes_the_drawing_plan_mcp_tool_module(self):
        module_name = "fusion_mcp_addin.tools.validate_drawing_modeling_plan"
        self.assertIsNotNone(importlib.util.find_spec(module_name))
        module = importlib.import_module(module_name)
        self.assertEqual("validate_drawing_modeling_plan", module.tool.name)

    @staticmethod
    def plate_request():
        return {
            "name": "Plate",
            "parameter_prefix": "plate",
            "views": [
                {
                    "plane": "xy",
                    "width_mm": 100.0,
                    "height_mm": 60.0,
                    "width_source": "stated",
                    "height_source": "stated",
                },
                {
                    "plane": "xz",
                    "width_mm": 100.0,
                    "height_mm": 5.0,
                    "width_source": "stated",
                    "height_source": "stated",
                },
            ],
            "geometry": {
                "type": "plate",
                "width_mm": 100.0,
                "height_mm": 60.0,
                "thickness_mm": 5.0,
                "holes": [],
                "edge_finish": {"type": "none"},
            },
        }

    def test_schema_is_strict_for_views_and_both_geometry_routes(self):
        schema = drawing_tool.tool.to_dict()["inputSchema"]

        self.assertEqual(
            ["name", "parameter_prefix", "views", "geometry"],
            schema["required"],
        )
        self.assertFalse(schema["additionalProperties"])
        views = schema["properties"]["views"]
        self.assertEqual(1, views["minItems"])
        self.assertEqual(3, views["maxItems"])
        self.assertEqual(
            ["plane", "width_mm", "height_mm", "width_source", "height_source"],
            views["items"]["required"],
        )
        self.assertFalse(views["items"]["additionalProperties"])
        geometry_options = schema["properties"]["geometry"]["oneOf"]
        self.assertEqual(2, len(geometry_options))
        self.assertEqual(
            [["plate"], ["straight_profile"]],
            [option["properties"]["type"]["enum"] for option in geometry_options],
        )
        self.assertTrue(all(not option["additionalProperties"] for option in geometry_options))

    def test_handler_returns_a_structured_non_mutating_tool_call(self):
        result = drawing_tool.handler(**self.plate_request())

        self.assertFalse(result["isError"])
        payload = result["structuredContent"]
        self.assertTrue(payload["ready_for_modeling"])
        self.assertFalse(payload["mutation_performed"])
        self.assertEqual("create_parametric_plate", payload["target_tool"])
        self.assertIn("\"ready_for_modeling\": true", result["content"][0]["text"])

    def test_handler_returns_structured_dimension_conflicts(self):
        request = self.plate_request()
        request["views"][1]["width_mm"] = 101.0

        result = drawing_tool.handler(**request)

        self.assertTrue(result["isError"])
        self.assertEqual("DRAWING_DIMENSION_MISMATCH", result["error"]["code"])
        self.assertFalse(result["error"]["retryable"])


if __name__ == "__main__":
    unittest.main()
