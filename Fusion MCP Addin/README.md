## Installation

### 1. Configure a shared local token

Generate a long random token and store it as the user environment variable `FUSION_MCP_TOKEN`. Do not put the value in Git or TOML. On Windows PowerShell, set it once and then restart Fusion and ChatGPT:

```powershell
$tokenBytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Fill($tokenBytes)
$fusionToken = [Convert]::ToBase64String($tokenBytes)
[Environment]::SetEnvironmentVariable('FUSION_MCP_TOKEN', $fusionToken, 'User')
```

The shell variable is only used to set the user environment value. Do not print or paste the token into chat.

1. Copy the `Fusion MCP Addin` folder to your Fusion add-ins directory:
    - Windows: `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\`
    - macOS: `~/Library/Application Support/Autodesk/Autodesk Fusion/API/AddIns/`

2. Start Fusion and go to the **Add-Ins** panel

3. Find "Fusion MCP Addin" in the list and click **Run**

4. The add-in starts an authenticated HTTP MCP server on `127.0.0.1:9100`. It refuses to start without `FUSION_MCP_TOKEN`.

Or work from the cloned repository directly by adding the `Fusion MCP Addin` folder from the cloned source location in Fusion's **Scripts and Add-Ins** panel.

### 3. Connect ChatGPT desktop Codex

Open this repository as the Codex project. Its `.codex/config.toml` points to the local server and reads the token from `FUSION_MCP_TOKEN`. In ChatGPT desktop, open **Settings → MCP servers**, confirm the project server, save, and restart the app. Then start a Codex task in this project.

Run the diagnostic from the repository root:

```powershell
python scripts/check_install.py --addon-path "Fusion MCP Addin"
```

The report shows only whether a token exists; it never prints the value.

## Configuring Cursor

To use this MCP server with Cursor, add it to your Cursor configuration:

```json
{
  "mcpServers": {
    "fusion-mcp-server": {
      "url": "http://localhost:9100/"
    }
  }
}
```

## Configuring Claude

To use this with Claude you need to run a small MCP proxy process as CLaude does not support local HTTP servers.

To do this you must first [install Node js](https://nodejs.org/en/download) and ensure npx is installed.

In Claude go to Settings/Connectors/Developer and select the **Edit Config** button to navigate to the config file.

Open the Claude configuration file `claude_desktop_config.json`and enter the following:

```json
{
  "mcpServers": {
    "fusion-mcp": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "http://localhost:9100/"
      ]
    }
  }
}
```

For information and other setup options see the [mcp-remote documentation here](https://www.npmjs.com/package/mcp-remote)

## Available Tools

Once the add-in is running, the following MCP tools are available:

### update_model_parameter

Update one existing model parameter owned by a named feature. Read `model_parameters` with `get_design_context(scope="all")`, then pass the exact `created_by.name`, `role`, current `expression` as `expected_old_expression`, and the new Fusion expression. The edit is refused when the owner and role are missing or ambiguous, or when the expression changed after it was read. The first version targets the active component and requires an exact feature name.

### create_extrusion

Create a named solid New Body from the largest closed profile in an existing named sketch. The distance is a Fusion expression such as `height` or `25 mm`; a negative value reverses direction. The tool rejects zero distance, missing or empty sketches, and duplicate extrusion names before modifying the design.

### create_simple_hole

Create one named simple hole on the planar +Z top face of a named solid body. The X coordinate, Y coordinate, diameter, and depth are driving Fusion expressions, and the generated placement sketch remains in the timeline so parameter edits can reposition the hole. This first explicit-hole version targets the +Z top face and distance depth; other faces, through-all, countersink, counterbore, and thread options remain future extensions.

### create_fillet

Create one named constant-radius fillet on a named solid body. Select `all`, `top`, `bottom`, or `vertical` body edges and provide a positive Fusion expression such as `2 mm` or `edge_radius`. The tool validates the body, expression, feature name, and selected edge group before modifying the design, then recomputes and records an Undo checkpoint.

### create_chamfer

Create one named equal-distance chamfer on a named solid body. Select `all`, `top`, `bottom`, or `vertical` body edges and provide a positive Fusion expression such as `2 mm` or `edge_chamfer`. The tool uses Fusion's current multi-edge-set chamfer API, validates all inputs before mutation, recomputes the design, and records an Undo checkpoint.

### create_linear_pattern

Create one named single-direction pattern of an existing named feature along the active component's X, Y, or Z construction axis. The total quantity includes the original feature, and `spacing_expression` defines the distance between adjacent instances. A negative spacing reverses direction. This first pattern version supports one direction and feature targets; two-direction, circular, and body patterns remain future extensions.

### execute_api_script

Deprecated compatibility alias. New Codex workflows should use `execute_fusion_python` with `intent`, `code`, and `expected_changes`.

**Parameters:**
- `script` (string): Python script source code to execute

**Example usage from AI assistant:**
- "Create a 10cm cube at the origin"
- "List all components in the current design"
- "Extrude the selected sketch 5cm"

### get_screenshot

Capture a screenshot of the current Fusion viewport with optional camera orientation.

**Parameters:**
- `view` (string): Camera orientation - "current", "top", "bottom", "front", "back", "left", "right", "iso-top-left", "iso-top-right", "iso-bottom-left", "iso-bottom-right" (default: "current")
- `width` (integer): Screenshot width in pixels, 1-4096 (default: 512)
- `height` (integer): Screenshot height in pixels, 1-4096 (default: 512)

**Returns:** Base64-encoded PNG image data

### get_api_documentation

Search the Fusion API documentation to find classes, properties, methods, and their descriptions. This tool helps AI assistants discover and understand the Fusion API.

**Parameters:**
- `search_term` (string, required): The term to search for. Can be prefixed with namespace (e.g., "fusion.Application") or class (e.g., "core.Application.activeDocument")
- `category` (string): Search category - "class_name", "member_name", "description", or "all" (default behavior)

**Returns:** Top 3 results with documentation including class definitions, properties, methods, and their signatures

**Example searches:**
- "Application" - Find the Application class
- "fusion.Sketch.sketchCurves" - Find sketchCurves member of Sketch class
- "extrude" - Search for extrusion-related items

> **Note on Tool Descriptions**: This add-in uses detailed tool descriptions to help AI assistants understand when and how to use each tool. Clear descriptions with specific parameter constraints and usage examples significantly improve the effectiveness of MCP-based interactions.

## Troubleshooting

**Server won't start:**

- Check if port 9100 is already in use
- Confirm `FUSION_MCP_TOKEN` exists at user scope and restart both Fusion and ChatGPT
- Verify Fusion has necessary permissions
- Check the Text Commands window for error messages

**Commands fail:**

- Check that Fusion API calls are valid for the current context
- Verify parameters are passed correctly

**Local logs:** execution audit records are written under the operating system temporary directory in `fusion-codex-mcp/audit.jsonl`. Delete that file when its local history is no longer needed. Authorization values are redacted.

**Data boundary:** CAD documents and the HTTP server stay local. Prompts, MCP results, error summaries, and screenshots passed into Codex may be transmitted to OpenAI's model service.

## License

This add-in is provided as-is for educational and development purposes. 
