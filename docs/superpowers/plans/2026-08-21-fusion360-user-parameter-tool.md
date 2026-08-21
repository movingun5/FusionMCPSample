# Fusion 360 User Parameter Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an idempotent `upsert_user_parameter` MCP tool that creates or safely updates one Fusion 360 user parameter, verifies recomputation, participates in shared undo checkpoints, and is documented in the `$fusion` skill.

**Architecture:** Keep MCP schema/registration in a thin tool module and place all Fusion parameter behavior in a focused adapter invoked on the existing `CustomEvent` main-thread queue. Extract the latest-mutation checkpoint from the arbitrary-Python executor into a shared module so both execution paths use the existing undo tool without changing its external contract.

**Tech Stack:** Fusion 360 Python API, Python standard library, JSON-RPC/MCP over localhost Streamable HTTP, `unittest`, project-local Codex MCP configuration.

**Spec:** `docs/superpowers/specs/2026-08-21-fusion360-user-parameter-tool-design.md`

## Global Constraints

- The server remains bound only to `127.0.0.1:9100` and requires `FUSION_MCP_TOKEN` bearer authentication.
- Fusion API access runs only on the existing Fusion UI `CustomEvent` main-thread queue.
- The tool handles one user parameter per call; no deletion, model-parameter editing, or batch operations.
- Parameter names match `[A-Za-z_][A-Za-z0-9_]*`.
- `expected_old_expression` is an exact optimistic-concurrency guard.
- Existing parameters keep their unit dimension; incompatible unit requests fail without mutation.
- Failures abort the Fusion transaction and restore the prior parameter state.
- Successful results contain MCP `content`, `structuredContent`, and `isError: false`.
- Server version becomes `1.2.0`.
- No new third-party runtime dependency is added.
- After verification, commit messages identify the feature as an update and the branch is pushed to `movingun5/FusionMCPSample`.

## File Structure

- Create `Fusion MCP Addin/fusion/checkpoints.py`: shared in-memory latest-mutation checkpoint state.
- Create `Fusion MCP Addin/fusion/parameters.py`: input validation, Fusion parameter creation/update, transaction recovery, result serialization, and audit logging.
- Create `Fusion MCP Addin/tools/upsert_user_parameter.py`: MCP schema and handler registration.
- Create `tests/test_checkpoints.py`: checkpoint copy/clear behavior.
- Create `tests/test_parameters.py`: adapter creation, update, conflict, validation, recompute, and checkpoint behavior.
- Create `tests/test_parameter_tool.py`: strict MCP input schema and registration-facing contract.
- Modify `Fusion MCP Addin/fusion/executor.py`: use the shared checkpoint store.
- Modify `Fusion MCP Addin/tools/undo_last_execution.py`: read and clear the shared checkpoint store.
- Modify `Fusion MCP Addin/tools/__init__.py`: register the new tool.
- Modify `Fusion MCP Addin/fusion/context.py` and `Fusion MCP Addin/tools/get_fusion_status.py`: report server version `1.2.0`.
- Modify `tests/fakes.py`, `tests/test_executor.py`, `tests/test_undo.py`, and `tests/test_context.py`: parameter and checkpoint test support/regressions.
- Modify `README.md`, `skills/fusion/SKILL.md`, and `docs/live-validation.md`: tool discovery, preferred workflow, and honest live status.

---

### Task 1: Shared Mutation Checkpoint Store

**Files:**
- Create: `Fusion MCP Addin/fusion/checkpoints.py`
- Create: `tests/test_checkpoints.py`
- Modify: `Fusion MCP Addin/fusion/executor.py`
- Modify: `Fusion MCP Addin/tools/undo_last_execution.py`
- Modify: `tests/test_executor.py`
- Modify: `tests/test_undo.py`

**Interfaces:**
- Produces: `record_checkpoint(checkpoint: dict) -> dict`
- Produces: `get_last_checkpoint() -> dict | None`
- Produces: `clear_last_checkpoint() -> None`
- Consumes: checkpoint dictionaries containing `request_id`, `document_id`, `timeline_marker`, and optional mutation metadata.

- [ ] **Step 1: Write the failing checkpoint tests**

```python
import unittest

import tests  # noqa: F401
from fusion_mcp_addin.fusion.checkpoints import (
    clear_last_checkpoint,
    get_last_checkpoint,
    record_checkpoint,
)


class CheckpointTests(unittest.TestCase):
    def tearDown(self):
        clear_last_checkpoint()

    def test_record_returns_and_stores_defensive_copies(self):
        source = {"request_id": "r1", "document_id": "doc-1", "timeline_marker": 2}
        recorded = record_checkpoint(source)
        source["request_id"] = "changed"
        recorded["request_id"] = "also-changed"
        self.assertEqual("r1", get_last_checkpoint()["request_id"])

    def test_clear_removes_checkpoint(self):
        record_checkpoint({"request_id": "r1"})
        clear_last_checkpoint()
        self.assertIsNone(get_last_checkpoint())
```

- [ ] **Step 2: Run the focused test and verify the missing-module failure**

Run: `python -m unittest tests.test_checkpoints -v`

Expected: FAIL because `fusion.checkpoints` does not exist.

- [ ] **Step 3: Implement the minimal shared store**

```python
"""Latest successful Fusion MCP mutation checkpoint."""

_last_checkpoint = None


def record_checkpoint(checkpoint):
    if not isinstance(checkpoint, dict):
        raise TypeError("checkpoint must be a dictionary")
    global _last_checkpoint
    _last_checkpoint = dict(checkpoint)
    return dict(_last_checkpoint)


def get_last_checkpoint():
    return dict(_last_checkpoint) if _last_checkpoint else None


def clear_last_checkpoint():
    global _last_checkpoint
    _last_checkpoint = None
```

- [ ] **Step 4: Route executor and undo through the shared store**

In `fusion/executor.py`, remove `_last_checkpoint` and its accessors, import `record_checkpoint`, and replace the successful assignment with:

```python
record_checkpoint({
    "request_id": request_id,
    "mutation": "execute_fusion_python",
    "code_hash": decision.code_hash,
    "document_id": before["document"]["id"],
    "timeline_marker": before["timeline"]["marker_position"],
})
```

In `tools/undo_last_execution.py`, import `clear_last_checkpoint` and `get_last_checkpoint` from `..fusion.checkpoints`. Change the description from “latest successful execute_fusion_python transaction” to “latest successful Fusion MCP mutation.”

- [ ] **Step 5: Add regression assertions and run focused tests**

Add to `tests/test_executor.py`:

```python
from fusion_mcp_addin.fusion.checkpoints import clear_last_checkpoint, get_last_checkpoint

def tearDown(self):
    clear_last_checkpoint()

def test_success_records_shared_checkpoint(self):
    result = self.execute("def run(context):\n    return 'ok'")
    checkpoint = get_last_checkpoint()
    self.assertFalse(result["isError"])
    self.assertEqual("execute_fusion_python", checkpoint["mutation"])
    self.assertEqual(self.design.parentDocument.id, checkpoint["document_id"])
```

Keep the existing `tests/test_undo.py` assertions unchanged. Only `tools/undo_last_execution.py` changes its checkpoint import source.

Run: `python -m unittest tests.test_checkpoints tests.test_executor tests.test_undo -v`

Expected: all checkpoint, executor, and undo tests PASS.

- [ ] **Step 6: Commit the checkpoint refactor**

```powershell
git add -- "Fusion MCP Addin/fusion/checkpoints.py" "Fusion MCP Addin/fusion/executor.py" "Fusion MCP Addin/tools/undo_last_execution.py" tests/test_checkpoints.py tests/test_executor.py tests/test_undo.py
git commit -m "refactor: MCP 체크포인트 공유"
```

---

### Task 2: Parameter Adapter and Transaction Recovery

**Files:**
- Create: `Fusion MCP Addin/fusion/parameters.py`
- Create: `tests/test_parameters.py`
- Modify: `tests/fakes.py`

**Interfaces:**
- Consumes: `app`, `name`, `expression`, optional `unit`, `comment`, `expected_old_expression`, optional `value_input_factory`, and optional `audit_logger`.
- Produces: `upsert_parameter(app, name, expression, unit=None, comment=None, expected_old_expression=None, value_input_factory=None, audit_logger=None) -> dict` containing a complete MCP success or error result.
- Uses: `record_checkpoint(checkpoint: dict) -> dict` from Task 1.

- [ ] **Step 1: Extend the Fusion fakes for deterministic parameter behavior**

Replace `FakeParameter` and add `FakeUserParameters` in `tests/fakes.py`:

```python
class FakeParameter:
    def __init__(self, name, expression, unit="mm", value=0.0, comment=""):
        self.name = name
        self.expression = expression
        self.unit = unit
        self.value = value
        self.comment = comment
        self.deleted = False

    def deleteMe(self):
        self.deleted = True
        return True


class FakeUserParameters(FakeCollection):
    @property
    def count(self):
        return len([item for item in self._items if not item.deleted])

    def itemByName(self, name):
        return next((item for item in self._items if item.name == name and not item.deleted), None)

    def add(self, name, value_input, unit, comment):
        parameter = FakeParameter(name, value_input, unit, value=0.0, comment=comment)
        self._items.append(parameter)
        return parameter
```

Change `FakeDesign.__init__` to assign `self.userParameters = FakeUserParameters(parameters)`.

- [ ] **Step 2: Write failing creation, update, idempotency, and comment tests**

```python
import unittest

import tests  # noqa: F401
from fusion_mcp_addin.fusion.checkpoints import clear_last_checkpoint, get_last_checkpoint
from fusion_mcp_addin.fusion.parameters import upsert_parameter
from tests.fakes import FakeApp, FakeComponent, FakeDesign, FakeParameter


class ParameterTests(unittest.TestCase):
    def setUp(self):
        clear_last_checkpoint()
        self.design = FakeDesign([FakeComponent("Root", "root")])
        self.app = FakeApp(self.design)
        self.factory = lambda expression: expression

    def tearDown(self):
        clear_last_checkpoint()

    def test_creates_missing_parameter(self):
        result = upsert_parameter(
            self.app, "plate_width", "50 mm", comment="Main width",
            value_input_factory=self.factory,
        )
        self.assertFalse(result["isError"])
        self.assertEqual("created", result["structuredContent"]["action"])
        self.assertEqual("50 mm", self.design.userParameters.itemByName("plate_width").expression)
        self.assertEqual("upsert_user_parameter", get_last_checkpoint()["mutation"])

    def test_updates_existing_parameter_without_duplication(self):
        original = FakeParameter("plate_width", "50 mm", value=5.0, comment="Keep")
        self.design.userParameters._items.append(original)
        result = upsert_parameter(
            self.app, "plate_width", "60 mm",
            expected_old_expression="50 mm", value_input_factory=self.factory,
        )
        self.assertEqual("updated", result["structuredContent"]["action"])
        self.assertEqual(1, self.design.userParameters.count)
        self.assertEqual("Keep", original.comment)

    def test_identical_request_is_unchanged_without_checkpoint(self):
        self.design.userParameters._items.append(FakeParameter("plate_width", "50 mm"))
        result = upsert_parameter(
            self.app, "plate_width", "50 mm", value_input_factory=self.factory,
        )
        self.assertEqual("unchanged", result["structuredContent"]["action"])
        self.assertFalse(result["structuredContent"]["checkpoint_recorded"])
        self.assertIsNone(get_last_checkpoint())

    def test_empty_comment_clears_existing_comment(self):
        parameter = FakeParameter("plate_width", "50 mm", comment="Remove me")
        self.design.userParameters._items.append(parameter)
        upsert_parameter(self.app, "plate_width", "50 mm", comment="", value_input_factory=self.factory)
        self.assertEqual("", parameter.comment)
```

- [ ] **Step 3: Run the focused tests and verify the missing-adapter failure**

Run: `python -m unittest tests.test_parameters -v`

Expected: FAIL because `fusion.parameters` does not exist.

- [ ] **Step 4: Implement validation and result serialization**

Create `fusion/parameters.py` with these exact public helpers:

```python
import hashlib
from pathlib import Path
import re
import tempfile
import time
import traceback

from ..core.audit import AuditLogger
from ..core.errors import MCPError
from ..core.results import tool_success
from .checkpoints import record_checkpoint
from .snapshot import safe_value

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _default_audit_logger():
    path = Path(tempfile.gettempdir()) / "fusion-codex-mcp" / "audit.jsonl"
    return AuditLogger(path)


def _audit(logger, payload):
    try:
        logger.write(payload)
    except Exception:
        return False
    return True


def _error(code, message, retryable=False, details=None):
    return MCPError(code, message, retryable, details).to_result()


def _parameter_data(parameter):
    return {
        "name": safe_value(parameter, "name", ""),
        "expression": safe_value(parameter, "expression", ""),
        "unit": safe_value(parameter, "unit", ""),
        "value": safe_value(parameter, "value"),
        "comment": safe_value(parameter, "comment", ""),
    }


def _validate(name, expression):
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        return _error("INVALID_REQUEST", "name must match [A-Za-z_][A-Za-z0-9_]*")
    if not isinstance(expression, str) or not expression.strip():
        return _error("INVALID_REQUEST", "expression must be a non-empty string")
    return None
```

Implement `upsert_parameter(...)` around this control flow:

```python
validation = _validate(name, expression)
if validation:
    return validation
design = safe_value(app, "activeProduct") if app else None
if design is None or safe_value(design, "rootComponent") is None:
    return _error("NO_ACTIVE_DESIGN", "Open or create a Fusion design first.", True)

parameters = design.userParameters
existing = parameters.itemByName(name)
previous = _parameter_data(existing) if existing else None
if existing and expected_old_expression is not None and previous["expression"] != expected_old_expression:
    return _error("PARAMETER_CONFLICT", "The parameter expression changed before this request.", True,
                  {"expected": expected_old_expression, "actual": previous["expression"]})

target_unit = previous["unit"] if existing else (unit or design.unitsManager.defaultLengthUnits)
if existing and unit:
    try:
        design.unitsManager.evaluateExpression(f"1 {unit}", target_unit)
    except Exception:
        return _error("PARAMETER_UNIT_MISMATCH", "unit is incompatible with the existing parameter")
try:
    design.unitsManager.evaluateExpression(expression, target_unit)
except Exception as error:
    return _error("PARAMETER_EVALUATION_FAILED", str(error))
```

Then implement exact idempotency and transaction behavior. Initialize `logger = audit_logger or _default_audit_logger()` and `started_at = time.time()` before mutation:

```python
next_comment = previous["comment"] if existing and comment is None else (comment or "")
if existing and previous["expression"] == expression and previous["comment"] == next_comment:
    return tool_success({"action": "unchanged", "parameter": previous, "previous": previous,
                         "recomputed": True, "checkpoint_recorded": False})

document = safe_value(app, "activeDocument")
timeline = safe_value(design, "timeline")
request_id = hashlib.sha256(f"{time.time_ns()}:{name}".encode()).hexdigest()[:16]
created = None
transaction_started = False
try:
    if document is not None:
        app.executeTextCommand('PTransaction.Start "Codex User Parameter"')
        transaction_started = True
    if existing:
        existing.expression = expression
        existing.comment = next_comment
        parameter = existing
        action = "updated"
    else:
        factory = value_input_factory
        if factory is None:
            import adsk.core
            factory = adsk.core.ValueInput.createByString
        created = parameters.add(name, factory(expression), target_unit, next_comment)
        parameter = created
        action = "created"
    if design.computeAll() is False:
        raise RuntimeError("RECOMPUTE_FAILED")
    if transaction_started:
        app.executeTextCommand("PTransaction.Commit")
except Exception as error:
    if transaction_started:
        app.executeTextCommand("PTransaction.Abort")
    if existing and previous:
        existing.expression = previous["expression"]
        existing.comment = previous["comment"]
    elif created is not None:
        created.deleteMe()
    code = "RECOMPUTE_FAILED" if str(error) == "RECOMPUTE_FAILED" else "PARAMETER_WRITE_FAILED"
    result = _error(code, str(error), retryable=True,
                    details={"undo_result": "transaction_aborted"})
    _audit(logger, {"request_id": request_id, "operation": "upsert_user_parameter",
                    "parameter": name, "result": result,
                    "local_traceback": traceback.format_exc(),
                    "duration_ms": int((time.time() - started_at) * 1000)})
    return result

record_checkpoint({"request_id": request_id, "mutation": "upsert_user_parameter",
                   "document_id": safe_value(document, "id"),
                   "timeline_marker": safe_value(timeline, "markerPosition")})
payload = {"action": action, "parameter": _parameter_data(parameter),
           "previous": previous, "recomputed": True, "checkpoint_recorded": True}
result = tool_success(payload)
_audit(logger, {"request_id": request_id, "operation": "upsert_user_parameter",
                "parameter": name, "action": action,
                "result": {"isError": False},
                "duration_ms": int((time.time() - started_at) * 1000)})
return result
```

For `unchanged`, write the same audit fields with `action="unchanged"`, return without recording a checkpoint, and never include a traceback in MCP error details.

- [ ] **Step 5: Add conflict, invalid-input, unit, and rollback tests**

```python
def test_conflict_does_not_mutate_parameter(self):
    parameter = FakeParameter("plate_width", "55 mm")
    self.design.userParameters._items.append(parameter)
    result = upsert_parameter(self.app, "plate_width", "60 mm",
                              expected_old_expression="50 mm", value_input_factory=self.factory)
    self.assertEqual("PARAMETER_CONFLICT", result["error"]["code"])
    self.assertEqual("55 mm", parameter.expression)

def test_invalid_name_is_rejected_before_transaction(self):
    result = upsert_parameter(self.app, "plate width", "50 mm", value_input_factory=self.factory)
    self.assertEqual("INVALID_REQUEST", result["error"]["code"])
    self.assertEqual([], self.app.commands)

def test_recompute_failure_aborts_and_restores_previous_value(self):
    parameter = FakeParameter("plate_width", "50 mm", comment="Original")
    self.design.userParameters._items.append(parameter)
    self.design.compute_result = False
    result = upsert_parameter(self.app, "plate_width", "60 mm", comment="Changed",
                              value_input_factory=self.factory)
    self.assertEqual("RECOMPUTE_FAILED", result["error"]["code"])
    self.assertEqual("50 mm", parameter.expression)
    self.assertEqual("Original", parameter.comment)
    self.assertEqual("PTransaction.Abort", self.app.commands[-1])
```

Replace `FakeUnitsManager.evaluateExpression` with the following length-only fake so unknown units fail deterministically:

```python
def evaluateExpression(self, expression, unit):
    parts = expression.split()
    number = float(parts[0])
    source = parts[1] if len(parts) > 1 else unit
    factors_to_cm = {"mm": 0.1, "cm": 1.0, "in": 2.54}
    if source not in factors_to_cm or unit not in factors_to_cm:
        raise ValueError("unsupported or incompatible unit")
    return number * factors_to_cm[source]
```

- [ ] **Step 6: Run focused and full adapter tests**

Run: `python -m unittest tests.test_parameters tests.test_units tests.test_context -v`

Expected: all parameter, unit, and context tests PASS.

- [ ] **Step 7: Commit the adapter**

```powershell
git add -- "Fusion MCP Addin/fusion/parameters.py" tests/fakes.py tests/test_parameters.py
git commit -m "feat: 사용자 파라미터 업데이트"
```

---

### Task 3: MCP Tool Registration and Server Version

**Files:**
- Create: `Fusion MCP Addin/tools/upsert_user_parameter.py`
- Create: `tests/test_parameter_tool.py`
- Modify: `Fusion MCP Addin/tools/__init__.py`
- Modify: `Fusion MCP Addin/fusion/context.py`
- Modify: `Fusion MCP Addin/tools/get_fusion_status.py`
- Modify: `tests/test_context.py`

**Interfaces:**
- Consumes: `upsert_parameter(...) -> dict` from Task 2.
- Produces MCP tool: `upsert_user_parameter(name: str, expression: str, unit?: str, comment?: str, expected_old_expression?: str) -> CallToolResult`.

- [ ] **Step 1: Write the failing strict-schema test**

```python
import unittest

import tests  # noqa: F401
from fusion_mcp_addin.tools.upsert_user_parameter import tool


class ParameterToolTests(unittest.TestCase):
    def test_schema_requires_name_and_expression_and_rejects_extra_fields(self):
        schema = tool.to_dict()["inputSchema"]
        self.assertEqual(["name", "expression"], schema["required"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual("string", schema["properties"]["expected_old_expression"]["type"])
```

- [ ] **Step 2: Run the focused test and verify the missing-tool failure**

Run: `python -m unittest tests.test_parameter_tool -v`

Expected: FAIL because `tools.upsert_user_parameter` does not exist.

- [ ] **Step 3: Implement and register the tool**

```python
"""Explicit MCP tool for one Fusion user parameter."""

import adsk.core

from ..fusion.parameters import upsert_parameter
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ..mcp_primitives.tool import Tool


def handler(name, expression, unit=None, comment=None, expected_old_expression=None):
    return upsert_parameter(
        adsk.core.Application.get(), name, expression,
        unit=unit, comment=comment,
        expected_old_expression=expected_old_expression,
    )


tool = Tool.create_simple(
    name="upsert_user_parameter",
    description=("Create a Fusion user parameter or update the existing parameter with the same "
                 "name. Uses an optional expected_old_expression guard and recomputes the design."),
).add_input_property(
    "name", {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]*$"},
).add_required_input("name").add_input_property(
    "expression", {"type": "string", "minLength": 1},
).add_required_input("expression").add_input_property(
    "unit", {"type": "string", "minLength": 1},
).add_input_property(
    "comment", {"type": "string"},
).add_input_property(
    "expected_old_expression", {"type": "string"},
).strict_schema()

register(Item.create_tool_item(tool=tool, handler=handler))
```

Import the module in `tools/__init__.py` after `get_design_context`.

- [ ] **Step 4: Bump and test server version**

Set both `fusion/context.py:get_status(..., server_version="1.2.0")` and `tools/get_fusion_status.py:SERVER_VERSION = "1.2.0"`.

Add to `tests/test_context.py`:

```python
def test_default_status_reports_parameter_tool_server_version(self):
    status = get_status(self.app)
    self.assertEqual("1.2.0", status["server_version"])
```

- [ ] **Step 5: Run schema, context, and full tests**

Run: `python -m unittest tests.test_parameter_tool tests.test_context -v`

Run: `python -m unittest discover -s tests -v`

Expected: focused tests and the complete suite PASS with no errors.

- [ ] **Step 6: Commit tool registration**

```powershell
git add -- "Fusion MCP Addin/tools/upsert_user_parameter.py" "Fusion MCP Addin/tools/__init__.py" "Fusion MCP Addin/fusion/context.py" "Fusion MCP Addin/tools/get_fusion_status.py" tests/test_parameter_tool.py tests/test_context.py
git commit -m "feat: 파라미터 MCP 도구 업데이트"
```

---

### Task 4: Documentation, Installed Add-in, Live Verification, and GitHub Publish

**Files:**
- Modify: `README.md`
- Modify: `skills/fusion/SKILL.md`
- Modify: `docs/live-validation.md`
- Deploy changed add-in files to: `C:\Users\movingun\AppData\Roaming\Autodesk\Autodesk Fusion 360\API\AddIns\Fusion MCP Addin`
- Deploy skill files to: `C:\Users\movingun\.codex\skills\fusion`

**Interfaces:**
- Documents and validates the `upsert_user_parameter` tool produced by Task 3.
- Preserves the current `fusion360` MCP URL and `FUSION_MCP_TOKEN` environment variable.

- [ ] **Step 1: Update user-facing guidance**

Add this tool bullet to `README.md` after `get_design_context`:

```markdown
- **upsert_user_parameter**: Create or safely update one named user parameter with optional optimistic concurrency checking
```

In `skills/fusion/SKILL.md`, add this rule immediately after reading design context:

```markdown
For user-parameter creation or edits, prefer `upsert_user_parameter` over arbitrary Python. Read the current expression first and pass it as `expected_old_expression` when changing an existing value.
```

Update the quick-reference table so parameter edits use `status → context(parameters) → upsert → context(parameters)`.

- [ ] **Step 2: Run repository verification**

Run: `python -m unittest discover -s tests -v`

Run: `python -m compileall -q "Fusion MCP Addin" scripts tests`

Run: `git diff --check`

Expected: the complete test suite passes, compilation exits 0, and diff check produces no errors.

- [ ] **Step 3: Commit documentation and source skill update**

```powershell
git add -- README.md skills/fusion/SKILL.md docs/live-validation.md
git commit -m "docs: Fusion 파라미터 사용법 업데이트"
```

- [ ] **Step 4: Install the exact changed runtime files**

Request write permission for these two existing destinations, then copy the full add-in source over the installed add-in without deleting unrelated files:

```powershell
$source = "C:\Users\movingun\Documents\Codex\2026-08-18\superpowers-brainstorming-c-users-movingun-codex\outputs\FusionMCPSample\Fusion MCP Addin"
$target = "C:\Users\movingun\AppData\Roaming\Autodesk\Autodesk Fusion 360\API\AddIns\Fusion MCP Addin"
Copy-Item -LiteralPath "$source\fusion\checkpoints.py" -Destination "$target\fusion\checkpoints.py" -Force
Copy-Item -LiteralPath "$source\fusion\parameters.py" -Destination "$target\fusion\parameters.py" -Force
Copy-Item -LiteralPath "$source\fusion\executor.py" -Destination "$target\fusion\executor.py" -Force
Copy-Item -LiteralPath "$source\fusion\context.py" -Destination "$target\fusion\context.py" -Force
Copy-Item -LiteralPath "$source\tools\upsert_user_parameter.py" -Destination "$target\tools\upsert_user_parameter.py" -Force
Copy-Item -LiteralPath "$source\tools\undo_last_execution.py" -Destination "$target\tools\undo_last_execution.py" -Force
Copy-Item -LiteralPath "$source\tools\get_fusion_status.py" -Destination "$target\tools\get_fusion_status.py" -Force
Copy-Item -LiteralPath "$source\tools\__init__.py" -Destination "$target\tools\__init__.py" -Force
```

Copy `skills/fusion/SKILL.md` to `C:\Users\movingun\.codex\skills\fusion\SKILL.md`, then compare SHA-256 hashes for every copied file.

- [ ] **Step 5: Reload Fusion and verify authenticated tool discovery**

In Fusion, stop and run `Fusion MCP Addin` once. Then run:

```powershell
python scripts/check_install.py --addon-path "C:\Users\movingun\AppData\Roaming\Autodesk\Autodesk Fusion 360\API\AddIns\Fusion MCP Addin"
```

Expected: manifest present, token configured, server healthy, MCP authenticated.

Call authenticated `tools/list` and verify `upsert_user_parameter` is present. Call `get_fusion_status` and verify `server_version` is `1.2.0`.

- [ ] **Step 6: Run the disposable-document live parameter flow**

Only after `get_design_context(scope="all")` confirms an unsaved blank test design, call:

```json
{
  "name": "codex_test_width",
  "expression": "50 mm",
  "unit": "mm",
  "comment": "Disposable MCP parameter test"
}
```

Verify `action="created"`, then call `get_design_context(scope="parameters")` and verify `50 mm`. Call again with `expression="60 mm"` and `expected_old_expression="50 mm"`; verify `action="updated"` and context `60 mm`. Call `undo_last_execution`; verify context returns to `50 mm`.

Record Fusion version, server version, test result, and the remaining disposable parameter in `docs/live-validation.md`. Do not claim the live flow passed if any result or context check fails.

- [ ] **Step 7: Commit live evidence and push the feature branch**

```powershell
git add -- docs/live-validation.md
git commit -m "test: 사용자 파라미터 업데이트 검증"
git push origin docs/fusion360-codex-design
```

Verify local `HEAD` equals `origin/docs/fusion360-codex-design`. Report the GitHub branch URL. Do not merge `main`, create a release, or open a pull request without separate authorization.
