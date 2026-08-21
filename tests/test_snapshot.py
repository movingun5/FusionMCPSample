import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.fusion.snapshot import capture_snapshot, compare_snapshots
from tests.fakes import FakeBody, FakeComponent, FakeDesign, FakeFeature, FakeSketch


class SnapshotTests(unittest.TestCase):
    def test_snapshot_contains_counts_geometry_and_timeline(self):
        body = FakeBody("Plate", "body-1", volume=30.0, maximum=(10.0, 6.0, 0.5))
        sketch = FakeSketch("Base", "sketch-1", profile_count=1)
        feature = FakeFeature("Extrude", "feature-1")
        design = FakeDesign([FakeComponent("Root", "component-1", [body], [sketch], [feature])])

        snapshot = capture_snapshot(design)

        self.assertEqual({"components": 1, "bodies": 1, "sketches": 1, "features": 1}, snapshot["counts"])
        self.assertEqual([100.0, 60.0, 5.0], snapshot["bodies"][0]["size_mm"])
        self.assertEqual(2, snapshot["timeline"]["marker_position"])

    def test_snapshot_delta_matches_expected_count_changes(self):
        before = {"counts": {"features": 2, "bodies": 1}, "failed_features": []}
        after = {"counts": {"features": 3, "bodies": 1}, "failed_features": []}

        result = compare_snapshots(before, after, {"features_created": 1, "bodies_created": 0})

        self.assertEqual(1, result["delta"]["features"])
        self.assertTrue(result["expectations_met"])
        self.assertEqual([], result["mismatches"])

    def test_snapshot_delta_reports_mismatch_and_failed_features(self):
        before = {"counts": {"features": 2}, "failed_features": []}
        after = {"counts": {"features": 2}, "failed_features": [{"name": "Extrude"}]}

        result = compare_snapshots(before, after, {"features_created": 1})

        self.assertFalse(result["expectations_met"])
        self.assertIn("features_created", result["mismatches"][0])
        self.assertEqual([{"name": "Extrude"}], result["failed_features"])


if __name__ == "__main__":
    unittest.main()
