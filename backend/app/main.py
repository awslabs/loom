"""
Loom Backend API

FastAPI application for the Loom Agent Builder Playground.
Provides endpoints for agent registration, invocation, and log retrieval.
"""
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import init_db
from app.routers import a2a, admin, agents, approvals, auth, costs, credentials, identity_providers, integrations, invocations, logs, mcp, memories, registry, security, settings, traces

# Configure logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan handler.

    Initializes the database on startup and performs cleanup on shutdown.
    """
    logger.info("Initializing Loom backend...")

    # Initialize database (create tables if they don't exist)
    try:
        init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

    # Initialize registry client from site_settings (or env var fallback)
    try:
        from app.services.registry import init_registry_from_db
        from app.db import SessionLocal
        db_session = SessionLocal()
        try:
            init_registry_from_db(db_session)
        finally:
            db_session.close()
    except Exception as e:
        logger.warning("Failed to initialize registry client: %s", e)

    yield

    # Cleanup
    logger.info("Shutting down Loom backend...")


# Create FastAPI application
app = FastAPI(
    title="Loom Backend API",
    description="Backend API for the Loom agent platform",
    version="1.6.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# Configure CORS
FRONTEND_PORT = os.getenv("LOOM_FRONTEND_PORT", "5173")
_default_origins = [
    f"http://localhost:{FRONTEND_PORT}",
    "http://127.0.0.1:5173",
]
_extra_origins = os.getenv("LOOM_ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS = _default_origins + [o.strip() for o in _extra_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(a2a.router)
app.include_router(admin.router)
app.include_router(agents.router)
app.include_router(approvals.router)
app.include_router(auth.router)
app.include_router(costs.router)
app.include_router(credentials.router)
app.include_router(identity_providers.router)
app.include_router(integrations.router)
app.include_router(invocations.router)
app.include_router(logs.router)
app.include_router(mcp.router)
app.include_router(memories.router)
app.include_router(registry.router)
app.include_router(security.router)
app.include_router(settings.router)
app.include_router(traces.router)


@app.get("/")
async def root() -> dict:
    """Root endpoint - health check."""
    return {
        "service": "Loom Backend API",
        "version": "1.6.0",
        "status": "running"
    }


@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("LOOM_BACKEND_PORT", "8000"))
    host = os.getenv("LOOM_BACKEND_HOST", "127.0.0.1")  # nosec B104
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=True,
        log_level=LOG_LEVEL.lower()
    )
