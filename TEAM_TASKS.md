# Team Task Division - Hackathon Day 1

**PRIMARY DEMO:** Mobile-first WhatsApp-like React UI on phone Chrome. Backend is channel-agnostic.

**BONUS:** Real WhatsApp Cloud API integration.

## Branches

| Branch | Owner | Based On | What |
|--------|-------|----------|------|
| `feat/backend` | Sid | `master` | Agents, tools, services, router, state, models |
| `dev-rowl` | Rahul | `master` | Vanilla JS WhatsApp demo, test dataset, backend stubs |
| `feat/frontend` (or similar) | Mayani | `dev-rowl` | React frontend (customer chat + owner dashboard) |
| (TBD) | Tanmay | `master` | `channels/whatsapp/` Cloud API integration |

**Merge order:** Rahul's `dev-rowl` -> master first. Then Mayani's branch -> master. Then Sid's `feat/backend` -> master. Tanmay's whenever ready.

Mayani branches FROM `dev-rowl` (Rahul's work), not from master. They share the frontend space — Rahul built the vanilla JS prototype + API stubs, Mayani rebuilds it in React.

## Who Does What

**Sid (AI Lead)** — branch: `feat/backend`
- `agents/` — Customer Agent, Owner Agent, all 28 tools, prompts, context
- `models/`, `database.py`, `state.py`, `router.py`, `main.py`
- `services/` — auth, relay, escalation, template_manager, daily_wrap, session_manager
- `channels/base.py` — abstract interface
- Tests (40/40 passing)
- Does NOT touch: `static/`, `whatsapp-demo/`, frontend files

**Rahul (Fullstack)** — branch: `dev-rowl`
- `whatsapp-demo/` — standalone vanilla JS WhatsApp chat demo (already done)
- `data/user_question_dataset.json` — test utterances (already done)
- `docs/TESTING.md` — testing strategy (already done)
- `web_api.py` — REST endpoints for frontend
- `channels/web_clone/adapter.py` — WebCloneAdapter

**Mayani (AI 2)** — branch: checked out FROM `dev-rowl`
- `src/frontend/` — React app (mobile-first WhatsApp clone)
  - Customer chat view (single chat, WhatsApp-like)
  - Owner dashboard (conversation list, relay UI, oracle)
  - Interactive message rendering (buttons, lists, images)
  - Two roles via URL route: `/customer` and `/owner`
- Calls same REST API endpoints as Rahul's vanilla demo
- Rahul and Mayani pull/push relative to each other on their branches

**Tanmay (Fullstack)** — branch: TBD from `master`
- `channels/whatsapp/` — Cloud API client, interactive messages, templates, webhook parsing, adapter
- Meta Developer App setup + test number + ngrok
- Wires into `channels/base.py` interface

## File Ownership (No Overlap)

| Files | Owner | Branch |
|-------|-------|--------|
| `agents/`, `models/`, `services/`, `router.py`, `state.py`, `database.py`, `main.py` | Sid | `feat/backend` |
| `whatsapp-demo/`, `data/user_question_dataset.json`, `docs/TESTING.md` | Rahul | `dev-rowl` |
| `src/frontend/` (React app) | Mayani | from `dev-rowl` |
| `channels/whatsapp/` | Tanmay | TBD |
| `channels/base.py` | Sid (read-only for others) | `feat/backend` |
| `web_api.py` | Rahul (Sid will also update on `feat/backend`) | both |
| `config.py` | Sid (Rahul has a copy in `whatsapp-demo/config.py`) | both |

**`web_api.py` conflict note:** Rahul has a demo version, Sid has the router-integrated version. On merge, Sid's version takes priority — Rahul's demo endpoints get folded in.

## Quick Start

```bash
# Backend (Sid's branch)
cd src && pip install -r requirements.txt && pytest tests/ -v  # 40 tests

# Rahul's demo
cd whatsapp-demo && pip install -r requirements.txt && python3 main.py  # :3000

# Mayani's React app (once set up)
cd src/frontend && npm install && npm run dev
```

## Key Files to Read First

1. `docs/DESIGN_DOC.md` — the full blueprint
2. `models/` — enums + schemas (shared contracts)
3. `router.py` — how messages flow
4. `channels/base.py` — channel interface
5. `config.py` — all env vars
