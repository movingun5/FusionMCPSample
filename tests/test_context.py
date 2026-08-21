import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.fusion.context import build_design_context, get_status
from tests.fakes import FakeApp, FakeBody, FakeComponent, FakeDesign, FakeParameter


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

        self.assertEqual("1.5.0", status["server_version"])

    def test_context_returns_components_bodies_and_parameters(self):
        context = build_design_context(self.app, scope="all", limit=20)

        self.assertEqual("mm", context["units"])
        self.assertEqual("Root", context["active_component"])
        self.assertEqual("Plate", context["components"][0]["bodies"][0]["name"])
        self.assertEqual("100 mm", context["parameters"][0]["expression"])
        self.assertFalse(context["truncated"])

    def test_context_applies_limit_and_marks_truncation(self):
        context = build_design_context(self.app, scope="all", limit=1)

        self.assertEqual(1, len(context["components"]))
        self.assertTrue(context["truncated"])

    def test_context_rejects_invalid_scope(self):
        with self.assertRaises(ValueError):
            build_design_context(self.app, scope="everything", limit=20)


if __name__ == "__main__":
    unittest.main()
