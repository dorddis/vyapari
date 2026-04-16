# Vyapari Agent - Design Specification

**Product:** AI sales agent for high-ticket businesses
**Version:** Hackathon MVP (Codex, April 16-17 2026)
**Demo vertical:** Used car dealership

---

## 1. Problem

A used car dealer posts a viral reel. 200 WhatsApp messages in 3 hours. 2 staff. 150 go unanswered. Each lost lead costs Rs 3-8 lakh.

The dealer doesn't need a CRM. He doesn't need a dashboard. He needs someone who knows his inventory, can talk to 50 customers at once, and knows when to shut up and let the human close the deal.

---

## 2. System Context

```
    +---------------------------------------------------+
    |              The Real World                        |
    |                                                    |
    |  YouTube Reel --> Customer sees link               |
    |                      |                             |
    |                      v                             |
    |  +----------+   +---------+   +--------------+    |
    |  | Customer |   | Vyapari |   | Owner +      |    |
    |  |          |<->| Agent   |<->| 2-3 Staff    |    |
    |  | WhatsApp |   |         |   | WhatsApp     |    |
    |  +----------+   | FastAPI |   +--------------+    |
    |                 | GPT-5   |                        |
    |                 | Postgres|                        |
    |                 +---------+                        |
    +---------------------------------------------------+
```

Four actor types:
- **Customer** (default, no login) -- browses inventory, asks questions, negotiates, books
- **SDR (Sales Development Rep)** -- relay sessions with assigned leads, view lead details, limited tools
- **Owner** -- full access: catalogue, analytics, broadcasts, staff management
- **Vyapari Agent** -- handles the conversation, knows the inventory, escalates intelligently, steps back when humans take over

The agent sits between customer and staff. It's not a generic chatbot -- it's a **capacity multiplier**. The 2-3 SDRs go from answering "kahan pe hai showroom?" (50x/day) to closing deals.

**Role resolution:** Everyone messages the same WhatsApp Business number. Any unknown phone number is treated as a customer. Owner and SDRs authenticate via `/login` with a one-time OTP. Once authenticated, the phone number is permanently mapped to a role.

**Critical design principle:** The agent is the intermediary for ALL communication. Owner never talks to the customer directly on WhatsApp. The agent relays messages, provides context, and manages session state. This means:
- Every message is logged and contextual
- The owner gets a conversation summary before entering any chat
- The agent can annotate, flag, and suggest during the relay
- No encryption or platform barriers -- messages are plaintext JSON at the webhook

---

## 3. Components

### 3a. Message Router

The entry point. Every incoming message hits the router first.

**Responsibilities:**
- Look up sender's `wa_id` in Staff table --> resolve role (owner/sdr/unknown)
- If unknown + message is `/login` --> start authentication flow
- If unknown + no `/login` --> treat as customer
- Look up (or create) conversation
- Check conversation state (including active relay sessions)
- Route to the correct agent OR relay to the correct person

**Routing rules:**

| Sender Role | State | Message Type | Action |
|-------------|-------|-------------|--------|
| Customer | ACTIVE | any | --> Customer Agent |
| Customer | ESCALATED | any | --> Customer Agent (still responds, staff notified) |
| Customer | RELAY_ACTIVE | any | Store + forward to session holder (owner/SDR) via agent |
| Unknown | -- | `/login` | --> Authentication flow (OTP) |
| Unknown | -- | anything else | --> Treat as customer (create Customer record) |
| Owner | no active session | any | --> Owner Agent (full tools) |
| Owner | RELAY_ACTIVE | no prefix | --> Forward to customer verbatim |
| Owner | RELAY_ACTIVE | `/` prefix | --> Agent command (session control) |
| SDR | no active session | any | --> SDR Agent (limited tools) |
| SDR | RELAY_ACTIVE | no prefix | --> Forward to customer verbatim |
| SDR | RELAY_ACTIVE | `/` prefix | --> Agent command (session control) |

### 3b. Customer Agent

An AI salesperson that knows the inventory cold, speaks Hinglish, and has opinions.

**What it knows:**
- Business profile (name, location, hours, USPs, greeting)
- Full catalogue (every car with specs, price, condition, images)
- FAQs (financing, documents, warranty, test drives, delivery)
- Conversation history with this customer
- Where the customer came from (which reel/link)

**How it behaves:**
- Matches the customer's language (Hindi, English, Hinglish, Marathi)
- Short responses (2-4 sentences -- this is WhatsApp, not email)
- Has opinions: "Nexon has 5-star safety but Brezza holds resale better"
- Proactively mentions competitive pricing (no showroom overhead)
- Quotes listed price, acknowledges negotiation is normal, escalates for actual discounts
- Uses urgency only from real data: "4 inquiries on this Creta this week"
- If a customer is leaving ("I don't like these") --> attempts recovery: suggests EMI stretch, asks about family size, offers higher-segment cars on financing
- Never halluccinates inventory. Never commits to unauthorized discounts. Never breaks character.

**WhatsApp UX patterns (how the agent renders responses):**

| Scenario | WhatsApp Message Type | Details |
|----------|----------------------|---------|
| General text reply | Text message | Max 4096 chars, `preview_url: true` for links |
| Show a car with actions | Reply Buttons + image header | 1 car photo in header, specs in body (1024 chars), max 3 buttons |
| Catalogue browse results | List Message | Max 10 rows across sections, grouped by category, 8 car slots + 2 navigation ("Next Page", "Change Filters") |
| Car photos | Sequential image messages | No native album. Each photo = separate API call with caption |
| Car comparison | Text message + Reply Buttons | Line-by-line text comparison (no tables in WA). Buttons: "Book X Test Drive" / "Book Y Test Drive" / "See more" |
| Dealership address | Location message | Lat/long + name + address. One message, done. |
| EMI/pricing | Text message | Formatted plain text. Optional CTA URL button for calculator |
| "Typing..." indicator | Typing indicator API | Fire before every GPT-5 call. Shows for up to 25s. |
| Read receipts | Mark as Read API | Mark on receipt before processing. Shows blue ticks. |

**Tools it can call:**

| Tool | When |
|------|------|
| `search_catalogue` | Customer asks about available cars |
| `get_item_details` | Customer asks about a specific car |
| `compare_items` | "Creta vs Nexon" |
| `get_faq_answer` | Financing, documents, warranty, address, hours |
| `get_pricing_info` | EMI estimates, additional costs (RC transfer, insurance) |
| `check_availability` | "Is the white Creta still available?" |
| `request_escalation` | Buying signal, price negotiation, frustration, uncertainty |
| `request_callback` | Customer wants a phone call |

### 3c. Owner Agent (The Oracle)

The owner doesn't want a dashboard. He wants to ask questions and get answers.

**What it knows:**
- Everything the Customer Agent knows PLUS
- All active conversations (who's talking, what they want, how hot they are)
- Lead pipeline (new / warm / hot / quiet / converted)
- Aggregate analytics (leads per day, top-queried cars, conversion trends)
- Daily wrap context files from previous days

**How it behaves:**
- Speaks Hinglish casually -- this is the boss, not a customer
- Concise and actionable -- "12 leads today. 3 hot. Nexon is your best seller."
- Proactive -- "Venue has had 0 inquiries in 2 weeks. Drop the price or feature it in a reel."
- For catalogue changes: confirms before acting. "Creta sold, the white one" --> "2021 Phantom Black or 2024 Abyss Black?"
- Flags discrepancies: "You told the customer 7.2L but catalogue says 7.5L. Update?"

**Tools it can call:**

| Tool | When |
|------|------|
| `search_catalogue` | "What Marutis do we have?" |
| `add_item` | "New stock: 2023 Venue, 6.5L, 22K km" |
| `update_item` | "Change Creta price to 7.8L" |
| `mark_sold` | "White Creta sold" --> disambiguate, confirm, mark, notify interested leads |
| `mark_reserved` | UPI token received --> car on hold, others redirected |
| `get_catalogue_summary` | "How many cars in stock?" |
| `get_active_leads` | "Who's ready to buy?" |
| `get_lead_details` | "What did the Creta guy say?" |
| `get_stats` | "Aaj kitne leads aaye?" |
| `add_faq` | "If someone asks about delivery, tell them Mumbai/Navi Mumbai/Thane free" |
| `broadcast_message` | "New Fortuner arrived -- message everyone" |
| `update_greeting` | "Change greeting to mention the Diwali sale" |
| `open_session` | "Ertiga wale se baat karna hai" -- opens relay session |
| `get_customer_number` | "Iska number de" -- returns phone number as tappable contact |
| `add_staff` | "Add Raj as SDR, 9876543210" -- generates OTP, creates invite |
| `remove_staff` | "Remove Raj" -- revokes access, closes active sessions |
| `list_staff` | "Show staff" / `/staff` -- lists all staff with roles and last active |
| `assign_lead` | "Give Priya's leads to Raj" -- sets `assigned_to` on conversation |

### 3d. Escalation System

**What triggers escalation:**

| Signal | Source | Example |
|--------|--------|---------|
| Price negotiation | Customer message | "Best price?", "Thoda kam karo", "Last price batao" |
| Visit/test drive intent | Customer message | "Kal aa sakta hu?", "Address kya hai showroom ka?" |
| Token/booking intent | Customer message | "Token kaise bhejun?", "Book kar do" |
| Explicit request | Customer message | "Kisi se baat karo", "Call me" |
| Frustration | Customer message | ALL CAPS, repeated question, negative sentiment |
| Agent uncertainty | Agent response | Low confidence, outside scope |
| Agent offers handoff | Agent response | "Let me connect you with our team" |

**What happens on escalation:**
1. Conversation state --> ESCALATED
2. Agent still responds to customer (doesn't go silent -- that's worse)
3. Notification sent to the right person:
   - If lead has `assigned_to` --> that SDR gets the notification
   - If no assignment --> owner gets the notification
   - Notification includes: reason, 2-line summary, customer name, car of interest, lead temperature
4. If staff opens a relay session --> state --> RELAY_ACTIVE, agent steps back
5. If no one responds within 15 min --> agent continues, adds "Our team will get back to you shortly"

### 3e. Relay System (The Hijack Redesign)

The staff's interface to talk to customers. The agent is the intelligent middle layer. Both owner and SDRs use the same relay mechanism -- role determines which leads they can access.

**Why relay, not direct chat:**
- Staff never leaves one conversation thread (staff <-> agent)
- Agent provides context summary before every session
- Every message is logged -- nothing is invisible to the system
- Works on any device (no coexistence mode restrictions)
- Agent adds value during the relay -- can annotate, suggest, flag
- Multiple SDRs can relay with different customers simultaneously

**How it works:**

**Step 1 -- Owner requests a session:**

```
Owner: ertiga wale se baat karna hai
```

The Owner Agent calls `open_session`. The agent runs `get_active_leads` to find matching conversations, then responds:

```
Agent: Active conversations matching "ertiga":

  1. Ramesh Patil -- 2023 Ertiga VXi (Black)
     Status: HOT | Last msg: 12 min ago
     Interested in EMI, asked for test drive

  2. Sunil Joshi -- 2022 Ertiga ZXi (Silver)
     Status: WARM | Last msg: 3 hours ago
     Comparing with Innova, price-sensitive

Reply with the number to connect.
```

**Step 2 -- Owner selects, session starts:**

```
Owner: 1
```

Agent creates the relay session and sends a context message:

```
Agent: Session with Ramesh Patil started.
Everything you type goes to the customer.
Use /done when finished. Use / for commands.

--- CONVERSATION SUMMARY ---
Ramesh clicked the Ertiga reel link 2 days ago.
Asked about diesel vs petrol, compared with XL6.
Today: asked for EMI on the VXi, then requested
a test drive. Escalated 12 min ago (test drive intent).

--- LAST 5 MESSAGES ---
[Customer] EMI kitna aayega VXi pe?
[Agent] HDFC se 48 months pe Rs 14,200/month.
        ICICI se thoda kam -- Rs 13,800/month.
        Down payment 20% assumed. Adjust karein?
[Customer] Kal dekhne aa sakta hu?
[Agent] Bilkul! Hum Mon-Sat 10am-8pm open hain.
        Shop 7, Oshiwara Industrial Centre, near
        Oshiwara Metro. Kaunsa time suit karega?
[Customer] Shaam ko 5 baje?
```

**Step 3 -- Relay mode active:**

```
Owner: Haan bhai 5 baje aa jao, gaadi ready rakhta hu
       --> FORWARDED TO CUSTOMER (as a message from the business number)

Customer: Done, kal aata hu
       --> RELAYED TO OWNER (shown inline in the owner's chat)

Owner: /done
       --> SESSION CLOSED
```

**Agent command prefix: `/`**

During an active relay session, the prefix `/` signals "this message is for the agent, not the customer":

| Command | Action |
|---------|--------|
| `/done` | Close session. Agent resumes for this customer. |
| `/switch [query]` | Close current session, open a new one matching query. |
| `/number` | Agent sends customer's phone as a tappable contact card. |
| `/status` | Agent shows current lead status, conversation stats. |
| `/summary` | Agent regenerates the conversation summary. |
| `/help` | Agent lists available commands. |
| `/note [text]` | Agent saves an internal note on this lead (not sent to customer). |

Everything WITHOUT the `/` prefix is forwarded to the customer verbatim.

**Safety net:** If a message without prefix looks suspiciously like a command (short message containing "switch", "done", "number de", "session" AND is under 5 words), the agent double-checks before forwarding: "Forward to customer? Reply Y or type /done to close."

**The prefix is configurable.** Default is `/`. Owner can change it during setup (`/settings prefix @`). Must be a single non-alphanumeric character. Options: `/`, `@`, `#`, `>`.

**Step 4 -- Mid-session context switch:**

```
Owner: /switch black ertiga wala

Agent: Closing session with Ramesh Patil.
       Opening session with Sunil Joshi (2022 Ertiga ZXi Silver).
       
       [... summary + last 5 messages ...]
```

If the owner's query is ambiguous, the agent shows the list again and asks for a number.

**Session expiry:**
- 15 min of owner inactivity --> agent sends: "Ramesh ka session 15 min se idle hai. Continue? Ya /done?"
- 20 min total inactivity --> auto-close. Agent resumes for the customer.
- Customer gets: "Thanks for your patience! I'm here if you need anything else."
- Owner gets: "Session with Ramesh auto-closed. Agent resumed."

**Incoming messages during active session:**
- Messages from the active customer --> relayed to owner inline
- Messages from OTHER customers --> agent handles normally (auto-reply, agent logic)
- Escalations from other customers --> queued, shown when session closes:

```
Agent: Session with Ramesh closed.

WHILE YOU WERE CHATTING:
- Priya (Creta) -- price negotiation, waiting 8 min
- New lead: Amit -- asking about Fortuner
```

**Concurrent sessions:** One active session per staff member. Each SDR can relay with one customer at a time. But SDR A can be in a session while SDR B is in a different session simultaneously -- the router uses `staff_id` on RelaySession to keep them isolated. Two staff cannot open sessions with the same customer (first one holds the lock).

### 3f. Daily Wrap System

Conversations and context go stale across days. The daily wrap captures the full day's state so the agent can retrieve it later.

**What gets saved (end of each day, automated):**

```
daily_wrap_2026_04_15.json
{
  "date": "2026-04-15",
  "leads_summary": {
    "new": 8, "warm": 5, "hot": 3, "quiet": 2, "converted": 1
  },
  "conversations": [
    {
      "customer": "Ramesh Patil",
      "customer_id": "cust_042",
      "car_interest": "2023 Ertiga VXi (Black)",
      "status": "hot",
      "summary": "Asked about EMI, requested test drive for tomorrow 5pm. Owner confirmed via relay session.",
      "escalations": ["test_drive_intent"],
      "owner_interactions": "Owner relayed at 14:32, confirmed test drive"
    }
  ],
  "catalogue_changes": [
    {"action": "sold", "item": "2021 Creta SX Phantom Black", "buyer": "Walk-in"},
    {"action": "reserved", "item": "2022 Nexon XZ+", "reserved_by": "Ramesh", "token": "5000"}
  ],
  "owner_decisions": [
    "Quoted 7.2L for white Creta (catalogue says 7.5L) -- discrepancy flagged"
  ],
  "top_queries": ["Ertiga", "Creta", "financing", "test drive"],
  "pending_followups": [
    {"customer": "Sunil Joshi", "car": "Ertiga ZXi", "last_active": "3 hours ago", "suggested_action": "Day 1 follow-up tomorrow"}
  ]
}
```

**How the agent uses it:**
- Agent does NOT load all historical wraps into context (token explosion)
- System prompt includes: today's date + yesterday's wrap summary (compact)
- When a customer re-engages or owner asks about a specific lead, agent does a **targeted retrieval** -- searches wrap files for that customer/car name
- This is RAG over your own conversation history

**Deletability:** Wraps reference customers by ID. If a customer exercises right to erasure (DPDP Act), delete their entries from all wrap files via customer_id lookup.

### 3g. Authentication & Roles

Everyone messages the same WhatsApp Business number. Role determines what the agent does with your messages.

**Roles:**

| Role | How assigned | Access |
|------|-------------|--------|
| **Customer** | Default. Any unregistered wa_id. | Browse catalogue, ask questions, get escalated. No login needed. |
| **SDR** | Owner adds them + OTP login. | Relay sessions (own assigned leads OR all, configurable), view leads, `/number`, `/status`. Cannot modify catalogue, settings, FAQs, or broadcast. |
| **Owner** | First registered user during `/setup`. | Full access: catalogue CRUD, analytics, broadcasts, staff management, settings, all relay sessions. |

**OTP Authentication Flow:**

```
STEP 1 -- Owner registers an SDR (owner's chat):

  Owner: Raj ko add karo, 9876543210
  Agent: Added Raj as SDR. OTP: 482910
         Share this with Raj. Expires in 24 hours.

STEP 2 -- SDR logs in (SDR's chat with the agent):

  Raj: /login
  Agent: Welcome! Enter your 6-digit OTP.
  Raj: 482910
  Agent: Verified! Welcome Raj, you're logged in as SDR
         at Sharma Motors. Type /help for commands.

STEP 3 -- Done. Raj's wa_id is mapped to SDR role permanently.
```

**OTP mechanics:**
- 6-digit numeric, generated server-side (cryptographically random)
- Expires in 24 hours (configurable)
- One-time use: invalidated after successful verification
- Max 3 attempts: after 3 wrong OTPs, the invite is locked. Owner must regenerate.
- OTP is shown ONLY to the owner. Owner shares it with the SDR out-of-band (in person, private message, etc.)

**Why OTP over password:**
- No password to remember or reset
- One-time friction, then permanent access
- Owner controls who gets access (generates the invite)
- If a phone is compromised, owner can `/remove` the SDR instantly

**Session persistence:**
- Once authenticated, the wa_id-to-role mapping is stored in the `Staff` table
- No re-login needed. Role persists until the owner removes them.
- If the SDR changes phone numbers, owner must add the new number and the SDR re-authenticates.

**SDR-specific behavior:**

The SDR gets a simpler version of the Owner Agent. Same conversational style, but limited tools:

| SDR Can Do | SDR Cannot Do |
|-----------|--------------|
| Open relay sessions with customers | Modify catalogue (add, update, mark sold) |
| View active leads and details | Change business settings |
| Get customer phone numbers | Add/remove FAQs |
| Save notes on leads | Broadcast messages |
| Ask about lead status | View full analytics (`/stats`) |
| `/summary`, `/status`, `/number` | Add or remove other staff |

**Owner staff management tools:**

| Command / Natural Language | Action |
|---------------------------|--------|
| "Add Raj as SDR, 9876543210" | Generates OTP, stores pending invite |
| "Remove Raj" | Revokes access, wa_id unmapped, active sessions closed |
| "Show staff" / `/staff` | Lists all registered staff with roles and last active |
| "Make Raj owner" | Promotes SDR to owner (requires confirmation) |
| "Demote Raj to SDR" | Demotes owner to SDR (requires confirmation) |

**Lead assignment (optional, configurable):**
- Default: all SDRs see all leads (small team, no need for assignment)
- If enabled: owner assigns leads to specific SDRs. SDR only sees assigned leads in `get_active_leads`.
- Escalations route to the assigned SDR first. If no SDR assigned, routes to owner.
- Owner can reassign: "Give Priya's leads to Raj"

**Multi-SDR relay sessions:**
- Each SDR can have one active relay session at a time
- Multiple SDRs CAN be in sessions with DIFFERENT customers simultaneously
- Two staff members CANNOT open sessions with the SAME customer (first one holds the lock)
- If SDR tries to open a session for a customer already in a relay: "Raj is already chatting with this customer. Try /switch or wait."

---

## 4. Data Model

### Entities

```
+----------+     +----------------+     +----------+
| Business |---->| CatalogueItem  |     |   FAQ    |
|          |     |                |     |          |
| name     |     | make, model    |     | question |
| greeting |     | price, year    |     | answer   |
| hours    |     | images, specs  |     | category |
| settings |     | sold/reserved  |     +----------+
+----+-----+     +----------------+
     |
     |         +----------+     +--------------+     +-----------+
     +-------->| Customer |---->| Conversation |---->|  Message   |
     |         |          |     |              |     |           |
     |         | wa_id    |     | status       |     | role      |
     |         | channel  |     | (state       |     | content   |
     |         | name     |     |  machine)    |     | timestamp |
     |         | source   |     | assigned_to  |     | wa_msg_id |
     |         | lead_    |     +--------------+     +-----------+
     |         | status   |          |
     |         +----------+   +------+-------+
     |                         |  Escalation  |
     |                         |              |
     |                         | trigger      |
     |                         | summary      |
     |                         | status       |
     |                         +--------------+
     |
     |         +----------+
     +-------->| Staff    |
     |         |          |
     |         | wa_id    |
     |         | name     |
     |         | role     |   (owner / sdr)
     |         | status   |   (active / invited / removed)
     |         | otp_hash |   (bcrypt, null after login)
     |         | otp_exp  |   (expiry timestamp)
     |         | added_by |
     |         +----------+
     |
     |         +--------------+
     +-------->| RelaySession |
               |              |
               | staff_id     |  (FK to Staff, not just owner)
               | customer_id  |
               | conversation |
               | started_at   |
               | last_active  |
               | status       |  (active / closed / expired)
               +--------------+

               +-----------+
               | DailyWrap |
               |           |
               | date      |
               | data JSON |
               +-----------+
```

### Key relationships
- One Business has many CatalogueItems, FAQs, Customers, and Staff
- One Customer has one active Conversation (can have past resolved ones)
- One Conversation has many Messages and zero or more Escalations
- One Conversation optionally has `assigned_to` (FK to Staff) for lead assignment
- CatalogueItem tracks `sold` and `reserved_by` for real-time availability
- One RelaySession links a Staff member to a customer's conversation (max one active per staff member)
- Two staff cannot hold sessions with the same customer simultaneously
- One DailyWrap per business per day

### Key fields

**Staff:** `wa_id` (phone with country code), `role` (owner/sdr), `status` (active/invited/removed). `otp_hash` stores bcrypt hash of the OTP during the invite period (null after successful login). `otp_exp` is the expiry timestamp. `added_by` references who created the invite.

**Customer:** `wa_id` (phone number with country code, e.g., `919876543210`), `channel` (whatsapp/web), `name` (from WhatsApp profile), `source` (which reel/link), `lead_status` (new/warm/hot/quiet/converted).

**Conversation:** `assigned_to` (optional FK to Staff) for lead assignment. If null, all staff can see and claim it.

**Message:** `role` is one of `customer`, `agent`, `owner`, `sdr`. `wa_msg_id` stores the WhatsApp message ID for reply-to context and read receipt tracking.

**Business.settings:** JSON field including `command_prefix` (default `/`), `session_timeout_minutes` (default 20), `escalation_phrases`, `greeting_template`, `lead_assignment_enabled` (default false).

### Catalogue item schema
Every car is stored with: make, model, variant, year, price (lakhs), fuel type, transmission, km driven, number of owners, color, condition, description, highlights (array), images (array of URLs), insurance validity, registration state, sold flag, reserved_by.

### Conversation isolation (per-customer sessions)

Each customer gets an isolated session keyed by `customer_{wa_id}`. Each staff member gets `staff_{wa_id}`. The Customer Agent and Owner Agent are separate agent instances with different tools and instructions -- they never share a session. When the Owner Agent needs to see a customer's history (via `open_session`), it reads from that customer's session directly. This is a DB read, not an agent handoff.

During RELAY_ACTIVE, no agent runs at all. The message router bypasses both agents and forwards messages raw between staff and customer. The router is pure Python application logic, not an LLM.

**Framework:** OpenAI Agents SDK (`openai-agents`). Sessions via custom `PostgresSession` implementing `SessionABC`. Per-customer context via `RunContextWrapper`. Batch operations via `asyncio.gather()` over parallel `Runner.run()` calls. See `research/AGENT_ARCHITECTURE_SYNTHESIS.md` for full rationale.

---

## 5. Conversation Lifecycle

```
    Customer clicks link
           |
           v
        +------+
        | NEW  |  Agent sends source-aware greeting
        +--+---+  ("Saw you checking out our Creta video...")
           |
           v
       +--------+
  +---->| ACTIVE |  Agent handles conversation
  |    +---+----+  Tools called as needed
  |        |
  |        | escalation trigger detected
  |        v
  |   +-----------+
  |   | ESCALATED |  Agent still responds + owner notified
  |   +-----+-----+  Owner sees: reason, summary, lead temp
  |         |
  |         | owner opens relay session
  |         v
  |   +--------------+
  |   | RELAY_ACTIVE |  Agent relays messages between owner <-> customer.
  |   +------+-------+  Owner messages forwarded. Customer responses relayed.
  |          |          Agent silent unless /command received.
  |          |
  |          | /done OR session timeout (20 min)
  |          |
  +----------+
                   
         owner explicitly closes OR marks converted
              |
              v
        +----------+
        | RESOLVED |
        +----------+
```

**State transitions:**

| From | To | Trigger |
|------|----|---------|
| NEW | ACTIVE | First agent response sent |
| ACTIVE | ESCALATED | Escalation trigger detected |
| ESCALATED | RELAY_ACTIVE | Owner or SDR opens relay session for this customer |
| ACTIVE | RELAY_ACTIVE | Owner or SDR opens relay session (no escalation needed) |
| RELAY_ACTIVE | ACTIVE | `/done`, session timeout, or staff inactivity |
| RELAY_ACTIVE | RELAY_ACTIVE | Messages flowing (timer resets on each staff message) |
| ANY | RESOLVED | Owner explicitly closes |

---

## 6. Integration Points

### OpenAI API + Agents SDK
- **OpenAI Agents SDK** (`pip install openai-agents`): Agent orchestration framework. Two agent instances (Customer Agent, Owner Agent) with separate tool sets and per-user sessions. `@function_tool` for tool definitions, `Runner.run()` for execution, `PostgresSession` for conversation persistence.
- **GPT-5:** Main agent conversations + multimodal parsing (PDF/image --> catalogue)
- **GPT-5 mini:** Lightweight classification (escalation detection fallback when phrase matching is ambiguous, command-vs-relay safety check)
- **GPT-4o mini Transcribe:** Voice note STT (stretch goal)
- **TTS:** Voice note responses (stretch goal)
- **Function calling:** All tool invocations go through the Agents SDK's tool_calls mechanism. Agent decides which tool, we execute and return results.

### WhatsApp Cloud API

**Base URL:** `https://graph.facebook.com/v21.0/`
**Auth:** Bearer token (System User Token, never expires)
**Library:** PyWa 3.9+ with FastAPI integration

**Incoming (webhook handlers via PyWa):**

| Handler | Webhook Event | What It Delivers |
|---------|--------------|-----------------|
| `@wa.on_message(filters.text)` | Text message | `msg.text`, `msg.from_user.wa_id`, `msg.from_user.name` |
| `@wa.on_message(filters.image)` | Image message | `msg.image.id`, `msg.image.caption` (download immediately, URL expires in 5 min) |
| `@wa.on_message(filters.voice)` | Voice note | `msg.audio.id`, OGG Opus format (same as Telegram, no conversion needed) |
| `@wa.on_message(filters.document)` | Document (PDF etc) | `msg.document.id`, `msg.document.filename` |
| `@wa.on_message(filters.location)` | Location share | `msg.location.latitude`, `msg.location.longitude` |
| `@wa.on_callback_button()` | Reply button tap | `btn.data` (button ID), `btn.title` |
| `@wa.on_callback_selection()` | List row selection | `sel.data` (row ID), `sel.title`, `sel.description` |
| `@wa.on_message_status(filters.failed)` | Send failure | Error code, e.g., 131047 = 24hr window expired |

**Outgoing (message types the agent sends):**

| Action | API Call | Key Constraints |
|--------|---------|-----------------|
| Text reply | `wa.send_message(to, text)` | Max 4096 chars |
| Image + buttons | `wa.send_image(to, image, caption, buttons)` | 1 image, max 3 buttons, button title max 20 chars |
| List (catalogue browse) | `wa.send_message(to, text, buttons=SectionList(...))` | Max 10 rows total, row title 24 chars, row desc 72 chars, text-only header (no images) |
| Location | `wa.send_location(to, lat, lon, name, address)` | -- |
| Contact card | `wa.send_contacts(to, contacts)` | For "iska number de" -- owner gets tappable phone number |
| Typing indicator | POST `/{phone_id}/messages` type `typing_indicator` | Shows "typing..." for up to 25s |
| Mark as read | POST `/{phone_id}/messages` status `read` | Blue ticks. Mark on receipt before processing. |
| Template message | `wa.send_template(to, template_name, ...)` | Required when customer hasn't messaged in 24 hours |

**Webhook setup:**
- Verification: PyWa auto-handles GET `/webhook` with `verify_token`
- Security: HMAC-SHA256 signature validation via `app_secret` param + `cryptography` extra
- Local testing: `validate_updates=False` + ngrok/cloudflare tunnel

### 24-Hour Messaging Window

WhatsApp enforces a 24-hour service window. After the customer's last message, the business can send free-form replies for 24 hours. After that, ONLY pre-approved template messages are allowed.

**Impact on the system:**

| Feature | Within 24hr | After 24hr |
|---------|------------|------------|
| Agent text replies | Free-form | BLOCKED |
| Agent interactive messages | Free-form | BLOCKED |
| Follow-up sequences (Day 1/3/7) | Free-form | Template required |
| Broadcast (`broadcast_message`) | Free-form | Template required |
| "Sold" notifications to interested leads | Free-form | Template required |
| Escalation timeout ("team will get back to you") | Free-form | Template required |

**Implementation:** Every outgoing message checks: `last_customer_message_at > now() - 24 hours`? If not, fall back to the matching template. The `send_message` layer in the WhatsApp adapter handles this transparently.

**Pre-designed templates (submit for Meta approval before hackathon):**

| Template Name | Category | Use Case |
|---------------|----------|----------|
| `car_followup_day1` | Marketing | Day 1: "Still thinking about the [car]?" |
| `car_followup_day3` | Marketing | Day 3: Urgency with real inquiry count |
| `car_followup_final` | Marketing | Day 7: Final check-in, offer new stock |
| `new_stock_arrival` | Marketing | Broadcast: new car with image header |
| `staff_followup_message` | Utility | Owner relay message outside 24hr window |
| `test_drive_confirmed` | Utility | Test drive booking confirmation |
| `token_payment_received` | Utility | Token/booking confirmation |
| `welcome_back_customer` | Marketing | Re-engagement for returning customers |

Cost: Marketing ~Rs 0.86/msg, Utility ~Rs 0.11-0.15/msg (free within 24hr window).

### Web Demo (fallback)
- Same backend. Same agents. Same tools.
- Frontend: two WhatsApp-like phone frames (customer + owner)
- REST API instead of webhooks: `POST /api/chat`, `GET /api/messages/{id}`, `POST /api/owner/send`
- Already built and tested in `prototypes/whatsapp-demo-v0/`

---

## 7. Agent Tool Contracts

### Shared Pattern
Every tool function follows the same contract:

```
Input:  Typed parameters (validated before LLM sees results)
Output: {"success": bool, "data": dict | list | null, "message": str}
```

The agent sees the `message` field as human-readable context. The `data` field contains structured results for the agent to reference.

If a tool fails or input is invalid, it returns `{"success": false, "data": null, "message": "error description"}` -- the agent sees the error and can recover gracefully.

### Anti-Hallucination Rules
- All IDs are validated against the database before execution. If agent fabricates an item_id, the tool returns "Item not found."
- `search_catalogue` returns max 5 results per call to prevent context flooding.
- `mark_sold` requires exact item_id -- if owner says "the Creta" and there are two, tool returns both and asks which one.
- Max 8 tool calls per agent turn. If exceeded, agent is cut off with a fallback response.

### Customer Tools (9)

| Tool | Input | Output |
|------|-------|--------|
| `search_catalogue` | Optional: max_price, min_price, fuel_type, make, category, transmission, max_km | Up to 5 cars: id, name, price, year, fuel, key highlight |
| `get_item_details` | item_id (required) | Full car details: all attributes, description, highlights, image URLs |
| `compare_items` | item_id_1, item_id_2 (required) | Side-by-side attributes + trade-off summary text |
| `get_faq_answer` | topic keyword (required) | Matching FAQ answer text |
| `get_pricing_info` | item_id (required), down_payment_pct (optional, default 20) | EMI table (4 banks x 3 tenures) + additional costs breakdown |
| `check_availability` | item_id (required) | Available / sold / reserved status |
| `get_business_info` | none | Hours, address, contact, landmark, nearest metro |
| `request_escalation` | reason (enum), summary (text) | Confirms escalation created, notifies owner |
| `request_callback` | phone_number (required) | Confirms callback request saved |

### Owner Tools (18)

| Tool | Input | Output |
|------|-------|--------|
| `search_catalogue` | Same as customer | Same as customer |
| `add_item` | make, model, year, price_lakhs (required), other fields optional | Created item with assigned ID |
| `update_item` | item_id (required), fields to change | Updated item confirmation |
| `mark_sold` | item_id (required), notify_interested (default true) | Confirmation + count of notified customers. Uses template if customer outside 24hr window. |
| `mark_reserved` | item_id, customer_name (required), token_amount (optional) | Confirmation. Car status --> reserved. |
| `get_catalogue_summary` | none | Total cars, by category, price range, avg days in stock |
| `get_active_leads` | status filter (optional: all/hot/warm/new/quiet), limit, search query (optional) | Lead list: name, car interest, last message, temperature |
| `get_lead_details` | customer_id or phone (required) | Full conversation summary, messages, escalation history |
| `get_stats` | period (today/week/month) | Leads count, top queried cars, escalation count, conversion rate |
| `add_faq` | question, answer, category | Confirmation |
| `broadcast_message` | message text, filter (optional: all/recent/hot) | Count of recipients. Uses template for customers outside 24hr window. |
| `update_greeting` | new greeting text | Confirmation |
| `open_session` | search query (e.g., "ertiga wala", customer name, phone) | Returns matching active leads for owner to select, then creates RelaySession |
| `get_customer_number` | customer_id (required) | Returns phone number as a WhatsApp contact card (tappable to call) |
| `add_staff` | name, wa_id, role (sdr/owner) | Generates OTP, creates Staff record with status=invited. Returns OTP to owner. |
| `remove_staff` | staff_id or name or phone | Revokes access, sets status=removed, closes any active relay sessions |
| `list_staff` | none | All staff: name, role, status, last active timestamp |
| `assign_lead` | customer_id or name, staff_id or name | Sets `assigned_to` on conversation. Confirmation. |
| `batch_followup` | date (default "yesterday"), status_filter (default "warm,hot") | Loads each matching lead's conversation history, generates personalized follow-up per customer in parallel, sends via WhatsApp (template if outside 24hr window). Returns count sent. |

### SDR Tools (7)

SDRs get a subset of tools. The agent enforces this based on the caller's role.

| Tool | Input | Output |
|------|-------|--------|
| `search_catalogue` | Same as customer | Same as customer (read-only) |
| `get_active_leads` | Same as owner, but filtered to assigned leads (if assignment enabled) | Lead list scoped to this SDR |
| `get_lead_details` | customer_id or phone (required) | Full conversation summary (if assigned or unassigned) |
| `open_session` | search query | Same as owner, but scoped to accessible leads |
| `get_customer_number` | customer_id (required) | Contact card (tappable to call) |
| `check_availability` | item_id (required) | Available / sold / reserved status |
| `get_business_info` | none | Hours, address, contact |

---

## 8. Encryption & Data Storage

### No Encryption Barriers

WhatsApp Cloud API messages are **not end-to-end encrypted** between customer and business. Meta decrypts at their servers (acting as "data processor") and delivers plaintext JSON to the webhook over HTTPS. This means:

- Messages arrive as plaintext at our FastAPI webhook
- We can read, store, process, and relay them freely
- No additional decryption needed on our side
- `X-Hub-Signature-256` is integrity verification (HMAC), not encryption

### Storage Architecture

```
CUSTOMER'S PHONE
  | Signal Protocol encryption
META'S CLOUD API SERVERS
  | Decrypted here. Stored encrypted-at-rest for max 30 days.
  | Media URLs expire in 5 minutes.
HTTPS/TLS
  | Plaintext JSON webhook payload
OUR FASTAPI SERVER
  | Store in PostgreSQL (standard DB security)
  | Media: download immediately on receipt, store in our own storage
```

### What We Store

| Data | Where | Retention |
|------|-------|-----------|
| Messages (text content) | PostgreSQL `Message` table | Until customer deletes or business purges |
| Media (images, voice, docs) | Object storage (S3/GCS) | Downloaded on receipt (5 min URL expiry). Kept until purge. |
| Customer profiles | PostgreSQL `Customer` table | wa_id, name, source, lead status |
| Daily wraps | PostgreSQL `DailyWrap` table or JSON files | Indefinite, deletable per customer_id |
| Conversation history | PostgreSQL `Message` table | Full history for agent context |

### Compliance (India DPDP Act 2023)

| Requirement | Implementation | Priority |
|-------------|---------------|----------|
| Consent | First message includes data handling notice | Post-hackathon |
| Purpose limitation | Messages used only for sales agent function | By design |
| Right to erasure | Delete customer data on request (messages, wraps, profile) | Design for now, build later |
| Data minimization | Only store what's needed for the agent | By design |
| Local storage | Enable India region in Meta Business Manager | Production config |

### Security Measures

- System User Token stored in environment variables, never in code
- App Secret for webhook signature validation, server-side only
- HTTPS-only webhook endpoint
- Optional: Business Encryption API (RSA public key upload for encrypted webhook payloads) -- production hardening

---

## 9. Design Constraints & Trade-offs

| Decision | What we chose | What we gave up | Why |
|----------|--------------|-----------------|-----|
| GPT-5 over Gemini | OpenAI stack, Codex hackathon alignment | Free tier (Gemini), existing Gemini agent code | Hackathon is Codex. GPT-5 is the flagship. |
| PostgreSQL over WA Catalogue as source of truth | Full control, query flexibility, no Meta API dependency | "Zero external DB" simplicity | Meta Commerce API has compliance overhead in India. Sync as display layer instead. |
| Agent-as-relay over Coexistence mode | Agent provides context before every session, full logging, any-device support, agent adds value during relay | Direct WhatsApp chat UX (zero latency, native feel) | The relay IS the product. Context summaries + smart routing are the differentiator. Coexistence is fallback for production. |
| `/` prefix for agent commands during relay | Simple, universal convention, zero ambiguity | Fully friction-free "just type" (owner must remember prefix for commands) | Only 3-4 commands needed mid-session. `/done` is the main one. Everything else is forwarded by default. |
| Phrase matching over ML for escalation | Simple, fast, no training data needed | Nuanced detection (sarcasm, implied frustration) | 15-20 trigger phrases cover 90%. GPT-5 mini as fallback. |
| Max 8 tool calls per turn | Safety against infinite loops | Deep multi-step reasoning | Covers search --> details --> compare --> escalate in one turn. |
| List Messages over Commerce Catalog | Flexible, no Meta approval, dynamic per-query | Native product cards with "Add to Cart" UX | Used cars are one-of-a-kind, prices negotiable, India compliance burdensome for Commerce API. |
| Sequential images over Carousel Templates | Dynamic per-query, no pre-approval needed | Swipeable card UX | Carousel templates need 24-48hr Meta approval. Can't generate dynamically. |
| One relay session at a time | Simple state management, no multiplexing | Parallel customer conversations | MVP constraint. Owner is used to serial WhatsApp conversations. |
| Daily wrap over persistent full history in context | Manageable token usage, targeted retrieval | Always-available full context | Full history would explode context window. Wrap + RAG retrieval is the right pattern. |
| OTP login over password/email auth | Zero ongoing friction, owner-controlled invites | Self-service signup, password reset flow | SDRs are 2-3 people. Owner hands them a code. Enterprise auth is overkill. |
| Role-based tool access over single admin | SDRs can relay but not modify inventory | Simpler codebase (one role) | Prevents accidental catalogue changes by junior staff. Owner stays in control. |
| Demo data (Sharma Motors) | Controlled, pre-validated, 20 cars | Real dealer data | Demo must not fail. Real data post-hackathon. |

---

## 10. What "Done" Looks Like

The demo runs the "Rajesh's Tuesday" script (see `DEMO_FLOW.md`) end to end:

1. Owner uploads PDF --> 20 cars parsed and live
2. Owner adds an SDR: "Add Mayani as SDR, 9876543210" --> OTP generated
3. SDR logs in from their phone: `/login` --> enters OTP --> verified
4. Customer from YouTube reel --> source-aware greeting --> browses with photos --> compares cars --> escalation fires
5. SDR opens relay session (types "ertiga wale se baat karna hai") --> gets summary + last 5 messages --> talks to customer through the agent --> types `/done` --> agent resumes
6. Difficult customer --> agent recovers the sale --> handles manipulation --> resists prompt injection
7. Owner asks "kitne leads aaye?" --> gets answer. "Creta sold" --> removed. Token screenshot --> car reserved --> next customer redirected.

Every response is grounded in real catalogue data. No hallucinations. No fake prices. The agent knows when to sell, when to relay, and when to shut up.
