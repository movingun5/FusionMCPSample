from pathlib import Path
import tempfile
import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.core.audit import AuditLogger
from fusion_mcp_addin.fusion.checkpoints import (
    clear_last_checkpoint,
    get_last_checkpoint,
)
from fusion_mcp_addin.fusion.sketches import create_rectangle_sketch
from tests.fakes import FakeApp, FakeComponent, FakeDesign, FakePoint


class RectangleSketchTests(unittest.TestCase):
    def setUp(self):
        clear_last_checkpoint()
        self.root = FakeComponent("Root", "root")
        self.design = FakeDesign([self.root])
        self.app = FakeApp(self.design)
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.audit = AuditLogger(Path(self.temp_directory.name) / "audit.jsonl")

    def tearDown(self):
        clear_last_checkpoint()

    def create(self, **kwargs):
        arguments = {
            "app": self.app,
            "name": "Base Rectangle",
            "width_expression": "100 mm",
            "height_expression": "60 mm",
            "point_factory": FakePoint,
            "dimension_orientations": {
                "horizontal": "horizontal",
                "vertical": "vertical",
            },
            "audit_logger": self.audit,
        }
        arguments.update(kwargs)
        return create_rectangle_sketch(**arguments)

    def test_creates_centered_rectangle_with_driving_expressions(self):
        result = self.create()

        sketch = self.root.sketches.itemByName("Base Rectangle")
        lines = sketch.sketchCurves.sketchLines
        expressions = [
            dimension.parameter.expression
            for dimension in sketch.sketchDimensions
        ]
        self.assertFalse(result["isError"])
        self.assertEqual(["100 mm", "60 mm"], expressions)
        self.assertEqual((0.0, 0.0), (lines.last_center.x, lines.last_center.y))
        self.assertEqual((5.0, 3.0), (lines.last_corner.x, lines.last_corner.y))
        self.assertEqual(
            [100.0, 60.0],
            result["structuredContent"]["evaluated_size_mm"],
        )
        self.assertEqual("create_rectangle_sketch", get_last_checkpoint()["mutation"])

    def test_uses_requested_construction_plane_and_center(self):
        result = self.create(
            plane="xz",
            center_x_expression="20 mm",
            center_y_expression="-10 mm",
        )

        sketch = self.root.sketches.itemByName("Base Rectangle")
        lines = sketch.sketchCurves.sketchLines
        self.assertFalse(result["isError"])
        self.assertIs(self.root.xZConstructionPlane, sketch.plane)
        self.assertEqual((2.0, -1.0), (lines.last_center.x, lines.last_center.y))

    def test_duplicate_name_is_rejected_before_transaction(self):
        self.create()
        self.app.commands.clear()

        result = self.create()

        self.assertEqual("SKETCH_NAME_CONFLICT", result["error"]["code"])
        self.assertEqual([], self.app.commands)
        self.assertEqual(1, self.root.sketches.count)

    def test_non_positive_size_is_rejected_before_transaction(self):
        result = self.create(width_expression="0 mm")

        self.assertEqual("SKETCH_DIMENSION_INVALID", result["error"]["code"])
        self.assertEqual([], self.app.commands)

    def test_recompute_failure_aborts_and_deletes_partial_sketch(self):
        self.design.compute_result = False

        result = self.create()

        self.assertEqual("RECOMPUTE_FAILED", result["error"]["code"])
        self.assertIsNone(self.root.sketches.itemByName("Base Rectangle"))
        self.assertEqual("PTransaction.Abort", self.app.commands[-1])
        self.assertIn("local_traceback", self.audit.path.read_text(encoding="utf-8"))

    def test_no_active_design_is_structured_error(self):
        result = create_rectangle_sketch(
            FakeApp(None),
            "Base Rectangle",
            "100 mm",
            "60 mm",
            point_factory=FakePoint,
            dimension_orientations={
                "horizontal": "horizontal",
                "vertical": "vertical",
            },
            audit_logger=self.audit,
        )

        self.assertEqual("NO_ACTIVE_DESIGN", result["error"]["code"])


if __name__ == "__main__":
    unittest.main()
