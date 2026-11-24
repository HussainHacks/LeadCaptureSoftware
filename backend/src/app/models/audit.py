"""AuditLog model providing an immutable ledger of administrative and system actions."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    event,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.exceptions import AuditLogImmutabilityError

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.user import User


class AuditLog(Base):
    """Immutable ledger of administrative actions, safety triggers, and status transitions."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_org_resource", "organization_id", "resource_type", "resource_id"),
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
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    changes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="audit_logs",
        foreign_keys=[organization_id],
    )
    user: Mapped["User | None"] = relationship(
        "User",
        back_populates="audit_logs",
        foreign_keys=[user_id],
    )


# ---------------------------------------------------------------------------
# ORM Immutability Protections for AuditLog
# ---------------------------------------------------------------------------
# IMPORTANT ARCHITECTURAL LIMITATION:
# These event listeners provide ORM-level protection against accidental or
# malicious updates and deletions performed through SQLAlchemy ORM sessions
# and flush cycles.
#
# Boundary & Limitations:
# - They intercept session-tracked ORM flush events (before_update, before_delete).
# - They DO NOT protect against Core SQL updates, raw SQL queries, bulk UPDATE/DELETE
#   statements (e.g., query.update() / update(AuditLog).where(...)), or direct
#   database administrative connections.
# - Full database-level immutability across all clients requires PostgreSQL triggers,
#   table partition append-only storage, or database user privilege revocations,
#   which remain reserved for future infrastructure hardening.
# ---------------------------------------------------------------------------


@event.listens_for(AuditLog, "before_update")
def _prevent_audit_log_update(mapper: Any, connection: Any, target: AuditLog) -> None:
    """Reject ORM attempts to update existing AuditLog records."""
    raise AuditLogImmutabilityError("update")


@event.listens_for(AuditLog, "before_delete")
def _prevent_audit_log_delete(mapper: Any, connection: Any, target: AuditLog) -> None:
    """Reject ORM attempts to delete existing AuditLog records."""
    raise AuditLogImmutabilityError("delete")
