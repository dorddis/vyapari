"""onboard_tenant reads secrets from env, not CLI argv."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


_SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "onboard_tenant.py"


def test_onboard_script_does_not_define_secret_cli_flags() -> None:
    """argparse must not expose --access-token / --app-secret /
    --webhook-verify-token / --verification-pin. They'd leak via ps auxww."""
    source = _SCRIPT.read_text(encoding="utf-8")
    forbidden_flags = [
        '--access-token',
        '--app-secret',
        '--webhook-verify-token',
        '--verification-pin',
    ]
    for flag in forbidden_flags:
        # Only flag uses in `add_argument(...)` calls count. Docstring
        # references to old flags would be text-level mentions.
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "attr", None) == "add_argument"
            ):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and arg.value == flag:
                        pytest.fail(
                            f"{flag!r} is still an argparse flag — "
                            "secrets must come from env vars"
                        )


def test_onboard_script_reads_from_env_vars() -> None:
    """Source must reference the VYAPARI_ONBOARD_* env vars."""
    source = _SCRIPT.read_text(encoding="utf-8")
    assert "VYAPARI_ONBOARD_ACCESS_TOKEN" in source
    assert "VYAPARI_ONBOARD_APP_SECRET" in source
