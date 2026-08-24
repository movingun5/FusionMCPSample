# Fusion 360 Parametric Profile Extrusion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one explicit MCP tool that atomically turns a validated, parameter-driven XY closed polyline from drawing measurements into one Fusion New Body extrusion with exact Undo.

**Architecture:** Keep image interpretation in Codex and add a pure `profile_geometry.py` boundary for request normalization, Fusion-unit evaluation, simple-polygon checks, and parameter naming. Build entities in `profile_builder.py`, own transaction/snapshot/checkpoint policy in `parametric_profiles.py`, and expose only a strict schema from the tool module. Reuse the existing Part/Hybrid container strategy, coordinate-dimension helper, snapshot verification, audit redaction, and exact-token root-part Undo conventions.

**Tech Stack:** Python 3.14, Autodesk Fusion 360 API, local MCP registry, `unittest`, Windows PowerShell `System.Drawing` for deterministic live-only PNG fixtures; no new Python package.

**Spec:** `docs/superpowers/specs/2026-08-24-fusion360-parametric-profile-extrusion-design.md`

## Global Constraints

- The first release supports only one simple 3–32 vertex straight-line profile on XY and one positive +Z New Body depth.
- The tool accepts structured dimensions only; no image path, bytes, URL, OCR output, or arbitrary Python.
- Every Fusion mutation is UI-thread routed by the existing server task queue and enclosed in one transaction.
- All coordinate and depth expressions use Fusion length parsing and generated `mm` user parameters.
- Part Design uses the root component; Hybrid Design uses one child component; Assembly external parts remain unsupported.
- Failure restores starting counts or returns `ROLLBACK_FAILED`; exact-target Undo never deletes ambiguous entities.
- Server version becomes `2.3.0`, and the registry contains exactly 22 unique tools.
- Full tests, compileall, live numeric/screenshot checks, STEP/STL export, install hash comparison, and a pushed Korean commit are required.

---

### Task 1: Pure Request and Polygon Validation

**Files:**
- Create: `Fusion MCP Addin/fusion/profile_geometry.py`
- Create: `tests/test_profile_geometry.py`

**Interfaces:**
- Produces: `ProfileValidation(code, message, details=None)`.
- Produces: `validate_profile_request(name, parameter_prefix, vertices, depth_expression) -> dict`.
- Produces: `generated_profile_parameter_names(normalized) -> dict` with `depth` and ordered `vertices` mappings.
- Produces: `evaluate_profile_request(normalized, units_manager) -> dict`.
- Produces: `all_profile_parameter_names(evaluated) -> list[str]` in depth then vertex X/Y order.

- [ ] **Step 1: Write failing normalization and naming tests**

Cover a six-point L profile, input immutability, safe unique keys, strict vertex fields, 3/32 count boundaries, control characters, and deterministic names:

```python
normalized = validate_profile_request("LProfile", "l_profile", vertices, "8 mm")
names = generated_profile_parameter_names(normalized)
self.assertEqual("l_profile_depth", names["depth"])
self.assertEqual("l_profile_p1_x", names["vertices"]["p1"]["x"])
self.assertEqual(vertices, original_vertices)
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `python -m unittest tests.test_profile_geometry -v`

Expected: import failure for `fusion_mcp_addin.fusion.profile_geometry`.

- [ ] **Step 3: Implement strict request normalization and names**

Use the plate identifier/control-character rules. Require each vertex object to contain exactly `key`, `x_expression`, and `y_expression`; clone every nested object before returning.

- [ ] **Step 4: Add failing evaluated-geometry tests**

Test positive depth, evaluated mm output, clockwise/counterclockwise L shapes, duplicate adjacent/closing points, bow-tie intersection, nonadjacent touching, collinear area zero, invalid units, and nonpositive depth. Require these codes:

```text
PROFILE_EXPRESSION_INVALID
PROFILE_DEPTH_INVALID
PROFILE_VERTEX_DUPLICATE
PROFILE_SELF_INTERSECTION
PROFILE_AREA_INVALID
```

- [ ] **Step 5: Implement polygon evaluation and simple-polygon validation**

Use `parse_length_expression`, orientation/cross-product segment tests with `1e-9 cm` tolerance, and the shoelace formula. Adjacent edges may share only their intended endpoint; all other intersection or contact is rejected.

- [ ] **Step 6: Run focused tests and commit**

Run: `python -m unittest tests.test_profile_geometry -v`

Expected: all profile-geometry tests pass.

```powershell
git add -- "Fusion MCP Addin/fusion/profile_geometry.py" tests/test_profile_geometry.py
git commit -m "feat: 도면 프로파일 치수 검증 업데이트"
git push origin docs/fusion360-codex-design
```

### Task 2: Low-Level Fusion Profile Builder

**Files:**
- Create: `Fusion MCP Addin/fusion/profile_builder.py`
- Create: `tests/test_profile_builder.py`
- Modify: `tests/fakes.py`

**Interfaces:**
- Consumes: Task 1 evaluated profile dictionary.
- Produces: `ProfileBuildFailure(stage, code, message)`.
- Produces: `FusionProfileBuilder(design, root, **factories)`.
- Produces: `FusionProfileBuilder.build(name, evaluated) -> dict` containing occurrence, component, container mode, parameters, profile sketch, lines, extrusion, and body.
- Produces: `FusionProfileBuilder.rollback() -> dict`.

- [ ] **Step 1: Extend only the shared sketch fakes needed by profile lines**

Add `FakeSketchLines.addByTwoPoints(start, end)` returning and recording one `FakeSketchLine`. Preserve existing rectangle behavior and tests.

- [ ] **Step 2: Write failing Part/Hybrid and parameter tests**

Assert Hybrid creates/names one component, Part keeps the root name and creates no occurrence, the six-point profile creates 13 user parameters, and parameter comments equal `create_parametric_profile_extrusion:LProfile`.

- [ ] **Step 3: Implement factory/container/parameter stages**

Mirror `FusionPlateBuilder` factory injection and Part Design intent handling without importing plate-private state. Parameter creation order is depth then each vertex X/Y pair.

- [ ] **Step 4: Write failing profile-sketch tests**

Require six points, six connected lines, a closed profile, `<name>_Profile`, and coordinate dimensions that reference generated names. Negative values must use `-(parameter_name)` and zero coordinates must use the sketch origin/coincident constraint convention.

- [ ] **Step 5: Implement sketch creation**

Create/reuse SketchPoints, join them with `addByTwoPoints`, close last to first, and call the existing `_add_position_dimensions` for non-origin points. Keep `isComputeDeferred` true until all points, lines, and dimensions are present, then require exactly one profile.

- [ ] **Step 6: Write failing extrusion and rollback tests**

Require `addSimple(profile, ValueInput(<prefix>_depth), NewBody)`, solid body naming, stage-specific failures, Hybrid occurrence rollback, root-part exact entity recording, and parameter cleanup.

- [ ] **Step 7: Implement extrusion and rollback**

Reuse `_largest_profile`; record created root-part sketch/feature/body handles so a nontransaction fallback can remove only those entities. Return structured rollback evidence.

- [ ] **Step 8: Run focused and regression tests, then commit**

Run:

```powershell
python -m unittest tests.test_profile_builder tests.test_plate_builder tests.test_sketches tests.test_extrusions -v
```

Expected: all focused and reused-builder tests pass.

```powershell
git add -- "Fusion MCP Addin/fusion/profile_builder.py" tests/test_profile_builder.py tests/fakes.py
git commit -m "feat: 도면 프로파일 Fusion 빌더 업데이트"
git push origin docs/fusion360-codex-design
```

### Task 3: Atomic Orchestration and Exact Undo

**Files:**
- Create: `Fusion MCP Addin/fusion/parametric_profiles.py`
- Create: `tests/test_parametric_profiles.py`
- Modify: `Fusion MCP Addin/fusion/undo.py`
- Modify: `tests/test_undo.py`

**Interfaces:**
- Consumes: Tasks 1–2 validation/evaluation/builder APIs.
- Produces: `create_parametric_profile_extrusion(app, name, parameter_prefix, vertices, depth_expression, *, builder_factory=FusionProfileBuilder, audit_logger=None) -> MCP result`.
- Extends checkpoint routing for mutation `create_parametric_profile_extrusion`.

- [ ] **Step 1: Write failing success, validation, and collision tests**

Require no builder call for invalid geometry or generated-name collision. On success require body +1, Part component +0 or Hybrid +1, ordered `vertices_mm`, `depth_mm`, body summary, audit result, and checkpoint tokens.

- [ ] **Step 2: Implement orchestration through transaction commit**

Follow `create_parametric_plate`: active design checks, pure preflight, name collisions, starting snapshot/counts, transaction, builder, `computeAll`, `compare_snapshots`, commit, checkpoint, and redacted audit.

- [ ] **Step 3: Write failing rollback tests**

Cover sketch failure, recompute failure, verification mismatch, transaction-restored invalid handles, and true count mismatch returning `ROLLBACK_FAILED`.

- [ ] **Step 4: Implement rollback classification**

Prefer a verified transaction-restored snapshot. Otherwise call builder rollback, recompute, recapture counts, and return the builder stage/code only when restoration is complete.

- [ ] **Step 5: Write failing exact Undo tests**

For child component require exact occurrence/component tokens and all parameter names before deletion. For root part require exact feature/sketch/parameter tokens, preserve an unrelated body, and restore starting counts. Missing or mismatched targets must perform no mutation.

- [ ] **Step 6: Implement profile checkpoint Undo routing**

Extract a shared exact-entity helper only if it reduces duplication without changing plate behavior. Route the new mutation before generic `UndoCommand`; return `undo_mode = "parametric_profile_deleted"`.

- [ ] **Step 7: Run focused tests and commit**

Run:

```powershell
python -m unittest tests.test_parametric_profiles tests.test_undo tests.test_parametric_plates -v
```

Expected: all atomic creation, rollback, old plate Undo, and new profile Undo tests pass.

```powershell
git add -- "Fusion MCP Addin/fusion/parametric_profiles.py" "Fusion MCP Addin/fusion/undo.py" tests/test_parametric_profiles.py tests/test_undo.py
git commit -m "feat: 도면 프로파일 원자 생성과 Undo 업데이트"
git push origin docs/fusion360-codex-design
```

### Task 4: MCP Schema, Registry, Version, and Skill Routing

**Files:**
- Create: `Fusion MCP Addin/tools/create_parametric_profile_extrusion.py`
- Create: `tests/test_parametric_profile_tool.py`
- Modify: `Fusion MCP Addin/tools/__init__.py`
- Modify: `Fusion MCP Addin/tools/get_fusion_status.py`
- Modify: `tests/test_context.py`
- Modify: `README.md`
- Modify: `Fusion MCP Addin/README.md`
- Modify: `skills/fusion/SKILL.md`
- Modify: `skills/fusion/references/image-modeling.md`
- Modify: `docs/live-validation.md`

**Interfaces:**
- Consumes: Task 3 orchestration function.
- Produces: one strict MCP tool and a 22-tool server catalog at version 2.3.0.

- [ ] **Step 1: Write failing strict-schema and registry tests**

Require exactly four top-level properties; strict vertex items; `minItems=3`, `maxItems=32`; required fields; handler forwarding; 22 unique registered tool names; and status version 2.3.0.

- [ ] **Step 2: Implement the MCP tool and registration**

The handler calls `adsk.core.Application.get()` and forwards the four request fields unchanged. Do not accept `plane`, image, operation, or optional arbitrary fields.

- [ ] **Step 3: Update documentation and progressive Fusion skill routing**

Document the structured example, generated parameter names, centered XY coordinates, atomicity, Part/Hybrid behavior, and exclusions. Add the profile tool to the image-modeling routing after calibrated canvas validation. Mark live 2.3.0 status as restart-required without claiming runtime success.

- [ ] **Step 4: Run schema, catalog, skill, and full tests**

Run:

```powershell
python -m unittest tests.test_parametric_profile_tool tests.test_context -v
python -m unittest discover -s tests -q
python -m compileall -q "Fusion MCP Addin" scripts tests
git diff --check
```

Expected: all tests pass, compilation exits 0, and diff check is clean.

- [ ] **Step 5: Commit and push the implementation**

```powershell
git add -- "Fusion MCP Addin" README.md skills/fusion docs/live-validation.md tests/test_parametric_profile_tool.py tests/test_context.py
git commit -m "feat: 이미지 기반 파라메트릭 프로파일 MCP 업데이트"
git push origin docs/fusion360-codex-design
```

### Task 5: Deterministic Drawing Fixtures and Live Harness

**Files:**
- Create: `scripts/generate_profile_drawing_fixtures.ps1`
- Create after generator run: `tests/assets/profile-l-top.png`
- Create after generator run: `tests/assets/profile-l-front.png`
- Create: `scripts/live_profile_acceptance.py`
- Create: `tests/test_live_profile_acceptance.py`
- Modify: `.gitignore` only if generated reports/exports are not already ignored

**Interfaces:**
- Produces: two deterministic distinct 1200×800 PNG drawings without product runtime dependencies.
- Produces: an authenticated raw-MCP acceptance harness with base64/path-redacted JSON report.

- [ ] **Step 1: Add the deterministic Windows fixture generator**

Use `System.Drawing.Bitmap`, `Graphics`, `Pen`, `Font`, and `Save(..., Png)`. Top view draws the approved six-point L outline with `100 mm`, `60 mm`, `40 mm`, and `30 mm` annotations. Front view draws `100 × 8 mm`. Create parent directories explicitly and dispose every GDI object in `finally`.

- [ ] **Step 2: Generate fixtures and record hashes**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/generate_profile_drawing_fixtures.ps1
Get-FileHash tests/assets/profile-l-top.png,tests/assets/profile-l-front.png -Algorithm SHA256
```

Expected: two nonempty distinct PNG files and stable hashes on a repeated generator run.

- [ ] **Step 3: Write failing live-harness construction tests**

Use a fake MCP client to require this call order: initialize, tools/list, status, blank context, orthographic canvas set, profile extrusion, context, screenshots, invalid bow-tie rejection, profile Undo, final context, STEP/STL exports. Require image payload redaction and no bearer token/full paths in the report.

- [ ] **Step 4: Implement the live harness without arbitrary Python**

Use the existing `MCPClient` transport. Add `--confirm-blank-design`, `--export-dir`, and `--report`. Stop dependent steps after a failed canvas or profile prerequisite. Use the approved L-profile request and require body bounds within 0.01 mm.

- [ ] **Step 5: Run harness tests and commit fixtures**

Run:

```powershell
python -m unittest tests.test_live_profile_acceptance -v
python -m compileall -q scripts tests
git diff --check
```

Expected: all harness tests pass and reports redact image bytes/paths/tokens.

```powershell
git add -- scripts/generate_profile_drawing_fixtures.ps1 scripts/live_profile_acceptance.py tests/assets/profile-l-top.png tests/assets/profile-l-front.png tests/test_live_profile_acceptance.py .gitignore
git commit -m "test: 이미지 프로파일 도면 검증 도구 업데이트"
git push origin docs/fusion360-codex-design
```

### Task 6: Automated Verification, Install, and Restart Boundary

**Files:**
- Copy after verification: repository `Fusion MCP Addin` into both detected Autodesk add-in paths
- Copy after verification: repository `skills/fusion` into `%USERPROFILE%\.codex\skills\fusion`

**Interfaces:**
- Produces: installed server 2.3.0 and updated Fusion skill ready for one required restart.

- [ ] **Step 1: Run final automated verification**

Run:

```powershell
python -m unittest discover -s tests -q
python -m compileall -q "Fusion MCP Addin" scripts tests
git diff --check
git status --short --branch
```

Expected: full suite passes, compilation and diff check exit 0, and only intentional changes remain.

- [ ] **Step 2: Copy verified files without deleting unrelated installed files**

Copy the repository add-in into each existing Autodesk Fusion add-in directory and the repository skill into the installed `fusion` skill directory. Never print `FUSION_MCP_TOKEN`.

- [ ] **Step 3: Compare installed SHA-256 hashes**

Compare repository and installed copies of `profile_geometry.py`, `profile_builder.py`, `parametric_profiles.py`, `undo.py`, the new tool, `get_fusion_status.py`, `skills/fusion/SKILL.md`, and `skills/fusion/references/image-modeling.md`.

- [ ] **Step 4: Pause once for restart**

Ask the user to fully restart Fusion and Codex, run `Fusion MCP Addin`, and open one new unsaved blank Part Design. This is the only implementation pause.

### Task 7: Fusion Live Evidence and Final Push

**Files:**
- Modify: `docs/live-validation.md`
- Create locally but do not commit when it contains user paths: `docs/live-profile-validation-result.json`

**Interfaces:**
- Produces: verified 2.3.0 live evidence, final clean branch, and identical local/remote hashes.

- [ ] **Step 1: Verify server/tool discovery and blank context**

Require Fusion 2704.1.53, server 2.3.0, authentication, 22 unique tools including the new tool, one active blank design, and no `l_profile_*` parameters.

- [ ] **Step 2: Run the explicit acceptance harness**

Use an accessible Documents export directory:

```powershell
$fusionExportDir = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'FusionMCPProfileExports'
New-Item -ItemType Directory -Force -Path $fusionExportDir | Out-Null
python scripts/live_profile_acceptance.py --confirm-blank-design --export-dir $fusionExportDir --report docs/live-profile-validation-result.json
```

Require distinct XY/XZ canvases, shared X difference 0 mm, `100 × 60 × 8 mm` body bounds, ordered vertex/depth parameters, matching top/front/isometric screenshots, bow-tie rejection without geometry delta, exact profile Undo, and verified STEP/STL files.

- [ ] **Step 3: Record evidence and rerun verification**

Update only confirmed facts in `docs/live-validation.md`, including any typed-tool cache limitation. Run the full tests, compileall, `git diff --check`, and `git status --short` again.

- [ ] **Step 4: Commit, push, and verify remote equality**

```powershell
git add -- docs/live-validation.md
git commit -m "test: 이미지 기반 프로파일 Fusion 라이브 검증 업데이트"
git push origin docs/fusion360-codex-design
git status --short --branch
git rev-parse HEAD
git rev-parse origin/docs/fusion360-codex-design
```

Expected: clean branch and identical hashes. Do not merge `main` or create a pull request.
