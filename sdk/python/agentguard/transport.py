"""HTTP transport layer for sending telemetry to AgentGuard backend services.

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
from typing import Dict, List, Optional

import httpx

from agentguard.models import ExecutionEvent, ThresholdConfig

logger = logging.getLogger(__name__)


class AsyncTransport:
    """Batching async transport that buffers events and flushes to the Ingestion API.

    Parameters
    ----------
    api_url:
        Base URL of the Ingestion API (e.g. ``https://api.agentguard.dev``).
    api_key:
        API key sent via the ``X-AgentGuard-Key`` header.
    flush_interval_s:
        Maximum seconds between automatic flushes (used by the Guard client's
        periodic flush loop; this class itself does not start a timer).
    flush_batch_size:
        Number of buffered events that triggers an immediate flush.
    timeout_s:
        HTTP request timeout in seconds.
    """

    def __init__(
        self,
        api_url: str,
        api_key: str,
        flush_interval_s: float = 1.0,
        flush_batch_size: int = 50,
        timeout_s: float = 2.0,
    ) -> None:
        self.api_url: str = api_url.rstrip("/")
        self.api_key: str = api_key
        self.flush_interval_s: float = flush_interval_s
        self.flush_batch_size: int = flush_batch_size
        self.timeout_s: float = timeout_s

        self._buffer: List[ExecutionEvent] = []
        self._lock: threading.Lock = threading.Lock()
        self._client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # Lazy client initialisation
    # ------------------------------------------------------------------

    def _get_client(self) -> httpx.AsyncClient:
        """Return the shared ``httpx.AsyncClient``, creating it on first use."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout_s,
                headers={"X-AgentGuard-Key": self.api_key},
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
        """
        with self._lock:
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

        On success the buffer is cleared.  On failure the events are put back
        into the buffer so they can be retried on the next flush cycle.
        """
        with self._lock:
            if not self._buffer:
                return
            batch = list(self._buffer)
            self._buffer.clear()

        payload = [event.model_dump(mode="json") for event in batch]
        url = f"{self.api_url}/v1/ingest/batch"

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
        except Exception:
            # Put events back for retry
            logger.warning(
                "Failed to flush %d events; returning to buffer for retry",
                len(batch),
                exc_info=True,
            )
            with self._lock:
                self._buffer = batch + self._buffer

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
      verify → correct → re-verify loops on the gateway side.  This client
      is created lazily on first use.

    Parameters
    ----------
    api_url:
        Base URL of the Sync Verification Gateway
        (e.g. ``https://api.agentguard.dev``).
    api_key:
        API key sent via the ``X-AgentGuard-Key`` header.
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
            timeout=self.timeout_s,
            headers={"X-AgentGuard-Key": self.api_key},
        )
        self._correction_client: Optional[httpx.Client] = None

    # ------------------------------------------------------------------
    # Lazy correction client
    # ------------------------------------------------------------------

    def _get_correction_client(self) -> httpx.Client:
        """Return the correction client with longer timeout, creating on first use."""
        if self._correction_client is None or self._correction_client.is_closed:
            self._correction_client = httpx.Client(
                timeout=self.correction_timeout_s,
                headers={"X-AgentGuard-Key": self.api_key},
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

        response = client.post(url, json=payload)
        response.raise_for_status()
        result: Dict[str, object] = response.json()
        return result

    def close(self) -> None:
        """Close the underlying HTTP clients."""
        if not self._client.is_closed:
            self._client.close()
        if self._correction_client is not None and not self._correction_client.is_closed:
            self._correction_client.close()
