"""API key validation dependency for the Sync Verification Gateway.

Uses the shared ``KeyValidator`` to authenticate incoming requests
against the ``organizations.api_keys`` JSONB column.  The gateway
requires the ``verify`` scope.
"""

import os
from typing import Optional

from fastapi import HTTPException, Request

from shared.auth import AuthError, KeyInfo, KeyValidator

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://agentguard:agentguard_dev@localhost:5432/agentguard",
)

_validator: Optional[KeyValidator] = None


def get_validator() -> KeyValidator:
    """Return the module-level KeyValidator singleton (lazy init)."""
    global _validator
    if _validator is None:
        _validator = KeyValidator(
            database_url=DATABASE_URL,
            required_scope="verify",
        )
    return _validator


def shutdown_validator() -> None:
    """Flush usage and close DB connections.  Called at app shutdown."""
    global _validator
    if _validator is not None:
        _validator.close()
        _validator = None


def verify_api_key(request: Request) -> KeyInfo:
    """FastAPI dependency that validates the API key and returns org info.

    Extracts the key from the ``X-AgentGuard-Key`` header, validates it
    through the ``KeyValidator``, and returns a ``KeyInfo`` containing
    the resolved ``org_id``, ``key_id``, and ``scopes``.

    Raises:
        HTTPException: 401 if the key is missing, invalid, revoked, or
            expired.  403 if the key lacks the ``verify`` scope.
            429 if the key's rate limit is exceeded.
    """
    api_key = request.headers.get("X-AgentGuard-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-AgentGuard-Key header")

    try:
        return get_validator().validate(api_key)
    except AuthError as e:
        headers = {}
        if e.retry_after_seconds is not None:
            headers["Retry-After"] = str(e.retry_after_seconds)
        raise HTTPException(
            status_code=e.status_code,
            detail=e.detail,
            headers=headers or None,
        )
