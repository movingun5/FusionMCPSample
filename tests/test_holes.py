from pathlib import Path
import tempfile
import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.core.audit import AuditLogger
from fusion_mcp_addin.fusion.checkpoints import clear_last_checkpoint, get_last_checkpoint
from fusion_mcp_addin.fusion.holes import create_simple_hole
from tests.fakes import (
    FakeApp,
    FakeBody,
    FakeCollection,
    FakeComponent,
    FakeDesign,
    FakeFeature,
    FakePoint,
)


class _Plane:
    objectType = "adsk::core::Plane"


class _Evaluator:
    def __init__(self, normal):
        self.normal = normal

    def getNormalAtPoint(self, point):
        return True, self.normal


class _Face:
    def __init__(self, z, normal=(0.0, 0.0, 1.0), planar=True):
        self.pointOnFace = FakePoint(0.0, 0.0, z)
        self.evaluator = _Evaluator(FakePoint(*normal))
        self.geometry = _Plane() if planar else object()


class _HoleInput:
    def __init__(self, diameter):
        self.diameter = diameter
        self.point = None
        self.depth = None
        self.participantBodies = []

    def setPositionBySketchPoint(self, point):
        self.point = point
        return True

    def setDistanceExtent(self, depth):
        self.depth = depth
        return True


class _HoleFeature(FakeFeature):
    def __init__(self, hole_input):
        super().__init__("Hole", "hole-1")
        self.input = hole_input
        self.deleted = False

    def deleteMe(self):
        self.deleted = True
        return True


class _Holes(FakeCollection):
    def itemByName(self, name):
        return next(
            (item for item in self._items if item.name == name and not item.deleted),
            None,
        )

    def createSimpleInput(self, diameter):
        return _HoleInput(diameter)

    def add(self, hole_input):
        feature = _HoleFeature(hole_input)
        self._items.append(feature)
        return feature


class _Features(FakeCollection):
    def __init__(self):
        super().__init__()
        self.holeFeatures = _Holes(self._items)


class SimpleHoleTests(unittest.TestCase):
    def setUp(self):
        clear_last_checkpoint()
        self.body = FakeBody("Base Body", "body-1", maximum=(5, 3, 1))
        self.body.faces = FakeCollection(
            [
                _Face(0.0, normal=(0.0, 0.0, -1.0)),
                _Face(1.0),
                _Face(0.5, normal=(1.0, 0.0, 0.0)),
            ]
        )
        self.root = FakeComponent("Root", "root", bodies=[self.body])
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
            "name": "Mount Hole",
            "body_name": "Base Body",
            "x_expression": "20 mm",
            "y_expression": "-10 mm",
            "diameter_expression": "6 mm",
            "depth_expression": "12 mm",
            "point_factory": FakePoint,
            "value_input_factory": lambda expression: expression,
            "dimension_orientations": {
                "horizontal": "horizontal",
                "vertical": "vertical",
            },
            "audit_logger": self.audit,
        }
        arguments.update(kwargs)
        return create_simple_hole(**arguments)

    def test_creates_parametric_hole_on_top_face(self):
        result = self.create()

        feature = self.root.features.holeFeatures.itemByName("Mount Hole")
        sketch = self.root.sketches.itemByName("Mount Hole Placement")
        expressions = [
            dimension.parameter.expression for dimension in sketch.sketchDimensions
        ]
        self.assertFalse(result["isError"])
        self.assertEqual(["20 mm", "-(-10 mm)"], expressions)
        self.assertEqual("6 mm", feature.input.diameter)
        self.assertEqual("12 mm", feature.input.depth)
        self.assertEqual([self.body], feature.input.participantBodies)
        self.assertFalse(sketch.isVisible)
        self.assertEqual("create_simple_hole", get_last_checkpoint()["mutation"])

    def test_zero_coordinates_use_origin_without_dimensions(self):
        result = self.create(x_expression="0 mm", y_expression="0 mm")

        feature = self.root.features.holeFeatures.itemByName("Mount Hole")
        sketch = self.root.sketches.itemByName("Mount Hole Placement")
        self.assertFalse(result["isError"])
        self.assertIs(sketch.originPoint, feature.input.point)
        self.assertEqual(0, sketch.sketchDimensions.count)

    def test_missing_body_is_rejected_before_transaction(self):
        result = self.create(body_name="Missing")

        self.assertEqual("BODY_NOT_FOUND", result["error"]["code"])
        self.assertEqual([], self.app.commands)

    def test_non_positive_dimensions_are_rejected(self):
        result = self.create(diameter_expression="0 mm")

        self.assertEqual("HOLE_DIMENSION_INVALID", result["error"]["code"])
        self.assertEqual([], self.app.commands)

    def test_missing_top_face_is_rejected(self):
        self.body.faces = FakeCollection([_Face(0.0, normal=(1.0, 0.0, 0.0))])

        result = self.create()

        self.assertEqual("TOP_FACE_NOT_FOUND", result["error"]["code"])
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
