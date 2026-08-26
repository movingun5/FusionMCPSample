import importlib
import importlib.util
import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.fusion.drawing_plan import (
    DrawingPlanValidation,
    validate_drawing_modeling_plan,
)


class DrawingPlanTests(unittest.TestCase):
    def test_exposes_a_pure_drawing_plan_validator(self):
        module_name = "fusion_mcp_addin.fusion.drawing_plan"
        self.assertIsNotNone(importlib.util.find_spec(module_name))
        module = importlib.import_module(module_name)
        self.assertTrue(callable(getattr(module, "validate_drawing_modeling_plan", None)))

    @staticmethod
    def view(plane, width_mm, height_mm, *, width_source="stated", height_source="stated"):
        return {
            "plane": plane,
            "width_mm": width_mm,
            "height_mm": height_mm,
            "width_source": width_source,
            "height_source": height_source,
        }

    @staticmethod
    def plate_geometry():
        return {
            "type": "plate",
            "width_mm": 100.0,
            "height_mm": 60.0,
            "thickness_mm": 5.0,
            "holes": [
                {
                    "key": "center",
                    "x_mm": 0.0,
                    "y_mm": 0.0,
                    "diameter_mm": 6.0,
                }
            ],
            "edge_finish": {"type": "fillet", "size_mm": 3.0},
        }

    def test_builds_an_exact_plate_tool_call_from_consistent_views(self):
        result = validate_drawing_modeling_plan(
            "Mounting Plate",
            "plate",
            [self.view("xy", 100.0, 60.0), self.view("xz", 100.0, 5.0)],
            self.plate_geometry(),
            0.25,
        )

        self.assertTrue(result["ready_for_modeling"])
        self.assertFalse(result["mutation_performed"])
        self.assertEqual([], result["blockers"])
        self.assertEqual({"x": 100.0, "y": 60.0, "z": 5.0}, result["axes_mm"])
        self.assertEqual("create_parametric_plate", result["target_tool"])
        self.assertEqual(
            {
                "name": "Mounting Plate",
                "parameter_prefix": "plate",
                "width_expression": "100 mm",
                "height_expression": "60 mm",
                "thickness_expression": "5 mm",
                "holes": [
                    {
                        "key": "center",
                        "x_expression": "0 mm",
                        "y_expression": "0 mm",
                        "diameter_expression": "6 mm",
                    }
                ],
                "edge_finish": {"type": "fillet", "size_expression": "3 mm"},
            },
            result["tool_arguments"],
        )
        self.assertEqual(
            {"stated": 4, "estimated": 0, "missing": 0},
            result["dimension_evidence"],
        )

    def test_builds_an_exact_straight_profile_tool_call(self):
        geometry = {
            "type": "straight_profile",
            "vertices": [
                {"key": "p1", "x_mm": -50.0, "y_mm": -30.0},
                {"key": "p2", "x_mm": 50.0, "y_mm": -30.0},
                {"key": "p3", "x_mm": 50.0, "y_mm": 30.0},
                {"key": "p4", "x_mm": 10.0, "y_mm": 30.0},
                {"key": "p5", "x_mm": 10.0, "y_mm": 0.0},
                {"key": "p6", "x_mm": -50.0, "y_mm": 0.0},
            ],
            "depth_mm": 8.0,
        }

        result = validate_drawing_modeling_plan(
            "L Profile",
            "l_profile",
            [self.view("xy", 100.0, 60.0), self.view("xz", 100.0, 8.0)],
            geometry,
        )

        self.assertTrue(result["ready_for_modeling"])
        self.assertEqual("create_parametric_profile_extrusion", result["target_tool"])
        self.assertEqual("8 mm", result["tool_arguments"]["depth_expression"])
        self.assertEqual(
            {"key": "p1", "x_expression": "-50 mm", "y_expression": "-30 mm"},
            result["tool_arguments"]["vertices"][0],
        )
        self.assertEqual(4200.0, result["geometry_summary"]["profile_area_mm2"])

    def test_blocks_estimates_missing_values_and_unsupported_features(self):
        geometry = self.plate_geometry()
        geometry["thickness_mm"] = None
        result = validate_drawing_modeling_plan(
            "Estimated Plate",
            "estimated_plate",
            [
                self.view("xy", 100.0, 60.0, height_source="estimated"),
                self.view("xz", 100.0, None, height_source="missing"),
            ],
            geometry,
            unsupported_features=["curved outer edge"],
        )

        self.assertFalse(result["ready_for_modeling"])
        self.assertIsNone(result["target_tool"])
        self.assertIsNone(result["tool_arguments"])
        self.assertEqual(
            ["ESTIMATED_DIMENSION", "MISSING_DIMENSION", "UNSUPPORTED_FEATURE"],
            sorted({blocker["code"] for blocker in result["blockers"]}),
        )
        self.assertEqual(
            {"stated": 2, "estimated": 1, "missing": 1},
            result["dimension_evidence"],
        )

    def test_blocks_a_model_axis_that_has_no_stated_drawing_dimension(self):
        result = validate_drawing_modeling_plan(
            "Plate Without Depth Evidence",
            "plate_without_depth",
            [self.view("xy", 100.0, 60.0)],
            self.plate_geometry(),
        )

        self.assertFalse(result["ready_for_modeling"])
        self.assertIsNone(result["tool_arguments"])
        self.assertIn(
            {
                "code": "MISSING_DIMENSION",
                "field": "drawing.axes.z",
                "message": "A required drawing dimension is missing.",
            },
            result["blockers"],
        )

    def test_rejects_conflicting_shared_view_dimensions(self):
        with self.assertRaises(DrawingPlanValidation) as caught:
            validate_drawing_modeling_plan(
                "Plate",
                "plate",
                [self.view("xy", 100.0, 60.0), self.view("xz", 101.0, 5.0)],
                self.plate_geometry(),
                0.25,
            )

        self.assertEqual("DRAWING_DIMENSION_MISMATCH", caught.exception.code)
        self.assertEqual("x", caught.exception.details["axis"])

    def test_rejects_geometry_that_disagrees_with_view_axes(self):
        geometry = self.plate_geometry()
        geometry["width_mm"] = 90.0
        with self.assertRaises(DrawingPlanValidation) as caught:
            validate_drawing_modeling_plan(
                "Plate",
                "plate",
                [self.view("xy", 100.0, 60.0), self.view("xz", 100.0, 5.0)],
                geometry,
                0.25,
            )

        self.assertEqual("DRAWING_MODEL_DIMENSION_MISMATCH", caught.exception.code)
        self.assertEqual("x", caught.exception.details["axis"])
        self.assertEqual(10.0, caught.exception.details["difference_mm"])

    def test_reuses_profile_geometry_checks_for_self_intersection(self):
        geometry = {
            "type": "straight_profile",
            "vertices": [
                {"key": "a", "x_mm": 0.0, "y_mm": 0.0},
                {"key": "b", "x_mm": 40.0, "y_mm": 40.0},
                {"key": "c", "x_mm": 0.0, "y_mm": 40.0},
                {"key": "d", "x_mm": 40.0, "y_mm": 0.0},
            ],
            "depth_mm": 8.0,
        }

        with self.assertRaises(DrawingPlanValidation) as caught:
            validate_drawing_modeling_plan(
                "Bow Tie",
                "bow_tie",
                [self.view("xy", 40.0, 40.0), self.view("xz", 40.0, 8.0)],
                geometry,
            )

        self.assertEqual("PROFILE_SELF_INTERSECTION", caught.exception.code)

    def test_rejects_unknown_fields_duplicate_planes_and_invalid_numbers(self):
        invalid_requests = []
        view_with_path = self.view("xy", 100.0, 60.0)
        view_with_path["image_path"] = r"C:\private\drawing.png"
        invalid_requests.append(([view_with_path], self.plate_geometry()))
        invalid_requests.append(
            ([self.view("xy", 100.0, 60.0), self.view("xy", 100.0, 60.0)], self.plate_geometry())
        )
        invalid_view = self.view("xy", True, 60.0)
        invalid_requests.append(([invalid_view], self.plate_geometry()))

        for views, geometry in invalid_requests:
            with self.subTest(views=views):
                with self.assertRaises(DrawingPlanValidation) as caught:
                    validate_drawing_modeling_plan("Plate", "plate", views, geometry)
                self.assertEqual("INVALID_REQUEST", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
