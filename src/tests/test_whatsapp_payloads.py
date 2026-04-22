"""Assert that each whatsapp.py helper + adapter method produces the
canonical Graph API payload Meta expects.

No network. Every test patches httpx.AsyncClient so we capture the
payload that would have been POSTed and assert its shape. Expected
shapes come from research/WHATSAPP_CLOUD_API_REFERENCE.md and the
Meta-official fbsamples repos cloned at
research/reference-implementations/.

The point isn't to exhaustively test every field — it's to catch
regressions when someone edits whatsapp.py or the adapter and
accidentally changes the wire format (common source of Meta 400s).
"""

from __future__ import annotations

import pytest
from unittest.mock import patch

import whatsapp


# ---------------------------------------------------------------------------
# Mock httpx.AsyncClient
# ---------------------------------------------------------------------------

class _MockResponse:
    def __init__(
        self,
        body: dict | None = None,
        *,
        status_code: int = 200,
    ) -> None:
        self._body = body if body is not None else {"messages": [{"id": "wamid.mock-1"}]}
        self.status_code = status_code
        # `content` is truthy when the body is non-empty — _post_message
        # short-circuits to {} on empty content.
        self.content = b"{}" if self._body else b""
        self.text = ""

    def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> None:
        return None


class _Captor:
    """Recording mock — collects everything AsyncClient.post was given.

    By default every call returns a success response (200 + messages[0].id).
    Use `next_response` to override the next response (for error-path tests).
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.next_response: _MockResponse | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def post(self, url, **kwargs):
        self.calls.append(
            {
                "url": url,
                "json": kwargs.get("json"),
                "data": kwargs.get("data"),
                "files": kwargs.get("files"),
                "timeout": kwargs.get("timeout"),
            }
        )
        if self.next_response is not None:
            resp, self.next_response = self.next_response, None
            return resp
        if kwargs.get("files"):
            return _MockResponse({"id": "media-mock-1"})
        return _MockResponse()


@pytest.fixture
def captor() -> _Captor:
    """Patches whatsapp.httpx.AsyncClient with a call captor."""
    cap = _Captor()
    with patch("whatsapp.httpx.AsyncClient", lambda: cap):
        yield cap


# ---------------------------------------------------------------------------
# whatsapp.py — per-helper payload shapes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_text_payload(captor: _Captor) -> None:
    await whatsapp.send_text("919999", "hello")
    assert captor.calls[0]["json"] == {
        "messaging_product": "whatsapp",
        "to": "919999",
        "type": "text",
        "text": {"body": "hello"},
    }


@pytest.mark.asyncio
async def test_send_image_payload(captor: _Captor) -> None:
    await whatsapp.send_image("919999", "https://cdn.example/pic.jpg", caption="look")
    p = captor.calls[0]["json"]
    assert p["type"] == "image"
    assert p["image"] == {"link": "https://cdn.example/pic.jpg", "caption": "look"}


@pytest.mark.asyncio
async def test_send_audio_by_id_payload(captor: _Captor) -> None:
    await whatsapp.send_audio("919999", media_id="m1")
    assert captor.calls[0]["json"]["audio"] == {"id": "m1"}


@pytest.mark.asyncio
async def test_send_audio_requires_id_or_link() -> None:
    with pytest.raises(ValueError, match="media_id or link"):
        await whatsapp.send_audio("919999")


@pytest.mark.asyncio
async def test_send_video_payload_link(captor: _Captor) -> None:
    await whatsapp.send_video("919999", link="https://x.com/v.mp4", caption="demo")
    p = captor.calls[0]["json"]
    assert p["type"] == "video"
    assert p["video"] == {"link": "https://x.com/v.mp4", "caption": "demo"}


@pytest.mark.asyncio
async def test_send_document_payload_with_filename(captor: _Captor) -> None:
    await whatsapp.send_document(
        "919999", media_id="d1", filename="price.pdf", caption="see"
    )
    p = captor.calls[0]["json"]
    assert p["document"] == {"id": "d1", "filename": "price.pdf", "caption": "see"}


@pytest.mark.asyncio
async def test_send_sticker_payload(captor: _Captor) -> None:
    await whatsapp.send_sticker("919999", "s1")
    assert captor.calls[0]["json"]["sticker"] == {"id": "s1"}


@pytest.mark.asyncio
async def test_send_reaction_add_and_remove(captor: _Captor) -> None:
    await whatsapp.send_reaction("919999", "wamid.x", "\U0001f44d")
    await whatsapp.send_reaction("919999", "wamid.x", "")
    assert captor.calls[0]["json"]["reaction"] == {
        "message_id": "wamid.x",
        "emoji": "\U0001f44d",
    }
    assert captor.calls[1]["json"]["reaction"] == {
        "message_id": "wamid.x",
        "emoji": "",
    }


@pytest.mark.asyncio
async def test_send_location_payload(captor: _Captor) -> None:
    await whatsapp.send_location("919999", 19.076, 72.88, name="X", address="Y")
    p = captor.calls[0]["json"]
    assert p["location"] == {
        "latitude": 19.076,
        "longitude": 72.88,
        "name": "X",
        "address": "Y",
    }


@pytest.mark.asyncio
async def test_send_contacts_payload(captor: _Captor) -> None:
    await whatsapp.send_contacts(
        "919999",
        [{"name": {"formatted_name": "Raj"}, "phones": [{"phone": "+91", "type": "WORK"}]}],
    )
    p = captor.calls[0]["json"]
    assert p["type"] == "contacts"
    assert len(p["contacts"]) == 1


@pytest.mark.asyncio
async def test_send_contacts_rejects_empty() -> None:
    with pytest.raises(ValueError, match="at least one contact"):
        await whatsapp.send_contacts("919999", [])


@pytest.mark.asyncio
async def test_send_interactive_buttons_full(captor: _Captor) -> None:
    await whatsapp.send_interactive_buttons(
        "919999",
        "pick one",
        [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}],
        header_text="Options",
        footer="footer",
    )
    inter = captor.calls[0]["json"]["interactive"]
    assert inter["type"] == "button"
    assert inter["body"] == {"text": "pick one"}
    assert inter["header"] == {"type": "text", "text": "Options"}
    assert inter["footer"] == {"text": "footer"}
    buttons = inter["action"]["buttons"]
    assert buttons[0] == {"type": "reply", "reply": {"id": "a", "title": "A"}}


@pytest.mark.asyncio
async def test_send_interactive_buttons_rejects_more_than_three() -> None:
    with pytest.raises(ValueError, match="max 3"):
        await whatsapp.send_interactive_buttons(
            "919999", "x", [{"id": f"b{i}", "title": f"B{i}"} for i in range(4)]
        )


@pytest.mark.asyncio
async def test_send_interactive_buttons_rejects_empty() -> None:
    with pytest.raises(ValueError, match="at least one button"):
        await whatsapp.send_interactive_buttons("919999", "x", [])


@pytest.mark.asyncio
async def test_send_interactive_list_payload(captor: _Captor) -> None:
    await whatsapp.send_interactive_list(
        "919999",
        "pick",
        "View",
        [{"title": "Section", "rows": [{"id": "r1", "title": "Row1"}]}],
        header_text="Hdr",
    )
    inter = captor.calls[0]["json"]["interactive"]
    assert inter["type"] == "list"
    assert inter["action"]["button"] == "View"
    assert inter["action"]["sections"][0]["title"] == "Section"


@pytest.mark.asyncio
async def test_send_interactive_list_rejects_too_many_rows() -> None:
    too_many = [{"title": "S", "rows": [{"id": f"r{i}", "title": str(i)} for i in range(11)]}]
    with pytest.raises(ValueError, match="max 10 list rows"):
        await whatsapp.send_interactive_list("919999", "p", "v", too_many)


@pytest.mark.asyncio
async def test_send_interactive_list_rejects_too_many_sections() -> None:
    too_many = [{"title": f"S{i}", "rows": [{"id": f"r{i}", "title": str(i)}]} for i in range(11)]
    with pytest.raises(ValueError, match="max 10 list sections"):
        await whatsapp.send_interactive_list("919999", "p", "v", too_many)


@pytest.mark.asyncio
async def test_send_interactive_list_rejects_zero_rows() -> None:
    with pytest.raises(ValueError, match="at least one row"):
        await whatsapp.send_interactive_list(
            "919999", "p", "v", [{"title": "S", "rows": []}]
        )


@pytest.mark.asyncio
async def test_send_interactive_list_strips_unknown_keys(captor: _Captor) -> None:
    """Extra fields on rows must not be forwarded to Meta (rejects unknown keys)."""
    await whatsapp.send_interactive_list(
        "919999",
        "pick",
        "View",
        [
            {
                "title": "Section",
                "extra_section_key": "ignored",
                "rows": [
                    {
                        "id": "r1",
                        "title": "Row1",
                        "description": "Desc",
                        "evil_key": "should not appear",
                    }
                ],
            }
        ],
    )
    row = captor.calls[0]["json"]["interactive"]["action"]["sections"][0]["rows"][0]
    assert set(row.keys()) == {"id", "title", "description"}, row


@pytest.mark.asyncio
async def test_send_interactive_cta_url_payload(captor: _Captor) -> None:
    await whatsapp.send_interactive_cta_url(
        "919999", "see site", "Open", "https://example.com"
    )
    inter = captor.calls[0]["json"]["interactive"]
    assert inter["type"] == "cta_url"
    assert inter["action"]["parameters"] == {
        "display_text": "Open",
        "url": "https://example.com",
    }


@pytest.mark.asyncio
async def test_send_template_payload(captor: _Captor) -> None:
    components = [
        {"type": "header", "parameters": [{"type": "image", "image": {"id": "i1"}}]},
        {"type": "body", "parameters": [{"type": "text", "text": "Rahul"}]},
    ]
    await whatsapp.send_template("919999", "followup", "en", components=components)
    p = captor.calls[0]["json"]
    assert p["type"] == "template"
    assert p["template"] == {
        "name": "followup",
        "language": {"code": "en"},
        "components": components,
    }


@pytest.mark.asyncio
async def test_send_template_no_components(captor: _Captor) -> None:
    """Templates without body params must still go through (rare but valid)."""
    await whatsapp.send_template("919999", "hello_world", "en")
    assert captor.calls[0]["json"]["template"] == {
        "name": "hello_world",
        "language": {"code": "en"},
    }


@pytest.mark.asyncio
async def test_send_typing_on_payload(captor: _Captor) -> None:
    await whatsapp.send_typing_on("wamid.inbound")
    assert captor.calls[0]["json"] == {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": "wamid.inbound",
        "typing_indicator": {"type": "text"},
    }


@pytest.mark.asyncio
async def test_mark_read_payload(captor: _Captor) -> None:
    await whatsapp.mark_read("wamid.x")
    assert captor.calls[0]["json"] == {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": "wamid.x",
    }


# ---------------------------------------------------------------------------
# upload_media — multipart validation + MIME guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_media_rejects_empty_bytes() -> None:
    with pytest.raises(ValueError, match="empty bytes"):
        await whatsapp.upload_media(b"", "audio/ogg")


@pytest.mark.asyncio
async def test_upload_media_rejects_injection_mime() -> None:
    with pytest.raises(ValueError, match="invalid mime_type"):
        await whatsapp.upload_media(b"x", "../etc/passwd")


@pytest.mark.asyncio
async def test_upload_media_accepts_codec_params(captor: _Captor) -> None:
    await whatsapp.upload_media(b"xx", "audio/ogg; codecs=opus", filename="v.ogg")
    call = captor.calls[0]
    assert call["data"] == {
        "messaging_product": "whatsapp",
        "type": "audio/ogg; codecs=opus",
    }
    # files is httpx's tuple form
    name, bytes_, mime = call["files"]["file"]
    assert name == "v.ogg" and bytes_ == b"xx" and mime == "audio/ogg; codecs=opus"


# ---------------------------------------------------------------------------
# Media host allow-list
# ---------------------------------------------------------------------------

def test_is_trusted_media_host_accepts_meta_hosts() -> None:
    for url in (
        "https://lookaside.fbsbx.com/path",
        "https://lookaside-eu.fbsbx.com/path",
        "https://cdn.fbcdn.net/path",
        "https://static.whatsapp.net/path",
        "https://graph.facebook.com/v21.0/12345",
    ):
        assert whatsapp._is_trusted_media_host(url), url


def test_is_trusted_media_host_rejects_attacker_lookalikes() -> None:
    for url in (
        "https://evil.example.com/steal",
        "https://fbsbx.com.evil.org/",
        "https://attacker.evil.com/fbsbx.com.malicious",
        "not-a-url",
        "",
    ):
        assert not whatsapp._is_trusted_media_host(url), url


# ---------------------------------------------------------------------------
# Adapter-level translation: send_template params -> components
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_adapter_send_template_translates_params_to_components(monkeypatch) -> None:
    """Adapter takes flat `params: list[str]` + optional `image_url`; must
    construct the components list Meta expects."""
    from channels.whatsapp.adapter import WhatsAppAdapter

    async def noop_log(*a, **kw):
        return None

    async def bot_role(self, to):
        return "bot"

    monkeypatch.setattr("channels.whatsapp.adapter.log_message", noop_log)
    monkeypatch.setattr(WhatsAppAdapter, "_resolve_outbound_role", bot_role)

    cap = _Captor()
    with patch("whatsapp.httpx.AsyncClient", lambda: cap):
        await WhatsAppAdapter().send_template(
            "919999",
            "followup",
            "en",
            params=["Rahul", "Creta"],
            image_url="https://cdn/car.jpg",
        )

    tmpl = cap.calls[0]["json"]["template"]
    assert tmpl["components"] == [
        {
            "type": "header",
            "parameters": [{"type": "image", "image": {"link": "https://cdn/car.jpg"}}],
        },
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": "Rahul"},
                {"type": "text", "text": "Creta"},
            ],
        },
    ]


@pytest.mark.asyncio
async def test_adapter_send_buttons_image_header(monkeypatch) -> None:
    from channels.whatsapp.adapter import WhatsAppAdapter

    async def noop_log(*a, **kw):
        return None

    async def bot_role(self, to):
        return "bot"

    monkeypatch.setattr("channels.whatsapp.adapter.log_message", noop_log)
    monkeypatch.setattr(WhatsAppAdapter, "_resolve_outbound_role", bot_role)

    cap = _Captor()
    with patch("whatsapp.httpx.AsyncClient", lambda: cap):
        await WhatsAppAdapter().send_buttons(
            "919999",
            "body",
            [{"id": "a", "title": "A"}],
            image_url="https://cdn/x.jpg",
        )

    inter = cap.calls[0]["json"]["interactive"]
    assert inter["header"] == {"type": "image", "image": {"link": "https://cdn/x.jpg"}}


@pytest.mark.asyncio
async def test_adapter_send_contact_splits_name(monkeypatch) -> None:
    from channels.whatsapp.adapter import WhatsAppAdapter

    async def noop_log(*a, **kw):
        return None

    async def bot_role(self, to):
        return "bot"

    monkeypatch.setattr("channels.whatsapp.adapter.log_message", noop_log)
    monkeypatch.setattr(WhatsAppAdapter, "_resolve_outbound_role", bot_role)

    cap = _Captor()
    with patch("whatsapp.httpx.AsyncClient", lambda: cap):
        await WhatsAppAdapter().send_contact("919999", "Raj Kumar", "+91987")

    contact = cap.calls[0]["json"]["contacts"][0]
    assert contact["name"] == {
        "formatted_name": "Raj Kumar",
        "first_name": "Raj",
        "last_name": "Kumar",
    }
    assert contact["phones"] == [{"phone": "+91987", "type": "WORK"}]


@pytest.mark.asyncio
async def test_adapter_send_typing_noop_without_msg_id(monkeypatch) -> None:
    """No replying_to_msg_id -> no HTTP call."""
    from channels.whatsapp.adapter import WhatsAppAdapter

    cap = _Captor()
    with patch("whatsapp.httpx.AsyncClient", lambda: cap):
        await WhatsAppAdapter().send_typing("919999", None)
    assert cap.calls == []


@pytest.mark.asyncio
async def test_adapter_send_typing_swallows_upstream_errors(monkeypatch) -> None:
    """Typing-indicator failures must never block a reply."""
    from channels.whatsapp.adapter import WhatsAppAdapter

    async def boom(_msg_id):
        raise RuntimeError("Graph 500")

    monkeypatch.setattr("channels.whatsapp.adapter.legacy_send_typing_on", boom)
    # Should return None silently — no exception bubbles.
    result = await WhatsAppAdapter().send_typing("919999", "wamid.x")
    assert result is None


# ---------------------------------------------------------------------------
# Error surfacing — _post_message must raise on Meta 4xx/5xx, and
# WhatsAppAdapter must record the failure instead of silently logging a
# success row. (The entire "I sent it but the customer never saw it"
# debugging nightmare this commit family exists to prevent.)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_message_raises_on_4xx() -> None:
    cap = _Captor()
    cap.next_response = _MockResponse(
        {"error": {"code": 131047, "message": "Re-engagement message",
                   "title": "More than 24 hours"}},
        status_code=400,
    )
    with patch("whatsapp.httpx.AsyncClient", lambda: cap):
        with pytest.raises(whatsapp.GraphAPIError) as exc_info:
            await whatsapp.send_text("919999", "hi")
    assert exc_info.value.status_code == 400
    assert exc_info.value.code == 131047


@pytest.mark.asyncio
async def test_post_message_raises_on_2xx_with_error_body() -> None:
    """Some Meta edge cases return an error inside a 200 response."""
    cap = _Captor()
    cap.next_response = _MockResponse(
        {"error": {"code": 131026, "title": "Message Undeliverable"}},
        status_code=200,
    )
    with patch("whatsapp.httpx.AsyncClient", lambda: cap):
        with pytest.raises(whatsapp.GraphAPIError) as exc_info:
            await whatsapp.send_text("919999", "hi")
    assert exc_info.value.code == 131026


@pytest.mark.asyncio
async def test_post_message_success_on_well_formed_200() -> None:
    cap = _Captor()
    with patch("whatsapp.httpx.AsyncClient", lambda: cap):
        body = await whatsapp.send_text("919999", "hi")
    assert body == {"messages": [{"id": "wamid.mock-1"}]}


@pytest.mark.asyncio
async def test_adapter_records_failure_on_graph_error(monkeypatch) -> None:
    """Adapter's _send_and_log must log a delivery_failed row and return
    a `failed-*` external_msg_id when Meta rejects the send."""
    from channels.whatsapp.adapter import WhatsAppAdapter

    captured_log: dict = {}

    async def capture_log(**kwargs):
        captured_log.update(kwargs)

    async def bot_role(self, to):
        return "bot"

    monkeypatch.setattr("channels.whatsapp.adapter.log_message", capture_log)
    monkeypatch.setattr(WhatsAppAdapter, "_resolve_outbound_role", bot_role)

    cap = _Captor()
    cap.next_response = _MockResponse(
        {"error": {"code": 131047, "message": "24h window expired"}},
        status_code=400,
    )
    with patch("whatsapp.httpx.AsyncClient", lambda: cap):
        external_msg_id = await WhatsAppAdapter().send_text("919999", "hi")

    assert external_msg_id.startswith("failed-"), external_msg_id
    assert captured_log["msg_type"] == "text"
    assert captured_log["meta"]["delivery_failed"] is True
    assert captured_log["meta"]["error_code"] == 131047
    assert captured_log["meta"]["error_http_status"] == 400


@pytest.mark.asyncio
async def test_adapter_success_path_records_real_msg_id(monkeypatch) -> None:
    """Sanity: success path still logs with Meta's real wamid, no failed- prefix."""
    from channels.whatsapp.adapter import WhatsAppAdapter

    captured_log: dict = {}

    async def capture_log(**kwargs):
        captured_log.update(kwargs)

    async def bot_role(self, to):
        return "bot"

    monkeypatch.setattr("channels.whatsapp.adapter.log_message", capture_log)
    monkeypatch.setattr(WhatsAppAdapter, "_resolve_outbound_role", bot_role)

    cap = _Captor()  # default success
    with patch("whatsapp.httpx.AsyncClient", lambda: cap):
        external_msg_id = await WhatsAppAdapter().send_text("919999", "hi")

    assert external_msg_id == "wamid.mock-1"
    assert not captured_log.get("meta", {}).get("delivery_failed")
