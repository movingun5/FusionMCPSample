import json
from pathlib import Path
import tempfile
import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from scripts.check_install import build_report


class InstallCheckTests(unittest.TestCase):
    def test_report_never_contains_token(self):
        with tempfile.TemporaryDirectory() as directory:
            addon_path = Path(directory) / "Fusion MCP Addin"
            addon_path.mkdir()
            (addon_path / "Fusion MCP Addin.manifest").write_text("{}", encoding="utf-8")

            report = build_report(
                env={"FUSION_MCP_TOKEN": "top-secret"},
                addon_path=addon_path,
                probe_server=False,
            )

            rendered = json.dumps(report)
            self.assertNotIn("top-secret", rendered)
            token_check = next(check for check in report["checks"] if check["code"] == "TOKEN_CONFIGURED")
            self.assertTrue(token_check["ok"])

    def test_missing_manifest_is_first_actionable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            report = build_report(
                env={},
                addon_path=Path(directory) / "missing",
                probe_server=False,
            )

            self.assertEqual("ADDIN_MANIFEST_MISSING", report["checks"][0]["code"])
            self.assertFalse(report["ok"])

    def test_server_probe_is_explicitly_skipped_in_unit_tests(self):
        with tempfile.TemporaryDirectory() as directory:
            addon_path = Path(directory)
            (addon_path / "Fusion MCP Addin.manifest").write_text("{}", encoding="utf-8")

            report = build_report(env={}, addon_path=addon_path, probe_server=False)

            server_check = next(check for check in report["checks"] if check["code"] == "SERVER_PROBE_SKIPPED")
            self.assertTrue(server_check["ok"])


if __name__ == "__main__":
    unittest.main()
