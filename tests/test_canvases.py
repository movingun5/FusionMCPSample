from pathlib import Path
import tempfile
import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.core.audit import AuditLogger
from fusion_mcp_addin.fusion.canvases import create_reference_canvas
from fusion_mcp_addin.fusion.checkpoints import clear_last_checkpoint, get_last_checkpoint
from tests.fakes import FakeApp, FakeCanvas, FakeCanvasInput, FakeComponent, FakeDesign


class ReferenceCanvasTests(unittest.TestCase):
    def setUp(self):
        clear_last_checkpoint()
        self.root = FakeComponent("Root", "root")
        self.design = FakeDesign([self.root])
        self.app = FakeApp(self.design)
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.image_path = Path(self.temp_directory.name) / "plate.png"
        self.image_path.write_bytes(b"fake-image")
        self.audit = AuditLogger(Path(self.temp_directory.name) / "audit.jsonl")

    def tearDown(self):
        clear_last_checkpoint()

    def create(self, **kwargs):
        arguments = {
            "app": self.app,
            "name": "Front Reference",
            "image_path": str(self.image_path),
            "plane": "xy",
            "width_expression": "100 mm",
            "center_x_expression": "10 mm",
            "center_y_expression": "-5 mm",
            "opacity": 60,
            "flip_horizontal": False,
            "flip_vertical": False,
            "point_factory": lambda x, y: __import__(
                "tests.fakes", fromlist=["FakePoint2D"]
            ).FakePoint2D(x, y),
            "vector_factory": lambda x, y: __import__(
                "tests.fakes", fromlist=["FakeVector2D"]
            ).FakeVector2D(x, y),
            "audit_logger": self.audit,
        }
        arguments.update(kwargs)
        return create_reference_canvas(**arguments)

    def test_creates_calibrated_canvas_and_records_checkpoint(self):
        result = self.create()

        canvas = self.root.canvases.itemByName("Front Reference")
        content = result["structuredContent"]
        origin, x_axis, y_axis = canvas.transform.getAsCoordinateSystem()
        self.assertFalse(result["isError"])
        self.assertIs(self.root.xYConstructionPlane, canvas.planarEntity)
        self.assertEqual((1.0, -0.5), (origin.x, origin.y))
        self.assertEqual((10.0, 0.0), (x_axis.x, x_axis.y))
        self.assertEqual((0.0, 5.0), (y_axis.x, y_axis.y))
        self.assertEqual(60, canvas.opacity)
        self.assertTrue(canvas.isSelectable)
        self.assertEqual("plate.png", content["canvas"]["image_name"])
        self.assertEqual(100.0, content["canvas"]["width_mm"])
        self.assertEqual(50.0, content["canvas"]["height_mm"])
        self.assertNotIn(str(self.image_path.parent), repr(result))
        self.assertEqual("create_reference_canvas", get_last_checkpoint()["mutation"])

    def test_selects_each_supported_principal_plane(self):
        for plane, attribute in (
            ("xy", "xYConstructionPlane"),
            ("xz", "xZConstructionPlane"),
            ("yz", "yZConstructionPlane"),
        ):
            with self.subTest(plane=plane):
                result = self.create(name=f"{plane} reference", plane=plane)
                canvas = self.root.canvases.itemByName(f"{plane} reference")
                self.assertFalse(result["isError"])
                self.assertIs(getattr(self.root, attribute), canvas.planarEntity)

    def test_flip_options_reverse_axes_without_negative_reported_size(self):
        result = self.create(flip_horizontal=True, flip_vertical=True)

        canvas = self.root.canvases.itemByName("Front Reference")
        _, x_axis, y_axis = canvas.transform.getAsCoordinateSystem()
        self.assertLess(x_axis.x, 0)
        self.assertLess(y_axis.y, 0)
        self.assertEqual(100.0, result["structuredContent"]["canvas"]["width_mm"])
        self.assertEqual(50.0, result["structuredContent"]["canvas"]["height_mm"])

    def test_duplicate_name_is_rejected_before_transaction(self):
        seed = FakeCanvas(FakeCanvasInput(str(self.image_path), object()), "canvas-0")
        seed.name = "Front Reference"
        self.root.canvases._items.append(seed)

        result = self.create()

        self.assertEqual("CANVAS_NAME_CONFLICT", result["error"]["code"])
        self.assertEqual([], self.app.commands)

    def test_rejects_unsafe_or_invalid_file_paths_before_transaction(self):
        cases = (
            ("relative.png", "IMAGE_PATH_INVALID"),
            ("https://example.com/image.png", "IMAGE_PATH_INVALID"),
            (str(Path(self.temp_directory.name) / "missing.png"), "IMAGE_NOT_FOUND"),
        )
        bad_extension = Path(self.temp_directory.name) / "reference.gif"
        bad_extension.write_bytes(b"gif")
        cases += ((str(bad_extension), "IMAGE_FORMAT_UNSUPPORTED"),)

        for image_path, code in cases:
            with self.subTest(image_path=image_path):
                result = self.create(image_path=image_path)
                self.assertEqual(code, result["error"]["code"])
        self.assertEqual([], self.app.commands)

    def test_rejects_files_larger_than_25_mib(self):
        large = Path(self.temp_directory.name) / "large.png"
        with large.open("wb") as handle:
            handle.truncate((25 * 1024 * 1024) + 1)

        result = self.create(image_path=str(large))

        self.assertEqual("IMAGE_TOO_LARGE", result["error"]["code"])
        self.assertEqual([], self.app.commands)

    def test_rejects_invalid_plane_opacity_and_flip_types(self):
        for arguments in (
            {"plane": "front"},
            {"opacity": -1},
            {"opacity": True},
            {"flip_horizontal": 1},
            {"flip_vertical": "yes"},
        ):
            with self.subTest(arguments=arguments):
                result = self.create(**arguments)
                self.assertEqual("INVALID_REQUEST", result["error"]["code"])
        self.assertEqual([], self.app.commands)

    def test_rejects_invalid_or_nonpositive_expressions(self):
        for arguments, code in (
            ({"width_expression": "wide"}, "CANVAS_EXPRESSION_INVALID"),
            ({"width_expression": "0 mm"}, "CANVAS_WIDTH_INVALID"),
            ({"center_x_expression": "left"}, "CANVAS_EXPRESSION_INVALID"),
        ):
            with self.subTest(arguments=arguments):
                result = self.create(**arguments)
                self.assertEqual(code, result["error"]["code"])
        self.assertEqual([], self.app.commands)

    def test_recompute_failure_aborts_transaction_without_leaking_path(self):
        self.design.compute_result = False

        result = self.create()

        audit_text = self.audit.path.read_text(encoding="utf-8")
        self.assertEqual("RECOMPUTE_FAILED", result["error"]["code"])
        self.assertEqual("PTransaction.Abort", self.app.commands[-1])
        self.assertNotIn(str(self.image_path.parent), audit_text)

    def test_no_active_design_is_retryable(self):
        result = self.create(app=FakeApp())

        self.assertEqual("NO_ACTIVE_DESIGN", result["error"]["code"])
        self.assertTrue(result["error"]["retryable"])


if __name__ == "__main__":
    unittest.main()
