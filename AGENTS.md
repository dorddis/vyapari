# Vyapari Agent - Codex Instructions

## Repo
`dorddis/vyapari` — Hackathon code repo. Team: Sid, Rahul, Mayani, Tanmay.
**NOT** `dorddis/ai-sales-agent` (that's the planning/research repo, separate git).

## Architecture (LOCKED)
- **LLM:** OpenAI GPT-5.4 (main), GPT-4.1 nano (classification)
- **Framework:** OpenAI Agents SDK (`from agents import Agent, Runner, function_tool`)
- **Backend:** FastAPI + async PostgreSQL (Supabase) / SQLite fallback
- **Channels:** Web clone (primary demo), WhatsApp Cloud API (bonus)
- **No RAG.** JSON catalogue + keyword matching via tools.

## Project Structure (Current)
```
vyapari/
  src/
    config.py                 # All env config
    database.py               # Async engine (Supabase/SQLite)
    state.py                  # In-memory state store (async interface)
    router.py                 # Message dispatcher (role lookup, state machine)
    main.py                   # FastAPI entry point
    web_api.py                # REST API endpoints
    catalogue.py              # JSON data queries (reusable)
    conversation.py           # Gemini fallback (legacy)
    owner_agent.py            # Gemini fallback (legacy)
    
    vyapari_agents/           # NOT "agents/" (renamed to avoid SDK collision)
      customer.py             # Customer Agent (9 tools, GPT-5.4)
      owner.py                # Owner Agent (23 tools) + SDR Agent (8 tools)
      context.py              # CustomerContext, StaffContext dataclasses
      prompts.py              # Dynamic system prompt builders
      tools/
        catalogue.py          # search, details, compare, pricing, availability, CRUD
        business.py           # FAQ, business info, greeting
        communication.py      # escalation, callback, broadcast
        leads.py              # active leads, details, stats, assign, batch followup
        staff.py              # add/remove/list staff (OTP)
        relay.py              # open session, get customer number
    
    services/
      auth.py                 # OTP login (pyotp + bcrypt)
      relay.py                # Session open/close/forward
      escalation.py           # Regex + GPT-4.1 nano classifier
    
    channels/
      base.py                 # Abstract ChannelAdapter interface
      web_clone/adapter.py    # In-memory queue (primary demo)
      whatsapp/               # Cloud API (Tanmay building)
    
    models/
      enums.py                # ConversationState, StaffRole, etc.
      schemas.py              # Pydantic schemas (IncomingMessage, ToolResponse, etc.)
    
    tests/                    # 40 tests passing
  
  data/                       # Sharma Motors demo data (20 cars, 20 FAQs)
  docs/                       # Design doc, demo flow, requirements
  research/                   # Implementation reference
```

## IMPORTANT: Import Collision
Our agents package is `vyapari_agents/`, NOT `agents/`. The OpenAI Agents SDK also uses `agents` as its package name. So:
```python
from agents import Agent, Runner          # SDK — correct
from vyapari_agents.customer import ...    # Our code — correct
from agents.customer import ...           # WRONG — would look in SDK
```

## Branches
| Branch | Owner | What |
|--------|-------|------|
| `master` | — | Clean base only |
| `feat/backend` | Sid | Full backend (40/40 tests) |
| `dev-rowl` | Rahul | Vanilla JS demo + test dataset |
| (from dev-rowl) | Mayani | React frontend |

## Running
```bash
cd src
cp ../.env.example .env       # Add OPENAI_API_KEY
pip install -r requirements.txt
python -m pytest tests/ -v    # 40 tests
python main.py                # http://localhost:8000
```

## Code Standards
- Type hints on all functions
- Pydantic models for API schemas
- Async everywhere (`await Runner.run()`, never `run_sync()`)
- Tools return `{"success": bool, "data": ..., "message": str}`
- Conventional commits: `type(scope): description`
- `reasoning.effort = "low"` on all agents (GPT-5.4 tool calling fix)

## Key References
- `docs/DESIGN_DOC.md` — Full system specification
- `docs/DEMO_FLOW.md` — Demo script ("Rajesh's Tuesday")
- `docs/SUPABASE_DB_SETUP.md` — Database connection guide
- `TEAM_TASKS.md` — Who does what, branch strategy
