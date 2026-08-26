from pathlib import Path
import tempfile
import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.core.audit import AuditLogger
from fusion_mcp_addin.fusion.checkpoints import clear_last_checkpoint, get_last_checkpoint
from fusion_mcp_addin.fusion.parameter_batch import update_parameter_batch
from tests.fakes import (
    FakeApp,
    FakeComponent,
    FakeDesign,
    FakeFeature,
    FakeModelParameter,
    FakeParameter,
)


class ParameterBatchTests(unittest.TestCase):
    def setUp(self):
        clear_last_checkpoint()
        self.feature = FakeFeature("Plate Extrusion", "feature-1")
        self.model_parameter = FakeModelParameter(
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
            model_parameters=[self.model_parameter],
        )
        self.model_parameter.component = self.root
        self.user_parameter = FakeParameter("plate_width", "50 mm", value=5.0)
        self.design = FakeDesign([self.root], parameters=[self.user_parameter])
        self.app = FakeApp(self.design)
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.audit = AuditLogger(Path(self.temp_directory.name) / "audit.jsonl")

    def tearDown(self):
        clear_last_checkpoint()

    @staticmethod
    def user_update(expression="60 mm", expected="50 mm"):
        return {
            "kind": "user",
            "name": "plate_width",
            "expression": expression,
            "expected_old_expression": expected,
        }

    @staticmethod
    def model_update(expression="15 mm", expected="10 mm"):
        return {
            "kind": "model",
            "feature_name": "Plate Extrusion",
            "role": "Distance",
            "expression": expression,
            "expected_old_expression": expected,
        }

    def update(self, updates):
        return update_parameter_batch(self.app, updates, audit_logger=self.audit)

    def test_updates_user_and_model_parameters_in_one_transaction(self):
        result = self.update([self.user_update(), self.model_update()])

        self.assertFalse(result["isError"])
        payload = result["structuredContent"]
        self.assertEqual("updated", payload["action"])
        self.assertEqual("60 mm", self.user_parameter.expression)
        self.assertEqual("15 mm", self.model_parameter.expression)
        self.assertEqual(["user", "model"], [item["kind"] for item in payload["updates"]])
        self.assertEqual(
            ['PTransaction.Start "Codex Parameter Batch"', "PTransaction.Commit"],
            self.app.commands,
        )
        self.assertEqual("update_parameter_batch", get_last_checkpoint()["mutation"])

    def test_rejects_duplicate_targets_before_mutation(self):
        result = self.update([self.user_update(), self.user_update("70 mm")])

        self.assertEqual("DUPLICATE_PARAMETER_TARGET", result["error"]["code"])
        self.assertEqual("50 mm", self.user_parameter.expression)
        self.assertEqual([], self.app.commands)

    def test_rejects_any_stale_value_before_mutating_other_targets(self):
        result = self.update([self.user_update(), self.model_update(expected="9 mm")])

        self.assertEqual("MODEL_PARAMETER_CONFLICT", result["error"]["code"])
        self.assertEqual("50 mm", self.user_parameter.expression)
        self.assertEqual("10 mm", self.model_parameter.expression)
        self.assertEqual([], self.app.commands)

    def test_recompute_failure_restores_every_expression(self):
        self.design.compute_result = False

        result = self.update([self.user_update(), self.model_update()])

        self.assertEqual("RECOMPUTE_FAILED", result["error"]["code"])
        self.assertEqual("50 mm", self.user_parameter.expression)
        self.assertEqual("10 mm", self.model_parameter.expression)
        self.assertEqual("PTransaction.Abort", self.app.commands[-1])
        self.assertIsNone(get_last_checkpoint())

    def test_all_unchanged_targets_skip_transaction_and_checkpoint(self):
        result = self.update(
            [self.user_update("50 mm"), self.model_update("10 mm")]
        )

        self.assertEqual("unchanged", result["structuredContent"]["action"])
        self.assertEqual([], self.app.commands)
        self.assertIsNone(get_last_checkpoint())

    def test_rejects_invalid_shape_missing_targets_and_bad_expressions(self):
        invalid_cases = [
            ([], "INVALID_REQUEST"),
            ([{"kind": "user"}], "INVALID_REQUEST"),
            ([{**self.user_update(), "unknown": True}], "INVALID_REQUEST"),
            ([{**self.user_update(), "name": "missing"}], "PARAMETER_NOT_FOUND"),
            ([self.model_update(expression="not-a-length")], "MODEL_PARAMETER_EXPRESSION_INVALID"),
        ]

        for updates, code in invalid_cases:
            with self.subTest(code=code):
                result = self.update(updates)
                self.assertEqual(code, result["error"]["code"])
                self.assertEqual([], self.app.commands)


if __name__ == "__main__":
    unittest.main()
