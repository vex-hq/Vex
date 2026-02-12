"""Tests for webhook delivery with retry logic."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.webhook import deliver


@pytest.mark.asyncio
async def test_successful_delivery():
    mock_response = httpx.Response(200)

    with patch("app.webhook.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.post = AsyncMock(return_value=mock_response)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        success, status = await deliver(
            "https://hooks.example.com/alert",
            {"event": "test"},
        )

    assert success is True
    assert status == 200
    instance.post.assert_called_once()


@pytest.mark.asyncio
async def test_retry_on_server_error():
    responses = [
        httpx.Response(500),
        httpx.Response(500),
        httpx.Response(200),
    ]
    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        resp = responses[call_count]
        call_count += 1
        return resp

    with patch("app.webhook.httpx.AsyncClient") as MockClient, \
         patch("app.webhook.RETRY_DELAYS", [0.01, 0.01, 0.01]):
        instance = AsyncMock()
        instance.post = mock_post
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        success, status = await deliver(
            "https://hooks.example.com/alert",
            {"event": "test"},
        )

    assert success is True
    assert status == 200
    assert call_count == 3


@pytest.mark.asyncio
async def test_max_retries_exhausted():
    mock_response = httpx.Response(500)

    with patch("app.webhook.httpx.AsyncClient") as MockClient, \
         patch("app.webhook.RETRY_DELAYS", [0.01, 0.01, 0.01]):
        instance = AsyncMock()
        instance.post = AsyncMock(return_value=mock_response)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        success, status = await deliver(
            "https://hooks.example.com/alert",
            {"event": "test"},
        )

    assert success is False
    assert status == 500
    assert instance.post.call_count == 3


@pytest.mark.asyncio
async def test_connection_error_retries():
    with patch("app.webhook.httpx.AsyncClient") as MockClient, \
         patch("app.webhook.RETRY_DELAYS", [0.01, 0.01, 0.01]):
        instance = AsyncMock()
        instance.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        success, status = await deliver(
            "https://hooks.example.com/alert",
            {"event": "test"},
        )

    assert success is False
    assert status == 0
    assert instance.post.call_count == 3
