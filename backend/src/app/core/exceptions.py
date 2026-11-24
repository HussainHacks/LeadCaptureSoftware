"""Domain and application exceptions for the LeadGen platform.

These exceptions represent business rule violations, resource states, and tenant security
boundaries. They are completely decoupled from HTTP status codes and transport logic.
Future FastAPI exception handlers will map these domain errors to appropriate HTTP responses.
"""

from typing import Any


class AppException(Exception):
    """Base exception for all domain and application errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class EntityNotFoundError(AppException):
    """Raised when a requested entity cannot be found within the specified scope."""

    def __init__(self, entity_name: str, identifier: Any) -> None:
        super().__init__(f"{entity_name} with identifier '{identifier}' was not found.")
        self.entity_name = entity_name
        self.identifier = identifier


class EntityAlreadyExistsError(AppException):
    """Raised when creating an entity that violates uniqueness constraints."""

    def __init__(self, entity_name: str, field: str, value: Any) -> None:
        super().__init__(f"{entity_name} with {field} '{value}' already exists.")
        self.entity_name = entity_name
        self.field = field
        self.value = value


class TenantAccessViolationError(AppException):
    """Raised when cross-tenant access or an unscoped tenant operation is attempted."""

    def __init__(
        self,
        message: str = "Cross-tenant access or unauthorized tenant operation detected.",
    ) -> None:
        super().__init__(message)


class InvalidOperationError(AppException):
    """Raised when a business operation cannot be executed in the current state."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ValidationError(AppException):
    """Raised when domain entity input fails business format or structural validation."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ConsentRequiredError(AppException):
    """Raised when an outbound communication is attempted without active customer consent."""

    def __init__(
        self,
        message: str = "Outbound communication requires active customer consent.",
    ) -> None:
        super().__init__(message)


class AuditLogImmutabilityError(InvalidOperationError):
    """Raised when an attempt is made to update or delete an immutable AuditLog record."""

    def __init__(self, operation: str = "modify") -> None:
        super().__init__(f"AuditLog records are immutable and cannot be {operation}d.")
        self.operation = operation


class DispatchError(AppException):
    """Base exception for outbox event dispatch failures."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = True,
        status_code: int = 500,
        event_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code
        self.event_id = event_id


class RetryableDispatchError(DispatchError):
    """Raised when a temporary dispatch failure occurs that should be retried with backoff."""

    def __init__(
        self,
        message: str = "Transient dispatch failure; retry scheduled.",
        *,
        status_code: int = 503,
        event_id: str | None = None,
    ) -> None:
        super().__init__(message, retryable=True, status_code=status_code, event_id=event_id)


class PermanentDispatchError(DispatchError):
    """Raised when a non-retryable dispatch failure occurs (terminal failure, e.g. bad request)."""

    def __init__(
        self,
        message: str = "Permanent dispatch failure; terminal error.",
        *,
        status_code: int = 400,
        event_id: str | None = None,
    ) -> None:
        super().__init__(message, retryable=False, status_code=status_code, event_id=event_id)


class StaleLeaseError(InvalidOperationError):
    """Raised when an outbox worker attempts to settle an event whose lease has been reassigned."""

    def __init__(
        self,
        message: str = "Outbox lease has expired or been reassigned to another worker.",
        *,
        event_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.event_id = event_id
