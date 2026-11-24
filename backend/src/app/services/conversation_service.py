"""Tenant-scoped service managing conversation threads, assignments, and safety locks."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_context import ActorContext
from app.core.exceptions import (
    EntityAlreadyExistsError,
    EntityNotFoundError,
    InvalidOperationError,
    ValidationError,
)
from app.models.conversation import Conversation
from app.models.enums import ChannelType, ConversationStatus, QualificationCategory, UserRole
from app.repositories.entities import (
    AuditLogRepository,
    ConversationRepository,
    LeadRepository,
    OrganizationMembershipRepository,
    QualificationRepository,
)
from app.schemas.conversation import ConversationCreate
from app.services.base import TenantService

VALID_CONVERSATION_TRANSITIONS: dict[ConversationStatus, set[ConversationStatus]] = {
    ConversationStatus.AI_ACTIVE: {
        ConversationStatus.AWAITING_CUSTOMER,
        ConversationStatus.HUMAN_TAKEOVER,
        ConversationStatus.ESCALATED_SAFETY,
        ConversationStatus.COMPLETED,
        ConversationStatus.CLOSED,
    },
    ConversationStatus.AWAITING_CUSTOMER: {
        ConversationStatus.AI_ACTIVE,
        ConversationStatus.HUMAN_TAKEOVER,
        ConversationStatus.ESCALATED_SAFETY,
        ConversationStatus.COMPLETED,
        ConversationStatus.CLOSED,
    },
    ConversationStatus.HUMAN_TAKEOVER: {
        ConversationStatus.AI_ACTIVE,
        ConversationStatus.ESCALATED_SAFETY,
        ConversationStatus.COMPLETED,
        ConversationStatus.CLOSED,
    },
    ConversationStatus.ESCALATED_SAFETY: {
        ConversationStatus.HUMAN_TAKEOVER,
        ConversationStatus.CLOSED,
    },
    ConversationStatus.COMPLETED: {
        ConversationStatus.CLOSED,
        ConversationStatus.AI_ACTIVE,
    },
    ConversationStatus.CLOSED: {
        ConversationStatus.AI_ACTIVE,
        ConversationStatus.HUMAN_TAKEOVER,
    },
}


class ConversationService(TenantService):
    """Tenant-scoped service managing conversation lifecycles and assignments."""

    def __init__(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        conversation_repo: ConversationRepository | None = None,
        lead_repo: LeadRepository | None = None,
        membership_repo: OrganizationMembershipRepository | None = None,
        qualification_repo: QualificationRepository | None = None,
        audit_repo: AuditLogRepository | None = None,
    ) -> None:
        super().__init__(session, organization_id)
        self.conversation_repo = conversation_repo or ConversationRepository(session)
        self.lead_repo = lead_repo or LeadRepository(session)
        self.membership_repo = membership_repo or OrganizationMembershipRepository(session)
        self.qualification_repo = qualification_repo or QualificationRepository(session)
        self.audit_repo = audit_repo or AuditLogRepository(session)

    async def create_conversation(
        self,
        data: ConversationCreate,
    ) -> Conversation:
        """Create a new conversation thread for a lead on a specific channel.

        Enforces:
        1. Tenant scope validation.
        2. Lead exists within the organization.
        3. Enforces one active conversation per lead and channel (partial index).
        4. Validates assigned staff member is an active member of this organization.
        """
        self.validate_tenant_scope(data.organization_id)

        # 1. Verify lead exists within organization
        lead = await self.lead_repo.get_by_id(self.organization_id, data.lead_id)
        if lead is None:
            raise EntityNotFoundError("Lead", data.lead_id)

        # 2. Check for existing active conversation on this channel
        active_conv = await self.conversation_repo.get_active_by_lead_and_channel(
            self.organization_id,
            data.lead_id,
            data.channel,
        )
        if active_conv is not None:
            raise EntityAlreadyExistsError(
                "Conversation",
                "active_lead_channel",
                f"{data.lead_id}:{data.channel.value}",
            )

        # 3. If assigned_to is provided, validate active membership
        assigned_to = data.assigned_to
        if assigned_to is not None:
            membership = await self.membership_repo.get_by_user_id(
                self.organization_id, assigned_to
            )
            if membership is None or not membership.is_active:
                raise InvalidOperationError(
                    f"User '{assigned_to}' is not an active member of organization "
                    f"'{self.organization_id}'."
                )

        conversation = Conversation(
            organization_id=self.organization_id,
            lead_id=data.lead_id,
            channel=data.channel.value,
            status=data.status.value,
            assigned_to=assigned_to,
            is_automated_reply_locked=False,
            escalation_reason=None,
        )

        return await self.conversation_repo.add(self.organization_id, conversation)

    async def get_conversation(self, conversation_id: uuid.UUID) -> Conversation:
        """Retrieve a conversation strictly scoped to the bound organization."""
        return await self.conversation_repo.get_by_id_or_raise(
            self.organization_id, conversation_id
        )

    async def list_conversations(
        self,
        *,
        status: ConversationStatus | str | None = None,
        channel: ChannelType | str | None = None,
        assigned_to: uuid.UUID | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Conversation]:
        """List conversations scoped to organization with optional filtering."""
        return await self.conversation_repo.list(
            self.organization_id,
            status=status,
            channel=channel,
            assigned_to=assigned_to,
            created_after=created_after,
            created_before=created_before,
            limit=limit,
            offset=offset,
        )

    async def count_conversations(
        self,
        *,
        status: ConversationStatus | str | None = None,
        channel: ChannelType | str | None = None,
        assigned_to: uuid.UUID | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> int:
        """Count conversations scoped to organization with matching filters."""
        return await self.conversation_repo.count(
            self.organization_id,
            status=status,
            channel=channel,
            assigned_to=assigned_to,
            created_after=created_after,
            created_before=created_before,
        )

    async def assign_conversation(
        self,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Conversation:
        """Assign conversation to an active staff member of the organization."""
        membership = await self.membership_repo.get_by_user_id(self.organization_id, user_id)
        if membership is None or not membership.is_active:
            raise InvalidOperationError(
                f"User '{user_id}' is not an active member of organization "
                f"'{self.organization_id}'."
            )

        return await self.conversation_repo.assign(
            self.organization_id,
            conversation_id,
            user_id,
        )

    async def unassign_conversation(
        self,
        conversation_id: uuid.UUID,
    ) -> Conversation:
        """Remove staff assignment from a conversation."""
        return await self.conversation_repo.assign(
            self.organization_id,
            conversation_id,
            None,
        )

    async def change_status(
        self,
        conversation_id: uuid.UUID,
        new_status: ConversationStatus | str,
    ) -> Conversation:
        """Transition conversation status following the validated state machine."""
        conv = await self.get_conversation(conversation_id)

        target = ConversationStatus(new_status) if isinstance(new_status, str) else new_status
        current = ConversationStatus(conv.status)

        if target == current:
            return conv

        allowed = VALID_CONVERSATION_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise InvalidOperationError(
                f"Invalid conversation status transition from '{current.value}' to "
                f"'{target.value}'."
            )

        conv.status = target.value
        await self.flush()
        return conv

    async def escalate_conversation(
        self,
        conversation_id: uuid.UUID,
        reason: str,
        *,
        lock_automated_reply: bool = True,
    ) -> Conversation:
        """Escalate conversation to human takeover or safety review with reply lock."""
        conv = await self.get_conversation(conversation_id)
        conv.status = ConversationStatus.HUMAN_TAKEOVER.value
        conv.escalation_reason = reason
        conv.is_automated_reply_locked = lock_automated_reply
        await self.flush()
        return conv

    async def trigger_safety_lock(
        self,
        conversation_id: uuid.UUID,
        hazard_reason: str = "SAFETY_HAZARD",
    ) -> Conversation:
        """Trigger an emergency safety lock on the conversation."""
        conv = await self.get_conversation(conversation_id)
        conv.status = ConversationStatus.ESCALATED_SAFETY.value
        conv.escalation_reason = hazard_reason
        conv.is_automated_reply_locked = True
        await self.flush()
        return conv

    async def unlock_automated_replies(
        self,
        conversation_id: uuid.UUID,
    ) -> Conversation:
        """Clear automated reply lock for non-escalated operational pauses.

        Conversations in ESCALATED_SAFETY or HUMAN_TAKEOVER, or with an active
        escalation reason, cannot be unlocked through this method. They must undergo
        the formal human safety resolution workflow via resolve_safety_escalation().
        """
        conv = await self.get_conversation(conversation_id)
        if (
            conv.status
            in (
                ConversationStatus.ESCALATED_SAFETY.value,
                ConversationStatus.HUMAN_TAKEOVER.value,
            )
            or conv.escalation_reason is not None
        ):
            raise InvalidOperationError(
                f"Cannot unlock automated replies for conversation in '{conv.status}' "
                "status through the ordinary unlock method. Use the dedicated "
                "resolve_safety_escalation workflow."
            )
        conv.is_automated_reply_locked = False
        await self.flush()
        return conv

    async def resolve_safety_escalation(
        self,
        conversation_id: uuid.UUID,
        authorized_user_id: uuid.UUID | ActorContext,
        resolution_notes: str,
        *,
        new_status: ConversationStatus = ConversationStatus.HUMAN_TAKEOVER,
    ) -> Conversation:
        """Explicitly resolve a safety escalation by an authorized human staff member.

        Verifies that authorized_user_id is an active member with role OWNER, ADMIN,
        or DISPATCHER in the organization. Requires an existing active safety escalation,
        meaningful resolution notes, and validates that the lead's latest qualification
        evaluation does not still require human review. Unlocks automated replies,
        transitions status, clears the escalation reason, and logs an immutable AuditLog event.
        """
        actor_id = (
            authorized_user_id.user_id
            if isinstance(authorized_user_id, ActorContext)
            else authorized_user_id
        )

        membership = await self.membership_repo.get_by_user_id(self.organization_id, actor_id)
        if membership is None or not membership.is_active:
            raise InvalidOperationError(
                f"User '{actor_id}' is not an active member of organization "
                f"'{self.organization_id}'."
            )
        if membership.role not in (
            UserRole.OWNER.value,
            UserRole.ADMIN.value,
            UserRole.DISPATCHER.value,
        ):
            raise InvalidOperationError(
                f"User with role '{membership.role}' is not authorized to resolve safety "
                "escalations."
            )

        if not resolution_notes or len(resolution_notes.strip()) < 5:
            raise ValidationError(
                "A detailed resolution note (at least 5 characters) is required to resolve "
                "a safety escalation."
            )

        conv = await self.get_conversation(conversation_id)

        # 1. Require an existing active safety escalation; reject repeated/out-of-order resolution
        is_active_safety = conv.status == ConversationStatus.ESCALATED_SAFETY.value or (
            conv.status == ConversationStatus.HUMAN_TAKEOVER.value
            and conv.is_automated_reply_locked
            and conv.escalation_reason is not None
        )
        if not is_active_safety:
            if (
                conv.status == ConversationStatus.HUMAN_TAKEOVER.value
                and not conv.is_automated_reply_locked
            ):
                raise InvalidOperationError(
                    "Conversation safety escalation has already been resolved."
                )
            raise InvalidOperationError(
                f"Conversation in status '{conv.status}' does not have an active safety escalation."
            )

        # 2. Check the latest qualification result before clearing the conversation safety lock
        latest_qual = await self.qualification_repo.get_latest_for_lead(
            self.organization_id, conv.lead_id
        )
        if latest_qual is not None and (
            latest_qual.requires_human
            or latest_qual.category == QualificationCategory.HUMAN_REVIEW.value
        ):
            raise InvalidOperationError(
                "Cannot resolve conversation safety escalation while lead qualification still "
                "requires human review. Resolve qualification safety review first."
            )

        # 3. Capture previous state for audit log
        prev_status = conv.status
        prev_locked = conv.is_automated_reply_locked
        prev_reason = conv.escalation_reason

        # 4. Apply status update
        conv.status = new_status.value
        conv.is_automated_reply_locked = False
        conv.escalation_reason = None

        # 5. Write immutable AuditLog record in the same transaction
        await self.audit_repo.log_event(
            self.organization_id,
            action="SAFETY_ESCALATION_RESOLVED",
            resource_type="conversation",
            resource_id=str(conv.id),
            user_id=actor_id,
            changes={
                "lead_id": str(conv.lead_id),
                "previous_status": prev_status,
                "new_status": new_status.value,
                "previous_reply_locked": prev_locked,
                "new_reply_locked": False,
                "previous_escalation_reason": prev_reason,
                "resolution_notes": resolution_notes.strip(),
            },
        )

        await self.flush()
        return conv
