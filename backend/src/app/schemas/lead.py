"""Pydantic schemas for Lead entity."""

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import ORMBase
from app.schemas.enums import (
    ConsentStatus,
    LeadSource,
    LeadStatus,
    LeadUrgency,
    TimezoneSource,
)


class LeadBase(ORMBase):
    """Base fields shared across Lead operations."""

    first_name: str | None = Field(default=None, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)
    phone: str = Field(..., max_length=30, description="E.164 formatted phone number")
    email: str | None = Field(default=None, max_length=255)
    postal_code: str | None = Field(default=None, max_length=20)
    street_address: str | None = Field(default=None, max_length=255)
    customer_timezone: str | None = Field(default=None, max_length=50)
    timezone_source: TimezoneSource = TimezoneSource.UNKNOWN
    service_type: str | None = Field(default=None, max_length=80)
    equipment_type: str | None = Field(default=None, max_length=80)
    problem_description: str | None = None
    urgency: LeadUrgency = LeadUrgency.MEDIUM
    source: LeadSource = LeadSource.WEBSITE_FORM
    metadata: dict = Field(default_factory=dict, alias="metadata_")


class LeadCreate(LeadBase):
    """Schema for creating a new lead."""

    organization_id: uuid.UUID
    sms_consent_status: ConsentStatus = ConsentStatus.PENDING
    email_consent_status: ConsentStatus = ConsentStatus.PENDING
    prior_lead_id: uuid.UUID | None = None


class LeadUpdate(ORMBase):
    """Client-facing schema for updating lead profile information.

    Prevents untrusted clients from manipulating qualification scores, lead statuses,
    or soft-deletion timestamps.
    """

    first_name: str | None = Field(default=None, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=255)
    postal_code: str | None = Field(default=None, max_length=20)
    street_address: str | None = Field(default=None, max_length=255)
    customer_timezone: str | None = Field(default=None, max_length=50)
    timezone_source: TimezoneSource | None = None
    service_type: str | None = Field(default=None, max_length=80)
    equipment_type: str | None = Field(default=None, max_length=80)
    problem_description: str | None = None
    urgency: LeadUrgency | None = None
    sms_consent_status: ConsentStatus | None = None
    email_consent_status: ConsentStatus | None = None
    metadata: dict | None = Field(default=None, alias="metadata_")


class LeadInternalUpdate(LeadUpdate):
    """Internal service DTO for automated workers and authorized workflow transitions.

    Only trusted services (qualification engine, state machine, retention workers)
    may update qualification scores, lifecyle status, or soft-deletion timestamps.
    """

    qualification_score: int | None = Field(default=None, ge=0, le=100)
    status: LeadStatus | None = None
    deleted_at: datetime | None = None


class LeadRead(LeadBase):
    """Schema for reading complete lead details."""

    id: uuid.UUID
    organization_id: uuid.UUID
    qualification_score: int
    status: LeadStatus
    sms_consent_status: ConsentStatus
    email_consent_status: ConsentStatus
    prior_lead_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
