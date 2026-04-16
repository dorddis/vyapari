# Vyapari Agent - Codex Instructions

## Project
AI sales agent for high-ticket businesses. Demo vertical: used car dealership.
Hackathon: OpenAI Codex Hackathon, Bengaluru, April 16-17, 2026.
Team: Low Cortisol Gang (4 members).

## Architecture (LOCKED - do not change)
- **LLM:** OpenAI GPT-5 (main), GPT-4.1 nano (classification), Whisper (STT)
- **Framework:** OpenAI Agents SDK (primary). LangGraph if complex routing needed.
- **Backend:** FastAPI + PostgreSQL
- **Channels:** WhatsApp Cloud API (primary), Web demo (fallback)
- **No RAG.** Simple JSON catalogue + keyword matching.
- **No OpenClaw.** Team vetoed.

## Tech Stack
- Python 3.13.5
- FastAPI + uvicorn
- PostgreSQL (asyncpg or SQLAlchemy async)
- OpenAI Agents SDK / LangGraph
- WhatsApp Cloud API (Meta Business)
- Pydantic for validation

## Code Standards
- Type hints on all functions
- Pydantic models for API request/response schemas
- Async everywhere (FastAPI native async)
- Environment variables via python-dotenv, never hardcode secrets
- Conventional commits: `type(scope): description`
- No co-authored-by lines

## Project Structure
```
src/
  agents/     # OpenAI agent definitions + tools
  api/        # FastAPI routes
  bot/        # WhatsApp webhook + message handling
  db/         # PostgreSQL models + queries
data/         # Sample catalogue, FAQs, business profile
docs/         # Specs, design doc, features
research/     # Market research, API docs, reference implementations
```

## Key References
- Design doc: `docs/DESIGN_DOC.md`
- Feature spec: `docs/FUNCTIONAL_REQUIREMENTS.md`
- Demo flow: `docs/DEMO_FLOW.md`

## Demo Data
- `data/catalogue.json` - 20 used car listings
- `data/faqs.json` - 20 dealer FAQ pairs
- `data/business_profile.json` - "Sharma Motors" profile

## P0 Features (Must ship at hackathon)
1. Customer conversation engine (greeting, inventory Q&A, comparison, negotiation)
2. Owner dashboard conversation (stats, escalation alerts, oracle)
3. Escalation detection + owner notification
4. Owner hijack (take over conversation, agent steps back)
5. Catalogue search + filtering via tool calls
6. Multi-turn conversation memory (PostgreSQL)
7. Guardrails (prompt injection protection, on-topic enforcement)

## Running the project
```bash
# Install dependencies
pip install -r src/requirements.txt

# Set environment
cp .env.example .env  # Fill in OPENAI_API_KEY, DATABASE_URL, etc.

# Run dev server
uvicorn src.main:app --reload --port 8000
```
