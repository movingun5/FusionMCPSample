from pathlib import Path
import tempfile
import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.core.audit import AuditLogger
from fusion_mcp_addin.fusion.checkpoints import clear_last_checkpoint, get_last_checkpoint
from fusion_mcp_addin.fusion.parametric_plates import create_parametric_plate
from fusion_mcp_addin.fusion.plate_builder import FusionPlateBuilder
from tests.fakes import FakeApp, FakeComponent, FakeDesign, FakeOccurrences, FakePoint
from tests.test_plate_builder import _Features, _ObjectCollection, _component_factory


class ParametricPlateTests(unittest.TestCase):
    def setUp(self):
        clear_last_checkpoint()
        self.root = FakeComponent("Root", "root")
        self.root.occurrences = FakeOccurrences(
            component_factory=lambda: _component_factory()
        )
        self.design = FakeDesign([self.root])
        self.app = FakeApp(self.design)
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.audit = AuditLogger(Path(self.temp_directory.name) / "audit.jsonl")

    def tearDown(self):
        clear_last_checkpoint()

    @staticmethod
    def builder_factory(design, root):
        return FusionPlateBuilder(
            design,
            root,
            point_factory=FakePoint,
            matrix_factory=lambda: object(),
            value_input_factory=lambda expression: expression,
            dimension_orientations={"horizontal": "horizontal", "vertical": "vertical"},
            new_body_operation="new-body",
            object_collection_factory=_ObjectCollection,
            part_design_intent="PartDesignIntentType",
        )

    @staticmethod
    def part_builder_factory(design, root):
        return FusionPlateBuilder(
            design,
            root,
            point_factory=FakePoint,
            matrix_factory=lambda: object(),
            value_input_factory=lambda expression: expression,
            dimension_orientations={"horizontal": "horizontal", "vertical": "vertical"},
            new_body_operation="new-body",
            object_collection_factory=_ObjectCollection,
            part_design_intent="PartDesignIntentType",
        )

    def arguments(self):
        return {
            "app": self.app,
            "name": "MountingPlate",
            "parameter_prefix": "plate",
            "width_expression": "100 mm",
            "height_expression": "60 mm",
            "thickness_expression": "5 mm",
            "holes": [
                {"key": "lower_left", "x_expression": "-40 mm", "y_expression": "-20 mm", "diameter_expression": "6 mm"},
                {"key": "upper_left", "x_expression": "-40 mm", "y_expression": "20 mm", "diameter_expression": "6 mm"},
                {"key": "lower_right", "x_expression": "40 mm", "y_expression": "-20 mm", "diameter_expression": "6 mm"},
                {"key": "upper_right", "x_expression": "40 mm", "y_expression": "20 mm", "diameter_expression": "6 mm"},
            ],
            "edge_finish": {"type": "fillet", "size_expression": "3 mm"},
            "builder_factory": self.builder_factory,
            "audit_logger": self.audit,
        }

    def create(self, **changes):
        arguments = self.arguments()
        arguments.update(changes)
        return create_parametric_plate(**arguments)

    def test_creates_whole_plate_in_one_transaction_and_checkpoint(self):
        result = self.create()
        content = result["structuredContent"]

        self.assertFalse(result["isError"])
        self.assertEqual(
            ['PTransaction.Start "Create Parametric Plate"', "PTransaction.Commit"],
            self.app.commands,
        )
        self.assertEqual("MountingPlate", content["component"])
        self.assertEqual("MountingPlate", content["body"])
        self.assertEqual(
            {"width": 100.0, "height": 60.0, "thickness": 5.0},
            content["dimensions_mm"],
        )
        self.assertEqual(4, len(content["holes"]))
        self.assertEqual("fillet", content["edge_finish"]["type"])
        self.assertEqual(3.0, content["edge_finish"]["size_mm"])
        self.assertEqual("MountingPlate_Fillet", content["edge_finish"]["feature"])
        self.assertEqual(16, len(content["parameters_created"]))
        self.assertTrue(content["recomputed"])
        self.assertTrue(content["checkpoint_recorded"])
        checkpoint = get_last_checkpoint()
        self.assertEqual("create_parametric_plate", checkpoint["mutation"])
        self.assertEqual("occurrence-1", checkpoint["occurrence_entity_token"])
        self.assertEqual(16, len(checkpoint["parameter_names"]))

    def test_part_design_uses_root_component_and_records_exact_entities(self):
        self.design.designIntent = "PartDesignIntentType"
        self.root.features = _Features(self.root)

        result = self.create(builder_factory=self.part_builder_factory)
        content = result["structuredContent"]
        checkpoint = get_last_checkpoint()

        self.assertFalse(result["isError"])
        self.assertEqual("root_part", content["container_mode"])
        self.assertEqual("root_part", checkpoint["container_mode"])
        self.assertIsNone(checkpoint["occurrence_entity_token"])
        self.assertEqual("body-1", checkpoint["body_entity_token"])
        self.assertEqual(6, len(checkpoint["feature_entity_tokens"]))
        self.assertEqual(2, len(checkpoint["sketch_entity_tokens"]))
        self.assertEqual(0, self.root.occurrences.count)

    def test_rejects_parameter_collisions_before_transaction(self):
        self.design.userParameters.add("plate_width", "80 mm", "mm", "existing")

        result = self.create()

        self.assertEqual("PLATE_PARAMETER_CONFLICT", result["error"]["code"])
        self.assertEqual(["plate_width"], result["error"]["details"]["names"])
        self.assertEqual("80 mm", self.design.userParameters.itemByName("plate_width").expression)
        self.assertEqual(0, self.root.occurrences.count)
        self.assertEqual([], self.app.commands)

    def test_rejects_invalid_geometry_before_builder_or_transaction(self):
        holes = [{
            "key": "outside",
            "x_expression": "49 mm",
            "y_expression": "0 mm",
            "diameter_expression": "6 mm",
        }]

        result = self.create(holes=holes)

        self.assertEqual("PLATE_HOLE_OUT_OF_BOUNDS", result["error"]["code"])
        self.assertEqual(0, self.root.occurrences.count)
        self.assertEqual([], self.app.commands)
        self.assertIsNone(get_last_checkpoint())

    def test_hole_failure_aborts_and_removes_every_created_entity(self):
        self.root.occurrences = FakeOccurrences(
            component_factory=lambda: _component_factory(fail_hole_at=2)
        )

        result = self.create()

        self.assertEqual("PLATE_HOLE_FAILED", result["error"]["code"])
        self.assertEqual("holes", result["error"]["details"]["stage"])
        self.assertEqual("PTransaction.Abort", self.app.commands[-1])
        self.assertEqual(0, self.root.occurrences.count)
        self.assertEqual(0, self.design.userParameters.count)
        self.assertIsNone(get_last_checkpoint())
        audit_text = self.audit.path.read_text(encoding="utf-8")
        self.assertIn("local_traceback", audit_text)
        self.assertNotIn("local_traceback", repr(result))

    def test_recompute_failure_aborts_and_returns_recompute_error(self):
        self.design.compute_result = False

        result = self.create(holes=[], edge_finish={"type": "none"})

        self.assertEqual("RECOMPUTE_FAILED", result["error"]["code"])
        self.assertEqual(0, self.root.occurrences.count)
        self.assertEqual(0, self.design.userParameters.count)
        self.assertIsNone(get_last_checkpoint())

    def test_no_active_design_is_structured_error(self):
        result = self.create(app=FakeApp(None))

        self.assertEqual("NO_ACTIVE_DESIGN", result["error"]["code"])


if __name__ == "__main__":
    unittest.main()
