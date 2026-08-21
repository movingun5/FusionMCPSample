from pathlib import Path
import tempfile
import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.core.audit import AuditLogger
from fusion_mcp_addin.fusion.checkpoints import clear_last_checkpoint, get_last_checkpoint
from fusion_mcp_addin.fusion.patterns import create_linear_pattern
from tests.fakes import (
    FakeApp,
    FakeCollection,
    FakeComponent,
    FakeDesign,
    FakeFeature,
)


class _ObjectCollection(FakeCollection):
    def add(self, item):
        self._items.append(item)
        return True


class _PatternInput:
    def __init__(self, entities, axis, quantity, spacing, distance_type):
        self.entities = entities
        self.axis = axis
        self.quantity = quantity
        self.spacing = spacing
        self.distance_type = distance_type


class _PatternFeature(FakeFeature):
    def __init__(self, pattern_input):
        super().__init__("RectangularPattern", "pattern-1")
        self.input = pattern_input
        self.deleted = False

    def deleteMe(self):
        self.deleted = True
        return True


class _RectangularPatterns(FakeCollection):
    def itemByName(self, name):
        return next(
            (
                item
                for item in self._items
                if item.name == name and not getattr(item, "deleted", False)
            ),
            None,
        )

    def createInput(self, entities, axis, quantity, spacing, distance_type):
        return _PatternInput(entities, axis, quantity, spacing, distance_type)

    def add(self, pattern_input):
        feature = _PatternFeature(pattern_input)
        self._items.append(feature)
        return feature


class _Features(FakeCollection):
    def __init__(self, items=()):
        super().__init__(items)
        self.rectangularPatternFeatures = _RectangularPatterns()


class LinearPatternTests(unittest.TestCase):
    def setUp(self):
        clear_last_checkpoint()
        self.seed = FakeFeature("Seed Hole", "hole-1")
        self.root = FakeComponent("Root", "root")
        self.root.features = _Features([self.seed])
        self.root.xConstructionAxis = object()
        self.root.yConstructionAxis = object()
        self.root.zConstructionAxis = object()
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
            "name": "Hole Row",
            "target_feature_name": "Seed Hole",
            "axis": "x",
            "quantity": 3,
            "spacing_expression": "15 mm",
            "value_input_factory": lambda expression: expression,
            "object_collection_factory": _ObjectCollection,
            "spacing_pattern_distance_type": "spacing",
            "audit_logger": self.audit,
        }
        arguments.update(kwargs)
        return create_linear_pattern(**arguments)

    def test_creates_feature_pattern_with_adjacent_spacing(self):
        result = self.create()

        feature = self.root.features.rectangularPatternFeatures.itemByName("Hole Row")
        pattern_input = feature.input
        self.assertFalse(result["isError"])
        self.assertEqual(1, pattern_input.entities.count)
        self.assertIs(self.seed, pattern_input.entities.item(0))
        self.assertIs(self.root.xConstructionAxis, pattern_input.axis)
        self.assertEqual("3", pattern_input.quantity)
        self.assertEqual("15 mm", pattern_input.spacing)
        self.assertEqual("spacing", pattern_input.distance_type)
        self.assertEqual(15.0, result["structuredContent"]["evaluated_spacing_mm"])
        self.assertEqual("create_linear_pattern", get_last_checkpoint()["mutation"])

    def test_selects_y_and_z_construction_axes(self):
        for axis in ("y", "z"):
            with self.subTest(axis=axis):
                name = f"{axis.upper()} Pattern"
                result = self.create(name=name, axis=axis)
                feature = self.root.features.rectangularPatternFeatures.itemByName(name)
                self.assertFalse(result["isError"])
                self.assertIs(
                    getattr(self.root, f"{axis}ConstructionAxis"),
                    feature.input.axis,
                )

    def test_missing_target_feature_is_rejected_before_transaction(self):
        result = self.create(target_feature_name="Missing")

        self.assertEqual("FEATURE_NOT_FOUND", result["error"]["code"])
        self.assertEqual([], self.app.commands)

    def test_quantity_below_two_is_rejected_before_transaction(self):
        result = self.create(quantity=1)

        self.assertEqual("PATTERN_QUANTITY_INVALID", result["error"]["code"])
        self.assertEqual([], self.app.commands)

    def test_zero_spacing_is_rejected_before_transaction(self):
        result = self.create(spacing_expression="0 mm")

        self.assertEqual("PATTERN_SPACING_INVALID", result["error"]["code"])
        self.assertEqual([], self.app.commands)

    def test_duplicate_pattern_name_is_rejected(self):
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
