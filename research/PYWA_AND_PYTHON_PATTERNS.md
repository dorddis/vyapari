# PyWa Library + Python Implementation Patterns

**Date:** April 14, 2026
**Context:** VibeCon Hackathon -- Python WhatsApp adapter for AI sales agent
**Tech stack:** FastAPI + aiogram (Telegram) + PyWa (WhatsApp) + Gemini LLM

---

## 1. PyWa Library Deep Dive

### Overview

| Attribute | Value |
|-----------|-------|
| GitHub | github.com/david-lev/pywa |
| Stars | ~529 |
| Latest | 3.9.0 (March 11, 2026) |
| License | MIT |
| Python | >= 3.10 |
| Docs | pywa.readthedocs.io |

**Actively maintained** with 70+ releases. The clear winner among Python WhatsApp libraries.

### Installation

```bash
pip install -U "pywa[fastapi]"              # With FastAPI support
pip install -U "pywa[cryptography]"         # Webhook signature validation
pip install -U "pywa[fastapi,cryptography]" # Both
```

### What It Handles

**Sending:** Text, images, video, audio, voice, documents, stickers, interactive buttons (max 3), section lists, location, contacts, templates, reactions, catalog/product messages.

**Receiving (webhook handlers):**
- `on_message` -- all incoming messages
- `on_callback_button` -- button reply clicks
- `on_callback_selection` -- list row selections
- `on_message_status` -- sent/delivered/read/failed
- `on_flow_completion` -- WhatsApp Flows
- `on_raw_update` -- raw webhook payloads

**Media:** `msg.image.download()`, `msg.image.get_bytes()`, `msg.image.stream()`, `msg.image.get_media_url()` (5 min expiry)

**Filters (composable with `&`, `|`, `~`):** `filters.text`, `filters.image`, `filters.voice`, `filters.matches(...)`, `filters.regex(...)`, `filters.from_users(...)`, custom via `filters.new(lambda ...)`

### Native FastAPI Support

YES. Pass a FastAPI app instance as `server=`, it auto-registers GET (verification) and POST (webhook) routes. Does NOT run the server -- you control uvicorn.

### Async Support

YES. Handlers accept both sync and async callbacks. **However:** send methods (`send_message`, etc.) are synchronous internally (httpx sync client). Wrap in `asyncio.to_thread()` for non-blocking sends.

### Code Examples

**Setup with FastAPI:**
```python
from pywa import WhatsApp, types, filters
from fastapi import FastAPI
import uvicorn

app = FastAPI()

wa = WhatsApp(
    phone_id="YOUR_PHONE_ID",
    token="YOUR_ACCESS_TOKEN",
    server=app,
    callback_url="https://yourdomain.com",
    verify_token="your-secret-verify-token",
    app_id=123456,
    app_secret="your-app-secret",
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

**Receiving text messages:**
```python
@wa.on_message(filters.text)
async def on_text(client: WhatsApp, msg: types.Message):
    sender = msg.from_user.wa_id      # "16505551234"
    name = msg.from_user.name
    text = msg.text
    timestamp = msg.timestamp         # datetime (UTC)
```

**Receiving voice notes:**
```python
@wa.on_message(filters.voice)
async def on_voice(client: WhatsApp, msg: types.Message):
    audio = msg.audio
    is_voice = audio.voice            # True for voice notes
    saved_path = audio.download(path="/tmp/voices", filename=f"{msg.id}.ogg")
    # Or: audio_bytes = audio.get_bytes()
```

**Sending images with buttons:**
```python
from pywa.types import Button

client.send_image(
    to="16505551234",
    image="https://example.com/product.jpg",
    caption="2022 Hyundai Creta SX - Rs 12.5L",
    buttons=[
        Button(title="Book Test Drive", callback_data="test_drive:101"),
        Button(title="More Photos", callback_data="photos:101"),
        Button(title="Talk to Sales", callback_data="escalate:101"),
    ],
)
```

**Sending list/section picker:**
```python
from pywa.types import SectionList, Section, SectionRow

client.send_message(
    to="16505551234",
    header="SUVs Under 8 Lakh",
    text="Found 6 SUVs matching your criteria. Tap to see details.",
    footer="Prices negotiable",
    buttons=SectionList(
        button_title="View Cars",
        sections=[
            Section(
                title="Compact SUVs",
                rows=[
                    SectionRow(title="2020 Tata Nexon XZ", callback_data="car:204",
                               description="45K km | Diesel | Rs 7.2L"),
                    SectionRow(title="2021 Hyundai Venue S", callback_data="car:301",
                               description="32K km | Petrol | Rs 7.8L"),
                ],
            ),
        ],
    ),
)
```

**Handling button callbacks:**
```python
@wa.on_callback_button()
async def on_button(client: WhatsApp, btn: types.CallbackButton):
    data = btn.data
    sender = btn.from_user.wa_id
    if data.startswith("test_drive:"):
        product_id = data.split(":")[1]
        btn.reply_text(f"Booking test drive for car #{product_id}...")

@wa.on_callback_selection()
async def on_selection(client: WhatsApp, sel: types.CallbackSelection):
    sel.reply_text(f"You selected: {sel.title}")
```

**Typed callback data:**
```python
from dataclasses import dataclass
from pywa.types import CallbackData

@dataclass(frozen=True, slots=True)
class CarAction(CallbackData):
    action: str   # "test_drive", "photos", "escalate"
    car_id: int

@wa.on_callback_button(factory=CarAction)
async def on_car_action(client: WhatsApp, btn: types.CallbackButton[CarAction]):
    if btn.data.action == "test_drive":
        schedule_test_drive(btn.data.car_id)
```

### Gotchas

1. **Sync HTTP client** -- `send_message()` blocks the event loop. Use `asyncio.to_thread()`.
2. **Media URL expires in 5 minutes** -- download immediately or re-call `get_media_url()`.
3. **Max 3 buttons** -- use SectionList for more options.
4. **Callback data limit: 200 chars**
5. **Python 3.10+ required**
6. **No album/multi-image send** -- send individually.

---

## 2. Alternative Libraries Comparison

| Feature | PyWa 3.9 | heyoo 0.1.2 | whatsapp-python 4.3 | Raw httpx |
|---------|----------|-------------|---------------------|-----------|
| Last updated | Mar 2026 | Mar 2024 (stale) | Nov 2024 | N/A |
| FastAPI native | YES | No | No | DIY |
| Webhook parsing | Full auto | Manual | Basic | Manual |
| Async handlers | YES | Partial | YES | DIY |
| Filters system | Rich | None | None | DIY |
| Interactive msgs | Full | Basic | Basic | DIY |
| WhatsApp Flows | YES | No | No | DIY |

**Recommendation: PyWa is the clear winner.**

---

## 3. Channel Abstraction Pattern

The key architectural piece -- common interface so the AI agent doesn't know whether it's talking to Telegram or WhatsApp.

```python
"""
channel_abstraction.py
Channel abstraction layer for multi-platform messaging.
"""
from __future__ import annotations
import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Sequence


class ChannelType(str, enum.Enum):
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"


class ContentType(str, enum.Enum):
    TEXT = "text"
    IMAGE = "image"
    VOICE = "voice"
    AUDIO = "audio"
    DOCUMENT = "document"
    VIDEO = "video"
    LOCATION = "location"
    INTERACTIVE_BUTTON_REPLY = "interactive_button_reply"
    INTERACTIVE_LIST_REPLY = "interactive_list_reply"


@dataclass
class MediaRef:
    """Platform-agnostic media reference."""
    media_id: str
    mime_type: str | None = None
    filename: str | None = None
    file_size: int | None = None
    url: str | None = None


@dataclass
class ButtonAction:
    id: str
    title: str
    description: str | None = None


@dataclass
class LocationData:
    latitude: float
    longitude: float
    name: str | None = None
    address: str | None = None


@dataclass
class IncomingMessage:
    """Normalized incoming message from any channel."""
    channel: ChannelType
    channel_user_id: str
    channel_chat_id: str
    channel_message_id: str
    user_name: str | None = None

    content_type: ContentType = ContentType.TEXT
    text: str | None = None
    media: MediaRef | None = None
    location: LocationData | None = None
    button_reply: ButtonAction | None = None

    is_reply: bool = False
    reply_to_message_id: str | None = None
    timestamp: float = 0.0
    _raw: object = field(default=None, repr=False)


@dataclass
class OutgoingButton:
    id: str
    title: str           # Max 20 chars for WA, flexible for TG
    description: str | None = None  # Only for WA list rows


@dataclass
class OutgoingMessage:
    """Normalized outgoing message for any channel."""
    text: str | None = None
    media_url: str | None = None
    media_bytes: bytes | None = None
    media_type: ContentType | None = None
    mime_type: str | None = None
    buttons: list[OutgoingButton] | None = None
    is_list: bool = False          # True = WA SectionList, TG inline keyboard
    list_button_title: str = "Options"
    quote_message_id: str | None = None
    template_name: str | None = None    # WA template fallback for 24hr window
    template_params: dict | None = None


class ChannelAdapter(ABC):
    @property
    @abstractmethod
    def channel_type(self) -> ChannelType: ...

    @abstractmethod
    async def send(self, chat_id: str, message: OutgoingMessage) -> str: ...

    @abstractmethod
    async def download_media(self, media_ref: MediaRef) -> bytes: ...
```

### TelegramAdapter (aiogram)

```python
class TelegramAdapter(ChannelAdapter):
    def __init__(self, bot):  # aiogram.Bot
        self.bot = bot

    @property
    def channel_type(self): return ChannelType.TELEGRAM

    @staticmethod
    def normalize(message) -> IncomingMessage:
        """Convert aiogram Message to IncomingMessage."""
        content_type = ContentType.TEXT
        text = message.text or message.caption
        media = None

        if message.voice:
            content_type = ContentType.VOICE
            media = MediaRef(media_id=message.voice.file_id,
                             mime_type=message.voice.mime_type or "audio/ogg")
        elif message.photo:
            content_type = ContentType.IMAGE
            photo = message.photo[-1]
            media = MediaRef(media_id=photo.file_id, mime_type="image/jpeg")
        elif message.document:
            content_type = ContentType.DOCUMENT
            media = MediaRef(media_id=message.document.file_id,
                             mime_type=message.document.mime_type,
                             filename=message.document.file_name)
        elif message.location:
            content_type = ContentType.LOCATION

        return IncomingMessage(
            channel=ChannelType.TELEGRAM,
            channel_user_id=str(message.from_user.id),
            channel_chat_id=str(message.chat.id),
            channel_message_id=str(message.message_id),
            user_name=message.from_user.full_name,
            content_type=content_type, text=text, media=media,
            timestamp=message.date.timestamp(), _raw=message,
        )

    async def send(self, chat_id, message):
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        keyboard = None
        if message.buttons:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=btn.title, callback_data=btn.id)]
                for btn in message.buttons
            ])
        if message.media_url and message.media_type == ContentType.IMAGE:
            sent = await self.bot.send_photo(int(chat_id), photo=message.media_url,
                                              caption=message.text, reply_markup=keyboard)
        elif message.media_url and message.media_type == ContentType.VOICE:
            sent = await self.bot.send_voice(int(chat_id), voice=message.media_url)
        else:
            sent = await self.bot.send_message(int(chat_id), text=message.text or "",
                                                reply_markup=keyboard)
        return str(sent.message_id)

    async def download_media(self, media_ref):
        from io import BytesIO
        buf = BytesIO()
        await self.bot.download(media_ref.media_id, buf)
        return buf.getvalue()
```

### WhatsAppAdapter (PyWa)

```python
class WhatsAppAdapter(ChannelAdapter):
    def __init__(self, wa_client):  # pywa.WhatsApp
        self.wa = wa_client

    @property
    def channel_type(self): return ChannelType.WHATSAPP

    @staticmethod
    def normalize_message(msg) -> IncomingMessage:
        """Convert pywa Message to IncomingMessage."""
        content_type = ContentType.TEXT
        text = msg.text or msg.caption
        media = None

        if msg.voice:
            content_type = ContentType.VOICE
            media = MediaRef(media_id=msg.audio.id, mime_type=msg.audio.mime_type)
        elif msg.image:
            content_type = ContentType.IMAGE
            media = MediaRef(media_id=msg.image.id, mime_type=msg.image.mime_type)
        elif msg.document:
            content_type = ContentType.DOCUMENT
            media = MediaRef(media_id=msg.document.id,
                             mime_type=msg.document.mime_type,
                             filename=msg.document.filename)
        elif msg.location:
            content_type = ContentType.LOCATION

        return IncomingMessage(
            channel=ChannelType.WHATSAPP,
            channel_user_id=msg.from_user.wa_id,
            channel_chat_id=msg.from_user.wa_id,  # WA 1:1
            channel_message_id=msg.id,
            user_name=msg.from_user.name,
            content_type=content_type, text=text, media=media,
            timestamp=msg.timestamp.timestamp(), _raw=msg,
        )

    @staticmethod
    def normalize_callback_button(btn) -> IncomingMessage:
        return IncomingMessage(
            channel=ChannelType.WHATSAPP,
            channel_user_id=btn.from_user.wa_id,
            channel_chat_id=btn.from_user.wa_id,
            channel_message_id=btn.id,
            content_type=ContentType.INTERACTIVE_BUTTON_REPLY,
            button_reply=ButtonAction(id=btn.data, title=btn.title),
            _raw=btn,
        )

    async def send(self, chat_id, message):
        import asyncio
        from pywa.types import Button, SectionList, Section, SectionRow

        if message.template_name:
            result = await asyncio.to_thread(self.wa.send_template,
                                              to=chat_id,
                                              template_name=message.template_name)
            return result.id

        wa_buttons = None
        if message.buttons:
            if message.is_list:
                wa_buttons = SectionList(
                    button_title=message.list_button_title,
                    sections=[Section(title="Options", rows=[
                        SectionRow(title=b.title[:24], callback_data=b.id[:200],
                                   description=b.description)
                        for b in message.buttons
                    ])])
            else:
                wa_buttons = [Button(title=b.title[:20], callback_data=b.id[:200])
                              for b in message.buttons[:3]]

        if message.media_url and message.media_type == ContentType.IMAGE:
            result = await asyncio.to_thread(self.wa.send_image,
                to=chat_id, image=message.media_url,
                caption=message.text, buttons=wa_buttons)
        elif message.media_url and message.media_type == ContentType.VOICE:
            result = await asyncio.to_thread(self.wa.send_voice,
                to=chat_id, voice=message.media_url)
        else:
            result = await asyncio.to_thread(self.wa.send_message,
                to=chat_id, text=message.text or "", buttons=wa_buttons)
        return result.id

    async def download_media(self, media_ref):
        import asyncio
        url = await asyncio.to_thread(self.wa.get_media_url, media_id=media_ref.media_id)
        return await asyncio.to_thread(self.wa.get_media_bytes, url=url.url)
```

### Agent Integration

```python
class SalesAgent:
    def __init__(self, adapters: dict[ChannelType, ChannelAdapter]):
        self.adapters = adapters

    async def process(self, msg: IncomingMessage):
        adapter = self.adapters[msg.channel]
        if msg.content_type == ContentType.VOICE:
            audio = await adapter.download_media(msg.media)
            transcript = await self.transcribe(audio)
            response = await self.generate_response(transcript)
        elif msg.content_type == ContentType.TEXT:
            response = await self.generate_response(msg.text)
        elif msg.content_type == ContentType.INTERACTIVE_BUTTON_REPLY:
            response = await self.handle_button(msg.button_reply)
        else:
            response = OutgoingMessage(text="Got your message!")
        await adapter.send(msg.channel_chat_id, response)
```

---

## 4. Webhook Simulator Script

Simulates WhatsApp Cloud API webhooks for local testing without any Meta account.

```python
"""
wa_webhook_simulator.py
Usage:
    python wa_webhook_simulator.py              # Interactive mode
    python wa_webhook_simulator.py text         # Send text message
    python wa_webhook_simulator.py voice        # Send voice note
    python wa_webhook_simulator.py button       # Send button reply
    python wa_webhook_simulator.py all          # Send all types

Requires: pip install httpx
"""
import json, sys, time, httpx

WEBHOOK_URL = "http://localhost:8000/"
PHONE_NUMBER_ID = "106540352242922"
CUSTOMER_PHONE = "919876543210"
CUSTOMER_NAME = "Test Customer"
WABA_ID = "102290129340398"


def envelope(value_content):
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": WABA_ID, "changes": [{"value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "15550783881",
                         "phone_number_id": PHONE_NUMBER_ID},
            **value_content
        }, "field": "messages"}]}]
    }


def text_message(body="Koi SUV hai 8 lakh ke under?"):
    return envelope({
        "contacts": [{"profile": {"name": CUSTOMER_NAME}, "wa_id": CUSTOMER_PHONE}],
        "messages": [{"from": CUSTOMER_PHONE, "id": f"wamid.text_{int(time.time())}",
                       "timestamp": str(int(time.time())), "type": "text",
                       "text": {"body": body}}]
    })


def voice_message():
    return envelope({
        "contacts": [{"profile": {"name": CUSTOMER_NAME}, "wa_id": CUSTOMER_PHONE}],
        "messages": [{"from": CUSTOMER_PHONE, "id": f"wamid.voice_{int(time.time())}",
                       "timestamp": str(int(time.time())), "type": "audio",
                       "audio": {"id": "media_id_voice_12345",
                                 "mime_type": "audio/ogg; codecs=opus",
                                 "sha256": "abc123", "voice": True}}]
    })


def image_message():
    return envelope({
        "contacts": [{"profile": {"name": CUSTOMER_NAME}, "wa_id": CUSTOMER_PHONE}],
        "messages": [{"from": CUSTOMER_PHONE, "id": f"wamid.image_{int(time.time())}",
                       "timestamp": str(int(time.time())), "type": "image",
                       "image": {"id": "media_id_image_67890",
                                 "mime_type": "image/jpeg",
                                 "caption": "Is this car available?"}}]
    })


def button_reply(button_id="test_drive:101", title="Book Test Drive"):
    return envelope({
        "contacts": [{"profile": {"name": CUSTOMER_NAME}, "wa_id": CUSTOMER_PHONE}],
        "messages": [{"from": CUSTOMER_PHONE, "id": f"wamid.btn_{int(time.time())}",
                       "timestamp": str(int(time.time())), "type": "interactive",
                       "interactive": {"type": "button_reply",
                                       "button_reply": {"id": button_id, "title": title}}}]
    })


def list_reply(row_id="car:204", title="2020 Tata Nexon XZ"):
    return envelope({
        "contacts": [{"profile": {"name": CUSTOMER_NAME}, "wa_id": CUSTOMER_PHONE}],
        "messages": [{"from": CUSTOMER_PHONE, "id": f"wamid.list_{int(time.time())}",
                       "timestamp": str(int(time.time())), "type": "interactive",
                       "interactive": {"type": "list_reply",
                                       "list_reply": {"id": row_id, "title": title,
                                                      "description": "45K km | Diesel | Rs 7.2L"}}}]
    })


def status_update(status="delivered"):
    return envelope({
        "statuses": [{"id": "wamid.original_msg", "status": status,
                       "timestamp": str(int(time.time())),
                       "recipient_id": CUSTOMER_PHONE}]
    })


def failed_status():
    return envelope({
        "statuses": [{"id": "wamid.failed_msg", "status": "failed",
                       "timestamp": str(int(time.time())),
                       "recipient_id": CUSTOMER_PHONE,
                       "errors": [{"code": 131047,
                                   "title": "Re-engagement message",
                                   "message": "More than 24 hours have passed since the customer last replied."}]}]
    })


def send(payload, label):
    print(f"\n--- {label} ---")
    try:
        resp = httpx.post(WEBHOOK_URL, json=payload, timeout=10)
        print(f"Response: {resp.status_code} {resp.text[:200]}")
    except httpx.ConnectError:
        print(f"ERROR: Cannot connect to {WEBHOOK_URL}")


def run_all():
    for payload, label in [
        (text_message(), "Text"), (voice_message(), "Voice"),
        (image_message(), "Image"), (button_reply(), "Button reply"),
        (list_reply(), "List reply"), (status_update("delivered"), "Delivered"),
        (status_update("read"), "Read"), (failed_status(), "Failed (24hr)")
    ]:
        send(payload, label)
        time.sleep(0.5)


if __name__ == "__main__":
    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else "interactive"
    dispatch = {"text": text_message(), "voice": voice_message(),
                "image": image_message(), "button": button_reply(),
                "list": list_reply(), "status": status_update(), "all": None}
    if cmd == "all": run_all()
    elif cmd == "interactive":
        print("Options: text, voice, image, button, list, status, all, quit")
        while (c := input("> ").strip()) != "quit":
            if c == "all": run_all()
            elif c in dispatch: send(dispatch[c], c.title())
    elif cmd in dispatch: send(dispatch[cmd], cmd.title())
```

**IMPORTANT:** Initialize PyWa with `validate_updates=False` for local testing (no HMAC signature):
```python
wa = WhatsApp(phone_id="...", token="test", server=app,
              verify_token="test", validate_updates=False)
```

---

## 5. Media Bridge Pattern

### Format Compatibility

| Format | Telegram | WhatsApp |
|--------|----------|----------|
| Voice notes | OGG Opus | OGG Opus (same!) |
| Images | JPEG, PNG, GIF, WebP, BMP | JPEG, PNG only |
| Audio | MP3, M4A, OGG, many | OGG Opus, MP3, AMR, M4A, AAC only |
| Video | Most formats | H.264 only |

**Voice notes need NO conversion** -- both platforms use OGG Opus.

### Media ID Lifecycle

| Platform | ID persistence | Download URL |
|----------|---------------|-------------|
| Telegram `file_id` | Persistent forever (bot-scoped) | Via `getFile` API |
| WhatsApp `media_id` | 7 days (user), 30 days (business) | 5-minute expiry URL |

**Rule:** Download WhatsApp media on receipt. Don't store media_ids and hope to download later.

### Conversion (when needed)

```python
# Image: WebP/GIF -> JPEG (for WhatsApp)
from PIL import Image
from io import BytesIO

def to_jpeg(data: bytes) -> bytes:
    img = Image.open(BytesIO(data))
    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()

# Audio: unsupported format -> OGG Opus (for WhatsApp)
# Requires ffmpeg installed
import subprocess, tempfile
def to_ogg_opus(data: bytes) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".input", delete=False) as inp:
        inp.write(data)
    out = inp.name + ".ogg"
    subprocess.run(["ffmpeg", "-y", "-i", inp.name, "-c:a", "libopus", "-ac", "1", out],
                   capture_output=True, check=True)
    with open(out, "rb") as f: return f.read()
```

---

## 6. Full Wiring Example

```python
"""main.py -- Dual-channel AI sales agent"""
from fastapi import FastAPI
from pywa import WhatsApp, types as wa_types, filters as wa_filters

app = FastAPI()

wa = WhatsApp(phone_id="YOUR_PHONE_ID", token="YOUR_TOKEN",
              server=app, verify_token="your-verify",
              validate_updates=False)  # True in production

wa_adapter = WhatsAppAdapter(wa)
# tg_adapter = TelegramAdapter(bot)

agent = SalesAgent(adapters={
    ChannelType.WHATSAPP: wa_adapter,
    # ChannelType.TELEGRAM: tg_adapter,
})

@wa.on_message()
async def wa_msg(client, msg):
    await agent.process(WhatsAppAdapter.normalize_message(msg))

@wa.on_callback_button()
async def wa_btn(client, btn):
    await agent.process(WhatsAppAdapter.normalize_callback_button(btn))

@wa.on_callback_selection()
async def wa_sel(client, sel):
    await agent.process(WhatsAppAdapter.normalize_callback_selection(sel))

@wa.on_message_status(wa_filters.failed)
async def wa_fail(client, status):
    print(f"Message {status.id} failed: {status.error}")
    # Switch to template messages for this customer

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

---

## Sources

- [PyWa GitHub](https://github.com/david-lev/pywa)
- [PyWa Docs](https://pywa.readthedocs.io/en/latest/)
- [PyWa Interactive Messages Example](https://pywa.readthedocs.io/en/latest/content/examples/interactive.html)
- [PyWa Handlers Overview](https://pywa.readthedocs.io/en/latest/content/handlers/overview.html)
- [Heyoo GitHub](https://github.com/Neurotech-HQ/heyoo)
- [whatsapp-python GitHub](https://github.com/filipporomani/whatsapp-python)
- [WhatsApp Media API Reference](https://developers.facebook.com/docs/whatsapp/cloud-api/reference/media/)
