# Fusion 360 Reference Canvas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe explicit MCP tool that places a local dimensioned drawing on a principal Fusion construction plane at a calibrated physical width, then exposes enough context for Codex to model and compare against it.

**Architecture:** Codex performs multimodal interpretation of the attached drawing; the Fusion add-in only validates and inserts a local raster canvas. `fusion/canvases.py` owns file validation, transform calculation, transaction handling, audit redaction, and result serialization; the MCP tool module only defines the strict schema. Canvas summaries join the existing bounded design context, and detailed image-modeling guidance is progressively disclosed through a Fusion skill reference.

**Tech Stack:** Python 3, Autodesk Fusion 360 Python API (`Canvases`, `CanvasInput`, `Matrix2D`, `UnitsManager`), existing MCP primitives, `unittest`, existing fake Fusion objects.

**Spec:** `docs/superpowers/specs/2026-08-24-fusion360-reference-canvas-design.md`

## Global Constraints

- Server version becomes exactly `2.0.0`.
- Accept only existing absolute local `.png`, `.jpg`, `.jpeg`, `.tif`, or `.tiff` regular files of at most 25 MiB.
- Do not add Pillow, OCR, OpenCV, an external AI API, or any new runtime dependency.
- Never include the full image path or image bytes in MCP results, structured errors, or audit records.
- Preserve the image aspect ratio using the default `CanvasInput.transform` X/Y vector lengths.
- Support only principal `xy`, `xz`, and `yz` planes, uniform scaling by requested width, optional center offsets, opacity, and horizontal/vertical flips.
- Use the existing Fusion transaction, recompute, audit, checkpoint, and one-step Undo conventions.
- Keep the base Fusion skill short; load image-modeling instructions only for image or drawing requests.
- Implementation and live verification are separate Korean-named commits pushed to `docs/fusion360-codex-design`.

---

### Task 1: Canvas Core and Test Fakes

**Files:**
- Create: `Fusion MCP Addin/fusion/canvases.py`
- Modify: `tests/fakes.py`
- Create: `tests/test_canvases.py`

**Interfaces:**
- Consumes: `AuditLogger`, `MCPError`, `tool_success`, `record_checkpoint`, `safe_value`, `entity_token`, and `iter_collection` from existing modules.
- Produces: `create_reference_canvas(app, name, image_path, plane, width_expression, center_x_expression="0 mm", center_y_expression="0 mm", opacity=50, flip_horizontal=False, flip_vertical=False, matrix_factory=None, point_factory=None, vector_factory=None, audit_logger=None)`.
- Produces test doubles `FakeCanvas`, `FakeCanvasInput`, `FakeCanvases`, `FakeMatrix2D`, `FakePoint2D`, and `FakeVector2D` with the real method/property surface used by production.

- [ ] **Step 1: Extend test fakes with real canvas behavior**

Add focused test utilities whose matrices expose `getAsCoordinateSystem()` and `setWithCoordinateSystem(origin, x_dir, y_dir)`, whose vectors have a computed `length`, and whose canvas collection implements `itemByName`, `createInput`, and `add`. Extend `FakeComponent` with `canvases` while preserving every existing constructor call.

```python
class FakeVector2D:
    def __init__(self, x, y):
        self.x, self.y = x, y

    @property
    def length(self):
        return (self.x ** 2 + self.y ** 2) ** 0.5


class FakeMatrix2D:
    def __init__(self, origin=None, x_dir=None, y_dir=None):
        self.origin = origin or FakePoint2D(0.0, 0.0)
        self.x_dir = x_dir or FakeVector2D(2.0, 0.0)
        self.y_dir = y_dir or FakeVector2D(0.0, 1.0)

    def getAsCoordinateSystem(self):
        return self.origin, self.x_dir, self.y_dir

    def setWithCoordinateSystem(self, origin, x_dir, y_dir):
        self.origin, self.x_dir, self.y_dir = origin, x_dir, y_dir
        return True
```

- [ ] **Step 2: Write failing canvas behavior tests**

Create temporary image files with `Path.write_bytes(b"test-image")`; file contents need not be decoded because fake Fusion owns image handling. Test successful creation, aspect ratio, center, opacity, both flips, checkpoint creation, name conflict, validation failures, recompute rollback, and path redaction.

```python
def test_creates_calibrated_canvas_without_disclosing_full_path(self):
    result = self.create(width_expression="100 mm")
    payload = result["structuredContent"]
    self.assertEqual(100.0, payload["canvas"]["width_mm"])
    self.assertEqual(50.0, payload["canvas"]["height_mm"])
    self.assertEqual(self.image_path.name, payload["canvas"]["image_name"])
    self.assertNotIn(str(self.image_path.parent), repr(result))
    self.assertEqual("create_reference_canvas", get_last_checkpoint()["mutation"])


def test_rejects_relative_path_before_transaction(self):
    result = self.create(image_path="drawing.png")
    self.assertEqual("REFERENCE_IMAGE_PATH_INVALID", result["error"]["code"])
    self.assertEqual([], self.app.commands)
```

- [ ] **Step 3: Run the focused tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_canvases -v
```

Expected: import failure for `fusion_mcp_addin.fusion.canvases`.

- [ ] **Step 4: Implement validation and calibrated creation**

Implement helpers with no full path in returned details:

```python
_PLANES = {"xy", "xz", "yz"}
_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
_MAX_IMAGE_BYTES = 25 * 1024 * 1024


def _validated_image(path_text):
    if not isinstance(path_text, str) or not path_text.strip():
        raise _CanvasValidation("REFERENCE_IMAGE_PATH_INVALID", "image_path must be an absolute local path")
    candidate = Path(path_text)
    if not candidate.is_absolute() or "://" in path_text:
        raise _CanvasValidation("REFERENCE_IMAGE_PATH_INVALID", "image_path must be an absolute local path")
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        raise _CanvasValidation("REFERENCE_IMAGE_NOT_FOUND", "The reference image was not found.")
    if not resolved.is_file() or resolved.suffix.lower() not in _EXTENSIONS:
        raise _CanvasValidation("REFERENCE_IMAGE_PATH_INVALID", "Use a PNG, JPEG, or TIFF regular file.")
    if resolved.stat().st_size > _MAX_IMAGE_BYTES:
        raise _CanvasValidation("REFERENCE_IMAGE_TOO_LARGE", "The reference image exceeds 25 MiB.")
    return resolved
```

After `canvases.createInput(str(path), construction_plane)`, read the default transform and preserve its ratio:

```python
origin, default_x, default_y = canvas_input.transform.getAsCoordinateSystem()
aspect_ratio = float(default_x.length) / float(default_y.length)
width_cm = float(units.evaluateExpression(width_expression, target_unit))
height_cm = width_cm / aspect_ratio
x_sign = -1.0 if flip_horizontal else 1.0
y_sign = -1.0 if flip_vertical else 1.0
matrix = matrix_factory()
matrix.setWithCoordinateSystem(
    point_factory(center_x_cm, center_y_cm),
    vector_factory(x_sign * width_cm, 0.0),
    vector_factory(0.0, y_sign * height_cm),
)
canvas_input.transform = matrix
canvas_input.opacity = opacity
canvas_input.isSelectable = True
canvas_input.isDisplayedThrough = True
canvas_input.isRenderable = False
```

Wrap addition with `PTransaction.Start "Codex Reference Canvas"`, `design.computeAll()`, commit/abort, checkpoint, and local traceback auditing. The audit base payload contains `image_name` and `image_size_bytes`, never `image_path`.

- [ ] **Step 5: Run the focused tests and confirm GREEN**

Run:

```powershell
python -m unittest tests.test_canvases -v
```

Expected: all canvas tests pass with no traceback or warnings.

- [ ] **Step 6: Commit the core only if an intermediate checkpoint is needed**

The user requested one update commit, so keep this task staged locally and do not create a separate remote commit unless recovery requires an intermediate local checkpoint.

---

### Task 2: MCP Schema, Design Context, and Version 2.0.0

**Files:**
- Create: `Fusion MCP Addin/tools/create_reference_canvas.py`
- Modify: `Fusion MCP Addin/tools/__init__.py`
- Modify: `Fusion MCP Addin/fusion/context.py`
- Modify: `Fusion MCP Addin/tools/get_design_context.py`
- Modify: `Fusion MCP Addin/tools/get_fusion_status.py`
- Modify: `tests/test_context.py`
- Create: `tests/test_reference_canvas_tool.py`

**Interfaces:**
- Consumes: Task 1 `create_reference_canvas(...)`.
- Produces: MCP tool `create_reference_canvas` with eight strict properties and required `name`, `image_path`, `plane`, and `width_expression`.
- Produces: component context keys `canvas_count` and `canvases` without changing existing keys.

- [ ] **Step 1: Write failing strict-schema and context tests**

```python
def test_schema_requires_name_path_plane_and_width_and_is_strict(self):
    schema = tool.to_dict()["inputSchema"]
    self.assertEqual(
        ["name", "image_path", "plane", "width_expression"],
        schema["required"],
    )
    self.assertFalse(schema["additionalProperties"])
    self.assertEqual(["xy", "xz", "yz"], schema["properties"]["plane"]["enum"])


def test_context_returns_canvas_summary(self):
    context = build_design_context(self.app, scope="all", limit=20)
    component = context["components"][0]
    self.assertEqual(1, component["canvas_count"])
    self.assertEqual("front.png", component["canvases"][0]["image_name"])
    self.assertNotIn("C:\\", repr(component["canvases"]))
```

Update the default-version assertion from `1.9.0` to `2.0.0`.

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_reference_canvas_tool tests.test_context -v
```

Expected: missing tool module, missing canvas context fields, and version mismatch.

- [ ] **Step 3: Register the MCP tool**

Define a thin handler forwarding to Task 1 and a strict schema:

```python
def handler(
    name,
    image_path,
    plane,
    width_expression,
    center_x_expression="0 mm",
    center_y_expression="0 mm",
    opacity=50,
    flip_horizontal=False,
    flip_vertical=False,
):
    return create_reference_canvas(
        adsk.core.Application.get(),
        name,
        image_path,
        plane,
        width_expression,
        center_x_expression=center_x_expression,
        center_y_expression=center_y_expression,
        opacity=opacity,
        flip_horizontal=flip_horizontal,
        flip_vertical=flip_vertical,
    )
```

Use `minimum: 0`, `maximum: 100` for opacity, boolean schemas for flips, and defaults matching the spec. Import the module in `tools/__init__.py`.

- [ ] **Step 4: Serialize canvases in bounded context**

Add a private summary helper that extracts transform lengths and returns only the basename:

```python
def _canvas_summary(canvas):
    origin, x_dir, y_dir = safe_value(canvas, "transform").getAsCoordinateSystem()
    return {
        "name": safe_value(canvas, "name", ""),
        "entity_token": entity_token(canvas),
        "image_name": Path(str(safe_value(canvas, "imageFilename", ""))).name,
        "width_mm": round(float(x_dir.length) * 10.0, 6),
        "height_mm": round(float(y_dir.length) * 10.0, 6),
        "center_mm": [round(float(origin.x) * 10.0, 6), round(float(origin.y) * 10.0, 6)],
        "opacity": safe_value(canvas, "opacity", 50),
    }
```

Pass the existing `_Limiter` into `_component_summary`; consume one unit per canvas after bodies. Return `canvas_count` even when the list is truncated. Do not include canvases in `summary` unless components are already requested by the current scope rules.

- [ ] **Step 5: Set version 2.0.0 and update context description**

Change both `get_status(..., server_version="2.0.0")` and `SERVER_VERSION = "2.0.0"`. Update the design-context tool description to mention calibrated canvases.

- [ ] **Step 6: Run focused and full tests**

Run:

```powershell
python -m unittest tests.test_canvases tests.test_reference_canvas_tool tests.test_context -v
python -m unittest discover -s tests -v
```

Expected: focused tests pass, then the complete suite passes with zero failures.

---

### Task 3: Progressive Fusion Skill and User Documentation

**Files:**
- Create: `skills/fusion/references/image-modeling.md`
- Modify: `skills/fusion/SKILL.md`
- Modify: `README.md`
- Modify: `Fusion MCP Addin/README.md`
- Modify: `docs/live-validation.md`

**Interfaces:**
- Consumes: MCP tool and context contract from Tasks 1-2.
- Produces: one conditional skill reference loaded only for image/drawing work.
- Produces: documented server `2.0.0` feature and explicit unverified live status before restart.

- [ ] **Step 1: Add the conditional skill routing line**

Insert one concise rule after context inspection:

```markdown
For image- or drawing-based modeling, read [references/image-modeling.md](references/image-modeling.md) before interpreting the reference or changing Fusion.
```

Add a quick-reference row:

```markdown
| Image or drawing | status → image reference guide → all context → calibrated canvas → explicit tools → matching orthographic screenshots |
```

- [ ] **Step 2: Write the image-modeling reference**

The reference must require this sequence:

```markdown
1. Classify the attachment as a dimensioned drawing, orthographic render, photo, or silhouette.
2. Record only visible units, views, outer dimensions, centers, diameters, radii, repetition, and depth.
3. Separate stated dimensions from estimates and ask one question when a missing value changes 3D geometry.
4. Choose the primary orthographic view and place one calibrated canvas on the matching principal plane.
5. Prefer existing explicit Fusion tools and preserve feature names that describe the source view.
6. Compare numeric context first, then capture the matching top/front/right screenshot and compare proportions and placement.
7. Do not claim hidden, occluded, perspective-distorted, or dimensionless geometry is exact.
```

Include a plane mapping: top/plan → XY, front → XZ, right/side → YZ. State that image attachment availability and a Fusion-readable local path are separate requirements.

- [ ] **Step 3: Update README tool lists and data boundary**

Document `create_reference_canvas`, supported formats, calibrated width/aspect behavior, local-only path, and the fact that Codex—not the add-in—interprets the image. Do not promise automatic OCR or full photo reconstruction.

- [ ] **Step 4: Update live status without claiming a pass**

Add `Live calibrated reference-canvas status: not run; restart required for server 2.0.0`. Update the automated test count only after the actual full test run. Add reference canvases to remaining live scope until Fusion validation succeeds.

- [ ] **Step 5: Validate docs and skill structure**

Run:

```powershell
python "C:\Users\movingun\.codex\skills\.system\skill-creator\scripts\quick_validate.py" skills\fusion
git diff --check
```

If `quick_validate.py` cannot start because `PyYAML` is absent, record that environment limitation without installing a new dependency; manually verify the unchanged frontmatter and new reference link. `git diff --check` must still exit zero.

---

### Task 4: Verification, Installation, GitHub, and Live Fusion Validation

**Files:**
- Modify after live run: `docs/live-validation.md`
- Copy after automated verification: repository `Fusion MCP Addin` to the installed Fusion add-in directory
- Copy after automated verification: repository `skills/fusion` to `C:\Users\movingun\.codex\skills\fusion`
- Create for live validation: `tests/assets/reference-plate-3x2.png` by copying the existing non-sensitive `900 × 600` Fusion viewport image from `C:\Users\movingun\.codex\visualizations\2026\08\18\01a01371-1735-79a0-9700-d3ff30a54854\linear-pattern-after.png`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: installed server `2.0.0`, discovered `create_reference_canvas`, live numeric/visual/Undo evidence, and two pushed commits.

- [ ] **Step 1: Run fresh automated verification**

```powershell
python -m unittest discover -s tests -v
python -m compileall -q "Fusion MCP Addin" scripts tests
git diff --check
python scripts/check_install.py --addon-path "Fusion MCP Addin"
```

Expected: all tests pass, compilation and whitespace checks exit zero, manifest and token checks pass; the live health probe may still report the currently running older server until restart.

- [ ] **Step 2: Commit and push implementation**

```powershell
git add -- "Fusion MCP Addin" README.md docs/live-validation.md skills/fusion tests
git commit -m "feat: 이미지 도면 참조 캔버스 MCP 업데이트"
git push origin docs/fusion360-codex-design
```

Expected: remote branch advances to the implementation commit.

- [ ] **Step 3: Install verified files**

Copy source files recursively without deleting unrelated local files:

```powershell
$sourceAddin = "C:\Users\movingun\Documents\Codex\2026-08-18\superpowers-brainstorming-c-users-movingun-codex\outputs\FusionMCPSample\Fusion MCP Addin"
$installedAddin = "$env:APPDATA\Autodesk\Autodesk Fusion 360\API\AddIns\Fusion MCP Addin"
Copy-Item -Path "$sourceAddin\*" -Destination $installedAddin -Recurse -Force
Copy-Item -Path "C:\Users\movingun\Documents\Codex\2026-08-18\superpowers-brainstorming-c-users-movingun-codex\outputs\FusionMCPSample\skills\fusion\*" -Destination "C:\Users\movingun\.codex\skills\fusion" -Recurse -Force
```

Verify installed module, tool registration, server version, base skill link, and reference file with `Test-Path` and `Select-String` without printing secrets.

- [ ] **Step 4: Restart and verify tool discovery**

The user fully restarts Fusion and Codex, opens a new unsaved blank design, then Codex calls `get_fusion_status` and `get_design_context(scope="all")`. Expected: server `2.0.0`, active design true, `create_reference_canvas` present, zero starting canvases.

- [ ] **Step 5: Perform live calibrated-canvas validation**

Copy the verified `900 × 600` source image to `tests/assets/reference-plate-3x2.png`, confirm the copied SHA-256 equals the source SHA-256, then call:

```json
{
  "name": "Codex_Reference_Canvas_2_0",
  "image_path": "C:\\Users\\movingun\\Documents\\Codex\\2026-08-18\\superpowers-brainstorming-c-users-movingun-codex\\outputs\\FusionMCPSample\\tests\\assets\\reference-plate-3x2.png",
  "plane": "xy",
  "width_expression": "100 mm",
  "center_x_expression": "0 mm",
  "center_y_expression": "0 mm",
  "opacity": 50,
  "flip_horizontal": false,
  "flip_vertical": false
}
```

Confirm result width `100.0 mm`, derived height matching the known ratio, center `[0.0, 0.0]`, context canvas count increment, basename-only output, and a centered top screenshot with correct proportions.

- [ ] **Step 6: Verify Undo restoration**

Call `undo_last_execution`, then `get_design_context(scope="all")` and a top screenshot. Expected: canvas count returns to zero and the reference disappears.

- [ ] **Step 7: Record and push live evidence**

Change live status to passed, record Fusion/server versions, exact numeric results, screenshot observation, Undo result, and remaining unsupported scope. Then run:

```powershell
git diff --check
git add -- docs/live-validation.md
git commit -m "test: 이미지 도면 참조 캔버스 라이브 검증 업데이트"
git push origin docs/fusion360-codex-design
git status --short --branch
git rev-parse HEAD
git rev-parse origin/docs/fusion360-codex-design
```

Expected: clean synchronized branch and identical local/remote commit hashes.
