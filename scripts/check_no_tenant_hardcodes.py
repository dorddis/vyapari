"""Grep fence — reject any new reference to the legacy single-tenant
constants outside their sanctioned homes.

Run by the pre-commit hook and by CI. Exit non-zero if any banned
pattern appears outside the whitelist.

Banned patterns:
    DEFAULT_BUSINESS_ID   — env constant for the single-tenant fallback
    DEFAULT_OWNER_PHONE   — same, for the seed owner
    _DEFAULT_BIZ          — the old module-level shortcut in state.py
    demo-sharma-motors    — literal hardcoded tenant id

Whitelisted files (where these references are legitimate):
    src/config.py                      — env constant definitions
    src/services/business_config.py    — the sanctioned indirection
                                         helpers (default_business_id,
                                         default_owner_phone)
    src/tests/**                       — fixtures + assertions
    supabase/migrations/**             — seed SQL
    scripts/check_no_tenant_hardcodes.py (this file)

Usage:
    python scripts/check_no_tenant_hardcodes.py        # exit 0 if clean
    python scripts/check_no_tenant_hardcodes.py --help
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


_BANNED = re.compile(
    r"(DEFAULT_BUSINESS_ID|DEFAULT_OWNER_PHONE|_DEFAULT_BIZ|demo-sharma-motors)"
)

_REPO_ROOT = Path(__file__).resolve().parent.parent

_WHITELIST_SUFFIXES = (
    "src/config.py",
    "src/services/business_config.py",
    "scripts/check_no_tenant_hardcodes.py",
)

_WHITELIST_DIR_PARTS = (
    "src/tests/",
    "src\\tests\\",
    "supabase/migrations/",
    "supabase\\migrations\\",
    "research/reference-implementations/",
    "research\\reference-implementations\\",
)


def _is_whitelisted(path: Path) -> bool:
    rel = path.resolve()
    try:
        rel = rel.relative_to(_REPO_ROOT)
    except ValueError:
        return False
    rel_posix = rel.as_posix()
    if any(rel_posix.endswith(suffix) for suffix in _WHITELIST_SUFFIXES):
        return True
    if any(part in rel_posix for part in _WHITELIST_DIR_PARTS):
        return True
    return False


def _scan_file(path: Path) -> list[tuple[int, str]]:
    """Return (line_no, matched_line) for every banned match in the file."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError, OSError):
        return []
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(text.splitlines(), start=1):
        if _BANNED.search(line):
            hits.append((i, line.rstrip()))
    return hits


def _walk_repo() -> list[Path]:
    """Collect every tracked-looking Python + markdown + yaml file in src/ and scripts/."""
    targets: list[Path] = []
    for sub in ("src", "scripts"):
        root = _REPO_ROOT / sub
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p.is_dir():
                continue
            if any(part.startswith(".") for part in p.parts):
                continue
            if "__pycache__" in p.parts:
                continue
            if p.suffix not in (".py", ".md", ".yaml", ".yml", ".sql"):
                continue
            targets.append(p)
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--list-whitelist",
        action="store_true",
        help="Print the whitelist and exit",
    )
    args = parser.parse_args()

    if args.list_whitelist:
        print("Whitelisted files / dirs:")
        for s in _WHITELIST_SUFFIXES:
            print(f"  - {s}")
        for s in _WHITELIST_DIR_PARTS:
            print(f"  - {s}")
        return 0

    violations = 0
    for path in _walk_repo():
        if _is_whitelisted(path):
            continue
        hits = _scan_file(path)
        if not hits:
            continue
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for line_no, line in hits:
            print(f"{rel}:{line_no}: {line}")
            violations += 1

    if violations:
        print()
        print(f"Found {violations} banned reference(s) to legacy single-tenant")
        print("constants. If the reference is legitimate (e.g. onboarding a new")
        print("sanctioned indirection), update the whitelist in")
        print("scripts/check_no_tenant_hardcodes.py.")
        return 1

    print("OK — no banned tenant-hardcode references outside whitelist.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
