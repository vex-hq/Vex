class VexError(Exception):
    """Base exception for Vex SDK."""


class ConfigurationError(VexError):
    """Invalid SDK configuration."""


class IngestionError(VexError):
    """Failed to send telemetry to Vex backend."""


class VerificationError(VexError):
    """Verification request failed."""


class VexBlockError(VexError):
    """Raised when verification blocks the agent output.

    Attributes:
        result: The VexResult that triggered the block.
    """

    def __init__(self, result: "VexResult") -> None:  # noqa: F821
        self.result = result
        super().__init__(
            f"Output blocked (confidence={result.confidence})"
        )
