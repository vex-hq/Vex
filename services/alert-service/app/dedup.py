"""Alert deduplication with window-based suppression.

Prevents alert fatigue by allowing at most one delivered alert per
(agent_id, alert_type) combination within a configurable time window.

Suppressed alerts are counted so the next delivered alert can report
how many similar events occurred during the suppression window.

This implementation uses in-memory tracking. For multi-instance
deployments, swap to a Redis-backed implementation.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Tuple

logger = logging.getLogger("agentguard.alert-service.dedup")

DEFAULT_WINDOW_SECONDS = 300  # 5 minutes


@dataclass
class _WindowState:
    """Tracks the state of a single dedup window."""

    last_delivered_at: float = 0.0
    suppressed_count: int = 0


class AlertDeduplicator:
    """Window-based alert deduplication.

    For each unique (agent_id, alert_type) key, only the first alert
    within the window is delivered. Subsequent alerts are suppressed
    and counted. When the window expires, the next alert is delivered
    with the accumulated suppressed count.

    Args:
        window_seconds: Duration of the suppression window in seconds.
    """

    def __init__(self, window_seconds: float = DEFAULT_WINDOW_SECONDS) -> None:
        self._window_seconds = window_seconds
        self._windows: Dict[str, _WindowState] = {}

    def should_deliver(
        self,
        agent_id: str,
        alert_type: str,
    ) -> Tuple[bool, int]:
        """Check whether an alert should be delivered or suppressed.

        Args:
            agent_id: The agent that triggered the alert.
            alert_type: The alert type (e.g. "verification_flag").

        Returns:
            Tuple of (should_deliver, suppressed_count).
            If should_deliver is True, suppressed_count is the number
            of similar alerts suppressed since the last delivery.
        """
        key = f"{agent_id}:{alert_type}"
        now = time.monotonic()

        state = self._windows.get(key)

        if state is None:
            # First alert for this key — deliver immediately
            self._windows[key] = _WindowState(last_delivered_at=now, suppressed_count=0)
            return True, 0

        elapsed = now - state.last_delivered_at

        if elapsed >= self._window_seconds:
            # Window expired — deliver and report suppressed count
            suppressed = state.suppressed_count
            state.last_delivered_at = now
            state.suppressed_count = 0
            return True, suppressed

        # Within window — suppress
        state.suppressed_count += 1
        logger.debug(
            "Suppressed alert for %s (count=%d, window=%.0fs remaining)",
            key,
            state.suppressed_count,
            self._window_seconds - elapsed,
        )
        return False, 0

    def reset(self) -> None:
        """Clear all dedup state. Useful for testing."""
        self._windows.clear()
