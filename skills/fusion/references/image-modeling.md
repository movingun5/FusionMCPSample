# Image- and Drawing-Based Modeling

Use this guide only when the user supplies an image, drawing, render, photo, or silhouette as modeling evidence.

## Interpretation and Modeling

1. Classify the attachment as a dimensioned drawing, orthographic render, photo, or silhouette.
2. Record only visible units, views, outer dimensions, centers, diameters, radii, repetition, and depth. Keep stated dimensions separate from visual estimates.
3. Ask one focused question when a missing value changes the 3D geometry. Do not infer an exact hidden or occluded dimension from appearance alone.
4. Map each orthographic view to its principal plane:
   - top or plan view → `xy`
   - front view → `xz`
   - right or side view → `yz`
5. Call `validate_drawing_modeling_plan` with one to three mapped views, every view dimension labeled `stated`, `estimated`, or `missing`, and either a plate or straight-profile geometry proposal. Pass numeric millimeters, never image paths or image bytes.
6. Stop when the result contains blockers. Ask one focused question for missing dimensions; never turn an estimate into stated evidence. Unsupported features require a later explicit tool or a separately approved modeling approach.
7. Continue only when `ready_for_modeling=true`. Preserve the returned `target_tool` and `tool_arguments`; do not rebuild them independently.
8. Use `create_reference_canvas` for one reference image. Use `create_orthographic_canvas_set` for 2–3 distinct orthographic views with at least one stated shared dimension.
9. Before calling the set tool, map XY to X/Y, XZ to X/Z, and YZ to Y/Z. Set each `width_expression` from a stated overall drawing width, preserve aspect ratio, and use offsets or flips only when the visible origin and orientation require them.
10. Call the preflight's returned `create_parametric_plate` or `create_parametric_profile_extrusion` arguments unchanged. The creation tool never receives the image or its path.
11. For other geometry, prefer the existing explicit Fusion tools for sketches, extrusions, holes, fillets, chamfers, patterns, and parameter edits. Use source-aware names such as `Front_Profile` or `Top_Hole_Row`.
12. Verify numeric context first. Then capture every supplied top, front, or right viewport and compare proportions, placement, and repeated features with the corresponding reference. If any view or shared dimension is wrong, use one Undo to remove the complete canvas set before retrying.
13. Report stated dimensions as exact only when Fusion measurements agree. Label estimates as estimates, and do not claim perspective-distorted or dimensionless geometry is exact.

## Boundaries

- A visible attachment in Codex and a Fusion-readable local path are separate requirements. If no local path is available, continue with dimension extraction and explicit modeling but do not claim a Fusion canvas was placed.
- The add-in does not perform OCR, contour tracing, perspective correction, or photo reconstruction. Codex interprets the image; the MCP tool validates and places it.
- The drawing-plan preflight is non-mutating. It normalizes only numeric millimeter evidence and supported plate or straight-profile geometry; it does not inspect the source pixels.
- The profile-extrusion tool receives structured dimension expressions only. It never receives the reference image or reconstructs an outline from pixels.
- Both canvas tools accept only existing absolute local PNG, JPEG, or TIFF paths of at most 25 MiB and support only `xy`, `xz`, or `yz`. The set tool requires 2–3 unique planes, validates every shared axis within the requested tolerance before mutation, creates all canvases atomically, and records one whole-set Undo checkpoint.
- Never expose the full local image path or image bytes in the final report. Use the basename and calibrated dimensions.
