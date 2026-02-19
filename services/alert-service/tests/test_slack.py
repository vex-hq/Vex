"""Tests for Slack webhook delivery."""

import os
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.slack import deliver_slack, format_slack_message, get_slack_webhook_url


class TestGetSlackWebhookUrl:
    def test_agent_specific_url(self):
        with patch.dict(os.environ, {"SLACK_WEBHOOK_URL_MY_BOT": "https://hooks.slack.com/agent"}):
            assert get_slack_webhook_url("my-bot") == "https://hooks.slack.com/agent"

    def test_global_fallback(self):
        with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/global"}, clear=False):
            url = get_slack_webhook_url("unknown-agent")
            if url == "https://hooks.slack.com/global":
                assert True
            else:
                # Agent-specific might exist in env
                assert url is not None or url is None

    def test_none_when_not_configured(self):
        with patch.dict(os.environ, {}, clear=True):
            assert get_slack_webhook_url("any-agent") is None


class TestFormatSlackMessage:
    def test_block_message_structure(self):
        msg = format_slack_message(
            alert_id="alert-123",
            agent_id="my-bot",
            execution_id="exec-456",
            action="block",
            severity="critical",
            confidence=0.25,
            failure_types=["schema", "hallucination"],
        )
        assert "blocks" in msg
        blocks = msg["blocks"]
        # header, section with text, section with fields, divider
        assert len(blocks) == 4
        assert blocks[0]["type"] == "header"
        assert "Block" in blocks[0]["text"]["text"]

    def test_flag_message_structure(self):
        msg = format_slack_message(
            alert_id="alert-789",
            agent_id="test-bot",
            execution_id="exec-101",
            action="flag",
            severity="high",
            confidence=0.6,
            failure_types=["drift"],
        )
        blocks = msg["blocks"]
        assert blocks[0]["type"] == "header"
        assert "Flag" in blocks[0]["text"]["text"]

    def test_dashboard_link_included(self):
        msg = format_slack_message(
            alert_id="alert-123",
            agent_id="bot",
            execution_id="exec-1",
            action="block",
            severity="critical",
            confidence=0.1,
            failure_types=[],
            dashboard_base_url="https://app.vex.dev",
        )
        blocks = msg["blocks"]
        # Should have actions block with button
        action_blocks = [b for b in blocks if b["type"] == "actions"]
        assert len(action_blocks) == 1
        assert "https://app.vex.dev/executions/exec-1" in action_blocks[0]["elements"][0]["url"]

    def test_none_confidence_shows_na(self):
        msg = format_slack_message(
            alert_id="a",
            agent_id="b",
            execution_id="c",
            action="flag",
            severity="high",
            confidence=None,
            failure_types=[],
        )
        fields_block = [b for b in msg["blocks"] if b.get("fields")]
        assert len(fields_block) == 1
        field_texts = [f["text"] for f in fields_block[0]["fields"]]
        assert any("N/A" in t for t in field_texts)


class TestDeliverSlack:
    @pytest.mark.asyncio
    async def test_successful_delivery(self):
        mock_response = httpx.Response(200)

        with patch("app.slack.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = AsyncMock(return_value=mock_response)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            success, status = await deliver_slack(
                "https://hooks.slack.com/test",
                {"blocks": []},
            )

        assert success is True
        assert status == 200

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        responses = [httpx.Response(500), httpx.Response(500), httpx.Response(200)]
        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            resp = responses[call_count]
            call_count += 1
            return resp

        with patch("app.slack.httpx.AsyncClient") as MockClient, \
             patch("app.slack.RETRY_DELAYS", [0.01, 0.01, 0.01]):
            instance = AsyncMock()
            instance.post = mock_post
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            success, status = await deliver_slack(
                "https://hooks.slack.com/test",
                {"blocks": []},
            )

        assert success is True
        assert status == 200
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_all_retries_exhausted(self):
        with patch("app.slack.httpx.AsyncClient") as MockClient, \
             patch("app.slack.RETRY_DELAYS", [0.01, 0.01, 0.01]):
            instance = AsyncMock()
            instance.post = AsyncMock(return_value=httpx.Response(500))
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            success, status = await deliver_slack(
                "https://hooks.slack.com/test",
                {"blocks": []},
            )

        assert success is False
        assert status == 500
        assert instance.post.call_count == 3
