import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.fusion.undo import undo_with
from tests.fakes import (
    FakeApp,
    FakeCanvasInput,
    FakeComponent,
    FakeDesign,
)


class UndoTests(unittest.TestCase):
    def setUp(self):
        self.design = FakeDesign([FakeComponent("Root", "root")])
        self.app = FakeApp(self.design)

    def test_undo_without_checkpoint_is_structured_error(self):
        result = undo_with(self.app, None)

        self.assertEqual("NO_EXECUTION_CHECKPOINT", result["error"]["code"])

    def test_undo_rejects_checkpoint_from_different_document(self):
        result = undo_with(self.app, {"document_id": "another-document"})

        self.assertEqual("CHECKPOINT_DOCUMENT_MISMATCH", result["error"]["code"])
        self.assertEqual([], self.app.commands)

    def test_undo_runs_fusion_command_and_recomputes(self):
        checkpoint = {"document_id": self.design.parentDocument.id, "request_id": "request-1"}

        result = undo_with(self.app, checkpoint)

        self.assertFalse(result["isError"])
        self.assertEqual("Commands.Start UndoCommand", self.app.commands[-1])
        self.assertEqual("request-1", result["undone_request_id"])

    def test_undo_reference_canvas_deletes_the_exact_checkpoint_canvas(self):
        root = self.design.rootComponent
        canvas = root.canvases.add(
            FakeCanvasInput(r"C:\reference\plate.png", root.xYConstructionPlane)
        )
        canvas.name = "Reference Canvas"
        checkpoint = {
            "document_id": self.design.parentDocument.id,
            "request_id": "request-canvas",
            "mutation": "create_reference_canvas",
            "canvas_name": "Reference Canvas",
            "canvas_entity_token": canvas.entityToken,
        }

        result = undo_with(self.app, checkpoint)

        self.assertFalse(result["isError"])
        self.assertEqual(0, root.canvases.count)
        self.assertEqual("canvas_deleted", result["undo_mode"])
        self.assertNotIn("Commands.Start UndoCommand", self.app.commands)

    def test_undo_canvas_set_deletes_every_checkpoint_canvas(self):
        root = self.design.rootComponent
        xy_canvas = root.canvases.add(
            FakeCanvasInput(r"C:\reference\top.png", root.xYConstructionPlane)
        )
        xy_canvas.name = "Assembly_XY"
        xz_canvas = root.canvases.add(
            FakeCanvasInput(r"C:\reference\front.png", root.xZConstructionPlane)
        )
        xz_canvas.name = "Assembly_XZ"
        checkpoint = {
            "document_id": self.design.parentDocument.id,
            "request_id": "request-canvas-set",
            "mutation": "create_orthographic_canvas_set",
            "component_entity_token": root.entityToken,
            "starting_canvas_count": 0,
            "canvases": [
                {"name": xy_canvas.name, "entity_token": xy_canvas.entityToken},
                {"name": xz_canvas.name, "entity_token": xz_canvas.entityToken},
            ],
        }

        result = undo_with(self.app, checkpoint)

        self.assertFalse(result["isError"])
        self.assertEqual(0, root.canvases.count)
        self.assertEqual(0, result["canvas_count"])
        self.assertEqual("canvas_set_deleted", result["undo_mode"])
        self.assertEqual(
            'PTransaction.Start "Codex Undo Orthographic Canvas Set"',
            self.app.commands[0],
        )
        self.assertEqual("PTransaction.Commit", self.app.commands[-1])
        self.assertNotIn("Commands.Start UndoCommand", self.app.commands)

    def test_undo_canvas_set_refuses_partial_target_match(self):
        root = self.design.rootComponent
        xy_canvas = root.canvases.add(
            FakeCanvasInput(r"C:\reference\top.png", root.xYConstructionPlane)
        )
        xy_canvas.name = "Assembly_XY"
        unrelated = root.canvases.add(
            FakeCanvasInput(r"C:\reference\other.png", root.xZConstructionPlane)
        )
        unrelated.name = "Other"
        checkpoint = {
            "document_id": self.design.parentDocument.id,
            "request_id": "request-canvas-set",
            "mutation": "create_orthographic_canvas_set",
            "component_entity_token": root.entityToken,
            "starting_canvas_count": 0,
            "canvases": [
                {"name": xy_canvas.name, "entity_token": xy_canvas.entityToken},
                {"name": "Assembly_XZ", "entity_token": "missing-token"},
            ],
        }

        result = undo_with(self.app, checkpoint)

        self.assertEqual("CHECKPOINT_ENTITY_NOT_FOUND", result["error"]["code"])
        self.assertEqual(2, root.canvases.count)
        self.assertFalse(xy_canvas.deleted)
        self.assertFalse(unrelated.deleted)
        self.assertEqual([], self.app.commands)


if __name__ == "__main__":
    unittest.main()
