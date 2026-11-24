"""CustomerConsent model tracking explicit consent per channel."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import ChannelType, ConsentStatus

if TYPE_CHECKING:
    from app.models.lead import Lead
    from app.models.organization import Organization


class CustomerConsent(Base):
    """Dedicated audit entity tracking explicit consent and opt-out history."""

    __tablename__ = "customer_consents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "lead_id"],
            ["leads.organization_id", "leads.id"],
            name="fk_consents_lead_composite",
            ondelete="RESTRICT",
        ),
        Index(
            "idx_consents_lead_channel",
            "organization_id",
            "lead_id",
            "channel",
            "consent_status",
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
    channel: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=ChannelType.SMS.value,
    )
    consent_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=ConsentStatus.OPTED_IN.value,
    )
    consent_source: Mapped[str] = mapped_column(String(50), nullable=False)
    consent_text_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    consent_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    opt_out_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    opt_out_keyword: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        foreign_keys=[organization_id],
    )
    lead: Mapped["Lead"] = relationship(
        "Lead",
        back_populates="consents",
        primaryjoin=(
            "and_("
            "CustomerConsent.organization_id == Lead.organization_id, "
            "CustomerConsent.lead_id == Lead.id"
            ")"
        ),
        foreign_keys=[organization_id, lead_id],
        overlaps="organization",
    )
