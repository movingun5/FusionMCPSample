import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.fusion.undo import undo_with
from tests.fakes import FakeApp, FakeComponent, FakeDesign


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


if __name__ == "__main__":
    unittest.main()
