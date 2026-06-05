"""All exceptions for the Unfurled library."""

from __future__ import annotations


class UnfurledError(Exception):
    """Base exception for all Unfurled errors."""


class HTTPError(UnfurledError):
    """Raised when an HTTP operation returns a non-2xx status."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"HTTP {status_code}: {message}")


class ConnectionError(UnfurledError):
    """Raised when a network connection fails."""


class AuthenticationError(UnfurledError):
    """Raised when authentication fails."""


class RemoteIsSleeping(ConnectionError):
    """Raised when the remote is asleep and cannot be woken."""

    def __init__(self) -> None:
        super().__init__("Remote is sleeping and could not be woken via Wake-on-LAN")


class NoActivityRunning(UnfurledError):
    """Raised when an operation requires an active activity but none is running."""

    def __init__(self) -> None:
        super().__init__("No activities are currently running")


class InvalidButtonCommand(UnfurledError):
    """Raised when an invalid physical button command is specified."""


class EntityCommandError(UnfurledError):
    """Raised when an entity command execution fails."""


class InvalidIRFormat(UnfurledError):
    """Raised when IR command details are missing or invalid."""


class NoEmitterFound(UnfurledError):
    """Raised when no IR emitter matches the supplied criteria."""


class ApiKeyNotFound(UnfurledError):
    """Raised when an API key with the given name cannot be found."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"API key '{name}' not found")


class ApiKeyError(UnfurledError):
    """Raised when API key creation or revocation fails."""


class DockNotFound(UnfurledError):
    """Raised when a dock cannot be found by the given identifier."""


class IntegrationNotFound(UnfurledError):
    """Raised when an integration instance cannot be found."""


class SystemCommandNotFound(UnfurledError):
    """Raised when an unrecognised system command is requested."""

    def __init__(self, command: str) -> None:
        self.command = command
        super().__init__(f"Invalid system command: '{command}'")


class ExternalSystemError(UnfurledError):
    """Raised when external system token operations fail."""


class TokenRegistrationError(ExternalSystemError):
    """Raised when registering an external system token fails."""


class DiscoveryError(UnfurledError):
    """Raised when Zeroconf discovery fails."""
