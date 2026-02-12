"""WebSocket connection manager and Redis Stream consumer for real-time
dashboard updates.

Subscribes to the ``executions.stored`` Redis Stream and broadcasts
new execution events to all connected WebSocket clients.
"""

import asyncio
import json
import logging
from typing import List

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("agentguard.dashboard-api.websocket")


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts messages."""

    def __init__(self) -> None:
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(
            "WebSocket client connected. Active connections: %d",
            len(self.active_connections),
        )

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.remove(websocket)
        logger.info(
            "WebSocket client disconnected. Active connections: %d",
            len(self.active_connections),
        )

    async def broadcast(self, message: dict) -> None:
        """Send a JSON message to all connected clients.

        Disconnected or erroring clients are silently skipped to avoid
        disrupting the broadcast to other clients.
        """
        disconnected: List[WebSocket] = []

        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        # Clean up any connections that failed during broadcast
        for conn in disconnected:
            try:
                self.active_connections.remove(conn)
            except ValueError:
                pass


manager = ConnectionManager()


async def stream_updates(redis_url: str) -> None:
    """Background task that reads from Redis Stream and broadcasts to
    WebSocket clients.

    Connects to the ``executions.stored`` stream using XREAD (not a
    consumer group) so multiple dashboard-api instances can each
    receive all messages. Uses ``$`` as the initial ID to only receive
    new messages from the point of connection.

    Args:
        redis_url: Redis connection URL.
    """
    import redis.asyncio as aioredis

    redis_client = aioredis.from_url(redis_url, decode_responses=True)
    last_id = "$"
    stream_key = "executions.stored"

    logger.info("Starting Redis Stream listener on '%s'", stream_key)

    while True:
        try:
            messages = await redis_client.xread(
                streams={stream_key: last_id},
                count=10,
                block=5000,
            )

            if messages:
                for stream, entries in messages:
                    for msg_id, data in entries:
                        last_id = msg_id

                        try:
                            payload = json.loads(data.get("data", "{}"))
                        except (json.JSONDecodeError, TypeError):
                            logger.warning(
                                "Skipping malformed message %s", msg_id,
                            )
                            continue

                        await manager.broadcast({
                            "type": "execution.new",
                            "data": payload,
                        })
        except asyncio.CancelledError:
            logger.info("Stream listener cancelled, shutting down")
            await redis_client.aclose()
            return
        except Exception as exc:
            logger.error("Stream read error: %s", exc, exc_info=True)
            await asyncio.sleep(1)


async def websocket_endpoint(websocket: WebSocket) -> None:
    """Handle a single WebSocket connection lifecycle.

    Accepts the connection, then keeps it open by receiving messages
    in a loop (client can send pings or control messages). On
    disconnect, the connection is removed from the manager.
    """
    await manager.connect(websocket)

    try:
        while True:
            # Keep the connection alive by waiting for client messages.
            # Clients may send ping/pong or keepalive messages.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
