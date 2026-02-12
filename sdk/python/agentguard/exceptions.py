class AgentGuardError(Exception):
    """Base exception for AgentGuard SDK."""


class ConfigurationError(AgentGuardError):
    """Invalid SDK configuration."""


class IngestionError(AgentGuardError):
    """Failed to send telemetry to AgentGuard backend."""


class VerificationError(AgentGuardError):
    """Verification request failed."""


class AgentGuardBlockError(AgentGuardError):
    """Raised when verification blocks the agent output.

    Attributes:
        result: The GuardResult that triggered the block.
    """

    def __init__(self, result: "GuardResult") -> None:  # noqa: F821
        self.result = result
        super().__init__(
            f"Output blocked (confidence={result.confidence})"
        )
