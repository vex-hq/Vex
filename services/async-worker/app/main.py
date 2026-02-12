"""Redis Stream consumer loop for the async verification worker.

Connects to Redis, joins the ``verification-workers`` consumer group on
the ``executions.raw`` stream, runs verification on each event, and
publishes verified results to ``executions.verified``.

This uses a separate consumer group from the storage worker so both
can independently consume from the same stream.
"""

import asyncio
import json
import logging
import os

import redis.asyncio as aioredis

from app.worker import VERIFIED_STREAM_KEY, process_event
from shared.models import IngestEvent

logger = logging.getLogger("agentguard.async-worker")

STREAM_KEY = "executions.raw"
CONSUMER_GROUP = "verification-workers"
CONSUMER_NAME = os.environ.get("CONSUMER_NAME", "async-worker-1")


async def run() -> None:
    """Main consumer loop.

    1. Connects to Redis and ensures the consumer group exists.
    2. Reads batches of up to 10 messages from the stream.
    3. For each message, deserialises the event, runs verification,
       and ACKs the message on success.
    4. Publishes verified results to ``executions.verified``.
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

    logger.info("Async verification worker started. Listening on %s", STREAM_KEY)

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
                        event = IngestEvent.model_validate_json(data["data"])
                        verified_event = await process_event(event)

                        await redis_client.xack(STREAM_KEY, CONSUMER_GROUP, msg_id)

                        # Publish verified result for storage worker and alert service
                        await redis_client.xadd(
                            VERIFIED_STREAM_KEY,
                            {"data": json.dumps(verified_event)},
                        )
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
