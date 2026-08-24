from pathlib import Path
import tempfile
import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.core.audit import AuditLogger
from fusion_mcp_addin.fusion.checkpoints import clear_last_checkpoint, get_last_checkpoint
from fusion_mcp_addin.fusion.model_parameters import update_model_parameter
from tests.fakes import (
    FakeApp,
    FakeCollection,
    FakeComponent,
    FakeDesign,
    FakeFeature,
    FakeModelParameter,
)


class ModelParameterTests(unittest.TestCase):
    def setUp(self):
        clear_last_checkpoint()
        self.feature = FakeFeature("Plate Extrusion", "feature-1")
        self.parameter = FakeModelParameter(
            "d12",
            "10 mm",
            "Distance",
            self.feature,
            value=1.0,
        )
        self.root = FakeComponent(
            "Root",
            "root",
            features=[self.feature],
            model_parameters=[self.parameter],
        )
        self.parameter.component = self.root
        self.design = FakeDesign([self.root])
        self.app = FakeApp(self.design)
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.audit = AuditLogger(Path(self.temp_directory.name) / "audit.jsonl")

    def tearDown(self):
        clear_last_checkpoint()

    def update(self, **kwargs):
        arguments = {
            "app": self.app,
            "feature_name": "Plate Extrusion",
            "role": "Distance",
            "expression": "15 mm",
            "expected_old_expression": "10 mm",
            "audit_logger": self.audit,
        }
        arguments.update(kwargs)
        return update_model_parameter(**arguments)

    def test_updates_exact_feature_role_and_records_checkpoint(self):
        result = self.update()

        self.assertFalse(result["isError"])
        self.assertEqual("updated", result["structuredContent"]["action"])
        self.assertEqual("15 mm", self.parameter.expression)
        self.assertEqual("10 mm", result["structuredContent"]["previous"]["expression"])
        self.assertEqual("update_model_parameter", get_last_checkpoint()["mutation"])
        self.assertEqual(
            [
                'PTransaction.Start "Codex Model Parameter"',
                "PTransaction.Commit",
            ],
            self.app.commands,
        )

    def test_role_matching_is_case_insensitive_but_result_preserves_fusion_role(self):
        result = self.update(role="distance")

        self.assertFalse(result["isError"])
        self.assertEqual("Distance", result["structuredContent"]["parameter"]["role"])

    def test_missing_feature_role_is_rejected_before_transaction(self):
        result = self.update(role="Angle")

        self.assertEqual("MODEL_PARAMETER_NOT_FOUND", result["error"]["code"])
        self.assertEqual("10 mm", self.parameter.expression)
        self.assertEqual([], self.app.commands)

    def test_ambiguous_feature_role_is_rejected_before_transaction(self):
        duplicate = FakeModelParameter(
            "d13",
            "8 mm",
            "Distance",
            self.feature,
            component=self.root,
        )
        self.root.modelParameters = FakeCollection([self.parameter, duplicate])

        result = self.update()

        self.assertEqual("MODEL_PARAMETER_AMBIGUOUS", result["error"]["code"])
        self.assertEqual(["d12", "d13"], result["error"]["details"]["parameter_names"])
        self.assertEqual([], self.app.commands)

    def test_conflict_does_not_overwrite_a_newer_expression(self):
        self.parameter.expression = "12 mm"

        result = self.update()

        self.assertEqual("MODEL_PARAMETER_CONFLICT", result["error"]["code"])
        self.assertEqual("12 mm", self.parameter.expression)
        self.assertEqual([], self.app.commands)

    def test_identical_expression_is_unchanged_without_checkpoint(self):
        result = self.update(expression="10 mm")

        self.assertEqual("unchanged", result["structuredContent"]["action"])
        self.assertFalse(result["structuredContent"]["checkpoint_recorded"])
        self.assertIsNone(get_last_checkpoint())
        self.assertEqual([], self.app.commands)

    def test_invalid_expression_is_rejected_before_transaction(self):
        result = self.update(expression="not-a-length")

        self.assertEqual("MODEL_PARAMETER_EXPRESSION_INVALID", result["error"]["code"])
        self.assertEqual("10 mm", self.parameter.expression)
        self.assertEqual([], self.app.commands)

    def test_recompute_failure_aborts_and_restores_previous_expression(self):
        self.design.compute_result = False

        result = self.update()

        self.assertEqual("RECOMPUTE_FAILED", result["error"]["code"])
        self.assertEqual("10 mm", self.parameter.expression)
        self.assertEqual("PTransaction.Abort", self.app.commands[-1])
        self.assertIn("local_traceback", self.audit.path.read_text(encoding="utf-8"))

    def test_no_active_design_is_structured_error(self):
        result = update_model_parameter(
            FakeApp(None),
            "Plate Extrusion",
            "Distance",
            "15 mm",
            "10 mm",
            audit_logger=self.audit,
        )

        self.assertEqual("NO_ACTIVE_DESIGN", result["error"]["code"])


if __name__ == "__main__":
    unittest.main()
