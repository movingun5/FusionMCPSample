import hashlib
from pathlib import Path
import tempfile
import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.core.audit import AuditLogger
from fusion_mcp_addin.fusion.checkpoints import clear_last_checkpoint, get_last_checkpoint
from fusion_mcp_addin.fusion.executor import execute_code
from tests.fakes import FakeApp, FakeBody, FakeComponent, FakeDesign, FakeUI


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        body = FakeBody("Plate", "body-1", volume=30.0, maximum=(10.0, 6.0, 0.5))
        self.design = FakeDesign([FakeComponent("Root", "component-1", bodies=[body])])
        self.app = FakeApp(self.design)
        self.ui = FakeUI()
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.audit = AuditLogger(Path(self.temp_directory.name) / "audit.jsonl")

    def execute(self, code, **kwargs):
        return execute_code(
            self.app,
            self.ui,
            kwargs.pop("intent", "test intent"),
            code,
            kwargs.pop("expected_changes", {}),
            audit_logger=self.audit,
            **kwargs,
        )

    def tearDown(self):
        clear_last_checkpoint()

    def test_routine_code_executes_without_prompt_and_captures_stdout(self):
        result = self.execute("def run(context):\n    print(context['rootComponent'].name)")

        self.assertFalse(result["isError"])
        self.assertEqual("routine", result["policy"]["level"])
        self.assertEqual("Root", result["stdout"].strip())
        self.assertEqual([], self.ui.messages)
        self.assertTrue(result["verification"]["expectations_met"])

    def test_success_records_shared_checkpoint(self):
        result = self.execute("def run(context):\n    return 'ok'")

        checkpoint = get_last_checkpoint()

        self.assertFalse(result["isError"])
        self.assertEqual("execute_fusion_python", checkpoint["mutation"])
        self.assertEqual(self.design.parentDocument.id, checkpoint["document_id"])

    def test_code_must_define_run_with_one_argument(self):
        result = self.execute("value = 1")

        self.assertTrue(result["isError"])
        self.assertEqual("INVALID_REQUEST", result["error"]["code"])

    def test_syntax_error_returns_line_and_column(self):
        result = self.execute("def run(:")

        self.assertEqual("PYTHON_SYNTAX_ERROR", result["error"]["code"])
        self.assertEqual(1, result["error"]["details"]["line"])
        self.assertGreater(result["error"]["details"]["column"], 0)

    def test_blocked_code_never_prompts_or_executes(self):
        result = self.execute("def run(context):\n    eval('1 + 1')")

        self.assertEqual("POLICY_BLOCKED", result["error"]["code"])
        self.assertEqual([], self.ui.messages)

    def test_approval_required_code_does_not_run_when_callback_denies(self):
        result = self.execute(
            "import os\ndef run(context):\n    print(os.getcwd())",
            approval_callback=lambda decision, intent: False,
        )

        self.assertEqual("POLICY_APPROVAL_REQUIRED", result["error"]["code"])
        self.assertEqual([], self.app.commands)

    def test_approval_is_bound_to_the_exact_code_hash(self):
        original = "import os\ndef run(context):\n    print(os.getcwd())"
        changed = original + "\nprint('changed')"
        expected_hash = hashlib.sha256(original.encode("utf-8")).hexdigest()

        result = self.execute(
            changed,
            approval_callback=lambda decision, intent: decision.code_hash == expected_hash,
        )

        self.assertEqual("POLICY_APPROVAL_REQUIRED", result["error"]["code"])

    def test_approved_external_code_receives_expanded_importer(self):
        result = self.execute(
            "import os\ndef run(context):\n    print(bool(os.getcwd()))",
            approval_callback=lambda decision, intent: True,
        )

        self.assertFalse(result["isError"])
        self.assertEqual("approval_required", result["policy"]["level"])
        self.assertEqual("True", result["stdout"].strip())

    def test_recompute_failure_returns_structured_error_and_aborts_transaction(self):
        self.design.compute_result = False

        result = self.execute("def run(context):\n    print('changed')")

        self.assertEqual("RECOMPUTE_FAILED", result["error"]["code"])
        self.assertIn("PTransaction.Abort", self.app.commands[-1])

    def test_runtime_error_response_omits_full_traceback_but_audit_keeps_it(self):
        result = self.execute("def run(context):\n    return 1 / 0")

        self.assertEqual("FUSION_API_ERROR", result["error"]["code"])
        self.assertNotIn("traceback", result["error"]["details"])
        self.assertIn("line", result["error"]["details"])
        audit_text = self.audit.path.read_text(encoding="utf-8")
        self.assertIn("local_traceback", audit_text)
        self.assertIn("ZeroDivisionError", audit_text)

    def test_audit_log_records_code_hash_and_not_environment_secrets(self):
        result = self.execute("def run(context):\n    print('ok')")

        text = self.audit.path.read_text(encoding="utf-8")
        self.assertIn(result["policy"]["code_hash"], text)
        self.assertNotIn("FUSION_MCP_TOKEN", text)


if __name__ == "__main__":
    unittest.main()
