---
name: fusion
description: Use when creating, editing, inspecting, validating, undoing, or exporting Autodesk Fusion 360 CAD models through the local fusion360 MCP server from a Codex task.
---

# Fusion

## Overview

Translate natural-language CAD intent into verifiable changes through `fusion360` MCP tools. Live Fusion state is authoritative; never infer its contents or identity.

## Workflow

1. Call `get_fusion_status`; stop if Fusion, authentication, or an active design is unavailable.
2. Call `get_design_context` before modeling; use `scope="all"` for edits. It exposes components, bodies, counts, user parameters, feature-owned model parameters, and bounds—not UI selections or per-hole geometry.
   For user-parameter creation or edits, prefer `upsert_user_parameter` over arbitrary Python. Read the current expression first and pass it as `expected_old_expression` when updating an existing parameter.
   For an existing feature dimension, prefer `update_model_parameter`. Choose one exact `created_by.name` and `role` from `model_parameters`, then pass its current expression as `expected_old_expression`. Stop on missing or ambiguous matches rather than guessing.
   For an axis-aligned center-point rectangle on a principal construction plane, prefer `create_rectangle_sketch`. Give it a unique name and explicit Fusion expressions for width, height, and optional center coordinates.
   For a constant-radius edge round, prefer `create_fillet`. For an equal-distance bevel, prefer `create_chamfer`. Both tools accept a named solid body, a unique feature name, a positive Fusion length expression, and the stable selectors `all`, `top`, `bottom`, or `vertical`.
   For a one-direction repetition of an existing named feature, prefer `create_linear_pattern`. Choose X, Y, or Z, make the total quantity include the original, and use a non-zero adjacent-spacing expression; a negative spacing reverses direction.
3. Capture `get_viewport_screenshot` before editing existing geometry. A verified blank design needs no before image.
4. Resolve dimensions, placement, target, and success criteria. Use explicit units. Ask one question when missing information would alter geometry.
5. For an uncertain API, call `get_api_documentation(search_term="ClassOrMember", category="all")`; do not invent argument or member names.
6. Call `execute_fusion_python` for one coherent feature group. `code` must define `run(context)` and use fresh `app`, `ui`, `design`, and `rootComponent` handles from `context`. Prefer `ValueInput.createByString("5 mm")`; raw Fusion point coordinates are centimeters.
7. Pass `expected_changes` as an object using `components_created`, `bodies_created`, `sketches_created`, or `features_created`. If context cannot expose a required property, make the code measure/assert it before returning; inputs are not proof.
8. After each change, inspect the result, call `get_design_context`, and capture an isometric screenshot. Add orthographic views only when useful.
9. Report success only when recomputation, expected deltas, failed-feature checks, numeric evidence, and images agree. Otherwise stop; when appropriate, call `undo_last_execution` and verify restoration before retrying.

## Safety Boundaries

- Never bypass server policy or an approval dialog; stop if approval is denied.
- Do not invent tokens, selections, geometry details, or reuse stale `adsk` objects.
- Do not delete or relocate ambiguous geometry. Ask for the missing target or location.
- Export only when requested. Only STEP/STL with an absolute matching path are supported; overwrite requires approval.
- MCP access does not authorize unrelated external actions.

## Quick Reference

| Intent | Required tools |
| --- | --- |
| Inspect | status → context → screenshot if useful |
| Parameters | status → context → upsert parameter → context |
| Existing feature dimension | status → all context → before image → update model parameter → all context → after image |
| Rectangle sketch | status → context → create rectangle sketch → context → screenshot |
| Fillet | status → context → before image → create fillet → context → after image |
| Chamfer | status → context → before image → create chamfer → context → after image |
| Linear pattern | status → context → before image → create linear pattern → context → after image |
| Other create | status → context → execute → context → screenshot |
| Other edit | status → context → before image → execute → context → after image |
| Recover | undo → context → screenshot |
| Export | context → STEP/STL export → report verified file |

## Execution Shape

```python
def run(context):
    design = context["design"]
    root = context["rootComponent"]
    # Create or modify one verifiable feature group, then assert its result.
    return {"result": "created named geometry"}
```

Use `{"bodies_created": 1, "sketches_created": 1, "features_created": 1}` only when those are the actual intended deltas.

## Common Mistakes

- “Just run it” → still check status and context.
- List/prose `expected_changes` → use an object.
- Script completed → verify numeric and visual evidence.
- Universal rollback → undo is best-effort for the latest execution in the same document.
