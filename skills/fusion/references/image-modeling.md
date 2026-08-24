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
5. Use `create_reference_canvas` for one reference image. Use `create_orthographic_canvas_set` for 2–3 distinct orthographic views with at least one stated shared dimension.
6. Before calling the set tool, map XY to X/Y, XZ to X/Z, and YZ to Y/Z. If Codex's extracted shared dimensions disagree, report the conflicting values instead of invoking Fusion.
7. Set each `width_expression` from a stated overall drawing width. Preserve the default aspect ratio. Use center offsets or flips only when the visible origin and orientation require them.
8. Prefer the existing explicit Fusion tools for sketches, extrusions, holes, fillets, chamfers, patterns, and parameter edits. Use source-aware names such as `Front_Profile` or `Top_Hole_Row`.
9. Verify numeric context first. Then capture every supplied top, front, or right viewport and compare proportions, placement, and repeated features with the corresponding reference. If any view or shared dimension is wrong, use one Undo to remove the complete canvas set before retrying.
10. Report stated dimensions as exact only when Fusion measurements agree. Label estimates as estimates, and do not claim perspective-distorted or dimensionless geometry is exact.

## Boundaries

- A visible attachment in Codex and a Fusion-readable local path are separate requirements. If no local path is available, continue with dimension extraction and explicit modeling but do not claim a Fusion canvas was placed.
- The add-in does not perform OCR, contour tracing, perspective correction, or photo reconstruction. Codex interprets the image; the MCP tool validates and places it.
- Both canvas tools accept only existing absolute local PNG, JPEG, or TIFF paths of at most 25 MiB and support only `xy`, `xz`, or `yz`. The set tool requires 2–3 unique planes, validates every shared axis within the requested tolerance before mutation, creates all canvases atomically, and records one whole-set Undo checkpoint.
- Never expose the full local image path or image bytes in the final report. Use the basename and calibrated dimensions.
