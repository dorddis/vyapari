# Vyapari Agent - Live Status

**Last Updated:** 2026-04-23 IST (Phase 3.5 audit-remediation complete)
**Master State:** 362/362 tests passing. +67 commits local, not yet pushed.
**Current Commit (local):** 2862805

---

## Phase 3.5 — Audit Remediation Complete (Apr 23)

Post-Phase-3, 5-agent `/review` pass surfaced 38 findings across logic,
gaps, security, quality, and build. Each was verified against the live
code (33 CONFIRMED, 1 REFUTED, 4 REFINED) and landed across 6 merged PRs
on top of master:

- **p3.5a (cross-tenant isolation, pilot blocker)** — media download
  through tenant-bound adapter, templates.py tenant-aware, escalation
  staff filter, wa_id endpoint scoping, webhook signature strict, +
  6 review follow-ups including legacy-token spoof via X-Business-Id.
- **p3.5b (immediate exploits)** — multipart filename path traversal,
  duplicate Pydantic validator shadowing, Win32 reserved-name handling,
  extension-preserving sanitizer.
- **p3.5c (data correctness)** — tool_assign_lead persist (was
  throwing away mutation), interested_cars list-ref bug, broadcast
  and batch_followup noop stubs removed (raise NotImplementedError),
  staging auth gate inversion, touch_inbound always records.
- **p3.5d (security hardening)** — upload size+MIME gates on voice +
  image endpoints, webhook 2MB body cap, media_id numeric regex,
  onboard_tenant reads secrets from env (not argv/getpass), Graph
  template-policy errors flip local row to PAUSED.
- **p3.5e (ops robustness)** — /health/live + /health/ready with real
  DB + encryption-key checks, relay advisory lock (cross-replica),
  expiry loop per-session try, 429/5xx retry with jittered backoff.
- **p3.5f (dead code + hygiene)** — delete message_store.py +
  conversation.py + owner_agent.py + USE_OPENAI=False branches,
  .env.example reconcile, explicit pins for cryptography +
  python-multipart, api_keys throttle test.

Plus a comment-tightening pass across PR-1 and PR-2 (-512 lines).

Total: 36 commits, +105 tests (257 -> 362), 3 dead files deleted,
grep fence clean.

**67 commits on local master, not yet pushed to origin.**

**Next:** Phase 4 (Docker + CI + Fly.io + Sentry + structlog + rate
limiting + worker process), ~1 week eng. Starts in a fresh session.

---

## Phase 0-3 Rewrite Complete (Apr 22-23)

Sid ran a systematic GTM rewrite over 2 days, taking Vyapari from the
hackathon prototype to a multi-tenant SaaS-ready backend:

- **Phase 0/0.5:** Unbroke WhatsApp adapter + webhook hardening.
- **Phase 1/1.8:** Full Cloud API surface (27 outbound + 11 inbound shapes, pywa fixtures ported, 101 new tests).
- **Phase 2/2.7:** 24h customer-service window + template catalog + outbound dispatcher.
- **Phase 3/3.11:** Multi-tenancy — encrypted per-business WhatsApp creds, per-tenant adapter via ContextVar, per-business API keys, DB-backed cross-replica idempotency, tenant onboarding CLI, grep fence.

**31 commits on local master (Phase 0-3) + 36 more commits (Phase 3.5) = 67 total local commits.** Full trail in parent
repo's STATUS.md and session logs under `sessions/ai-sales-agent/`.

Coordinate before pulling or pushing — the master branch has significant
new code that team members will need to rebase onto. Ops scripts:

- `scripts/onboard_tenant.py` — provision a new business + encrypted WA channel + initial API key
- `scripts/mint_api_key.py` — issue per-business REST auth
- `scripts/register_starter_templates.py` / `scripts/sync_templates.py` — Meta templates
- `scripts/check_no_tenant_hardcodes.py` — grep fence (wire into pre-commit)

**Next:** Phase 4 (Docker + CI + Fly.io + Sentry + rate limiting) — starting in a fresh session.

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

### 1. ~~Missing API Endpoints~~ DONE (6f37b61)
`POST /api/owner/send`, `/api/owner/release`, `/api/owner/query` committed to master. All route through `dispatch()`.

### 2. ~~Remaining `state._dict` access~~ DONE (2f362d6)
Agent A fixed `leads.py` and `staff.py` in commit 2f362d6.

### 3. Frontend fixes needed (Mayani's files -- DO NOT TOUCH)

These are documented for Mayani to fix when she rebases `codex/dashboard-frontend`:

**`owner.js` -- `openConversation()` must load full DB history:**
- Currently: `GET /api/messages/{customerId}` (outbox only, empty on page load)
- Should be: `GET /api/conversation/{customerId}` (full DB history)
- Map `role === "agent"` to display as "bot"

**`customer.js` -- polling filter too narrow:**
- Currently: `if (msg.role === "owner")` (misses bot outbox messages)
- Should be: `if (msg.role !== "customer")` (shows all non-customer messages)

---

## Open PRs

| PR | Branch | Author | Status | Action |
|----|--------|--------|--------|--------|
| #1 | dev-rowl | Rahul | Stale | Close it. Cherry-picked already. |
| #2 | codex/dashboard-frontend | Mayani | Active | React dashboard. Rebase onto master. |
| #3 | feat/evals-prompt-tuning | Agent | REVIEWED | Cherry-pick eval tests only. Code regresses fixes. |
| #4 | feat/voice-notes | Agent | MERGED | Voice STT+TTS merged to master. |

---

## Known Issues

1. **Supabase DB pooler** -- `mhxpcsylxicnzujgtepa` pooler returns "Tenant not found" (new project, needs propagation time). Direct connection fails from Windows (IPv6). SQLite fallback works locally.
2. **mark_sold via owner agent** -- sometimes returns None (agent skips tool call). Prompt tuning needed (Agent A).
3. **Escalation notification to owner** -- fires but demo check wasn't finding it (Agent A).
4. **`interested_cars` not persisted** -- `update_customer_interested_cars()` missing from state.py. Agent B to add.

---

## Requested Changes (Cross-Agent)

### Agent B (DB/infra) will do:
- [x] ~~Commit `web_api.py` with 3 missing owner endpoints~~ DONE (6f37b61)
- [ ] Add `update_customer_interested_cars(wa_id, cars)` to state.py
- NOT touching `static/*` -- documented for Mayani instead

### Agent A (agents/routing) will do:
- [x] ~~Fix `vyapari_agents/tools/leads.py:107-108`~~ DONE (2f362d6)
- [x] ~~Fix `vyapari_agents/tools/staff.py:28`~~ DONE (2f362d6)
- [ ] Cherry-pick eval tests from PR #3
- [ ] Fix mark_sold prompt in owner agent
- [ ] Fix escalation notification check

### Mayani (frontend):
- [ ] Rebase codex/dashboard-frontend onto current master
- [ ] Fix `owner.js:openConversation()` to use `GET /api/conversation/{id}` for full DB history
- [ ] Fix `customer.js:pollMessages()` filter: `msg.role !== "customer"` instead of `=== "owner"`
- [ ] Owner conversation detail response now includes `text` field alongside `content` (both have same value)
- [ ] `GET /api/conversations` now returns `mode`, `has_escalation`, `last_activity` fields
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
