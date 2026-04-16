# Team Task Division - Hackathon Day 1

Pull latest from `master`. All code lives in `vyapari/src/`.

Backbone is ready — router, models, state, escalation, tests (16/16 passing). Run `pytest tests/ -v` to verify.

**PRIMARY DEMO:** Mobile-first WhatsApp-like web UI on phone Chrome. Backend is channel-agnostic — same agents/router whether message comes from web UI or real WhatsApp.

**BONUS:** Real WhatsApp Cloud API integration (miracle if it works, but backend supports it).

## Who Does What

**Sid (AI Lead)** — Agents + Tools + Backend Integration
- `agents/` — Customer Agent, Owner Agent, all 28 tools, prompts, context
- `database.py` + `main.py` rewrite (router integration, webhook, background tasks)
- `services/auth.py`, `services/relay.py`, `services/template_manager.py`, `services/daily_wrap.py`, `services/session_manager.py`
- Wiring everything into `router.py` handler stubs

**Tanmay (Fullstack)** — WhatsApp Cloud API (Bonus Path)
- `channels/whatsapp/` — client, messages, interactive (lists/buttons), templates, typing indicator, webhook parsing, adapter
- Wire into `channels/base.py` interface (already defined)
- Set up Meta Developer App + test number + ngrok webhook

**Rahul (Fullstack)** — WhatsApp Clone Web UI (PRIMARY DEMO)
- `channels/web_clone/` — implement `WebCloneAdapter` conforming to `channels/base.py`
- `web_api.py` — REST endpoints for the web frontend
- This is THE demo path, not a fallback. Must work on phone Chrome.

**Mayani (AI 2)** — Mobile-First Frontend
- `static/` — WhatsApp-like UI that runs on phone Chrome
- Single chat view (not desktop two-frame layout)
- Render interactive messages: list items as tappable rows, reply buttons as buttons, images inline
- Support two roles: one tab = customer, another tab = owner
- Real-time updates (polling with since_id)

## Branching

We PR everything now. Create a branch from `master`, do your work, open a PR.

```
git checkout -b feat/your-feature-name
# ... work ...
git push -u origin feat/your-feature-name
# Open PR on GitHub
```

## Quick Start

```bash
cd vyapari/src
pip install -r requirements.txt
pytest tests/ -v              # 16 tests should pass
python main.py                # starts on :8000
```

## Key Files to Read First

1. `docs/DESIGN_DOC.md` — the full blueprint
2. `models/` — enums + schemas (the shared contracts)
3. `router.py` — how messages flow (find your handler stub)
4. `channels/base.py` — the interface Tanmay and Rahul implement
5. `config.py` — all env vars

## Rule

No two people edit the same file. If you need something from someone else's file, ask them or wait for their PR.
