# Live Fusion validation status

- Date: 2026-08-24
- Automated environment: Windows, Python 3.14, Fusion API replaced by test fakes
- Live Fusion user-parameter status: **passed on Fusion 2704.1.53**
- Live rectangle-sketch status: **passed on Fusion 2704.1.53**
- Live new-body extrusion status: **passed on Fusion 2704.1.53**
- Live simple-hole status: **passed on Fusion 2704.1.53**
- Live constant-radius fillet status: **passed on Fusion 2704.1.53**
- Live equal-distance chamfer status: **passed on Fusion 2704.1.53**
- Live single-direction feature-pattern status: **passed on Fusion 2704.1.53**
- Live feature-owned model-parameter update status: **passed on Fusion 2704.1.53**
- Live calibrated reference-canvas status: **passed on Fusion 2704.1.53 with server 2.0.0**
- Live orthographic canvas-set status: **passed on Fusion 2704.1.53 with server 2.1.0**
- ChatGPT desktop Codex to authenticated local MCP status: **passed**
- Phase-1 mounting-plate geometry acceptance: **not run**

## Automated evidence

The repository test suite covers policy classification, audit redaction, bearer authentication, authenticated HTTP initialization, design context, snapshots, unit conversion, risk-gated execution, parameter upsert and rollback behavior, recompute failure, STEP/STL export validation, undo behavior, install diagnostics, and live-harness construction.

Current result: **162 tests passed**. The calibrated reference-canvas coverage includes path, format and size validation, aspect-preserving calibration, principal-plane selection through Fusion wrappers and plane normals, center offsets, opacity, both flips, name conflicts, recompute rollback, checkpoint-targeted deletion, path redaction, strict MCP schema, version reporting, and bounded canvas context serialization. Orthographic-set coverage adds strict 2–3 view normalization, XY/XZ/YZ model-axis mapping, tolerance-boundary and mismatch checks, preparation before mutation, two- and three-view creation, one-transaction commit, partial-failure cleanup, basename-only results and audits, one whole-set checkpoint, and all-target-prevalidated Undo. Live server 2.1.0 behavior remains pending until Fusion restarts. The skill validator could not start because the local Python environment does not include optional `PyYAML`; frontmatter and the reference link were checked manually without adding a runtime dependency.

Run:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q "Fusion MCP Addin" scripts tests
python scripts/check_install.py --addon-path "Fusion MCP Addin"
```

## Live user-parameter evidence

The installed add-in exposed `upsert_user_parameter`, reported server version `1.2.0`, and completed authenticated calls against an unsaved blank design. The live sequence was:

1. Create `codex_test_width = 50 mm` and confirm it through `get_design_context`.
2. Update it to `60 mm` with `expected_old_expression = "50 mm"` and confirm the new value.
3. After correcting the Fusion command ID from the display name `Undo` to `UndoCommand`, repeat the update and call `undo_last_execution`.
4. Confirm through `get_design_context` that Undo restored `codex_test_width = 50 mm`.

The final disposable document remains unsaved with the test parameter at `50 mm`. No bodies, sketches, or features were created by this validation.

## Live rectangle-sketch evidence

The installed add-in exposed `create_rectangle_sketch` and reported server version `1.3.0`. Against an unsaved blank design, the tool created `Codex_Live_Rectangle_1_3` on the XY plane with driving expressions `40 mm` by `30 mm` and a center of `0 mm`, `0 mm`.

- The result reported four lines, one closed profile, and evaluated dimensions of `40.0 × 30.0 mm`.
- `get_design_context` confirmed the sketch count changed from zero to one.
- A top viewport capture visually confirmed a centered 4:3 rectangle.
- `undo_last_execution` succeeded, and a final context read confirmed the sketch count returned to zero.

## Live extrusion and simple-hole evidence

The installed add-in exposed `create_extrusion` and `create_simple_hole` and reported server version `1.5.0`. Against a new unsaved blank design, the validation sequence was:

1. Create `Codex_Validation_Rectangle_1_5` on the XY plane at `40 × 30 mm`.
2. Create `Codex_Validation_Extrusion_1_5` from its only profile at `12 mm` as a New Body.
3. Confirm a solid `Body1` with `40 × 30 × 12 mm` bounds and `14.4 cm³` volume.
4. Create `Codex_Validation_Hole_1_5` on the +Z top face at `(10 mm, 5 mm)`, with `6 mm` diameter and `12 mm` depth.
5. Confirm the body retained its bounds and its volume decreased to `14.06070799341229 cm³`, matching the removed cylinder volume.
6. Inspect top and isometric viewport captures and visually confirm the offset circular opening.
7. Call `undo_last_execution` and confirm the placement sketch and hole feature were removed, the counts returned to one sketch and one feature, and the body volume returned to `14.4 cm³`.

The validation rectangle and extrusion remain only in the disposable unsaved document. The test did not modify or save an existing user design.

## Live constant-radius fillet evidence

The installed add-in exposed `create_fillet` and reported server version `1.6.0`. Against a new unsaved blank design, the validation sequence was:

1. Create a `40 × 30 mm` rectangle and extrude it `12 mm` as `Body1`.
2. Confirm the unmodified body measured `40 × 30 × 12 mm` with `14.4 cm³` volume and one feature.
3. Create `Codex_Vertical_Fillet_1_6` with `edge_selector = "vertical"`, `radius_expression = "2 mm"`, and tangent chaining enabled.
4. Confirm four selected edges, an evaluated radius of `2.0 mm`, two total features, unchanged body bounds, and a reduced volume of `14.35879644737231 cm³`.
5. Compare before and after isometric captures and visually confirm that all four vertical corners became rounded while the top and bottom perimeter edges remained sharp.
6. Call `undo_last_execution` and confirm the feature count returned to one, the volume returned to `14.4 cm³`, and the isometric capture showed the original sharp vertical corners.

The validation body remains only in the disposable unsaved document, and the fillet itself was removed by Undo.

## Live equal-distance chamfer evidence

After a full Fusion restart, the installed add-in exposed `create_chamfer` and reported server version `1.7.0`. Against a new unsaved blank design, the validation sequence was:

1. Confirm the design contained zero bodies, zero sketches, and zero features.
2. Create a `40 × 30 mm` rectangle and extrude it `12 mm` as `Body1`.
3. Confirm the unmodified solid measured `40 × 30 × 12 mm`, had `14.4 cm³` volume, and contained one feature.
4. Create `Codex_Vertical_Chamfer_1_7` with `edge_selector = "vertical"`, `distance_expression = "2 mm"`, and tangent chaining enabled.
5. Confirm four selected edges, an evaluated distance of `2.0 mm`, two total features, unchanged body bounds, and a reduced volume of `14.304 cm³`.
6. Compare before and after isometric captures and visually confirm four equal flat bevel faces along the vertical corners while the top and bottom perimeter edges remained sharp.
7. Call `undo_last_execution` and confirm the feature count returned to one, the volume returned to `14.4 cm³`, and the final isometric capture matched the original sharp-corner body.

The validation rectangle and extrusion remain only in the disposable unsaved document. The chamfer itself was removed by Undo.

## Live single-direction feature-pattern evidence

After a full Fusion restart, the installed add-in exposed `create_linear_pattern` and reported server version `1.8.0`. Against a new unsaved blank design, the validation sequence was:

1. Create a `60 × 30 mm` rectangle and extrude it `10 mm` as `Body1`, producing an `18.0 cm³` solid.
2. Create `Codex_Pattern_Seed_Hole_1_8`, a `6 mm` diameter, `10 mm` deep hole at `(-20 mm, 0 mm)` on the +Z top face.
3. Confirm the seed-hole body retained `60 × 30 × 10 mm` bounds, had `17.717256661176904 cm³` volume, and contained two features.
4. Create `Codex_Hole_Row_1_8` from the seed hole along X with quantity `3` and adjacent spacing `20 mm`.
5. Confirm an evaluated spacing of `20.0 mm`, three total features, unchanged body bounds, and a reduced volume of `17.15176998353072 cm³`.
6. Compare top captures and visually confirm three aligned `6 mm` openings at X positions `-20`, `0`, and `20 mm`.
7. Call `undo_last_execution` and confirm the feature count returned to two, the volume returned to `17.717256661176904 cm³`, and the final top capture showed only the original seed hole.

The validation plate and seed hole remain only in the disposable unsaved document. The linear pattern itself was removed by Undo.

## Live feature-owned model-parameter evidence

After a full Fusion and Codex restart, the installed add-in exposed `update_model_parameter`, included `model_parameters` in design context, and reported server version `1.9.0`. Against a new unsaved blank design, the validation sequence was:

1. Create `Codex_Model_Param_Rectangle_1_9` at `40 × 30 mm` and extrude it as `Codex_Model_Param_Extrusion_1_9` at `10 mm`.
2. Confirm `Body1` measured `40 × 30 × 10 mm`, had `12.0 cm³` volume, and the extrusion exposed model parameter `d3` with role `AlongDistance` and expression `10 mm`.
3. Call `update_model_parameter` with the exact feature name, role `AlongDistance`, expression `15 mm`, and `expected_old_expression = "10 mm"`.
4. Confirm `d3 = 15 mm`, the body measured `40 × 30 × 15 mm`, volume increased to `18.0 cm³`, and the isometric capture showed the increased height.
5. Call `undo_last_execution` and confirm `d3 = 10 mm`, the body returned to `40 × 30 × 10 mm`, volume returned to `12.0 cm³`, and the final isometric capture matched the original height.

The validation rectangle and extrusion remain only in the disposable unsaved document at the restored `10 mm` height. The test did not save or modify an existing user design.

## Live calibrated reference-canvas evidence

After installing the server 2.0.0 add-in and fully restarting Fusion, the authenticated server tool catalog exposed `create_reference_canvas`. Against a new unsaved blank design, the validation sequence was:

1. Confirm zero bodies, sketches, features, and canvases through `get_design_context(scope="all")`.
2. Create `Codex_Reference_Canvas_2_0` from the 900 × 600 test image on the XY construction plane with a calibrated width of `100 mm`, center `0 mm, 0 mm`, opacity 50, and no flips.
3. Confirm recomputation and checkpoint creation. The result reported only the basename `reference-plate-3x2.png`, size 30,523 bytes, plane `xy`, width `100.0 mm`, derived height `66.666671 mm`, and center `[0.0, 0.0]`; no full local path or image bytes were returned.
4. Confirm the design context changed from zero to one canvas and independently reported `plane = xy`, `100.0 × 66.666671 mm`, center `0.0, 0.0`, opacity 50, and selectable true.
5. Capture the top viewport and visually confirm a centered 3:2 canvas outline with the reference image visible at the expected proportions.
6. Call `undo_last_execution`. The canvas-specific checkpoint rollback removed the exact canvas, recomputed the design, and a final context read confirmed the canvas count returned to zero. The final top capture showed only the blank grid.

An already-open Codex task retained its pre-update callable-tool cache even though the restarted server's authenticated `/tools` catalog included `create_reference_canvas`. The live creation therefore used the same authenticated MCP `tools/call` endpoint directly. Discovery of the new typed tool in a newly created Codex task remains a separate client-cache check; server registration and execution are verified.

## Live orthographic canvas-set evidence

After installing server 2.1.0 and fully restarting Fusion, `get_fusion_status` reported Fusion 2704.1.53, server 2.1.0, authentication enabled, and an active unsaved design. The authenticated server catalog contained 20 tools and exposed `create_orthographic_canvas_set`. The validation sequence was:

1. Confirm zero bodies, sketches, features, and canvases through `get_design_context(scope="all")`.
2. Create `Codex_Orthographic_Set_2_1` using the repository's 900 × 600 test image for an XY view and an XZ view, both calibrated to `100 mm` width, center `0 mm, 0 mm`, opacity 50, and no flips.
3. Confirm one atomic success result and checkpoint. Both views reported only the basename `reference-plate-3x2.png`, size 30,523 bytes, `100.0 × 66.666671 mm`, and center `[0.0, 0.0]`. The shared X check compared `100.0 mm` with `100.0 mm`, reported a `0.0 mm` difference against the `0.25 mm` tolerance, and produced model axes X `100.0 mm`, Y `66.666671 mm`, and Z `66.666671 mm`.
4. Confirm design context changed from zero to two canvases named `Codex_Orthographic_Set_2_1_XY` and `Codex_Orthographic_Set_2_1_XZ`, with the expected planes, independent dimensions, centers, opacity, and selectable state.
5. Capture top and front views. The top capture showed the centered horizontal 3:2 reference with three aligned holes; the front capture showed the corresponding centered vertical presentation, also at the expected proportions.
6. Call `undo_last_execution` once. The server returned success, recomputed the design, and a final context read confirmed the canvas count returned from two to zero. Final top and front captures both showed only the blank grid.

The already-open Codex task retained its pre-2.1 typed-tool cache, so the new set creation used the authenticated MCP `tools/call` endpoint after confirming server registration. This live run validates two-view XY/XZ calibration, shared-X validation, atomic creation, context serialization, visual placement, and whole-set Undo. It deliberately reuses one synthetic image to isolate placement mechanics; three-view YZ behavior and modeling from distinct real drawings remain separate live scope.

## Server 2.2.0 parametric plate status

**Partial; patched server restart required.** The installed server reported 2.2.0 and its live catalog exposed all 21 tools including `create_parametric_plate`. A blank Part Design document rejected the first creation at `Occurrences.addNewComponent` because Part Design permits only its single root component. The failure returned `PLATE_COMPONENT_WRITE_FAILED`, restored all geometry counts, and a later out-of-bounds request returned `PLATE_HOLE_OUT_OF_BOUNDS` without geometry mutation. The acceptance harness incorrectly continued after the failed creation and created `plate_width`; `undo_last_execution` removed that parameter and context returned to zero bodies, sketches, features, and parameters.

The next live run confirmed that Part Design reached the root-component geometry path, but the shared four-point hole sketch failed with `VCS_SKETCH_OVER_CONSTRAINTS` while adding a repeated signed coordinate dimension. Fusion's transaction restored every count to zero, but invalid post-abort parameter handles caused the tool to misreport the restored state as `ROLLBACK_FAILED`.

The current compatibility patch gives every hole an independent hidden placement sketch, preserving its own X/Y driving parameters without cross-hole solver constraints. It also treats a verified transaction-restored snapshot as the authoritative rollback result instead of deleting invalid handles again. The complete automated suite passes **199 tests**. Measured live geometry, parameter propagation, screenshots of the plate, successful STEP/STL export, whole-part Undo, and Redo remain unverified until Fusion reloads this patch.

## Required live procedure

1. Set `FUSION_MCP_TOKEN` at user scope and restart Fusion and ChatGPT.
2. Add and run `Fusion MCP Addin` from Fusion's **Scripts and Add-Ins** panel.
3. Open a new blank design. The acceptance script creates geometry in the active document.
4. From this repository run:

```powershell
python scripts/live_acceptance.py --confirm-blank-design --report docs/live-validation-result.json
```

5. When the high-risk confirmation appears in Fusion, inspect the intent, reasons, and SHA-256 and choose **No**. The test passes only when no high-risk code runs.
6. Visually inspect the isometric, front, and top screenshots in the ChatGPT Codex task.
7. Restart the Fusion add-in and ChatGPT desktop, then rerun `check_install.py` to record reconnect behavior.

The generated JSON report strips base64 screenshot data and never includes the bearer token. Do not commit `docs/live-validation-result.json` if it contains personal file paths.

## Remaining live scope

The add-in manifest, bearer token, health endpoint, authenticated initialization, reconnect, user-parameter updates, feature-owned model-parameter updates, rectangle-sketch creation, New Body extrusion, simple top-face distance-depth holes, constant-radius fillets, equal-distance chamfers, single-direction feature patterns, calibrated XY reference canvases, atomic two-view XY/XZ canvas sets, viewport screenshots, checkpoint-targeted single-canvas Undo, and whole-set Undo are verified. A separate 50 mm cube creation also produced measured `50 × 50 × 50 mm` bounds and `125 cm³` volume. No claim is made yet that a newly created Codex task refreshes the typed tool catalog, three-view or YZ canvas sets, modeling from distinct real drawings, multiple-view image reconstruction, automatic OCR or contour tracing, the complete mounting-plate scenario, exports, approval dialogs, Join/Cut/Intersect extrusions, through-all holes, non-top-face holes, countersinks, counterbores, threads, two-direction patterns, circular patterns, body patterns, or model-parameter edits outside the active component have passed; those remain separate expansion scope.
