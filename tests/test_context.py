import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.fusion.context import build_design_context, get_status
from tests.fakes import (
    FakeApp,
    FakeBody,
    FakeCanvas,
    FakeCanvasInput,
    FakeComponent,
    FakeDesign,
    FakeFeature,
    FakeModelParameter,
    FakeParameter,
)


class _PlaneWrapper:
    def __init__(self, name, token):
        self.name = name
        self.entityToken = token


class ContextTests(unittest.TestCase):
    def setUp(self):
        body = FakeBody("Plate", "body-1", volume=30.0, maximum=(10.0, 6.0, 0.5))
        root = FakeComponent("Root", "component-1", bodies=[body])
        self.design = FakeDesign([root], [FakeParameter("plate_width", "100 mm")])
        self.app = FakeApp(self.design)

    def test_status_reports_active_design_without_secret_data(self):
        status = get_status(self.app, "1.1.0")

        self.assertTrue(status["fusion_available"])
        self.assertTrue(status["active_design"])
        self.assertEqual("1.1.0", status["server_version"])
        self.assertNotIn("token", repr(status).lower())

    def test_status_handles_missing_fusion(self):
        status = get_status(None, "1.1.0")

        self.assertFalse(status["fusion_available"])
        self.assertEqual("FUSION_UNAVAILABLE", status["error"]["code"])

    def test_status_defaults_to_parameter_tool_server_version(self):
        status = get_status(self.app)

        self.assertEqual("2.0.0", status["server_version"])

    def test_context_returns_components_bodies_and_parameters(self):
        context = build_design_context(self.app, scope="all", limit=20)

        self.assertEqual("mm", context["units"])
        self.assertEqual("Root", context["active_component"])
        self.assertEqual("Plate", context["components"][0]["bodies"][0]["name"])
        self.assertEqual("100 mm", context["parameters"][0]["expression"])
        self.assertFalse(context["truncated"])

    def test_context_returns_safe_canvas_summary_without_full_image_path(self):
        root = self.design.rootComponent
        canvas_input = FakeCanvasInput(
            r"C:\private\reference\plate.png",
            root.xYConstructionPlane,
        )
        canvas_input.opacity = 65
        canvas = FakeCanvas(canvas_input, "canvas-1")
        canvas.name = "Front Reference"
        root.canvases._items.append(canvas)

        context = build_design_context(self.app, scope="all", limit=20)

        component = context["components"][0]
        self.assertEqual(1, component["canvas_count"])
        self.assertEqual("Front Reference", component["canvases"][0]["name"])
        self.assertEqual("plate.png", component["canvases"][0]["image_name"])
        self.assertEqual("xy", component["canvases"][0]["plane"])
        self.assertEqual(20.0, component["canvases"][0]["width_mm"])
        self.assertEqual(10.0, component["canvases"][0]["height_mm"])
        self.assertEqual(65, component["canvases"][0]["opacity"])
        self.assertNotIn(r"C:\private\reference", repr(context))

    def test_context_recognizes_same_plane_returned_as_a_distinct_fusion_wrapper(self):
        root = self.design.rootComponent
        root.xYConstructionPlane = _PlaneWrapper("XY Plane", "xy-plane-token")
        canvas_input = FakeCanvasInput(
            r"C:\reference\plate.png",
            _PlaneWrapper("XY Plane", "xy-plane-token"),
        )
        canvas = FakeCanvas(canvas_input, "canvas-2")
        canvas.name = "Wrapped Plane Reference"
        root.canvases._items.append(canvas)

        context = build_design_context(self.app, scope="all", limit=20)

        self.assertEqual("xy", context["components"][0]["canvases"][0]["plane"])

    def test_context_returns_model_parameter_owner_and_role_for_edits(self):
        feature = FakeFeature("Plate Extrusion", "feature-1")
        parameter = FakeModelParameter(
            "d12",
            "10 mm",
            "Distance",
            feature,
            component=self.design.rootComponent,
            value=1.0,
        )
        self.design.rootComponent.features = type(
            self.design.rootComponent.features
        )([feature])
        self.design.rootComponent.modelParameters = type(
            self.design.rootComponent.modelParameters
        )([parameter])

        context = build_design_context(self.app, scope="all", limit=20)

        self.assertEqual(
            {
                "name": "d12",
                "expression": "10 mm",
                "unit": "mm",
                "role": "Distance",
                "component": "Root",
                "created_by": {
                    "name": "Plate Extrusion",
                    "type": "FakeFeature",
                    "entity_token": "feature-1",
                },
            },
            context["model_parameters"][0],
        )

    def test_context_applies_limit_and_marks_truncation(self):
        context = build_design_context(self.app, scope="all", limit=1)

        self.assertEqual(1, len(context["components"]))
        self.assertTrue(context["truncated"])

    def test_context_rejects_invalid_scope(self):
        with self.assertRaises(ValueError):
            build_design_context(self.app, scope="everything", limit=20)


if __name__ == "__main__":
    unittest.main()
