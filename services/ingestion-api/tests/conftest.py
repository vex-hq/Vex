import sys
import os

# Ensure the shared package is importable when running tests without
# installing it into the virtual-env (fallback for local dev).
# Add `services/` to path so that `import shared.models` resolves to
# `services/shared/models.py`.
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", ".."),
)

import pytest
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def mock_redis():
    mock = AsyncMock()
    mock.xadd = AsyncMock(return_value="1234567890-0")
    return mock


@pytest.fixture
def client(mock_redis):
    app = create_app()
    app.state.redis = mock_redis
    return TestClient(app)
