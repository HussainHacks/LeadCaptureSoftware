"""Pydantic schemas for AuditLog entity.

NOTE: Audit logs are append-only compliance records generated exclusively by backend
middleware and service interceptors. Public API clients MUST NOT be given endpoints
to create or modify audit entries.
"""

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import ORMBase


class AuditLogCreate(ORMBase):
    """Internal service DTO for recording an immutable audit event.

    Strictly internal: instantiated only by backend service interceptors and security
    middleware. Never exposed to external client input.
    """

    organization_id: uuid.UUID
    user_id: uuid.UUID | None = None
    action: str = Field(..., max_length=60)
    resource_type: str = Field(..., max_length=40)
    resource_id: str = Field(..., max_length=64)
    changes: dict | None = None
    ip_address: str | None = Field(default=None, max_length=45)


# Explicit internal alias
InternalAuditLogCreate = AuditLogCreate


class AuditLogRead(ORMBase):
    """Schema for reading audit log records in administrative compliance views."""

    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID | None
    action: str
    resource_type: str
    resource_id: str
    changes: dict | None
    ip_address: str | None
    created_at: datetime
