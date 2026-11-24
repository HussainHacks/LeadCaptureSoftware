"""Conversation model representing engagement threads with leads."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import ChannelType, ConversationStatus

if TYPE_CHECKING:
    from app.models.lead import Lead
    from app.models.membership import OrganizationMembership
    from app.models.message import Message
    from app.models.organization import Organization
    from app.models.user import User


class Conversation(Base):
    """Represents an ongoing interaction thread with a lead across an engagement channel."""

    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_conversations_org_id"),
        ForeignKeyConstraint(
            ["organization_id", "lead_id"],
            ["leads.organization_id", "leads.id"],
            name="fk_conversations_lead_composite",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "assigned_to"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            name="fk_conversations_assigned_membership",
            ondelete="SET NULL (assigned_to)",
        ),
        Index(
            "uq_active_conv_per_lead",
            "organization_id",
            "lead_id",
            "channel",
            unique=True,
            postgresql_where=text("status NOT IN ('CLOSED', 'ARCHIVED')"),
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
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=ConversationStatus.AI_ACTIVE.value,
    )
    # Database-level composite foreign key fk_conversations_assigned_membership ensures
    # the assigned user is a member of the conversation's organization.
    # Active membership (is_active = TRUE) must still be validated in the service layer,
    # since foreign key constraints cannot evaluate dynamic boolean predicates.
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    is_automated_reply_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    escalation_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="conversations",
        foreign_keys=[organization_id],
    )
    lead: Mapped["Lead"] = relationship(
        "Lead",
        back_populates="conversations",
        primaryjoin=(
            "and_("
            "Conversation.organization_id == Lead.organization_id, "
            "Conversation.lead_id == Lead.id"
            ")"
        ),
        foreign_keys=[organization_id, lead_id],
        overlaps="organization",
    )
    assigned_user: Mapped["User | None"] = relationship(
        "User",
        back_populates="assigned_conversations",
        primaryjoin="Conversation.assigned_to == User.id",
        foreign_keys=[assigned_to],
    )
    assigned_membership: Mapped["OrganizationMembership | None"] = relationship(
        "OrganizationMembership",
        back_populates="conversations",
        primaryjoin=(
            "and_("
            "Conversation.organization_id == OrganizationMembership.organization_id, "
            "Conversation.assigned_to == OrganizationMembership.user_id"
            ")"
        ),
        foreign_keys=[organization_id, assigned_to],
        overlaps="assigned_conversations,assigned_user,lead,organization",
    )
    messages: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        primaryjoin=(
            "and_("
            "Conversation.organization_id == Message.organization_id, "
            "Conversation.id == Message.conversation_id"
            ")"
        ),
        foreign_keys="[Message.organization_id, Message.conversation_id]",
    )
