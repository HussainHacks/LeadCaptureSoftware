"""Pydantic schemas for Service entity."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import Field

from app.schemas.common import ORMBase


class ServiceBase(ORMBase):
    """Base fields shared across Service operations."""

    service_name: str = Field(..., max_length=100)
    service_code: str = Field(..., max_length=50)
    description: str | None = None
    estimated_duration_minutes: int = Field(default=60, ge=15)
    base_price: Decimal | None = Field(default=None, decimal_places=2, max_digits=10)
    is_emergency_service: bool = False
    active: bool = True


class ServiceCreate(ServiceBase):
    """Schema for adding a service to an organization."""

    organization_id: uuid.UUID


class ServiceUpdate(ORMBase):
    """Schema for updating service details."""

    service_name: str | None = Field(default=None, max_length=100)
    service_code: str | None = Field(default=None, max_length=50)
    description: str | None = None
    estimated_duration_minutes: int | None = Field(default=None, ge=15)
    base_price: Decimal | None = Field(default=None, decimal_places=2, max_digits=10)
    is_emergency_service: bool | None = None
    active: bool | None = None


class ServiceRead(ServiceBase):
    """Schema for reading service details."""

    id: uuid.UUID
    organization_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
