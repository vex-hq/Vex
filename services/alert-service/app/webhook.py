"""Webhook delivery with retry logic.

Delivers alert payloads to configured webhook URLs with exponential
backoff retry (up to 3 attempts).
"""

import asyncio
import logging
from typing import Any, Dict, Tuple

import httpx

logger = logging.getLogger("agentguard.alert-service.webhook")

MAX_RETRIES = 3
RETRY_DELAYS = [1.0, 2.0, 4.0]  # seconds
WEBHOOK_TIMEOUT_S = 5.0


async def deliver(
    url: str,
    payload: Dict[str, Any],
) -> Tuple[bool, int]:
    """Deliver a webhook payload with retry.

    Args:
        url: The webhook URL to POST to.
        payload: The JSON payload to send.

    Returns:
        Tuple of (success: bool, status_code: int).
        status_code is 0 if all attempts failed with connection errors.
    """
    last_status = 0

    async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT_S) as client:
        for attempt in range(MAX_RETRIES):
            try:
                response = await client.post(url, json=payload)
                last_status = response.status_code

                if 200 <= response.status_code < 300:
                    logger.info(
                        "Webhook delivered to %s (status %d, attempt %d)",
                        url,
                        response.status_code,
                        attempt + 1,
                    )
                    return True, response.status_code

                logger.warning(
                    "Webhook to %s returned %d (attempt %d/%d)",
                    url,
                    response.status_code,
                    attempt + 1,
                    MAX_RETRIES,
                )
            except Exception:
                logger.warning(
                    "Webhook to %s failed (attempt %d/%d)",
                    url,
                    attempt + 1,
                    MAX_RETRIES,
                    exc_info=True,
                )

            # Wait before retrying (except after last attempt)
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAYS[attempt])

    logger.error("Webhook delivery to %s failed after %d attempts", url, MAX_RETRIES)
    return False, last_status
