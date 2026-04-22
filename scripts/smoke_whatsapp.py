"""Smoke test the WhatsApp webhook path end-to-end.

Posts canonical Cloud API webhook payloads (text, voice, status-update) to a
running instance of the Vyapari server and asserts the handler returns the
right HTTP status. Also checks that a bad signature is rejected.

This is the Phase 0 regression check: it does not exercise outbound Graph
calls (Phase 1 will cover those with respx fixtures). It just proves that
inbound parsing, signature verification, and dispatch routing survive a
real HTTP round-trip.

Usage
-----
1. In a separate terminal, start the server in WhatsApp mode:

       cd vyapari/src
       export CHANNEL_MODE=whatsapp
       export WHATSAPP_ENABLED=true
       export WHATSAPP_ACCESS_TOKEN=dummy
       export WHATSAPP_PHONE_NUMBER_ID=dummy
       export META_APP_SECRET=smoke-secret-change-me
       export WHATSAPP_VERIFY_TOKEN=verify-token
       uvicorn main:app --port 8000

2. In this terminal:

       cd vyapari
       META_APP_SECRET=smoke-secret-change-me python scripts/smoke_whatsapp.py

The two META_APP_SECRET values must match — that is the shared key HMAC
uses to verify inbound webhooks.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

# Make `src/` importable even when the script is invoked from anywhere.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

import httpx  # noqa: E402


# ---------------------------------------------------------------------------
# Canonical payloads (shapes verified against Meta samples + pywa fixtures)
# ---------------------------------------------------------------------------

def _text_payload() -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "102290129340398",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550783881",
                                "phone_number_id": "106540352242922",
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Ramesh Patil"},
                                    "wa_id": "919876543210",
                                }
                            ],
                            "messages": [
                                {
                                    "from": "919876543210",
                                    "id": "wamid.smoke-text-0001",
                                    "timestamp": "1749416383",
                                    "type": "text",
                                    "text": {"body": "Creta chahiye 8 lakh ke under"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def _voice_payload() -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "102290129340398",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550783881",
                                "phone_number_id": "106540352242922",
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Ramesh Patil"},
                                    "wa_id": "919876543210",
                                }
                            ],
                            "messages": [
                                {
                                    "from": "919876543210",
                                    "id": "wamid.smoke-voice-0001",
                                    "timestamp": "1749416390",
                                    "type": "audio",
                                    "audio": {
                                        "id": "media-xyz",
                                        "mime_type": "audio/ogg; codecs=opus",
                                        "voice": True,
                                        "sha256": "deadbeef",
                                    },
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def _status_payload() -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "102290129340398",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550783881",
                                "phone_number_id": "106540352242922",
                            },
                            "statuses": [
                                {
                                    "id": "wamid.smoke-outbound-0001",
                                    "status": "delivered",
                                    "timestamp": "1749416400",
                                    "recipient_id": "919876543210",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# HMAC + HTTP helpers
# ---------------------------------------------------------------------------

def _sign(secret: str, body: bytes) -> str:
    """Compute the X-Hub-Signature-256 value Meta expects."""
    digest = hmac.new(
        key=secret.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


async def _post(client: httpx.AsyncClient, url: str, payload: dict, secret: str, *, bad_sig: bool = False) -> httpx.Response:
    body = json.dumps(payload).encode("utf-8")
    sig = _sign(secret, body)
    if bad_sig:
        sig = "sha256=ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    return await client.post(
        url,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sig,
        },
        timeout=15,
    )


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

async def run(base_url: str, secret: str) -> int:
    url = base_url.rstrip("/") + "/webhook"
    failures: list[str] = []

    async with httpx.AsyncClient() as client:
        # 1. Valid text webhook -> 200
        resp = await _post(client, url, _text_payload(), secret)
        label = "text + valid sig"
        if resp.status_code == 200:
            print(f"[PASS] {label}: {resp.status_code} {resp.text.strip()}")
        else:
            failures.append(f"{label}: got {resp.status_code} body={resp.text!r}")

        # 2. Voice webhook -> 200 (extract_message returns VOICE; dispatch
        #    will try to transcribe via main.py:200-230; that may fail if
        #    OPENAI_API_KEY isn't set, but the webhook endpoint itself still
        #    returns 200 because processing is backgrounded).
        resp = await _post(client, url, _voice_payload(), secret)
        label = "voice + valid sig"
        if resp.status_code == 200:
            print(f"[PASS] {label}: {resp.status_code} {resp.text.strip()}")
        else:
            failures.append(f"{label}: got {resp.status_code} body={resp.text!r}")

        # 3. Status callback -> 200 (handler returns ok; extract_message
        #    returns None; no background task queued).
        resp = await _post(client, url, _status_payload(), secret)
        label = "status update + valid sig"
        if resp.status_code == 200:
            print(f"[PASS] {label}: {resp.status_code} {resp.text.strip()}")
        else:
            failures.append(f"{label}: got {resp.status_code} body={resp.text!r}")

        # 4. Bad signature -> 403
        resp = await _post(client, url, _text_payload(), secret, bad_sig=True)
        label = "text + bad sig"
        if resp.status_code == 403:
            print(f"[PASS] {label}: {resp.status_code} (rejected as expected)")
        else:
            failures.append(
                f"{label}: got {resp.status_code} (expected 403) body={resp.text!r}"
            )

    if failures:
        print()
        print(f"{len(failures)} case(s) FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print()
    print("All smoke cases passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test the WhatsApp webhook.")
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="Base URL of the running Vyapari server (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--secret",
        default=os.environ.get("META_APP_SECRET", ""),
        help="Shared HMAC secret. Defaults to $META_APP_SECRET.",
    )
    args = parser.parse_args()

    if not args.secret:
        print(
            "ERROR: META_APP_SECRET is not set. Pass --secret or export it in the "
            "environment. It must match the secret the server was started with.",
            file=sys.stderr,
        )
        return 2

    return asyncio.run(run(args.url, args.secret))


if __name__ == "__main__":
    sys.exit(main())
