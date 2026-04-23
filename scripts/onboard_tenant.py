"""Onboard a new tenant — create a business + WhatsApp channel row.

Until Embedded Signup lands (Phase 5), tenants are added by ops:
1. Customer signs up out-of-band (email/call).
2. They share their Meta WABA id, phone number + number id, access
   token, app secret, webhook verify token, and verification pin.
3. Ops runs this CLI:

    # Secrets come from env vars (NOT CLI flags — argv leaks via `ps`):
    export VYAPARI_ONBOARD_ACCESS_TOKEN="EAAG..."
    export VYAPARI_ONBOARD_APP_SECRET="abc123..."
    export VYAPARI_ONBOARD_WEBHOOK_VERIFY_TOKEN="vt_hard_to_guess"  # optional
    export VYAPARI_ONBOARD_VERIFICATION_PIN="1234"                  # optional

    python scripts/onboard_tenant.py \\
        --business-id acme-motors \\
        --name "Acme Motors" \\
        --owner-phone 919812345678 \\
        --vertical used_cars \\
        --waba-id 12345 \\
        --phone-number 15551234567 \\
        --phone-number-id 98765 \\
        --description "Primary key for acme-motors"

    # Unset env vars? The script will prompt via getpass for
    # access-token and app-secret.

4. Script mints an initial API key and prints it ONCE.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))


def _read_secret(env_var: str, prompt_label: str) -> str:
    """Read a secret from env var; fall back to getpass prompt."""
    value = os.environ.get(env_var, "").strip()
    if value:
        return value
    if not sys.stdin.isatty():
        print(
            f"[FAIL] {env_var} not set and no interactive TTY to prompt.",
            file=sys.stderr,
        )
        sys.exit(2)
    return getpass.getpass(f"{prompt_label}: ")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--business-id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--owner-phone", required=True)
    parser.add_argument("--vertical", default="")
    parser.add_argument("--type", dest="type_", default="")
    parser.add_argument("--greeting", default="")
    parser.add_argument("--waba-id", required=True)
    parser.add_argument("--phone-number", required=True)
    parser.add_argument("--phone-number-id", required=True)
    parser.add_argument("--description", default="Primary key")
    parser.add_argument("--source", default="manual", choices=["manual", "embedded_signup"])
    parser.add_argument("--skip-api-key", action="store_true",
                        help="Don't mint an initial API key")
    # Secrets are NOT argparse flags — argv is visible in `ps` and shell
    # history. Read from env vars (VYAPARI_ONBOARD_*) or prompt.
    args = parser.parse_args()

    access_token = _read_secret("VYAPARI_ONBOARD_ACCESS_TOKEN", "Access token")
    app_secret = _read_secret("VYAPARI_ONBOARD_APP_SECRET", "App secret")
    webhook_verify_token = os.environ.get(
        "VYAPARI_ONBOARD_WEBHOOK_VERIFY_TOKEN", ""
    ).strip()
    verification_pin = os.environ.get(
        "VYAPARI_ONBOARD_VERIFICATION_PIN", ""
    ).strip()

    from database import init_db, close_db
    from services.tenant_onboarding import (
        onboard_business,
        provision_whatsapp_channel,
        BusinessExistsError,
        BusinessNotFoundError,
        ChannelAlreadyExistsError,
    )
    from services.api_keys import mint_api_key

    await init_db()
    try:
        try:
            await onboard_business(
                business_id=args.business_id,
                name=args.name,
                owner_phone=args.owner_phone,
                vertical=args.vertical,
                type_=args.type_,
                greeting=args.greeting,
            )
            print(f"[PASS] Created business {args.business_id!r}")
        except BusinessExistsError:
            print(f"[SKIP] Business {args.business_id!r} already exists")

        try:
            await provision_whatsapp_channel(
                business_id=args.business_id,
                phone_number=args.phone_number,
                phone_number_id=args.phone_number_id,
                waba_id=args.waba_id,
                access_token=access_token,
                app_secret=app_secret,
                webhook_verify_token=webhook_verify_token,
                verification_pin=verification_pin,
                source=args.source,
            )
            print(f"[PASS] Provisioned whatsapp_channel pni={args.phone_number_id!r}")
        except BusinessNotFoundError as exc:
            print(f"[FAIL] {exc}", file=sys.stderr)
            return 1
        except ChannelAlreadyExistsError as exc:
            print(f"[FAIL] {exc}", file=sys.stderr)
            return 1

        if not args.skip_api_key:
            minted = await mint_api_key(args.business_id, description=args.description)
            print()
            print("=== API KEY (store now — won't be shown again) ===")
            print(f"  business_id: {minted.business_id}")
            print(f"  id:          {minted.id}")
            print(f"  prefix:      {minted.key_prefix}...")
            print(f"  plaintext:   {minted.plaintext}")
            print()
            print("Use in requests as: `X-API-Key: {...}`")

        print()
        print("Next steps:")
        print(f"  1. Register templates: python scripts/register_starter_templates.py --business-id {args.business_id}")
        print(f"  2. Sync status after Meta approval: python scripts/sync_templates.py --business-id {args.business_id}")
    finally:
        await close_db()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
