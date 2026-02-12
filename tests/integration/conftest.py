"""Integration test configuration.

Adds necessary service paths to sys.path for cross-service imports.

For the sync path tests, the sync-gateway ``app`` module is the primary
entry point.  For the async path tests, worker modules from different
services are loaded via ``importlib`` to avoid ``app`` namespace
collisions (every service uses ``app`` as its package name).
"""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SERVICES_DIR = Path(__file__).parent.parent.parent / "services"

# Shared libs used by all services — must happen before service imports
for path in [
    SERVICES_DIR / "shared",
    SERVICES_DIR / "verification-engine",
]:
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from shared.auth import KeyInfo


# ---------- helpers for loading worker modules by file path ---------- #


def _load_module_from_file(name: str, file_path: Path):
    """Load a Python module from *file_path* and register it as *name*."""
    spec = importlib.util.spec_from_file_location(name, str(file_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module {name!r} from {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_async_worker():
    """Import async-worker's ``worker.py`` as ``async_worker_mod``."""
    if "async_worker_mod" in sys.modules:
        return sys.modules["async_worker_mod"]
    return _load_module_from_file(
        "async_worker_mod",
        SERVICES_DIR / "async-worker" / "app" / "worker.py",
    )


def load_storage_worker():
    """Import storage-worker's ``worker.py`` as ``storage_worker_mod``."""
    if "storage_worker_mod" in sys.modules:
        return sys.modules["storage_worker_mod"]
    return _load_module_from_file(
        "storage_worker_mod",
        SERVICES_DIR / "storage-worker" / "app" / "worker.py",
    )


def load_alert_webhook():
    """Import alert-service's ``webhook.py`` as ``alert_webhook_mod``."""
    if "alert_webhook_mod" in sys.modules:
        return sys.modules["alert_webhook_mod"]
    return _load_module_from_file(
        "alert_webhook_mod",
        SERVICES_DIR / "alert-service" / "app" / "webhook.py",
    )


def load_alert_worker():
    """Import alert-service's ``worker.py`` as ``alert_worker_mod``.

    The alert worker imports ``from app.webhook import deliver`` at
    module level.  We pre-load the webhook module and inject a shim
    ``app`` package so the import resolves correctly.
    """
    if "alert_worker_mod" in sys.modules:
        return sys.modules["alert_worker_mod"]

    # Make sure the webhook module is loaded first
    webhook_mod = load_alert_webhook()

    # Create a shim ``app`` package with a ``webhook`` attribute
    import types

    shim_app = types.ModuleType("app")
    shim_app.webhook = webhook_mod  # type: ignore[attr-defined]
    prev_app = sys.modules.get("app")
    sys.modules["app"] = shim_app
    sys.modules["app.webhook"] = webhook_mod

    try:
        mod = _load_module_from_file(
            "alert_worker_mod",
            SERVICES_DIR / "alert-service" / "app" / "worker.py",
        )
    finally:
        # Restore previous ``app`` (or remove shim)
        if prev_app is not None:
            sys.modules["app"] = prev_app
        else:
            sys.modules.pop("app", None)
        sys.modules.pop("app.webhook", None)

    return mod


# ---------- pytest fixtures wrapping the loaders ---------- #


@pytest.fixture(scope="session")
def async_worker_module():
    """Provide the async-worker's worker module."""
    return load_async_worker()


@pytest.fixture(scope="session")
def storage_worker_module():
    """Provide the storage-worker's worker module."""
    return load_storage_worker()


@pytest.fixture(scope="session")
def alert_worker_module():
    """Provide the alert-service's worker module."""
    return load_alert_worker()


# ---------- Shared auth bypass for gateway tests ---------- #


def _make_passthrough_validator():
    """Return a mock ``KeyValidator`` that accepts any key.

    Used by gateway integration tests that are not specifically testing
    the auth flow.  The API key lifecycle test overrides this with its
    own per-test patches.
    """
    validator = MagicMock()
    validator.close = MagicMock()
    validator.flush_usage = MagicMock()
    validator.validate = MagicMock(
        return_value=KeyInfo(org_id="test-org", key_id="test-key-id", scopes=["ingest", "verify", "read"]),
    )
    return validator


@pytest.fixture(autouse=True)
def _bypass_gateway_auth(request, monkeypatch):
    """Auto-mock the gateway's ``get_validator`` so tests that send
    ``X-AgentGuard-Key`` headers don't require a live database.

    Tests in ``test_api_key_lifecycle.py`` override this by patching
    ``app.auth.get_validator`` explicitly in each test body.
    """
    # Only apply if the sync-gateway app module is loaded
    gw_path = str(SERVICES_DIR / "sync-gateway")
    if gw_path not in sys.path:
        return

    try:
        import app.auth as gw_auth  # noqa: WPS433
        monkeypatch.setattr(gw_auth, "get_validator", _make_passthrough_validator)
    except (ImportError, ModuleNotFoundError):
        pass
