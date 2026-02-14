"""HTTP transport layer for sending telemetry to Vex backend services.

Provides two transport implementations:

- ``AsyncTransport`` -- buffers events locally and flushes them in batches to
  the Ingestion API (``/v1/ingest/batch``).  Designed for fire-and-forget
  telemetry in async agent pipelines.

- ``SyncTransport`` -- sends a single event to the Sync Verification Gateway
  (``/v1/verify``) and returns the parsed response.  Designed for inline
  verification where the caller needs an immediate result.
"""

import asyncio
import logging
import threading
import time
from typing import Dict, List, Optional

import httpx

from vex.models import ExecutionEvent, ThresholdConfig

logger = logging.getLogger(__name__)


class AsyncTransport:
    """Batching async transport that buffers events and flushes to the Ingestion API.

    Parameters
    ----------
    api_url:
        Base URL of the Ingestion API (e.g. ``https://api.tryvex.dev``).
    api_key:
        API key sent via the ``X-Vex-Key`` header.
    flush_interval_s:
        Maximum seconds between automatic flushes (used by the Vex client's
        periodic flush loop; this class itself does not start a timer).
    flush_batch_size:
        Number of buffered events that triggers an immediate flush.
    timeout_s:
        HTTP request timeout in seconds.
    max_buffer_size:
        Maximum number of events that can be buffered. When full, new events
        are dropped with a warning. Prevents OOM when the API is unavailable.
    """

    def __init__(
        self,
        api_url: str,
        api_key: str,
        flush_interval_s: float = 1.0,
        flush_batch_size: int = 50,
        timeout_s: float = 2.0,
        max_buffer_size: int = 10000,
    ) -> None:
        self.api_url: str = api_url.rstrip("/")
        self.api_key: str = api_key
        self.flush_interval_s: float = flush_interval_s
        self.flush_batch_size: int = flush_batch_size
        self.timeout_s: float = timeout_s
        self.max_buffer_size: int = max_buffer_size

        self._buffer: List[ExecutionEvent] = []
        self._lock: threading.Lock = threading.Lock()
        self._client: Optional[httpx.AsyncClient] = None
        self._dropped_count: int = 0

    # ------------------------------------------------------------------
    # Lazy client initialisation
    # ------------------------------------------------------------------

    def _get_client(self) -> httpx.AsyncClient:
        """Return the shared ``httpx.AsyncClient``, creating it on first use."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5.0, read=self.timeout_s, write=10.0, pool=5.0),
                headers={"X-Vex-Key": self.api_key},
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            )
        return self._client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, event: ExecutionEvent) -> None:
        """Add an event to the internal buffer.

        If the buffer size reaches ``flush_batch_size``, an async flush is
        scheduled on the running event loop (best-effort; failures are logged
        and the events remain in the buffer for the next flush cycle).

        If the buffer is full (``max_buffer_size``), the event is dropped
        and a warning is logged every 100 dropped events to avoid log spam.
        """
        with self._lock:
            if len(self._buffer) >= self.max_buffer_size:
                self._dropped_count += 1
                if self._dropped_count % 100 == 1:
                    logger.warning(
                        "Buffer full (%d events), dropping event (total dropped: %d)",
                        self.max_buffer_size,
                        self._dropped_count,
                    )
                return
            self._buffer.append(event)
            should_flush = len(self._buffer) >= self.flush_batch_size

        if should_flush:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.flush())
            except RuntimeError:
                # No running event loop -- caller will need to flush manually
                # or the periodic flush timer will pick it up.
                logger.debug(
                    "No running event loop; skipping auto-flush "
                    "(buffer size: %d)",
                    len(self._buffer),
                )

    async def flush(self) -> None:
        """Send all buffered events as a batch POST to the Ingestion API.

        Retries up to 3 times with exponential backoff (0.1s, 0.2s, 0.4s) for
        server errors (5xx) and network errors. Client errors (4xx) are not
        retried as they indicate permanent failures.

        On success the buffer is cleared. After all retries are exhausted,
        events are put back into the buffer so they can be retried on the next
        flush cycle.

        When retrying, respects ``max_buffer_size``: if the buffer is already
        partially full, only the events that fit are returned, and the rest
        are dropped with a warning.
        """
        with self._lock:
            if not self._buffer:
                return
            batch = list(self._buffer)
            self._buffer.clear()

        payload = [event.model_dump(mode="json") for event in batch]
        url = f"{self.api_url}/v1/ingest/batch"

        max_retries = 3
        base_delay = 0.1

        for attempt in range(max_retries):
            try:
                client = self._get_client()
                response = await client.post(url, json={"events": payload})
                response.raise_for_status()
                logger.debug(
                    "Flushed %d events to %s (status %d)",
                    len(batch),
                    url,
                    response.status_code,
                )
                return  # Success - exit without putting events back
            except httpx.HTTPStatusError as e:
                # Client errors (4xx) are permanent - don't retry, don't re-buffer
                if e.response.status_code < 500:
                    logger.warning(
                        "Client error %d on flush; dropping %d events (not retrying)",
                        e.response.status_code,
                        len(batch),
                    )
                    return  # Don't put events back in buffer
                # Server errors (5xx) are transient - retry with backoff
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "Server error %d on flush (attempt %d/%d); retrying in %.2fs",
                        e.response.status_code,
                        attempt + 1,
                        max_retries,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.warning(
                        "Server error %d on flush after %d attempts; returning to buffer",
                        e.response.status_code,
                        max_retries,
                        exc_info=True,
                    )
            except Exception as e:
                # Network errors and other exceptions - retry with backoff
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "Network error on flush (attempt %d/%d); retrying in %.2fs: %s",
                        attempt + 1,
                        max_retries,
                        delay,
                        type(e).__name__,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.warning(
                        "Failed to flush %d events after %d attempts; returning to buffer",
                        len(batch),
                        max_retries,
                        exc_info=True,
                    )

        # All retries exhausted - put events back in buffer
        with self._lock:
            available_space = max(0, self.max_buffer_size - len(self._buffer))
            events_to_retry = batch[:available_space]
            dropped = len(batch) - len(events_to_retry)
            if dropped > 0:
                self._dropped_count += dropped
                logger.warning("Dropped %d events due to buffer overflow on retry", dropped)
            self._buffer = events_to_retry + self._buffer

    async def close(self) -> None:
        """Flush remaining events and close the underlying HTTP client."""
        await self.flush()
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()


class SyncTransport:
    """Synchronous transport that sends a single event to the Verification Gateway.

    Maintains two HTTP clients with different timeouts:

    - A *default* client (``timeout_s``, default 30 s) used for normal
      verification requests.  This must be long enough for the server to
      run LLM-based verification checks.
    - A *correction* client (``correction_timeout_s``, default 90 s) used when
      the caller requests server-side correction (``correction != "none"``).
      The longer timeout accounts for the correction cascade which involves
      verify -> correct -> re-verify loops on the gateway side.  This client
      is created lazily on first use.

    Parameters
    ----------
    api_url:
        Base URL of the Sync Verification Gateway
        (e.g. ``https://api.tryvex.dev``).
    api_key:
        API key sent via the ``X-Vex-Key`` header.
    timeout_s:
        HTTP request timeout in seconds for normal verification.
    correction_timeout_s:
        HTTP request timeout in seconds for correction-enabled verification.
    """

    def __init__(
        self,
        api_url: str,
        api_key: str,
        timeout_s: float = 30.0,
        correction_timeout_s: float = 90.0,
    ) -> None:
        self.api_url: str = api_url.rstrip("/")
        self.api_key: str = api_key
        self.timeout_s: float = timeout_s
        self.correction_timeout_s: float = correction_timeout_s

        self._client: httpx.Client = httpx.Client(
            timeout=httpx.Timeout(connect=5.0, read=self.timeout_s, write=10.0, pool=5.0),
            headers={"X-Vex-Key": self.api_key},
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
        self._correction_client: Optional[httpx.Client] = None

    # ------------------------------------------------------------------
    # Lazy correction client
    # ------------------------------------------------------------------

    def _get_correction_client(self) -> httpx.Client:
        """Return the correction client with longer timeout, creating on first use."""
        if self._correction_client is None or self._correction_client.is_closed:
            self._correction_client = httpx.Client(
                timeout=httpx.Timeout(connect=5.0, read=self.correction_timeout_s, write=10.0, pool=5.0),
                headers={"X-Vex-Key": self.api_key},
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            )
        return self._correction_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def verify(
        self,
        event: ExecutionEvent,
        thresholds: Optional[ThresholdConfig] = None,
        correction: str = "none",
        transparency: str = "opaque",
    ) -> Dict[str, object]:
        """POST the event to ``/v1/verify`` and return the parsed JSON response.

        Includes threshold configuration in the request metadata so the
        gateway can use the caller's threshold settings.

        When *correction* is not ``"none"``, the request is sent via a
        dedicated HTTP client with a longer timeout
        (``correction_timeout_s``) to accommodate the server-side correction
        loop.  The *correction* and *transparency* values are forwarded in
        the payload metadata.

        Retries up to 3 times with exponential backoff (0.1s, 0.2s, 0.4s) for
        network errors. HTTP errors (4xx/5xx) are raised immediately without
        retry, as the caller must handle them (e.g., block on low confidence).

        Parameters
        ----------
        event:
            The execution event to verify.
        thresholds:
            Optional threshold overrides for pass/flag decisions.
        correction:
            Correction mode (``"none"``, ``"cascade"``, etc.).
        transparency:
            Transparency mode (``"opaque"``, ``"transparent"``).

        Raises ``httpx.HTTPStatusError`` if the server returns a non-2xx
        status code.
        """
        url = f"{self.api_url}/v1/verify"
        payload = event.model_dump(mode="json")

        if thresholds is not None:
            if "metadata" not in payload or payload["metadata"] is None:
                payload["metadata"] = {}
            payload["metadata"]["thresholds"] = {
                "pass_threshold": thresholds.pass_threshold,
                "flag_threshold": thresholds.flag_threshold,
            }

        if correction != "none":
            if "metadata" not in payload or payload["metadata"] is None:
                payload["metadata"] = {}
            payload["metadata"]["correction"] = correction
            payload["metadata"]["transparency"] = transparency

        # Select the appropriate client based on correction mode
        client = self._get_correction_client() if correction != "none" else self._client

        max_retries = 3
        base_delay = 0.1
        last_exception: Optional[Exception] = None

        for attempt in range(max_retries):
            try:
                response = client.post(url, json=payload)
                response.raise_for_status()
                result: Dict[str, object] = response.json()
                return result
            except httpx.HTTPStatusError:
                # HTTP errors (4xx/5xx) should be raised immediately
                # The caller needs to handle these (e.g., block on low confidence)
                raise
            except Exception as e:
                # Network errors - retry with backoff
                last_exception = e
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "Network error on verify (attempt %d/%d); retrying in %.2fs: %s",
                        attempt + 1,
                        max_retries,
                        delay,
                        type(e).__name__,
                    )
                    time.sleep(delay)
                else:
                    logger.warning(
                        "Failed to verify after %d attempts",
                        max_retries,
                        exc_info=True,
                    )

        # All retries exhausted - raise the last exception
        if last_exception is not None:
            raise last_exception
        # This should never happen, but satisfy the type checker
        raise RuntimeError("verify() failed without setting last_exception")

    def close(self) -> None:
        """Close the underlying HTTP clients."""
        if not self._client.is_closed:
            self._client.close()
        if self._correction_client is not None and not self._correction_client.is_closed:
            self._correction_client.close()
