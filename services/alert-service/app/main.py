"""Redis Stream consumer loop for the alert service.

Connects to Redis, joins the ``alert-workers`` consumer group on the
``executions.verified`` stream, and processes flag/block events by
delivering webhooks and recording alerts.
"""

import asyncio
import json
import logging
import os

import redis.asyncio as aioredis

from app.db import SessionLocal
from app.worker import process_verified_event

logger = logging.getLogger("agentguard.alert-service")

STREAM_KEY = "executions.verified"
CONSUMER_GROUP = "alert-workers"
CONSUMER_NAME = os.environ.get("CONSUMER_NAME", "alert-worker-1")


async def run() -> None:
    """Main consumer loop.

    1. Connects to Redis and ensures the consumer group exists.
    2. Reads batches of up to 10 messages from the stream.
    3. For each message, processes verified events (skip pass, alert on flag/block).
    4. ACKs messages on success.
    5. On per-message failure, logs the error and continues.
    6. On stream-level failure, backs off for 1 second and retries.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    redis_client = aioredis.from_url(redis_url, decode_responses=True)

    # Create consumer group; ignore error if it already exists.
    try:
        await redis_client.xgroup_create(
            STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True,
        )
        logger.info("Created consumer group '%s' on stream '%s'", CONSUMER_GROUP, STREAM_KEY)
    except Exception:
        logger.debug(
            "Consumer group '%s' already exists on stream '%s'",
            CONSUMER_GROUP,
            STREAM_KEY,
        )

    logger.info("Alert service started. Listening on %s", STREAM_KEY)

    while True:
        try:
            messages = await redis_client.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams={STREAM_KEY: ">"},
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
                            await process_verified_event(event_data, db_session)
                        finally:
                            db_session.close()

                        await redis_client.xack(STREAM_KEY, CONSUMER_GROUP, msg_id)
                    except Exception as exc:
                        logger.error(
                            "Failed to process message %s: %s",
                            msg_id,
                            exc,
                            exc_info=True,
                        )
        except Exception as exc:
            logger.error("Stream read error: %s", exc, exc_info=True)
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(run())
