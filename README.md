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
- **get_design_context**: Read bounded component, body, parameter, and entity-token context
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

CAD files and the add-in remain local. Prompts, MCP results, error summaries, and screenshots supplied to Codex may be sent to OpenAI's model service.

## License
Samples are licensed under the terms of the [MIT License](http://opensource.org/licenses/MIT). Please see the [LICENSE](LICENSE) file for full details.
