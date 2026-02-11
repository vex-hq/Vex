from importlib.metadata import PackageNotFoundError, version

from agentguard.config import GuardConfig
from agentguard.guard import AgentGuard, Session
from agentguard.models import GuardResult

__all__ = ["AgentGuard", "GuardConfig", "GuardResult", "Session"]

try:
    __version__ = version("agentguard")
except PackageNotFoundError:
    # Running from source without installing (e.g. editable dev install)
    __version__ = "0.0.0-dev"
