"""Test bootstrap for the Fusion add-in's importable pure-Python modules."""

from pathlib import Path
import sys


ADDIN_ROOT = Path(__file__).resolve().parents[1] / "Fusion MCP Addin"
if str(ADDIN_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDIN_ROOT))
