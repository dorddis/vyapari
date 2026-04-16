"""Centralized configuration — loads from .env, provides typed constants."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR.parent / "data"
STATIC_DIR = BASE_DIR / "static"

# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MAIN_MODEL = os.getenv("OPENAI_MAIN_MODEL", "gpt-5.4")
OPENAI_CLASSIFIER_MODEL = os.getenv("OPENAI_CLASSIFIER_MODEL", "gpt-5.4-mini")
OPENAI_STT_MODEL = os.getenv("OPENAI_STT_MODEL", "gpt-4o-transcribe")
OPENAI_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "")

# If no OpenAI key, fall back to existing Gemini conversation engine
USE_OPENAI = bool(OPENAI_API_KEY)

# ---------------------------------------------------------------------------
# Gemini (fallback)
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "")
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL", "")
DATABASE_ECHO = os.getenv("DATABASE_ECHO", "false").lower() == "true"
DATABASE_POOL_SIZE = int(os.getenv("DATABASE_POOL_SIZE", "10"))
DATABASE_MAX_OVERFLOW = int(os.getenv("DATABASE_MAX_OVERFLOW", "10"))

# Priority: DATABASE_URL > SUPABASE_DB_URL > local SQLite
if not DATABASE_URL and SUPABASE_DB_URL:
    # Convert postgresql:// to postgresql+asyncpg:// for SQLAlchemy async
    DATABASE_URL = SUPABASE_DB_URL.replace(
        "postgresql://", "postgresql+asyncpg://"
    )
if not DATABASE_URL:
    _sqlite_path = BASE_DIR / "vyapari.db"
    DATABASE_URL = f"sqlite+aiosqlite:///{_sqlite_path}"

# ---------------------------------------------------------------------------
# Channel (WhatsApp vs Web Clone fallback)
# ---------------------------------------------------------------------------
CHANNEL_MODE = os.getenv("CHANNEL_MODE", "web_clone")  # "whatsapp" | "web_clone"

# ---------------------------------------------------------------------------
# WhatsApp Cloud API
# ---------------------------------------------------------------------------
WHATSAPP_ENABLED = os.getenv("WHATSAPP_ENABLED", "false").lower() == "true"
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "hackathon-verify-token")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v21.0")
WHATSAPP_API_URL = (
    f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"
    f"/{WHATSAPP_PHONE_NUMBER_ID}/messages"
)
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
META_APP_ID = os.getenv("META_APP_ID", "")

# ---------------------------------------------------------------------------
# Business defaults (single-tenant demo)
# ---------------------------------------------------------------------------
DEFAULT_BUSINESS_ID = os.getenv("DEFAULT_BUSINESS_ID", "demo-sharma-motors")
DEFAULT_BUSINESS_NAME = os.getenv("DEFAULT_BUSINESS_NAME", "Sharma Motors")
DEFAULT_BUSINESS_VERTICAL = os.getenv("DEFAULT_BUSINESS_VERTICAL", "used_cars")
DEFAULT_OWNER_NAME = os.getenv("DEFAULT_OWNER_NAME", "Rajesh")
DEFAULT_OWNER_PHONE = os.getenv("DEFAULT_OWNER_PHONE", "919876543210")

# ---------------------------------------------------------------------------
# Agent behavior & guardrails
# ---------------------------------------------------------------------------
MAX_TOOL_CALLS_PER_TURN = int(os.getenv("MAX_TOOL_CALLS_PER_TURN", "8"))
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "/")
RELAY_SESSION_TIMEOUT_MINUTES = int(os.getenv("RELAY_SESSION_TIMEOUT_MINUTES", "20"))
OWNER_ACTIVE_IDLE_MINUTES = int(os.getenv("OWNER_ACTIVE_IDLE_MINUTES", "15"))
ESCALATION_RESPONSE_TIMEOUT_MINUTES = int(
    os.getenv("ESCALATION_RESPONSE_TIMEOUT_MINUTES", "15")
)
CALLBACK_SLA_MINUTES = int(os.getenv("CALLBACK_SLA_MINUTES", "15"))

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
APP_ENV = os.getenv("APP_ENV", "development")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", f"http://localhost:{PORT}")
