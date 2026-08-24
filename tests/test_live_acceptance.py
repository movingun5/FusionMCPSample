from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from scripts.live_acceptance import (
    EXPECTED_PLATE_MM,
    REQUIRED_TOOLS,
    build_parametric_plate_arguments,
    dimensions_match,
    run_acceptance,
    summarize_tool_result,
)


class LiveAcceptanceHarnessTests(unittest.TestCase):
    def test_explicit_plate_arguments_define_four_parameter_driven_holes(self):
        arguments = build_parametric_plate_arguments()

        self.assertEqual("MountingPlate", arguments["name"])
        self.assertEqual("plate", arguments["parameter_prefix"])
        self.assertEqual("100 mm", arguments["width_expression"])
        self.assertEqual("60 mm", arguments["height_expression"])
        self.assertEqual("5 mm", arguments["thickness_expression"])
        self.assertEqual(4, len(arguments["holes"]))
        self.assertEqual(
            {"type": "fillet", "size_expression": "3 mm"},
            arguments["edge_finish"],
        )
        self.assertNotIn("code", arguments)

    def test_dimensions_match_in_any_axis_order_with_tolerance(self):
        self.assertTrue(dimensions_match([60.0, 5.0, 100.0], EXPECTED_PLATE_MM, 0.01))
        self.assertFalse(dimensions_match([60.0, 6.0, 100.0], EXPECTED_PLATE_MM, 0.01))

    def test_summary_removes_base64_image_payload(self):
        result = {
            "isError": False,
            "content": [{"type": "image", "data": "very-large-base64", "mimeType": "image/png"}],
        }

        summary = summarize_tool_result(result)

        self.assertNotIn("very-large-base64", repr(summary))
        self.assertEqual("[IMAGE_DATA_REMOVED]", summary["content"][0]["data"])

    def test_creation_failure_stops_dependent_parameter_export_and_image_steps(self):
        class FailedCreationClient:
            instances = []

            def __init__(self, *_args, **_kwargs):
                self.tool_calls = []
                self.__class__.instances.append(self)

            def call(self, method, _params=None):
                if method == "initialize":
                    return {"serverInfo": {"name": "test"}}
                if method == "tools/list":
                    return {"tools": [{"name": name} for name in REQUIRED_TOOLS]}
                raise AssertionError(method)

            def tool(self, name, _arguments=None):
                self.tool_calls.append(name)
                if name == "get_fusion_status":
                    return {"structuredContent": {"fusion_available": True, "active_design": True}}
                if name == "get_design_context":
                    return {"structuredContent": {"components": [], "parameters": []}}
                if name == "create_parametric_plate":
                    return {
                        "isError": True,
                        "error": {"code": "PLATE_COMPONENT_WRITE_FAILED"},
                    }
                return {"isError": False}

        with tempfile.TemporaryDirectory() as directory:
            with patch("scripts.live_acceptance.MCPClient", FailedCreationClient):
                report = run_acceptance(
                    "http://127.0.0.1:9100/",
                    "test-token",
                    Path(directory),
                    include_approval_gate=False,
                )

        calls = FailedCreationClient.instances[-1].tool_calls
        self.assertFalse(report["ok"])
        self.assertIn("create_parametric_plate", calls)
        self.assertNotIn("upsert_user_parameter", calls)
        self.assertNotIn("get_viewport_screenshot", calls)
        self.assertNotIn("export_design", calls)


if __name__ == "__main__":
    unittest.main()
