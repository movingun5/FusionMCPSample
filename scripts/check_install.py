"""Check the local Fusion add-in, token, health endpoint, and authenticated MCP."""

import argparse
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _check(code, ok, message, details=None):
    item = {"code": code, "ok": bool(ok), "message": message}
    if details:
        item["details"] = details
    return item


def _probe_json(url, request=None, timeout=2):
    target = request or url
    with urlopen(target, timeout=timeout) as response:
        return response.status, json.load(response)


def build_report(env, addon_path, url="http://127.0.0.1:9100/", probe_server=True):
    """Build a secret-free diagnostic report."""

    addon_path = Path(addon_path)
    manifest = addon_path / "Fusion MCP Addin.manifest"
    checks = []
    checks.append(
        _check(
            "ADDIN_MANIFEST_PRESENT" if manifest.is_file() else "ADDIN_MANIFEST_MISSING",
            manifest.is_file(),
            "Fusion add-in manifest found." if manifest.is_file() else f"Manifest not found under {addon_path}.",
        )
    )

    token = env.get("FUSION_MCP_TOKEN", "")
    checks.append(
        _check(
            "TOKEN_CONFIGURED" if token else "TOKEN_MISSING",
            bool(token),
            "FUSION_MCP_TOKEN is configured." if token else "Set FUSION_MCP_TOKEN and restart Fusion and ChatGPT.",
        )
    )

    if not probe_server:
        checks.append(_check("SERVER_PROBE_SKIPPED", True, "Server probe was explicitly skipped."))
        return {"ok": all(check["ok"] for check in checks), "url": url, "checks": checks}

    health_url = url.rstrip("/") + "/health"
    try:
        status, payload = _probe_json(health_url)
        healthy = status == 200 and payload == {"status": "healthy", "server": "MCP"}
        checks.append(_check("SERVER_HEALTHY" if healthy else "SERVER_HEALTH_INVALID", healthy, "Local MCP health endpoint responded."))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
        checks.append(_check("SERVER_UNAVAILABLE", False, "Local MCP health endpoint is unavailable.", {"type": type(error).__name__}))

    if token:
        request = Request(
            url,
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        )
        try:
            status, payload = _probe_json(url, request=request)
            authenticated = status == 200 and "result" in payload
            checks.append(_check("MCP_AUTHENTICATED" if authenticated else "MCP_AUTH_INVALID", authenticated, "Authenticated MCP initialize completed."))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
            checks.append(_check("MCP_AUTH_FAILED", False, "Authenticated MCP initialize failed.", {"type": type(error).__name__}))

    return {"ok": all(check["ok"] for check in checks), "url": url, "checks": checks}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--addon-path", required=True, type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:9100/")
    parser.add_argument("--skip-server", action="store_true")
    args = parser.parse_args(argv)
    report = build_report(
        os.environ,
        args.addon_path,
        url=args.url,
        probe_server=not args.skip_server,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
