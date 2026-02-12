"""API key validation for AgentGuard backend services.

Provides ``KeyValidator``, a shared authentication module used by the
sync gateway and ingestion API to validate incoming API keys against
the ``organizations.api_keys`` JSONB column in TimescaleDB.

Features:
- SHA-256 hash-based key lookup (keys are never stored in plaintext)
- In-memory cache with configurable TTL (default 60 s)
- Per-key scope enforcement (``ingest``, ``verify``, ``read``)
- Per-key rate limiting (sliding window, requests per minute)
- Batched ``last_used_at`` updates (avoids write pressure on hot path)
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Deque, Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

logger = logging.getLogger("agentguard.auth")

VALID_SCOPES = frozenset({"ingest", "verify", "read"})


@dataclass
class KeyInfo:
    """Validated API key information returned to the caller."""

    org_id: str
    key_id: str
    scopes: List[str]


@dataclass
class _CachedKey:
    """Internal cached representation of a validated key."""

    org_id: str
    key_id: str
    scopes: List[str]
    rate_limit_rpm: int
    expires_at: Optional[datetime]
    revoked: bool
    cached_at: float = field(default_factory=time.monotonic)


class KeyValidator:
    """Validates API keys against the organizations table.

    Each backend service creates a ``KeyValidator`` instance at startup,
    specifying the required scope for that service.  The validator
    maintains an in-memory cache to avoid hitting the database on every
    request.

    Args:
        database_url: PostgreSQL connection string.
        required_scope: The scope that incoming keys must have
            (e.g. ``"ingest"`` or ``"verify"``).
        cache_ttl_s: How long cached key entries remain valid (seconds).
        flush_interval_s: How often ``last_used_at`` is flushed to the DB.
    """

    def __init__(
        self,
        database_url: str,
        required_scope: str,
        cache_ttl_s: float = 60.0,
        flush_interval_s: float = 60.0,
    ) -> None:
        if required_scope not in VALID_SCOPES:
            raise ValueError(
                f"Invalid scope {required_scope!r}; must be one of {VALID_SCOPES}"
            )

        self._engine: Engine = create_engine(
            database_url,
            pool_size=2,
            max_overflow=3,
            pool_pre_ping=True,
        )
        self._required_scope = required_scope
        self._cache_ttl_s = cache_ttl_s
        self._flush_interval_s = flush_interval_s

        # key_hash -> _CachedKey
        self._cache: Dict[str, _CachedKey] = {}
        self._cache_lock = Lock()

        # Rate limit counters: key_id -> deque of request timestamps
        self._rate_counters: Dict[str, Deque[float]] = {}
        self._rate_lock = Lock()

        # Batched last_used_at updates: key_id -> timestamp
        self._usage_buffer: Dict[str, str] = {}
        self._usage_lock = Lock()
        self._last_flush = time.monotonic()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(self, api_key: str) -> KeyInfo:
        """Validate an API key and return org information.

        This method is synchronous.  When used as a FastAPI dependency
        in an async route, FastAPI automatically runs it in a thread
        pool so it does not block the event loop.

        Args:
            api_key: The raw API key from the ``X-AgentGuard-Key`` header.

        Returns:
            A ``KeyInfo`` with the resolved org_id, key_id, and scopes.

        Raises:
            AuthError: On any validation failure (invalid, revoked,
                expired, wrong scope, rate limited).
        """
        key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()

        # 1. Cache lookup
        entry = self._cache_get(key_hash)

        # 2. Cache miss -> DB query
        if entry is None:
            entry = self._query_db(key_hash)
            if entry is None:
                raise AuthError(401, "Invalid API key")
            self._cache_put(key_hash, entry)

        # 3. Check revoked
        if entry.revoked:
            raise AuthError(401, "API key has been revoked")

        # 4. Check expired
        if entry.expires_at is not None:
            now = datetime.now(tz=timezone.utc)
            if now > entry.expires_at:
                raise AuthError(401, "API key has expired")

        # 5. Check scope
        if self._required_scope not in entry.scopes:
            raise AuthError(
                403,
                f"API key missing required scope: {self._required_scope}",
            )

        # 6. Check rate limit
        self._check_rate_limit(entry)

        # 7. Track usage (batched)
        self._track_usage(entry.key_id)

        return KeyInfo(
            org_id=entry.org_id,
            key_id=entry.key_id,
            scopes=entry.scopes,
        )

    def flush_usage(self) -> None:
        """Flush buffered ``last_used_at`` updates to the database.

        Called automatically by ``_track_usage`` when the flush interval
        elapses.  Can also be called explicitly at shutdown.
        """
        with self._usage_lock:
            if not self._usage_buffer:
                return
            buffer = dict(self._usage_buffer)
            self._usage_buffer.clear()
            self._last_flush = time.monotonic()

        try:
            with self._engine.connect() as conn:
                for key_id, used_at in buffer.items():
                    conn.execute(
                        text(
                            """
                            UPDATE organizations
                            SET api_keys = (
                                SELECT jsonb_agg(
                                    CASE
                                        WHEN elem->>'id' = :key_id
                                        THEN jsonb_set(elem, '{last_used_at}', to_jsonb(CAST(:used_at AS text)))
                                        ELSE elem
                                    END
                                )
                                FROM jsonb_array_elements(api_keys) AS elem
                            )
                            WHERE api_keys @> CAST(:filter AS jsonb)
                            """
                        ),
                        {
                            "key_id": key_id,
                            "used_at": used_at,
                            "filter": json.dumps([{"id": key_id}]),
                        },
                    )
                conn.commit()
        except Exception:
            logger.warning("Failed to flush last_used_at updates", exc_info=True)

    def close(self) -> None:
        """Flush pending usage and dispose of the DB engine."""
        self.flush_usage()
        self._engine.dispose()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cache_get(self, key_hash: str) -> Optional[_CachedKey]:
        with self._cache_lock:
            entry = self._cache.get(key_hash)
            if entry is None:
                return None
            if (time.monotonic() - entry.cached_at) > self._cache_ttl_s:
                del self._cache[key_hash]
                return None
            return entry

    def _cache_put(self, key_hash: str, entry: _CachedKey) -> None:
        with self._cache_lock:
            self._cache[key_hash] = entry

    def _query_db(self, key_hash: str) -> Optional[_CachedKey]:
        """Query the organizations table for a matching key hash."""
        try:
            with self._engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                        SELECT org_id, api_keys
                        FROM organizations
                        WHERE api_keys @> CAST(:filter AS jsonb)
                        """
                    ),
                    {"filter": json.dumps([{"key_hash": key_hash}])},
                )
                row = result.fetchone()
        except Exception:
            logger.error("Database error during key lookup", exc_info=True)
            raise AuthError(500, "Internal authentication error")

        if row is None:
            return None

        org_id = row[0]
        api_keys = row[1] if isinstance(row[1], list) else json.loads(row[1])

        # Find the matching key entry in the JSONB array
        for key_entry in api_keys:
            if key_entry.get("key_hash") == key_hash:
                expires_at = None
                if key_entry.get("expires_at"):
                    expires_at = datetime.fromisoformat(
                        key_entry["expires_at"].replace("Z", "+00:00")
                    )

                return _CachedKey(
                    org_id=org_id,
                    key_id=key_entry["id"],
                    scopes=key_entry.get("scopes", []),
                    rate_limit_rpm=key_entry.get("rate_limit_rpm", 1000),
                    expires_at=expires_at,
                    revoked=key_entry.get("revoked", False),
                )

        return None

    def _check_rate_limit(self, entry: _CachedKey) -> None:
        """Enforce per-key sliding window rate limit."""
        now = time.monotonic()
        window = 60.0  # 1 minute

        with self._rate_lock:
            counter = self._rate_counters.get(entry.key_id)
            if counter is None:
                counter = deque()
                self._rate_counters[entry.key_id] = counter

            # Remove timestamps outside the window
            while counter and (now - counter[0]) > window:
                counter.popleft()

            if len(counter) >= entry.rate_limit_rpm:
                oldest = counter[0]
                retry_after = int(window - (now - oldest)) + 1
                raise AuthError(
                    429,
                    "Rate limit exceeded",
                    retry_after_seconds=max(retry_after, 1),
                )

            counter.append(now)

    def _track_usage(self, key_id: str) -> None:
        """Buffer a last_used_at timestamp and flush periodically."""
        now_iso = datetime.now(tz=timezone.utc).isoformat()

        with self._usage_lock:
            self._usage_buffer[key_id] = now_iso

        # Check if it's time to flush
        if (time.monotonic() - self._last_flush) > self._flush_interval_s:
            self.flush_usage()


class AuthError(Exception):
    """Raised when API key validation fails.

    Carries the HTTP status code and detail message so that FastAPI
    route handlers (or a middleware) can convert it to the appropriate
    HTTP response.
    """

    def __init__(
        self,
        status_code: int,
        detail: str,
        retry_after_seconds: Optional[int] = None,
    ) -> None:
        self.status_code = status_code
        self.detail = detail
        self.retry_after_seconds = retry_after_seconds
        super().__init__(detail)
