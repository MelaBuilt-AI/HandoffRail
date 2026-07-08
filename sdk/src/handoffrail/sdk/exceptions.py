"""HandoffRail SDK — Custom exception hierarchy.

All SDK exceptions inherit from HandoffRailError so callers can catch
the base class or any specific subclass.

Exception tree:
    HandoffRailError
    ├── AuthenticationError   (401)
    ├── NotFoundError         (404 / 410)
    ├── ValidationError       (400)
    ├── RateLimitError        (429)
    ├── ServerError           (5xx)
    └── ConnectionError       (network / timeout)
"""

from __future__ import annotations

from typing import Any


class HandoffRailError(Exception):
    """Base exception for all HandoffRail SDK errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_body = response_body or {}

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(message={self.message!r}, status_code={self.status_code})"


class AuthenticationError(HandoffRailError):
    """Raised when the API key is missing, invalid, or revoked (401)."""

    def __init__(
        self,
        message: str = "Authentication failed: invalid or missing API key",
        *,
        status_code: int = 401,
        response_body: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, response_body=response_body)


class NotFoundError(HandoffRailError):
    """Raised when the requested resource does not exist (404 / 410)."""

    def __init__(
        self,
        message: str = "Resource not found",
        *,
        resource_id: str | None = None,
        status_code: int = 404,
        response_body: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, response_body=response_body)
        self.resource_id = resource_id


class ValidationError(HandoffRailError):
    """Raised when the request payload fails server-side validation (400)."""

    def __init__(
        self,
        message: str = "Validation error",
        *,
        field: str | None = None,
        status_code: int = 400,
        response_body: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, response_body=response_body)
        self.field = field


class RateLimitError(HandoffRailError):
    """Raised when the API rate limit has been exceeded (429)."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        *,
        retry_after: int | None = None,
        status_code: int = 429,
        response_body: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, response_body=response_body)
        self.retry_after = retry_after


class ServerError(HandoffRailError):
    """Raised when the server returns a 5xx error."""

    def __init__(
        self,
        message: str = "Internal server error",
        *,
        status_code: int = 500,
        response_body: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, response_body=response_body)


class ConnectionError(HandoffRailError):
    """Raised when the SDK cannot reach the HandoffRail server."""

    def __init__(
        self,
        message: str = "Unable to connect to HandoffRail server",
        *,
        original_error: Exception | None = None,
    ) -> None:
        super().__init__(message, status_code=None, response_body={})
        self.original_error = original_error
