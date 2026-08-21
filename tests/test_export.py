from pathlib import Path
import tempfile
import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.fusion.exporting import export_with, validate_export_request
from tests.fakes import FakeApp, FakeComponent, FakeDesign, FakeExportManager, FakeUI


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.root = FakeComponent("Root", "root")
        self.design = FakeDesign([self.root])
        self.design.exportManager = FakeExportManager()
        self.app = FakeApp(self.design)
        self.ui = FakeUI()

    def test_existing_export_requires_explicit_overwrite(self):
        path = Path(self.temp_directory.name) / "part.step"
        path.write_bytes(b"existing")

        error = validate_export_request("step", path, overwrite=False)

        self.assertEqual("EXPORT_TARGET_EXISTS", error["code"])

    def test_export_rejects_unsupported_format(self):
        path = Path(self.temp_directory.name) / "part.f3d"

        error = validate_export_request("f3d", path, overwrite=False)

        self.assertEqual("INVALID_REQUEST", error["code"])

    def test_export_requires_absolute_path_and_matching_extension(self):
        self.assertEqual(
            "INVALID_REQUEST",
            validate_export_request("step", "part.step", overwrite=False)["code"],
        )
        mismatch = Path(self.temp_directory.name) / "part.stl"
        self.assertEqual(
            "INVALID_REQUEST",
            validate_export_request("step", mismatch, overwrite=False)["code"],
        )

    def test_step_export_verifies_created_nonempty_file(self):
        path = Path(self.temp_directory.name) / "part.step"

        result = export_with(self.app, self.ui, "step", path)

        self.assertFalse(result["isError"])
        self.assertTrue(path.exists())
        self.assertEqual(path.stat().st_size, result["export"]["size_bytes"])
        self.assertEqual("step", result["export"]["format"])

    def test_overwrite_is_cancelled_when_fusion_approval_is_denied(self):
        path = Path(self.temp_directory.name) / "part.stl"
        path.write_bytes(b"existing")

        result = export_with(
            self.app,
            self.ui,
            "stl",
            path,
            overwrite=True,
            approval_callback=lambda decision, intent: False,
        )

        self.assertEqual("POLICY_APPROVAL_REQUIRED", result["error"]["code"])
        self.assertEqual(b"existing", path.read_bytes())


if __name__ == "__main__":
    unittest.main()
