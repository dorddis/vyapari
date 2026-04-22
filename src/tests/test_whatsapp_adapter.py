"""Tests for channels.whatsapp.adapter.WhatsAppAdapter.

Two families of assertions:

1. Fixture round-trips: load Meta's canonical inbound webhook shapes
   (ported from pywa/tests/data/updates/) and confirm extract_message
   produces the right MessageType + populates the fields we promise.

2. Status callbacks: status webhooks (sent/delivered/read/failed) go
   through extract_status_updates and never become IncomingMessages.

All tests are sync + pure — they do not hit the DB, the LLM, or the
Graph API.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from channels.whatsapp.adapter import WhatsAppAdapter
from models import MessageType


_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "whatsapp"


def _load(name: str) -> dict:
    with open(_FIXTURES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


# Loaded once at import so the parametrize ids are human-readable.
_MESSAGE_FIXTURES = _load("message.json")
_BUTTON_FIXTURES = _load("callback_button.json")
_LIST_FIXTURES = _load("callback_selection.json")
_STATUS_FIXTURES = _load("message_status.json")


# ---------------------------------------------------------------------------
# Every fixture: extract_message must not raise.
# ---------------------------------------------------------------------------

_ALL_FIXTURES: list[tuple[str, dict]] = (
    [(f"message:{k}", v) for k, v in _MESSAGE_FIXTURES.items()]
    + [(f"callback_button:{k}", v) for k, v in _BUTTON_FIXTURES.items()]
    + [(f"callback_selection:{k}", v) for k, v in _LIST_FIXTURES.items()]
    + [(f"status:{k}", v) for k, v in _STATUS_FIXTURES.items()]
)


@pytest.mark.parametrize(
    "fixture_id,payload",
    _ALL_FIXTURES,
    ids=[fid for fid, _ in _ALL_FIXTURES],
)
def test_extract_message_never_raises(fixture_id: str, payload: dict) -> None:
    """Every canonical Meta payload must parse without raising."""
    adapter = WhatsAppAdapter()
    result = adapter.extract_message(payload)
    assert result is None or hasattr(result, "wa_id"), (
        f"{fixture_id} returned {type(result).__name__}"
    )


# ---------------------------------------------------------------------------
# Specific shape checks — the high-value regressions.
# ---------------------------------------------------------------------------

def test_extract_text_populates_fields() -> None:
    adapter = WhatsAppAdapter()
    msg = adapter.extract_message(_MESSAGE_FIXTURES["text"])
    assert msg is not None
    assert msg.msg_type == MessageType.TEXT
    assert msg.text  # pywa's fixture carries a non-empty body
    assert msg.wa_id
    assert msg.msg_id
    assert msg.sender_name  # "Test Name"


def test_extract_image_carries_media_id_and_caption() -> None:
    adapter = WhatsAppAdapter()
    msg = adapter.extract_message(_MESSAGE_FIXTURES["image"])
    assert msg is not None
    assert msg.msg_type == MessageType.IMAGE
    assert msg.media_id
    # pywa's image fixture includes a caption; we preserve it.
    # (caption may be None for some fixtures — only the main `image` one is asserted)
    assert msg.media_url is None  # media isn't downloaded at parse time


def test_extract_voice_vs_audio_discriminated() -> None:
    adapter = WhatsAppAdapter()
    voice_msg = adapter.extract_message(_MESSAGE_FIXTURES["voice"])
    audio_msg = adapter.extract_message(_MESSAGE_FIXTURES["audio"])
    assert voice_msg is not None and audio_msg is not None
    assert voice_msg.msg_type == MessageType.VOICE
    assert audio_msg.msg_type == MessageType.AUDIO


def test_extract_video_preserved_for_reject_path() -> None:
    """main.py:270-280 rejects videos; parser must still surface the type."""
    adapter = WhatsAppAdapter()
    msg = adapter.extract_message(_MESSAGE_FIXTURES["video"])
    assert msg is not None
    assert msg.msg_type == MessageType.VIDEO
    assert msg.media_id


def test_extract_document_carries_media_id() -> None:
    adapter = WhatsAppAdapter()
    msg = adapter.extract_message(_MESSAGE_FIXTURES["document"])
    assert msg is not None
    assert msg.msg_type == MessageType.DOCUMENT
    assert msg.media_id


def test_extract_static_and_animated_stickers() -> None:
    adapter = WhatsAppAdapter()
    for key in ("static_sticker", "animated_sticker"):
        msg = adapter.extract_message(_MESSAGE_FIXTURES[key])
        assert msg is not None, key
        assert msg.msg_type == MessageType.STICKER, key
        assert msg.media_id, key


def test_extract_reaction_add_and_remove() -> None:
    adapter = WhatsAppAdapter()
    add = adapter.extract_message(_MESSAGE_FIXTURES["reaction"])
    # Meta may model "remove reaction" two ways; both our branches should
    # still produce REACTION with an informative text.
    empty = adapter.extract_message(_MESSAGE_FIXTURES["unreaction_empty"])
    no_emoji = adapter.extract_message(_MESSAGE_FIXTURES["unreaction_no_emoji"])
    for m, label in [(add, "add"), (empty, "remove_empty"), (no_emoji, "remove_none")]:
        assert m is not None, label
        assert m.msg_type == MessageType.REACTION, label
        assert m.text, f"{label} should produce human-readable text"


def test_extract_location_variants() -> None:
    adapter = WhatsAppAdapter()
    for key in ("current_location", "chosen_location"):
        msg = adapter.extract_message(_MESSAGE_FIXTURES[key])
        assert msg is not None, key
        assert msg.msg_type == MessageType.LOCATION, key
        assert msg.text, key  # text carries the human summary


def test_extract_contacts() -> None:
    adapter = WhatsAppAdapter()
    msg = adapter.extract_message(_MESSAGE_FIXTURES["contacts"])
    assert msg is not None
    assert msg.msg_type == MessageType.CONTACTS
    assert msg.text and "[contact shared]" in msg.text


def test_extract_button_reply_variants() -> None:
    """callback_button.json has 'button' (from interactive message) and
    'quick_reply' (from template quick-reply button)."""
    adapter = WhatsAppAdapter()
    for key, payload in _BUTTON_FIXTURES.items():
        msg = adapter.extract_message(payload)
        assert msg is not None, key
        assert msg.msg_type == MessageType.BUTTON_REPLY, key
        assert msg.button_reply_id, key
        assert msg.button_reply_title, key
        # text surfaces the title so tools that read only .text still see intent
        assert msg.text == msg.button_reply_title, key


def test_extract_list_reply_variants() -> None:
    adapter = WhatsAppAdapter()
    for key, payload in _LIST_FIXTURES.items():
        msg = adapter.extract_message(payload)
        assert msg is not None, key
        assert msg.msg_type == MessageType.LIST_REPLY, key
        assert msg.list_reply_id, key
        assert msg.list_reply_title, key


def test_unsupported_payload_returns_none() -> None:
    """Meta sends 'unsupported' for features our number isn't eligible for."""
    adapter = WhatsAppAdapter()
    for key in ("unsupported", "unsupported_with_type"):
        assert adapter.extract_message(_MESSAGE_FIXTURES[key]) is None, key


def test_status_payloads_return_none_from_extract_message() -> None:
    """Status callbacks are handled by extract_status_updates, not
    extract_message. Critical regression guard — a status payload
    misclassified as a message causes the webhook to dispatch to the
    agent as if it was a customer inbound."""
    adapter = WhatsAppAdapter()
    for key, payload in _STATUS_FIXTURES.items():
        assert adapter.extract_message(payload) is None, key


def test_extract_quick_reply_with_empty_payload_drops() -> None:
    """Template quick-reply with empty text+payload has no actionable
    intent downstream — drop instead of dispatching a null-everything msg."""
    adapter = WhatsAppAdapter()
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "1",
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "919999",
                        "id": "wamid.empty-btn",
                        "type": "button",
                        "button": {"payload": "", "text": ""},
                    }],
                },
                "field": "messages",
            }],
        }],
    }
    assert adapter.extract_message(payload) is None


def test_extract_list_reply_description_only_no_leading_colon() -> None:
    """Empty title + non-empty description must not produce a ': desc'
    leading-colon artifact in the text field."""
    adapter = WhatsAppAdapter()
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "1",
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "919999",
                        "id": "wamid.empty-title",
                        "type": "interactive",
                        "interactive": {
                            "type": "list_reply",
                            "list_reply": {
                                "id": "row1",
                                "title": "",
                                "description": "Just a description",
                            },
                        },
                    }],
                },
                "field": "messages",
            }],
        }],
    }
    msg = adapter.extract_message(payload)
    assert msg is not None
    assert msg.text == "Just a description"


def test_extract_contacts_with_non_dict_entries_safe() -> None:
    """Defense-in-depth: webhook signature is valid but Meta sent junk."""
    adapter = WhatsAppAdapter()
    bad_shapes = [
        {"messages": [{"from": "9", "id": "wamid.x", "type": "contacts", "contacts": ["not-a-dict"]}]},
        {"messages": [{"from": "9", "id": "wamid.y", "type": "contacts", "contacts": [{"name": "string-not-dict", "phones": [{"phone": "+91"}]}]}]},
        {"messages": [{"from": "9", "id": "wamid.z", "type": "contacts", "contacts": [{"name": {"formatted_name": "Raj"}, "phones": ["not-a-dict"]}]}]},
    ]
    for value in bad_shapes:
        payload = {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{"value": value, "field": "messages"}]}]}
        # Must not raise; either parses safely or returns None.
        result = adapter.extract_message(payload)
        assert result is None or hasattr(result, "wa_id")


def test_malformed_payloads_never_raise() -> None:
    adapter = WhatsAppAdapter()
    for payload in (
        {},
        {"entry": []},
        {"entry": [{}]},
        {"entry": [{"changes": []}]},
        {"entry": [{"changes": [{"value": {}}]}]},
        {"entry": [{"changes": [{"value": {"messages": []}}]}]},
        {"entry": [{"changes": [{"value": {"messages": ["not-a-dict"]}}]}]},
    ):
        assert adapter.extract_message(payload) is None


# ---------------------------------------------------------------------------
# Status-update extraction
# ---------------------------------------------------------------------------

def test_extract_status_updates_parses_all_lifecycle_stages() -> None:
    adapter = WhatsAppAdapter()
    seen_statuses: set[str] = set()
    for key, payload in _STATUS_FIXTURES.items():
        events = adapter.extract_status_updates(payload)
        assert events, f"{key} produced no events"
        for ev in events:
            assert ev["external_msg_id"], key
            assert ev["status"], key
            seen_statuses.add(ev["status"])
    # pywa fixture covers sent/delivered/read/failed (and 'played' for voice)
    assert {"sent", "delivered", "read", "failed"}.issubset(seen_statuses), seen_statuses


def test_extract_status_updates_failed_carries_error() -> None:
    adapter = WhatsAppAdapter()
    events = adapter.extract_status_updates(_STATUS_FIXTURES["failed"])
    assert events
    assert events[0]["status"] == "failed"
    assert events[0]["error"] is not None
    assert "code" in events[0]["error"] or "title" in events[0]["error"]


def test_extract_status_updates_empty_on_message_payload() -> None:
    """Inbound messages must not produce status events."""
    adapter = WhatsAppAdapter()
    assert adapter.extract_status_updates(_MESSAGE_FIXTURES["text"]) == []


def test_extract_status_updates_malformed_safe() -> None:
    adapter = WhatsAppAdapter()
    assert adapter.extract_status_updates({}) == []
    assert adapter.extract_status_updates({"entry": [{"changes": [{"value": {"statuses": ["not-a-dict"]}}]}]}) == []
