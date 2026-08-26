import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from scripts.live_profile_acceptance import (
    REQUIRED_TOOLS,
    build_drawing_plan_arguments,
    build_profile_arguments,
    run_acceptance,
    sanitize_report_value,
)


class LiveProfileAcceptanceTests(unittest.TestCase):
    def test_script_entrypoint_can_be_run_directly_from_the_repository(self):
        repository = Path(__file__).resolve().parents[1]
        script = repository / "scripts" / "live_profile_acceptance.py"

        completed = subprocess.run(
            [sys.executable, str(script), "--help"],
            cwd=repository,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("--confirm-blank-design", completed.stdout)

    def test_committed_drawing_fixtures_are_distinct_1200_by_800_pngs(self):
        asset_dir = Path(__file__).resolve().parent / "assets"
        top = (asset_dir / "profile-l-top.png").read_bytes()
        front = (asset_dir / "profile-l-front.png").read_bytes()

        self.assertTrue(top.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertTrue(front.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual((1200, 800), struct.unpack(">II", top[16:24]))
        self.assertEqual((1200, 800), struct.unpack(">II", front[16:24]))
        self.assertNotEqual(top, front)

    def test_profile_arguments_are_explicit_and_match_the_dimensioned_l_outline(self):
        arguments = build_profile_arguments()

        self.assertEqual("LProfile", arguments["name"])
        self.assertEqual("l_profile", arguments["parameter_prefix"])
        self.assertEqual("8 mm", arguments["depth_expression"])
        self.assertEqual(6, len(arguments["vertices"]))
        self.assertEqual(
            {"key": "p4", "x_expression": "10 mm", "y_expression": "30 mm"},
            arguments["vertices"][3],
        )
        self.assertNotIn("image", repr(arguments).lower())
        self.assertNotIn("code", arguments)

    def test_drawing_plan_arguments_mark_every_visible_dimension_as_stated(self):
        arguments = build_drawing_plan_arguments()

        self.assertEqual("LProfile", arguments["name"])
        self.assertEqual("straight_profile", arguments["geometry"]["type"])
        self.assertEqual(["xy", "xz"], [view["plane"] for view in arguments["views"]])
        self.assertEqual(
            {"stated"},
            {
                source
                for view in arguments["views"]
                for source in (view["width_source"], view["height_source"])
            },
        )
        self.assertEqual([], arguments["unsupported_features"])

    def test_report_sanitizer_removes_images_absolute_paths_and_secrets(self):
        secret = "test-bearer-token"
        value = {
            "path": r"C:\Users\Example\drawing.png",
            "content": [{"type": "image", "data": "large-base64"}],
            "message": f"failed near C:\\Private\\part.step using {secret}",
        }

        rendered = json.dumps(
            sanitize_report_value(value, secrets=(secret,)),
            ensure_ascii=False,
        )

        self.assertNotIn("large-base64", rendered)
        self.assertNotIn("C:\\\\Users", rendered)
        self.assertNotIn("C:\\\\Private", rendered)
        self.assertNotIn(secret, rendered)

    def test_full_flow_uses_only_explicit_tools_and_redacts_the_report(self):
        class SuccessfulClient:
            instances = []

            def __init__(self, *_args, **_kwargs):
                self.calls = []
                self.context_calls = 0
                self.__class__.instances.append(self)

            def call(self, method, _params=None):
                self.calls.append(method)
                if method == "initialize":
                    return {"serverInfo": {"name": "fusion", "version": "2.4.0"}}
                if method == "tools/list":
                    names = sorted(REQUIRED_TOOLS) + [
                        f"dummy_{index}" for index in range(23 - len(REQUIRED_TOOLS))
                    ]
                    return {"tools": [{"name": name} for name in names]}
                raise AssertionError(method)

            def tool(self, name, arguments=None):
                arguments = arguments or {}
                self.calls.append(name)
                if name == "get_fusion_status":
                    return {
                        "structuredContent": {
                            "fusion_available": True,
                            "active_design": True,
                            "server_version": "2.4.0",
                            "fusion_version": "2704.1.53",
                        }
                    }
                if name == "get_design_context":
                    self.context_calls += 1
                    if self.context_calls == 1:
                        return {
                            "structuredContent": {
                                "components": [{"name": "Root", "bodies": [], "canvas_count": 0}],
                                "parameters": [],
                            }
                        }
                    if self.context_calls in {2, 3}:
                        return {
                            "structuredContent": {
                                "components": [
                                    {
                                        "name": "Root",
                                        "bodies": [{"name": "LProfile", "size_mm": [100.0, 60.0, 8.0]}],
                                        "canvas_count": 2,
                                    }
                                ],
                                "parameters": [
                                    {"name": "l_profile_depth"},
                                    *[
                                        {"name": f"l_profile_p{index}_{axis}"}
                                        for index in range(1, 7)
                                        for axis in ("x", "y")
                                    ],
                            ],
                            }
                        }
                    return {
                        "structuredContent": {
                            "components": [{"name": "Root", "bodies": [], "canvas_count": 2}],
                            "parameters": [],
                        }
                    }
                if name == "create_orthographic_canvas_set":
                    return {
                        "structuredContent": {
                            "set": {
                                "views": [
                                    {"name": "LReference_XY", "plane": "xy"},
                                    {"name": "LReference_XZ", "plane": "xz"},
                                ],
                                "axes_mm": {"x": 100.0, "y": 66.666667, "z": 66.666667},
                            },
                            "shared_dimension_checks": [
                                {"axis": "x", "difference_mm": 0.0, "matched": True}
                            ],
                        }
                    }
                if name == "validate_drawing_modeling_plan":
                    return {
                        "structuredContent": {
                            "ready_for_modeling": True,
                            "mutation_performed": False,
                            "target_tool": "create_parametric_profile_extrusion",
                            "tool_arguments": build_profile_arguments(),
                            "blockers": [],
                        }
                    }
                if name == "create_parametric_profile_extrusion":
                    if arguments.get("name") == "BowTieInvalid":
                        return {"isError": True, "error": {"code": "PROFILE_SELF_INTERSECTION"}}
                    return {
                        "structuredContent": {
                            "recomputed": True,
                            "body": "LProfile",
                            "body_summary": {"name": "LProfile", "size_mm": [100.0, 60.0, 8.0]},
                            "parameters_created": [
                                "l_profile_depth",
                                *[
                                    f"l_profile_p{index}_{axis}"
                                    for index in range(1, 7)
                                    for axis in ("x", "y")
                                ],
                        ],
                        }
                    }
                if name == "get_viewport_screenshot":
                    return {"content": [{"type": "image", "data": "large-base64", "mimeType": "image/png"}]}
                if name == "export_design":
                    target = Path(arguments["path"])
                    target.write_bytes(b"verified-export")
                    return {"structuredContent": {"path": str(target), "verified": True}}
                if name == "undo_last_execution":
                    return {"structuredContent": {"undo_mode": "parametric_profile_deleted"}}
                raise AssertionError(name)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            top = root / "profile-l-top.png"
            front = root / "profile-l-front.png"
            top.write_bytes(b"top")
            front.write_bytes(b"front")
            with patch("scripts.live_profile_acceptance.MCPClient", SuccessfulClient):
                report = run_acceptance(
                    "http://127.0.0.1:9100/",
                    "test-bearer-token",
                    root,
                    top,
                    front,
                )
            rendered = json.dumps(report, ensure_ascii=False)

        calls = SuccessfulClient.instances[-1].calls
        self.assertTrue(report["ok"])
        self.assertEqual("initialize", calls[0])
        self.assertEqual("tools/list", calls[1])
        self.assertLess(calls.index("validate_drawing_modeling_plan"), calls.index("create_orthographic_canvas_set"))
        self.assertLess(calls.index("create_orthographic_canvas_set"), calls.index("create_parametric_profile_extrusion"))
        self.assertLess(calls.index("create_parametric_profile_extrusion"), calls.index("undo_last_execution"))
        self.assertNotIn("execute_fusion_python", calls)
        self.assertNotIn("large-base64", rendered)
        self.assertNotIn("test-bearer-token", rendered)
        self.assertNotIn(directory, rendered)


if __name__ == "__main__":
    unittest.main()
