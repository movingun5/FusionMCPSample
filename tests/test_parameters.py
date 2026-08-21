from pathlib import Path
import tempfile
import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.core.audit import AuditLogger
from fusion_mcp_addin.fusion.checkpoints import (
    clear_last_checkpoint,
    get_last_checkpoint,
)
from fusion_mcp_addin.fusion.parameters import upsert_parameter
from tests.fakes import FakeApp, FakeComponent, FakeDesign, FakeParameter


class ParameterTests(unittest.TestCase):
    def setUp(self):
        clear_last_checkpoint()
        self.design = FakeDesign([FakeComponent("Root", "root")])
        self.app = FakeApp(self.design)
        self.factory = lambda expression: expression
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.audit = AuditLogger(Path(self.temp_directory.name) / "audit.jsonl")

    def tearDown(self):
        clear_last_checkpoint()

    def upsert(self, name, expression, **kwargs):
        return upsert_parameter(
            self.app,
            name,
            expression,
            value_input_factory=self.factory,
            audit_logger=self.audit,
            **kwargs,
        )

    def test_creates_missing_parameter(self):
        result = self.upsert(
            "plate_width",
            "50 mm",
            comment="Main width",
        )

        parameter = self.design.userParameters.itemByName("plate_width")
        self.assertFalse(result["isError"])
        self.assertEqual("created", result["structuredContent"]["action"])
        self.assertEqual("50 mm", parameter.expression)
        self.assertEqual("mm", parameter.unit)
        self.assertEqual("Main width", parameter.comment)
        self.assertEqual("upsert_user_parameter", get_last_checkpoint()["mutation"])

    def test_updates_existing_parameter_without_duplication_and_preserves_comment(self):
        parameter = FakeParameter(
            "plate_width",
            "50 mm",
            value=5.0,
            comment="Keep",
        )
        self.design.userParameters._items.append(parameter)

        result = self.upsert(
            "plate_width",
            "60 mm",
            expected_old_expression="50 mm",
        )

        self.assertEqual("updated", result["structuredContent"]["action"])
        self.assertEqual(1, self.design.userParameters.count)
        self.assertEqual("60 mm", parameter.expression)
        self.assertEqual("Keep", parameter.comment)
        self.assertEqual("50 mm", result["structuredContent"]["previous"]["expression"])

    def test_identical_request_is_unchanged_without_checkpoint(self):
        self.design.userParameters._items.append(
            FakeParameter("plate_width", "50 mm")
        )

        result = self.upsert("plate_width", "50 mm")

        self.assertEqual("unchanged", result["structuredContent"]["action"])
        self.assertFalse(result["structuredContent"]["checkpoint_recorded"])
        self.assertIsNone(get_last_checkpoint())
        self.assertEqual([], self.app.commands)

    def test_empty_comment_clears_existing_comment(self):
        parameter = FakeParameter(
            "plate_width",
            "50 mm",
            comment="Remove me",
        )
        self.design.userParameters._items.append(parameter)

        result = self.upsert("plate_width", "50 mm", comment="")

        self.assertEqual("updated", result["structuredContent"]["action"])
        self.assertEqual("", parameter.comment)

    def test_conflict_does_not_mutate_parameter(self):
        parameter = FakeParameter("plate_width", "55 mm")
        self.design.userParameters._items.append(parameter)

        result = self.upsert(
            "plate_width",
            "60 mm",
            expected_old_expression="50 mm",
        )

        self.assertEqual("PARAMETER_CONFLICT", result["error"]["code"])
        self.assertEqual("55 mm", parameter.expression)
        self.assertEqual([], self.app.commands)

    def test_invalid_name_is_rejected_before_transaction(self):
        result = self.upsert("plate width", "50 mm")

        self.assertEqual("INVALID_REQUEST", result["error"]["code"])
        self.assertEqual([], self.app.commands)

    def test_invalid_expression_is_rejected_before_transaction(self):
        result = self.upsert("plate_width", "not-a-length")

        self.assertEqual("PARAMETER_EVALUATION_FAILED", result["error"]["code"])
        self.assertEqual([], self.app.commands)

    def test_incompatible_update_unit_is_rejected_without_mutation(self):
        parameter = FakeParameter("plate_width", "50 mm")
        self.design.userParameters._items.append(parameter)

        result = self.upsert("plate_width", "60 mm", unit="deg")

        self.assertEqual("PARAMETER_UNIT_MISMATCH", result["error"]["code"])
        self.assertEqual("50 mm", parameter.expression)

    def test_recompute_failure_aborts_and_restores_previous_value(self):
        parameter = FakeParameter(
            "plate_width",
            "50 mm",
            comment="Original",
        )
        self.design.userParameters._items.append(parameter)
        self.design.compute_result = False

        result = self.upsert(
            "plate_width",
            "60 mm",
            comment="Changed",
        )

        self.assertEqual("RECOMPUTE_FAILED", result["error"]["code"])
        self.assertEqual("50 mm", parameter.expression)
        self.assertEqual("Original", parameter.comment)
        self.assertEqual("PTransaction.Abort", self.app.commands[-1])
        self.assertNotIn("traceback", result["error"]["details"])
        self.assertIn("local_traceback", self.audit.path.read_text(encoding="utf-8"))

    def test_create_failure_deletes_partially_created_parameter(self):
        self.design.compute_result = False

        result = self.upsert("plate_width", "50 mm")

        self.assertEqual("RECOMPUTE_FAILED", result["error"]["code"])
        self.assertIsNone(self.design.userParameters.itemByName("plate_width"))

    def test_no_active_design_is_structured_error(self):
        result = upsert_parameter(
            FakeApp(None),
            "plate_width",
            "50 mm",
            value_input_factory=self.factory,
            audit_logger=self.audit,
        )

        self.assertEqual("NO_ACTIVE_DESIGN", result["error"]["code"])


if __name__ == "__main__":
    unittest.main()
