"""Domain-level exceptions (framework independent). The API layer maps these to HTTP status codes."""

from __future__ import annotations


class DomainError(Exception):
    """Base class. `code` is a stable machine-readable string."""

    code = "domain_error"

    def __init__(self, message: str, *, detail: dict | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class ParamsError(DomainError):
    code = "params_error"


class NotFound(DomainError):
    code = "not_found"


class Unauthorized(DomainError):
    code = "demo_identity_missing"


class Forbidden(DomainError):
    code = "forbidden"


class StateConflict(DomainError):
    """The request is valid but conflicts with the current state (HTTP 409)."""

    code = "state_conflict"


class InvalidInput(DomainError):
    """The request content is invalid (HTTP 422)."""

    code = "invalid_input"
