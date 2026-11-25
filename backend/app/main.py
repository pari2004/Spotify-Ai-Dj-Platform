"""FastAPI application entrypoint (PRD §7.1).

Wires the Application API Layer (REST) and the Queue & State Gateway (WebSocket) into one
ASGI app, with CORS for the React dev client, health checks, and structured request IDs.
"""
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .database import init_db
from .realtime.ws import router as ws_router
from .routers import admin, ai, analytics, auth, lounges, recommendations, tracks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("djstudio")

settings = get_settings()

app = FastAPI(
    title="AI DJ Studio API",
    version="1.0.0",
    description="Collaborative Live Queue Curation & Sentiment-Aware Audio Engine (Spotify intern PRD).",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    """Correlation ID per request for structured logging (PRD §10.3)."""
    corr_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = corr_id
    return response


@app.on_event("startup")
def on_startup():
    init_db()
    logger.info("AI DJ Studio API started (db=%s, ai_backend=%s)", settings.database_url, settings.ai_backend)


# --- REST routers ---
app.include_router(auth.router)
app.include_router(tracks.router)
app.include_router(lounges.router)
app.include_router(ai.router)
app.include_router(recommendations.router)
app.include_router(analytics.router)
app.include_router(admin.router)

# --- WebSocket gateway ---
app.include_router(ws_router)


# --- Health checks (PRD §10.3) ---
@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "service": "api"}


@app.get("/health/gateway", tags=["health"])
def health_gateway():
    from .realtime.connection_manager import manager
    return {"status": "ok", "service": "queue-gateway", "activeRooms": len(manager.rooms)}


@app.get("/", tags=["health"])
def root():
    return {"name": "AI DJ Studio API", "version": "1.0.0", "docs": "/docs"}
