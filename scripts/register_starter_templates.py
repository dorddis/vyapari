"""Register the starter Meta templates for a business.

Called once per tenant, typically right after onboarding. Each template
goes to Meta for approval (hours for UTILITY, up to days for MARKETING).

Usage
-----
    cd vyapari
    export WHATSAPP_ACCESS_TOKEN=EAAG...
    export WHATSAPP_BUSINESS_ACCOUNT_ID=123456789
    python scripts/register_starter_templates.py --business-id <YOUR_BUSINESS_ID>

Options
-------
    --business-id <id>   Target business (required). Must exist in `businesses`.
    --dry-run            Print what would be registered, don't call Meta.
    --only <name>        Register only one template by name (e.g. "followup_24h").
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT))  # makes `scripts.` imports resolvable

from scripts._starter_templates import STARTER_TEMPLATES  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--business-id", required=True,
                        help="businesses.id row to register templates for")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print planned registrations, don't hit Meta")
    parser.add_argument("--only",
                        help="Register only templates matching this name")
    args = parser.parse_args()

    from database import init_db, close_db
    from services.templates import register_template

    templates = STARTER_TEMPLATES
    if args.only:
        templates = [t for t in templates if t["name"] == args.only]
        if not templates:
            print(f"No template named {args.only!r} in STARTER_TEMPLATES.",
                  file=sys.stderr)
            return 2

    print(f"Planning to register {len(templates)} template(s) for "
          f"business={args.business_id}:")
    for t in templates:
        print(f"  - {t['name']} / {t['language']} ({t['category']})")

    if args.dry_run:
        print("\nDry run — no Meta calls made.")
        return 0

    await init_db()
    try:
        failures: list[tuple[str, str, str]] = []
        for t in templates:
            name, lang = t["name"], t["language"]
            try:
                row = await register_template(
                    business_id=args.business_id,
                    name=name,
                    language=lang,
                    components=t["components"],
                    category=t["category"],
                )
                print(f"[PASS] {name} / {lang} -> status={row.status} "
                      f"meta_id={row.meta_template_id}")
            except Exception as exc:
                print(f"[FAIL] {name} / {lang}: {exc}", file=sys.stderr)
                failures.append((name, lang, str(exc)))

        if failures:
            print(f"\n{len(failures)} template(s) failed to register:")
            for name, lang, err in failures:
                print(f"  - {name} / {lang}: {err}")
            return 1

        print(f"\nAll {len(templates)} template(s) submitted. Run "
              "`scripts/sync_templates.py --business-id ...` after a few "
              "minutes to pull Meta's verdict.")
        return 0
    finally:
        await close_db()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
