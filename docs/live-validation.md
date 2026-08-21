# Live Fusion validation status

- Date: 2026-08-21
- Automated environment: Windows, Python 3.14, Fusion API replaced by test fakes
- Live Fusion user-parameter status: **passed on Fusion 2704.1.53**
- ChatGPT desktop Codex to authenticated local MCP status: **passed**
- Phase-1 mounting-plate geometry acceptance: **not run**

## Automated evidence

The repository test suite covers policy classification, audit redaction, bearer authentication, authenticated HTTP initialization, design context, snapshots, unit conversion, risk-gated execution, parameter upsert and rollback behavior, recompute failure, STEP/STL export validation, undo behavior, install diagnostics, and live-harness construction.

Current result: **68 tests passed**, and `compileall` plus `git diff --check` exited successfully.

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

The add-in manifest, bearer token, health endpoint, authenticated initialization, reconnect, parameter updates, and one-step parameter Undo are verified. No claim is made yet that live geometry creation, screenshots, exports, or approval dialogs have passed; use the mounting-plate procedure above for that separate acceptance scope.
