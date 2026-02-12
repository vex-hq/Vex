"""Tests for the AgentGuard Dashboard API WebSocket service."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.websocket import ConnectionManager, manager


@pytest.fixture
def app():
    """Create a test app with the stream listener disabled."""
    with patch("app.main.stream_updates", new_callable=AsyncMock):
        test_app = create_app()
        yield test_app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_health_check(client):
    """GET /health returns healthy status."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_websocket_connect_and_receive(client):
    """WebSocket connects, receives a broadcasted message, then disconnects."""
    with client.websocket_connect("/ws") as ws:
        # Broadcast a message from the manager
        async def do_broadcast():
            await manager.broadcast({
                "type": "execution.new",
                "data": {"execution_id": "test-123"},
            })

        asyncio.get_event_loop().run_until_complete(do_broadcast())

        data = ws.receive_json()
        assert data["type"] == "execution.new"
        assert data["data"]["execution_id"] == "test-123"


def test_websocket_multiple_clients(client):
    """Multiple WebSocket clients each receive broadcasted messages."""
    with client.websocket_connect("/ws") as ws1:
        with client.websocket_connect("/ws") as ws2:
            async def do_broadcast():
                await manager.broadcast({
                    "type": "execution.new",
                    "data": {"execution_id": "multi-456"},
                })

            asyncio.get_event_loop().run_until_complete(do_broadcast())

            data1 = ws1.receive_json()
            data2 = ws2.receive_json()

            assert data1["data"]["execution_id"] == "multi-456"
            assert data2["data"]["execution_id"] == "multi-456"


class TestConnectionManager:
    """Unit tests for the ConnectionManager class."""

    def test_initial_state(self):
        mgr = ConnectionManager()
        assert len(mgr.active_connections) == 0

    @pytest.mark.asyncio
    async def test_connect_adds_to_active(self):
        mgr = ConnectionManager()
        mock_ws = AsyncMock()
        await mgr.connect(mock_ws)
        assert mock_ws in mgr.active_connections
        mock_ws.accept.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_removes_from_active(self):
        mgr = ConnectionManager()
        mock_ws = AsyncMock()
        await mgr.connect(mock_ws)
        mgr.disconnect(mock_ws)
        assert mock_ws not in mgr.active_connections

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all(self):
        mgr = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await mgr.connect(ws1)
        await mgr.connect(ws2)

        message = {"type": "test", "data": "hello"}
        await mgr.broadcast(message)

        ws1.send_json.assert_called_once_with(message)
        ws2.send_json.assert_called_once_with(message)

    @pytest.mark.asyncio
    async def test_broadcast_cleans_up_failed_connections(self):
        mgr = ConnectionManager()
        good_ws = AsyncMock()
        bad_ws = AsyncMock()
        bad_ws.send_json.side_effect = Exception("connection lost")

        await mgr.connect(good_ws)
        await mgr.connect(bad_ws)
        assert len(mgr.active_connections) == 2

        await mgr.broadcast({"type": "test"})

        # bad_ws should be removed after failed broadcast
        assert bad_ws not in mgr.active_connections
        assert good_ws in mgr.active_connections

    @pytest.mark.asyncio
    async def test_broadcast_to_empty_connections(self):
        mgr = ConnectionManager()
        # Should not raise
        await mgr.broadcast({"type": "test"})
