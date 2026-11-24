"""Tenant-scoped service managing inbound and outbound message records and delivery."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConsentRequiredError,
    EntityAlreadyExistsError,
    InvalidOperationError,
    ValidationError,
)
from app.core.safety import detect_safety_hazard, is_opt_out_keyword
from app.models.enums import (
    ConversationStatus,
    DeliveryStatus,
    LeadUrgency,
    MessageSender,
)
from app.models.message import Message
from app.repositories.entities import (
    ConversationRepository,
    LeadRepository,
    MessageRepository,
)
from app.services.base import TenantService
from app.services.consent_service import ConsentService

VALID_DELIVERY_TRANSITIONS: dict[DeliveryStatus, set[DeliveryStatus]] = {
    DeliveryStatus.QUEUED: {DeliveryStatus.SENT, DeliveryStatus.FAILED},
    DeliveryStatus.SENT: {DeliveryStatus.DELIVERED, DeliveryStatus.FAILED},
    DeliveryStatus.FAILED: {DeliveryStatus.QUEUED},
    DeliveryStatus.DELIVERED: set(),
    DeliveryStatus.RECEIVED: set(),
}


class MessageService(TenantService):
    """Tenant-scoped service managing messages, delivery tracking, and consent checks."""

    def __init__(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        message_repo: MessageRepository | None = None,
        conversation_repo: ConversationRepository | None = None,
        lead_repo: LeadRepository | None = None,
        consent_service: ConsentService | None = None,
    ) -> None:
        super().__init__(session, organization_id)
        self.message_repo = message_repo or MessageRepository(session)
        self.conversation_repo = conversation_repo or ConversationRepository(session)
        self.lead_repo = lead_repo or LeadRepository(session)
        self.consent_service = consent_service or ConsentService(session, organization_id)

    async def store_inbound_message(
        self,
        conversation_id: uuid.UUID,
        message_content: str,
        *,
        external_message_id: str | None = None,
        delivery_metadata: dict | None = None,
    ) -> Message:
        """Store an incoming customer message.

        Enforces:
        1. Conversation exists within the organization.
        2. Content validation (non-empty, <= 10000 chars).
        3. External provider message ID uniqueness check.
        4. Safety hazard detection: triggers immediate reply lockout and escalates lead.
        5. Opt-out keyword detection: revokes consent on STOP/UNSUBSCRIBE.
        6. Updates conversation last_message_at timestamp.
        """
        # 1. Fetch parent conversation
        conv = await self.conversation_repo.get_by_id_or_raise(
            self.organization_id, conversation_id
        )

        # 2. Content validation
        content = message_content.strip() if message_content else ""
        if not content:
            raise ValidationError("Message content cannot be empty.")
        if len(content) > 10000:
            raise ValidationError("Message content cannot exceed 10000 characters.")

        # 3. Provider message ID uniqueness check
        if external_message_id:
            existing = await self.message_repo.get_by_external_id(
                self.organization_id, external_message_id
            )
            if existing is not None:
                raise EntityAlreadyExistsError(
                    "Message", "external_message_id", external_message_id
                )

        now = datetime.now(UTC)

        # 4. Safety hazard evaluation
        hazard = detect_safety_hazard(content)
        if hazard:
            conv.is_automated_reply_locked = True
            conv.status = ConversationStatus.ESCALATED_SAFETY.value
            conv.escalation_reason = "SAFETY_HAZARD"

            # Escalate parent lead urgency to EMERGENCY
            lead = await self.lead_repo.get_by_id(self.organization_id, conv.lead_id)
            if lead is not None:
                lead.urgency = LeadUrgency.EMERGENCY.value

        # 5. Opt-out evaluation (STOP / UNSUBSCRIBE)
        if is_opt_out_keyword(content):
            await self.consent_service.revoke_consent(
                conv.lead_id,
                conv.channel,
                opt_out_keyword=content.upper(),
            )

        # 6. Persist Message
        msg = Message(
            organization_id=self.organization_id,
            conversation_id=conv.id,
            sender=MessageSender.CUSTOMER.value,
            message_content=content,
            delivery_status=DeliveryStatus.RECEIVED.value,
            external_message_id=external_message_id,
            delivery_metadata=delivery_metadata or {"received_at": now.isoformat()},
            created_at=now,
        )
        await self.message_repo.add(self.organization_id, msg)

        # Update conversation last_message_at
        conv.last_message_at = now
        await self.flush()

        return msg

    async def create_outbound_message(
        self,
        conversation_id: uuid.UUID,
        message_content: str,
        *,
        sender: MessageSender | str = MessageSender.AI_AGENT,
        external_message_id: str | None = None,
        delivery_metadata: dict | None = None,
    ) -> Message:
        """Create an outbound message record intended for customer delivery.

        Enforces:
        1. Conversation exists within the organization.
        2. Content validation.
        3. Automated reply lock safety: Blocks AI replies if is_automated_reply_locked is True.
        4. Customer consent: Rejects outbound message if channel consent is absent or revoked.
        5. Provider ID uniqueness check.
        """
        conv = await self.conversation_repo.get_by_id_or_raise(
            self.organization_id, conversation_id
        )

        sender_enum = MessageSender(sender) if isinstance(sender, str) else sender

        # Content validation
        content = message_content.strip() if message_content else ""
        if not content:
            raise ValidationError("Message content cannot be empty.")
        if len(content) > 10000:
            raise ValidationError("Message content cannot exceed 10000 characters.")

        # Safety rule: automated replies blocked during lock
        if conv.is_automated_reply_locked and sender_enum == MessageSender.AI_AGENT:
            raise InvalidOperationError(
                "Automated AI replies are strictly locked for this conversation "
                f"(status={conv.status}, reason={conv.escalation_reason})."
            )

        # Consent verification: Outbound customer messaging requires active consent
        has_consent = await self.consent_service.has_active_consent(conv.lead_id, conv.channel)
        if not has_consent:
            raise ConsentRequiredError(
                f"Outbound communication rejected: Lead '{conv.lead_id}' has not granted "
                f"or has revoked consent for channel '{conv.channel}'."
            )

        # Provider message ID uniqueness check
        if external_message_id:
            existing = await self.message_repo.get_by_external_id(
                self.organization_id, external_message_id
            )
            if existing is not None:
                raise EntityAlreadyExistsError(
                    "Message", "external_message_id", external_message_id
                )

        now = datetime.now(UTC)
        initial_metadata = dict(delivery_metadata or {})
        initial_metadata["created_at"] = now.isoformat()

        msg = Message(
            organization_id=self.organization_id,
            conversation_id=conv.id,
            sender=sender_enum.value,
            message_content=content,
            delivery_status=DeliveryStatus.QUEUED.value,
            external_message_id=external_message_id,
            delivery_metadata=initial_metadata,
            created_at=now,
        )
        await self.message_repo.add(self.organization_id, msg)

        conv.last_message_at = now
        await self.flush()

        return msg

    async def get_message_history(
        self,
        conversation_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Message]:
        """Retrieve chronological message history for a conversation."""
        # Validate conversation belongs to this organization
        await self.conversation_repo.get_by_id_or_raise(self.organization_id, conversation_id)
        return await self.message_repo.list_by_conversation(
            self.organization_id,
            conversation_id,
            limit=limit,
            offset=offset,
        )

    async def get_message(self, message_id: uuid.UUID) -> Message:
        """Retrieve a message by ID strictly scoped to the bound organization."""
        return await self.message_repo.get_by_id_or_raise(self.organization_id, message_id)

    async def update_delivery_status(
        self,
        message_id: uuid.UUID,
        new_status: DeliveryStatus | str,
        *,
        metadata: dict | None = None,
    ) -> Message:
        """Update delivery status validating allowed state transitions."""
        msg = await self.message_repo.get_by_id_or_raise(self.organization_id, message_id)

        target = DeliveryStatus(new_status) if isinstance(new_status, str) else new_status
        current = DeliveryStatus(msg.delivery_status)

        if target == current:
            return msg

        allowed = VALID_DELIVERY_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise InvalidOperationError(
                f"Invalid delivery status transition from '{current.value}' to '{target.value}'."
            )

        now = datetime.now(UTC)
        tracking_metadata = dict(metadata or {})
        if target == DeliveryStatus.SENT:
            tracking_metadata["sent_at"] = now.isoformat()
        elif target == DeliveryStatus.DELIVERED:
            tracking_metadata["delivered_at"] = now.isoformat()
        elif target == DeliveryStatus.FAILED:
            tracking_metadata["failed_at"] = now.isoformat()

        return await self.message_repo.update_delivery_status(
            self.organization_id,
            message_id,
            target,
            delivery_metadata=tracking_metadata,
        )
