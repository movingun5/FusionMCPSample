# Fusion 360 Parametric Plate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one explicit `create_parametric_plate` MCP tool that atomically creates a centered rectangular plate, 0–32 parametrically positioned circular through-holes, and one optional vertical-edge fillet or chamfer from named Fusion user parameters.

**Architecture:** Keep request normalization and geometric checks in a pure `plate_geometry.py` module, isolate direct Fusion entity construction in `plate_builder.py`, and keep transaction, audit, checkpoint, rollback, and result translation in `parametric_plates.py`. The new MCP module is a strict thin adapter; existing individual sketch, extrusion, hole, fillet, and chamfer tools remain behaviorally unchanged.

**Tech Stack:** Python 3 standard library, Autodesk Fusion 360 `adsk.core`/`adsk.fusion`, the repository MCP primitives, `unittest`, local JSONL audit logging, PowerShell installation scripts.

**Spec:** `docs/superpowers/specs/2026-08-24-fusion360-parametric-plate-design.md`

## Global Constraints

- Target server version is exactly `2.2.0`; the authenticated tool catalog grows from 20 to 21 tools.
- User-facing dimensions are explicit Fusion expressions and evaluated results are reported in mm; Fusion API coordinates remain internal cm.
- `parameter_prefix` and every hole `key` match `[A-Za-z_][A-Za-z0-9_]*`; holes contain 0–32 strict objects.
- The component is centered on root XY at the origin and extrudes only in +Z; hole coordinates are signed from the plate center.
- Generated width, height, thickness, every hole X/Y/diameter, and optional edge size are named user parameters and drive the resulting features.
- The tool accepts no image bytes or paths; Codex performs image interpretation before calling the tool.
- All preflight checks finish before mutation; any write or recompute failure leaves no new component, feature, sketch, body, or user parameter.
- One successful call records one checkpoint and supports one whole-part Undo; native Fusion Undo/Redo is verified separately.
- Existing objects and existing user parameters are never overwritten or deleted.
- Do not add third-party dependencies, a general feature-recipe engine, OCR, slots, pockets, threaded holes, non-rectangular outlines, multiple bodies, or arbitrary placement.
- Keep the base `Fusion` skill concise; image-specific detail remains in `skills/fusion/references/image-modeling.md`.
- Implement sequentially without recurring plan/review pauses. Stop only for a real scope conflict, unsafe external change, failed rollback, or the required Fusion/Codex restart.
- Push each completed implementation milestone to `origin/docs/fusion360-codex-design` with a Korean commit message; do not merge `main` or create a PR.

## File Structure

- Create `Fusion MCP Addin/fusion/plate_geometry.py`: strict runtime normalization, parameter-name derivation, Fusion expression evaluation, bounds/overlap validation, and structured `PlateValidation` errors.
- Create `Fusion MCP Addin/fusion/plate_builder.py`: direct Fusion component, parameter, sketch, extrusion, hole, and edge-finish construction plus reverse-order cleanup.
- Create `Fusion MCP Addin/fusion/parametric_plates.py`: public atomic operation, transaction lifecycle, conflict checks, checkpoint, audit, structured result, and rollback verification.
- Create `Fusion MCP Addin/tools/create_parametric_plate.py`: strict nested MCP schema and main-thread handler.
- Modify `Fusion MCP Addin/tools/__init__.py`: register the 21st tool.
- Modify `Fusion MCP Addin/tools/get_fusion_status.py`: publish server `2.2.0`.
- Modify `Fusion MCP Addin/fusion/context.py`: make the default status version `2.2.0` without adding context fields.
- Modify `Fusion MCP Addin/fusion/undo.py`: prevalidate and remove the exact created occurrence and parameter set in one transaction.
- Modify `tests/fakes.py`: add occurrences, component features, circles, hole inputs, feature deletion, and failure injection needed by the real builder tests.
- Create `tests/test_plate_geometry.py`: pure request and geometry validation.
- Create `tests/test_plate_builder.py`: direct Fusion-builder wiring and cleanup behavior.
- Create `tests/test_parametric_plates.py`: transaction, checkpoint, audit, error mapping, rollback, and result behavior.
- Create `tests/test_parametric_plate_tool.py`: strict MCP schema and handler forwarding.
- Modify `tests/test_context.py`, `tests/test_undo.py`, `tests/test_live_acceptance.py`: version, whole-part Undo, and live harness behavior.
- Modify `scripts/live_acceptance.py`: replace the legacy arbitrary-Python plate creation step with `create_parametric_plate` and explicit parameter-update verification.
- Modify `README.md`, `Fusion MCP Addin/README.md`, `docs/live-validation.md`, `skills/fusion/SKILL.md`, and `skills/fusion/references/image-modeling.md`: tool contract, routing, pending/live evidence, and progressive image workflow.

---

### Task 1: Pure Plate Contract and Geometry Validation

**Files:**
- Create: `Fusion MCP Addin/fusion/plate_geometry.py`
- Create: `tests/test_plate_geometry.py`

**Interfaces:**
- Produces: `PlateValidation(code: str, message: str, details: dict | None)` with public `.code`, `.message`, and `.details`.
- Produces: `validate_plate_request(name, parameter_prefix, width_expression, height_expression, thickness_expression, holes=None, edge_finish=None) -> dict`.
- Produces: `generated_parameter_names(normalized: dict) -> dict` with keys `width`, `height`, `thickness`, `holes`, and optional `edge_size`.
- Produces: `all_parameter_names(evaluated: dict) -> list[str]` in deterministic creation order.
- Produces: `evaluate_plate_request(normalized: dict, units_manager) -> dict` containing `expressions`, `values_cm`, `values_mm`, `parameter_names`, normalized holes, and normalized edge finish.

- [ ] **Step 1: Write failing normalization and naming tests**

Create `tests/test_plate_geometry.py` with the real four-hole request:

```python
import unittest

import tests  # noqa: F401
from fusion_mcp_addin.fusion.plate_geometry import (
    PlateValidation,
    evaluate_plate_request,
    generated_parameter_names,
    validate_plate_request,
)
from tests.fakes import FakeUnitsManager


class PlateGeometryTests(unittest.TestCase):
    def request(self, **changes):
        request = {
            "name": "MountingPlate",
            "parameter_prefix": "plate",
            "width_expression": "100 mm",
            "height_expression": "60 mm",
            "thickness_expression": "5 mm",
            "holes": [
                {"key": "lower_left", "x_expression": "-40 mm", "y_expression": "-20 mm", "diameter_expression": "6 mm"},
                {"key": "upper_left", "x_expression": "-40 mm", "y_expression": "20 mm", "diameter_expression": "6 mm"},
                {"key": "lower_right", "x_expression": "40 mm", "y_expression": "-20 mm", "diameter_expression": "6 mm"},
                {"key": "upper_right", "x_expression": "40 mm", "y_expression": "20 mm", "diameter_expression": "6 mm"},
            ],
            "edge_finish": {"type": "fillet", "size_expression": "3 mm"},
        }
        request.update(changes)
        return request

    def test_normalizes_request_and_generates_every_parameter_name(self):
        normalized = validate_plate_request(**self.request())
        names = generated_parameter_names(normalized)
        self.assertEqual("plate_width", names["width"])
        self.assertEqual("plate_thickness", names["thickness"])
        self.assertEqual("plate_upper_left_x", names["holes"]["upper_left"]["x"])
        self.assertEqual("plate_upper_left_diameter", names["holes"]["upper_left"]["diameter"])
        self.assertEqual("plate_edge_size", names["edge_size"])
```

Add cases asserting `holes=None` becomes `[]`, `edge_finish=None` becomes `{"type": "none"}`, and the input dictionaries are not mutated.

- [ ] **Step 2: Run the focused test and confirm RED**

Run:

```powershell
python -m unittest tests.test_plate_geometry.PlateGeometryTests.test_normalizes_request_and_generates_every_parameter_name -v
```

Expected: import failure for `fusion_mcp_addin.fusion.plate_geometry`.

- [ ] **Step 3: Implement strict normalization and generated names**

Implement these constants and class:

```python
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
HOLE_KEYS = {"key", "x_expression", "y_expression", "diameter_expression"}
EDGE_KEYS = {
    "none": {"type"},
    "fillet": {"type", "size_expression"},
    "chamfer": {"type", "size_expression"},
}


class PlateValidation(ValueError):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
```

`validate_plate_request` must trim string values, reject control characters in `name`, reject unknown nested fields, enforce 0–32 holes, enforce unique safe keys, and require a non-empty `size_expression` only for `fillet`/`chamfer`. It returns fresh dictionaries and lists.

`generated_parameter_names` must return:

```python
{
    "width": f"{prefix}_width",
    "height": f"{prefix}_height",
    "thickness": f"{prefix}_thickness",
    "holes": {
        hole["key"]: {
            "x": f"{prefix}_{hole['key']}_x",
            "y": f"{prefix}_{hole['key']}_y",
            "diameter": f"{prefix}_{hole['key']}_diameter",
        }
        for hole in holes
    },
    **({"edge_size": f"{prefix}_edge_size"} if edge_type != "none" else {}),
}
```

- [ ] **Step 4: Write failing expression, boundary, and overlap tests**

Add these assertions using `FakeUnitsManager`:

```python
def code_for(self, **changes):
    with self.assertRaises(PlateValidation) as caught:
        normalized = validate_plate_request(**self.request(**changes))
        evaluate_plate_request(normalized, FakeUnitsManager())
    return caught.exception.code

def test_rejects_hole_that_touches_plate_boundary(self):
    holes = [{"key": "edge", "x_expression": "47 mm", "y_expression": "0 mm", "diameter_expression": "6 mm"}]
    self.assertEqual("PLATE_HOLE_OUT_OF_BOUNDS", self.code_for(holes=holes))

def test_rejects_touching_holes(self):
    holes = [
        {"key": "a", "x_expression": "0 mm", "y_expression": "0 mm", "diameter_expression": "6 mm"},
        {"key": "b", "x_expression": "6 mm", "y_expression": "0 mm", "diameter_expression": "6 mm"},
    ]
    self.assertEqual("PLATE_HOLES_OVERLAP", self.code_for(holes=holes))
```

Also cover invalid Fusion expressions, non-length units, non-positive width/height/thickness/diameter/edge size, `size >= min(width, height) / 2`, 32-hole success, 33-hole rejection, invalid prefix/key, duplicate key, unknown fields, and `none` with a size.

- [ ] **Step 5: Run validation tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_plate_geometry -v
```

Expected: naming tests pass; evaluation and geometry tests fail because `evaluate_plate_request` is incomplete.

- [ ] **Step 6: Implement evaluation and geometric preflight**

Evaluate every expression with `parse_length_expression(expression, units_manager)` so values are internal cm. Preserve original expressions and expose rounded mm values separately. Apply strict containment and non-overlap with an internal tolerance of `1e-9` cm:

```python
radius = hole["diameter_cm"] / 2.0
if abs(hole["x_cm"]) + radius >= width_cm / 2.0 - 1e-9:
    raise PlateValidation(
        "PLATE_HOLE_OUT_OF_BOUNDS",
        "Every circular hole must remain strictly inside the rectangular plate.",
        {"key": hole["key"]},
    )
if math.hypot(left["x_cm"] - right["x_cm"], left["y_cm"] - right["y_cm"]) <= left_radius + right_radius + 1e-9:
    raise PlateValidation(
        "PLATE_HOLES_OVERLAP",
        "Circular holes must not overlap or touch.",
        {"keys": [left["key"], right["key"]]},
    )
```

Raise `PLATE_EXPRESSION_INVALID` with only the field and safe expression, and `PLATE_DIMENSION_INVALID` with evaluated mm values. Implement `all_parameter_names` by flattening width, height, thickness, each hole's X/Y/diameter in request order, and the optional edge size. Do not import `adsk` in this module.

- [ ] **Step 7: Run Task 1 tests and confirm GREEN**

Run:

```powershell
python -m unittest tests.test_plate_geometry tests.test_units -v
```

Expected: all pure validation and existing unit-conversion tests pass.

- [ ] **Step 8: Commit and push Task 1**

```powershell
git add -- "Fusion MCP Addin/fusion/plate_geometry.py" tests/test_plate_geometry.py
git commit -m "feat: 파라메트릭 판 치수 검증 업데이트"
git push origin docs/fusion360-codex-design
```

---

### Task 2: Fusion Plate Builder and Reverse Cleanup

**Files:**
- Create: `Fusion MCP Addin/fusion/plate_builder.py`
- Modify: `tests/fakes.py:1-415`
- Create: `tests/test_plate_builder.py`

**Interfaces:**
- Consumes: Task 1 evaluated request dictionary.
- Produces: `FusionPlateBuilder(design, root, *, point_factory=None, matrix_factory=None, value_input_factory=None, dimension_orientations=None, new_body_operation=None, object_collection_factory=None)`.
- Produces: `builder.build(name: str, evaluated: dict) -> dict` containing `occurrence`, `component`, `body`, `profile_sketch`, `profile_dimensions`, `hole_sketch`, `extrusion`, `hole_features`, `hole_inputs`, `edge_feature`, `edge_size_input`, and `parameters`.
- Produces: `builder.rollback() -> dict` containing `clean`, `deleted_occurrence`, `deleted_parameters`, and `errors`.
- Produces: `PlateBuildFailure(stage: str, code: str, message: str)`.

- [ ] **Step 1: Confirm the unfamiliar component API before coding**

With Fusion running, call:

```text
get_api_documentation(search_term="Occurrences.addNewComponent Matrix3D", category="all")
```

Confirm the project pattern is `root.occurrences.addNewComponent(adsk.core.Matrix3D.create())` and the returned occurrence exposes `.component`. If the installed API differs, update only the adapter method and record the exact installed signature in the implementation commit message body.

- [ ] **Step 2: Extend fakes for a real builder test**

Add deletion-aware `FakeOccurrences`, component feature collections, extrusion bodies, simple-hole inputs, fillet/chamfer edge sets, and one-based `fail_at` injection. The central occurrence fake must follow this shape:

```python
class FakeOccurrence:
    def __init__(self, component, token, collection):
        self.component = component
        self.entityToken = token
        self._collection = collection
        self.deleted = False

    def deleteMe(self):
        self.deleted = True
        return True


class FakeOccurrences(FakeCollection):
    def addNewComponent(self, _matrix):
        component = FakeComponent("Component", f"component-{len(self._items) + 1}")
        occurrence = FakeOccurrence(component, f"occurrence-{len(self._items) + 1}", self)
        self._items.append(occurrence)
        return occurrence
```

Make `FakeDesign.allComponents` include non-deleted occurrence components and make count-oriented collections ignore deleted entities. Extend `FakeUserParameters` with `fail_add_at` and expression-to-cm values so rollback count checks are meaningful.

- [ ] **Step 3: Write the failing four-hole builder test**

Create `tests/test_plate_builder.py`. Evaluate the Task 1 request, build with fake factories, then assert exact dependencies:

```python
result = builder.build("MountingPlate", evaluated)
self.assertEqual("MountingPlate", result["component"].name)
self.assertEqual("MountingPlate", result["body"].name)
self.assertEqual("MountingPlate_Profile", result["profile_sketch"].name)
self.assertEqual("plate_width", result["profile_dimensions"]["width"].parameter.expression)
self.assertEqual("plate_height", result["profile_dimensions"]["height"].parameter.expression)
self.assertEqual("plate_thickness", result["extrusion"].distance)
self.assertEqual(4, len(result["hole_features"]))
self.assertEqual("plate_upper_left_diameter", result["hole_inputs"]["upper_left"].diameter)
self.assertEqual("plate_thickness", result["hole_inputs"]["upper_left"].distance)
self.assertEqual("MountingPlate_Fillet", result["edge_feature"].name)
self.assertEqual("plate_edge_size", result["edge_size_input"])
```

Assert the single hidden placement sketch is named `MountingPlate_Holes`, every hole feature follows `<name>_<key>_Hole`, all hole position dimensions reference the generated X/Y parameter names, and only four vertical outer edges enter the fillet collection.

- [ ] **Step 4: Run the builder test and confirm RED**

Run:

```powershell
python -m unittest tests.test_plate_builder.PlateBuilderTests.test_builds_named_parameter_driven_four_hole_fillet_plate -v
```

Expected: import failure for `fusion_mcp_addin.fusion.plate_builder`.

- [ ] **Step 5: Implement the direct Fusion builder**

Implement `FusionPlateBuilder` without starting transactions, recomputing, auditing, or recording checkpoints. Resolve real factories lazily so unit tests do not import `adsk`:

```python
def _resolve_factories(self):
    if all(self._factories_are_set()):
        return
    import adsk.core
    import adsk.fusion
    self.point_factory = self.point_factory or adsk.core.Point3D.create
    self.matrix_factory = self.matrix_factory or adsk.core.Matrix3D.create
    self.value_input_factory = self.value_input_factory or adsk.core.ValueInput.createByString
    self.new_body_operation = self.new_body_operation or adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    self.object_collection_factory = self.object_collection_factory or adsk.core.ObjectCollection.create
```

Build in this exact order:

1. Create and name the occurrence/component at root identity transform.
2. Add every user parameter with unit `mm`, the original expression, and comment `create_parametric_plate:<name>`.
3. Add a center-point rectangle on the new component XY plane; dimension its selected horizontal/vertical lines with `<prefix>_width` and `<prefix>_height`.
4. Extrude the largest profile with `<prefix>_thickness` using new-body operation; name the feature/body.
5. Find the body planar +Z top face, add one hidden `<name>_Holes` sketch, add one sketch point per hole, and constrain its X/Y position with the generated parameter names. Reuse the current `holes._positive_dimension_expression` behavior so negative initial quadrants produce positive driving distances.
6. Create one simple distance-extent hole feature per sketch point with diameter `<prefix>_<key>_diameter`, depth `<prefix>_thickness`, and `participantBodies = [body]`.
7. For `fillet` or `chamfer`, select only the four straight vertical outer edges using the existing bounding-box selector logic; create one named edge feature driven by `<prefix>_edge_size`.

Each method raises `PlateBuildFailure` with its exact stage and design error code. Store every created parameter and the occurrence immediately after creation so `rollback()` can always delete the occurrence first and then parameters in reverse order.

- [ ] **Step 6: Add builder failure and cleanup tests**

Cover failures at component, parameter N, profile sketch, extrusion, hole N, fillet/chamfer, and missing vertical edges. For each failure call `rollback()` and assert:

```python
self.assertTrue(rollback["clean"])
self.assertEqual(0, self.root.occurrences.count)
self.assertEqual(0, self.design.userParameters.count)
```

Also test `edge_finish=none`, chamfer selection, zero-coordinate constraints, negative-coordinate expressions, no-hole plate, and cleanup idempotence.

- [ ] **Step 7: Run builder and existing primitive regressions**

Run:

```powershell
python -m unittest tests.test_plate_builder tests.test_sketches tests.test_extrusions tests.test_holes tests.test_fillets tests.test_chamfers -v
```

Expected: the new builder tests and all unchanged individual-tool tests pass.

- [ ] **Step 8: Commit and push Task 2**

```powershell
git add -- "Fusion MCP Addin/fusion/plate_builder.py" tests/fakes.py tests/test_plate_builder.py
git commit -m "feat: 파라메트릭 판 Fusion 빌더 업데이트"
git push origin docs/fusion360-codex-design
```

---

### Task 3: Atomic Operation, Checkpoint, and Whole-Part Undo

**Files:**
- Create: `Fusion MCP Addin/fusion/parametric_plates.py`
- Modify: `Fusion MCP Addin/fusion/undo.py:1-220`
- Create: `tests/test_parametric_plates.py`
- Modify: `tests/test_undo.py:1-150`

**Interfaces:**
- Consumes: Task 1 validation/evaluation and Task 2 `FusionPlateBuilder`.
- Produces: `create_parametric_plate(app, name, parameter_prefix, width_expression, height_expression, thickness_expression, holes=None, edge_finish=None, *, builder_factory=FusionPlateBuilder, audit_logger=None) -> dict`.
- Extends checkpoint mutation `create_parametric_plate` with `occurrence_entity_token`, `component_entity_token`, `parameter_names`, `starting_counts`, and `created_counts`.
- Extends Undo result with `undo_mode="parametric_plate_deleted"` and restored counts.

- [ ] **Step 1: Write failing atomic success, preflight, and rollback tests**

Create `tests/test_parametric_plates.py` with a `RecordingPlateBuilder` that exposes each build stage and can fail a named stage. Assert the success path starts and commits exactly one transaction, computes once, records one checkpoint, and returns the approved result fields:

```python
self.assertEqual(
    ['PTransaction.Start "Create Parametric Plate"', "PTransaction.Commit"],
    self.app.commands,
)
self.assertEqual("create_parametric_plate", get_last_checkpoint()["mutation"])
self.assertEqual([100.0, 60.0, 5.0], [
    content["dimensions_mm"]["width"],
    content["dimensions_mm"]["height"],
    content["dimensions_mm"]["thickness"],
])
self.assertEqual(4, len(content["holes"]))
self.assertEqual({"type": "fillet", "size_mm": 3.0}, content["edge_finish"])
```

Add tests proving invalid geometry and any existing generated parameter name return before transaction/builder construction. Assert `PLATE_PARAMETER_CONFLICT` details list every collision but do not change the existing parameter.

Inject failures for every builder stage and recompute. Assert `PTransaction.Abort`, `builder.rollback()` called, count deltas all zero, no new checkpoint, error stage preserved, and the audit file alone contains `local_traceback`.

- [ ] **Step 2: Run atomic tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_parametric_plates -v
```

Expected: import failure for `fusion_mcp_addin.fusion.parametric_plates`.

- [ ] **Step 3: Implement the public atomic operation**

Follow this mutation boundary:

```python
normalized = validate_plate_request(
    name,
    parameter_prefix,
    width_expression,
    height_expression,
    thickness_expression,
    holes=holes,
    edge_finish=edge_finish,
)
evaluated = evaluate_plate_request(normalized, design.unitsManager)
collisions = [name for name in all_parameter_names(evaluated) if design.userParameters.itemByName(name)]
if collisions:
    return _error(
        "PLATE_PARAMETER_CONFLICT",
        "One or more generated user parameter names already exist.",
        details={"names": sorted(collisions)},
    )

before = capture_snapshot(design)
app.executeTextCommand('PTransaction.Start "Create Parametric Plate"')
created = builder.build(name, evaluated)
if design.computeAll() is False:
    raise _RecomputeFailure("Fusion could not recompute the parametric plate.")
after = capture_snapshot(design)
comparison = compare_snapshots(before, after, expected={"components_created": 1, "bodies_created": 1})
if not comparison["expectations_met"]:
    raise PlateBuildFailure(
        "verification",
        "PLATE_VERIFICATION_FAILED",
        "; ".join(comparison["mismatches"]),
    )
app.executeTextCommand("PTransaction.Commit")
```

Define private `_RecomputeFailure(RuntimeError)` in this module. Capture the document/timeline and collection counts before mutation. On any exception, abort first, call `builder.rollback()` defensively, recompute, recapture counts, and return `ROLLBACK_FAILED` if any created occurrence or generated parameter remains. Otherwise map `PlateBuildFailure.code`; map recompute to `RECOMPUTE_FAILED`.

Record the checkpoint only after commit. Build the success response from safe summaries using `body_summary`, evaluated mm values, feature names/tokens, parameter names/expressions, `recomputed=True`, `checkpoint_recorded=True`, and `undo_label="Create Parametric Plate"`.

Audit only request ID, mutation, component name, prefix, hole count, evaluated dimension summary, edge type, before/after counts, result, and duration. Keep traceback local to error audit.

- [ ] **Step 4: Write failing exact-target Undo tests**

Extend `tests/test_undo.py` with a root occurrence, its component token, and the exact generated parameters. Assert one call deletes the occurrence before parameters, uses one transaction, recomputes, and restores checkpoint counts:

```python
self.assertEqual("parametric_plate_deleted", result["undo_mode"])
self.assertEqual(0, self.root.occurrences.count)
self.assertEqual(0, self.design.userParameters.count)
self.assertEqual(
    ['PTransaction.Start "Codex Undo Parametric Plate"', "PTransaction.Commit"],
    self.app.commands,
)
```

Add separate cases for wrong component token, missing occurrence, one missing parameter, duplicate resolution, wrong document, deletion failure, recompute failure, and count mismatch. Every prevalidation failure must leave all targets unchanged and start no transaction.

- [ ] **Step 5: Run Undo tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_undo -v
```

Expected: new plate-checkpoint cases fall through to generic `UndoCommand`.

- [ ] **Step 6: Implement prevalidated whole-part Undo**

Add `_undo_parametric_plate` before generic Undo routing. Resolve the root occurrence by token, confirm its component token, resolve every named user parameter, and reject the entire call if any exact target is missing. Then:

```python
app.executeTextCommand('PTransaction.Start "Codex Undo Parametric Plate"')
if occurrence.deleteMe() is False:
    raise RuntimeError("Fusion rejected the plate occurrence deletion.")
for parameter in reversed(parameters):
    if parameter.deleteMe() is False:
        raise RuntimeError("Fusion rejected a generated parameter deletion.")
if design.computeAll() is False:
    raise RuntimeError("Fusion could not recompute after deleting the plate.")
app.executeTextCommand("PTransaction.Commit")
```

Verify component/body/sketch/feature/user-parameter counts match `starting_counts`. Abort on failure and return a structured retryable error. Route `mutation == "create_parametric_plate"` before the canvas branches.

- [ ] **Step 7: Run Task 3 and regression tests**

Run:

```powershell
python -m unittest tests.test_parametric_plates tests.test_undo tests.test_checkpoints tests.test_snapshot tests.test_parameters -v
```

Expected: atomic creation, defensive rollback, exact Undo, and existing checkpoint behavior all pass.

- [ ] **Step 8: Commit and push Task 3**

```powershell
git add -- "Fusion MCP Addin/fusion/parametric_plates.py" "Fusion MCP Addin/fusion/undo.py" tests/test_parametric_plates.py tests/test_undo.py
git commit -m "feat: 파라메트릭 판 원자 생성과 Undo 업데이트"
git push origin docs/fusion360-codex-design
```

---

### Task 4: Strict MCP Tool, Server 2.2.0, Skill, and Automated Acceptance

**Files:**
- Create: `Fusion MCP Addin/tools/create_parametric_plate.py`
- Modify: `Fusion MCP Addin/tools/__init__.py:1-25`
- Modify: `Fusion MCP Addin/tools/get_fusion_status.py:1-20`
- Modify: `Fusion MCP Addin/fusion/context.py`
- Create: `tests/test_parametric_plate_tool.py`
- Modify: `tests/test_context.py:45-60`
- Modify: `scripts/live_acceptance.py`
- Modify: `tests/test_live_acceptance.py`
- Modify: `README.md`
- Modify: `Fusion MCP Addin/README.md`
- Modify: `skills/fusion/SKILL.md`
- Modify: `skills/fusion/references/image-modeling.md`
- Modify: `docs/live-validation.md`

**Interfaces:**
- Consumes: Task 3 `create_parametric_plate`.
- Produces: strict main-thread MCP tool `create_parametric_plate`.
- Produces: status server version `2.2.0` and 21-tool catalog.
- Produces: acceptance harness that calls the explicit tool and verifies a parameter-driven edit.

- [ ] **Step 1: Write failing strict-schema and version tests**

Create `tests/test_parametric_plate_tool.py` and assert:

```python
schema = tool.to_dict()["inputSchema"]
self.assertEqual(
    ["name", "parameter_prefix", "width_expression", "height_expression", "thickness_expression"],
    schema["required"],
)
self.assertFalse(schema["additionalProperties"])
self.assertEqual(0, schema["properties"]["holes"]["minItems"])
self.assertEqual(32, schema["properties"]["holes"]["maxItems"])
self.assertFalse(schema["properties"]["holes"]["items"]["additionalProperties"])
self.assertEqual(3, len(schema["properties"]["edge_finish"]["oneOf"]))
```

Assert the handler forwards all inputs unchanged. Change the status assertion in `tests/test_context.py` from `2.1.0` to `2.2.0`. Add a registry test that imports `fusion_mcp_addin.tools`, lists registered tool names, asserts exactly 21 unique names, and includes `create_parametric_plate`.

- [ ] **Step 2: Run schema/version tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_parametric_plate_tool tests.test_context -v
```

Expected: missing tool module and server-version mismatch.

- [ ] **Step 3: Add the strict tool and register version 2.2.0**

Define strict `_HOLE_SCHEMA` with required `key`, `x_expression`, `y_expression`, `diameter_expression`; define `edge_finish.oneOf` as three strict objects for `none`, `fillet`, and `chamfer`. Use defaults `holes=[]` and `edge_finish={"type": "none"}` in JSON schema while using `None` in the Python handler to avoid shared mutable defaults.

The handler must be only:

```python
def handler(name, parameter_prefix, width_expression, height_expression, thickness_expression, holes=None, edge_finish=None):
    return create_parametric_plate(
        adsk.core.Application.get(),
        name,
        parameter_prefix,
        width_expression,
        height_expression,
        thickness_expression,
        holes=holes,
        edge_finish=edge_finish,
    )
```

Import the module from `tools/__init__.py`, set `SERVER_VERSION = "2.2.0"`, and change `get_status(app, server_version="2.2.0")` in `fusion/context.py`. Do not add design-context fields.

- [ ] **Step 4: Replace arbitrary-Python plate creation in the acceptance harness**

Replace `build_mounting_plate_code()` with `build_parametric_plate_arguments()` returning the approved four-hole request. Add `create_parametric_plate` and `upsert_user_parameter` to `REQUIRED_TOOLS`.

In `run_acceptance`, call `create_parametric_plate`, then `get_design_context`; find `MountingPlate`, verify `size_mm == [100.0, 60.0, 5.0]`, parameter names exist, and no failed features exist. Update `plate_width` using:

```python
client.tool(
    "upsert_user_parameter",
    {
        "name": "plate_width",
        "expression": "120 mm",
        "expected_old_expression": "100 mm",
        "comment": "create_parametric_plate:MountingPlate",
    },
)
```

Call context again and require the body X size to become `120.0 mm` while Y/Z remain `60.0/5.0`. Keep screenshot and export checks. Use a separate invalid `create_parametric_plate` request with an out-of-bounds hole for error-isolation evidence instead of dividing by zero in arbitrary Python.

Update `tests/test_live_acceptance.py` to assert the argument object contains four holes, the fillet, all named dimensions, and no Python code string. Keep base64 redaction tests.

- [ ] **Step 5: Update the progressive Fusion skill and documentation**

Add one concise base-skill routing line:

```markdown
For a new rectangular plate, bracket base, or mounting plate with circular through-holes and one optional outer fillet/chamfer, prefer `create_parametric_plate`; provide a safe parameter prefix and explicit expressions for every dimension.
```

Add a Quick Reference row `Parametric plate | status → context → create parametric plate → context → orthographic screenshots`.

In `image-modeling.md`, route a dimensioned rectangular plate to `create_parametric_plate` after canvas/shared-dimension verification and state that the tool receives only structured dimensions. Update both READMEs with the complete parameter names, centered XY coordinate convention, 0–32 holes, one edge finish, all-or-nothing behavior, and exclusions.

Add a `2.2.0 parametric plate` section to `docs/live-validation.md` marked **not run; Fusion and Codex restart required**. Do not claim live geometry, Undo, Redo, or parameter propagation passed yet.

- [ ] **Step 6: Run complete automated verification**

Run:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q "Fusion MCP Addin" scripts tests
git diff --check
python scripts/check_install.py --addon-path "Fusion MCP Addin" --skip-server
python "$env:USERPROFILE\.codex\skills\.system\skill-creator\scripts\quick_validate.py" skills\fusion
```

Expected: all tests, compilation, whitespace, manifest, and skill checks pass. If `quick_validate.py` fails only because optional `PyYAML` is unavailable, do not install it; verify `name: fusion`, the referenced file path, and YAML indentation manually and record only that environment limitation.

- [ ] **Step 7: Check secrets and final implementation scope**

Run:

```powershell
rg -n "FUSION_MCP_TOKEN|Authorization|Bearer " --glob "!docs/superpowers/**" --glob "!tests/**"
git diff --stat HEAD~1
git status --short
```

Expected: no token value is present; legitimate environment-variable and header-name references contain no credential. The diff contains only the files listed in Tasks 1–4.

- [ ] **Step 8: Commit and push Task 4**

```powershell
git add -- "Fusion MCP Addin" README.md docs/live-validation.md scripts/live_acceptance.py skills/fusion tests
git commit -m "feat: 파라메트릭 판 부품 MCP 업데이트"
git push origin docs/fusion360-codex-design
```

Do not merge or create a PR.

---

### Task 5: Install, Restart, and Live Fusion Verification

**Files:**
- Copy after automated verification: repository `Fusion MCP Addin` into `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\Fusion MCP Addin`
- Copy after automated verification: repository `skills/fusion` into `%USERPROFILE%\.codex\skills\fusion`
- Modify after live evidence: `docs/live-validation.md`

**Interfaces:**
- Consumes: verified Task 4 repository files and the installed local MCP token without printing it.
- Produces: installed server `2.2.0`, discoverable `create_parametric_plate`, live parametric geometry evidence, failure atomicity, one Undo/Redo result, and a pushed validation commit.

- [ ] **Step 1: Install only the verified add-in and skill files**

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

Compare SHA-256 hashes for `fusion/plate_geometry.py`, `fusion/plate_builder.py`, `fusion/parametric_plates.py`, `fusion/undo.py`, `tools/create_parametric_plate.py`, `tools/get_fusion_status.py`, `skills/fusion/SKILL.md`, and `skills/fusion/references/image-modeling.md`. Do not print environment variables or tokens.

- [ ] **Step 2: Pause once for the required full restart**

Ask the user to fully quit and restart Fusion and Codex, run the `Fusion MCP Addin`, and open a new unsaved blank design. This is the only planned execution pause.

- [ ] **Step 3: Verify server and tool discovery**

Call authenticated `initialize`, `tools/list`, `get_fusion_status`, and `get_design_context`. Require server `2.2.0`, 21 unique tools including `create_parametric_plate`, an active blank design, and no pre-existing `plate_*` user parameters. If the current Codex task retains an older typed-tool cache, use the authenticated raw MCP `tools/call` path and distinguish server registration from client cache.

- [ ] **Step 4: Create and inspect the approved plate**

Call `create_parametric_plate` with:

```json
{
  "name": "MountingPlate",
  "parameter_prefix": "plate",
  "width_expression": "100 mm",
  "height_expression": "60 mm",
  "thickness_expression": "5 mm",
  "holes": [
    {"key": "lower_left", "x_expression": "-40 mm", "y_expression": "-20 mm", "diameter_expression": "6 mm"},
    {"key": "upper_left", "x_expression": "-40 mm", "y_expression": "20 mm", "diameter_expression": "6 mm"},
    {"key": "lower_right", "x_expression": "40 mm", "y_expression": "-20 mm", "diameter_expression": "6 mm"},
    {"key": "upper_right", "x_expression": "40 mm", "y_expression": "20 mm", "diameter_expression": "6 mm"}
  ],
  "edge_finish": {"type": "fillet", "size_expression": "3 mm"}
}
```

Require one new component, one solid body, body bounds `100 × 60 × 5 mm` within `0.01 mm`, four named healthy hole features, one healthy fillet feature, no failed features, and every expected user parameter/expression.

- [ ] **Step 5: Verify numeric and visual geometry**

Capture top, front, and isometric screenshots. Numerically inspect hole center points, diameter model parameters, and distance extents; require centers `(±40, ±20) mm`, diameter `6 mm`, and depth `5 mm`. Confirm visually that four holes are symmetric and only the four outer vertical corners are rounded.

- [ ] **Step 6: Verify parameter propagation in a separate retained model**

Use `upsert_user_parameter` with optimistic concurrency to change:

```text
plate_width: 100 mm → 120 mm
plate_upper_left_x: -40 mm → -50 mm
plate_upper_left_diameter: 6 mm → 8 mm
plate_edge_size: 3 mm → 4 mm
```

After each update, require a clean recompute and no failed features. Confirm body X size `120 mm`, the upper-left center X `-50 mm`, its diameter `8 mm`, and vertical fillet radius `4 mm`; capture a new top and isometric screenshot.

- [ ] **Step 7: Verify failure atomicity in a second blank design**

Open a second blank design and submit the same request with one hole at `x_expression="49 mm"`. Require `PLATE_HOLE_OUT_OF_BOUNDS`, no transaction start, and zero component/body/sketch/feature/user-parameter deltas.

Then inject no artificial Fusion failure in production. Mid-stage rollback remains automated-test evidence unless a naturally safe live failure can be produced without risking the open document.

- [ ] **Step 8: Verify whole-part Undo and Redo in a third blank design**

Open a third blank design, create the unchanged baseline model, and immediately call `undo_last_execution`. Require `undo_mode="parametric_plate_deleted"`, all generated component and parameter counts restored, and an empty top/isometric view. Invoke Fusion Redo once and require the component, body, features, and user parameters to return with baseline values.

- [ ] **Step 9: Record live evidence and rerun verification**

Replace only the pending `2.2.0` section in `docs/live-validation.md` with the exact Fusion/server versions, 21-tool catalog evidence, automated test count, measured body and hole values, parameter-update results, screenshot observations, invalid-request deltas, Undo/Redo results, and any client-cache limitation.

Run:

```powershell
python -m unittest discover -s tests -q
python -m compileall -q "Fusion MCP Addin" scripts tests
git diff --check
git status --short
```

Expected: full suite and compilation pass; only `docs/live-validation.md` is changed.

- [ ] **Step 10: Commit and push live validation**

```powershell
git add -- docs/live-validation.md
git commit -m "test: 파라메트릭 판 부품 라이브 검증 업데이트"
git push origin docs/fusion360-codex-design
git status --short --branch
git rev-parse HEAD
git rev-parse origin/docs/fusion360-codex-design
```

Expected: clean branch and identical local/remote hashes. Do not merge `main` or create a PR.
