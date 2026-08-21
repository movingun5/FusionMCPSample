import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.fusion.checkpoints import (
    clear_last_checkpoint,
    get_last_checkpoint,
    record_checkpoint,
)


class CheckpointTests(unittest.TestCase):
    def tearDown(self):
        clear_last_checkpoint()

    def test_record_returns_and_stores_defensive_copies(self):
        source = {
            "request_id": "r1",
            "document_id": "doc-1",
            "timeline_marker": 2,
        }

        recorded = record_checkpoint(source)
        source["request_id"] = "changed"
        recorded["request_id"] = "also-changed"

        self.assertEqual("r1", get_last_checkpoint()["request_id"])

    def test_clear_removes_checkpoint(self):
        record_checkpoint({"request_id": "r1"})

        clear_last_checkpoint()

        self.assertIsNone(get_last_checkpoint())


if __name__ == "__main__":
    unittest.main()
