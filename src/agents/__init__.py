"""Bridge local agent modules with the OpenAI Agents SDK package.

This repo has a local ``agents`` package for app code, which would otherwise
shadow the installed OpenAI Agents SDK package of the same name. We extend the
package search path to include the SDK package and execute its ``__init__``
module in this namespace so imports like ``from agents import Agent`` work.
"""

from __future__ import annotations

import sys
from pathlib import Path

_sdk_pkg_dir = (
    Path(__file__).resolve().parents[2]
    / ".venv"
    / "lib"
    / f"python{sys.version_info.major}.{sys.version_info.minor}"
    / "site-packages"
    / "agents"
)

if _sdk_pkg_dir.exists():
    __path__.insert(0, str(_sdk_pkg_dir))
    _sdk_init = _sdk_pkg_dir / "__init__.py"
    exec(_sdk_init.read_text(), globals(), globals())
else:
    raise ImportError(
        "OpenAI Agents SDK is not installed in .venv. "
        "Run `pip install -r src/requirements.txt`."
    )
