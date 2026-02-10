"""Redis Stream consumer loop for the storage worker.

Connects to Redis, joins the ``storage-workers`` consumer group on the
``executions.raw`` stream, and processes incoming events by delegating
to :func:`app.worker.process_event`.

Messages are ACK'd on success; failures are logged but do not crash
the consumer loop, ensuring resilience against malformed messages.
"""

import asyncio
import logging
import os

import redis.asyncio as aioredis

from app.db import SessionLocal
from app.s3_client import get_s3_client
from app.worker import process_event
from shared.models import IngestEvent

logger = logging.getLogger("agentguard.storage-worker")

STREAM_KEY = "executions.raw"
CONSUMER_GROUP = "storage-workers"
CONSUMER_NAME = os.environ.get("CONSUMER_NAME", "storage-worker-1")
DEFAULT_ORG = "default"


async def run() -> None:
    """Main consumer loop.

    1. Connects to Redis and ensures the consumer group exists.
    2. Reads batches of up to 10 messages from the stream.
    3. For each message, deserialises the event, calls process_event,
       and ACKs the message on success.
    4. On per-message failure, logs the error and continues.
    5. On stream-level failure (e.g. Redis disconnect), backs off for
       1 second and retries.
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

    s3_client = get_s3_client()
    logger.info("Storage worker started. Listening on %s", STREAM_KEY)

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
                        db_session = SessionLocal()
                        try:
                            process_event(
                                event,
                                s3_client,
                                db_session,
                                org_id=DEFAULT_ORG,
                            )
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
