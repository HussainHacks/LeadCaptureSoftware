"""Pydantic schemas for Conversation entity."""

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import ORMBase
from app.schemas.enums import ChannelType, ConversationStatus


class ConversationBase(ORMBase):
    """Base fields shared across Conversation operations."""

    channel: ChannelType = ChannelType.SMS
    status: ConversationStatus = ConversationStatus.AI_ACTIVE
    assigned_to: uuid.UUID | None = None
    is_automated_reply_locked: bool = False
    escalation_reason: str | None = Field(default=None, max_length=50)


class ConversationCreate(ORMBase):
    """Client schema for initializing a new conversation thread.

    Prevents external clients from setting emergency lockout flags or fake escalation
    reasons upon conversation creation.
    """

    organization_id: uuid.UUID
    lead_id: uuid.UUID
    channel: ChannelType = ChannelType.SMS
    status: ConversationStatus = ConversationStatus.AI_ACTIVE
    assigned_to: uuid.UUID | None = None


class ConversationUpdate(ORMBase):
    """Client-facing schema for updating conversation status or assignment.

    Prevents untrusted clients from tampering with emergency safety lockouts.
    """

    status: ConversationStatus | None = None
    assigned_to: uuid.UUID | None = None


class ConversationInternalUpdate(ConversationUpdate):
    """Internal service DTO for system-level safety lockouts and emergency handling.

    Only trusted internal safety workflows (e.g. emergency detection triggers,
    manual supervisor override handlers) may set or clear reply lockouts.
    """

    is_automated_reply_locked: bool | None = None
    escalation_reason: str | None = Field(default=None, max_length=50)


class ConversationEscalationRequest(ORMBase):
    """Explicit schema for manual dispatcher or supervisor escalation."""

    escalation_reason: str = Field(..., max_length=50)
    lock_automated_reply: bool = True


class ConversationRead(ConversationBase):
    """Schema for reading conversation thread details."""

    id: uuid.UUID
    organization_id: uuid.UUID
    lead_id: uuid.UUID
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime
