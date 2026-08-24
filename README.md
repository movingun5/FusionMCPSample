# Fusion MCP Add-in

> This fork targets natural-language modeling from the ChatGPT desktop app's local Codex workspace. It remains an experimental Fusion automation add-in, not a safety-certified CAD/CAM product.

A Fusion add-in that provides HTTP API functionality for Model Context Protocol (MCP) communication. MCP is a standardized protocol that enables AI assistants to interact with external tools and data sources. This add-in enables external applications (like Cursor) to interact with Fusion through a secure HTTP interface.

[See detailed usage instructions here](<Fusion MCP Addin/tips.md>)

## Features

- **HTTP Server Management**: Create and manage HTTP servers within Fusion
- **Thread-Safe Execution**: Execute Fusion API calls safely from background threads
- **MCP Server**: Exposes a Model Context Protocol server for AI assistant integration
- **Resource Access**: Access design information, components, and viewport screenshots
- **Tool Execution**: Execute Fusion commands remotely

### Available Tools

- **get_fusion_status**: Check Fusion, add-in, and active-design availability without exposing secrets
- **get_design_context**: Read bounded component, body, user/model parameter, and entity-token context
- **upsert_user_parameter**: Create or safely update one named user parameter with optional optimistic concurrency checking
- **update_model_parameter**: Safely change one existing feature-owned dimension by exact feature name and parameter role
- **create_rectangle_sketch**: Create a named center-point rectangle on XY/XZ/YZ with Fusion expressions as driving dimensions
- **create_extrusion**: Extrude the largest closed profile in a named sketch as a named solid New Body using a Fusion distance expression
- **create_simple_hole**: Create a named, parametrically positioned simple hole on a named solid body's planar +Z top face
- **create_fillet**: Apply a named constant-radius fillet to all, top, bottom, or vertical edges of a named solid body
- **create_chamfer**: Apply a named equal-distance chamfer to all, top, bottom, or vertical edges of a named solid body
- **create_linear_pattern**: Repeat a named feature along the X, Y, or Z construction axis using a count and adjacent-spacing expression
- **create_reference_canvas**: Place a local PNG/JPEG/TIFF on XY/XZ/YZ at a calibrated physical width while preserving its aspect ratio
- **create_orthographic_canvas_set**: Atomically place 2–3 unique principal-view images, validate their shared X/Y/Z dimensions within tolerance, and record one whole-set Undo checkpoint
- **create_parametric_plate**: Atomically create one centered XY rectangular plate with named driving parameters, 0–32 circular through-holes, and one optional vertical-edge fillet or chamfer
- **create_parametric_profile_extrusion**: Atomically create one closed straight-line XY profile from 3–32 named parametric vertices and extrude it in +Z as a new body
- **execute_fusion_python**: Execute risk-classified `run(context)` code with Fusion approval gates and post-run verification
- **get_viewport_screenshot**: Capture conventional current, orthographic, and isometric views
- **get_api_documentation**: Search the Fusion API documentation for classes, methods, properties, and descriptions
- **undo_last_execution**: Attempt to undo the most recent successful Codex transaction in the same document
- **export_design**: Export and verify STEP/STL, requiring Fusion approval before overwrite
- **execute_api_script**, **get_screenshot**: Backward-compatible aliases

> **Note on Tool Descriptions**: In MCP environments, well-crafted tool descriptions are critical for AI assistants to understand when and how to use each tool. This add-in includes detailed descriptions and parameter specifications to help AI assistants effectively interact with Fusion.

## Architecture

The add-in consists of three main components:

### 1. TaskManager (`task_manager.py`)

Provides thread-safe execution of Fusion API calls from background threads using Fusion's custom event system.

**Key Features:**

- Safe execution of Fusion API calls from HTTP request handlers
- Custom event-based communication between threads
- Error handling and result reporting

### 2. McpServer (`mcp_server.py`)

**Key Features:**

- Threaded HTTP server implementation
- Custom request handler support
- Integrated socketserver ThreadingMixIn for safe Fusion API access

### 3. Main Add-in (`Fusion MCP Addin.py`)

The main add-in that implements MCP-compatible HTTP endpoints for Fusion interaction.

**Key Features:**

- Health check and status endpoints
- Resource reading (design info, components)
- Tool execution (screenshots, environment info)
- JSON-based request/response handling

## Installation & More

[Installation instructions, troubleshooting, and more are found here](<Fusion MCP Addin/README.md>)

The repository includes a project-local [`.codex/config.toml`](.codex/config.toml) and a secret-free diagnostic:

```powershell
python scripts/check_install.py --addon-path "Fusion MCP Addin"
```

Set `FUSION_MCP_TOKEN` at user scope, then fully restart both Fusion and ChatGPT so both processes inherit the same value. The MCP server binds only to `127.0.0.1:9100`.

After opening a new blank Fusion design, run the live phase-1 acceptance flow:

```powershell
python scripts/live_acceptance.py --confirm-blank-design --report docs/live-validation-result.json
```

See [live validation status](docs/live-validation.md). A missing live run is reported as unverified, never as a pass.

CAD files and the add-in remain local. Prompts, MCP results, error summaries, and screenshots supplied to Codex may be sent to OpenAI's model service.

For image- or drawing-based work, Codex interprets visible dimensions and geometry; the add-in does not perform OCR, automatic contour reconstruction, or perspective correction. The canvas tools read existing absolute local image paths and return only basenames and calibration metadata—not image bytes or full paths. A single image can be placed with `create_reference_canvas`; 2–3 unique XY/XZ/YZ views can be placed all-or-nothing with `create_orthographic_canvas_set`, which validates shared model dimensions before changing Fusion and removes the complete set with one checkpointed Undo.

`create_parametric_plate` converts explicit dimensions into one reusable component at the root origin. In a Fusion Part Design document it builds in the single root component; in a Hybrid Design document it creates a child component. Width, height, thickness, every hole's signed center X/Y and diameter, and optional edge size become user parameters such as `plate_width` and `plate_upper_left_diameter`. The first version supports a centered rectangular XY plate, 0–32 non-touching circular distance-depth through-holes, and either one vertical-edge fillet, one equal-distance vertical-edge chamfer, or no edge finish. It validates all expressions, parameter-name collisions, plate boundaries, and hole overlap before mutation; any later failure rolls the complete generated entity and parameter set back.

`create_parametric_profile_extrusion` turns an ordered 3–32 vertex outline extracted from a dimensioned drawing into one constrained XY sketch and a +Z NewBody extrusion. Every signed vertex coordinate and the depth is a named user parameter. It accepts clockwise or counterclockwise outlines, rejects duplicates, zero-area shapes, crossings, and touching non-adjacent segments before changing Fusion, and rolls back the whole result on failure. This first version supports one closed straight-line outer boundary only—no arcs, splines, internal holes, pockets, or automatic image tracing.

## License
Samples are licensed under the terms of the [MIT License](http://opensource.org/licenses/MIT). Please see the [LICENSE](LICENSE) file for full details.
