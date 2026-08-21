import hashlib
import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from core.policy import classify_code


class PolicyTests(unittest.TestCase):
    def test_routine_fusion_geometry_is_automatic(self):
        code = "rootComponent.features.extrudeFeatures.add(ext_input)"

        decision = classify_code(code)

        self.assertEqual("routine", decision.level)
        self.assertEqual((), decision.reasons)
        self.assertEqual(hashlib.sha256(code.encode("utf-8")).hexdigest(), decision.code_hash)

    def test_filesystem_and_delete_require_approval(self):
        decision = classify_code("import os\nos.remove(path)\nbody.deleteMe()")

        self.assertEqual("approval_required", decision.level)
        self.assertIn("filesystem", decision.reasons)
        self.assertIn("delete", decision.reasons)

    def test_cam_and_simulation_require_approval(self):
        decision = classify_code("cam_product.generateAllToolpaths(True)\nsimulation.start()")

        self.assertEqual("approval_required", decision.level)
        self.assertIn("cam", decision.reasons)
        self.assertIn("simulation", decision.reasons)

    def test_dynamic_execution_is_blocked(self):
        decision = classify_code("globals()['__builtins__']['eval'](payload)")

        self.assertEqual("blocked", decision.level)
        self.assertIn("policy_bypass", decision.reasons)

    def test_server_reconfiguration_is_blocked(self):
        decision = classify_code("HOST = '0.0.0.0'\nFUSION_MCP_TOKEN = 'disabled'")

        self.assertEqual("blocked", decision.level)
        self.assertIn("security_reconfiguration", decision.reasons)

    def test_invalid_python_raises_syntax_error(self):
        with self.assertRaises(SyntaxError):
            classify_code("def run(:")


if __name__ == "__main__":
    unittest.main()
