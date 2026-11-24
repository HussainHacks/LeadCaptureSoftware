"""Organization model representing an HVAC contractor business tenant."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.appointment import Appointment
    from app.models.audit import AuditLog
    from app.models.conversation import Conversation
    from app.models.lead import Lead
    from app.models.membership import OrganizationMembership
    from app.models.outbox import AutomationEvent
    from app.models.service import Service


class Organization(Base):
    """Represents an individual HVAC contractor business (tenant)."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    slug: Mapped[str] = mapped_column(String(60), nullable=False, unique=True, index=True)
    industry: Mapped[str] = mapped_column(String(50), nullable=False, default="HVAC")
    timezone: Mapped[str] = mapped_column(String(50), nullable=False, default="America/New_York")
    dispatch_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    utility_emergency_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    default_slot_capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    memberships: Mapped[list["OrganizationMembership"]] = relationship(
        "OrganizationMembership",
        back_populates="organization",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    services: Mapped[list["Service"]] = relationship(
        "Service",
        back_populates="organization",
        foreign_keys="[Service.organization_id]",
    )
    leads: Mapped[list["Lead"]] = relationship(
        "Lead",
        back_populates="organization",
        foreign_keys="[Lead.organization_id]",
        overlaps="prior_lead,subsequent_leads",
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation",
        back_populates="organization",
        foreign_keys="[Conversation.organization_id]",
        overlaps="assigned_membership,conversations,lead",
    )
    appointments: Mapped[list["Appointment"]] = relationship(
        "Appointment",
        back_populates="organization",
        foreign_keys="[Appointment.organization_id]",
        overlaps="appointments,lead,service",
    )
    automation_events: Mapped[list["AutomationEvent"]] = relationship(
        "AutomationEvent",
        back_populates="organization",
        foreign_keys="[AutomationEvent.organization_id]",
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        "AuditLog",
        back_populates="organization",
        foreign_keys="[AuditLog.organization_id]",
    )
