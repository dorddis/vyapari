# Supabase Database Connection Guide

## Current Issue

The Supabase instance `fadwxcixytgdvqiavquc` is returning **IPv6-only DNS** which causes `getaddrinfo failed` on Windows. This typically means the **free tier instance is paused** (auto-pauses after 7 days of inactivity).

### Diagnosis Results (Apr 16)

```
DNS:        db.fadwxcixytgdvqiavquc.supabase.co -> IPv6 only (2406:da14:...)  NO IPv4
REST API:   https://fadwxcixytgdvqiavquc.supabase.co/rest/v1/ -> 401 (alive)
Direct DB:  postgresql://...@db.xxx:5432/postgres -> getaddrinfo failed
Pooler DB:  postgresql://...@pooler.supabase.com:6543/postgres -> Tenant not found
```

## Fix: Unpause the Instance

1. **Mayani** (instance owner) needs to log into https://supabase.com/dashboard
2. Go to the project `fadwxcixytgdvqiavquc`
3. If paused: click **"Restore project"** — takes 1-2 minutes
4. After restore, DNS will return an IPv4 address and connections will work

## Connection Strings

### For asyncpg (Python async — what our backend uses)

```
# Direct connection (port 5432) — use this for migrations and admin
postgresql+asyncpg://postgres:w1kn6IK7vN9iSNAt@db.fadwxcixytgdvqiavquc.supabase.co:5432/postgres

# Pooler connection (port 6543) — use this for app connections
# Format: postgres.[PROJECT_REF]:password@pooler-host:6543/postgres
postgresql+asyncpg://postgres.fadwxcixytgdvqiavquc:w1kn6IK7vN9iSNAt@aws-0-ap-south-1.pooler.supabase.com:6543/postgres
```

### For plain psycopg2/psql

```
postgresql://postgres:w1kn6IK7vN9iSNAt@db.fadwxcixytgdvqiavquc.supabase.co:5432/postgres
```

## How to Set It Up in the Backend

### Option 1: Set in .env (simplest)

```bash
# In vyapari/src/.env (gitignored)
SUPABASE_DB_URL=postgresql://postgres:w1kn6IK7vN9iSNAt@db.fadwxcixytgdvqiavquc.supabase.co:5432/postgres
```

`config.py` auto-converts this to `postgresql+asyncpg://...` for SQLAlchemy.

### Option 2: Set DATABASE_URL directly

```bash
DATABASE_URL=postgresql+asyncpg://postgres:w1kn6IK7vN9iSNAt@db.fadwxcixytgdvqiavquc.supabase.co:5432/postgres
```

### Fallback

If neither is set, the backend falls back to **local SQLite** (`vyapari.db` in src/). This works for development — no setup needed.

## Verifying the Connection

```python
# Quick test script
import asyncio, asyncpg

async def test():
    conn = await asyncpg.connect(
        'postgresql://postgres:w1kn6IK7vN9iSNAt@db.fadwxcixytgdvqiavquc.supabase.co:5432/postgres',
        timeout=10,
    )
    version = await conn.fetchval('SELECT version()')
    print(f'Connected: {version}')
    
    tables = await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public'")
    print(f'Tables: {[t["tablename"] for t in tables]}')
    
    await conn.close()

asyncio.run(test())
```

If this prints `Connected: PostgreSQL 15...`, you're good.

## Architecture Notes

- `database.py` creates the async engine lazily (first use, not import time)
- `state.py` is currently in-memory dicts — same async interface that can swap to DB later
- Tables will be created by `database.init_db()` on startup (calls `Base.metadata.create_all`)
- No ORM models in `models/db.py` yet — that's the next step
- For now the backend works fully with in-memory state + SQLite fallback

## If IPv6 Issue Persists After Unpause

Try the **pooler connection** instead (uses a different hostname that resolves to IPv4):

```
SUPABASE_DB_URL=postgresql://postgres.fadwxcixytgdvqiavquc:w1kn6IK7vN9iSNAt@aws-0-ap-south-1.pooler.supabase.com:6543/postgres
```

Note: pooler username format is `postgres.[PROJECT_REF]` not just `postgres`.

## Supabase CLI Login (if needed)

```bash
npx supabase login
# Paste access token from https://supabase.com/dashboard/account/tokens
npx supabase projects list
```
