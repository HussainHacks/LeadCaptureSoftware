"""Pydantic schemas for AutomationEvent entity (Transactional Outbox).

NOTE: Automation events are exclusively generated and processed by backend business
services and worker jobs. Public API clients MUST NOT be given endpoints to create,
modify, or inject arbitrary outbox events.
"""

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import ORMBase
from app.schemas.enums import OutboxStatus


class AutomationEventBase(ORMBase):
    """Base fields shared across outbox events."""

    event_type: str = Field(..., max_length=60)
    idempotency_key: str = Field(..., max_length=128)
    payload: dict = Field(...)
    processing_status: OutboxStatus = OutboxStatus.PENDING
    retry_count: int = Field(default=0, ge=0)
    max_retries: int = Field(default=5, ge=1)
    next_retry_at: datetime | None = None
    last_error: str | None = None


class AutomationEventCreate(AutomationEventBase):
    """Internal service DTO for atomically appending an outbox event.

    Strictly internal: instantiated only within database transactions alongside
    business mutations (e.g. outbox worker pattern). Never exposed to client input.
    """

    organization_id: uuid.UUID


# Explicit internal alias
InternalAutomationEventCreate = AutomationEventCreate


class AutomationEventUpdate(ORMBase):
    """Internal service DTO for outbox worker status transitions and backoff scheduling."""

    processing_status: OutboxStatus | None = None
    retry_count: int | None = Field(default=None, ge=0)
    next_retry_at: datetime | None = None
    last_error: str | None = None
    processed_at: datetime | None = None


class AutomationEventRead(AutomationEventBase):
    """Schema for monitoring and inspecting outbox events."""

    id: uuid.UUID
    organization_id: uuid.UUID
    created_at: datetime
    processed_at: datetime | None
