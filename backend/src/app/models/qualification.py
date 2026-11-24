"""QualificationResult model representing evaluation output."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.lead import Lead
    from app.models.organization import Organization


class QualificationResult(Base):
    """Structured evaluation output produced by the qualification engine."""

    __tablename__ = "qualification_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "lead_id"],
            ["leads.organization_id", "leads.id"],
            name="fk_qualification_lead_composite",
            ondelete="RESTRICT",
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
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    collected_information: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    missing_information: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    recommended_action: Mapped[str] = mapped_column(String(50), nullable=False)
    requires_human: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        foreign_keys=[organization_id],
        overlaps="qualification_results",
    )
    lead: Mapped["Lead"] = relationship(
        "Lead",
        back_populates="qualification_results",
        primaryjoin=(
            "and_("
            "QualificationResult.organization_id == Lead.organization_id, "
            "QualificationResult.lead_id == Lead.id"
            ")"
        ),
        foreign_keys=[organization_id, lead_id],
        overlaps="organization",
    )
