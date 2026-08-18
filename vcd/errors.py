class VcdError(RuntimeError):
    """Base exception for user-facing verifier failures."""


class ConfigError(VcdError):
    """Raised when a run or storage configuration is invalid."""


class AgentError(VcdError):
    """Raised when an agent cannot complete a request."""


class StorageError(VcdError):
    """Raised when an artifact store operation fails."""

