"""Tests for alert deduplication."""

from unittest.mock import patch

from app.dedup import AlertDeduplicator


class TestAlertDeduplicator:
    def test_first_alert_is_delivered(self):
        dedup = AlertDeduplicator(window_seconds=300)
        allow, suppressed = dedup.should_deliver("bot-1", "verification_flag")
        assert allow is True
        assert suppressed == 0

    def test_second_alert_within_window_is_suppressed(self):
        dedup = AlertDeduplicator(window_seconds=300)
        dedup.should_deliver("bot-1", "verification_flag")

        allow, suppressed = dedup.should_deliver("bot-1", "verification_flag")
        assert allow is False
        assert suppressed == 0

    def test_different_agent_not_suppressed(self):
        dedup = AlertDeduplicator(window_seconds=300)
        dedup.should_deliver("bot-1", "verification_flag")

        allow, suppressed = dedup.should_deliver("bot-2", "verification_flag")
        assert allow is True

    def test_different_alert_type_not_suppressed(self):
        dedup = AlertDeduplicator(window_seconds=300)
        dedup.should_deliver("bot-1", "verification_flag")

        allow, suppressed = dedup.should_deliver("bot-1", "verification_block")
        assert allow is True

    def test_window_expiry_delivers_with_suppressed_count(self):
        dedup = AlertDeduplicator(window_seconds=300)

        # First delivery
        dedup.should_deliver("bot-1", "verification_flag")

        # Suppress 3 alerts
        dedup.should_deliver("bot-1", "verification_flag")
        dedup.should_deliver("bot-1", "verification_flag")
        dedup.should_deliver("bot-1", "verification_flag")

        # Simulate window expiry by advancing monotonic clock
        with patch("app.dedup.time.monotonic", return_value=_get_monotonic() + 301):
            allow, suppressed = dedup.should_deliver("bot-1", "verification_flag")

        assert allow is True
        assert suppressed == 3

    def test_suppressed_count_resets_after_delivery(self):
        dedup = AlertDeduplicator(window_seconds=300)
        dedup.should_deliver("bot-1", "verification_flag")

        # Suppress 2
        dedup.should_deliver("bot-1", "verification_flag")
        dedup.should_deliver("bot-1", "verification_flag")

        # Expire window and deliver
        with patch("app.dedup.time.monotonic", return_value=_get_monotonic() + 301):
            dedup.should_deliver("bot-1", "verification_flag")

        # Suppress 1 more in new window
        with patch("app.dedup.time.monotonic", return_value=_get_monotonic() + 302):
            dedup.should_deliver("bot-1", "verification_flag")

        # Expire again
        with patch("app.dedup.time.monotonic", return_value=_get_monotonic() + 603):
            allow, suppressed = dedup.should_deliver("bot-1", "verification_flag")

        assert allow is True
        assert suppressed == 1

    def test_custom_window(self):
        dedup = AlertDeduplicator(window_seconds=10)
        dedup.should_deliver("bot-1", "verification_flag")

        # Suppress within 10s
        allow, _ = dedup.should_deliver("bot-1", "verification_flag")
        assert allow is False

        # After 10s
        with patch("app.dedup.time.monotonic", return_value=_get_monotonic() + 11):
            allow, _ = dedup.should_deliver("bot-1", "verification_flag")
        assert allow is True

    def test_reset_clears_state(self):
        dedup = AlertDeduplicator(window_seconds=300)
        dedup.should_deliver("bot-1", "verification_flag")

        allow, _ = dedup.should_deliver("bot-1", "verification_flag")
        assert allow is False

        dedup.reset()

        allow, _ = dedup.should_deliver("bot-1", "verification_flag")
        assert allow is True


def _get_monotonic():
    """Get a stable reference time for patching."""
    import time
    return time.monotonic()
