import sys
import os

# Add the storage-worker service root to the path so that
# `from app.worker import ...` resolves correctly when tests
# are invoked from the project root.
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), ".."),
)

# Ensure the shared package is importable when running tests without
# installing it into the virtual-env (fallback for local dev).
# Add `services/` to path so that `import shared.models` resolves to
# `services/shared/models.py`.
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", ".."),
)
