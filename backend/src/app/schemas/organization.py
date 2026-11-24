"""Pydantic schemas for Organization entity."""

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import ORMBase


class OrganizationBase(ORMBase):
    """Base fields shared across Organization operations."""

    name: str = Field(..., max_length=150, description="Legal/Trading contractor name")
    slug: str = Field(..., max_length=60, description="Unique URL/tenant identifier")
    industry: str = Field(default="HVAC", max_length=50)
    timezone: str = Field(default="America/New_York", max_length=50)
    dispatch_phone: str | None = Field(default=None, max_length=30)
    utility_emergency_phone: str | None = Field(default=None, max_length=30)
    default_slot_capacity: int = Field(default=1, ge=1)
    settings: dict = Field(default_factory=dict)


class OrganizationCreate(OrganizationBase):
    """Schema for registering a new organization."""

    pass


class OrganizationUpdate(ORMBase):
    """Schema for updating an existing organization."""

    name: str | None = Field(default=None, max_length=150)
    slug: str | None = Field(default=None, max_length=60)
    industry: str | None = Field(default=None, max_length=50)
    timezone: str | None = Field(default=None, max_length=50)
    dispatch_phone: str | None = Field(default=None, max_length=30)
    utility_emergency_phone: str | None = Field(default=None, max_length=30)
    default_slot_capacity: int | None = Field(default=None, ge=1)
    settings: dict | None = None
    is_active: bool | None = None


class OrganizationRead(OrganizationBase):
    """Schema for reading organization details."""

    id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime
