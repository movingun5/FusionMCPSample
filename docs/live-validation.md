# Live Fusion validation status

- Date: 2026-08-21
- Automated environment: Windows, Python 3.14, Fusion API replaced by test fakes
- Live Fusion user-parameter status: **passed on Fusion 2704.1.53**
- Live rectangle-sketch status: **passed on Fusion 2704.1.53**
- Live new-body extrusion status: **passed on Fusion 2704.1.53**
- Live simple-hole status: **passed on Fusion 2704.1.53**
- Live constant-radius fillet status: **passed on Fusion 2704.1.53**
- Live equal-distance chamfer status: **not run**
- ChatGPT desktop Codex to authenticated local MCP status: **passed**
- Phase-1 mounting-plate geometry acceptance: **not run**

## Automated evidence

The repository test suite covers policy classification, audit redaction, bearer authentication, authenticated HTTP initialization, design context, snapshots, unit conversion, risk-gated execution, parameter upsert and rollback behavior, recompute failure, STEP/STL export validation, undo behavior, install diagnostics, and live-harness construction.

Current result: **107 tests passed**, and `compileall` plus `git diff --check` exited successfully. The constant-radius fillet and equal-distance chamfer tools are covered for all/top/bottom/vertical edge selection, expression validation, body and feature conflicts, empty selection rejection, recompute rollback, checkpointing, and strict MCP schemas. The chamfer result is still pending live Fusion validation.

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

The add-in manifest, bearer token, health endpoint, authenticated initialization, reconnect, parameter updates, rectangle-sketch creation, New Body extrusion, simple top-face distance-depth holes, constant-radius fillets, viewport screenshots, and one-step Undo are verified. A separate 50 mm cube creation also produced measured `50 × 50 × 50 mm` bounds and `125 cm³` volume. The equal-distance chamfer tool has automated coverage but not yet live evidence. No claim is made yet that the complete mounting-plate scenario, exports, approval dialogs, Join/Cut/Intersect extrusions, through-all holes, non-top-face holes, countersinks, counterbores, threads, chamfers, or patterns have passed; those remain separate expansion scope.
