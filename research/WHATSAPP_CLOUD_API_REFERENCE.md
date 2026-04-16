# WhatsApp Cloud API - Implementation Reference
## v21.0+ | Compiled Apr 14, 2026 | For Hackathon Team (AI Sales Agent - Used Car Dealers India)

**Base URL:** `https://graph.facebook.com/v21.0/`
**All requests require:** `Authorization: Bearer <ACCESS_TOKEN>` header

---

## 1. Authentication

### Token Types

| Token Type | Lifetime | Use Case |
|-----------|----------|----------|
| **Temporary Token** | ~24 hours | Testing only. Generated in App Dashboard. |
| **System User Token** | Never expires (until revoked) | Production. Created via Business Manager. |
| **User Access Token (short)** | ~1-2 hours | Never use in production. |
| **User Access Token (long)** | ~60 days | Avoid - use System User instead. |

### Getting a Permanent System User Token (Production)

1. Go to **Meta Business Suite > Business Settings > System Users**
2. Click **Add** > name the system user > set role to **Admin**
3. Click **Add Assets** > select your WhatsApp Business Account > toggle full control
4. Click **Generate New Token** > select your app
5. Check the **`whatsapp_business_messaging`** permission
6. Click **Generate Token** > copy and store securely

**This token does NOT expire.** Store it in environment variables, never in code.

### Required Permission

All API calls need the `whatsapp_business_messaging` permission on the token.

### Request Header (All Calls)

```
Authorization: Bearer <ACCESS_TOKEN>
Content-Type: application/json
```

### Security Best Practices

- Never embed tokens in client-side/mobile apps
- Store in env vars or secret managers (Vault, AWS Secrets Manager)
- The **App Secret** (shown in App Dashboard) must remain server-side only
- Enable **App Secret Proof** in production for extra security

---

## 2. Sending Messages

**Endpoint:** `POST https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages`

All messages share this base structure:
```json
{
  "messaging_product": "whatsapp",
  "recipient_type": "individual",
  "to": "<RECIPIENT_PHONE_WITH_COUNTRY_CODE>",
  "type": "<MESSAGE_TYPE>"
}
```

**Phone number format:** Full international format without `+` or `00`. India example: `919876543210`

**Success Response (all message types):**
```json
{
  "messaging_product": "whatsapp",
  "contacts": [
    { "input": "919876543210", "wa_id": "919876543210" }
  ],
  "messages": [
    { "id": "wamid.HBgLMTY1MDM4Nzk0MzkVAgASGBQzQTRBNjU5OUFFRTAzODEwMTQ0RgA=",
      "message_status": "accepted" }
  ]
}
```

`message_status` can be: `accepted`, `held_for_quality_assessment`, or `paused`.

### 2.1 Text Message

```json
{
  "messaging_product": "whatsapp",
  "to": "919876543210",
  "type": "text",
  "text": {
    "preview_url": true,
    "body": "Check out this car: https://example.com/car/123"
  }
}
```

`preview_url: true` renders link previews. Max body length: 4096 characters.

### 2.2 Image Message

```json
{
  "messaging_product": "whatsapp",
  "to": "919876543210",
  "type": "image",
  "image": {
    "id": "1037543291543636",
    "caption": "2022 Maruti Swift - 25,000 km - Front View"
  }
}
```

**OR with a public URL (no upload needed):**
```json
{
  "messaging_product": "whatsapp",
  "to": "919876543210",
  "type": "image",
  "image": {
    "link": "https://yourcdn.com/cars/swift-front.jpg",
    "caption": "2022 Maruti Swift - 25,000 km - Front View"
  }
}
```

Use `id` (media ID from upload) OR `link` (public HTTPS URL), never both.

### 2.3 Video Message

```json
{
  "messaging_product": "whatsapp",
  "to": "919876543210",
  "type": "video",
  "video": {
    "id": "<MEDIA_ID>",
    "caption": "Walk-around video of the car"
  }
}
```

Only H.264 video codec + AAC audio codec supported. Single audio stream or no audio.

### 2.4 Audio Message

```json
{
  "messaging_product": "whatsapp",
  "to": "919876543210",
  "type": "audio",
  "audio": {
    "id": "<MEDIA_ID>"
  }
}
```

**To send as a voice note (plays inline like a recorded message):**
The audio must be OGG format with Opus codec. The MIME type must be `audio/ogg; codecs=opus`. No caption field on audio messages.

### 2.5 Document Message

```json
{
  "messaging_product": "whatsapp",
  "to": "919876543210",
  "type": "document",
  "document": {
    "id": "<MEDIA_ID>",
    "caption": "Vehicle inspection report",
    "filename": "inspection_report_MH02AB1234.pdf"
  }
}
```

`filename` controls what the recipient sees as the download name.

### 2.6 Location Message

```json
{
  "messaging_product": "whatsapp",
  "to": "919876543210",
  "type": "location",
  "location": {
    "latitude": 19.0760,
    "longitude": 72.8777,
    "name": "AutoMax Used Cars",
    "address": "Andheri West, Mumbai 400053"
  }
}
```

### 2.7 Contact Message

```json
{
  "messaging_product": "whatsapp",
  "to": "919876543210",
  "type": "contacts",
  "contacts": [
    {
      "name": {
        "formatted_name": "Raj Kumar - Sales Manager",
        "first_name": "Raj",
        "last_name": "Kumar"
      },
      "phones": [
        {
          "phone": "+919876543210",
          "type": "WORK",
          "wa_id": "919876543210"
        }
      ],
      "org": {
        "company": "AutoMax Used Cars",
        "title": "Sales Manager"
      }
    }
  ]
}
```

### 2.8 Sticker Message

```json
{
  "messaging_product": "whatsapp",
  "to": "919876543210",
  "type": "sticker",
  "sticker": {
    "id": "<MEDIA_ID>"
  }
}
```

Must be `.webp` format. Static: max 100 KB. Animated: max 500 KB.

### 2.9 Reaction Message

```json
{
  "messaging_product": "whatsapp",
  "to": "919876543210",
  "type": "reaction",
  "reaction": {
    "message_id": "wamid.HBgLMTY1MDM4Nzk0MzkVAgASGBQ...",
    "emoji": "\ud83d\udc4d"
  }
}
```

To remove a reaction, send with `"emoji": ""`.

### 2.10 Interactive Message - Reply Buttons (max 3)

```json
{
  "messaging_product": "whatsapp",
  "to": "919876543210",
  "type": "interactive",
  "interactive": {
    "type": "button",
    "header": {
      "type": "text",
      "text": "Interested in this car?"
    },
    "body": {
      "text": "2022 Maruti Swift VXi - 25,000 km\nPrice: Rs 6.5 Lakh\nLocation: Andheri, Mumbai"
    },
    "footer": {
      "text": "Reply to get more details"
    },
    "action": {
      "buttons": [
        {
          "type": "reply",
          "reply": { "id": "btn_schedule_visit", "title": "Schedule Visit" }
        },
        {
          "type": "reply",
          "reply": { "id": "btn_more_photos", "title": "More Photos" }
        },
        {
          "type": "reply",
          "reply": { "id": "btn_price_nego", "title": "Negotiate Price" }
        }
      ]
    }
  }
}
```

Max 3 buttons. Title max 20 chars. ID max 256 chars.

Header can also be `image`, `video`, or `document` type:
```json
"header": {
  "type": "image",
  "image": { "id": "<MEDIA_ID>" }
}
```

### 2.11 Interactive Message - List (max 10 rows, max 10 sections)

```json
{
  "messaging_product": "whatsapp",
  "to": "919876543210",
  "type": "interactive",
  "interactive": {
    "type": "list",
    "header": {
      "type": "text",
      "text": "Available Cars in Your Budget"
    },
    "body": {
      "text": "Here are cars matching your criteria (Rs 5-8 Lakh, Petrol, < 50K km):"
    },
    "footer": {
      "text": "Tap to select a car for details"
    },
    "action": {
      "button": "View Cars",
      "sections": [
        {
          "title": "Hatchbacks",
          "rows": [
            {
              "id": "car_swift_2022",
              "title": "2022 Maruti Swift",
              "description": "Rs 6.5L | 25K km | Petrol | White"
            },
            {
              "id": "car_i20_2021",
              "title": "2021 Hyundai i20",
              "description": "Rs 7.2L | 32K km | Petrol | Red"
            }
          ]
        },
        {
          "title": "Sedans",
          "rows": [
            {
              "id": "car_amaze_2020",
              "title": "2020 Honda Amaze",
              "description": "Rs 7.8L | 40K km | Diesel | Silver"
            }
          ]
        }
      ]
    }
  }
}
```

List button text max 20 chars. Row title max 24 chars. Row description max 72 chars.

### 2.12 Interactive CTA URL Button

```json
{
  "messaging_product": "whatsapp",
  "to": "919876543210",
  "type": "interactive",
  "interactive": {
    "type": "cta_url",
    "header": {
      "type": "text",
      "text": "View Full Listing"
    },
    "body": {
      "text": "Check out the complete details, photos, and service history on our website."
    },
    "footer": {
      "text": "AutoMax Used Cars"
    },
    "action": {
      "name": "cta_url",
      "parameters": {
        "display_text": "View on Website",
        "url": "https://automax.in/cars/swift-2022-MH02AB1234"
      }
    }
  }
}
```

Only 1 CTA URL button per message.

### 2.13 Reply to a Specific Message (Context)

Add `context` to any message type to reply to a specific message:
```json
{
  "messaging_product": "whatsapp",
  "to": "919876543210",
  "type": "text",
  "context": {
    "message_id": "wamid.HBgLMTY1MDM4Nzk0MzkVAgASGBQ..."
  },
  "text": { "body": "Yes, that car is still available!" }
}
```

### 2.14 Mark as Read

```json
POST /{PHONE_NUMBER_ID}/messages

{
  "messaging_product": "whatsapp",
  "status": "read",
  "message_id": "wamid.HBgLMTY1MDM4Nzk0MzkVAgASGBQ..."
}
```

This shows blue double-check marks. Also marks all earlier messages as read. Best practice: mark within 30 days.

### 2.15 Typing Indicator

```json
POST /{PHONE_NUMBER_ID}/messages

{
  "messaging_product": "whatsapp",
  "recipient_type": "individual",
  "to": "919876543210",
  "type": "typing_indicator",
  "typing_indicator": {
    "type": "text"
  }
}
```

Shows "typing..." for up to 25 seconds or until you send a message. Also marks the user's last message as read. Use this when AI processing takes a few seconds.

---

## 3. Receiving Messages (Webhooks)

### 3.1 Webhook Verification (GET - One-Time Setup)

When you register your webhook URL in the App Dashboard, Meta sends a GET request:

```
GET https://your-server.com/webhook?hub.mode=subscribe&hub.verify_token=YOUR_SECRET_TOKEN&hub.challenge=1158201444
```

**Your server must:**
1. Check `hub.mode === "subscribe"`
2. Check `hub.verify_token` matches your secret
3. Respond with HTTP 200 and the `hub.challenge` value as the response body

**Python/Flask example:**
```python
from flask import Flask, request

app = Flask(__name__)
VERIFY_TOKEN = "your-secret-verify-token"

@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403
```

**Node.js/Express example:**
```javascript
app.get("/webhook", (req, res) => {
  const mode = req.query["hub.mode"];
  const token = req.query["hub.verify_token"];
  const challenge = req.query["hub.challenge"];

  if (mode === "subscribe" && token === VERIFY_TOKEN) {
    return res.status(200).send(challenge);
  }
  return res.sendStatus(403);
});
```

### 3.2 Webhook Security - Signature Validation

Every POST from Meta includes an `X-Hub-Signature-256` header:

```
X-Hub-Signature-256: sha256=a]bc123def456...
```

**Validation process:**
1. Get the raw request body (before any JSON parsing)
2. Compute HMAC-SHA256 of the raw body using your **App Secret**
3. Compare with the value after `sha256=` in the header
4. Use constant-time comparison to prevent timing attacks

**Python example:**
```python
import hmac
import hashlib

def verify_signature(payload_body, signature_header, app_secret):
    expected = hmac.new(
        app_secret.encode("utf-8"),
        payload_body,
        hashlib.sha256
    ).hexdigest()
    received = signature_header.replace("sha256=", "")
    return hmac.compare_digest(expected, received)
```

**Node.js example:**
```javascript
const crypto = require("crypto");

function verifySignature(rawBody, signatureHeader, appSecret) {
  const expected = crypto
    .createHmac("sha256", appSecret)
    .update(rawBody)
    .digest("hex");
  const received = signatureHeader.replace("sha256=", "");
  return crypto.timingSafeEqual(
    Buffer.from(expected),
    Buffer.from(received)
  );
}
```

**CRITICAL:** You must use the raw request body, not parsed JSON. With Express, use `express.raw({ type: "application/json" })` middleware before your webhook route.

### 3.3 Webhook Payload Structure (All Incoming Events)

Every webhook POST has this wrapper:
```json
{
  "object": "whatsapp_business_account",
  "entry": [
    {
      "id": "<WHATSAPP_BUSINESS_ACCOUNT_ID>",
      "changes": [
        {
          "value": {
            "messaging_product": "whatsapp",
            "metadata": {
              "display_phone_number": "15550783881",
              "phone_number_id": "106540352242922"
            },
            "contacts": [...],
            "messages": [...],
            "statuses": [...]
          },
          "field": "messages"
        }
      ]
    }
  ]
}
```

`contacts` + `messages` = incoming message event
`statuses` = outgoing message status update

### 3.4 Incoming Text Message

```json
{
  "object": "whatsapp_business_account",
  "entry": [{
    "id": "102290129340398",
    "changes": [{
      "value": {
        "messaging_product": "whatsapp",
        "metadata": {
          "display_phone_number": "15550783881",
          "phone_number_id": "106540352242922"
        },
        "contacts": [{
          "profile": { "name": "Rahul Sharma" },
          "wa_id": "919876543210"
        }],
        "messages": [{
          "from": "919876543210",
          "id": "wamid.HBgLMTY1MDM4Nzk0MzkVAgASGBQzQTRBNjU5OUFFRTAzODEwMTQ0RgA=",
          "timestamp": "1749416383",
          "type": "text",
          "text": {
            "body": "I am looking for a Swift under 7 lakh"
          }
        }]
      },
      "field": "messages"
    }]
  }]
}
```

### 3.5 Incoming Image Message

```json
"messages": [{
  "from": "919876543210",
  "id": "wamid.HBgMOTE5NzQyNDg2MjcxFQIAFhgUM0EzMDg3MzA0QTNBRDM2QzhGQTcA",
  "timestamp": "1703462814",
  "type": "image",
  "image": {
    "mime_type": "image/jpeg",
    "sha256": "Oz7aRmRmALR++ZDmS8LqkZxsjFDSwpTZYyXUAQ9ZlRk=",
    "id": "725847798869820",
    "caption": "Here is the car I want to sell"
  }
}]
```

### 3.6 Incoming Audio / Voice Note

```json
"messages": [{
  "from": "919876543210",
  "id": "wamid.ABCxyz...",
  "timestamp": "1703462900",
  "type": "audio",
  "audio": {
    "mime_type": "audio/ogg; codecs=opus",
    "sha256": "...",
    "id": "725847798869821",
    "voice": true
  }
}]
```

`voice: true` = recorded voice note. `voice: false` or absent = audio file attachment.
Android sends `.ogg` (Opus), iPhone sends `.m4a`.

### 3.7 Incoming Video

```json
"messages": [{
  "from": "919876543210",
  "id": "wamid.ABCxyz...",
  "timestamp": "1703463000",
  "type": "video",
  "video": {
    "mime_type": "video/mp4",
    "sha256": "...",
    "id": "725847798869822",
    "caption": "Video of the car"
  }
}]
```

### 3.8 Incoming Document

```json
"messages": [{
  "from": "919876543210",
  "id": "wamid.ABCxyz...",
  "timestamp": "1703463100",
  "type": "document",
  "document": {
    "mime_type": "application/pdf",
    "sha256": "...",
    "id": "725847798869823",
    "filename": "RC_book_MH02AB1234.pdf",
    "caption": "Here is the RC book"
  }
}]
```

### 3.9 Incoming Location

```json
"messages": [{
  "from": "919876543210",
  "id": "wamid.ABCxyz...",
  "timestamp": "1703463200",
  "type": "location",
  "location": {
    "latitude": 19.0760,
    "longitude": 72.8777,
    "name": "My Location",
    "address": "Andheri West, Mumbai"
  }
}]
```

### 3.10 Incoming Button Reply (from interactive buttons)

```json
"messages": [{
  "from": "919876543210",
  "id": "wamid.ABCxyz...",
  "timestamp": "1703463300",
  "type": "interactive",
  "interactive": {
    "type": "button_reply",
    "button_reply": {
      "id": "btn_schedule_visit",
      "title": "Schedule Visit"
    }
  }
}]
```

### 3.11 Incoming List Reply (from interactive lists)

```json
"messages": [{
  "from": "919876543210",
  "id": "wamid.ABCxyz...",
  "timestamp": "1703463400",
  "type": "interactive",
  "interactive": {
    "type": "list_reply",
    "list_reply": {
      "id": "car_swift_2022",
      "title": "2022 Maruti Swift",
      "description": "Rs 6.5L | 25K km | Petrol | White"
    }
  }
}]
```

### 3.12 Message Status Updates (Outgoing Messages)

```json
{
  "object": "whatsapp_business_account",
  "entry": [{
    "id": "102290129340398",
    "changes": [{
      "value": {
        "messaging_product": "whatsapp",
        "metadata": {
          "display_phone_number": "15550783881",
          "phone_number_id": "106540352242922"
        },
        "statuses": [{
          "id": "wamid.HBgLMTY1MDM4Nzk0MzkVAgARGBI3MTE5MjVBOTE3MDk5QUVFM0YA",
          "status": "delivered",
          "timestamp": "1750263773",
          "recipient_id": "919876543210",
          "conversation": {
            "id": "6ceb9d929c9bdc4f90e967a32f8639b4",
            "origin": { "type": "service" }
          },
          "pricing": {
            "billable": true,
            "pricing_model": "CBP",
            "category": "service"
          }
        }]
      },
      "field": "messages"
    }]
  }]
}
```

**Status progression:** `sent` -> `delivered` -> `read` (or `failed`)

**Failed status includes errors array:**
```json
"statuses": [{
  "id": "wamid.ABCxyz...",
  "status": "failed",
  "timestamp": "1750263773",
  "recipient_id": "919876543210",
  "errors": [{
    "code": 131047,
    "title": "Re-engagement message",
    "message": "More than 24 hours have passed since the customer last replied",
    "error_data": { "details": "Outside 24hr window, use template" }
  }]
}]
```

### 3.13 Webhook Response Requirements

- **MUST respond with HTTP 200 within 5 seconds**
- If you don't, Meta retries with exponential backoff for up to 7 days
- After 7 days of failure, events are permanently lost (no replay API)
- **Best practice:** Return 200 immediately, process async (use a queue)
- Subscribe to the `messages` field in App Dashboard > Webhooks

### 3.14 Webhook Fields to Subscribe

In App Dashboard > WhatsApp > Configuration > Webhook fields:
- **messages** - incoming messages + status updates (this is the main one you need)

---

## 4. Media Handling Deep Dive

### 4.1 Upload Media

```
POST https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/media
```

**Form data (multipart/form-data):**
```bash
curl 'https://graph.facebook.com/v21.0/106540352242922/media' \
  -H 'Authorization: Bearer <ACCESS_TOKEN>' \
  -F 'messaging_product=whatsapp' \
  -F 'file=@/path/to/car_photo.jpg;type=image/jpeg'
```

**Response:**
```json
{ "id": "1037543291543636" }
```

This `id` is the **media ID** you use in send message calls.

### 4.2 Get Media URL (Step 1 of Download)

```
GET https://graph.facebook.com/v21.0/{MEDIA_ID}
Authorization: Bearer <ACCESS_TOKEN>
```

Optional query param: `?phone_number_id=<YOUR_PHONE_NUMBER_ID>` (for validation)

**Response:**
```json
{
  "messaging_product": "whatsapp",
  "url": "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=...",
  "mime_type": "image/jpeg",
  "sha256": "Oz7aRmRmALR++ZDmS8LqkZxsjFDSwpTZYyXUAQ9ZlRk=",
  "file_size": 234567,
  "id": "1037543291543636"
}
```

**The URL expires after 5 minutes.** Query again to get a fresh URL.

### 4.3 Download Media (Step 2 of Download)

```bash
curl '<MEDIA_URL_FROM_STEP_1>' \
  -H 'Authorization: Bearer <ACCESS_TOKEN>' \
  -o 'downloaded_car_photo.jpg'
```

**CRITICAL:** The Authorization header is required even for the download URL. Without it, the request fails.

The response is raw binary data (the file itself). Set `responseType: 'arraybuffer'` in axios/fetch.

### 4.4 Delete Media

```
DELETE https://graph.facebook.com/v21.0/{MEDIA_ID}?phone_number_id={PHONE_NUMBER_ID}
Authorization: Bearer <ACCESS_TOKEN>
```

**Response:** `{ "success": true }`

### 4.5 Supported Formats and Size Limits

| Type | Formats | Max Size | Notes |
|------|---------|----------|-------|
| **Audio** | .aac, .amr, .mp3, .m4a, .ogg (Opus only) | 16 MB | Voice notes MUST be OGG/Opus |
| **Document** | .pdf, .doc(x), .xls(x), .ppt(x), .txt | 100 MB | `filename` field controls display name |
| **Image** | .jpeg, .png | 5 MB | No GIF, no WebP (except stickers) |
| **Sticker** | .webp only | 100 KB static, 500 KB animated | Must be exactly 512x512 px |
| **Video** | .mp4, .3gp | 16 MB | H.264 + AAC only. Single audio stream. |

### 4.6 Media ID Lifecycle

| Context | Lifetime |
|---------|----------|
| Media you uploaded via API | **30 days** |
| Media received from user (webhook) | **30 days** (confirmed by Meta docs) |
| Media download URL (from GET /MEDIA_ID) | **5 minutes** |

After expiry, the media ID returns an error. Download and store media you need long-term.

### 4.7 WhatsApp vs Telegram Media Handling (Bridge Comparison)

| Aspect | WhatsApp Cloud API | Telegram Bot API |
|--------|-------------------|------------------|
| **Upload** | POST multipart to `/{PHONE_ID}/media` -> get `media_id` | `sendPhoto`/`sendDocument` accepts file directly |
| **Media reference** | `media_id` (expires in 30 days) | `file_id` (permanent, reusable forever) |
| **Download incoming** | 2-step: GET media_id -> get URL -> GET URL with auth | 1-step: `getFile` -> download from URL (no auth header needed) |
| **Download URL lifetime** | 5 minutes | ~1 hour |
| **Auth for download** | Bearer token required in header | Token is in the URL itself |
| **Size limit (upload)** | Varies: 5MB image, 16MB video/audio, 100MB doc | 50 MB for all types (bots), 2 GB for premium |
| **Supported formats** | Strict per type (jpeg/png only for images) | Very permissive |
| **Voice notes** | Must be OGG/Opus with `audio/ogg; codecs=opus` MIME | OGG/Opus via `sendVoice` |
| **Media persistence** | 30 days max, then gone | Permanent on Telegram servers |

**Key bridge implication:** When bridging Telegram to WhatsApp, you must:
1. Download media from Telegram immediately
2. Re-upload to WhatsApp (different API, different ID system)
3. Handle format conversion (Telegram allows more formats)
4. Re-download from WhatsApp if forwarding back (2-step process)
5. Cannot reuse IDs across platforms - they are completely independent

---

## 5. The 24-Hour Window - Implementation Details

### How It Works

When a user sends you a message, a **24-hour customer service window** opens. During this window:
- You can send **any message type** (text, image, interactive, etc.) - these are "service messages"
- Service messages are **FREE** (no per-message charge, no cap)
- The window resets with each new user message

When the window is **closed** (>24hrs since last user message):
- You can ONLY send **pre-approved template messages**
- Template messages cost money (marketing: ~Rs 1.09/msg, utility: ~Rs 0.145/msg in India)
- Free-form messages will fail with **error 131047**

### There Is No "Check Window" API

**WhatsApp does NOT provide an API endpoint to check if the 24-hour window is open.** You must track this yourself.

**Implementation pattern:**
```python
from datetime import datetime, timedelta

# In your database, store last_message_time per user
def is_window_open(user_phone):
    last_msg = db.get_last_incoming_message_time(user_phone)
    if last_msg is None:
        return False
    return datetime.utcnow() - last_msg < timedelta(hours=24)

def send_message(user_phone, message_content):
    if is_window_open(user_phone):
        # Send free-form message (text, interactive, media, etc.)
        send_freeform_message(user_phone, message_content)
    else:
        # Must use template message
        send_template_message(user_phone, template_name="re_engage",
                            params={"1": message_content})
```

### Error When Sending Outside Window

If you try to send a free-form message outside the window:

**HTTP 400 response:**
```json
{
  "error": {
    "message": "(#131047) Re-engagement message",
    "type": "OAuthException",
    "code": 131047,
    "error_subcode": 2388023,
    "fbtrace_id": "AaBC123..."
  }
}
```

### Template Messages (Required Outside 24hr Window)

Templates must be pre-approved by Meta. Create them in WhatsApp Manager or via API.

**Sending a template message:**
```json
{
  "messaging_product": "whatsapp",
  "to": "919876543210",
  "type": "template",
  "template": {
    "name": "car_followup",
    "language": { "code": "en" },
    "components": [
      {
        "type": "body",
        "parameters": [
          { "type": "text", "text": "Rahul" },
          { "type": "text", "text": "2022 Maruti Swift" },
          { "type": "text", "text": "Rs 6.5 Lakh" }
        ]
      }
    ]
  }
}
```

For a template with header image:
```json
{
  "messaging_product": "whatsapp",
  "to": "919876543210",
  "type": "template",
  "template": {
    "name": "car_showcase",
    "language": { "code": "en" },
    "components": [
      {
        "type": "header",
        "parameters": [
          { "type": "image", "image": { "id": "<MEDIA_ID>" } }
        ]
      },
      {
        "type": "body",
        "parameters": [
          { "type": "text", "text": "Maruti Swift 2022" }
        ]
      }
    ]
  }
}
```

### Template Categories and India Pricing (as of Jan 2026)

| Category | When to Use | India Cost |
|----------|-------------|------------|
| **Service** | Reply within 24hr window | FREE (no cap) |
| **Utility** | Order updates, appointment reminders, payment confirmations | Rs 0.145/msg |
| **Authentication** | OTPs, verification codes | Rs 0.145/msg |
| **Marketing** | Promotions, offers, re-engagement, product recommendations | Rs 1.09/msg |

**For the AI sales agent:** Most re-engagement (follow-ups after 24hrs) will be classified as **marketing** templates = Rs 1.09 per message. Design your flow to maximize engagement within the free 24hr window.

### Decision Logic Flowchart

```
User sends message
    |
    v
[Store timestamp in DB]
    |
    v
[Process message, generate AI response]
    |
    v
Is it < 24hrs since last user message? --YES--> Send free-form message (any type)
    |                                              (FREE)
    NO
    |
    v
Send template message only
    (PAID - Rs 0.145 to Rs 1.09 per msg)
    |
    v
Template message gets delivered -> User replies -> Window reopens -> Back to free-form
```

---

## 6. Error Handling Reference

### Error Response Format

```json
{
  "error": {
    "message": "Human-readable error description",
    "type": "OAuthException",
    "code": 131047,
    "error_subcode": 2388023,
    "fbtrace_id": "AaBC123...",
    "error_data": {
      "messaging_product": "whatsapp",
      "details": "Additional context about the error"
    }
  }
}
```

### Critical Error Codes for Your Bot

| Code | HTTP | Name | What It Means | Action |
|------|------|------|---------------|--------|
| **0** | 401 | Auth Exception | Token invalid or expired | Refresh token |
| **4** | 429 | Too Many Calls | App-level rate limit (200-5000 calls/hr) | Backoff + retry |
| **100** | 400 | Invalid Parameter | Bad request body | Check payload |
| **131008** | 400 | Missing Parameter | Required field missing | Check payload |
| **131009** | 400 | Invalid Parameter Value | Wrong value type/format | Check payload |
| **131026** | 400 | Message Undeliverable | User not on WhatsApp, or unsupported region | Skip this number |
| **131047** | 400 | Re-engagement Required | **24hr window closed** | Switch to template |
| **131048** | 429 | Spam Rate Limited | Too many users blocking/reporting you | Review message quality |
| **131049** | 400 | Delivery Blocked | Meta frequency capping | User getting too many msgs from businesses |
| **131051** | 400 | Unsupported Message Type | Message type not supported | Check type field |
| **131052** | 400 | Media Download Error | Incoming media can't be downloaded | Retry or skip |
| **131053** | 400 | Media Upload Error | Your media upload failed | Check format/size |
| **131056** | 429 | Pair Rate Limited | Too many msgs to SAME user too fast | Space out messages |
| **130429** | 429 | Rate Limit Hit | Cloud API throughput limit (80 msg/sec default) | Queue + backoff |
| **132000** | 400 | Template Param Mismatch | Wrong number of variables in template | Fix params |
| **132001** | 400 | Template Missing | Template doesn't exist or not approved | Check template name/language |
| **132015** | 400 | Template Paused | Low quality rating paused the template | Improve template quality |
| **190** | 401 | Access Token Expired | Token has expired | Get new token |
| **368** | 403 | Policy Violation | WABA restricted for policy violation | Contact Meta support |

### Rate Limits

| Limit | Default | Upgraded |
|-------|---------|----------|
| **Message throughput** | 80 messages/second | Up to 1,000 msg/sec (automatic upgrade) |
| **API calls** | 200 calls/hour (dev) | 5,000+ calls/hour (production) |
| **Pair rate limit** | ~10-15 msgs/min to same user | N/A - don't spam individuals |
| **Template messages/day** | Tier-based: 250 -> 1K -> 10K -> 100K -> unlimited | Based on quality rating |

### Template Message Tier System

New WhatsApp Business accounts start at Tier 1 (250 unique users/day for templates). Tiers increase based on message quality:
- Tier 1: 250 unique users/24hrs
- Tier 2: 1,000
- Tier 3: 10,000
- Tier 4: 100,000
- Unlimited

Quality rating (green/yellow/red) determines if you go up or down.

### Retry Strategy

```python
import time

MAX_RETRIES = 3
RETRY_DELAYS = [1, 5, 15]  # seconds

def send_with_retry(phone, payload):
    for attempt in range(MAX_RETRIES):
        response = send_message(phone, payload)
        
        if response.status_code == 200:
            return response.json()
        
        error_code = response.json().get("error", {}).get("code")
        
        # Don't retry these - they won't succeed
        if error_code in [131047, 131026, 131051, 132001, 368]:
            return handle_permanent_error(error_code, phone)
        
        # Rate limits - wait and retry
        if error_code in [4, 130429, 131056]:
            time.sleep(RETRY_DELAYS[attempt])
            continue
        
        # Server errors - retry
        if response.status_code in [500, 503]:
            time.sleep(RETRY_DELAYS[attempt])
            continue
    
    return handle_max_retries_exceeded(phone)
```

---

## 7. Webhook Setup (Dev to Production)

### Development Setup with ngrok

1. **Start your local server** on port 3000 (or any port)
2. **Run ngrok:** `ngrok http 3000`
3. Copy the HTTPS URL (e.g., `https://abc123.ngrok-free.app`)
4. **Go to:** Meta App Dashboard > WhatsApp > Configuration
5. **Callback URL:** `https://abc123.ngrok-free.app/webhook`
6. **Verify token:** Your secret string (e.g., `my_hackathon_secret_2026`)
7. Click **Verify and Save**
8. Under **Webhook fields**, subscribe to `messages`
9. **Test:** Send a WhatsApp message to your test number

**ngrok gotcha:** Free tier URLs change on restart. You must re-register in the App Dashboard each time. Use `ngrok http 3000 --url=your-custom.ngrok-free.app` if you have a reserved domain.

### Production Checklist

- Valid TLS/SSL certificate (self-signed NOT accepted)
- HTTPS endpoint (HTTP not accepted)
- Respond to all webhooks within 5 seconds with HTTP 200
- Implement signature validation (x-hub-signature-256)
- Process events asynchronously (queue-based)
- Handle webhook retries (Meta retries for up to 7 days)
- Use system user token (not temporary token)
- Set App Mode to "Live" (not development)

### Minimal Webhook Server (Python/Flask - Hackathon Ready)

```python
from flask import Flask, request, jsonify
import hmac
import hashlib
import json
import os

app = Flask(__name__)

VERIFY_TOKEN = os.environ["WA_VERIFY_TOKEN"]
ACCESS_TOKEN = os.environ["WA_ACCESS_TOKEN"]
APP_SECRET = os.environ["WA_APP_SECRET"]
PHONE_NUMBER_ID = os.environ["WA_PHONE_NUMBER_ID"]

# Webhook verification (GET)
@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

# Webhook events (POST)
@app.route("/webhook", methods=["POST"])
def webhook():
    # 1. Verify signature
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(request.data, signature):
        return "Invalid signature", 403
    
    # 2. Parse payload
    data = request.get_json()
    
    # 3. Process each entry
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            
            # Handle incoming messages
            if "messages" in value:
                for message in value["messages"]:
                    handle_incoming_message(message, value["contacts"][0])
            
            # Handle status updates
            if "statuses" in value:
                for status in value["statuses"]:
                    handle_status_update(status)
    
    # 4. ALWAYS return 200 quickly
    return "OK", 200

def verify_signature(payload, signature_header):
    if not signature_header:
        return False
    expected = hmac.new(
        APP_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    received = signature_header.replace("sha256=", "")
    return hmac.compare_digest(expected, received)

def handle_incoming_message(message, contact):
    sender = message["from"]
    msg_id = message["id"]
    msg_type = message["type"]
    sender_name = contact.get("profile", {}).get("name", "Unknown")
    
    if msg_type == "text":
        text = message["text"]["body"]
        print(f"Text from {sender_name} ({sender}): {text}")
        # -> Route to your AI agent here
    
    elif msg_type == "image":
        media_id = message["image"]["id"]
        caption = message["image"].get("caption", "")
        print(f"Image from {sender}: media_id={media_id}, caption={caption}")
        # -> Download image, process with vision AI
    
    elif msg_type == "audio":
        media_id = message["audio"]["id"]
        is_voice = message["audio"].get("voice", False)
        print(f"Audio from {sender}: media_id={media_id}, voice={is_voice}")
        # -> Download, transcribe with Whisper/Gemini
    
    elif msg_type == "interactive":
        interactive = message["interactive"]
        if interactive["type"] == "button_reply":
            btn_id = interactive["button_reply"]["id"]
            btn_title = interactive["button_reply"]["title"]
            print(f"Button reply from {sender}: {btn_id} ({btn_title})")
        elif interactive["type"] == "list_reply":
            row_id = interactive["list_reply"]["id"]
            row_title = interactive["list_reply"]["title"]
            print(f"List reply from {sender}: {row_id} ({row_title})")
    
    elif msg_type == "location":
        lat = message["location"]["latitude"]
        lon = message["location"]["longitude"]
        print(f"Location from {sender}: {lat}, {lon}")
    
    elif msg_type == "document":
        media_id = message["document"]["id"]
        filename = message["document"].get("filename", "unknown")
        print(f"Document from {sender}: {filename}, media_id={media_id}")

def handle_status_update(status):
    msg_id = status["id"]
    status_val = status["status"]  # sent, delivered, read, failed
    recipient = status["recipient_id"]
    
    if status_val == "failed":
        errors = status.get("errors", [])
        for err in errors:
            print(f"Message {msg_id} failed: {err['code']} - {err['title']}")
    else:
        print(f"Message {msg_id} -> {status_val} for {recipient}")

if __name__ == "__main__":
    app.run(port=3000, debug=True)
```

### Minimal Send Helper (Python)

```python
import requests

BASE_URL = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

def send_text(to, text):
    return requests.post(BASE_URL, headers=HEADERS, json={
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    })

def send_buttons(to, body_text, buttons):
    """buttons = [{"id": "btn_1", "title": "Yes"}, ...]"""
    return requests.post(BASE_URL, headers=HEADERS, json={
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": btn}
                    for btn in buttons
                ]
            }
        }
    })

def send_image(to, image_url, caption=""):
    return requests.post(BASE_URL, headers=HEADERS, json={
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {"link": image_url, "caption": caption}
    })

def send_template(to, template_name, language="en", body_params=None):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language}
        }
    }
    if body_params:
        payload["template"]["components"] = [{
            "type": "body",
            "parameters": [
                {"type": "text", "text": p} for p in body_params
            ]
        }]
    return requests.post(BASE_URL, headers=HEADERS, json=payload)

def mark_as_read(message_id):
    return requests.post(BASE_URL, headers=HEADERS, json={
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id
    })

def show_typing(to):
    return requests.post(BASE_URL, headers=HEADERS, json={
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "typing_indicator",
        "typing_indicator": {"type": "text"}
    })

def download_media(media_id):
    """Two-step media download. Returns binary data."""
    # Step 1: Get URL
    url_resp = requests.get(
        f"https://graph.facebook.com/v21.0/{media_id}",
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}"}
    )
    media_url = url_resp.json()["url"]
    
    # Step 2: Download binary
    media_resp = requests.get(
        media_url,
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}"}
    )
    return media_resp.content, url_resp.json()["mime_type"]
```

---

## Quick Reference Card

### Endpoints

| Action | Method | URL |
|--------|--------|-----|
| Send any message | POST | `/{PHONE_NUMBER_ID}/messages` |
| Upload media | POST | `/{PHONE_NUMBER_ID}/media` |
| Get media URL | GET | `/{MEDIA_ID}` |
| Download media | GET | `<URL from above>` (with auth header) |
| Delete media | DELETE | `/{MEDIA_ID}` |
| Webhook verify | GET | Your server |
| Webhook events | POST | Your server |

### Message Type Quick Reference

| Type | `type` field | Key object | Notes |
|------|-------------|------------|-------|
| Text | `text` | `text.body` | Max 4096 chars |
| Image | `image` | `image.id` or `image.link` | Max 5MB, JPEG/PNG only |
| Video | `video` | `video.id` or `video.link` | Max 16MB, H.264+AAC |
| Audio | `audio` | `audio.id` or `audio.link` | Max 16MB |
| Document | `document` | `document.id` or `document.link` | Max 100MB |
| Location | `location` | `location.latitude/longitude` | |
| Contacts | `contacts` | `contacts[].name.formatted_name` | Required field |
| Sticker | `sticker` | `sticker.id` or `sticker.link` | WebP only |
| Reaction | `reaction` | `reaction.message_id` + `reaction.emoji` | Empty emoji = remove |
| Buttons | `interactive` | `interactive.type=button` | Max 3 buttons |
| List | `interactive` | `interactive.type=list` | Max 10 rows |
| CTA URL | `interactive` | `interactive.type=cta_url` | Max 1 URL button |
| Template | `template` | `template.name` + `template.language` | Required outside 24hr |

---

**Sources consulted:**
- Meta WhatsApp Cloud API Official Docs (developers.facebook.com/docs/whatsapp/cloud-api/)
- Meta Business Messaging Webhooks Reference
- Meta Developer Blog: Using Authorization Tokens
- Heltar: Complete WhatsApp API Error Codes Guide (2025)
- Various implementation guides and community resources
