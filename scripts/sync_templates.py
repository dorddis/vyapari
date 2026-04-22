"""Sync template status from Meta into the local message_templates table.

Meta's review lifecycle (PENDING -> APPROVED / REJECTED / PAUSED) is
asynchronous and there's no reliable webhook during the hackathon
window. Run this script on a cron / after `/account_updates` webhook
(Phase 4) to keep the local catalog fresh.

Usage
-----
    cd vyapari
    export WHATSAPP_ACCESS_TOKEN=EAAG...
    export WHATSAPP_BUSINESS_ACCOUNT_ID=123456789
    python scripts/sync_templates.py --business-id demo-sharma-motors
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--business-id", required=True,
                        help="businesses.id row whose templates we're syncing")
    args = parser.parse_args()

    from database import init_db, close_db
    from services.templates import list_templates, sync_templates

    await init_db()
    try:
        try:
            upserted = await sync_templates(args.business_id)
        except Exception as exc:
            print(f"sync_templates failed: {exc}", file=sys.stderr)
            return 1

        # Summary per status
        rows = await list_templates(args.business_id)
        by_status: dict[str, list[str]] = {}
        for r in rows:
            by_status.setdefault(r.status, []).append(f"{r.name}/{r.language}")

        print(f"Synced {upserted} template(s) for {args.business_id}:")
        for status, names in sorted(by_status.items()):
            print(f"  [{status}] {', '.join(names)}")

        return 0
    finally:
        await close_db()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
