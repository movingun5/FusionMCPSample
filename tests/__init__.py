"""Test bootstrap for the Fusion add-in's importable pure-Python modules."""

from pathlib import Path
import importlib.util
import sys
import types


ADDIN_ROOT = Path(__file__).resolve().parents[1] / "Fusion MCP Addin"
if str(ADDIN_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDIN_ROOT))

if "adsk" not in sys.modules:
    adsk_module = types.ModuleType("adsk")
    core_module = types.ModuleType("adsk.core")
    fusion_module = types.ModuleType("adsk.fusion")

    class _Application:
        @staticmethod
        def get():
            return None

    core_module.Application = _Application
    core_module.CustomEventHandler = object
    core_module.CustomEventArgs = object
    adsk_module.core = core_module
    adsk_module.fusion = fusion_module
    sys.modules["adsk"] = adsk_module
    sys.modules["adsk.core"] = core_module
    sys.modules["adsk.fusion"] = fusion_module

PACKAGE_NAME = "fusion_mcp_addin"
if PACKAGE_NAME not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        ADDIN_ROOT / "__init__.py",
        submodule_search_locations=[str(ADDIN_ROOT)],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = package
    spec.loader.exec_module(package)
