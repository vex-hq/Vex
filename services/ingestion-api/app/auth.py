"""API key validation dependency for FastAPI routes."""

from fastapi import HTTPException, Request


async def verify_api_key(request: Request) -> str:
    """Extract and validate the API key from request headers.

    Currently accepts any non-empty key value. Phase 2 will validate
    keys against the database.

    Args:
        request: The incoming FastAPI request.

    Returns:
        The API key string.

    Raises:
        HTTPException: 401 if the header is missing or empty.
    """
    api_key = request.headers.get("X-AgentGuard-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-AgentGuard-Key header")
    # TODO: validate against DB in Phase 2. For now, accept any non-empty key.
    return api_key
