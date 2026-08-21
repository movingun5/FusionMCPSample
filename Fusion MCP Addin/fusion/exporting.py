"""Validated STEP/STL export adapter."""

import hashlib
import json
from pathlib import Path

from ..core.errors import MCPError
from ..core.policy import RiskDecision
from .executor import request_ui_approval
from .snapshot import safe_value


_EXTENSIONS = {
    "step": {".step", ".stp"},
    "stl": {".stl"},
}


def validate_export_request(format_name, path, overwrite=False):
    normalized = str(format_name).lower()
    if normalized not in _EXTENSIONS:
        return {"code": "INVALID_REQUEST", "message": "format must be step or stl"}

    target = Path(path)
    if not target.is_absolute():
        return {"code": "INVALID_REQUEST", "message": "export path must be absolute"}
    if target.suffix.lower() not in _EXTENSIONS[normalized]:
        return {
            "code": "INVALID_REQUEST",
            "message": f"path extension does not match {normalized}",
        }
    if not target.parent.exists() or not target.parent.is_dir():
        return {"code": "INVALID_REQUEST", "message": "export parent directory does not exist"}
    if target.exists() and not overwrite:
        return {
            "code": "EXPORT_TARGET_EXISTS",
            "message": "target exists; set overwrite=true to request Fusion approval",
        }
    return None


def _result_error(error):
    return MCPError(error["code"], error["message"]).to_result()


def _resolve_entity(design, entity_token):
    if not entity_token:
        return design.rootComponent
    resolver = safe_value(design, "findEntityByToken")
    if not callable(resolver):
        raise ValueError("STALE_ENTITY_TOKEN")
    entities = resolver(entity_token)
    if not entities:
        raise ValueError("STALE_ENTITY_TOKEN")
    return entities[0]


def _overwrite_decision(format_name, target):
    payload = json.dumps(
        {"operation": "export_overwrite", "format": format_name, "path": str(target)},
        sort_keys=True,
    )
    return RiskDecision(
        "approval_required",
        ("overwrite", "filesystem"),
        hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    )


def export_with(
    app,
    ui,
    format_name,
    path,
    entity_token=None,
    overwrite=False,
    approval_callback=None,
):
    """Export an entity and verify the resulting file exists and is non-empty."""

    error = validate_export_request(format_name, path, overwrite=overwrite)
    if error:
        return _result_error(error)
    if app is None:
        return MCPError("FUSION_UNAVAILABLE", "Fusion 360 is not available.", True).to_result()
    design = safe_value(app, "activeProduct")
    if design is None or safe_value(design, "rootComponent") is None:
        return MCPError("NO_ACTIVE_DESIGN", "Open or create a Fusion design first.", True).to_result()

    normalized = str(format_name).lower()
    target = Path(path)
    if target.exists() and overwrite:
        decision = _overwrite_decision(normalized, target)
        approved = (
            bool(approval_callback(decision, "Overwrite Fusion export"))
            if approval_callback is not None
            else request_ui_approval(
                ui,
                decision,
                f"Overwrite {target} with a {normalized.upper()} export",
                safe_value(safe_value(app, "activeDocument"), "name"),
            )
        )
        if not approved:
            result = MCPError(
                "POLICY_APPROVAL_REQUIRED",
                "Fusion approval was not granted for export overwrite.",
                details={"code_hash": decision.code_hash, "reasons": list(decision.reasons)},
            ).to_result()
            result["policy"] = decision.to_dict()
            return result

    try:
        entity = _resolve_entity(design, entity_token)
        manager = design.exportManager
        if normalized == "step":
            options = manager.createSTEPExportOptions(str(target), entity)
        else:
            options = manager.createSTLExportOptions(entity, str(target))
        executed = manager.execute(options)
        if executed is False or not target.exists() or target.stat().st_size <= 0:
            return MCPError(
                "EXPORT_FAILED",
                "Fusion did not create a non-empty export file.",
                retryable=True,
                details={"format": normalized, "path": str(target)},
            ).to_result()
        return {
            "isError": False,
            "message": "Fusion export completed and the file was verified.",
            "export": {
                "format": normalized,
                "path": str(target),
                "size_bytes": target.stat().st_size,
                "entity_token": entity_token,
                "overwritten": bool(overwrite),
            },
            "content": [{
                "type": "text",
                "text": json.dumps(
                    {"format": normalized, "path": str(target), "size_bytes": target.stat().st_size},
                    ensure_ascii=False,
                ),
            }],
        }
    except ValueError as exception:
        if str(exception) == "STALE_ENTITY_TOKEN":
            return MCPError(
                "STALE_ENTITY_TOKEN",
                "The Fusion entity token is no longer valid; refresh design context.",
                retryable=True,
            ).to_result()
        raise
    except Exception as exception:
        return MCPError(
            "EXPORT_FAILED",
            str(exception),
            retryable=True,
            details={"format": normalized, "path": str(target)},
        ).to_result()
