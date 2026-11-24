"""Pydantic schemas for Message entity.

ARCHITECTURAL NOTE ON SCHEMA ISOLATION AND AUTHORIZATION:
Pydantic schema separation distinguishes between client-facing request payloads and
internal service DTOs, but schema structure alone is NOT an authorization mechanism.
FastAPI route handlers and endpoint parameters must explicitly declare and bind the
appropriate public request models (e.g., InboundMessageRequest), while internal service
DTOs (e.g., MessageCreate / InternalMessageCreate) must only be instantiated by trusted
service logic and worker pipelines after authentication, tenancy, and role validation.
"""

import uuid
from datetime import datetime

from pydantic import ConfigDict, Field

from app.schemas.common import ORMBase
from app.schemas.enums import DeliveryStatus, MessageSender


class InboundMessageRequest(ORMBase):
    """Client-facing schema for incoming customer messages.

    Accepts ONLY customer-controlled message content. Untrusted callers
    (public webhooks, SMS gateways, web chat) must not supply channel,
    sender, delivery status, delivery metadata, or external identifiers.
    The trusted backend route or provider integration determines the channel
    and assigns it internally alongside tenant context.
    """

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        extra="forbid",
    )

    message_content: str = Field(
        ..., min_length=1, max_length=10000, description="Customer message body"
    )


class MessageBase(ORMBase):
    """Base fields shared across internal Message operations."""

    sender: MessageSender
    message_content: str
    delivery_status: DeliveryStatus = DeliveryStatus.DELIVERED
    external_message_id: str | None = Field(default=None, max_length=100)
    delivery_metadata: dict = Field(default_factory=dict)


class MessageCreate(MessageBase):
    """Internal service DTO for persisting messages.

    Used exclusively by backend services (outbound workers, inbound ingestion pipeline)
    to write validated message records to the database.
    """

    organization_id: uuid.UUID
    conversation_id: uuid.UUID


# Explicit internal alias for backend service code
InternalMessageCreate = MessageCreate


class MessageRead(MessageBase):
    """Schema for reading message details."""

    id: uuid.UUID
    organization_id: uuid.UUID
    conversation_id: uuid.UUID
    created_at: datetime
