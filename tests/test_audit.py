import json
from pathlib import Path
import tempfile
import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from core.audit import AuditLogger, redact


class AuditTests(unittest.TestCase):
    def test_redact_removes_nested_secrets_without_mutating_input(self):
        event = {
            "authorization": "Bearer secret",
            "nested": {"token": "secret", "safe": "value"},
            "items": [{"password": "secret"}],
        }

        cleaned = redact(event)

        self.assertEqual("[REDACTED]", cleaned["authorization"])
        self.assertEqual("[REDACTED]", cleaned["nested"]["token"])
        self.assertEqual("value", cleaned["nested"]["safe"])
        self.assertEqual("[REDACTED]", cleaned["items"][0]["password"])
        self.assertEqual("Bearer secret", event["authorization"])

    def test_logger_appends_one_redacted_json_object_per_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "logs" / "audit.jsonl"
            logger = AuditLogger(path)

            logger.write({"request_id": "one", "secret": "do-not-log"})
            logger.write({"request_id": "two", "result": "ok"})

            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(2, len(lines))
            self.assertEqual("[REDACTED]", json.loads(lines[0])["secret"])
            self.assertEqual("two", json.loads(lines[1])["request_id"])
            self.assertNotIn("do-not-log", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
