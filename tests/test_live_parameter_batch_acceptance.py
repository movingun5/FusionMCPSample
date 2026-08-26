import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from scripts.live_parameter_batch_acceptance import (
    REQUIRED_TOOLS,
    build_batch_arguments,
    build_plate_arguments,
    run_acceptance,
)


class LiveParameterBatchAcceptanceTests(unittest.TestCase):
    def test_script_entrypoint_requires_blank_design_confirmation(self):
        repository = Path(__file__).resolve().parents[1]
        script = repository / "scripts" / "live_parameter_batch_acceptance.py"

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

    def test_builds_explicit_plate_and_compare_and_swap_batch(self):
        self.assertEqual("40 mm", build_plate_arguments()["width_expression"])
        updates = build_batch_arguments()["updates"]
        self.assertEqual(["batch_plate_width", "batch_plate_thickness"], [item["name"] for item in updates])
        self.assertEqual(["40 mm", "4 mm"], [item["expected_old_expression"] for item in updates])
        self.assertEqual(["60 mm", "6 mm"], [item["expression"] for item in updates])

    def test_full_flow_rejects_stale_batch_updates_atomically_and_undoes_valid_batch(self):
        class SuccessfulClient:
            instances = []

            def __init__(self, *_args, **_kwargs):
                self.calls = []
                self.plate_created = False
                self.batch_active = False
                self.__class__.instances.append(self)

            def call(self, method, _params=None):
                self.calls.append(method)
                if method == "initialize":
                    return {"serverInfo": {"name": "fusion", "version": "2.5.0"}}
                if method == "tools/list":
                    names = sorted(REQUIRED_TOOLS) + [
                        f"dummy_{index}" for index in range(24 - len(REQUIRED_TOOLS))
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
                            "server_version": "2.5.0",
                            "fusion_version": "2704.1.53",
                        }
                    }
                if name == "get_design_context":
                    if not self.plate_created:
                        return {
                            "structuredContent": {
                                "components": [{"name": "Root", "bodies": []}],
                                "parameters": [],
                            }
                        }
                    width = "60 mm" if self.batch_active else "40 mm"
                    thickness = "6 mm" if self.batch_active else "4 mm"
                    size = [60.0, 30.0, 6.0] if self.batch_active else [40.0, 30.0, 4.0]
                    half_width = size[0] / 2.0
                    half_height = size[1] / 2.0
                    return {
                        "structuredContent": {
                            "components": [
                                {
                                    "name": "Root",
                                    "bodies": [
                                        {
                                            "name": "BatchPlate",
                                            "size_mm": size,
                                            "bounding_box_mm": {
                                                "min": [-half_width, -half_height, 0.0],
                                                "max": [half_width, half_height, size[2]],
                                            },
                                        }
                                    ],
                                }
                            ],
                            "parameters": [
                                {"name": "batch_plate_width", "expression": width},
                                {"name": "batch_plate_height", "expression": "30 mm"},
                                {"name": "batch_plate_thickness", "expression": thickness},
                            ],
                        }
                    }
                if name == "create_parametric_plate":
                    self.plate_created = True
                    return {
                        "structuredContent": {
                            "action": "created",
                            "recomputed": True,
                            "body": "BatchPlate",
                        }
                    }
                if name == "update_parameter_batch":
                    if arguments["updates"][0]["expected_old_expression"] == "39 mm":
                        return {"isError": True, "error": {"code": "PARAMETER_CONFLICT"}}
                    self.batch_active = True
                    return {
                        "structuredContent": {
                            "action": "updated",
                            "recomputed": True,
                            "checkpoint_recorded": True,
                        }
                    }
                if name == "undo_last_execution":
                    self.batch_active = False
                    return {"message": "The most recent Codex Fusion execution was undone."}
                raise AssertionError(name)

        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "report.json"
            with patch("scripts.live_parameter_batch_acceptance.MCPClient", SuccessfulClient):
                report = run_acceptance("http://127.0.0.1:9100/", "secret")
            report_path.write_text(json.dumps(report), encoding="utf-8")

        calls = SuccessfulClient.instances[-1].calls
        self.assertTrue(report["ok"])
        self.assertEqual(10, report["passed"])
        self.assertEqual(2, calls.count("update_parameter_batch"))
        self.assertLess(calls.index("create_parametric_plate"), calls.index("update_parameter_batch"))
        self.assertLess(calls.index("update_parameter_batch"), calls.index("undo_last_execution"))
        self.assertNotIn("execute_fusion_python", calls)
        self.assertNotIn("secret", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
