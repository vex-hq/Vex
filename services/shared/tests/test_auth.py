"""Tests for the shared KeyValidator authentication module."""

import hashlib
import json
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from shared.auth import AuthError, KeyInfo, KeyValidator, _CachedKey


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_key_entry(
    key_id="key-001",
    raw_key="ag_live_testkey1234567890abcdefgh",
    name="Test Key",
    scopes=None,
    rate_limit_rpm=1000,
    expires_at=None,
    revoked=False,
):
    """Build an api_keys JSONB entry for test fixtures."""
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    entry = {
        "id": key_id,
        "prefix": raw_key[:12],
        "key_hash": key_hash,
        "name": name,
        "scopes": scopes or ["ingest", "verify", "read"],
        "rate_limit_rpm": rate_limit_rpm,
        "expires_at": expires_at,
        "created_at": "2026-02-12T00:00:00Z",
        "created_by": "user-001",
        "last_used_at": None,
        "revoked": revoked,
    }
    return entry, raw_key, key_hash


RAW_KEY = "ag_live_testkey1234567890abcdefgh"
KEY_HASH = hashlib.sha256(RAW_KEY.encode("utf-8")).hexdigest()


def _make_db_row(api_keys, org_id="test-org"):
    """Create a mock DB row tuple (org_id, api_keys)."""
    return (org_id, api_keys)


def _build_validator(required_scope="verify", cache_ttl_s=60.0):
    """Build a KeyValidator with a mocked database engine."""
    with patch("shared.auth.create_engine") as mock_create:
        mock_engine = MagicMock()
        mock_create.return_value = mock_engine
        validator = KeyValidator(
            database_url="postgresql://test:test@localhost/test",
            required_scope=required_scope,
            cache_ttl_s=cache_ttl_s,
        )
    return validator, mock_engine


def _mock_db_query(mock_engine, row):
    """Configure the mocked engine to return a specific row."""
    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = row
    mock_conn.execute.return_value = mock_result
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_engine.connect.return_value = mock_conn
    return mock_conn


# ---------------------------------------------------------------------------
# Tests: Valid key
# ---------------------------------------------------------------------------

class TestValidKey:
    def test_valid_key_returns_key_info(self):
        entry, raw_key, _ = _make_key_entry()
        validator, engine = _build_validator(required_scope="verify")
        row = _make_db_row([entry])
        _mock_db_query(engine, row)

        result = validator.validate(raw_key)

        assert isinstance(result, KeyInfo)
        assert result.org_id == "test-org"
        assert result.key_id == "key-001"
        assert "verify" in result.scopes

    def test_valid_key_with_all_scopes(self):
        entry, raw_key, _ = _make_key_entry(
            scopes=["ingest", "verify", "read"]
        )
        validator, engine = _build_validator(required_scope="ingest")
        _mock_db_query(engine, _make_db_row([entry]))

        result = validator.validate(raw_key)
        assert result.scopes == ["ingest", "verify", "read"]


# ---------------------------------------------------------------------------
# Tests: Invalid key
# ---------------------------------------------------------------------------

class TestInvalidKey:
    def test_missing_key_raises_401(self):
        validator, engine = _build_validator()
        _mock_db_query(engine, None)

        with pytest.raises(AuthError) as exc_info:
            validator.validate("ag_live_nonexistent_key_abcdefg")

        assert exc_info.value.status_code == 401
        assert "Invalid API key" in exc_info.value.detail

    def test_empty_api_keys_array(self):
        validator, engine = _build_validator()
        _mock_db_query(engine, None)

        with pytest.raises(AuthError) as exc_info:
            validator.validate("ag_live_bogus_key_0000000000000")

        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Tests: Revoked key
# ---------------------------------------------------------------------------

class TestRevokedKey:
    def test_revoked_key_raises_401(self):
        entry, raw_key, _ = _make_key_entry(revoked=True)
        validator, engine = _build_validator()
        _mock_db_query(engine, _make_db_row([entry]))

        with pytest.raises(AuthError) as exc_info:
            validator.validate(raw_key)

        assert exc_info.value.status_code == 401
        assert "revoked" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Tests: Expired key
# ---------------------------------------------------------------------------

class TestExpiredKey:
    def test_expired_key_raises_401(self):
        yesterday = (datetime.now(tz=timezone.utc) - timedelta(days=1)).isoformat()
        entry, raw_key, _ = _make_key_entry(expires_at=yesterday)
        validator, engine = _build_validator()
        _mock_db_query(engine, _make_db_row([entry]))

        with pytest.raises(AuthError) as exc_info:
            validator.validate(raw_key)

        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail

    def test_non_expired_key_passes(self):
        tomorrow = (datetime.now(tz=timezone.utc) + timedelta(days=1)).isoformat()
        entry, raw_key, _ = _make_key_entry(expires_at=tomorrow)
        validator, engine = _build_validator()
        _mock_db_query(engine, _make_db_row([entry]))

        result = validator.validate(raw_key)
        assert result.org_id == "test-org"

    def test_null_expiry_passes(self):
        entry, raw_key, _ = _make_key_entry(expires_at=None)
        validator, engine = _build_validator()
        _mock_db_query(engine, _make_db_row([entry]))

        result = validator.validate(raw_key)
        assert result.org_id == "test-org"


# ---------------------------------------------------------------------------
# Tests: Scope enforcement
# ---------------------------------------------------------------------------

class TestScopeEnforcement:
    def test_wrong_scope_raises_403(self):
        entry, raw_key, _ = _make_key_entry(scopes=["ingest"])
        validator, engine = _build_validator(required_scope="verify")
        _mock_db_query(engine, _make_db_row([entry]))

        with pytest.raises(AuthError) as exc_info:
            validator.validate(raw_key)

        assert exc_info.value.status_code == 403
        assert "verify" in exc_info.value.detail

    def test_ingest_scope_accepted_by_ingest_service(self):
        entry, raw_key, _ = _make_key_entry(scopes=["ingest"])
        validator, engine = _build_validator(required_scope="ingest")
        _mock_db_query(engine, _make_db_row([entry]))

        result = validator.validate(raw_key)
        assert result.org_id == "test-org"

    def test_read_scope_rejected_by_verify_service(self):
        entry, raw_key, _ = _make_key_entry(scopes=["read"])
        validator, engine = _build_validator(required_scope="verify")
        _mock_db_query(engine, _make_db_row([entry]))

        with pytest.raises(AuthError) as exc_info:
            validator.validate(raw_key)

        assert exc_info.value.status_code == 403

    def test_invalid_required_scope_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid scope"):
            with patch("shared.auth.create_engine"):
                KeyValidator(
                    database_url="postgresql://x:x@localhost/x",
                    required_scope="admin",
                )


# ---------------------------------------------------------------------------
# Tests: Rate limiting
# ---------------------------------------------------------------------------

class TestRateLimiting:
    def test_rate_limit_exceeded_raises_429(self):
        entry, raw_key, _ = _make_key_entry(rate_limit_rpm=3)
        validator, engine = _build_validator()
        _mock_db_query(engine, _make_db_row([entry]))

        # First 3 requests succeed
        for _ in range(3):
            validator.validate(raw_key)

        # 4th request should be rate limited
        with pytest.raises(AuthError) as exc_info:
            validator.validate(raw_key)

        assert exc_info.value.status_code == 429
        assert "Rate limit" in exc_info.value.detail
        assert exc_info.value.retry_after_seconds is not None
        assert exc_info.value.retry_after_seconds > 0

    def test_rate_limit_resets_after_window(self):
        entry, raw_key, _ = _make_key_entry(rate_limit_rpm=2)
        validator, engine = _build_validator()
        _mock_db_query(engine, _make_db_row([entry]))

        # Use up the rate limit
        validator.validate(raw_key)
        validator.validate(raw_key)

        with pytest.raises(AuthError) as exc_info:
            validator.validate(raw_key)
        assert exc_info.value.status_code == 429

        # Simulate window expiry by clearing the deque
        validator._rate_counters[entry["id"]].clear()

        # Should work again
        result = validator.validate(raw_key)
        assert result.org_id == "test-org"


# ---------------------------------------------------------------------------
# Tests: Cache behavior
# ---------------------------------------------------------------------------

class TestCacheBehavior:
    def test_cache_hit_skips_db_query(self):
        entry, raw_key, _ = _make_key_entry()
        validator, engine = _build_validator()
        mock_conn = _mock_db_query(engine, _make_db_row([entry]))

        # First call queries DB
        validator.validate(raw_key)
        call_count_after_first = mock_conn.execute.call_count

        # Second call should use cache (no additional DB query)
        validator.validate(raw_key)
        assert mock_conn.execute.call_count == call_count_after_first

    def test_cache_expiry_re_queries_db(self):
        entry, raw_key, _ = _make_key_entry()
        validator, engine = _build_validator(cache_ttl_s=0.1)
        mock_conn = _mock_db_query(engine, _make_db_row([entry]))

        # First call queries DB
        validator.validate(raw_key)
        call_count_after_first = mock_conn.execute.call_count

        # Wait for cache to expire
        time.sleep(0.15)

        # Second call should query DB again
        validator.validate(raw_key)
        assert mock_conn.execute.call_count > call_count_after_first

    def test_revoked_key_in_cache_rejected(self):
        """If a key is cached then revoked, the cached entry should still reject."""
        entry, raw_key, _ = _make_key_entry(revoked=False)
        validator, engine = _build_validator()
        _mock_db_query(engine, _make_db_row([entry]))

        # First call succeeds
        result = validator.validate(raw_key)
        assert result.org_id == "test-org"

        # Manually mark the cached entry as revoked (simulates cache refresh)
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        validator._cache[key_hash].revoked = True

        with pytest.raises(AuthError) as exc_info:
            validator.validate(raw_key)
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Tests: Batched last_used_at
# ---------------------------------------------------------------------------

class TestLastUsedAt:
    def test_usage_tracked_in_buffer(self):
        entry, raw_key, _ = _make_key_entry()
        validator, engine = _build_validator()
        _mock_db_query(engine, _make_db_row([entry]))

        validator.validate(raw_key)

        assert "key-001" in validator._usage_buffer

    def test_flush_clears_buffer(self):
        entry, raw_key, _ = _make_key_entry()
        validator, engine = _build_validator()
        _mock_db_query(engine, _make_db_row([entry]))

        validator.validate(raw_key)
        assert len(validator._usage_buffer) > 0

        validator.flush_usage()
        assert len(validator._usage_buffer) == 0


# ---------------------------------------------------------------------------
# Tests: Multiple keys per org
# ---------------------------------------------------------------------------

class TestMultipleKeys:
    def test_org_with_multiple_keys(self):
        entry1, raw_key1, _ = _make_key_entry(
            key_id="key-001",
            raw_key="ag_live_firstkey_000000000000000",
            scopes=["ingest"],
        )
        entry2, raw_key2, _ = _make_key_entry(
            key_id="key-002",
            raw_key="ag_live_secondkey_00000000000000",
            scopes=["verify"],
        )

        validator, engine = _build_validator(required_scope="verify")

        # Key 1 (ingest only) should fail on verify service
        _mock_db_query(engine, _make_db_row([entry1, entry2]))
        with pytest.raises(AuthError) as exc_info:
            validator.validate(raw_key1)
        assert exc_info.value.status_code == 403

        # Key 2 (verify) should succeed
        _mock_db_query(engine, _make_db_row([entry1, entry2]))
        result = validator.validate(raw_key2)
        assert result.key_id == "key-002"


# ---------------------------------------------------------------------------
# Tests: DB error handling
# ---------------------------------------------------------------------------

class TestDBErrors:
    def test_db_connection_error_raises_500(self):
        validator, engine = _build_validator()
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("connection refused")
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        engine.connect.return_value = mock_conn

        with pytest.raises(AuthError) as exc_info:
            validator.validate(RAW_KEY)

        assert exc_info.value.status_code == 500
        assert "Internal" in exc_info.value.detail
