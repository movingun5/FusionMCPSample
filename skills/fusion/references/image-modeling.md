# Image- and Drawing-Based Modeling

Use this guide only when the user supplies an image, drawing, render, photo, or silhouette as modeling evidence.

## Interpretation and Modeling

1. Classify the attachment as a dimensioned drawing, orthographic render, photo, or silhouette.
2. Record only visible units, views, outer dimensions, centers, diameters, radii, repetition, and depth. Keep stated dimensions separate from visual estimates.
3. Ask one focused question when a missing value changes the 3D geometry. Do not infer an exact hidden or occluded dimension from appearance alone.
4. Choose the primary orthographic view. When Fusion can read the same image through an absolute local file path, place one calibrated canvas with `create_reference_canvas`:
   - top or plan view → `xy`
   - front view → `xz`
   - right or side view → `yz`
5. Set `width_expression` from a stated overall drawing width. Preserve the default aspect ratio. Use center offsets or flips only when the visible origin and orientation require them.
6. Prefer the existing explicit Fusion tools for sketches, extrusions, holes, fillets, chamfers, patterns, and parameter edits. Use source-aware names such as `Front_Profile` or `Top_Hole_Row`.
7. Verify numeric context first. Then capture the matching top, front, or right viewport and compare proportions, placement, and repeated features with the reference.
8. Report stated dimensions as exact only when Fusion measurements agree. Label estimates as estimates, and do not claim perspective-distorted or dimensionless geometry is exact.

## Boundaries

- A visible attachment in Codex and a Fusion-readable local path are separate requirements. If no local path is available, continue with dimension extraction and explicit modeling but do not claim a Fusion canvas was placed.
- The add-in does not perform OCR, contour tracing, perspective correction, or photo reconstruction. Codex interprets the image; the MCP tool validates and places it.
- `create_reference_canvas` accepts only an existing absolute local PNG, JPEG, or TIFF path of at most 25 MiB and supports only `xy`, `xz`, or `yz`.
- Never expose the full local image path or image bytes in the final report. Use the basename and calibrated dimensions.
