"""API key validation dependencies for the AgentGuard API Gateway.

Uses the shared ``KeyValidator`` to authenticate incoming requests
against the ``organizations.api_keys`` JSONB column.  Provides separate
dependencies for ``verify`` and ``ingest`` scopes so each route group
can enforce the appropriate permission.
"""

import os
from typing import Dict, Optional

from fastapi import HTTPException, Request

from shared.auth import AuthError, KeyInfo, KeyValidator

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://agentguard:agentguard_dev@localhost:5432/agentguard",
)

_validators: Dict[str, KeyValidator] = {}


def _get_validator(scope: str) -> KeyValidator:
    """Return a KeyValidator for the given scope (lazy init, singleton per scope)."""
    if scope not in _validators:
        _validators[scope] = KeyValidator(
            database_url=DATABASE_URL,
            required_scope=scope,
        )
    return _validators[scope]


def shutdown_validator() -> None:
    """Flush usage and close DB connections.  Called at app shutdown."""
    for validator in _validators.values():
        validator.close()
    _validators.clear()


def _validate_key(request: Request, scope: str) -> KeyInfo:
    """Extract and validate the API key from the request header."""
    api_key = request.headers.get("X-AgentGuard-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-AgentGuard-Key header")

    try:
        return _get_validator(scope).validate(api_key)
    except AuthError as e:
        headers = {}
        if e.retry_after_seconds is not None:
            headers["Retry-After"] = str(e.retry_after_seconds)
        raise HTTPException(
            status_code=e.status_code,
            detail=e.detail,
            headers=headers or None,
        )


def verify_api_key(request: Request) -> KeyInfo:
    """FastAPI dependency requiring the ``verify`` scope."""
    return _validate_key(request, "verify")


def verify_ingest_key(request: Request) -> KeyInfo:
    """FastAPI dependency requiring the ``ingest`` scope."""
    return _validate_key(request, "ingest")
