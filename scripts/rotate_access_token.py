"""Rotate the access_token inside whatsapp_channels.provider_config for one tenant.

Reads new token from VYAPARI_NEW_ACCESS_TOKEN env var (so it never lands in argv).
Decrypts the existing Fernet envelope, swaps access_token, re-encrypts, commits.

Usage:
    VYAPARI_ENCRYPTION_KEY=... \\
    VYAPARI_NEW_ACCESS_TOKEN=EAA... \\
    python scripts/rotate_access_token.py --business-id demo-sharma-motors
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--business-id", required=True)
    args = parser.parse_args()

    new_token = os.environ.get("VYAPARI_NEW_ACCESS_TOKEN", "").strip()
    if not new_token:
        print("[FAIL] VYAPARI_NEW_ACCESS_TOKEN not set", file=sys.stderr)
        return 2

    from sqlalchemy import select

    from database import close_db, get_session_factory, init_db
    from db_models import WhatsAppChannel
    from services.secrets import decrypt_secrets, encrypt_secrets

    await init_db()
    try:
        Session = get_session_factory()
        async with Session() as session:
            result = await session.execute(
                select(WhatsAppChannel).where(
                    WhatsAppChannel.business_id == args.business_id
                )
            )
            channel = result.scalar_one_or_none()
            if not channel:
                print(f"[FAIL] No whatsapp_channels row for {args.business_id!r}", file=sys.stderr)
                return 1

            plaintext = decrypt_secrets(channel.provider_config)
            old_suffix = plaintext.get("access_token", "")[-8:]
            plaintext["access_token"] = new_token
            channel.provider_config = encrypt_secrets(plaintext)
            await session.commit()

            print(f"[PASS] {args.business_id} access_token rotated")
            print(f"  old suffix: ...{old_suffix}")
            print(f"  new suffix: ...{new_token[-8:]}")
            print(f"  pni:        {channel.phone_number_id}")
    finally:
        await close_db()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
