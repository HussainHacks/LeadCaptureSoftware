"""Pydantic schemas for Appointment entity."""

import uuid
from datetime import datetime

from pydantic import Field, model_validator

from app.schemas.common import ORMBase
from app.schemas.enums import AppointmentStatus


class AppointmentBase(ORMBase):
    """Base fields shared across Appointment operations."""

    service_id: uuid.UUID | None = None
    appointment_start: datetime
    appointment_end: datetime
    appointment_status: AppointmentStatus = AppointmentStatus.CONFIRMED
    service_type: str = Field(..., max_length=80)
    notes: str | None = None
    cancellation_reason: str | None = None

    @model_validator(mode="after")
    def validate_slot_range(self) -> "AppointmentBase":
        """Verify that timestamps are timezone-aware and end is after start."""
        if self.appointment_start.tzinfo is None or self.appointment_start.utcoffset() is None:
            raise ValueError("appointment_start must be a timezone-aware datetime")
        if self.appointment_end.tzinfo is None or self.appointment_end.utcoffset() is None:
            raise ValueError("appointment_end must be a timezone-aware datetime")
        if self.appointment_end <= self.appointment_start:
            raise ValueError("appointment_end must be strictly after appointment_start")
        return self


class AppointmentCreate(ORMBase):
    """Client/dispatcher schema for scheduling a new appointment.

    Note: Contractor appointment capacity is deterministically enforced at the
    database level via GiST exclusion constraints and row-level locking transactions.
    New appointments are initialized in CONFIRMED status.
    """

    organization_id: uuid.UUID
    lead_id: uuid.UUID
    service_id: uuid.UUID | None = None
    appointment_start: datetime
    appointment_end: datetime
    appointment_status: AppointmentStatus = AppointmentStatus.CONFIRMED
    service_type: str = Field(..., max_length=80)
    notes: str | None = None

    @model_validator(mode="after")
    def validate_slot_range(self) -> "AppointmentCreate":
        """Verify that timestamps are timezone-aware and end is after start."""
        if self.appointment_start.tzinfo is None or self.appointment_start.utcoffset() is None:
            raise ValueError("appointment_start must be a timezone-aware datetime")
        if self.appointment_end.tzinfo is None or self.appointment_end.utcoffset() is None:
            raise ValueError("appointment_end must be a timezone-aware datetime")
        if self.appointment_end <= self.appointment_start:
            raise ValueError("appointment_end must be strictly after appointment_start")
        return self


class AppointmentUpdate(ORMBase):
    """Schema for rescheduling or updating an appointment."""

    service_id: uuid.UUID | None = None
    appointment_start: datetime | None = None
    appointment_end: datetime | None = None
    appointment_status: AppointmentStatus | None = None
    service_type: str | None = Field(default=None, max_length=80)
    notes: str | None = None
    cancellation_reason: str | None = None

    @model_validator(mode="after")
    def validate_update_range(self) -> "AppointmentUpdate":
        """Verify timezone awareness and slot range when boundaries are supplied."""
        if self.appointment_start is not None and (
            self.appointment_start.tzinfo is None or self.appointment_start.utcoffset() is None
        ):
            raise ValueError("appointment_start must be a timezone-aware datetime")
        if self.appointment_end is not None and (
            self.appointment_end.tzinfo is None or self.appointment_end.utcoffset() is None
        ):
            raise ValueError("appointment_end must be a timezone-aware datetime")
        if (
            self.appointment_start is not None
            and self.appointment_end is not None
            and self.appointment_end <= self.appointment_start
        ):
            raise ValueError("appointment_end must be strictly after appointment_start")
        return self


class AppointmentRead(AppointmentBase):
    """Schema for reading appointment details."""

    id: uuid.UUID
    organization_id: uuid.UUID
    lead_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
