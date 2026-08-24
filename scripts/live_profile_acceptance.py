"""Validate the dimensioned L-profile flow against a live authenticated Fusion MCP."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.error import URLError

if __package__:
    from scripts.live_acceptance import MCPClient, structured
else:
    from live_acceptance import MCPClient, structured


EXPECTED_FUSION_VERSION = "2704.1.53"
EXPECTED_SERVER_VERSION = "2.3.0"
EXPECTED_PROFILE_MM = [100.0, 60.0, 8.0]
EXPECTED_PARAMETER_NAMES = [
    "l_profile_depth",
    *[
        f"l_profile_p{index}_{axis}"
        for index in range(1, 7)
        for axis in ("x", "y")
    ],
]
REQUIRED_TOOLS = {
    "get_fusion_status",
    "get_design_context",
    "create_orthographic_canvas_set",
    "create_parametric_profile_extrusion",
    "get_viewport_screenshot",
    "undo_last_execution",
    "export_design",
}
_WINDOWS_ABSOLUTE_PATH = re.compile(r"(?i)[A-Z]:\\[^\r\n\"<>|]*")


def build_profile_arguments():
    return {
        "name": "LProfile",
        "parameter_prefix": "l_profile",
        "vertices": [
            {"key": "p1", "x_expression": "-50 mm", "y_expression": "-30 mm"},
            {"key": "p2", "x_expression": "50 mm", "y_expression": "-30 mm"},
            {"key": "p3", "x_expression": "50 mm", "y_expression": "30 mm"},
            {"key": "p4", "x_expression": "10 mm", "y_expression": "30 mm"},
            {"key": "p5", "x_expression": "10 mm", "y_expression": "0 mm"},
            {"key": "p6", "x_expression": "-50 mm", "y_expression": "0 mm"},
        ],
        "depth_expression": "8 mm",
    }


def build_bow_tie_arguments():
    return {
        "name": "BowTieInvalid",
        "parameter_prefix": "bow_tie_invalid",
        "vertices": [
            {"key": "a", "x_expression": "0 mm", "y_expression": "0 mm"},
            {"key": "b", "x_expression": "40 mm", "y_expression": "40 mm"},
            {"key": "c", "x_expression": "0 mm", "y_expression": "40 mm"},
            {"key": "d", "x_expression": "40 mm", "y_expression": "0 mm"},
        ],
        "depth_expression": "8 mm",
    }


def build_canvas_arguments(top_image, front_image):
    return {
        "name": "LReference",
        "views": [
            {
                "image_path": str(Path(top_image).resolve()),
                "plane": "xy",
                "width_expression": "100 mm",
                "opacity": 40,
            },
            {
                "image_path": str(Path(front_image).resolve()),
                "plane": "xz",
                "width_expression": "100 mm",
                "opacity": 40,
            },
        ],
        "dimension_tolerance_mm": 0.01,
    }


def dimensions_match(actual, expected=EXPECTED_PROFILE_MM, tolerance=0.01):
    if not actual or len(actual) != 3:
        return False
    return all(
        abs(float(left) - float(right)) <= tolerance
        for left, right in zip(sorted(actual), sorted(expected))
    )


def sanitize_report_value(value, *, secrets=()):
    """Return a report-safe copy without image bytes, local paths, or secrets."""

    secret_values = tuple(item for item in secrets if item)

    def redact(item, key=None):
        if isinstance(item, dict):
            cleaned = {}
            is_image = item.get("type") == "image"
            for child_key, child_value in item.items():
                if is_image and child_key == "data":
                    cleaned[child_key] = "[IMAGE_DATA_REMOVED]"
                else:
                    cleaned[child_key] = redact(child_value, child_key)
            return cleaned
        if isinstance(item, list):
            return [redact(child) for child in item]
        if isinstance(item, tuple):
            return [redact(child) for child in item]
        if isinstance(item, str):
            if key in {"path", "image_path", "export_dir"}:
                return Path(item).name or "[LOCAL_PATH_REMOVED]"
            cleaned = item
            for secret in secret_values:
                cleaned = cleaned.replace(secret, "[REDACTED]")
            return _WINDOWS_ABSOLUTE_PATH.sub("[LOCAL_PATH_REMOVED]", cleaned)
        return deepcopy(item)

    return redact(value)


def _find_body(context, name):
    for component in context.get("components", []):
        for body in component.get("bodies", []):
            if body.get("name") == name:
                return body
    return None


def _total_bodies(context):
    return sum(len(component.get("bodies", [])) for component in context.get("components", []))


def _total_canvases(context):
    return sum(int(component.get("canvas_count", 0)) for component in context.get("components", []))


def _parameter_names(context):
    return [parameter.get("name") for parameter in context.get("parameters", [])]


class _AcceptanceStopped(RuntimeError):
    pass


def _record(steps, name, ok, details=None, *, secrets=()):
    steps.append(
        {
            "name": name,
            "ok": bool(ok),
            "details": sanitize_report_value(details or {}, secrets=secrets),
        }
    )
    return bool(ok)


def _fixture_summary(path):
    data = Path(path).read_bytes()
    return {
        "name": Path(path).name,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def run_acceptance(url, token, export_dir, top_image, front_image):
    client = MCPClient(url, token)
    steps = []
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "url": url,
        "expected_profile_mm": EXPECTED_PROFILE_MM,
        "fixtures": [],
        "steps": steps,
    }
    secrets = (token,)

    try:
        top_summary = _fixture_summary(top_image)
        front_summary = _fixture_summary(front_image)
        fixtures_ok = (
            top_summary["bytes"] > 0
            and front_summary["bytes"] > 0
            and top_summary["sha256"] != front_summary["sha256"]
        )
        report["fixtures"] = [top_summary, front_summary]
        _record(steps, "distinct_drawing_fixtures", fixtures_ok, report["fixtures"], secrets=secrets)
        if not fixtures_ok:
            raise _AcceptanceStopped()

        initialized = client.call("initialize", {})
        _record(steps, "initialize", "serverInfo" in initialized, initialized, secrets=secrets)

        listed = client.call("tools/list", {})
        names = [tool.get("name") for tool in listed.get("tools", [])]
        tools_ok = len(names) == 22 and len(set(names)) == 22 and REQUIRED_TOOLS <= set(names)
        _record(
            steps,
            "server_2_3_tool_catalog",
            tools_ok,
            {"count": len(names), "present": sorted(names), "missing": sorted(REQUIRED_TOOLS - set(names))},
            secrets=secrets,
        )

        status = client.tool("get_fusion_status")
        status_data = structured(status)
        status_ok = (
            status_data.get("fusion_available") is True
            and status_data.get("active_design") is True
            and status_data.get("server_version") == EXPECTED_SERVER_VERSION
            and status_data.get("fusion_version") == EXPECTED_FUSION_VERSION
        )
        _record(steps, "fusion_status", status_ok, status, secrets=secrets)

        context_before_result = client.tool("get_design_context", {"scope": "all", "limit": 300})
        context_before = structured(context_before_result)
        blank_ok = (
            not context_before_result.get("isError", False)
            and _total_bodies(context_before) == 0
            and not any((name or "").startswith("l_profile_") for name in _parameter_names(context_before))
        )
        _record(steps, "blank_design_context", blank_ok, context_before_result, secrets=secrets)
        if not (tools_ok and status_ok and blank_ok):
            raise _AcceptanceStopped()

        canvas_result = client.tool(
            "create_orthographic_canvas_set",
            build_canvas_arguments(top_image, front_image),
        )
        canvas_data = structured(canvas_result)
        x_checks = [
            check
            for check in canvas_data.get("shared_dimension_checks", [])
            if check.get("axis") == "x"
        ]
        views = canvas_data.get("set", {}).get("views", [])
        canvas_ok = (
            not canvas_result.get("isError", False)
            and len(views) == 2
            and len({view.get("plane") for view in views}) == 2
            and len(x_checks) == 1
            and x_checks[0].get("difference_mm") == 0.0
            and x_checks[0].get("matched") is True
        )
        _record(steps, "orthographic_canvas_set", canvas_ok, canvas_result, secrets=secrets)
        if not canvas_ok:
            raise _AcceptanceStopped()

        profile_result = client.tool(
            "create_parametric_profile_extrusion",
            build_profile_arguments(),
        )
        profile_data = structured(profile_result)
        context_created_result = client.tool("get_design_context", {"scope": "all", "limit": 400})
        context_created = structured(context_created_result)
        body = _find_body(context_created, "LProfile")
        created_parameter_names = _parameter_names(context_created)
        profile_ok = (
            not profile_result.get("isError", False)
            and profile_data.get("recomputed") is True
            and profile_data.get("parameters_created") == EXPECTED_PARAMETER_NAMES
            and body is not None
            and dimensions_match(body.get("size_mm"))
            and all(name in created_parameter_names for name in EXPECTED_PARAMETER_NAMES)
            and _total_canvases(context_created) == 2
        )
        _record(steps, "parametric_l_profile", profile_ok, profile_result, secrets=secrets)
        if not profile_ok:
            raise _AcceptanceStopped()

        for view in ("top", "front", "isometric"):
            screenshot = client.tool(
                "get_viewport_screenshot",
                {"view": view, "width": 768, "height": 768},
            )
            image_ok = any(
                item.get("type") == "image" and bool(item.get("data"))
                for item in screenshot.get("content", [])
            )
            _record(steps, f"screenshot_{view}", image_ok, screenshot, secrets=secrets)

        export_dir = Path(export_dir)
        export_dir.mkdir(parents=True, exist_ok=True)
        for format_name, suffix in (("step", ".step"), ("stl", ".stl")):
            target = export_dir / f"codex_l_profile{suffix}"
            if target.exists():
                target = export_dir / f"codex_l_profile_{os.getpid()}{suffix}"
            exported = client.tool(
                "export_design",
                {"format": format_name, "path": str(target.resolve()), "overwrite": False},
            )
            export_ok = (
                not exported.get("isError", False)
                and target.exists()
                and target.stat().st_size > 0
            )
            _record(steps, f"export_{format_name}", export_ok, exported, secrets=secrets)

        invalid = client.tool(
            "create_parametric_profile_extrusion",
            build_bow_tie_arguments(),
        )
        context_after_invalid_result = client.tool("get_design_context", {"scope": "all", "limit": 400})
        context_after_invalid = structured(context_after_invalid_result)
        invalid_ok = (
            invalid.get("error", {}).get("code") == "PROFILE_SELF_INTERSECTION"
            and _total_bodies(context_after_invalid) == _total_bodies(context_created)
            and _parameter_names(context_after_invalid) == created_parameter_names
        )
        _record(steps, "bow_tie_rejected_without_delta", invalid_ok, invalid, secrets=secrets)

        undone = client.tool("undo_last_execution")
        undo_data = structured(undone)
        undo_ok = (
            not undone.get("isError", False)
            and undo_data.get("undo_mode") == "parametric_profile_deleted"
        )
        _record(steps, "exact_profile_undo", undo_ok, undone, secrets=secrets)

        final_context_result = client.tool("get_design_context", {"scope": "all", "limit": 400})
        final_context = structured(final_context_result)
        restored_ok = (
            _find_body(final_context, "LProfile") is None
            and not any((name or "").startswith("l_profile_") for name in _parameter_names(final_context))
            and _total_canvases(final_context) == 2
        )
        _record(steps, "profile_removed_canvases_preserved", restored_ok, final_context_result, secrets=secrets)
    except _AcceptanceStopped:
        pass
    except (RuntimeError, URLError, TimeoutError, OSError, ValueError) as error:
        _record(
            steps,
            "harness_exception",
            False,
            {"type": type(error).__name__, "message": str(error)},
            secrets=secrets,
        )

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["passed"] = sum(1 for step in steps if step["ok"])
    report["failed"] = sum(1 for step in steps if not step["ok"])
    report["ok"] = bool(steps) and report["failed"] == 0
    return sanitize_report_value(report, secrets=secrets)


def main(argv=None):
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:9100/")
    parser.add_argument("--export-dir", type=Path)
    parser.add_argument("--top-image", type=Path, default=repo_root / "tests" / "assets" / "profile-l-top.png")
    parser.add_argument("--front-image", type=Path, default=repo_root / "tests" / "assets" / "profile-l-front.png")
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--confirm-blank-design",
        action="store_true",
        help="Required acknowledgement that the active Fusion document may be modified.",
    )
    args = parser.parse_args(argv)
    if not args.confirm_blank_design:
        parser.error("open a blank Fusion Part Design, then pass --confirm-blank-design")
    token = os.environ.get("FUSION_MCP_TOKEN", "")
    if not token:
        print("FUSION_MCP_TOKEN is not configured.", file=sys.stderr)
        return 2
    export_dir = args.export_dir or Path(tempfile.mkdtemp(prefix="fusion-profile-acceptance-"))
    report = run_acceptance(
        args.url,
        token,
        export_dir,
        args.top_image,
        args.front_image,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
