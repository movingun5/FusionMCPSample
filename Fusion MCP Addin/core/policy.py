"""Conservative static risk classification for submitted Fusion Python."""

import ast
import hashlib


_EXTERNAL_MODULES = {
    "os": "filesystem",
    "pathlib": "filesystem",
    "shutil": "filesystem",
    "tempfile": "filesystem",
    "glob": "filesystem",
    "subprocess": "process",
    "multiprocessing": "process",
    "socket": "network",
    "http": "network",
    "urllib": "network",
    "ftplib": "network",
    "requests": "network",
}
_DELETE_NAMES = {
    "delete",
    "deleteme",
    "deleteallaftermarker",
    "remove",
    "rmdir",
    "unlink",
    "clear",
}
_DYNAMIC_NAMES = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "globals",
    "locals",
}
_REFLECTION_NAMES = {"getattr", "setattr", "delattr", "vars"}
_SECURITY_NAMES = {"fusion_mcp_token", "host", "port", "bearer_token"}


class RiskDecision:
    """Immutable-enough value object describing policy classification."""

    def __init__(self, level, reasons, code_hash):
        self.level = level
        self.reasons = tuple(sorted(set(reasons)))
        self.code_hash = code_hash

    def to_dict(self):
        return {
            "level": self.level,
            "reasons": list(self.reasons),
            "code_hash": self.code_hash,
            "sandbox_guarantee": False,
        }


def _root_module(name):
    return (name or "").split(".", 1)[0].lower()


def _node_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def classify_code(code):
    """Classify exact source as routine, approval-required, or blocked."""

    if not isinstance(code, str):
        raise TypeError("code must be a string")

    code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
    tree = ast.parse(code)
    approval_reasons = set()
    blocked_reasons = set()
    lowered_source = code.lower()

    if "0.0.0.0" in lowered_source or "fusion_mcp_token" in lowered_source:
        blocked_reasons.add("security_reconfiguration")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                reason = _EXTERNAL_MODULES.get(_root_module(alias.name))
                if reason:
                    approval_reasons.add(reason)
                if _root_module(alias.name) == "importlib":
                    approval_reasons.add("dynamic_import")

        elif isinstance(node, ast.ImportFrom):
            reason = _EXTERNAL_MODULES.get(_root_module(node.module))
            if reason:
                approval_reasons.add(reason)
            if _root_module(node.module) == "importlib":
                approval_reasons.add("dynamic_import")

        elif isinstance(node, (ast.Call, ast.Name, ast.Attribute)):
            name = _node_name(node).lower()
            if name in _DYNAMIC_NAMES:
                blocked_reasons.add("policy_bypass")
            if name in _REFLECTION_NAMES or name.startswith("__"):
                approval_reasons.add("reflection")
            if name in _DELETE_NAMES or name.startswith("delete"):
                approval_reasons.add("delete")
            if "toolpath" in name or name.startswith("cam") or "manufactur" in name:
                approval_reasons.add("cam")
            if "simulat" in name:
                approval_reasons.add("simulation")

        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id.lower() in _SECURITY_NAMES:
                    blocked_reasons.add("security_reconfiguration")

        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.lower()
            if value in _DYNAMIC_NAMES and isinstance(getattr(node, "parent", None), ast.Subscript):
                blocked_reasons.add("policy_bypass")

    # Subscripted builtins such as globals()['__builtins__']['eval'] are visible
    # as source text even though Python's AST does not retain parent pointers.
    if "__builtins__" in lowered_source and any(name in lowered_source for name in _DYNAMIC_NAMES):
        blocked_reasons.add("policy_bypass")

    if blocked_reasons:
        return RiskDecision("blocked", blocked_reasons | approval_reasons, code_hash)
    if approval_reasons:
        return RiskDecision("approval_required", approval_reasons, code_hash)
    return RiskDecision("routine", (), code_hash)
