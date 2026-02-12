"""Redis Stream consumer loop for the storage worker.

Connects to Redis and runs two consumer loops:

1. ``storage-workers`` on ``executions.raw`` — stores raw execution data
   (S3 + PostgreSQL) and publishes to ``executions.stored``.

2. ``storage-verified`` on ``executions.verified`` — stores check_results
   and updates execution confidence/action from verification results.

Messages are ACK'd on success; failures are logged but do not crash
the consumer loop, ensuring resilience against malformed messages.
"""

import asyncio
import json
import logging
import os

import redis.asyncio as aioredis

from app.db import SessionLocal
from app.s3_client import get_s3_client
from app.worker import STORED_STREAM_KEY, VERIFIED_STREAM_KEY, process_event, process_verified_event
from shared.models import IngestEvent

logger = logging.getLogger("agentguard.storage-worker")

RAW_STREAM_KEY = "executions.raw"
RAW_CONSUMER_GROUP = "storage-workers"
VERIFIED_CONSUMER_GROUP = "storage-verified"
CONSUMER_NAME = os.environ.get("CONSUMER_NAME", "storage-worker-1")
FALLBACK_ORG = "default"


async def _ensure_consumer_group(
    redis_client: aioredis.Redis,
    stream_key: str,
    group_name: str,
) -> None:
    """Create a consumer group, ignoring if it already exists."""
    try:
        await redis_client.xgroup_create(
            stream_key, group_name, id="0", mkstream=True,
        )
        logger.info("Created consumer group '%s' on stream '%s'", group_name, stream_key)
    except Exception:
        logger.debug(
            "Consumer group '%s' already exists on stream '%s'",
            group_name,
            stream_key,
        )


async def _consume_raw(redis_client: aioredis.Redis, s3_client: object) -> None:
    """Consumer loop for raw execution events (S3 + DB storage)."""
    while True:
        try:
            messages = await redis_client.xreadgroup(
                groupname=RAW_CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams={RAW_STREAM_KEY: ">"},
                count=10,
                block=5000,
            )
            if not messages:
                continue

            for stream, entries in messages:
                for msg_id, data in entries:
                    try:
                        event = IngestEvent.model_validate_json(data["data"])
                        org_id = event.metadata.get("org_id", FALLBACK_ORG) if event.metadata else FALLBACK_ORG
                        db_session = SessionLocal()
                        try:
                            stored_notification = process_event(
                                event,
                                s3_client,
                                db_session,
                                org_id=org_id,
                            )
                        finally:
                            db_session.close()

                        await redis_client.xack(RAW_STREAM_KEY, RAW_CONSUMER_GROUP, msg_id)

                        # Publish to executions.stored for real-time consumers
                        await redis_client.xadd(
                            STORED_STREAM_KEY,
                            {"data": json.dumps(stored_notification)},
                        )
                    except Exception as exc:
                        logger.error(
                            "Failed to process raw message %s: %s",
                            msg_id,
                            exc,
                            exc_info=True,
                        )
        except Exception as exc:
            logger.error("Raw stream read error: %s", exc, exc_info=True)
            await asyncio.sleep(1)


async def _consume_verified(redis_client: aioredis.Redis) -> None:
    """Consumer loop for verified events (check_results + execution update)."""
    while True:
        try:
            messages = await redis_client.xreadgroup(
                groupname=VERIFIED_CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams={VERIFIED_STREAM_KEY: ">"},
                count=10,
                block=5000,
            )
            if not messages:
                continue

            for stream, entries in messages:
                for msg_id, data in entries:
                    try:
                        event_data = json.loads(data["data"])
                        db_session = SessionLocal()
                        try:
                            updated = process_verified_event(event_data, db_session)
                        finally:
                            db_session.close()

                        await redis_client.xack(
                            VERIFIED_STREAM_KEY, VERIFIED_CONSUMER_GROUP, msg_id,
                        )

                        # Publish updated notification for real-time consumers
                        await redis_client.xadd(
                            STORED_STREAM_KEY,
                            {"data": json.dumps(updated)},
                        )
                    except Exception as exc:
                        logger.error(
                            "Failed to process verified message %s: %s",
                            msg_id,
                            exc,
                            exc_info=True,
                        )
        except Exception as exc:
            logger.error("Verified stream read error: %s", exc, exc_info=True)
            await asyncio.sleep(1)


async def run() -> None:
    """Start both consumer loops concurrently."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    redis_client = aioredis.from_url(redis_url, decode_responses=True)

    await _ensure_consumer_group(redis_client, RAW_STREAM_KEY, RAW_CONSUMER_GROUP)
    await _ensure_consumer_group(redis_client, VERIFIED_STREAM_KEY, VERIFIED_CONSUMER_GROUP)

    s3_client = get_s3_client()
    logger.info(
        "Storage worker started. Listening on %s and %s",
        RAW_STREAM_KEY,
        VERIFIED_STREAM_KEY,
    )

    await asyncio.gather(
        _consume_raw(redis_client, s3_client),
        _consume_verified(redis_client),
    )


if __name__ == "__main__":
    asyncio.run(run())
