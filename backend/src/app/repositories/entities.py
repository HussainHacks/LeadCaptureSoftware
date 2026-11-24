"""Concrete entity repository implementations."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EntityNotFoundError, InvalidOperationError
from app.models import (
    Appointment,
    AuditLog,
    AutomationEvent,
    Conversation,
    CustomerConsent,
    Lead,
    Message,
    Organization,
    OrganizationMembership,
    QualificationResult,
    Service,
    User,
)
from app.models.enums import (
    AppointmentStatus,
    ChannelType,
    ConversationStatus,
    DeliveryStatus,
    LeadSource,
    LeadStatus,
    LeadUrgency,
    OutboxStatus,
)
from app.repositories.global_repo import GlobalRepository
from app.repositories.tenant import TenantRepository


class LeadRepository(TenantRepository[Lead]):
    """Tenant-scoped repository for Lead entities.

    Enforces organization isolation on all queries and mutations.
    Provides tenant-scoped filtering, phone lookups, rolling duplicate queries,
    and soft-deletion.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Lead)

    async def get_by_id(
        self,
        organization_id: uuid.UUID,
        id: uuid.UUID,
        *,
        include_deleted: bool = False,
    ) -> Lead | None:
        """Fetch a lead by ID strictly scoped to organization, optionally excluding deleted."""
        stmt = select(Lead).where(
            Lead.organization_id == organization_id,
            Lead.id == id,
        )
        if not include_deleted:
            stmt = stmt.where(Lead.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_or_raise(
        self,
        organization_id: uuid.UUID,
        id: uuid.UUID,
        *,
        include_deleted: bool = False,
    ) -> Lead:
        """Fetch a lead by ID or raise EntityNotFoundError."""
        lead = await self.get_by_id(organization_id, id, include_deleted=include_deleted)
        if lead is None:
            raise EntityNotFoundError("Lead", id)
        return lead

    async def get_by_phone(
        self,
        organization_id: uuid.UUID,
        phone: str,
        *,
        include_deleted: bool = False,
    ) -> Lead | None:
        """Fetch the most recent lead matching a phone number within an organization."""
        stmt = select(Lead).where(
            Lead.organization_id == organization_id,
            Lead.phone == phone,
        )
        if not include_deleted:
            stmt = stmt.where(Lead.deleted_at.is_(None))
        stmt = stmt.order_by(Lead.created_at.desc()).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_recent_by_phone(
        self,
        organization_id: uuid.UUID,
        phone: str,
        since: datetime,
        *,
        include_deleted: bool = False,
    ) -> Lead | None:
        """Find the most recent lead for a phone number created at or after `since`."""
        stmt = select(Lead).where(
            Lead.organization_id == organization_id,
            Lead.phone == phone,
            Lead.created_at >= since,
        )
        if not include_deleted:
            stmt = stmt.where(Lead.deleted_at.is_(None))
        stmt = stmt.order_by(Lead.created_at.desc()).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        organization_id: uuid.UUID,
        *,
        status: LeadStatus | str | None = None,
        urgency: LeadUrgency | str | None = None,
        source: LeadSource | str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Lead]:
        """List leads scoped to organization with optional status, urgency, and date filters."""
        stmt = select(Lead).where(Lead.organization_id == organization_id)

        if not include_deleted:
            stmt = stmt.where(Lead.deleted_at.is_(None))
        if status is not None:
            val = status.value if isinstance(status, LeadStatus) else status
            stmt = stmt.where(Lead.status == val)
        if urgency is not None:
            val = urgency.value if isinstance(urgency, LeadUrgency) else urgency
            stmt = stmt.where(Lead.urgency == val)
        if source is not None:
            val = source.value if isinstance(source, LeadSource) else source
            stmt = stmt.where(Lead.source == val)
        if created_after is not None:
            stmt = stmt.where(Lead.created_at >= created_after)
        if created_before is not None:
            stmt = stmt.where(Lead.created_at <= created_before)

        stmt = stmt.order_by(Lead.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(
        self,
        organization_id: uuid.UUID,
        *,
        status: LeadStatus | str | None = None,
        urgency: LeadUrgency | str | None = None,
        source: LeadSource | str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        include_deleted: bool = False,
    ) -> int:
        """Count leads scoped to organization using identical tenant-scoped filters."""
        stmt = select(func.count()).select_from(Lead).where(Lead.organization_id == organization_id)

        if not include_deleted:
            stmt = stmt.where(Lead.deleted_at.is_(None))
        if status is not None:
            val = status.value if isinstance(status, LeadStatus) else status
            stmt = stmt.where(Lead.status == val)
        if urgency is not None:
            val = urgency.value if isinstance(urgency, LeadUrgency) else urgency
            stmt = stmt.where(Lead.urgency == val)
        if source is not None:
            val = source.value if isinstance(source, LeadSource) else source
            stmt = stmt.where(Lead.source == val)
        if created_after is not None:
            stmt = stmt.where(Lead.created_at >= created_after)
        if created_before is not None:
            stmt = stmt.where(Lead.created_at <= created_before)

        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def soft_delete(
        self,
        organization_id: uuid.UUID,
        id: uuid.UUID,
    ) -> Lead:
        """Mark a lead as soft-deleted by setting deleted_at to current UTC timestamp."""
        lead = await self.get_by_id_or_raise(organization_id, id, include_deleted=False)
        lead.deleted_at = datetime.now(UTC)
        await self.session.flush()
        return lead


class ServiceRepository(TenantRepository[Service]):
    """Tenant-scoped repository for Service entities.

    Enforces organization boundaries on every service query and mutation.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Service)

    async def get_by_code(self, organization_id: uuid.UUID, service_code: str) -> Service | None:
        """Fetch a service by its unique service code within an organization."""
        stmt = select(Service).where(
            Service.organization_id == organization_id,
            func.lower(Service.service_code) == service_code.strip().lower(),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        organization_id: uuid.UUID,
        *,
        active_only: bool = False,
        is_emergency_service: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Service]:
        """List services scoped to organization with optional active and emergency filters."""
        stmt = select(Service).where(Service.organization_id == organization_id)
        if active_only:
            stmt = stmt.where(Service.active.is_(True))
        if is_emergency_service is not None:
            stmt = stmt.where(Service.is_emergency_service == is_emergency_service)
        stmt = stmt.order_by(Service.service_name.asc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(
        self,
        organization_id: uuid.UUID,
        *,
        active_only: bool = False,
        is_emergency_service: bool | None = None,
    ) -> int:
        """Count services scoped to organization with matching active and emergency filters."""
        stmt = (
            select(func.count())
            .select_from(Service)
            .where(Service.organization_id == organization_id)
        )
        if active_only:
            stmt = stmt.where(Service.active.is_(True))
        if is_emergency_service is not None:
            stmt = stmt.where(Service.is_emergency_service == is_emergency_service)
        result = await self.session.execute(stmt)
        return result.scalar() or 0


class UserRepository(GlobalRepository[User]):
    """Global repository for User entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User)

    async def get_by_email(self, email: str) -> User | None:
        """Fetch a user by normalized lowercase email."""
        stmt = select(User).where(func.lower(User.email) == email.lower().strip())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class OrganizationRepository(GlobalRepository[Organization]):
    """Global repository for Organization entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Organization)

    async def get_by_slug(self, slug: str) -> Organization | None:
        """Fetch an organization by its unique lowercase slug."""
        stmt = select(Organization).where(Organization.slug == slug.lower().strip())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class OrganizationMembershipRepository(TenantRepository[OrganizationMembership]):
    """Tenant-scoped repository for OrganizationMembership entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, OrganizationMembership)

    async def get_by_user_id(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> OrganizationMembership | None:
        """Fetch a membership record for a specific user within an organization."""
        stmt = select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_organization(
        self,
        organization_id: uuid.UUID,
        *,
        include_inactive: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[OrganizationMembership]:
        """List memberships for an organization with optional active-only filtering."""
        stmt = select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id
        )
        if not include_inactive:
            stmt = stmt.where(OrganizationMembership.is_active.is_(True))
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()


class ConversationRepository(TenantRepository[Conversation]):
    """Tenant-scoped repository for Conversation entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Conversation)

    async def get_by_id(self, organization_id: uuid.UUID, id: uuid.UUID) -> Conversation | None:
        """Fetch a conversation by ID strictly scoped to organization."""
        stmt = select(Conversation).where(
            Conversation.organization_id == organization_id,
            Conversation.id == id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_or_raise(self, organization_id: uuid.UUID, id: uuid.UUID) -> Conversation:
        """Fetch a conversation by ID or raise EntityNotFoundError."""
        conv = await self.get_by_id(organization_id, id)
        if conv is None:
            raise EntityNotFoundError("Conversation", id)
        return conv

    async def get_active_by_lead_and_channel(
        self,
        organization_id: uuid.UUID,
        lead_id: uuid.UUID,
        channel: ChannelType | str,
    ) -> Conversation | None:
        """Fetch an active conversation for a lead on a specific channel.

        Active statuses are all except CLOSED and ARCHIVED (per uq_active_conv_per_lead).
        """
        chan_val = channel.value if isinstance(channel, ChannelType) else channel
        stmt = select(Conversation).where(
            Conversation.organization_id == organization_id,
            Conversation.lead_id == lead_id,
            Conversation.channel == chan_val,
            Conversation.status.notin_(["CLOSED", "ARCHIVED"]),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_lead(
        self,
        organization_id: uuid.UUID,
        lead_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Conversation]:
        """List all conversations for a specific lead."""
        stmt = (
            select(Conversation)
            .where(
                Conversation.organization_id == organization_id,
                Conversation.lead_id == lead_id,
            )
            .order_by(Conversation.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list(
        self,
        organization_id: uuid.UUID,
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
        stmt = select(Conversation).where(Conversation.organization_id == organization_id)

        if status is not None:
            val = status.value if isinstance(status, ConversationStatus) else status
            stmt = stmt.where(Conversation.status == val)
        if channel is not None:
            val = channel.value if isinstance(channel, ChannelType) else channel
            stmt = stmt.where(Conversation.channel == val)
        if assigned_to is not None:
            stmt = stmt.where(Conversation.assigned_to == assigned_to)
        if created_after is not None:
            stmt = stmt.where(Conversation.created_at >= created_after)
        if created_before is not None:
            stmt = stmt.where(Conversation.created_at <= created_before)

        stmt = stmt.order_by(Conversation.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(
        self,
        organization_id: uuid.UUID,
        *,
        status: ConversationStatus | str | None = None,
        channel: ChannelType | str | None = None,
        assigned_to: uuid.UUID | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> int:
        """Count conversations scoped to organization with matching filters."""
        stmt = (
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.organization_id == organization_id)
        )

        if status is not None:
            val = status.value if isinstance(status, ConversationStatus) else status
            stmt = stmt.where(Conversation.status == val)
        if channel is not None:
            val = channel.value if isinstance(channel, ChannelType) else channel
            stmt = stmt.where(Conversation.channel == val)
        if assigned_to is not None:
            stmt = stmt.where(Conversation.assigned_to == assigned_to)
        if created_after is not None:
            stmt = stmt.where(Conversation.created_at >= created_after)
        if created_before is not None:
            stmt = stmt.where(Conversation.created_at <= created_before)

        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def assign(
        self,
        organization_id: uuid.UUID,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID | None,
    ) -> Conversation:
        """Assign or unassign a conversation."""
        conv = await self.get_by_id_or_raise(organization_id, conversation_id)
        conv.assigned_to = user_id
        await self.session.flush()
        return conv

    async def update_status(
        self,
        organization_id: uuid.UUID,
        conversation_id: uuid.UUID,
        status: ConversationStatus | str,
        *,
        is_automated_reply_locked: bool | None = None,
        escalation_reason: str | None = None,
    ) -> Conversation:
        """Update conversation status and optional safety lockout fields."""
        conv = await self.get_by_id_or_raise(organization_id, conversation_id)
        conv.status = status.value if isinstance(status, ConversationStatus) else status
        if is_automated_reply_locked is not None:
            conv.is_automated_reply_locked = is_automated_reply_locked
        if escalation_reason is not None:
            conv.escalation_reason = escalation_reason
        await self.session.flush()
        return conv

    async def update_last_message_at(
        self,
        organization_id: uuid.UUID,
        conversation_id: uuid.UUID,
        last_message_at: datetime,
    ) -> Conversation:
        """Update the last_message_at timestamp for ordering inboxes."""
        conv = await self.get_by_id_or_raise(organization_id, conversation_id)
        conv.last_message_at = last_message_at
        await self.session.flush()
        return conv


class MessageRepository(TenantRepository[Message]):
    """Tenant-scoped repository for Message entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Message)

    async def get_by_id(self, organization_id: uuid.UUID, id: uuid.UUID) -> Message | None:
        """Fetch a message by ID strictly scoped to organization."""
        stmt = select(Message).where(
            Message.organization_id == organization_id,
            Message.id == id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_or_raise(self, organization_id: uuid.UUID, id: uuid.UUID) -> Message:
        """Fetch a message by ID or raise EntityNotFoundError."""
        msg = await self.get_by_id(organization_id, id)
        if msg is None:
            raise EntityNotFoundError("Message", id)
        return msg

    async def list_by_conversation(
        self,
        organization_id: uuid.UUID,
        conversation_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Message]:
        """List messages in chronological order strictly scoped to organization and conversation."""
        stmt = (
            select(Message)
            .where(
                Message.organization_id == organization_id,
                Message.conversation_id == conversation_id,
            )
            .order_by(Message.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_external_id(
        self,
        organization_id: uuid.UUID,
        external_message_id: str,
    ) -> Message | None:
        """Fetch a message by provider external ID within the organization."""
        stmt = select(Message).where(
            Message.organization_id == organization_id,
            Message.external_message_id == external_message_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_delivery_status(
        self,
        organization_id: uuid.UUID,
        message_id: uuid.UUID,
        delivery_status: DeliveryStatus | str,
        *,
        delivery_metadata: dict | None = None,
    ) -> Message:
        """Update delivery status and merge delivery metadata tracking."""
        msg = await self.get_by_id_or_raise(organization_id, message_id)
        msg.delivery_status = (
            delivery_status.value
            if isinstance(delivery_status, DeliveryStatus)
            else delivery_status
        )
        if delivery_metadata:
            merged = dict(msg.delivery_metadata or {})
            merged.update(delivery_metadata)
            msg.delivery_metadata = merged
        await self.session.flush()
        return msg


class ConsentRepository(TenantRepository[CustomerConsent]):
    """Tenant-scoped repository for CustomerConsent audit records."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CustomerConsent)

    async def get_latest_consent(
        self,
        organization_id: uuid.UUID,
        lead_id: uuid.UUID,
        channel: ChannelType | str,
    ) -> CustomerConsent | None:
        """Fetch the most recent consent record for a lead on a given channel."""
        chan_val = channel.value if isinstance(channel, ChannelType) else channel
        stmt = (
            select(CustomerConsent)
            .where(
                CustomerConsent.organization_id == organization_id,
                CustomerConsent.lead_id == lead_id,
                CustomerConsent.channel == chan_val,
            )
            .order_by(
                CustomerConsent.opt_out_timestamp.desc().nullslast(),
                CustomerConsent.consent_timestamp.desc(),
                CustomerConsent.created_at.desc(),
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class AppointmentRepository(TenantRepository[Appointment]):
    """Tenant-scoped repository for Appointment entities.

    Enforces organization isolation, provides active overlapping window checks,
    and supports hold expiration and cancellations.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Appointment)

    async def get_by_id(self, organization_id: uuid.UUID, id: uuid.UUID) -> Appointment | None:
        """Fetch an appointment strictly scoped to organization."""
        stmt = select(Appointment).where(
            Appointment.organization_id == organization_id,
            Appointment.id == id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_or_raise(self, organization_id: uuid.UUID, id: uuid.UUID) -> Appointment:
        """Fetch an appointment scoped to organization or raise EntityNotFoundError."""
        appt = await self.get_by_id(organization_id, id)
        if appt is None:
            raise EntityNotFoundError("Appointment", id)
        return appt

    async def list_by_lead(
        self,
        organization_id: uuid.UUID,
        lead_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Appointment]:
        """List all appointments for a specific lead ordered by start time descending."""
        stmt = (
            select(Appointment)
            .where(
                Appointment.organization_id == organization_id,
                Appointment.lead_id == lead_id,
            )
            .order_by(Appointment.appointment_start.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list(
        self,
        organization_id: uuid.UUID,
        *,
        status: AppointmentStatus | str | None = None,
        service_id: uuid.UUID | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        lead_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Appointment]:
        """List appointments scoped to organization with optional filtering."""
        stmt = select(Appointment).where(Appointment.organization_id == organization_id)

        if status is not None:
            val = status.value if isinstance(status, AppointmentStatus) else status
            stmt = stmt.where(Appointment.appointment_status == val)
        if service_id is not None:
            stmt = stmt.where(Appointment.service_id == service_id)
        if lead_id is not None:
            stmt = stmt.where(Appointment.lead_id == lead_id)
        if start_time is not None:
            stmt = stmt.where(Appointment.appointment_start >= start_time)
        if end_time is not None:
            stmt = stmt.where(Appointment.appointment_end <= end_time)

        stmt = stmt.order_by(Appointment.appointment_start.asc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(
        self,
        organization_id: uuid.UUID,
        *,
        status: AppointmentStatus | str | None = None,
        service_id: uuid.UUID | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        lead_id: uuid.UUID | None = None,
    ) -> int:
        """Count appointments scoped to organization with matching filters."""
        stmt = (
            select(func.count())
            .select_from(Appointment)
            .where(Appointment.organization_id == organization_id)
        )

        if status is not None:
            val = status.value if isinstance(status, AppointmentStatus) else status
            stmt = stmt.where(Appointment.appointment_status == val)
        if service_id is not None:
            stmt = stmt.where(Appointment.service_id == service_id)
        if lead_id is not None:
            stmt = stmt.where(Appointment.lead_id == lead_id)
        if start_time is not None:
            stmt = stmt.where(Appointment.appointment_start >= start_time)
        if end_time is not None:
            stmt = stmt.where(Appointment.appointment_end <= end_time)

        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def get_overlapping_active(
        self,
        organization_id: uuid.UUID,
        start_time: datetime,
        end_time: datetime,
        *,
        exclude_appointment_id: uuid.UUID | None = None,
    ) -> Sequence[Appointment]:
        """Find active appointments in the organization overlapping [start_time, end_time).

        Active capacity statuses are CONFIRMED and OFFERED.
        Two half-open intervals [s1, e1) and [s2, e2) overlap if s1 < e2 and s2 < e1.
        """
        stmt = select(Appointment).where(
            Appointment.organization_id == organization_id,
            Appointment.appointment_status.in_(
                [
                    AppointmentStatus.CONFIRMED.value,
                    AppointmentStatus.OFFERED.value,
                ]
            ),
            Appointment.appointment_start < end_time,
            Appointment.appointment_end > start_time,
        )
        if exclude_appointment_id is not None:
            stmt = stmt.where(Appointment.id != exclude_appointment_id)
        stmt = stmt.order_by(Appointment.appointment_start.asc())
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def expire_stale_holds(
        self,
        organization_id: uuid.UUID,
        *,
        hold_duration_minutes: int = 15,
        cutoff: datetime | None = None,
    ) -> int:
        """Transition OFFERED holds older than cutoff/hold_duration_minutes to CANCELLED."""
        effective_cutoff = cutoff or (datetime.now(UTC) - timedelta(minutes=hold_duration_minutes))
        stmt = select(Appointment).where(
            Appointment.organization_id == organization_id,
            Appointment.appointment_status == AppointmentStatus.OFFERED.value,
            Appointment.created_at <= effective_cutoff,
        )
        result = await self.session.execute(stmt)
        stale = result.scalars().all()
        for appt in stale:
            appt.appointment_status = AppointmentStatus.CANCELLED.value
            appt.cancellation_reason = f"Offered hold expired after {hold_duration_minutes} minutes"
        if stale:
            await self.session.flush()
        return len(stale)

    async def cancel(
        self,
        organization_id: uuid.UUID,
        appointment_id: uuid.UUID,
        reason: str | None = None,
    ) -> Appointment:
        """Cancel an appointment and free its scheduling capacity."""
        appt = await self.get_by_id_or_raise(organization_id, appointment_id)
        appt.appointment_status = AppointmentStatus.CANCELLED.value
        appt.cancellation_reason = reason
        await self.session.flush()
        return appt


class QualificationRepository(TenantRepository[QualificationResult]):
    """Tenant-scoped repository for QualificationResult evaluation outputs."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, QualificationResult)

    async def get_by_id(
        self, organization_id: uuid.UUID, id: uuid.UUID
    ) -> QualificationResult | None:
        """Fetch a qualification result strictly scoped to organization."""
        stmt = select(QualificationResult).where(
            QualificationResult.organization_id == organization_id,
            QualificationResult.id == id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_or_raise(
        self, organization_id: uuid.UUID, id: uuid.UUID
    ) -> QualificationResult:
        """Fetch a qualification result or raise EntityNotFoundError."""
        res = await self.get_by_id(organization_id, id)
        if res is None:
            raise EntityNotFoundError("QualificationResult", id)
        return res

    async def get_latest_for_lead(
        self, organization_id: uuid.UUID, lead_id: uuid.UUID
    ) -> QualificationResult | None:
        """Fetch the most recent qualification result for a lead."""
        stmt = (
            select(QualificationResult)
            .where(
                QualificationResult.organization_id == organization_id,
                QualificationResult.lead_id == lead_id,
            )
            .order_by(
                QualificationResult.created_at.desc(),
                QualificationResult.id.desc(),
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_lead(
        self,
        organization_id: uuid.UUID,
        lead_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[QualificationResult]:
        """List qualification evaluations for a lead ordered by created_at descending."""
        stmt = (
            select(QualificationResult)
            .where(
                QualificationResult.organization_id == organization_id,
                QualificationResult.lead_id == lead_id,
            )
            .order_by(
                QualificationResult.created_at.desc(),
                QualificationResult.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(
        self,
        organization_id: uuid.UUID,
        lead_id: uuid.UUID | None = None,
    ) -> int:
        """Count qualification results scoped to organization."""
        stmt = (
            select(func.count())
            .select_from(QualificationResult)
            .where(QualificationResult.organization_id == organization_id)
        )
        if lead_id is not None:
            stmt = stmt.where(QualificationResult.lead_id == lead_id)
        result = await self.session.execute(stmt)
        return result.scalar() or 0


class AuditLogRepository(TenantRepository[AuditLog]):
    """Tenant-scoped append-oriented repository for AuditLog immutable audit entries.

    Guarantees:
    - Every retrieval and insertion requires explicit organization_id scoping.
    - Update and delete operations are prohibited at both repository and ORM listener levels.
    - Flushes only; transaction commit ownership belongs to the caller.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AuditLog)

    async def log_event(
        self,
        organization_id: uuid.UUID,
        *,
        action: str,
        resource_type: str,
        resource_id: str,
        user_id: uuid.UUID | None = None,
        changes: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLog:
        """Create and flush an immutable audit log record within the current transaction."""
        changes_dict = dict(changes) if changes is not None else None
        if user_agent is not None:
            if changes_dict is None:
                changes_dict = {}
            if "user_agent" not in changes_dict:
                changes_dict["user_agent"] = user_agent

        entry = AuditLog(
            organization_id=organization_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            changes=changes_dict,
            ip_address=ip_address,
        )
        return await self.add(organization_id, entry)

    async def log_system_event(
        self,
        organization_id: uuid.UUID,
        *,
        action: str,
        resource_type: str,
        resource_id: str,
        changes: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLog:
        """Log an automated system action with user_id=None and SYSTEM_WORKER actor metadata."""
        changes_dict = dict(changes or {})
        if "actor_type" not in changes_dict:
            changes_dict["actor_type"] = "SYSTEM_WORKER"
        return await self.log_event(
            organization_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=None,
            changes=changes_dict,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def list_by_resource(
        self,
        organization_id: uuid.UUID,
        resource_type: str,
        resource_id: str,
    ) -> Sequence[AuditLog]:
        """Fetch audit log records for a specific resource ordered by created_at desc."""
        stmt = (
            select(AuditLog)
            .where(
                AuditLog.organization_id == organization_id,
                AuditLog.resource_type == resource_type,
                AuditLog.resource_id == str(resource_id),
            )
            .order_by(AuditLog.created_at.desc())
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def list_filtered(
        self,
        organization_id: uuid.UUID,
        *,
        action: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        user_id: uuid.UUID | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[AuditLog]:
        """Fetch audit logs matching composable criteria strictly scoped to an organization."""
        stmt = select(AuditLog).where(AuditLog.organization_id == organization_id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if resource_type:
            stmt = stmt.where(AuditLog.resource_type == resource_type)
        if resource_id:
            stmt = stmt.where(AuditLog.resource_id == str(resource_id))
        if user_id:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if start_time:
            stmt = stmt.where(AuditLog.created_at >= start_time)
        if end_time:
            stmt = stmt.where(AuditLog.created_at <= end_time)

        stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def delete(self, organization_id: uuid.UUID, id: uuid.UUID) -> bool:
        """Deletion is prohibited on the immutable AuditLog repository."""
        raise InvalidOperationError(
            "AuditLog records are immutable and cannot be deleted via repository."
        )

    async def delete_entity(self, organization_id: uuid.UUID, entity: AuditLog) -> None:
        """Deletion is prohibited on the immutable AuditLog repository."""
        raise InvalidOperationError(
            "AuditLog records are immutable and cannot be deleted via repository."
        )


class AutomationEventRepository(TenantRepository[AutomationEvent]):
    """Tenant-scoped repository for AutomationEvent outbox records.

    Enforces organization isolation on all event persistence and retrieval.
    Provides methods for idempotency lookups, status filtering, retry eligibility,
    and expired-lease monitoring.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AutomationEvent)

    async def get_by_idempotency_key(
        self,
        organization_id: uuid.UUID,
        idempotency_key: str,
    ) -> AutomationEvent | None:
        """Fetch an event by idempotency key strictly within the specified organization."""
        stmt = select(AutomationEvent).where(
            AutomationEvent.organization_id == organization_id,
            AutomationEvent.idempotency_key == idempotency_key,
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_by_status(
        self,
        organization_id: uuid.UUID,
        status: str | OutboxStatus,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[AutomationEvent]:
        """List events with a specific processing status within the organization."""
        status_val = status.value if isinstance(status, OutboxStatus) else str(status)
        stmt = (
            select(AutomationEvent)
            .where(
                AutomationEvent.organization_id == organization_id,
                AutomationEvent.processing_status == status_val,
            )
            .order_by(AutomationEvent.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def count_by_status(
        self,
        organization_id: uuid.UUID,
        status: str | OutboxStatus,
    ) -> int:
        """Count events with a specific processing status within the organization."""
        status_val = status.value if isinstance(status, OutboxStatus) else str(status)
        stmt = (
            select(func.count())
            .select_from(AutomationEvent)
            .where(
                AutomationEvent.organization_id == organization_id,
                AutomationEvent.processing_status == status_val,
            )
        )
        res = await self.session.execute(stmt)
        return res.scalar() or 0

    async def list_retry_eligible(
        self,
        organization_id: uuid.UUID,
        *,
        now_utc: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[AutomationEvent]:
        """List PENDING and FAILED events whose retry backoff timestamp has elapsed.

        Leverages Index A: idx_outbox_retry_eligible.
        """
        now = now_utc or datetime.now(UTC)
        stmt = (
            select(AutomationEvent)
            .where(
                AutomationEvent.organization_id == organization_id,
                AutomationEvent.processing_status.in_(
                    [
                        OutboxStatus.PENDING.value,
                        OutboxStatus.FAILED.value,
                    ]
                ),
                or_(
                    AutomationEvent.next_retry_at.is_(None),
                    AutomationEvent.next_retry_at <= now,
                ),
            )
            .order_by(
                AutomationEvent.processing_status.asc(),
                AutomationEvent.next_retry_at.asc().nulls_first(),
                AutomationEvent.created_at.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def list_expired_leases(
        self,
        organization_id: uuid.UUID,
        *,
        now_utc: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[AutomationEvent]:
        """List in-flight PROCESSING events whose lease has expired.

        Leverages Index B: idx_outbox_lease_recovery.
        """
        now = now_utc or datetime.now(UTC)
        stmt = (
            select(AutomationEvent)
            .where(
                AutomationEvent.organization_id == organization_id,
                AutomationEvent.processing_status == OutboxStatus.PROCESSING.value,
                AutomationEvent.lease_expires_at.is_not(None),
                AutomationEvent.lease_expires_at <= now,
            )
            .order_by(
                AutomationEvent.lease_expires_at.asc(),
                AutomationEvent.created_at.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()
