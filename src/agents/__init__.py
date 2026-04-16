"""Bridge local agent modules with the OpenAI Agents SDK package.

This repo has a local ``agents`` package for app code, which would otherwise
shadow the installed OpenAI Agents SDK package of the same name. We find the
SDK's real location and execute its ``__init__`` in this namespace so imports
like ``from agents import Agent`` work.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

# Find the real SDK package by looking through sys.path (skipping ourselves)
_this_dir = str(Path(__file__).resolve().parent)
_sdk_pkg_dir = None

for p in sys.path:
    candidate = Path(p) / "agents"
    if candidate.is_dir() and str(candidate.resolve()) != _this_dir:
        init_file = candidate / "__init__.py"
        if init_file.exists():
            _sdk_pkg_dir = candidate
            break

if _sdk_pkg_dir is not None:
    __path__.insert(0, str(_sdk_pkg_dir))
    exec(_sdk_pkg_dir.joinpath("__init__.py").read_text(), globals(), globals())
else:
    raise ImportError(
        "OpenAI Agents SDK is not installed. "
        "Run: pip install openai-agents"
    )
