"""FastAPI application entrypoint for the SH-205 backend.

Run with::

    cd backend
    python -m uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import init_db
from app.core.logging import configure_logging, get_logger
from app.engines.e1_misplacement.registry import get_registry

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown hooks.

    Everything here is best-effort except the database: a missing model or
    credential degrades a feature and is reported by ``/ready``, rather than
    preventing the service from starting.
    """
    configure_logging()
    logger.info(
        "Starting %s v%s (environment=%s)",
        settings.app_name,
        settings.app_version,
        settings.environment,
    )
    logger.info("CORS origins: %s", ", ".join(settings.cors_origins) or "(none)")

    # Creates any missing tables. Alembic still owns migrations; this just
    # means a fresh checkout boots without a separate migration step.
    init_db()

    # Firebase Admin: non-fatal. A missing or bad credential file leaves the
    # server up; protected routes then answer 503 with the reason.
    if settings.auth_enabled:
        from app.core.security import init_firebase

        init_firebase()
    else:
        logger.warning(
            "AUTH_MODE=disabled — every request is treated as a dev admin. "
            "Never use this outside local development."
        )

    # Register the bundled E1 artifact so /model/status has a row to read.
    from app.core.database import SessionLocal
    from app.services.model_artifacts import sync_local_artifact

    with SessionLocal() as db:
        sync_local_artifact(db)

    # Loaded on a background thread so startup never blocks on it and
    # /model/status can report progress.
    if settings.e1_eager_load:
        get_registry().start_background_load()

    # Lets sync routes (which run in the threadpool) broadcast WebSocket
    # events onto the server loop.
    import asyncio

    from app.services.events import bind_event_loop

    bind_event_loop(asyncio.get_running_loop())

    yield

    bind_event_loop(None)
    logger.info("Shutting down %s", settings.app_name)


def create_app() -> FastAPI:
    """Builds the FastAPI application."""
    configure_logging()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Backend for SH-205 Intelligent Shipment Piggybacking: "
            "Predict -> Price -> Plan -> Prove."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # The frontend is deployed to a different origin than the API, so every
    # browser call is cross-origin. `allow_origin_regex` additionally admits
    # Vercel preview deployments, whose hostnames are generated per build and
    # so cannot be listed ahead of time.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex or None,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health lives both at the root (for probes and load balancers) and under
    # the versioned prefix (for API clients).
    app.include_router(api_router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/", tags=["meta"], summary="Service banner")
    async def root() -> dict[str, str]:
        return {
            "service": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
            "health": "/health",
        }

    return app


app = create_app()
