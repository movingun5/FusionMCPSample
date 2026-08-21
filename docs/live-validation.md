# Live Fusion validation status

- Date: 2026-08-21
- Automated environment: Windows, Python 3.14, Fusion API replaced by test fakes
- Live Fusion status: **not run**
- ChatGPT desktop Codex MCP status: **not run**

## Automated evidence

The repository test suite covers policy classification, audit redaction, bearer authentication, authenticated HTTP initialization, design context, snapshots, unit conversion, risk-gated execution, recompute failure, STEP/STL export validation, undo behavior, install diagnostics, and live-harness construction.

Current result: **50 tests passed**, and `compileall` plus `git diff --check` exited successfully.

Run:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q "Fusion MCP Addin" scripts tests
python scripts/check_install.py --addon-path "Fusion MCP Addin"
```

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

## Current limitation

The diagnostic found the add-in manifest, but reported `TOKEN_MISSING` and `SERVER_UNAVAILABLE`. Therefore no claim is made that live geometry creation, screenshots, exports, approval dialogs, or reconnect behavior have passed.
