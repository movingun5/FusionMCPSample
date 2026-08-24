from pathlib import Path
import tempfile
import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.core.audit import AuditLogger
from fusion_mcp_addin.fusion.checkpoints import clear_last_checkpoint, get_last_checkpoint
from fusion_mcp_addin.fusion.parametric_profiles import (
    create_parametric_profile_extrusion,
)
from fusion_mcp_addin.fusion.profile_builder import FusionProfileBuilder
from tests.fakes import FakeApp, FakeComponent, FakeDesign, FakeOccurrences, FakePoint
from tests.test_profile_builder import _Features, _component_factory


class ParametricProfileTests(unittest.TestCase):
    def setUp(self):
        clear_last_checkpoint()
        self.root = FakeComponent("Root", "root")
        self.root.occurrences = FakeOccurrences(component_factory=_component_factory)
        self.design = FakeDesign([self.root])
        self.app = FakeApp(self.design)
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.audit = AuditLogger(Path(self.temp_directory.name) / "audit.jsonl")

    def tearDown(self):
        clear_last_checkpoint()

    @staticmethod
    def vertices():
        return [
            {"key": "p1", "x_expression": "-50 mm", "y_expression": "-30 mm"},
            {"key": "p2", "x_expression": "50 mm", "y_expression": "-30 mm"},
            {"key": "p3", "x_expression": "50 mm", "y_expression": "30 mm"},
            {"key": "p4", "x_expression": "10 mm", "y_expression": "30 mm"},
            {"key": "p5", "x_expression": "10 mm", "y_expression": "0 mm"},
            {"key": "p6", "x_expression": "-50 mm", "y_expression": "0 mm"},
        ]

    @staticmethod
    def builder_factory(design, root):
        return FusionProfileBuilder(
            design,
            root,
            point_factory=FakePoint,
            matrix_factory=lambda: object(),
            value_input_factory=lambda expression: expression,
            dimension_orientations={"horizontal": "horizontal", "vertical": "vertical"},
            new_body_operation="new-body",
            part_design_intent="PartDesignIntentType",
        )

    def arguments(self):
        return {
            "app": self.app,
            "name": "LProfile",
            "parameter_prefix": "l_profile",
            "vertices": self.vertices(),
            "depth_expression": "8 mm",
            "builder_factory": self.builder_factory,
            "audit_logger": self.audit,
        }

    def create(self, **changes):
        arguments = self.arguments()
        arguments.update(changes)
        return create_parametric_profile_extrusion(**arguments)

    def test_creates_profile_in_one_transaction_and_records_exact_checkpoint(self):
        result = self.create()
        content = result["structuredContent"]
        checkpoint = get_last_checkpoint()

        self.assertFalse(result["isError"])
        self.assertEqual(
            [
                'PTransaction.Start "Create Parametric Profile Extrusion"',
                "PTransaction.Commit",
            ],
            self.app.commands,
        )
        self.assertEqual("child_component", content["container_mode"])
        self.assertEqual("LProfile", content["body"])
        self.assertEqual(8.0, content["depth_mm"])
        self.assertEqual([-50.0, -30.0], content["vertices_mm"][0]["point_mm"])
        self.assertEqual(13, len(content["parameters_created"]))
        self.assertEqual("create_parametric_profile_extrusion", checkpoint["mutation"])
        self.assertEqual("occurrence-1", checkpoint["occurrence_entity_token"])
        self.assertEqual(["profile-extrude-1"], checkpoint["feature_entity_tokens"])
        self.assertEqual(["sketch-1"], checkpoint["sketch_entity_tokens"])

    def test_part_design_uses_root_and_records_single_feature_and_sketch(self):
        self.design.designIntent = "PartDesignIntentType"
        self.root.features = _Features(self.root)

        result = self.create()
        checkpoint = get_last_checkpoint()

        self.assertFalse(result["isError"])
        self.assertEqual("root_part", result["structuredContent"]["container_mode"])
        self.assertIsNone(checkpoint["occurrence_entity_token"])
        self.assertEqual("profile-body-1", checkpoint["body_entity_token"])
        self.assertEqual(1, len(checkpoint["feature_entity_tokens"]))
        self.assertEqual(1, len(checkpoint["sketch_entity_tokens"]))

    def test_rejects_generated_parameter_collision_before_transaction(self):
        self.design.userParameters.add("l_profile_p2_x", "20 mm", "mm", "existing")

        result = self.create()

        self.assertEqual("PROFILE_PARAMETER_CONFLICT", result["error"]["code"])
        self.assertEqual(["l_profile_p2_x"], result["error"]["details"]["names"])
        self.assertEqual([], self.app.commands)
        self.assertEqual(0, self.root.occurrences.count)

    def test_rejects_bow_tie_before_builder_or_transaction(self):
        bow_tie = [
            {"key": "a", "x_expression": "0 mm", "y_expression": "0 mm"},
            {"key": "b", "x_expression": "40 mm", "y_expression": "40 mm"},
            {"key": "c", "x_expression": "0 mm", "y_expression": "40 mm"},
            {"key": "d", "x_expression": "40 mm", "y_expression": "0 mm"},
        ]

        result = self.create(vertices=bow_tie)

        self.assertEqual("PROFILE_SELF_INTERSECTION", result["error"]["code"])
        self.assertEqual([], self.app.commands)
        self.assertEqual(0, self.design.userParameters.count)
        self.assertIsNone(get_last_checkpoint())

    def test_recompute_failure_aborts_and_restores_every_count(self):
        self.design.compute_result = False

        result = self.create()

        self.assertEqual("RECOMPUTE_FAILED", result["error"]["code"])
        self.assertEqual("PTransaction.Abort", self.app.commands[-1])
        self.assertEqual(0, self.root.occurrences.count)
        self.assertEqual(0, self.design.userParameters.count)
        self.assertIsNone(get_last_checkpoint())

    def test_no_active_design_is_structured_error(self):
        result = self.create(app=FakeApp(None))

        self.assertEqual("NO_ACTIVE_DESIGN", result["error"]["code"])


if __name__ == "__main__":
    unittest.main()
