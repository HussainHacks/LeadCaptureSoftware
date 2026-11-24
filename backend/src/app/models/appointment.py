"""Appointment model representing booked service visits and inspections."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TSTZRANGE, UUID, ExcludeConstraint, Range
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import AppointmentStatus

if TYPE_CHECKING:
    from app.models.lead import Lead
    from app.models.organization import Organization
    from app.models.service import Service


class Appointment(Base):
    """Booked service visits and diagnostic inspections."""

    __tablename__ = "appointments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "lead_id"],
            ["leads.organization_id", "leads.id"],
            name="fk_appointments_lead_composite",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "service_id"],
            ["services.organization_id", "services.id"],
            name="fk_appointments_service_composite",
            ondelete="RESTRICT",
        ),
        ExcludeConstraint(
            ("organization_id", "="),
            ("time_slot", "&&"),
            where=text("appointment_status IN ('CONFIRMED', 'OFFERED')"),
            using="gist",
            name="uq_contractor_no_double_booking",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    service_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    time_slot: Mapped[Range[datetime]] = mapped_column(TSTZRANGE, nullable=False)
    appointment_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    appointment_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    appointment_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=AppointmentStatus.CONFIRMED.value,
    )
    service_type: Mapped[str] = mapped_column(String(80), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="appointments",
        foreign_keys=[organization_id],
    )
    lead: Mapped["Lead"] = relationship(
        "Lead",
        back_populates="appointments",
        primaryjoin=(
            "and_("
            "Appointment.organization_id == Lead.organization_id, "
            "Appointment.lead_id == Lead.id"
            ")"
        ),
        foreign_keys=[organization_id, lead_id],
        overlaps="organization",
    )
    service: Mapped["Service | None"] = relationship(
        "Service",
        back_populates="appointments",
        primaryjoin=(
            "and_("
            "Appointment.organization_id == Service.organization_id, "
            "Appointment.service_id == Service.id"
            ")"
        ),
        foreign_keys=[organization_id, service_id],
        overlaps="lead,organization",
    )
