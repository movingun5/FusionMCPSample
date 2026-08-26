"""Validate atomic existing-parameter updates against a live Fusion MCP server."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from urllib.error import URLError

if __package__:
    from scripts.live_acceptance import MCPClient, structured
else:
    from live_acceptance import MCPClient, structured


EXPECTED_FUSION_VERSION = "2704.1.53"
EXPECTED_SERVER_VERSION = "2.5.0"
REQUIRED_TOOLS = {
    "get_fusion_status",
    "get_design_context",
    "create_parametric_plate",
    "update_parameter_batch",
    "undo_last_execution",
}


def build_plate_arguments():
    return {
        "name": "BatchPlate",
        "parameter_prefix": "batch_plate",
        "width_expression": "40 mm",
        "height_expression": "30 mm",
        "thickness_expression": "4 mm",
        "holes": [],
        "edge_finish": {"type": "none"},
    }


def build_batch_arguments():
    return {
        "updates": [
            {
                "kind": "user",
                "name": "batch_plate_width",
                "expression": "60 mm",
                "expected_old_expression": "40 mm",
            },
            {
                "kind": "user",
                "name": "batch_plate_thickness",
                "expression": "6 mm",
                "expected_old_expression": "4 mm",
            },
        ]
    }


def _redact(value, secrets=()):
    if isinstance(value, dict):
        return {key: _redact(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, str):
        cleaned = value
        for secret in secrets:
            if secret:
                cleaned = cleaned.replace(secret, "[REDACTED]")
        return cleaned
    return deepcopy(value)


def _record(steps, name, ok, details=None, secrets=()):
    steps.append(
        {
            "name": name,
            "ok": bool(ok),
            "details": _redact(details or {}, secrets),
        }
    )
    return bool(ok)


def _find_body(context, name):
    for component in context.get("components", []):
        for body in component.get("bodies", []):
            if body.get("name") == name:
                return body
    return None


def _parameter_expressions(context):
    return {
        parameter.get("name"): parameter.get("expression")
        for parameter in context.get("parameters", [])
    }


def _matches_state(context, size_mm, width, thickness):
    body = _find_body(context, "BatchPlate")
    expressions = _parameter_expressions(context)
    bounds = (body or {}).get("bounding_box_mm", {})
    minimum = bounds.get("min", [])
    maximum = bounds.get("max", [])
    centered = (
        len(minimum) == 3
        and len(maximum) == 3
        and abs(float(minimum[0]) + float(maximum[0])) <= 0.01
        and abs(float(minimum[1]) + float(maximum[1])) <= 0.01
    )
    return (
        body is not None
        and body.get("size_mm") == size_mm
        and centered
        and expressions.get("batch_plate_width") == width
        and expressions.get("batch_plate_height") == "30 mm"
        and expressions.get("batch_plate_thickness") == thickness
    )


def run_acceptance(url, token):
    client = MCPClient(url, token)
    steps = []
    secrets = (token,)
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "url": url,
        "steps": steps,
    }

    try:
        initialized = client.call("initialize", {})
        _record(steps, "initialize", "serverInfo" in initialized, initialized, secrets)

        listed = client.call("tools/list", {})
        names = [tool.get("name") for tool in listed.get("tools", [])]
        tools_ok = len(names) == 24 and len(set(names)) == 24 and REQUIRED_TOOLS <= set(names)
        _record(
            steps,
            "server_2_5_tool_catalog",
            tools_ok,
            {"count": len(names), "missing": sorted(REQUIRED_TOOLS - set(names))},
            secrets,
        )

        status_result = client.tool("get_fusion_status")
        status = structured(status_result)
        status_ok = (
            status.get("fusion_available") is True
            and status.get("active_design") is True
            and status.get("server_version") == EXPECTED_SERVER_VERSION
            and status.get("fusion_version") == EXPECTED_FUSION_VERSION
        )
        _record(steps, "fusion_status", status_ok, status_result, secrets)

        before_result = client.tool("get_design_context", {"scope": "all", "limit": 300})
        before = structured(before_result)
        blank_ok = (
            _find_body(before, "BatchPlate") is None
            and not any(name.startswith("batch_plate_") for name in _parameter_expressions(before) if name)
            and not any(component.get("bodies") for component in before.get("components", []))
        )
        _record(steps, "blank_design_context", blank_ok, before_result, secrets)
        if not (tools_ok and status_ok and blank_ok):
            raise RuntimeError("Live parameter-batch prerequisites were not met.")

        created = client.tool("create_parametric_plate", build_plate_arguments())
        created_data = structured(created)
        created_ok = (
            not created.get("isError", False)
            and created_data.get("recomputed") is True
            and created_data.get("body") == "BatchPlate"
        )
        _record(steps, "create_batch_plate", created_ok, created, secrets)

        baseline_result = client.tool("get_design_context", {"scope": "all", "limit": 300})
        baseline = structured(baseline_result)
        baseline_ok = _matches_state(baseline, [40.0, 30.0, 4.0], "40 mm", "4 mm")
        _record(steps, "baseline_parameter_state", baseline_ok, baseline_result, secrets)
        if not (created_ok and baseline_ok):
            raise RuntimeError("Fusion did not create the expected batch-test plate.")

        stale_arguments = build_batch_arguments()
        stale_arguments["updates"][0]["expected_old_expression"] = "39 mm"
        stale = client.tool("update_parameter_batch", stale_arguments)
        stale_context_result = client.tool("get_design_context", {"scope": "all", "limit": 300})
        stale_context = structured(stale_context_result)
        stale_ok = (
            stale.get("error", {}).get("code") == "PARAMETER_CONFLICT"
            and _matches_state(stale_context, [40.0, 30.0, 4.0], "40 mm", "4 mm")
        )
        _record(steps, "stale_batch_rejected_without_delta", stale_ok, stale, secrets)

        updated = client.tool("update_parameter_batch", build_batch_arguments())
        updated_data = structured(updated)
        updated_ok = (
            not updated.get("isError", False)
            and updated_data.get("action") == "updated"
            and updated_data.get("recomputed") is True
            and updated_data.get("checkpoint_recorded") is True
        )
        _record(steps, "atomic_parameter_batch", updated_ok, updated, secrets)

        changed_result = client.tool("get_design_context", {"scope": "all", "limit": 300})
        changed = structured(changed_result)
        changed_ok = _matches_state(changed, [60.0, 30.0, 6.0], "60 mm", "6 mm")
        _record(steps, "batch_geometry_propagated", changed_ok, changed_result, secrets)

        undone = client.tool("undo_last_execution")
        restored_result = client.tool("get_design_context", {"scope": "all", "limit": 300})
        restored = structured(restored_result)
        undo_ok = not undone.get("isError", False) and _matches_state(
            restored,
            [40.0, 30.0, 4.0],
            "40 mm",
            "4 mm",
        )
        _record(
            steps,
            "single_undo_restored_whole_batch",
            undo_ok,
            {"undo": undone, "context": restored_result},
            secrets,
        )
    except (RuntimeError, URLError, TimeoutError, OSError, ValueError) as error:
        _record(
            steps,
            "harness_exception",
            False,
            {"type": type(error).__name__, "message": str(error)},
            secrets,
        )

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["passed"] = sum(1 for step in steps if step["ok"])
    report["failed"] = sum(1 for step in steps if not step["ok"])
    report["ok"] = bool(steps) and report["failed"] == 0
    return _redact(report, secrets)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:9100/")
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--confirm-blank-design",
        action="store_true",
        help="Required acknowledgement that a BatchPlate may be created in the active design.",
    )
    args = parser.parse_args(argv)
    if not args.confirm_blank_design:
        parser.error("open a blank Fusion design, then pass --confirm-blank-design")
    token = os.environ.get("FUSION_MCP_TOKEN", "")
    if not token:
        print("FUSION_MCP_TOKEN is not configured.", file=sys.stderr)
        return 2
    report = run_acceptance(args.url, token)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
