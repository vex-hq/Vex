import sys
import os

# Add the dashboard-api service root to the path so that
# `from app.main import ...` resolves correctly when tests
# are invoked from the project root.
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), ".."),
)
