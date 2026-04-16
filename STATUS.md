# Vyapari Agent - Live Status

**Last Updated:** 2026-04-16 21:30 IST
**Master State:** 45/45 tests passing, stable
**Current Commit:** 8f50504

---

## CRITICAL: COORDINATION RULES FOR ALL AGENTS

**Multiple agents are working simultaneously. Follow these rules or we get merge conflicts.**

### File Ownership (LOCKED)

| Files | Owner | Do Not Touch |
|-------|-------|--------------|
| `router.py`, `vyapari_agents/**` | **Agent A** | Routing, agents, tools |
| `state.py`, `db_models.py`, `database.py` | **Agent B** | State, DB, schema |
| `services/*` | **Agent A** | auth, relay, escalation, vision, image_store, owner_setup |
| `web_api.py` | **SHARED** | Coordinate before editing. Agent B has pending changes (see below) |
| `main.py` | **SHARED** | Coordinate before editing |
| `config.py` | **Agent B** | Config values |
| `channels/*` | **Agent A** / Rahul | Channel adapters |
| `static/*` | **Mayani** | Frontend HTML/JS/CSS |
| `tests/*` | Follows source ownership | Tests for the file you own |
| `models/*` | **Agent A** | Pydantic schemas, enums |
| `docs/*`, `STATUS.md`, `AGENTS.md` | **Any** | Documentation |

### Rules
1. **Run `pytest tests/ -v` before pushing. All tests must pass.**
2. **Never modify a file you don't own.** Document needed changes in STATUS.md "Requested Changes".
3. **Pull before pushing.** `git pull origin master` first.
4. **No direct pushes of new features** -- use PRs for anything non-trivial.

---

## What's Done (on master)

### Infrastructure (Agent B -- COMPLETED)
- [x] `db_models.py` -- 12 SQLAlchemy ORM tables matching design doc
- [x] `database.py` -- Supabase pooler support + graceful SQLite fallback
- [x] `state.py` -- **Full rewrite**: 26 functions swapped from in-memory dicts to SQLAlchemy DB queries. Same Pydantic interface, zero caller changes.
- [x] `state.get_staff_raw()` -- new function for auth.py (sees INVITED/REMOVED status)
- [x] Supabase project `mhxpcsylxicnzujgtepa` (dorddis org, Mumbai) -- 12 tables created + seed data
- [x] SQL migration: `supabase/migrations/20260416000000_full_schema.sql`
- [x] `.env` updated to new project (pooler URL)
- [x] Security hardening cherry-picked from dev-rowl (CORS, HMAC, timezone fixes)
- [x] `tests/conftest.py` -- forces in-memory SQLite for tests, seeds business without owner collision
- [x] `tests/test_auth.py` -- updated to use `get_staff_raw()` instead of `state._staff`

### Agents + Services (Agent A -- COMPLETED)
- [x] Customer agent (10 tools, GPT-5.4, source-aware greeting, prompt injection guardrail)
- [x] Owner agent (25 tools incl. vision)
- [x] All 7 tool modules
- [x] All 6 services (auth, relay, escalation, vision, image_store, owner_setup)
- [x] Router with full dispatch + orphan recovery

### Demo Tested E2E (Agent B verified)
- [x] `POST /api/chat` -- customer chat works, agent responds in Hinglish with car images
- [x] `GET /api/conversations` -- owner panel lists conversations with correct fields
- [x] `GET /api/conversation/{wa_id}` -- full DB history (customer + agent + owner messages)
- [x] `POST /api/owner/query` -- oracle works ("How many leads?")
- [x] `POST /api/owner/send` -- relay opens + forwards message, mode switches to "owner"
- [x] `POST /api/owner/release` -- relay closes, mode switches back to "bot"

---

## What's NOT Done (Blocking Demo)

### 1. Missing API Endpoints in `web_api.py` (Agent B needs to commit)

**STATUS: Code written + E2E tested but NOT YET COMMITTED to master.**

The frontend (`owner.js`) calls these endpoints which exist in Agent B's local changes but were lost in a branch merge:

| Endpoint | Purpose | Frontend uses it |
|----------|---------|-----------------|
| `POST /api/owner/send` | Owner sends relay message to customer | `owner.js:261` |
| `POST /api/owner/release` | Owner releases relay (/done) | `owner.js:239` |
| `POST /api/owner/query` | Owner oracle query | `owner.js:304` |

**Agent B will commit these.** Agent A should NOT edit `web_api.py` until this is done.

### 2. `owner.js` needs to load history from DB

**STATUS: Code written but NOT YET COMMITTED.**

`openConversation()` in `owner.js` fetches `/api/messages/{id}` (outbox-only) but needs to fetch `/api/conversation/{id}` (full DB history). Agent B has the fix ready.

**This touches `static/owner.js` (Mayani's ownership).** Sid to approve before commit.

### 3. Remaining `state._dict` access in agent tools (Agent A's files)

3 files still directly access internal dicts that no longer exist in DB-backed state.py:

| File | Line | Code | Fix Needed |
|------|------|------|------------|
| `vyapari_agents/tools/leads.py` | 107 | `state._conversations` | Use `state.list_customers()` count |
| `vyapari_agents/tools/leads.py` | 108 | `state._messages` | Remove or use DB query |
| `vyapari_agents/tools/staff.py` | 28 | `state._staff.get(wa_id)` | Use `state.get_staff_raw(wa_id)` |

**These will crash at runtime** if those tools are called. Agent A owns these files.

### 4. `customer.js` polling fix

`pollMessages()` filters `msg.role === "owner"` which misses bot messages from outbox. Agent B has fix ready (`msg.role !== "customer"` instead). Needs Sid approval since it's `static/` (Mayani's ownership).

---

## Open PRs

| PR | Branch | Author | Status | Action |
|----|--------|--------|--------|--------|
| #1 | dev-rowl | Rahul | Stale | Close it. Cherry-picked already. |
| #2 | codex/dashboard-frontend | Mayani | Active | React dashboard. Rebase onto master. |
| #3 | feat/evals-prompt-tuning | Agent | REVIEWED | Cherry-pick eval tests only. Code regresses fixes. |
| #4 | feat/voice-notes | Agent | New | Voice STT+TTS. Review needed. |

---

## Known Issues

1. **Supabase DB pooler** -- `mhxpcsylxicnzujgtepa` pooler returns "Tenant not found" (new project, needs propagation time). Direct connection fails from Windows (IPv6). SQLite fallback works locally.
2. **mark_sold via owner agent** -- sometimes returns None (agent skips tool call). Prompt tuning needed (Agent A).
3. **Escalation notification to owner** -- fires but demo check wasn't finding it (Agent A).
4. **`interested_cars` not persisted** -- `update_customer_interested_cars()` missing from state.py. Agent B to add.

---

## Requested Changes (Cross-Agent)

### Agent B (DB/infra) will do:
- [ ] Commit `web_api.py` with 3 missing owner endpoints (owner/send, owner/release, owner/query)
- [ ] Commit `owner.js` fix (load full DB history via `/api/conversation/`)
- [ ] Commit `customer.js` polling fix
- [ ] Add `update_customer_interested_cars(wa_id, cars)` to state.py
- [ ] **Needs Sid's OK** before touching `static/*` files (Mayani's ownership)

### Agent A (agents/routing) will do:
- [ ] Fix `vyapari_agents/tools/leads.py:107-108` -- replace `state._conversations` / `state._messages`
- [ ] Fix `vyapari_agents/tools/staff.py:28` -- replace `state._staff.get()` with `state.get_staff_raw()`
- [ ] Cherry-pick eval tests from PR #3
- [ ] Fix mark_sold prompt in owner agent
- [ ] Fix escalation notification check

### Mayani:
- [ ] Rebase codex/dashboard-frontend onto current master
- [ ] Open PR when ready

### Rahul:
- [ ] Close PR #1
- [ ] Fresh branch from master for web_clone work

---

## Supabase Project Info

| Key | Value |
|-----|-------|
| Project ref | `mhxpcsylxicnzujgtepa` |
| Org | `dorddis` (psfbxpjwzulvjlkqjnkk) |
| Region | ap-south-1 (Mumbai) |
| DB password | `VyapariHack2026!` |
| Direct host | `db.mhxpcsylxicnzujgtepa.supabase.co:5432` (IPv6 only from Windows) |
| Pooler host | `aws-0-ap-south-1.pooler.supabase.com:6543` (not propagated yet) |
| Storage bucket | `images` (public) |
| Tables | 12 (businesses, catalogue_items, faqs, staff, customers, conversations, messages, escalations, relay_sessions, daily_wraps, owner_setup, message_logs) |
| Seed data | demo-sharma-motors business + Rajesh owner |

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
