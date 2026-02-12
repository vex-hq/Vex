"""FastAPI application factory for the AgentGuard API Gateway.

Serves as the unified entry point for the SDK.  Handles both synchronous
verification (``/v1/verify``) and async event ingestion (``/v1/ingest``).
Events are emitted to Redis for downstream storage and alerting.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.auth import shutdown_validator
from app.redis_client import get_redis
from app.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application-level resources (Redis connection, auth)."""
    app.state.redis = await get_redis()
    yield
    shutdown_validator()
    await app.state.redis.aclose()


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application instance."""
    app = FastAPI(
        title="AgentGuard API Gateway",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(router)
    return app


app = create_app()
