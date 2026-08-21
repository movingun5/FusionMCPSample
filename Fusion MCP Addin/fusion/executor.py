"""Risk-gated execution of arbitrary Fusion Python on Fusion's main thread."""

import ast
import builtins
from contextlib import redirect_stdout
import hashlib
from io import StringIO
import json
import math
from pathlib import Path
import tempfile
import time
import traceback

from ..core.audit import AuditLogger
from ..core.errors import MCPError
from ..core.policy import classify_code
from .checkpoints import record_checkpoint
from .snapshot import capture_snapshot, compare_snapshots, safe_value


def _default_audit_logger():
    path = Path(tempfile.gettempdir()) / "fusion-codex-mcp" / "audit.jsonl"
    return AuditLogger(path)


def _error(code, message, retryable=False, details=None):
    return MCPError(code, message, retryable=retryable, details=details).to_result()


def _find_run_function(tree):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run":
            positional = list(node.args.posonlyargs) + list(node.args.args)
            return node, len(positional) == 1 and node.args.vararg is None and not isinstance(node, ast.AsyncFunctionDef)
    return None, False


def _approval_message(decision, intent, document_name):
    return (
        "Codex가 고위험 Fusion Python 실행 승인을 요청합니다.\n\n"
        f"목적: {intent}\n"
        f"문서: {document_name or '(저장되지 않은 문서)'}\n"
        f"감지 위험: {', '.join(decision.reasons)}\n"
        f"코드 SHA-256: {decision.code_hash}\n\n"
        "이 정확한 코드를 실행하시겠습니까?"
    )


def request_ui_approval(ui, decision, intent, document_name=None):
    if ui is None:
        return False
    message = _approval_message(decision, intent, document_name)
    try:
        import adsk.core

        result = ui.messageBox(
            message,
            "Fusion Codex MCP 위험 작업 승인",
            adsk.core.MessageBoxButtonTypes.YesNoButtonType,
            adsk.core.MessageBoxIconTypes.WarningIconType,
        )
        return result == adsk.core.DialogResults.DialogYes
    except (AttributeError, ImportError):
        result = ui.messageBox(message, "Fusion Codex MCP 위험 작업 승인")
        return str(result).endswith("DialogYes")


def _restricted_import(name, globals_=None, locals_=None, fromlist=(), level=0):
    root = name.split(".", 1)[0]
    if root not in {"adsk", "math"}:
        raise ImportError(f"routine execution cannot import {name!r}")
    return builtins.__import__(name, globals_, locals_, fromlist, level)


def _builtins_for(decision):
    if decision.level == "approval_required":
        return builtins.__dict__
    allowed_names = {
        "abs", "all", "any", "bool", "dict", "enumerate", "Exception",
        "float", "int", "isinstance", "len", "list", "map", "max", "min",
        "next", "object", "print", "range", "repr", "reversed", "round",
        "set", "sorted", "str", "sum", "tuple", "TypeError", "ValueError", "zip",
    }
    safe = {name: builtins.__dict__[name] for name in allowed_names}
    safe["__import__"] = _restricted_import
    return safe


def _abort_transaction(app, started):
    if started:
        try:
            app.executeTextCommand("PTransaction.Abort")
        except Exception:
            pass


def _audit(logger, payload):
    try:
        logger.write(payload)
    except Exception:
        return False
    return True


def execute_code(
    app,
    ui,
    intent,
    code,
    expected_changes,
    approval_callback=None,
    audit_logger=None,
):
    """Compile, classify, approve, execute, recompute, and verify one script."""

    started_at = time.time()
    logger = audit_logger or _default_audit_logger()
    request_id = hashlib.sha256(f"{time.time_ns()}:{intent}".encode("utf-8")).hexdigest()[:16]

    if app is None:
        return _error("FUSION_UNAVAILABLE", "Fusion 360 is not available.", retryable=True)
    design = safe_value(app, "activeProduct")
    if design is None or safe_value(design, "rootComponent") is None:
        return _error("NO_ACTIVE_DESIGN", "Open or create a Fusion design first.", retryable=True)
    if not isinstance(intent, str) or not intent.strip():
        return _error("INVALID_REQUEST", "intent must be a non-empty string")
    if not isinstance(code, str) or not code.strip():
        return _error("INVALID_REQUEST", "code must be a non-empty string")
    if not isinstance(expected_changes, dict):
        return _error("INVALID_REQUEST", "expected_changes must be an object")

    try:
        tree = ast.parse(code)
        compiled = compile(tree, "<codex-fusion-python>", "exec")
    except SyntaxError as error:
        return _error(
            "PYTHON_SYNTAX_ERROR",
            error.msg,
            details={"line": error.lineno, "column": error.offset, "text": error.text},
        )

    _, valid_run = _find_run_function(tree)
    if not valid_run:
        return _error(
            "INVALID_REQUEST",
            "code must define a synchronous run(context) function with one argument",
        )

    decision = classify_code(code)
    base_audit = {
        "request_id": request_id,
        "intent": intent,
        "code": code,
        "code_hash": decision.code_hash,
        "policy": decision.to_dict(),
    }
    if decision.level == "blocked":
        _audit(logger, {**base_audit, "result": "blocked"})
        result = _error(
            "POLICY_BLOCKED",
            "The script attempts to bypass or reconfigure MCP security policy.",
            details={"reasons": list(decision.reasons), "code_hash": decision.code_hash},
        )
        result["policy"] = decision.to_dict()
        return result

    if decision.level == "approval_required":
        document_name = safe_value(safe_value(app, "activeDocument"), "name")
        approved = (
            bool(approval_callback(decision, intent))
            if approval_callback is not None
            else request_ui_approval(ui, decision, intent, document_name)
        )
        if not approved:
            _audit(logger, {**base_audit, "result": "approval_denied"})
            result = _error(
                "POLICY_APPROVAL_REQUIRED",
                "Fusion approval was not granted for this exact code hash.",
                details={"reasons": list(decision.reasons), "code_hash": decision.code_hash},
            )
            result["policy"] = decision.to_dict()
            return result

    current_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
    if current_hash != decision.code_hash:
        _audit(logger, {**base_audit, "result": "hash_mismatch"})
        return _error(
            "POLICY_APPROVAL_REQUIRED",
            "Code changed after classification; a new approval is required.",
            details={"code_hash": current_hash},
        )

    before = capture_snapshot(design)
    transaction_started = False
    output = StringIO()
    run_result = None
    try:
        if safe_value(app, "activeDocument") is not None:
            app.executeTextCommand('PTransaction.Start "Codex Fusion Python"')
            transaction_started = True

        try:
            import adsk
        except ImportError:
            adsk = None
        namespace = {
            "__builtins__": _builtins_for(decision),
            "__name__": "__codex_fusion_script__",
            "adsk": adsk,
            "math": math,
        }
        context = {
            "app": app,
            "ui": ui,
            "design": design,
            "rootComponent": design.rootComponent,
        }
        with redirect_stdout(output):
            exec(compiled, namespace, namespace)
            run_result = namespace["run"](context)

        recomputed = design.computeAll()
        if recomputed is False:
            _abort_transaction(app, transaction_started)
            result = _error(
                "RECOMPUTE_FAILED",
                "Fusion could not recompute the design after script execution.",
                retryable=True,
                details={"undo_result": "transaction_aborted"},
            )
            result["policy"] = decision.to_dict()
            _audit(logger, {**base_audit, "result": result, "duration_ms": int((time.time() - started_at) * 1000)})
            return result

        after = capture_snapshot(design)
        verification = compare_snapshots(before, after, expected_changes)
        if transaction_started:
            app.executeTextCommand("PTransaction.Commit")

        record_checkpoint({
            "request_id": request_id,
            "mutation": "execute_fusion_python",
            "code_hash": decision.code_hash,
            "document_id": before["document"]["id"],
            "timeline_marker": before["timeline"]["marker_position"],
        })
        serializable_return = (
            run_result
            if isinstance(run_result, (type(None), bool, int, float, str, list, dict))
            else repr(run_result)
        )
        result = {
            "isError": False,
            "message": "Fusion Python executed and the design was recomputed.",
            "policy": decision.to_dict(),
            "stdout": output.getvalue(),
            "return_value": serializable_return,
            "before": {"counts": before["counts"], "timeline": before["timeline"]},
            "after": {"counts": after["counts"], "timeline": after["timeline"], "bodies": after["bodies"]},
            "verification": verification,
            "content": [{
                "type": "text",
                "text": json.dumps(
                    {"stdout": output.getvalue(), "verification": verification, "counts": after["counts"]},
                    ensure_ascii=False,
                ),
            }],
        }
        result["audit_logged"] = _audit(
            logger,
            {**base_audit, "result": result, "duration_ms": int((time.time() - started_at) * 1000)},
        )
        return result
    except Exception as error:
        _abort_transaction(app, transaction_started)
        local_traceback = traceback.format_exc()
        frames = traceback.extract_tb(error.__traceback__)
        last_frame = frames[-1] if frames else None
        details = {
            "exception_type": type(error).__name__,
            "line": last_frame.lineno if last_frame else None,
            "function": last_frame.name if last_frame else None,
            "source": Path(last_frame.filename).name if last_frame else None,
            "documentation_search_term": type(error).__name__,
            "undo_result": "transaction_aborted" if transaction_started else "not_started",
        }
        result = _error("FUSION_API_ERROR", str(error), retryable=True, details=details)
        result["policy"] = decision.to_dict()
        _audit(
            logger,
            {
                **base_audit,
                "result": result,
                "local_traceback": local_traceback,
                "duration_ms": int((time.time() - started_at) * 1000),
            },
        )
        return result
