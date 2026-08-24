# Fusion 360 Orthographic Canvas Set Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one explicit MCP tool that atomically places 2~3 calibrated orthographic reference images, rejects inconsistent shared model dimensions before mutation, and removes the whole set with one checkpointed Undo.

**Architecture:** Keep image interpretation in Codex and add a pure `fusion/orthographic.py` validation layer for view-shape and shared-axis checks. Refactor the existing single-canvas implementation just enough to expose a prepared-canvas boundary, then build `fusion/canvas_sets.py` around one Fusion transaction and one multi-entity checkpoint. Register a strict nested MCP schema, preserve the existing individual context summaries, and progressively disclose the multi-view workflow through the existing Fusion image-modeling reference.

**Tech Stack:** Python 3, Autodesk Fusion 360 Python API (`Canvases`, `CanvasInput`, `Matrix2D`, `UnitsManager`), existing MCP primitives and authenticated local transport, `unittest`, existing Fusion test fakes.

**Spec:** `docs/superpowers/specs/2026-08-24-fusion360-orthographic-canvas-set-design.md`

## Global Constraints

- Server version becomes exactly `2.1.0`.
- The new tool is exactly `create_orthographic_canvas_set(name, views, dimension_tolerance_mm=0.25)`.
- `views` contains 2~3 objects with unique `xy`, `xz`, or `yz` planes.
- Accept only existing absolute local `.png`, `.jpg`, `.jpeg`, `.tif`, or `.tiff` regular files of at most 25 MiB each.
- Do not add Pillow, OCR, OpenCV, an external AI API, SVG generation, or any new runtime dependency.
- Never include full image paths or image bytes in MCP results, structured errors, audit records, or final reports.
- Map XY to X/Y, XZ to X/Z, and YZ to Y/Z; compare every axis supplied by two views with an absolute tolerance of `0.001`~`10.0` mm.
- Validate every input, expression, image ratio, shared dimension, and generated name before starting a Fusion transaction.
- Create all canvases in one transaction; on failure abort the transaction or delete all partial canvases in reverse order.
- Record one checkpoint containing every created canvas name and entity token; one `undo_last_execution` call removes the complete set.
- Do not add persistent Fusion attributes for set membership; use `<name>_<PLANE>` names and the checkpoint/result contract.
- Keep the base Fusion skill short; add multi-view details only to `skills/fusion/references/image-modeling.md`.
- Implementation and live verification are separate Korean-named commits pushed to `docs/fusion360-codex-design`.
- Do not merge to `main` or create a PR without explicit user authorization.

---

### Task 1: Pure Orthographic Request and Shared-Dimension Validation

**Files:**
- Create: `Fusion MCP Addin/fusion/orthographic.py`
- Create: `tests/test_orthographic.py`

**Interfaces:**
- Consumes: plain Python request dictionaries and prepared view measurements from Task 2.
- Produces: `OrthographicValidation(code, message, details=None)`.
- Produces: `validate_orthographic_request(name, views, dimension_tolerance_mm) -> tuple[str, list[dict], float]`.
- Produces: `compare_shared_dimensions(measurements, tolerance_mm) -> tuple[dict, list[dict]]`, where each measurement contains `plane`, `width_mm`, and `height_mm`.

- [ ] **Step 1: Write failing request-shape tests**

Create literal cases in `tests/test_orthographic.py`:

```python
import unittest

import tests  # noqa: F401
from fusion_mcp_addin.fusion.orthographic import (
    OrthographicValidation,
    compare_shared_dimensions,
    validate_orthographic_request,
)


class OrthographicValidationTests(unittest.TestCase):
    def view(self, plane):
        return {
            "image_path": rf"C:\drawings\{plane}.png",
            "plane": plane,
            "width_expression": "100 mm",
        }

    def test_accepts_two_or_three_unique_principal_views(self):
        for planes in (("xy", "xz"), ("xy", "xz", "yz")):
            with self.subTest(planes=planes):
                name, views, tolerance = validate_orthographic_request(
                    "Gearbox Views",
                    [self.view(plane) for plane in planes],
                    0.25,
                )
                self.assertEqual("Gearbox Views", name)
                self.assertEqual(list(planes), [view["plane"] for view in views])
                self.assertEqual(0.25, tolerance)

    def test_rejects_wrong_count_duplicate_planes_and_unknown_fields(self):
        cases = (
            ([self.view("xy")], "INVALID_REQUEST"),
            ([self.view("xy"), self.view("xy")], "INVALID_REQUEST"),
            ([{**self.view("xy"), "rotation": 90}, self.view("xz")], "INVALID_REQUEST"),
        )
        for views, code in cases:
            with self.subTest(views=views):
                with self.assertRaises(OrthographicValidation) as caught:
                    validate_orthographic_request("Views", views, 0.25)
                self.assertEqual(code, caught.exception.code)
```

Add separate literal assertions for blank set names, non-list views, invalid plane strings, missing required view fields, invalid booleans, opacity outside 0~100, non-number/bool tolerance, and tolerance values `0`, `0.0009`, and `10.001`.

- [ ] **Step 2: Run request tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_orthographic.OrthographicValidationTests.test_accepts_two_or_three_unique_principal_views tests.test_orthographic.OrthographicValidationTests.test_rejects_wrong_count_duplicate_planes_and_unknown_fields -v
```

Expected: import failure for `fusion_mcp_addin.fusion.orthographic`.

- [ ] **Step 3: Implement exact request validation**

Create `orthographic.py` with these constants and normalization rules:

```python
_PLANES = {"xy", "xz", "yz"}
_VIEW_KEYS = {
    "image_path",
    "plane",
    "width_expression",
    "center_x_expression",
    "center_y_expression",
    "opacity",
    "flip_horizontal",
    "flip_vertical",
}
_REQUIRED_VIEW_KEYS = {"image_path", "plane", "width_expression"}


class OrthographicValidation(ValueError):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
```

`validate_orthographic_request` must copy each view and set only these defaults:

```python
{
    "center_x_expression": "0 mm",
    "center_y_expression": "0 mm",
    "opacity": 50,
    "flip_horizontal": False,
    "flip_vertical": False,
}
```

Do not resolve paths or evaluate expressions here; Task 2 owns Fusion-dependent preparation. Reject booleans as tolerances even though `bool` is an `int` subclass.

- [ ] **Step 4: Write failing shared-axis tests**

Add hand-derived measurements:

```python
    def test_compares_x_y_and_z_shared_dimensions(self):
        axes, checks = compare_shared_dimensions(
            [
                {"plane": "xy", "width_mm": 100.0, "height_mm": 60.0},
                {"plane": "xz", "width_mm": 100.2, "height_mm": 40.0},
                {"plane": "yz", "width_mm": 60.1, "height_mm": 40.1},
            ],
            0.25,
        )

        self.assertEqual({"x": 100.1, "y": 60.05, "z": 40.05}, axes)
        self.assertEqual(["x", "y", "z"], [item["axis"] for item in checks])
        self.assertTrue(all(item["matched"] for item in checks))

    def test_rejects_shared_dimension_above_tolerance(self):
        with self.assertRaises(OrthographicValidation) as caught:
            compare_shared_dimensions(
                [
                    {"plane": "xy", "width_mm": 100.0, "height_mm": 60.0},
                    {"plane": "xz", "width_mm": 100.251, "height_mm": 40.0},
                ],
                0.25,
            )

        self.assertEqual("ORTHOGRAPHIC_DIMENSION_MISMATCH", caught.exception.code)
        self.assertEqual("x", caught.exception.details["axis"])
        self.assertEqual(0.251, caught.exception.details["difference_mm"])
```

Add a boundary case where a difference exactly equal to `0.25` passes. Derive expected averages and rounded differences as literals to six decimal places.

- [ ] **Step 5: Run shared-axis tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_orthographic -v
```

Expected: request tests pass while shared-axis tests fail because `compare_shared_dimensions` is missing or incomplete.

- [ ] **Step 6: Implement model-axis mapping and comparison**

Use this exact mapping:

```python
_PLANE_AXES = {
    "xy": ("x", "y"),
    "xz": ("x", "z"),
    "yz": ("y", "z"),
}
```

For each measurement, append `(plane, width_mm)` to its horizontal axis and `(plane, height_mm)` to its vertical axis. For axes with two values, compute the absolute difference, round returned numbers to six decimals, append a check containing `axis`, `planes`, `values_mm`, `difference_mm`, `tolerance_mm`, and `matched`, and raise on the first mismatch. `axes_mm` uses the rounded average for two values and the only value for one.

- [ ] **Step 7: Run Task 1 tests and confirm GREEN**

Run:

```powershell
python -m unittest tests.test_orthographic -v
```

Expected: all orthographic validation tests pass.

---

### Task 2: Prepared Canvas Boundary and Atomic Canvas-Set Core

**Files:**
- Modify: `Fusion MCP Addin/fusion/canvases.py`
- Create: `Fusion MCP Addin/fusion/canvas_sets.py`
- Modify: `Fusion MCP Addin/fusion/undo.py`
- Modify: `tests/fakes.py`
- Modify: `tests/test_canvases.py`
- Create: `tests/test_canvas_sets.py`
- Modify: `tests/test_undo.py`

**Interfaces:**
- Consumes: Task 1 `validate_orthographic_request` and `compare_shared_dimensions`.
- Produces from `canvases.py`: `prepare_reference_canvas(design, component, name, image_path, plane, width_expression, center_x_expression="0 mm", center_y_expression="0 mm", opacity=50, flip_horizontal=False, flip_vertical=False, point_factory=None, vector_factory=None) -> dict`.
- Produces from `canvases.py`: `add_prepared_canvas(canvases, prepared) -> Canvas`.
- Produces from `canvas_sets.py`: `create_orthographic_canvas_set(app, name, views, dimension_tolerance_mm=0.25, point_factory=None, vector_factory=None, audit_logger=None) -> dict`.
- Extends Undo checkpoint mutation `create_orthographic_canvas_set` with `canvases: list[{name, entity_token}]` and `starting_canvas_count`.

- [ ] **Step 1: Write failing prepared-canvas extraction tests**

Extend `tests/test_canvases.py` to call `prepare_reference_canvas` directly with the existing fake design and 2:1 default image transform. Assert it returns a dictionary containing:

```python
{
    "name": "Front Reference",
    "image_name": "plate.png",
    "image_size_bytes": 10,
    "plane": "xy",
    "width_mm": 100.0,
    "height_mm": 50.0,
    "center_mm": [10.0, -5.0],
    "opacity": 60,
    "flip_horizontal": False,
    "flip_vertical": False,
}
```

Also assert no canvas was added and no transaction command ran. Keep the existing public `create_reference_canvas` behavior test unchanged to guard compatibility.

- [ ] **Step 2: Run the prepared test and confirm RED**

Run:

```powershell
python -m unittest tests.test_canvases.ReferenceCanvasTests.test_prepares_canvas_without_mutating_design -v
```

Expected: import or attribute failure for `prepare_reference_canvas`.

- [ ] **Step 3: Extract preparation without changing single-canvas behavior**

Move the existing file, design, component, name-conflict, expression, aspect-ratio, transform, opacity, and display-option preparation into `prepare_reference_canvas`. It returns private fields needed for creation (`canvas_input`, `component`, `canvases`, centimeter measurements) plus the safe summary fields above. It raises a private `CanvasValidation` carrying the existing error code/message/details; details never contain the resolved path.

Implement `add_prepared_canvas` exactly as the mutation boundary:

```python
def add_prepared_canvas(canvases, prepared):
    canvas = canvases.add(prepared["canvas_input"])
    if canvas is None:
        raise RuntimeError("Fusion did not create the reference canvas.")
    canvas.name = prepared["name"]
    return canvas
```

Refactor `create_reference_canvas` to call both helpers inside its existing transaction. Preserve all current result keys, error codes, redaction, checkpoint fields, and tests.

- [ ] **Step 4: Run all single-canvas tests and confirm GREEN**

Run:

```powershell
python -m unittest tests.test_canvases tests.test_context tests.test_undo -v
```

Expected: all existing tests plus the new preparation test pass.

- [ ] **Step 5: Extend fakes for controlled multi-add failures**

Change `FakeCanvases` so `fail_add_at=None` can fail a specific one-based add attempt while preserving existing `fail_add` behavior:

```python
class FakeCanvases(FakeCollection):
    def __init__(self, items=(), fail_input=False, fail_add=False, fail_add_at=None):
        super().__init__(items)
        self.fail_input = fail_input
        self.fail_add = fail_add
        self.fail_add_at = fail_add_at
        self.add_attempts = 0

    def add(self, canvas_input):
        self.add_attempts += 1
        if self.fail_add or self.add_attempts == self.fail_add_at:
            return None
        # existing canvas creation follows
```

- [ ] **Step 6: Write failing atomic set tests**

Create `tests/test_canvas_sets.py` using two temporary PNG files and the existing 2:1 fake transform. The default success request uses XY and XZ with both widths `100 mm`, so the shared X check matches and both heights are `50 mm`.

Required tests:

```python
def test_creates_two_view_set_in_one_transaction_and_checkpoint(self):
    result = self.create()
    content = result["structuredContent"]
    self.assertFalse(result["isError"])
    self.assertEqual(2, self.root.canvases.count)
    self.assertEqual(["Assembly_XY", "Assembly_XZ"], [v["name"] for v in content["set"]["views"]])
    self.assertEqual({"x": 100.0, "y": 50.0, "z": 50.0}, content["set"]["axes_mm"])
    self.assertEqual(1, len(content["shared_dimension_checks"]))
    self.assertEqual('PTransaction.Start "Codex Orthographic Canvas Set"', self.app.commands[0])
    self.assertEqual("PTransaction.Commit", self.app.commands[-1])
    self.assertEqual(2, len(get_last_checkpoint()["canvases"]))

def test_dimension_mismatch_is_rejected_before_transaction(self):
    views = self.views()
    views[1]["width_expression"] = "100.3 mm"
    result = self.create(views=views)
    self.assertEqual("ORTHOGRAPHIC_DIMENSION_MISMATCH", result["error"]["code"])
    self.assertEqual([], self.app.commands)
    self.assertEqual(0, self.root.canvases.count)

def test_second_add_failure_aborts_the_whole_set(self):
    self.root.canvases.fail_add_at = 2
    result = self.create()
    self.assertEqual("CANVAS_SET_WRITE_FAILED", result["error"]["code"])
    self.assertEqual("PTransaction.Abort", self.app.commands[-1])
```

Also cover three-view axis checks, tolerance boundary success, duplicate generated-name conflict, one invalid image or expression causing no transaction, recompute failure, basename-only results/audit, and non-transaction fallback deleting every partial canvas in reverse order.

- [ ] **Step 7: Run set tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_canvas_sets -v
```

Expected: import failure for `fusion_mcp_addin.fusion.canvas_sets`.

- [ ] **Step 8: Implement atomic set creation**

In `canvas_sets.py`, follow this order:

```python
name, normalized_views, tolerance = validate_orthographic_request(
    name, views, dimension_tolerance_mm
)
prepared = [
    prepare_reference_canvas(
        design,
        component,
        f"{name}_{view['plane'].upper()}",
        **{key: value for key, value in view.items() if key != "plane"},
        plane=view["plane"],
        point_factory=point_factory,
        vector_factory=vector_factory,
    )
    for view in normalized_views
]
axes_mm, checks = compare_shared_dimensions(prepared, tolerance)
```

Only after every preparation and comparison succeeds, start `PTransaction.Start "Codex Orthographic Canvas Set"`. Add prepared inputs in view order, set names, recompute once, commit once, then record:

```python
{
    "request_id": request_id,
    "mutation": "create_orthographic_canvas_set",
    "document_id": document_id,
    "component_entity_token": entity_token(component),
    "set_name": name,
    "starting_canvas_count": starting_canvas_count,
    "canvases": [
        {"name": canvas.name, "entity_token": entity_token(canvas)}
        for canvas in created
    ],
}
```

Build success and audit summaries only from safe prepared fields. Translate `CanvasValidation` and `OrthographicValidation` to existing MCP errors. Unexpected failures return `CANVAS_SET_WRITE_FAILED`; recompute failures return `RECOMPUTE_FAILED`.

- [ ] **Step 9: Run set and regression tests and confirm GREEN**

Run:

```powershell
python -m unittest tests.test_canvas_sets tests.test_canvases tests.test_context -v
```

Expected: all focused tests pass.

- [ ] **Step 10: Write failing multi-canvas Undo tests**

Extend `tests/test_undo.py` with a checkpoint containing two exact canvases. Assert one call deletes both, uses `undo_mode = "canvas_set_deleted"`, commits one transaction, and returns the starting count. Add a missing-second-target case asserting `CHECKPOINT_ENTITY_NOT_FOUND`, no transaction commands, and both existing canvases unchanged.

- [ ] **Step 11: Run multi-canvas Undo tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_undo.UndoTests.test_undo_canvas_set_deletes_every_checkpoint_canvas tests.test_undo.UndoTests.test_undo_canvas_set_refuses_partial_target_match -v
```

Expected: the first test uses generic Undo or leaves canvases; the second does not enforce all-target prevalidation.

- [ ] **Step 12: Implement prevalidated canvas-set Undo**

Add `_undo_reference_canvas_set` to `fusion/undo.py`. Before starting a transaction:

1. Validate active component token when present.
2. Resolve every checkpoint canvas by entity token, falling back to exact name only when no token was recorded.
3. Reject if any target is missing or if the resolved count differs from the checkpoint count.
4. Start `PTransaction.Start "Codex Undo Orthographic Canvas Set"`.
5. Delete targets in reverse checkpoint order.
6. Recompute, commit, and verify collection count equals `starting_canvas_count` when recorded.

Route `mutation == "create_orthographic_canvas_set"` to this helper before generic `UndoCommand`.

- [ ] **Step 13: Run Task 2 tests and confirm GREEN**

Run:

```powershell
python -m unittest tests.test_canvas_sets tests.test_canvases tests.test_undo tests.test_context -v
```

Expected: all atomic creation, rollback, redaction, and whole-set Undo tests pass.

---

### Task 3: Strict MCP Tool Registration and Server 2.1.0

**Files:**
- Create: `Fusion MCP Addin/tools/create_orthographic_canvas_set.py`
- Modify: `Fusion MCP Addin/tools/__init__.py`
- Modify: `Fusion MCP Addin/tools/get_fusion_status.py`
- Modify: `Fusion MCP Addin/fusion/context.py`
- Create: `tests/test_orthographic_canvas_set_tool.py`
- Modify: `tests/test_context.py`

**Interfaces:**
- Consumes: Task 2 `create_orthographic_canvas_set`.
- Produces: MCP tool `create_orthographic_canvas_set` with strict top-level and nested view schemas.
- Produces: status server version `2.1.0`; no design-context field changes.

- [ ] **Step 1: Write failing strict-schema and version tests**

Create `tests/test_orthographic_canvas_set_tool.py`:

```python
class OrthographicCanvasSetToolTests(unittest.TestCase):
    def test_schema_requires_name_and_two_to_three_strict_views(self):
        schema = tool.to_dict()["inputSchema"]
        self.assertEqual(["name", "views"], schema["required"])
        self.assertFalse(schema["additionalProperties"])
        views = schema["properties"]["views"]
        self.assertEqual(2, views["minItems"])
        self.assertEqual(3, views["maxItems"])
        self.assertEqual(["image_path", "plane", "width_expression"], views["items"]["required"])
        self.assertFalse(views["items"]["additionalProperties"])
        self.assertEqual(["xy", "xz", "yz"], views["items"]["properties"]["plane"]["enum"])
        self.assertEqual(0.25, schema["properties"]["dimension_tolerance_mm"]["default"])
```

Change the default status assertion in `tests/test_context.py` from `2.0.0` to `2.1.0`.

- [ ] **Step 2: Run schema/version tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_orthographic_canvas_set_tool tests.test_context.ContextTests.test_status_defaults_to_parameter_tool_server_version -v
```

Expected: missing tool module and version mismatch.

- [ ] **Step 3: Register the nested strict tool**

Use a thin handler forwarding all three arguments to Task 2. Define the `views` property with `type: array`, `minItems: 2`, `maxItems: 3`, and this nested object shape:

```python
{
    "type": "object",
    "properties": {
        "image_path": {"type": "string", "minLength": 1},
        "plane": {"type": "string", "enum": ["xy", "xz", "yz"]},
        "width_expression": {"type": "string", "minLength": 1},
        "center_x_expression": {"type": "string", "minLength": 1, "default": "0 mm"},
        "center_y_expression": {"type": "string", "minLength": 1, "default": "0 mm"},
        "opacity": {"type": "integer", "minimum": 0, "maximum": 100, "default": 50},
        "flip_horizontal": {"type": "boolean", "default": False},
        "flip_vertical": {"type": "boolean", "default": False},
    },
    "required": ["image_path", "plane", "width_expression"],
    "additionalProperties": False,
}
```

Set tolerance schema to `type: number`, `minimum: 0.001`, `maximum: 10.0`, `default: 0.25`. Call `.strict_schema()` for the top level and import the module in `tools/__init__.py`.

- [ ] **Step 4: Set version 2.1.0**

Change both:

```python
def get_status(app, server_version="2.1.0"):
```

and:

```python
SERVER_VERSION = "2.1.0"
```

Update the `get_design_context` description only if needed to say canvases may belong to an orthographic set; do not add output fields.

- [ ] **Step 5: Run Task 3 tests and confirm GREEN**

Run:

```powershell
python -m unittest tests.test_orthographic_canvas_set_tool tests.test_context tests.test_canvas_sets -v
```

Expected: strict schema, version, and batch behavior tests pass.

---

### Task 4: Progressive Skill, Documentation, Verification, Installation, and GitHub

**Files:**
- Modify: `skills/fusion/references/image-modeling.md`
- Modify: `README.md`
- Modify: `Fusion MCP Addin/README.md`
- Modify: `docs/live-validation.md`
- Copy after verification: repository `Fusion MCP Addin` to the installed Fusion add-in directory
- Copy after verification: repository `skills/fusion` to `%USERPROFILE%\.codex\skills\fusion`

**Interfaces:**
- Consumes: Tasks 1~3 and the approved spec.
- Produces: installed server 2.1.0, updated progressive image guidance, complete automated evidence, one pushed implementation commit, live evidence, and one pushed live-validation commit.

- [ ] **Step 1: Update only the image-modeling reference**

Add this routing rule to `skills/fusion/references/image-modeling.md`:

```markdown
- Use `create_reference_canvas` for one reference image.
- Use `create_orthographic_canvas_set` for 2–3 distinct orthographic views with at least one stated shared dimension.
- Before calling the set tool, map XY to X/Y, XZ to X/Z, and YZ to Y/Z. If Codex's extracted shared dimensions disagree, report the conflicting values instead of invoking Fusion.
```

Add verification guidance: compare numeric context first, then capture each supplied view, and use one Undo if any view or shared dimension is wrong. Do not expand the base `SKILL.md`.

- [ ] **Step 2: Update tool lists and pre-live status**

Document in both READMEs:

- 2~3 unique principal views
- shared-axis tolerance validation
- all-or-nothing creation and whole-set Undo
- no OCR, contour tracing, or full path disclosure

In `docs/live-validation.md`, add `Live orthographic canvas-set status: **not run; restart required for server 2.1.0**`. Do not change it to passed before live evidence exists. Update the automated test count only after running the full suite.

- [ ] **Step 3: Run fresh automated verification**

Run:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q "Fusion MCP Addin" scripts tests
git diff --check
python scripts/check_install.py --addon-path "Fusion MCP Addin"
```

Expected: all tests pass; compilation and whitespace checks exit zero; manifest/token checks pass. A running older Fusion server may still report its currently loaded version until restart, so record that as a live pending state rather than an automated failure.

- [ ] **Step 4: Validate the skill structure without adding dependencies**

Run:

```powershell
python "$env:USERPROFILE\.codex\skills\.system\skill-creator\scripts\quick_validate.py" skills\fusion
```

If it fails only because optional `PyYAML` is absent, do not install it. Manually verify valid `name: fusion` frontmatter and the existing `references/image-modeling.md` link, then record the environment limitation.

- [ ] **Step 5: Commit and push implementation**

```powershell
git add -- "Fusion MCP Addin" README.md docs/live-validation.md skills/fusion tests
git commit -m "feat: 다중 직교 캔버스 세트 MCP 업데이트"
git push origin docs/fusion360-codex-design
```

Expected: remote branch advances to the implementation commit. Do not merge or create a PR.

- [ ] **Step 6: Install verified files**

Copy without deleting unrelated installed files:

```powershell
$repoRoot = (Resolve-Path -LiteralPath ".").Path
$sourceAddin = Join-Path $repoRoot "Fusion MCP Addin"
$installedAddin = Join-Path $env:APPDATA "Autodesk\Autodesk Fusion 360\API\AddIns\Fusion MCP Addin"
$sourceSkill = Join-Path $repoRoot "skills\fusion"
$installedSkill = Join-Path $env:USERPROFILE ".codex\skills\fusion"
Copy-Item -Path "$sourceAddin\*" -Destination $installedAddin -Recurse -Force
Copy-Item -Path "$sourceSkill\*" -Destination $installedSkill -Recurse -Force
```

Verify installed hashes for `fusion/orthographic.py`, `fusion/canvas_sets.py`, `fusion/canvases.py`, `fusion/undo.py`, the new tool module, status version, and the image-modeling reference without printing secrets.

- [ ] **Step 7: Restart and verify server/tool discovery**

The user fully restarts Fusion, runs the add-in, and opens a new unsaved blank design. Call status and context. Expected: Fusion available, server `2.1.0`, active design true, zero canvases. Query the authenticated server tool catalog and confirm `create_orthographic_canvas_set` exists; an already-open Codex task may retain its earlier typed-tool cache, so distinguish server registration from client cache.

- [ ] **Step 8: Perform two-view live creation**

Resolve the existing non-sensitive `reference-plate-3x2.png` from the repository and use the same absolute runtime value for both views:

```powershell
$testImage = (Resolve-Path -LiteralPath "tests\assets\reference-plate-3x2.png").Path
$toolArguments = @{
    name = "Codex_Orthographic_Set_2_1"
    views = @(
        @{
            image_path = $testImage
            plane = "xy"
            width_expression = "100 mm"
            opacity = 50
        },
        @{
            image_path = $testImage
            plane = "xz"
            width_expression = "100 mm"
            opacity = 50
        }
    )
    dimension_tolerance_mm = 0.25
}
```

Pass `$toolArguments` as the arguments object for `create_orthographic_canvas_set`.

Confirm two canvases, shared X `100.0 mm`, both derived sizes `100.0 × 66.666671 mm`, centers `0.0, 0.0`, basename-only output, and one set checkpoint. Capture top and front screenshots; visually confirm each 3:2 outline is centered in its principal view.

- [ ] **Step 9: Verify whole-set Undo**

Call `undo_last_execution`, then context and top/front screenshots. Expected: response mode `canvas_set_deleted`, canvas count returns from two to zero, and both reference images disappear.

- [ ] **Step 10: Record and push live evidence**

Update `docs/live-validation.md` with Fusion/server versions, exact numeric results, shared-axis check, both screenshot observations, Undo count restoration, and remaining XZ/YZ three-view/real-distinct-drawing scope. Then run:

```powershell
python -m unittest discover -s tests -q
git diff --check
git add -- docs/live-validation.md
git commit -m "test: 다중 직교 캔버스 세트 라이브 검증 업데이트"
git push origin docs/fusion360-codex-design
git status --short --branch
git rev-parse HEAD
git rev-parse origin/docs/fusion360-codex-design
```

Expected: the full suite passes, the branch is clean, and local/remote hashes are identical.
