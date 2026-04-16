# Vyapari Agent - Live Status

**Last Updated:** 2026-04-16 18:30 IST
**Master State:** 45/45 tests passing, stable
**Current Commit:** cb54422

---

## CRITICAL: COORDINATION RULES FOR ALL AGENTS

**Multiple agents are working simultaneously and stepping on each other's files. Follow these rules:**

### File Ownership (LOCKED — do not violate)

| Files | Owner Agent | No One Else Touches |
|-------|------------|---------------------|
| `router.py`, `vyapari_agents/customer.py`, `vyapari_agents/owner.py`, `vyapari_agents/prompts.py`, `vyapari_agents/tools/*` | **Agent A (Sid's main session)** | Tools, agents, routing |
| `state.py`, `db_models.py`, `database.py`, `config.py` | **Agent B (DB/infra agent)** | State management, DB schema |
| `services/*` | **Agent A** (auth, relay, escalation, vision, image_store, owner_setup) | Services |
| `web_api.py`, `main.py` | **SHARED — coordinate before editing** | API layer |
| `channels/*` | **Agent A** (base), **Rahul** (web_clone, whatsapp) | Channel adapters |
| `static/*` | **Mayani** | Frontend |
| `tests/*` | **Whoever owns the file being tested** | Tests follow source ownership |
| `models/*` | **Agent A** (schemas, enums) | Shared contracts |
| `docs/*` | **Any** | Documentation |

### Rules
1. **NEVER push to master without running `pytest tests/ -v` first. All 45 tests must pass.**
2. **NEVER modify a file you don't own.** If you need a change in someone else's file, document it in this STATUS.md under "Requested Changes" and wait.
3. **If you add a new function to state.py**, add it to both the in-memory AND DB-backed versions (they keep flipping).
4. **All PRs go through review** before merge. No direct pushes to master for new features.

---

## What's on Master (Working)

### Infrastructure
- `config.py` — full env config (OpenAI, Supabase, WhatsApp, channels)
- `database.py` — async engine, lazy init, SQLite fallback
- `db_models.py` — SQLAlchemy ORM tables
- `state.py` — DB-backed (SQLAlchemy) with same Pydantic interface as in-memory version
- `models/` — 9 enums + 10+ Pydantic schemas

### Agents (OpenAI Agents SDK, GPT-5.4)
- `vyapari_agents/customer.py` — 10 tools, dynamic prompts, conversation history, source-aware greeting, prompt injection guardrail, AgentResponse with images + escalation data
- `vyapari_agents/owner.py` — 25 tools (incl. vision), dynamic prompts
- `vyapari_agents/tools/` — 7 tool files: catalogue, business, communication, leads, staff, relay, vision

### Services
- `services/auth.py` — OTP login (pyotp + bcrypt, 3-attempt lockout)
- `services/relay.py` — session open/close/forward/context
- `services/escalation.py` — async regex + GPT-4.1 nano LLM classifier
- `services/vision.py` — GPT-5.4 vision (PDF parsing, UPI screenshot, car ID) with Pydantic structured output
- `services/image_store.py` — Supabase Storage upload, local fallback
- `services/owner_setup.py` — /setup onboarding flow

### Channel Abstraction
- `channels/base.py` — abstract ChannelAdapter interface + factory
- `channels/web_clone/adapter.py` — in-memory outbox for frontend polling

### API + Server
- `router.py` — message dispatcher (role lookup, state machine, all handlers wired, orphan recovery)
- `main.py` — FastAPI, webhook (HMAC verification), background relay expiry, lifespan
- `web_api.py` — REST endpoints: chat, owner/chat, messages, conversations, staff, catalogue, upload-image, voice, reset

### Tests
- 45 tests passing (router 10, auth 8, relay 8, escalation 6, catalogue 8, owner_setup 5)

---

## Demo Flow Test Results (Last Run)

| # | Capability | Status | Notes |
|---|-----------|--------|-------|
| 1 | Customer search ("SUV under 8L") | PASS | Hinglish, real data, images queued |
| 2 | Escalation ("best price") | PASS | State → escalated |
| 3 | Owner oracle ("kitne leads?") | PASS | Real data |
| 4 | Relay open ("Nexon wale se baat karo") | PASS | Finds customer by interested_cars |
| 5 | Relay forward (owner → customer) | PASS | Forwarded silently |
| 6 | Relay close (/done) | PASS | State → active |
| 7 | Mark sold ("Alto bik gayi") | NEEDS FIX | Agent sometimes returns None |
| 8 | Images inline | PASS | 2 images queued |
| 9 | Escalation notification to owner | NEEDS FIX | Sent but check wasn't finding it |

---

## Open PRs (DO NOT MERGE WITHOUT REVIEW)

| PR | Branch | Author | Status | Action Needed |
|----|--------|--------|--------|---------------|
| #1 | dev-rowl | Rahul | Stale | Cherry-picked useful parts already. Close or rebase. |
| #2 | codex/dashboard-frontend | Mayani | Active | React dashboard. No file overlap. Safe to merge after rebase onto master. |
| #3 | feat/evals-prompt-tuning | Agent | REVIEWED — DO NOT MERGE AS-IS | Regresses our fixes (removes guardrail, removes async escalation, removes image tracking, removes orphan recovery). Cherry-pick eval tests only. |
| #4 | feat/voice-notes | Agent | New | Voice note STT+TTS. Review needed. |

---

## Known Issues

1. **state.py keeps flipping** between in-memory and DB-backed versions. Two agents editing it. Current master has DB-backed version. The in-memory version works but doesn't persist across restarts.
2. **Supabase DB pooler connection** fails from Windows (IPv6 DNS issue). SQLite fallback works fine.
3. **interested_cars** not persisted in DB-backed state.py (no `update_customer_interested_cars` function). Works in in-memory version.
4. **mark_sold via owner agent** sometimes returns None (agent fails to call the tool). Needs prompt tuning.
5. **PR #3 has good eval tests** but the code changes conflict with master's security/logic fixes.

---

## Requested Changes (Cross-Agent Coordination)

### For Agent B (DB/infra):
- [ ] Add `update_customer_interested_cars(wa_id, cars)` to DB-backed state.py
- [ ] Add `get_staff_raw(wa_id)` to DB-backed state.py (returns any status including invited/removed)
- [ ] Do NOT modify router.py, customer.py, owner.py, or any services/* files

### For Agent A (Sid's main session):
- [ ] Cherry-pick eval tests from PR #3 (tests/evals/*)
- [ ] Fix mark_sold prompt (owner agent sometimes ignores the tool)
- [ ] Fix escalation notification check in demo test

### For Mayani:
- [ ] Rebase codex/dashboard-frontend onto current master
- [ ] Open PR when ready

### For Rahul:
- [ ] Close PR #1 (already cherry-picked)
- [ ] Continue web_clone frontend on a fresh branch from master

---

## File Inventory (47 Python files)

```
src/
  config.py, database.py, db_models.py, state.py, router.py, main.py, web_api.py
  catalogue.py, whatsapp.py, conversation.py (legacy), owner_agent.py (legacy), message_store.py (legacy)
  models/: __init__.py, enums.py, schemas.py
  vyapari_agents/: __init__.py, customer.py, owner.py, context.py, prompts.py
  vyapari_agents/tools/: __init__.py, catalogue.py, business.py, communication.py, leads.py, staff.py, relay.py, vision.py
  services/: __init__.py, auth.py, relay.py, escalation.py, vision.py, image_store.py, owner_setup.py
  channels/: __init__.py, base.py, web_clone/__init__.py, web_clone/adapter.py, whatsapp/__init__.py
  tests/: __init__.py, conftest.py, test_auth.py, test_escalation.py, test_owner_setup.py, test_relay.py, test_router.py
  tests/test_tools/: __init__.py, test_catalogue.py
```
