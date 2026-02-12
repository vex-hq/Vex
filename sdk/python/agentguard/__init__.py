from importlib.metadata import PackageNotFoundError, version

from agentguard.config import GuardConfig
from agentguard.exceptions import AgentGuardBlockError
from agentguard.guard import AgentGuard, Session
from agentguard.models import ConversationTurn, GuardResult

__all__ = [
    "AgentGuard",
    "AgentGuardBlockError",
    "ConversationTurn",
    "GuardConfig",
    "GuardResult",
    "Session",
]

try:
    __version__ = version("agentx-sdk")
except PackageNotFoundError:
    # Running from source without installing (e.g. editable dev install)
    __version__ = "0.0.0-dev"
