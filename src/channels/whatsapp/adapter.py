"""WhatsApp channel adapter implementation."""

from __future__ import annotations

import logging
from uuid import uuid4

from channels.base import ChannelAdapter
from models import IncomingMessage, MessageType
from services.message_log import log_message
from whatsapp import (
    GraphAPIError,
    mark_read as legacy_mark_read,
    send_audio as legacy_send_audio,
    send_contacts as legacy_send_contacts,
    send_image as legacy_send_image,
    send_interactive_buttons as legacy_send_interactive_buttons,
    send_interactive_list as legacy_send_interactive_list,
    send_location as legacy_send_location,
    send_template as legacy_send_template,
    send_text as legacy_send_text,
    send_typing_on as legacy_send_typing_on,
    upload_media as legacy_upload_media,
    use_tenant,
)

log = logging.getLogger("vyapari.channels.whatsapp")


def _extract_response_msg_id(response: dict) -> str:
    """Extract message id from Cloud API response."""
    try:
        return str(response["messages"][0]["id"])
    except (KeyError, IndexError, TypeError):
        return f"wa-{uuid4()}"


class WhatsAppAdapter(ChannelAdapter):
    """Adapter that talks to WhatsApp Cloud API.

    Multi-tenant: pass `access_token` + `phone_number_id` at construction
    to bind the adapter to a specific tenant. Each outbound send wraps
    the whatsapp.py helpers in `use_tenant(...)` so per-request creds
    land in the contextvar without leaking across tasks.

    Legacy single-tenant deployments can construct without args — the
    whatsapp.py helpers then fall back to module-level env values.
    """

    def __init__(
        self,
        *,
        access_token: str | None = None,
        phone_number_id: str | None = None,
    ) -> None:
        self._access_token = access_token
        self._phone_number_id = phone_number_id

    def _tenant_ctx(self):
        """Return the per-call credentials context manager, or a no-op
        if the adapter is unbound (falls back to module-level env)."""
        if self._access_token and self._phone_number_id:
            return use_tenant(self._access_token, self._phone_number_id)
        import contextlib as _cl
        return _cl.nullcontext()

    async def _send_and_log(
        self,
        coro,
        *,
        to: str,
        log_text: str,
        msg_type: str,
        images: list[str] | None = None,
    ) -> str:
        """Run a Graph API send coroutine, log success or failure.

        Returns the external message id. On GraphAPIError, returns a
        synthetic `failed-<hex>` id and stamps the log row's meta with
        the error code/body so a later audit can tell what went wrong.
        Never re-raises — the caller (agent, main.py) should keep going.
        """
        role = await self._resolve_outbound_role(to)
        try:
            # Bind per-tenant credentials (if any) around the await so
            # whatsapp.py helpers read this adapter's access_token +
            # phone_number_id instead of the global env values.
            with self._tenant_ctx():
                response = await coro
        except GraphAPIError as exc:
            external_msg_id = f"failed-{uuid4().hex[:12]}"
            log.error(
                "Graph API send failed for %s (code=%s, http=%s): %s",
                to, exc.code, exc.status_code, exc,
            )
            await log_message(
                wa_id=to,
                role=role,
                direction="outbound",
                channel="whatsapp",
                text=log_text,
                msg_type=msg_type,
                external_msg_id=external_msg_id,
                images=images or [],
                meta={
                    "delivery_failed": True,
                    "error_code": exc.code,
                    "error_http_status": exc.status_code,
                    "error_body": exc.body,
                },
            )
            return external_msg_id

        external_msg_id = _extract_response_msg_id(response)
        await log_message(
            wa_id=to,
            role=role,
            direction="outbound",
            channel="whatsapp",
            text=log_text,
            msg_type=msg_type,
            external_msg_id=external_msg_id,
            images=images or [],
        )
        return external_msg_id

    async def _resolve_outbound_role(self, to: str) -> str:
        """Return the logical sender role for a message we're about to send.

        Default is 'bot'. If the customer has an active relay session, the
        role reflects the staff on the other end (owner/sdr) so message
        logs distinguish agent replies from human hijacks.

        DB lookups are best-effort. A DB outage or schema mismatch falls
        back to 'bot' with a warning (previously masked as silent success).
        """
        try:
            import state
            from models import StaffRole

            relay = await state.get_active_relay_for_customer(to)
            if not relay:
                return "bot"
            staff = await state.get_staff(relay.staff_wa_id)
            if staff and staff.role == StaffRole.OWNER:
                return "owner"
            if staff and staff.role == StaffRole.SDR:
                return "sdr"
            return "bot"
        except Exception:
            log.warning("Role resolution failed for %s; defaulting to 'bot'", to, exc_info=True)
            return "bot"

    async def send_text(self, to: str, text: str) -> str:
        return await self._send_and_log(
            legacy_send_text(to, text),
            to=to, log_text=text, msg_type="text",
        )

    async def send_image(self, to: str, image_url: str, caption: str = "") -> str:
        return await self._send_and_log(
            legacy_send_image(to, image_url, caption),
            to=to, log_text=caption or "Image", msg_type="image",
            images=[image_url],
        )

    async def send_audio(
        self, to: str, audio_bytes: bytes, mime_type: str = "audio/ogg; codecs=opus"
    ) -> str:
        """Upload the audio bytes to Meta's media endpoint, then send by media_id."""
        # Trim any codec parameters for the filename hint; the mime_type stays full.
        base_mime = mime_type.split(";")[0].strip()
        ext = base_mime.split("/")[-1] if "/" in base_mime else "bin"
        try:
            with self._tenant_ctx():
                upload_result = await legacy_upload_media(
                    file_bytes=audio_bytes,
                    mime_type=mime_type,
                    filename=f"voice.{ext}",
                )
        except Exception as exc:
            # Upload failures (network, 4xx, bad mime) come back as either
            # httpx.HTTPStatusError or ValueError. Route through the same
            # failure-log path as downstream send errors.
            log.error("upload_media failed for audio to %s: %s", to, exc)
            external_msg_id = f"failed-{uuid4().hex[:12]}"
            role = await self._resolve_outbound_role(to)
            await log_message(
                wa_id=to, role=role, direction="outbound", channel="whatsapp",
                text="Audio", msg_type="audio",
                external_msg_id=external_msg_id,
                meta={"delivery_failed": True, "error_stage": "upload_media",
                      "error_message": str(exc)},
            )
            return external_msg_id
        media_id = upload_result.get("id")
        if not media_id:
            log.error("upload_media returned no id for audio to %s: %s", to, upload_result)
            external_msg_id = f"failed-{uuid4().hex[:12]}"
            role = await self._resolve_outbound_role(to)
            await log_message(
                wa_id=to, role=role, direction="outbound", channel="whatsapp",
                text="Audio", msg_type="audio",
                external_msg_id=external_msg_id,
                meta={"delivery_failed": True, "error_stage": "upload_media",
                      "error_body": upload_result},
            )
            return external_msg_id
        return await self._send_and_log(
            legacy_send_audio(to, media_id=media_id),
            to=to, log_text="Audio", msg_type="audio",
        )

    async def send_buttons(
        self,
        to: str,
        body: str,
        buttons: list[dict],
        header: str | None = None,
        footer: str | None = None,
        image_url: str | None = None,
    ) -> str:
        """Send interactive reply buttons. Max 3 per Meta spec (enforced in helper)."""
        header_media: dict | None = None
        if image_url:
            header_media = {"type": "image", "image": {"link": image_url}}
        titles = ", ".join(button.get("title", "Option") for button in buttons)
        return await self._send_and_log(
            legacy_send_interactive_buttons(
                to=to,
                body=body,
                buttons=buttons,
                header_text=header if not header_media else None,
                header_media=header_media,
                footer=footer,
            ),
            to=to,
            log_text=f"{body}\n[buttons: {titles}]" if titles else body,
            msg_type="interactive_buttons",
            images=[image_url] if image_url else [],
        )

    async def send_list(
        self,
        to: str,
        body: str,
        button_text: str,
        sections: list[dict],
        header: str | None = None,
        footer: str | None = None,
    ) -> str:
        """Send interactive list picker. Max 10 rows across sections."""
        rows: list[str] = []
        for section in sections:
            for row in section.get("rows", []):
                rows.append(row.get("title", "Item"))
        preview = f"{body}\n[{button_text}: {', '.join(rows[:10])}]" if rows else body
        return await self._send_and_log(
            legacy_send_interactive_list(
                to=to,
                body=body,
                button_text=button_text,
                sections=sections,
                header_text=header,
                footer=footer,
            ),
            to=to, log_text=preview, msg_type="interactive_list",
        )

    async def send_location(
        self,
        to: str,
        latitude: float,
        longitude: float,
        name: str = "",
        address: str = "",
    ) -> str:
        label = name or "Location"
        text = f"{label}: {latitude}, {longitude}"
        if address:
            text = f"{text}\n{address}"
        return await self._send_and_log(
            legacy_send_location(
                to=to,
                latitude=latitude,
                longitude=longitude,
                name=name or None,
                address=address or None,
            ),
            to=to, log_text=text, msg_type="location",
        )

    async def send_contact(self, to: str, name: str, phone: str) -> str:
        """Send a single contact card. Minimal shape: name + WORK phone."""
        parts = (name or "").strip().split(None, 1)
        first_name = parts[0] if parts else name
        last_name = parts[1] if len(parts) > 1 else ""
        contact: dict = {
            "name": {
                "formatted_name": name,
                "first_name": first_name,
                **({"last_name": last_name} if last_name else {}),
            },
            "phones": [{"phone": phone, "type": "WORK"}],
        }
        return await self._send_and_log(
            legacy_send_contacts(to, [contact]),
            to=to, log_text=f"Contact: {name} ({phone})", msg_type="contact",
        )

    async def send_template(
        self,
        to: str,
        template_name: str,
        language: str = "en",
        params: list[str] | None = None,
        image_url: str | None = None,
    ) -> str:
        """Send an approved template.

        `params` are positional body parameters that Meta substitutes into
        {{1}}, {{2}}, ... in the approved template body. `image_url` adds
        an image header component. Phase 2's dispatcher replaces this with
        a catalog-aware one that reads the approved schema from the DB.
        """
        components: list[dict] = []
        if image_url:
            components.append(
                {
                    "type": "header",
                    "parameters": [{"type": "image", "image": {"link": image_url}}],
                }
            )
        if params:
            components.append(
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(p)} for p in params],
                }
            )
        params_str = ", ".join(params) if params else ""
        preview = f"Template[{template_name}/{language}]"
        if params_str:
            preview = f"{preview}: {params_str}"
        return await self._send_and_log(
            legacy_send_template(
                to=to,
                name=template_name,
                language=language,
                components=components or None,
            ),
            to=to,
            log_text=preview,
            msg_type="template",
            images=[image_url] if image_url else [],
        )

    async def send_typing(self, to: str, replying_to_msg_id: str | None = None) -> None:
        """Show typing dots for the given inbound message.

        Cloud API v21+ keys typing indicators off the inbound message_id.
        If the caller didn't pass one (legacy callers / web-clone-only
        code paths), we no-op rather than send a malformed request.
        """
        if not replying_to_msg_id:
            return None
        try:
            with self._tenant_ctx():
                await legacy_send_typing_on(replying_to_msg_id)
        except Exception:
            # Typing indicator is a UX nicety; a failure must never block
            # the actual reply. Log and move on.
            log.warning("Typing indicator failed for %s", to, exc_info=True)
        return None

    async def mark_read(self, msg_id: str) -> None:
        with self._tenant_ctx():
            await legacy_mark_read(msg_id)

    def extract_status_updates(self, payload: dict) -> list[dict]:
        """Parse the `statuses[]` array Meta delivers for outbound messages.

        Meta sends these separately from inbound user messages. The event
        lifecycle is sent -> delivered -> read, with `failed` replacing the
        rest on rejection (errors[] carries the reason code). We surface
        every event so services/message_log.update_status can append it to
        the originating outbound row's meta JSON.
        """
        try:
            value = payload["entry"][0]["changes"][0]["value"]
        except (KeyError, IndexError, TypeError):
            return []
        statuses = value.get("statuses") or []
        events: list[dict] = []
        for s in statuses:
            if not isinstance(s, dict):
                continue
            errors = s.get("errors") or []
            first_error = errors[0] if errors and isinstance(errors[0], dict) else None
            events.append(
                {
                    "external_msg_id": s.get("id"),
                    "status": s.get("status"),
                    "timestamp": s.get("timestamp"),
                    "recipient_id": s.get("recipient_id"),
                    "error": first_error,
                }
            )
        return events

    def extract_message(self, payload: dict) -> IncomingMessage | None:
        """Parse a WhatsApp Cloud API webhook payload into an IncomingMessage.

        Returns None for:
        - Non-message payloads (status updates, system events, malformed)
        - `unsupported` message types and anything else Meta adds later
        """
        try:
            value = payload["entry"][0]["changes"][0]["value"]
        except (KeyError, IndexError, TypeError):
            return None

        # Status updates (delivered/read/failed/sent) have `statuses`, not
        # `messages`. They're parsed separately by extract_status_updates,
        # which the webhook handler calls in addition to this function.
        if "statuses" in value:
            return None

        messages = value.get("messages")
        if not messages:
            return None

        msg = messages[0]
        # Defensive: Meta is supposed to send a dict, but mis-sent array
        # entries (e.g. a raw string) must not crash the webhook handler.
        if not isinstance(msg, dict):
            log.warning("messages[0] was %s, not a dict; dropping", type(msg).__name__)
            return None
        wa_id = msg.get("from")
        msg_id = msg.get("id")
        msg_type_raw = msg.get("type", "text")

        if not wa_id or not msg_id:
            return None

        # Sender display name (from WhatsApp profile) if present.
        sender_name: str | None = None
        contacts = value.get("contacts") or []
        if contacts:
            profile = contacts[0].get("profile") or {}
            sender_name = profile.get("name")

        # Branch on message type. Phase 0 covers text + the four media kinds
        # that main.py:200-275 already flows. Everything else is deferred.
        if msg_type_raw == "text":
            text_body = (msg.get("text") or {}).get("body")
            return IncomingMessage(
                wa_id=wa_id,
                text=text_body,
                msg_id=msg_id,
                msg_type=MessageType.TEXT,
                sender_name=sender_name,
            )

        if msg_type_raw == "image":
            image = msg.get("image") or {}
            return IncomingMessage(
                wa_id=wa_id,
                text=None,
                msg_id=msg_id,
                msg_type=MessageType.IMAGE,
                media_id=image.get("id"),
                caption=image.get("caption"),
                sender_name=sender_name,
            )

        if msg_type_raw == "document":
            doc = msg.get("document") or {}
            return IncomingMessage(
                wa_id=wa_id,
                text=None,
                msg_id=msg_id,
                msg_type=MessageType.DOCUMENT,
                media_id=doc.get("id"),
                caption=doc.get("caption"),
                sender_name=sender_name,
            )

        if msg_type_raw == "audio":
            audio = msg.get("audio") or {}
            # Voice notes carry `voice: true`; plain audio uploads don't.
            # Use `is True` (not bool()) so a stringly-typed "false" from
            # a future Meta schema change doesn't misroute to the voice path.
            is_voice = audio.get("voice") is True
            return IncomingMessage(
                wa_id=wa_id,
                text=None,
                msg_id=msg_id,
                msg_type=MessageType.VOICE if is_voice else MessageType.AUDIO,
                media_id=audio.get("id"),
                sender_name=sender_name,
            )

        if msg_type_raw == "video":
            # main.py:270-275 rejects videos with a friendly message.
            # Surface the type so that reject path fires.
            video = msg.get("video") or {}
            return IncomingMessage(
                wa_id=wa_id,
                text=None,
                msg_id=msg_id,
                msg_type=MessageType.VIDEO,
                media_id=video.get("id"),
                caption=video.get("caption"),
                sender_name=sender_name,
            )

        if msg_type_raw == "sticker":
            sticker = msg.get("sticker") or {}
            return IncomingMessage(
                wa_id=wa_id,
                text=None,
                msg_id=msg_id,
                msg_type=MessageType.STICKER,
                media_id=sticker.get("id"),
                sender_name=sender_name,
            )

        if msg_type_raw == "button":
            # Template quick-reply buttons arrive as type="button" with
            # msg.button = {"payload": "...", "text": "..."}. Different
            # shape from interactive.button_reply (which is type=interactive)
            # but same semantics — a tap on a pre-defined choice. Normalize
            # both into MessageType.BUTTON_REPLY.
            btn = msg.get("button") or {}
            title = btn.get("text") or ""
            payload_val = btn.get("payload") or ""
            # If both are empty, nothing actionable downstream — drop it.
            if not title and not payload_val:
                log.info("Dropping empty quick-reply button from %s", wa_id)
                return None
            return IncomingMessage(
                wa_id=wa_id,
                text=title or None,
                msg_id=msg_id,
                msg_type=MessageType.BUTTON_REPLY,
                button_reply_id=payload_val or None,
                button_reply_title=title or None,
                sender_name=sender_name,
            )

        if msg_type_raw == "interactive":
            interactive = msg.get("interactive") or {}
            inter_type = interactive.get("type")
            if inter_type == "button_reply":
                br = interactive.get("button_reply") or {}
                title = br.get("title") or ""
                return IncomingMessage(
                    wa_id=wa_id,
                    # Surface the title as text so tools that only read
                    # `text` still see the user's intent.
                    text=title or None,
                    msg_id=msg_id,
                    msg_type=MessageType.BUTTON_REPLY,
                    button_reply_id=br.get("id"),
                    button_reply_title=title or None,
                    sender_name=sender_name,
                )
            if inter_type == "list_reply":
                lr = interactive.get("list_reply") or {}
                title = lr.get("title") or ""
                desc = lr.get("description") or ""
                # Guard the "" + "Y" edge case that would produce ": Y".
                if title and desc:
                    text = f"{title}: {desc}"
                else:
                    text = title or desc or None
                return IncomingMessage(
                    wa_id=wa_id,
                    text=text,
                    msg_id=msg_id,
                    msg_type=MessageType.LIST_REPLY,
                    list_reply_id=lr.get("id"),
                    list_reply_title=title or None,
                    sender_name=sender_name,
                )
            # nfm_reply / flow replies / anything else — drop for now;
            # Phase 2 flow support will add these.
            log.info("Dropping interactive subtype '%s' from %s", inter_type, wa_id)
            return None

        if msg_type_raw == "location":
            loc = msg.get("location") or {}
            lat = loc.get("latitude")
            lon = loc.get("longitude")
            name = loc.get("name") or ""
            address = loc.get("address") or ""
            # We don't have dedicated lat/lon fields on IncomingMessage; the
            # customer agent today doesn't route on geo. Surface a readable
            # summary as text so the agent can at least reason about it.
            parts = [name] if name else []
            if address:
                parts.append(address)
            parts.append(f"({lat}, {lon})" if lat is not None and lon is not None else "")
            text = " ".join(p for p in parts if p) or None
            return IncomingMessage(
                wa_id=wa_id,
                text=text,
                msg_id=msg_id,
                msg_type=MessageType.LOCATION,
                sender_name=sender_name,
            )

        if msg_type_raw == "contacts":
            cards = msg.get("contacts") or []
            if not cards or not isinstance(cards[0], dict):
                return None
            first = cards[0]
            name_obj = first.get("name") if isinstance(first.get("name"), dict) else {}
            formatted = (name_obj or {}).get("formatted_name") or (name_obj or {}).get("first_name") or "Contact"
            phones = first.get("phones") or []
            phone = None
            if phones and isinstance(phones[0], dict):
                phone = phones[0].get("phone")
            suffix = f" ({phone})" if phone else ""
            return IncomingMessage(
                wa_id=wa_id,
                text=f"[contact shared] {formatted}{suffix}",
                msg_id=msg_id,
                msg_type=MessageType.CONTACTS,
                sender_name=sender_name,
            )

        if msg_type_raw == "reaction":
            reaction = msg.get("reaction") or {}
            emoji = reaction.get("emoji") or ""
            target = reaction.get("message_id") or "?"
            # Emoji "" means the user removed their reaction.
            label = emoji if emoji else "(removed)"
            return IncomingMessage(
                wa_id=wa_id,
                text=f"[reaction {label} on {target}]",
                msg_id=msg_id,
                msg_type=MessageType.REACTION,
                sender_name=sender_name,
            )

        # Unsupported / future types — Meta sends `unsupported` for features
        # our number isn't eligible for (e.g. some order types). Drop safely.
        log.info(
            "Dropping unsupported inbound type '%s' from %s", msg_type_raw, wa_id,
        )
        return None
