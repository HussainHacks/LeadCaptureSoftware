"""Lead model representing incoming customer inquiries."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import (
    ConsentStatus,
    LeadSource,
    LeadStatus,
    LeadUrgency,
    TimezoneSource,
)

if TYPE_CHECKING:
    from app.models.appointment import Appointment
    from app.models.consent import CustomerConsent
    from app.models.conversation import Conversation
    from app.models.organization import Organization
    from app.models.qualification import QualificationResult


class Lead(Base):
    """Authoritative record of incoming customer inquiries."""

    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_leads_org_id"),
        ForeignKeyConstraint(
            ["organization_id", "prior_lead_id"],
            ["leads.organization_id", "leads.id"],
            name="fk_leads_prior_lead_composite",
            ondelete="SET NULL",
        ),
        Index(
            "idx_leads_org_status",
            "organization_id",
            "status",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("idx_leads_org_phone", "organization_id", "phone"),
        Index("idx_leads_org_created", "organization_id", text("created_at DESC")),
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
    first_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    phone: Mapped[str] = mapped_column(String(30), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    street_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_timezone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    timezone_source: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=TimezoneSource.UNKNOWN.value,
    )
    service_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    equipment_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    problem_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    urgency: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=LeadUrgency.MEDIUM.value,
    )
    qualification_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=LeadStatus.NEW.value,
    )
    sms_consent_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=ConsentStatus.PENDING.value,
    )
    email_consent_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=ConsentStatus.PENDING.value,
    )
    source: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=LeadSource.WEBSITE_FORM.value,
    )
    prior_lead_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="leads",
        foreign_keys=[organization_id],
    )
    prior_lead: Mapped["Lead | None"] = relationship(
        "Lead",
        remote_side="[Lead.organization_id, Lead.id]",
        foreign_keys="[Lead.organization_id, Lead.prior_lead_id]",
        primaryjoin=(
            "and_(Lead.organization_id == Lead.organization_id, Lead.prior_lead_id == Lead.id)"
        ),
        back_populates="subsequent_leads",
        overlaps="organization",
    )
    subsequent_leads: Mapped[list["Lead"]] = relationship(
        "Lead",
        remote_side="[Lead.organization_id, Lead.prior_lead_id]",
        foreign_keys="[Lead.organization_id, Lead.prior_lead_id]",
        primaryjoin=(
            "and_(Lead.organization_id == Lead.organization_id, Lead.id == Lead.prior_lead_id)"
        ),
        back_populates="prior_lead",
        overlaps="organization",
    )
    consents: Mapped[list["CustomerConsent"]] = relationship(
        "CustomerConsent",
        back_populates="lead",
        primaryjoin=(
            "and_("
            "Lead.organization_id == CustomerConsent.organization_id, "
            "Lead.id == CustomerConsent.lead_id"
            ")"
        ),
        foreign_keys="[CustomerConsent.organization_id, CustomerConsent.lead_id]",
        overlaps="organization",
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation",
        back_populates="lead",
        primaryjoin=(
            "and_("
            "Lead.organization_id == Conversation.organization_id, "
            "Lead.id == Conversation.lead_id"
            ")"
        ),
        foreign_keys="[Conversation.organization_id, Conversation.lead_id]",
        overlaps="assigned_membership,organization",
    )
    appointments: Mapped[list["Appointment"]] = relationship(
        "Appointment",
        back_populates="lead",
        primaryjoin=(
            "and_("
            "Lead.organization_id == Appointment.organization_id, "
            "Lead.id == Appointment.lead_id"
            ")"
        ),
        foreign_keys="[Appointment.organization_id, Appointment.lead_id]",
        overlaps="organization,service",
    )
    qualification_results: Mapped[list["QualificationResult"]] = relationship(
        "QualificationResult",
        back_populates="lead",
        primaryjoin=(
            "and_("
            "Lead.organization_id == QualificationResult.organization_id, "
            "Lead.id == QualificationResult.lead_id"
            ")"
        ),
        foreign_keys="[QualificationResult.organization_id, QualificationResult.lead_id]",
        overlaps="organization",
    )
