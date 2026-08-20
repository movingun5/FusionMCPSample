"""Secret-redacted local JSONL audit logging."""

from datetime import datetime, timezone
import json
from pathlib import Path


_SECRET_FRAGMENTS = ("authorization", "token", "secret", "password")


def _is_secret_key(key):
    lowered = str(key).lower()
    return any(fragment in lowered for fragment in _SECRET_FRAGMENTS)


def redact(value):
    """Return a recursively redacted copy of JSON-like data."""

    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _is_secret_key(key) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    return value


class AuditLogger:
    """Append one redacted event per line to a local UTF-8 JSONL file."""

    def __init__(self, path):
        self.path = Path(path)

    def write(self, event):
        payload = redact(dict(event))
        payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            stream.write("\n")
