"""Pydantic schemas for OrganizationMembership entity."""

import uuid
from datetime import datetime

from app.schemas.common import ORMBase
from app.schemas.enums import UserRole


class OrganizationMembershipBase(ORMBase):
    """Base fields for organization membership."""

    role: UserRole = UserRole.DISPATCHER


class OrganizationMembershipCreate(OrganizationMembershipBase):
    """Schema for adding a user to an organization."""

    organization_id: uuid.UUID
    user_id: uuid.UUID


class OrganizationMembershipUpdate(ORMBase):
    """Schema for updating membership role or status."""

    role: UserRole | None = None
    is_active: bool | None = None


class OrganizationMembershipRead(OrganizationMembershipBase):
    """Schema for reading membership details."""

    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    is_active: bool
    created_at: datetime
