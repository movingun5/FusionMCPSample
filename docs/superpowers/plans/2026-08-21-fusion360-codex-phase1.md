# Fusion 360 Codex Local MCP Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a localhost-only, bearer-authenticated Fusion 360 MCP add-in that lets ChatGPT desktop Codex execute risk-classified Fusion Python, inspect and verify the active design, capture views, undo the latest execution, and export STEP/STL.

**Architecture:** Extend Autodesk's dependency-free in-process HTTP MCP sample. Keep security policy, structured errors, logging, and unit helpers as pure Python modules; keep all `adsk` access behind Fusion adapters invoked on the existing `CustomEvent` main-thread queue. Preserve the original tools as compatibility aliases while exposing the approved Codex-oriented tool names.

**Tech Stack:** Fusion 360 Python API, Python standard library, JSON-RPC/MCP over localhost HTTP, `unittest`, project-local Codex TOML.

**Spec:** `docs/superpowers/specs/2026-08-21-fusion360-codex-local-mcp-design.md`

## Global Constraints

- Bind only to `127.0.0.1:9100`; do not expose the MCP server publicly.
- Read the bearer token from `FUSION_MCP_TOKEN`; never commit or log its value.
- Keep production code dependency-free because it runs inside Fusion's Python runtime.
- Execute every `adsk` operation through the existing `TaskManager`/`CustomEvent` main-thread path.
- Treat arbitrary Python analysis as a risk classifier, not a complete sandbox.
- Require Fusion UI approval for deletion, overwrite, CAM, simulation, filesystem, process, network, dynamic execution, or reflective bypass patterns.
- Block policy bypass and server/auth reconfiguration attempts.
- Preserve Autodesk's MIT license and do not copy code or wording from proprietary AuraFriday sources.
- Do not claim live Fusion validation until the live acceptance script has actually passed.

---

### Task 1: Pure Python contracts, policy, logging, and tests

**Files:**
- Create: `Fusion MCP Addin/core/__init__.py`
- Create: `Fusion MCP Addin/core/errors.py`
- Create: `Fusion MCP Addin/core/policy.py`
- Create: `Fusion MCP Addin/core/audit.py`
- Create: `tests/__init__.py`
- Create: `tests/test_policy.py`
- Create: `tests/test_audit.py`

**Interfaces:**
- Produces: `MCPError(code, message, retryable=False, details=None).to_result()`.
- Produces: `RiskDecision(level, reasons, code_hash)` and `classify_code(code: str) -> RiskDecision`.
- Produces: `AuditLogger(path).write(event: dict) -> None` with recursive redaction.

- [ ] **Step 1: Write failing policy and audit tests**

```python
def test_routine_fusion_geometry_is_automatic(self):
    decision = classify_code("rootComponent.features.extrudeFeatures.add(ext_input)")
    self.assertEqual("routine", decision.level)

def test_filesystem_and_delete_require_approval(self):
    decision = classify_code("import os\nos.remove(path)\nbody.deleteMe()")
    self.assertEqual("approval_required", decision.level)
    self.assertIn("filesystem", decision.reasons)
    self.assertIn("delete", decision.reasons)

def test_policy_bypass_is_blocked(self):
    decision = classify_code("globals()['__builtins__']['eval'](payload)")
    self.assertEqual("blocked", decision.level)

def test_audit_redacts_nested_secrets(self):
    cleaned = redact({"authorization": "Bearer secret", "nested": {"token": "secret"}})
    self.assertEqual("[REDACTED]", cleaned["authorization"])
    self.assertEqual("[REDACTED]", cleaned["nested"]["token"])
```

- [ ] **Step 2: Run tests and verify missing modules fail**

Run: `python -m unittest tests.test_policy tests.test_audit -v`

Expected: import failure for `core.policy` or `core.audit`.

- [ ] **Step 3: Implement immutable decisions, AST classification, and JSONL audit**

```python
class RiskDecision:
    def __init__(self, level, reasons, code_hash):
        self.level = level
        self.reasons = tuple(sorted(set(reasons)))
        self.code_hash = code_hash

def classify_code(code):
    code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
    tree = ast.parse(code)
    # Walk Import, ImportFrom, Call, Attribute, Subscript, and Name nodes.
    # Return blocked for bypass/server/auth patterns, approval_required for
    # destructive or external effects, and routine otherwise.
    return RiskDecision(level, reasons, code_hash)
```

`AuditLogger.write` creates only its configured parent directory, redacts keys containing `authorization`, `token`, `secret`, or `password`, and appends one UTF-8 JSON object per line.

- [ ] **Step 4: Run focused tests**

Run: `python -m unittest tests.test_policy tests.test_audit -v`

Expected: all tests pass.

- [ ] **Step 5: Commit the task**

```powershell
git add -- 'Fusion MCP Addin/core' tests/test_policy.py tests/test_audit.py tests/__init__.py
git commit -m "feat: add execution policy and audit core"
```

### Task 2: Bearer authentication and strict localhost startup

**Files:**
- Create: `Fusion MCP Addin/server/auth.py`
- Modify: `Fusion MCP Addin/server/mcp_server.py`
- Modify: `Fusion MCP Addin/Fusion MCP Addin.py`
- Create: `tests/test_auth.py`
- Create: `tests/test_http_auth.py`

**Interfaces:**
- Produces: `verify_authorization(header: str | None, expected_token: str) -> bool` using `hmac.compare_digest`.
- Changes: `start_mcp_server(..., bearer_token=None)` passes a token to the request handler.
- Changes: `/health` remains token-free but returns no design data; MCP POST and `/tools` require authentication.

- [ ] **Step 1: Write failing auth tests**

```python
def test_requires_exact_bearer_scheme(self):
    self.assertTrue(verify_authorization("Bearer abc", "abc"))
    self.assertFalse(verify_authorization("bearer abc", "abc"))
    self.assertFalse(verify_authorization(None, "abc"))

def test_no_configured_token_rejects_requests(self):
    self.assertFalse(verify_authorization("Bearer anything", ""))
```

The HTTP test starts `ThreadedHTTPServer` on port `0`, asserts `/health` is `200`, unauthenticated POST is `401`, and authenticated `initialize` is `200`.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m unittest tests.test_auth tests.test_http_auth -v`

Expected: missing `server.auth` or unsupported handler token.

- [ ] **Step 3: Add authentication at the HTTP boundary**

```python
def verify_authorization(header, expected_token):
    if not expected_token or not header or not header.startswith("Bearer "):
        return False
    return hmac.compare_digest(header[7:], expected_token)
```

`MCPHandler.do_POST` must return JSON-RPC-compatible `AUTH_FAILED` data with HTTP 401 before reading or dispatching the request. `run()` must read `FUSION_MCP_TOKEN`, refuse startup when empty, and call `start_mcp_server(host="127.0.0.1", port=9100, bearer_token=token, ...)`.

- [ ] **Step 4: Run auth tests**

Run: `python -m unittest tests.test_auth tests.test_http_auth -v`

Expected: all tests pass and server threads stop in test cleanup.

- [ ] **Step 5: Commit the task**

```powershell
git add -- 'Fusion MCP Addin/server/auth.py' 'Fusion MCP Addin/server/mcp_server.py' 'Fusion MCP Addin/Fusion MCP Addin.py' tests/test_auth.py tests/test_http_auth.py
git commit -m "feat: protect local MCP with bearer auth"
```

### Task 3: Fusion status, design context, snapshots, and verification

**Files:**
- Create: `Fusion MCP Addin/fusion/__init__.py`
- Create: `Fusion MCP Addin/fusion/context.py`
- Create: `Fusion MCP Addin/fusion/snapshot.py`
- Create: `Fusion MCP Addin/fusion/units.py`
- Create: `Fusion MCP Addin/tools/get_fusion_status.py`
- Create: `Fusion MCP Addin/tools/get_design_context.py`
- Modify: `Fusion MCP Addin/tools/__init__.py`
- Create: `tests/fakes.py`
- Create: `tests/test_context.py`
- Create: `tests/test_snapshot.py`
- Create: `tests/test_units.py`

**Interfaces:**
- Produces: `get_status(app, server_version) -> dict`.
- Produces: `build_design_context(app, scope="summary", limit=200) -> dict`.
- Produces: `capture_snapshot(design) -> dict` and `compare_snapshots(before, after, expected) -> dict`.
- Produces: `format_internal_length(value_cm, unit) -> dict` and `parse_length_expression(expression, units_manager) -> float`.

- [ ] **Step 1: Write fake-design tests**

```python
def test_snapshot_delta_counts_created_features(self):
    before = {"counts": {"features": 2, "bodies": 1}}
    after = {"counts": {"features": 3, "bodies": 1}}
    result = compare_snapshots(before, after, {"features_created": 1})
    self.assertEqual(1, result["delta"]["features"])
    self.assertTrue(result["expectations_met"])

def test_centimeters_render_as_requested_millimeters(self):
    self.assertEqual(100.0, format_internal_length(10.0, "mm")["value"])
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m unittest tests.test_context tests.test_snapshot tests.test_units -v`

Expected: missing `fusion` modules.

- [ ] **Step 3: Implement adapters with defensive collection access**

Snapshots must include document identity, design type, active component name, timeline marker, counts for components/bodies/sketches/features, user parameter expressions, body entity tokens, bounding boxes, and volume when available. Context output must truncate collections at `limit` and set `truncated: true` when needed.

- [ ] **Step 4: Register both tools with strict object schemas**

`get_fusion_status` takes no fields. `get_design_context` accepts `scope` from `summary|components|parameters|all` and `limit` from 1 through 1000. Both `Item`s run on the main thread.

- [ ] **Step 5: Run adapter tests**

Run: `python -m unittest tests.test_context tests.test_snapshot tests.test_units -v`

Expected: all tests pass.

- [ ] **Step 6: Commit the task**

```powershell
git add -- 'Fusion MCP Addin/fusion' 'Fusion MCP Addin/tools/get_fusion_status.py' 'Fusion MCP Addin/tools/get_design_context.py' 'Fusion MCP Addin/tools/__init__.py' tests/fakes.py tests/test_context.py tests/test_snapshot.py tests/test_units.py
git commit -m "feat: expose Fusion status and design context"
```

### Task 4: Risk-gated arbitrary Fusion Python executor

**Files:**
- Create: `Fusion MCP Addin/fusion/executor.py`
- Create: `Fusion MCP Addin/tools/execute_fusion_python.py`
- Modify: `Fusion MCP Addin/tools/execute_api_script.py`
- Modify: `Fusion MCP Addin/tools/__init__.py`
- Create: `tests/test_executor.py`

**Interfaces:**
- Consumes: `classify_code`, `AuditLogger`, `capture_snapshot`, `compare_snapshots`.
- Produces: `execute_code(app, ui, intent, code, expected_changes, approval_callback=None) -> dict`.
- Produces MCP tool: `execute_fusion_python(intent: str, code: str, expected_changes: dict)`.

- [ ] **Step 1: Write failing executor tests**

```python
def test_routine_code_executes_without_prompt(self):
    result = execute_code(app, ui, "measure", "def run(context):\n print('ok')", {})
    self.assertFalse(result["isError"])
    self.assertEqual("routine", result["policy"]["level"])

def test_approval_hash_must_match_executed_code(self):
    original = "import os\nos.remove(target)"
    changed = original + "\nprint('changed')"
    callback = lambda decision, intent: decision.code_hash == hashlib.sha256(original).hexdigest()
    result = execute_code(app, ui, "delete", changed, {}, callback)
    self.assertEqual("POLICY_APPROVAL_REQUIRED", result["error"]["code"])

def test_syntax_error_returns_line_and_column(self):
    result = execute_code(app, ui, "bad", "def run(:", {})
    self.assertEqual("PYTHON_SYNTAX_ERROR", result["error"]["code"])
```

- [ ] **Step 2: Run executor tests and verify failure**

Run: `python -m unittest tests.test_executor -v`

Expected: missing executor module.

- [ ] **Step 3: Implement compile, approval, execution, and structured result flow**

The executor must:

1. Require a `run(context)` function in the submitted module.
2. Compile before any Fusion change and return line/column for `SyntaxError`.
3. Classify the exact UTF-8 code and retain its SHA-256.
4. Reject `blocked`; for `approval_required`, show purpose, reasons, document/file targets, and hash in Fusion and continue only on explicit Yes.
5. Recompute the hash immediately before `exec` and reject a mismatch.
6. Capture pre-state, execute in a fresh namespace, call `run` with `app`, `ui`, `design`, and `rootComponent`, call `computeAll()`, capture post-state, compare expectations, and return captured stdout.
7. Record the request and result through `AuditLogger` without credentials.

Routine namespace imports are restricted to `adsk`, `adsk.core`, `adsk.fusion`, and `math`. Approved code may use the normal importer. The result must explicitly say that policy classification is not a complete sandbox.

- [ ] **Step 4: Preserve compatibility**

Make `execute_api_script.handler(script)` call `execute_fusion_python.handler(intent="Legacy execute_api_script call", code=script, expected_changes={})` and mark the legacy tool description as deprecated.

- [ ] **Step 5: Run executor and policy tests**

Run: `python -m unittest tests.test_executor tests.test_policy tests.test_audit -v`

Expected: all tests pass.

- [ ] **Step 6: Commit the task**

```powershell
git add -- 'Fusion MCP Addin/fusion/executor.py' 'Fusion MCP Addin/tools/execute_fusion_python.py' 'Fusion MCP Addin/tools/execute_api_script.py' 'Fusion MCP Addin/tools/__init__.py' tests/test_executor.py
git commit -m "feat: add risk-gated Fusion Python executor"
```

### Task 5: Screenshot, undo, and STEP/STL export tools

**Files:**
- Modify: `Fusion MCP Addin/tools/get_screenshot.py`
- Create: `Fusion MCP Addin/tools/get_viewport_screenshot.py`
- Create: `Fusion MCP Addin/tools/undo_last_execution.py`
- Create: `Fusion MCP Addin/tools/export_design.py`
- Modify: `Fusion MCP Addin/tools/__init__.py`
- Create: `tests/test_export.py`
- Create: `tests/test_undo.py`

**Interfaces:**
- Produces: `get_viewport_screenshot(view="isometric", width=768, height=768) -> MCP result`.
- Produces: `undo_last_execution() -> MCP result` using executor checkpoint state.
- Produces: `export_design(format, path, entity_token=None, overwrite=False) -> MCP result`.

- [ ] **Step 1: Write failing export and undo tests**

```python
def test_existing_export_requires_overwrite_approval(self):
    result = validate_export_request("step", existing_path, overwrite=False)
    self.assertEqual("EXPORT_TARGET_EXISTS", result["code"])

def test_export_rejects_unsupported_format(self):
    result = validate_export_request("f3d", new_path, overwrite=False)
    self.assertEqual("INVALID_REQUEST", result["code"])

def test_undo_without_checkpoint_is_structured_error(self):
    self.assertEqual("NO_EXECUTION_CHECKPOINT", undo_with(app, None)["error"]["code"])
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m unittest tests.test_export tests.test_undo -v`

Expected: missing export and undo helpers.

- [ ] **Step 3: Implement tools**

The screenshot tool wraps the existing camera/image implementation and returns orientation, width, height, MIME type, and image content. Export supports only case-insensitive `step` and `stl`, resolves entity tokens at request time, requires approval for overwrite through the same policy confirmation helper, and verifies output existence plus non-zero byte size. Undo attempts the stored transaction/timeline checkpoint and reports whether recomputation succeeded.

- [ ] **Step 4: Run focused tests**

Run: `python -m unittest tests.test_export tests.test_undo -v`

Expected: all tests pass.

- [ ] **Step 5: Commit the task**

```powershell
git add -- 'Fusion MCP Addin/tools/get_screenshot.py' 'Fusion MCP Addin/tools/get_viewport_screenshot.py' 'Fusion MCP Addin/tools/undo_last_execution.py' 'Fusion MCP Addin/tools/export_design.py' 'Fusion MCP Addin/tools/__init__.py' tests/test_export.py tests/test_undo.py
git commit -m "feat: add verified screenshot undo and export tools"
```

### Task 6: Codex project configuration and Korean operating guidance

**Files:**
- Create: `.codex/config.toml.example`
- Create: `AGENTS.md`
- Modify: `README.md`
- Modify: `Fusion MCP Addin/README.md`
- Modify: `Fusion MCP Addin/tools/best_practices.md`
- Create: `scripts/check_install.py`
- Create: `tests/test_install_check.py`

**Interfaces:**
- Produces: an example project MCP entry using `http://127.0.0.1:9100/` and `FUSION_MCP_TOKEN`.
- Produces: `scripts/check_install.py --addon-path PATH` that validates manifest, token presence, port availability, and health/auth responses without printing the token.

- [ ] **Step 1: Write failing install-check tests**

```python
def test_report_never_contains_token(self):
    report = build_report(env={"FUSION_MCP_TOKEN": "top-secret"}, addon_path=valid_path)
    self.assertNotIn("top-secret", json.dumps(report))

def test_missing_manifest_is_actionable(self):
    report = build_report(env={}, addon_path=missing_path)
    self.assertEqual("ADDIN_MANIFEST_MISSING", report["checks"][0]["code"])
```

- [ ] **Step 2: Run test and verify failure**

Run: `python -m unittest tests.test_install_check -v`

Expected: missing `scripts.check_install`.

- [ ] **Step 3: Implement diagnostic and documentation**

Document ChatGPT desktop Settings → MCP servers → Add server → restart, Fusion Add-ins → Scripts and Add-Ins → add folder → Run, token setup, localhost-only behavior, data sent to the model, log location/deletion, troubleshooting, and the Korean mounting-plate acceptance prompt. `AGENTS.md` tells Codex to inspect context, query uncertain Fusion API documentation, make one verifiable geometry change at a time, call screenshots, compare expected changes, and never claim success from script exit alone.

- [ ] **Step 4: Run install tests and diagnostic**

Run: `python -m unittest tests.test_install_check -v`

Run: `python scripts/check_install.py --addon-path "Fusion MCP Addin"`

Expected: test passes; diagnostic reports manifest present and may report token/server unavailable without exposing secrets.

- [ ] **Step 5: Commit the task**

```powershell
git add -- .codex/config.toml.example AGENTS.md README.md 'Fusion MCP Addin/README.md' 'Fusion MCP Addin/tools/best_practices.md' scripts/check_install.py tests/test_install_check.py
git commit -m "docs: add ChatGPT Codex setup and diagnostics"
```

### Task 7: Full automated verification and live Fusion acceptance harness

**Files:**
- Create: `scripts/live_acceptance.py`
- Create: `docs/live-validation.md`
- Modify: `README.md`

**Interfaces:**
- Produces: `python scripts/live_acceptance.py --url http://127.0.0.1:9100/` using `FUSION_MCP_TOKEN` and standard library HTTP only.
- Produces: a JSON report for connection, tool discovery, mounting plate execution, numeric checks, screenshots, STEP/STL exports, error isolation, approval gates, and reconnect.

- [ ] **Step 1: Add the live harness**

The harness must call `initialize`, `tools/list`, `get_fusion_status`, `execute_fusion_python`, `get_design_context`, three screenshots, and two exports. The submitted Fusion code creates a 100 mm × 60 mm × 5 mm plate with four M6 holes whose centers are 10 mm from adjacent edges. Numeric assertions accept at most 0.01 mm dimension error.

- [ ] **Step 2: Run the complete non-Fusion suite**

Run: `python -m unittest discover -s tests -v`

Expected: all tests pass with Fusion not installed or running.

- [ ] **Step 3: Run syntax and repository checks**

Run: `python -m compileall -q "Fusion MCP Addin" scripts tests`

Run: `git diff --check`

Expected: both commands exit 0.

- [ ] **Step 4: Run live acceptance when Fusion is available**

Run: `python scripts/live_acceptance.py --url http://127.0.0.1:9100/`

Expected: exit 0 only when all live checks pass. If Fusion or the token is unavailable, record live validation as not run rather than converting that environment gap into a product pass.

- [ ] **Step 5: Record evidence and commit**

Write `docs/live-validation.md` with date, Fusion version, ChatGPT/Codex surface, commands, pass/fail counts, and unresolved limitations. Do not include tokens, local personal paths, or exported CAD artifacts.

```powershell
git add -- scripts/live_acceptance.py docs/live-validation.md README.md
git commit -m "test: add Fusion live acceptance workflow"
```

### Task 8: Final phase-1 verification and handoff

**Files:**
- Modify only files required to fix failures introduced by Tasks 1-7.

**Interfaces:**
- Consumes all prior task outputs.
- Produces a clean branch with reproducible automated results and an explicit live-validation status.

- [ ] **Step 1: Run all automated checks from a clean process**

Run: `python -m unittest discover -s tests -v`

Run: `python -m compileall -q "Fusion MCP Addin" scripts tests`

Run: `python scripts/check_install.py --addon-path "Fusion MCP Addin"`

Run: `git diff --check`

Expected: tests and compilation pass; diagnostic is truthful about external state; diff check passes.

- [ ] **Step 2: Inspect only the final branch state**

Run: `git status --short --branch`

Run: `git log --oneline --decorate main..HEAD`

Expected: intentional commits only and no uncommitted implementation changes.

- [ ] **Step 3: Report without a separate review round**

Report the fork URL, branch, implemented tools, automated test count, live Fusion status, install command/path, and known limitations. Do not push the feature branch or merge to `main` without separate explicit authorization.
