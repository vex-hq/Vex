"""FastAPI application factory for the AgentGuard Dashboard API.

Provides:
- ``GET /health`` -- service health check.
- ``WS /ws`` -- WebSocket endpoint for real-time execution updates.

A background task subscribes to the ``executions.stored`` Redis Stream
and broadcasts new execution events to all connected WebSocket clients.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.websocket import stream_updates, websocket_endpoint

logger = logging.getLogger("agentguard.dashboard-api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle: start/stop the Redis Stream listener."""
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")

    # Start the background stream listener
    stream_task = asyncio.create_task(stream_updates(redis_url))
    logger.info("Dashboard API started, Redis stream listener active")

    yield

    # Shutdown: cancel the background task
    stream_task.cancel()

    try:
        await stream_task
    except asyncio.CancelledError:
        pass

    logger.info("Dashboard API shutting down")


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application instance."""
    app = FastAPI(
        title="AgentGuard Dashboard API",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health_check():
        """Return service health status."""
        return {"status": "healthy"}

    app.add_api_websocket_route("/ws", websocket_endpoint)

    return app


app = create_app()
