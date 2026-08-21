from pathlib import Path
import tempfile
import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.core.audit import AuditLogger
from fusion_mcp_addin.fusion.checkpoints import clear_last_checkpoint, get_last_checkpoint
from fusion_mcp_addin.fusion.extrusions import create_extrusion
from tests.fakes import (
    FakeApp,
    FakeBody,
    FakeCollection,
    FakeComponent,
    FakeDesign,
    FakeFeature,
    FakeSketch,
)


class _AreaProperties:
    def __init__(self, area):
        self.area = area


class _Profile:
    def __init__(self, area):
        self.area = area

    def areaProperties(self):
        return _AreaProperties(self.area)


class _ExtrudeFeature(FakeFeature):
    def __init__(self, profile, distance, operation):
        super().__init__("Extrude", "extrude-1")
        self.profile = profile
        self.distance = distance
        self.operation = operation
        self.bodies = FakeCollection(
            [FakeBody("Body1", "body-1", volume=12.5, maximum=(5, 3, 1))]
        )
        self.deleted = False

    def deleteMe(self):
        self.deleted = True
        return True


class _Extrudes(FakeCollection):
    def itemByName(self, name):
        return next(
            (item for item in self._items if item.name == name and not item.deleted),
            None,
        )

    def addSimple(self, profile, distance, operation):
        feature = _ExtrudeFeature(profile, distance, operation)
        self._items.append(feature)
        return feature


class _Features(FakeCollection):
    def __init__(self):
        super().__init__()
        self.extrudeFeatures = _Extrudes(self._items)


class ExtrusionTests(unittest.TestCase):
    def setUp(self):
        clear_last_checkpoint()
        self.sketch = FakeSketch("Base Rectangle", "sketch-1")
        self.small_profile = _Profile(10.0)
        self.large_profile = _Profile(60.0)
        self.sketch.profiles = FakeCollection([self.small_profile, self.large_profile])
        self.root = FakeComponent("Root", "root", sketches=[self.sketch])
        self.root.features = _Features()
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
            "name": "Base Extrusion",
            "sketch_name": "Base Rectangle",
            "distance_expression": "10 mm",
            "value_input_factory": lambda expression: expression,
            "new_body_operation": "new-body",
            "audit_logger": self.audit,
        }
        arguments.update(kwargs)
        return create_extrusion(**arguments)

    def test_extrudes_largest_profile_as_new_body(self):
        result = self.create()

        feature = self.root.features.extrudeFeatures.itemByName("Base Extrusion")
        self.assertFalse(result["isError"])
        self.assertIs(self.large_profile, feature.profile)
        self.assertEqual("10 mm", feature.distance)
        self.assertEqual(1, result["structuredContent"]["selected_profile_index"])
        self.assertEqual(10.0, result["structuredContent"]["evaluated_distance_mm"])
        self.assertEqual("create_extrusion", get_last_checkpoint()["mutation"])

    def test_missing_sketch_is_rejected_before_transaction(self):
        result = self.create(sketch_name="Missing")

        self.assertEqual("SKETCH_NOT_FOUND", result["error"]["code"])
        self.assertEqual([], self.app.commands)

    def test_empty_profile_is_rejected_before_transaction(self):
        self.sketch.profiles = FakeCollection()

        result = self.create()

        self.assertEqual("SKETCH_HAS_NO_PROFILE", result["error"]["code"])
        self.assertEqual([], self.app.commands)

    def test_zero_distance_is_rejected_before_transaction(self):
        result = self.create(distance_expression="0 mm")

        self.assertEqual("EXTRUSION_DISTANCE_INVALID", result["error"]["code"])
        self.assertEqual([], self.app.commands)

    def test_duplicate_feature_name_is_rejected(self):
        self.create()
        self.app.commands.clear()

        result = self.create()

        self.assertEqual("FEATURE_NAME_CONFLICT", result["error"]["code"])
        self.assertEqual([], self.app.commands)

    def test_recompute_failure_aborts_transaction(self):
        self.design.compute_result = False

        result = self.create()

        self.assertEqual("RECOMPUTE_FAILED", result["error"]["code"])
        self.assertEqual("PTransaction.Abort", self.app.commands[-1])
        self.assertIn("local_traceback", self.audit.path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
