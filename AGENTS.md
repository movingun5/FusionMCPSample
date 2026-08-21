# Fusion Codex MCP Working Rules

- Work in millimeters for user-facing dimensions; Fusion API internal lengths are centimeters.
- Before editing an existing design, call `get_fusion_status`, `get_design_context`, and an appropriate viewport screenshot.
- Query `get_api_documentation` before relying on an unfamiliar Fusion API class or member.
- Submit code through `execute_fusion_python` with a concise Korean or English `intent` and explicit count deltas in `expected_changes`.
- Make one coherent, verifiable geometry change per execution. Reacquire Fusion entities from names or entity tokens on each request.
- After each change, compare recomputed counts, body dimensions, failed features, and screenshots. Script exit alone is not success.
- Do not bypass the risk classifier. Deletion, overwrite, CAM, simulation, filesystem, process, network, and dynamic execution require Fusion UI approval.
- Use `export_design` for STEP/STL. Never overwrite an existing export without the user's Fusion approval.
- Treat `execute_api_script` and `get_screenshot` as compatibility aliases; prefer the Codex-oriented tools.
- Never print, log, or commit `FUSION_MCP_TOKEN`.
