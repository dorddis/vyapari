# Vyapari Agent

AI sales agent for high-ticket businesses. WhatsApp-native. Built for the Codex Hackathon (April 16-17, 2026).

**Demo vertical:** Used car dealership (Sharma Motors, Mumbai)

## What It Does

A dealer posts a viral reel. 200 WhatsApp messages in 3 hours. 2 staff. 150 go unanswered. Each lost lead costs Rs 3-8 lakh.

Vyapari Agent handles the overflow -- answers questions, browses inventory with photos, compares cars, detects buying signals, and relays the owner in when it's time to close. The owner never opens a dashboard. They just talk to the agent.

## Architecture

```
Customer (WhatsApp) <-> Vyapari Agent (FastAPI + OpenAI) <-> Owner/SDR (WhatsApp)
                              |
                         PostgreSQL
                         (sessions, catalogue, leads)
```

- **Customer Agent** -- per-customer sessions, catalogue tools, escalation detection
- **Owner Agent** -- analytics, catalogue management, relay sessions, staff management
- **Message Router** -- role-based routing (customer/owner/SDR), relay state machine
- **Relay System** -- owner talks to customers through the agent with `/` commands

See `docs/DESIGN_DOC.md` for the full specification.

## Quick Start

```bash
cd whatsapp-demo
cp ../.env.example .env
pip install -r requirements.txt
python3 main.py                  # http://localhost:3000
```

Current local demo scope is intentionally minimal:
- Single WhatsApp-style customer chat interface
- Quick message chips for common buyer intents
- Lightweight `/api/chat` placeholder endpoint to plug in the real agent later

## Project Structure

```
vyapari/
|-- docs/                  # Design doc, demo flow, requirements
|-- data/                  # Sharma Motors demo data (20 cars, FAQs, business profile)
|-- research/              # Implementation reference (WhatsApp API, OpenAI Agents SDK)
|-- whatsapp-demo/         # Isolated runnable WhatsApp demo (chat-only)
|   |-- main.py            # FastAPI entry point for local web demo
|   |-- config.py          # Demo config
|   |-- message_store.py   # In-memory chat state
|   |-- web_api.py         # Demo REST API
|   |-- static/            # Demo frontend assets
|-- src/                   # Application code
|   |-- config.py          # Environment config
|   |-- catalogue.py       # Catalogue queries
|   |-- conversation.py    # Customer agent (Gemini, to be swapped to OpenAI)
|   |-- owner_agent.py     # Owner oracle agent
|-- .env.example           # Environment template
```

## Team Work Split

| Area | Files | What To Build |
|------|-------|---------------|
| Customer Agent | `conversation.py` | Swap Gemini -> OpenAI Agents SDK, add function tools |
| Owner Agent | `owner_agent.py` | OpenAI Agents SDK, relay tools, staff mgmt tools |
| Router + Relay | `whatsapp-demo/message_store.py`, `whatsapp-demo/web_api.py` | Chat state and demo API flow |
| WhatsApp UX | `whatsapp-demo/static/*` | UI interactions and chat experience |

## Key Docs

- **`docs/DESIGN_DOC.md`** -- The blueprint. Read this first.
- **`docs/DEMO_FLOW.md`** -- Demo script ("Rajesh's Tuesday")
- **`research/AGENT_ARCHITECTURE_SYNTHESIS.md`** -- Why OpenAI Agents SDK, how sessions work
- **`research/OPENAI_AGENTS_SDK_ARCHITECTURE.md`** -- Code patterns for the SDK

## Tech Stack

| Layer | Choice |
|-------|--------|
| Backend | FastAPI (Python) |
| LLM | GPT-5 (OpenAI Agents SDK) |
| Database | PostgreSQL |
| WhatsApp | Cloud API v21.0 via PyWa |
| Web Demo | Vanilla HTML/CSS/JS |
