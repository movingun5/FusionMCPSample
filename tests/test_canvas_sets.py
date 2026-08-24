from pathlib import Path
import tempfile
import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.core.audit import AuditLogger
from fusion_mcp_addin.fusion.canvas_sets import create_orthographic_canvas_set
from fusion_mcp_addin.fusion.checkpoints import clear_last_checkpoint, get_last_checkpoint
from tests.fakes import FakeApp, FakeCanvas, FakeCanvasInput, FakeComponent, FakeDesign
from tests.fakes import FakePoint2D, FakeVector2D


class OrthographicCanvasSetTests(unittest.TestCase):
    def setUp(self):
        clear_last_checkpoint()
        self.root = FakeComponent("Root", "root")
        self.design = FakeDesign([self.root])
        self.app = FakeApp(self.design)
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.xy_image = Path(self.temp_directory.name) / "top.png"
        self.xz_image = Path(self.temp_directory.name) / "front.png"
        self.yz_image = Path(self.temp_directory.name) / "side.png"
        for path in (self.xy_image, self.xz_image, self.yz_image):
            path.write_bytes(b"fake-image")
        self.audit = AuditLogger(Path(self.temp_directory.name) / "audit.jsonl")

    def tearDown(self):
        clear_last_checkpoint()

    def views(self, include_yz=False):
        views = [
            {
                "image_path": str(self.xy_image),
                "plane": "xy",
                "width_expression": "100 mm",
            },
            {
                "image_path": str(self.xz_image),
                "plane": "xz",
                "width_expression": "100 mm",
            },
        ]
        if include_yz:
            views.append(
                {
                    "image_path": str(self.yz_image),
                    "plane": "yz",
                    "width_expression": "100 mm",
                }
            )
        return views

    def create(self, views=None, **kwargs):
        arguments = {
            "app": self.app,
            "name": "Assembly",
            "views": views if views is not None else self.views(),
            "dimension_tolerance_mm": 0.25,
            "point_factory": FakePoint2D,
            "vector_factory": FakeVector2D,
            "audit_logger": self.audit,
        }
        arguments.update(kwargs)
        return create_orthographic_canvas_set(**arguments)

    def test_creates_two_view_set_in_one_transaction_and_checkpoint(self):
        result = self.create()

        content = result["structuredContent"]
        self.assertFalse(result["isError"])
        self.assertEqual(2, self.root.canvases.count)
        self.assertEqual(
            ["Assembly_XY", "Assembly_XZ"],
            [view["name"] for view in content["set"]["views"]],
        )
        self.assertEqual(
            {"x": 100.0, "y": 50.0, "z": 50.0},
            content["set"]["axes_mm"],
        )
        self.assertEqual(1, len(content["shared_dimension_checks"]))
        self.assertEqual(
            'PTransaction.Start "Codex Orthographic Canvas Set"',
            self.app.commands[0],
        )
        self.assertEqual("PTransaction.Commit", self.app.commands[-1])
        checkpoint = get_last_checkpoint()
        self.assertEqual("create_orthographic_canvas_set", checkpoint["mutation"])
        self.assertEqual(2, len(checkpoint["canvases"]))
        self.assertEqual(0, checkpoint["starting_canvas_count"])

    def test_creates_three_view_set_and_checks_all_shared_axes(self):
        self.root.canvases.aspect_ratio = 1.0
        result = self.create(views=self.views(include_yz=True))

        content = result["structuredContent"]
        self.assertFalse(result["isError"])
        self.assertEqual(3, self.root.canvases.count)
        self.assertEqual(["x", "y", "z"], [
            check["axis"] for check in content["shared_dimension_checks"]
        ])
        self.assertEqual(
            {"x": 100.0, "y": 100.0, "z": 100.0},
            content["set"]["axes_mm"],
        )

    def test_dimension_mismatch_is_rejected_before_transaction(self):
        views = self.views()
        views[1]["width_expression"] = "100.3 mm"

        result = self.create(views=views)

        self.assertEqual("ORTHOGRAPHIC_DIMENSION_MISMATCH", result["error"]["code"])
        self.assertEqual([], self.app.commands)
        self.assertEqual(0, self.root.canvases.count)

    def test_difference_at_tolerance_is_accepted(self):
        views = self.views()
        views[1]["width_expression"] = "100.25 mm"

        result = self.create(views=views)

        self.assertFalse(result["isError"])
        check = result["structuredContent"]["shared_dimension_checks"][0]
        self.assertEqual(0.25, check["difference_mm"])
        self.assertTrue(check["matched"])

    def test_second_add_failure_aborts_and_removes_the_whole_set(self):
        self.root.canvases.fail_add_at = 2

        result = self.create()

        self.assertEqual("CANVAS_SET_WRITE_FAILED", result["error"]["code"])
        self.assertEqual("PTransaction.Abort", self.app.commands[-1])
        self.assertEqual(0, self.root.canvases.count)

    def test_nontransaction_failure_deletes_partial_canvases_in_reverse_order(self):
        self.app.activeDocument = None
        self.root.canvases.aspect_ratio = 1.0
        self.root.canvases.fail_add_at = 3

        result = self.create(views=self.views(include_yz=True))

        self.assertEqual("CANVAS_SET_WRITE_FAILED", result["error"]["code"])
        self.assertEqual([], self.app.commands)
        self.assertEqual(0, self.root.canvases.count)
        self.assertEqual(["canvas-2", "canvas-1"], self.root.canvases.deleted_tokens)

    def test_name_conflict_and_bad_view_are_rejected_before_transaction(self):
        seed = FakeCanvas(FakeCanvasInput(str(self.xy_image), object()), "canvas-0")
        seed.name = "Assembly_XZ"
        self.root.canvases._items.append(seed)

        conflict = self.create()
        self.assertEqual("CANVAS_NAME_CONFLICT", conflict["error"]["code"])
        self.assertEqual([], self.app.commands)

        self.root.canvases._items.clear()
        bad_views = self.views()
        bad_views[1]["width_expression"] = "wide"
        invalid = self.create(views=bad_views)
        self.assertEqual("CANVAS_EXPRESSION_INVALID", invalid["error"]["code"])
        self.assertEqual([], self.app.commands)

    def test_recompute_failure_aborts_without_leaking_image_paths(self):
        self.design.compute_result = False

        result = self.create()

        audit_text = self.audit.path.read_text(encoding="utf-8")
        self.assertEqual("RECOMPUTE_FAILED", result["error"]["code"])
        self.assertEqual("PTransaction.Abort", self.app.commands[-1])
        self.assertEqual(0, self.root.canvases.count)
        self.assertNotIn(str(self.xy_image.parent), repr(result))
        self.assertNotIn(str(self.xy_image.parent), audit_text)

    def test_success_result_and_audit_use_only_image_basenames(self):
        result = self.create()

        audit_text = self.audit.path.read_text(encoding="utf-8")
        self.assertIn("top.png", repr(result))
        self.assertIn("front.png", audit_text)
        self.assertNotIn(str(self.xy_image.parent), repr(result))
        self.assertNotIn(str(self.xy_image.parent), audit_text)


if __name__ == "__main__":
    unittest.main()
