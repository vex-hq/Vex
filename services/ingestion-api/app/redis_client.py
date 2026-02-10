"""Redis connection factory for the ingestion API."""

import os

import redis.asyncio as redis


async def get_redis() -> redis.Redis:
    """Create and return an async Redis client.

    The Redis URL is read from the ``REDIS_URL`` environment variable,
    defaulting to ``redis://localhost:6379`` for local development.
    """
    url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    return redis.from_url(url, decode_responses=True)
