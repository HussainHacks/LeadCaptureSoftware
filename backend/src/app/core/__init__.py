"""Core platform services, exceptions, and event dispatch abstractions."""

from app.core.events import (
    DispatchResult,
    EventDispatcher,
    SimulatedEventDispatcher,
    sanitize_payload,
)
from app.core.exceptions import (
    AppException,
    AuditLogImmutabilityError,
    ConsentRequiredError,
    DispatchError,
    EntityAlreadyExistsError,
    EntityNotFoundError,
    InvalidOperationError,
    PermanentDispatchError,
    RetryableDispatchError,
    TenantAccessViolationError,
    ValidationError,
)

__all__ = [
    "AppException",
    "AuditLogImmutabilityError",
    "ConsentRequiredError",
    "DispatchError",
    "DispatchResult",
    "EntityAlreadyExistsError",
    "EntityNotFoundError",
    "EventDispatcher",
    "InvalidOperationError",
    "PermanentDispatchError",
    "RetryableDispatchError",
    "SimulatedEventDispatcher",
    "TenantAccessViolationError",
    "ValidationError",
    "sanitize_payload",
]
