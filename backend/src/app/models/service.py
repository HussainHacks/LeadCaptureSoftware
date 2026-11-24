"""Service model representing HVAC services offered by a contractor."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.appointment import Appointment
    from app.models.organization import Organization


class Service(Base):
    """Catalog of contractor-offered HVAC services."""

    __tablename__ = "services"
    __table_args__ = (
        UniqueConstraint("organization_id", "service_code", name="uq_services_org_code"),
        UniqueConstraint("organization_id", "id", name="uq_services_org_id"),
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
    service_name: Mapped[str] = mapped_column(String(100), nullable=False)
    service_code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    base_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    is_emergency_service: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="services",
        foreign_keys=[organization_id],
    )
    appointments: Mapped[list["Appointment"]] = relationship(
        "Appointment",
        back_populates="service",
        primaryjoin=(
            "and_("
            "Service.organization_id == foreign(Appointment.organization_id), "
            "Service.id == foreign(Appointment.service_id)"
            ")"
        ),
        overlaps="appointments,lead,organization",
    )
