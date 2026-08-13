"""Domain errors. HTTP/API adapters map these to transport-level responses."""

from __future__ import annotations

from typing import Any, Optional


class AuthHubError(Exception):
    def __init__(self, message: str, *, code: str, details: Optional[Any] = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


class ValidationError(AuthHubError):
    def __init__(self, message: str, details: Optional[Any] = None) -> None:
        super().__init__(message, code="VALIDATION_ERROR", details=details)


class NotFoundError(AuthHubError):
    def __init__(self, entity: str, identifier: str) -> None:
        super().__init__(f"{entity} was not found", code=f"{entity.upper()}_NOT_FOUND", details={"id": identifier})


class ConflictError(AuthHubError):
    def __init__(self, message: str, details: Optional[Any] = None) -> None:
        super().__init__(message, code="CONFLICT", details=details)


class AuthenticationError(AuthHubError):
    def __init__(self, code: str = "TOKEN_INVALID", message: Optional[str] = None) -> None:
        super().__init__(message or code.replace("_", " ").lower(), code=code)


class AuthorizationError(AuthHubError):
    def __init__(self, code: str = "PERMISSION_DENIED", message: Optional[str] = None) -> None:
        super().__init__(message or code.replace("_", " ").lower(), code=code)

