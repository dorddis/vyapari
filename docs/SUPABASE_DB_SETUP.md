# Supabase Database Connection Guide

## Active Instance

**Project ref:** `mhxpcsylxicnzujgtepa` (dorddis org, Mumbai region)

> **Note:** There was an older instance `fadwxcixytgdvqiavquc` (Mayani's). That one is **deprecated** — it kept pausing and returning IPv6-only DNS on Windows. All work now uses the dorddis instance below.

## Connection Strings

### For asyncpg (Python async — what our backend uses)

```
# Pooler connection (port 6543, IPv4) — use this for app connections
postgresql+asyncpg://postgres.mhxpcsylxicnzujgtepa:VyapariHack2026!@aws-0-ap-south-1.pooler.supabase.com:6543/postgres
```

### For plain psycopg2/psql

```
postgresql://postgres.mhxpcsylxicnzujgtepa:VyapariHack2026!@aws-0-ap-south-1.pooler.supabase.com:6543/postgres
```

## How to Set It Up in the Backend

### Option 1: Set in .env (simplest)

```bash
# In vyapari/src/.env (gitignored)
SUPABASE_DB_URL=postgresql://postgres.mhxpcsylxicnzujgtepa:VyapariHack2026!@aws-0-ap-south-1.pooler.supabase.com:6543/postgres
```

`config.py` auto-converts this to `postgresql+asyncpg://...` for SQLAlchemy.

### Option 2: Set DATABASE_URL directly

```bash
DATABASE_URL=postgresql+asyncpg://postgres.mhxpcsylxicnzujgtepa:VyapariHack2026!@aws-0-ap-south-1.pooler.supabase.com:6543/postgres
```

### Supabase project config (for storage, auth, etc.)

```bash
SUPABASE_PROJECT_REF=mhxpcsylxicnzujgtepa
SUPABASE_URL=https://mhxpcsylxicnzujgtepa.supabase.co
SUPABASE_SERVICE_KEY=<service role key from Supabase dashboard>
```

### Fallback

If neither is set, the backend falls back to **local SQLite** (`vyapari.db` in src/). This works for development — no setup needed.

## Verifying the Connection

```python
# Quick test script
import asyncio, asyncpg

async def test():
    conn = await asyncpg.connect(
        'postgresql://postgres.mhxpcsylxicnzujgtepa:VyapariHack2026!@aws-0-ap-south-1.pooler.supabase.com:6543/postgres',
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
- `config.py` resolves DB priority: `DATABASE_URL` > `SUPABASE_DB_URL` > local SQLite
- Tables are created by `database.init_db()` on startup (calls `Base.metadata.create_all`)
- For now the backend works fully with in-memory state + SQLite fallback

## Supabase CLI Login (if needed)

```bash
npx supabase login
# Paste access token from https://supabase.com/dashboard/account/tokens
npx supabase projects list
```
