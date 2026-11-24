"""Message model representing individual messages in a conversation."""

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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import DeliveryStatus

if TYPE_CHECKING:
    from app.models.conversation import Conversation
    from app.models.organization import Organization


class Message(Base):
    """Individual messages exchanged in a conversation."""

    __tablename__ = "messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            name="fk_messages_conversation_composite",
            ondelete="CASCADE",
        ),
        Index("idx_messages_conversation", "conversation_id", text("created_at ASC")),
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
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    sender: Mapped[str] = mapped_column(String(20), nullable=False)
    message_content: Mapped[str] = mapped_column(Text, nullable=False)
    delivery_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=DeliveryStatus.DELIVERED.value,
    )
    external_message_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    delivery_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        foreign_keys=[organization_id],
        overlaps="messages",
    )
    conversation: Mapped["Conversation"] = relationship(
        "Conversation",
        back_populates="messages",
        primaryjoin=(
            "and_("
            "Message.organization_id == Conversation.organization_id, "
            "Message.conversation_id == Conversation.id"
            ")"
        ),
        foreign_keys=[organization_id, conversation_id],
        overlaps="organization",
    )
