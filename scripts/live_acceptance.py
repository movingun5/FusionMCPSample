"""Run the phase-1 mounting-plate acceptance flow against a live Fusion MCP."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


EXPECTED_PLATE_MM = [100.0, 60.0, 5.0]
REQUIRED_TOOLS = {
    "get_fusion_status",
    "get_design_context",
    "execute_fusion_python",
    "get_viewport_screenshot",
    "get_api_documentation",
    "undo_last_execution",
    "export_design",
    "create_parametric_plate",
    "upsert_user_parameter",
}


def build_parametric_plate_arguments():
    """Return the explicit 100×60×5 mm four-hole plate request."""

    return {
        "name": "MountingPlate",
        "parameter_prefix": "plate",
        "width_expression": "100 mm",
        "height_expression": "60 mm",
        "thickness_expression": "5 mm",
        "holes": [
            {"key": "lower_left", "x_expression": "-40 mm", "y_expression": "-20 mm", "diameter_expression": "6 mm"},
            {"key": "upper_left", "x_expression": "-40 mm", "y_expression": "20 mm", "diameter_expression": "6 mm"},
            {"key": "lower_right", "x_expression": "40 mm", "y_expression": "-20 mm", "diameter_expression": "6 mm"},
            {"key": "upper_right", "x_expression": "40 mm", "y_expression": "20 mm", "diameter_expression": "6 mm"},
        ],
        "edge_finish": {"type": "fillet", "size_expression": "3 mm"},
    }


def dimensions_match(actual, expected=EXPECTED_PLATE_MM, tolerance=0.01):
    if not actual or len(actual) != 3:
        return False
    return all(abs(float(left) - float(right)) <= tolerance for left, right in zip(sorted(actual), sorted(expected)))


def summarize_tool_result(result):
    """Remove base64 image payloads before writing a local JSON report."""

    summary = deepcopy(result)
    for content in summary.get("content", []) if isinstance(summary, dict) else []:
        if content.get("type") == "image" and "data" in content:
            content["data"] = "[IMAGE_DATA_REMOVED]"
    return summary


def structured(result):
    """Return structured MCP data while accepting already-unwrapped responses."""

    if not isinstance(result, dict):
        return {}
    return result.get("structuredContent", result)


def find_body(context, name):
    for component in context.get("components", []):
        for body in component.get("bodies", []):
            if body.get("name") == name:
                return body
    return None


class MCPClient:
    def __init__(self, url, token, timeout=90):
        self.url = url.rstrip("/") + "/"
        self.token = token
        self.timeout = timeout
        self.request_id = 0

    def call(self, method, params=None):
        self.request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params or {},
        }
        request = Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.load(response)
        except HTTPError as error:
            try:
                body = error.read().decode("utf-8", errors="replace")
            finally:
                error.close()
            raise RuntimeError(f"MCP HTTP {error.code}: {body[:500]}") from None
        if "error" in result:
            raise RuntimeError(f"MCP JSON-RPC error: {json.dumps(result['error'], ensure_ascii=False)}")
        return result["result"]

    def tool(self, name, arguments=None):
        return self.call("tools/call", {"name": name, "arguments": arguments or {}})


class _AcceptanceStopped(RuntimeError):
    """Stop dependent acceptance steps after a recorded prerequisite failure."""


def _record(steps, name, ok, details=None):
    steps.append({"name": name, "ok": bool(ok), "details": summarize_tool_result(details or {})})
    return ok


def run_acceptance(url, token, export_dir, include_approval_gate=True):
    client = MCPClient(url, token)
    steps = []
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "url": url,
        "expected_plate_mm": EXPECTED_PLATE_MM,
        "steps": steps,
    }

    try:
        initialized = client.call("initialize", {})
        _record(steps, "initialize", "serverInfo" in initialized, initialized)

        listed = client.call("tools/list", {})
        names = {tool["name"] for tool in listed.get("tools", [])}
        _record(
            steps,
            "required_tools",
            REQUIRED_TOOLS <= names,
            {"present": sorted(names), "missing": sorted(REQUIRED_TOOLS - names)},
        )

        status = client.tool("get_fusion_status")
        status_data = structured(status)
        _record(
            steps,
            "fusion_status",
            bool(status_data.get("fusion_available") and status_data.get("active_design")),
            status,
        )

        context_before = client.tool("get_design_context", {"scope": "all", "limit": 200})
        _record(steps, "design_context_before", not context_before.get("isError", False), context_before)

        execution = client.tool(
            "create_parametric_plate",
            build_parametric_plate_arguments(),
        )
        execution_data = structured(execution)
        context_created = client.tool("get_design_context", {"scope": "all", "limit": 300})
        context_created_data = structured(context_created)
        plate = find_body(context_created_data, "MountingPlate")
        parameter_names = {
            parameter.get("name")
            for parameter in context_created_data.get("parameters", [])
        }
        geometry_ok = (
            not execution.get("isError", False)
            and execution_data.get("recomputed", False)
            and plate is not None
            and dimensions_match(plate.get("size_mm"))
            and set(execution_data.get("parameters_created", [])) <= parameter_names
        )
        _record(steps, "mounting_plate_geometry", geometry_ok, execution)
        if not geometry_ok:
            raise _AcceptanceStopped()

        width_update = client.tool(
            "upsert_user_parameter",
            {
                "name": "plate_width",
                "expression": "120 mm",
                "expected_old_expression": "100 mm",
                "comment": "create_parametric_plate:MountingPlate",
            },
        )
        context_updated = client.tool("get_design_context", {"scope": "all", "limit": 300})
        updated_plate = find_body(structured(context_updated), "MountingPlate")
        parameter_update_ok = (
            not width_update.get("isError", False)
            and updated_plate is not None
            and dimensions_match(updated_plate.get("size_mm"), [120.0, 60.0, 5.0])
        )
        _record(steps, "plate_width_parameter_update", parameter_update_ok, width_update)

        for view in ("isometric", "front", "top"):
            screenshot = client.tool(
                "get_viewport_screenshot",
                {"view": view, "width": 768, "height": 768},
            )
            image_ok = any(
                item.get("type") == "image" and bool(item.get("data"))
                for item in screenshot.get("content", [])
            )
            _record(steps, f"screenshot_{view}", image_ok, screenshot)

        export_dir.mkdir(parents=True, exist_ok=True)
        for format_name, suffix in (("step", ".step"), ("stl", ".stl")):
            target = export_dir / f"codex_mounting_plate{suffix}"
            if target.exists():
                target = export_dir / f"codex_mounting_plate_{os.getpid()}{suffix}"
            exported = client.tool(
                "export_design",
                {"format": format_name, "path": str(target.resolve()), "overwrite": False},
            )
            export_ok = (
                not exported.get("isError", False)
                and target.exists()
                and target.stat().st_size > 0
            )
            _record(steps, f"export_{format_name}", export_ok, exported)

        invalid_arguments = build_parametric_plate_arguments()
        invalid_arguments["name"] = "InvalidPlate"
        invalid_arguments["parameter_prefix"] = "invalid_plate"
        invalid_arguments["holes"] = [
            {
                "key": "outside",
                "x_expression": "49 mm",
                "y_expression": "0 mm",
                "diameter_expression": "6 mm",
            }
        ]
        failure = client.tool("create_parametric_plate", invalid_arguments)
        _record(
            steps,
            "error_isolation",
            failure.get("error", {}).get("code") == "PLATE_HOLE_OUT_OF_BOUNDS",
            failure,
        )

        if include_approval_gate:
            gated = client.tool(
                "execute_fusion_python",
                {
                    "intent": "승인 게이트 확인용 파일 접근 및 바디 삭제 시도; Fusion에서 아니요 선택",
                    "code": (
                        "import os\n"
                        "def run(context):\n"
                        "    print(os.getcwd())\n"
                        "    context['rootComponent'].bRepBodies.item(0).deleteMe()"
                    ),
                    "expected_changes": {},
                },
            )
            _record(
                steps,
                "high_risk_gate_denied",
                gated.get("error", {}).get("code") == "POLICY_APPROVAL_REQUIRED",
                gated,
            )
    except _AcceptanceStopped:
        pass
    except (RuntimeError, URLError, TimeoutError, OSError, ValueError) as error:
        _record(steps, "harness_exception", False, {"type": type(error).__name__, "message": str(error)})

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["passed"] = sum(1 for step in steps if step["ok"])
    report["failed"] = sum(1 for step in steps if not step["ok"])
    report["ok"] = bool(steps) and report["failed"] == 0
    report["export_dir"] = str(export_dir)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:9100/")
    parser.add_argument("--export-dir", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--skip-approval-gate", action="store_true")
    parser.add_argument(
        "--confirm-blank-design",
        action="store_true",
        help="Required acknowledgement that the active Fusion document may be modified.",
    )
    args = parser.parse_args(argv)
    if not args.confirm_blank_design:
        parser.error("open a blank Fusion design, then pass --confirm-blank-design")
    token = os.environ.get("FUSION_MCP_TOKEN", "")
    if not token:
        print("FUSION_MCP_TOKEN is not configured.", file=sys.stderr)
        return 2
    export_dir = args.export_dir or Path(tempfile.mkdtemp(prefix="fusion-codex-acceptance-"))
    report = run_acceptance(
        args.url,
        token,
        export_dir,
        include_approval_gate=not args.skip_approval_gate,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
