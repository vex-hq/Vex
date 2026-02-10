"""FastAPI application factory for the AgentGuard Ingestion API.

The service receives agent execution telemetry from the SDK and pushes
events onto a Redis Stream (``executions.raw``) for downstream
processing by the storage worker.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.redis_client import get_redis
from app.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application-level resources (Redis connection)."""
    app.state.redis = await get_redis()
    yield
    await app.state.redis.aclose()


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application instance."""
    app = FastAPI(
        title="AgentGuard Ingestion API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(router)
    return app


app = create_app()
