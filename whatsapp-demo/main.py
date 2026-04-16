"""FastAPI server for the local WhatsApp-style chat demo."""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import state
from config import HOST, PORT
from database import close_db, init_db

STATIC_DIR = Path(__file__).resolve().parent / "static"
WEB_API_PATH = Path(__file__).resolve().parent / "web_api.py"
WEB_API_SPEC = spec_from_file_location("whatsapp_demo_web_api", WEB_API_PATH)
if WEB_API_SPEC is None or WEB_API_SPEC.loader is None:
    raise RuntimeError("Failed to load whatsapp-demo web_api module")
WEB_API_MODULE = module_from_spec(WEB_API_SPEC)
WEB_API_SPEC.loader.exec_module(WEB_API_MODULE)
api_router = WEB_API_MODULE.router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await state.init_state()
    yield
    await close_db()


app = FastAPI(title="Vyapari WhatsApp Demo", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/")
async def serve_frontend() -> FileResponse:
    """Serve the demo chat interface."""
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/health")
async def health() -> dict[str, str]:
    """Basic health endpoint for local checks."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=HOST, port=int(PORT), reload=True)
