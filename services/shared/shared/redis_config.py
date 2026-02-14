"""Shared Redis client configuration for resilient connections."""

REDIS_CLIENT_OPTIONS = {
    "decode_responses": True,
    "socket_timeout": 5.0,
    "socket_connect_timeout": 5.0,
    "socket_keepalive": True,
    "retry_on_timeout": True,
    "health_check_interval": 30,
}
