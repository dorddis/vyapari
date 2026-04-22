"""Mint a per-business API key.

Usage:
    cd vyapari
    python scripts/mint_api_key.py --business-id <YOUR_BUSINESS_ID> --description "Mobile app key"

Prints the plaintext key ONCE. Store it immediately — the DB only keeps
the SHA-256 hash. Revoke via `python scripts/revoke_api_key.py --id <uuid>`.
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
                        help="businesses.id row to mint a key for")
    parser.add_argument("--description", default="",
                        help="Free-text hint (e.g. 'Mobile app', 'Staging'); "
                             "shown in admin panels, not used for auth")
    args = parser.parse_args()

    from database import init_db, close_db
    from services.api_keys import mint_api_key

    await init_db()
    try:
        minted = await mint_api_key(
            business_id=args.business_id,
            description=args.description,
        )
    finally:
        await close_db()

    print()
    print(f"Minted API key for business_id={minted.business_id!r}")
    print(f"  id:          {minted.id}")
    print(f"  prefix:      {minted.key_prefix}...")
    print(f"  description: {minted.description or '<none>'}")
    print()
    print("  PLAINTEXT (stored ONLY in your client — not re-shown):")
    print(f"  {minted.plaintext}")
    print()
    print("Use in requests as:")
    print(f"  X-API-Key: {minted.plaintext}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
