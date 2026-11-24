"""Tenant-scoped service managing appointment scheduling, capacity, and rescheduling."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    EntityNotFoundError,
    InvalidOperationError,
    ValidationError,
)
from app.models.appointment import Appointment
from app.models.enums import (
    AppointmentStatus,
    ConversationStatus,
    LeadStatus,
    QualificationCategory,
)
from app.models.organization import Organization
from app.repositories.entities import (
    AppointmentRepository,
    ConversationRepository,
    LeadRepository,
    OrganizationRepository,
    QualificationRepository,
    ServiceRepository,
)
from app.schemas.appointment import AppointmentCreate
from app.services.base import TenantService


class AppointmentService(TenantService):
    """Tenant-scoped service managing appointment booking and contractor capacity."""

    def __init__(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        appointment_repo: AppointmentRepository | None = None,
        lead_repo: LeadRepository | None = None,
        service_repo: ServiceRepository | None = None,
        org_repo: OrganizationRepository | None = None,
        qualification_repo: QualificationRepository | None = None,
        conversation_repo: ConversationRepository | None = None,
    ) -> None:
        super().__init__(session, organization_id)
        self.appointment_repo = appointment_repo or AppointmentRepository(session)
        self.lead_repo = lead_repo or LeadRepository(session)
        self.service_repo = service_repo or ServiceRepository(session)
        self.org_repo = org_repo or OrganizationRepository(session)
        self.qualification_repo = qualification_repo or QualificationRepository(session)
        self.conversation_repo = conversation_repo or ConversationRepository(session)

    async def schedule_appointment(
        self,
        *,
        lead_id: uuid.UUID,
        appointment_start: datetime,
        appointment_end: datetime,
        service_type: str,
        service_id: uuid.UUID | None = None,
        status: AppointmentStatus | str = AppointmentStatus.CONFIRMED,
        notes: str | None = None,
    ) -> Appointment:
        """Schedule an appointment for a lead, enforcing capacity and constraints.

        Validates lead state, active contractor service, ensures start < end,
        expires stale holds, verifies capacity, and translates exclusion constraint
        conflicts to clean domain errors.
        """
        # Ensure timezone awareness
        if appointment_start.tzinfo is None or appointment_start.utcoffset() is None:
            raise ValidationError("appointment_start must be a timezone-aware datetime.")
        if appointment_end.tzinfo is None or appointment_end.utcoffset() is None:
            raise ValidationError("appointment_end must be a timezone-aware datetime.")

        if appointment_end <= appointment_start:
            raise ValidationError("appointment_end must be strictly after appointment_start.")

        # Validate lead
        lead = await self.lead_repo.get_by_id(self.organization_id, lead_id)
        if lead is None or lead.deleted_at is not None:
            raise EntityNotFoundError("Lead", lead_id)

        # Enforce that lead must have an appropriate qualified status before scheduling
        if lead.status not in (
            LeadStatus.QUALIFIED.value,
            LeadStatus.APPOINTMENT_OFFERED.value,
            LeadStatus.APPOINTMENT_BOOKED.value,
        ):
            raise InvalidOperationError(
                f"Cannot schedule an appointment for lead with status '{lead.status}'. "
                "Lead must be qualified before scheduling."
            )

        # Check latest qualification result
        latest_qual = await self.qualification_repo.get_latest_for_lead(
            self.organization_id, lead_id
        )
        if latest_qual is not None:
            if (
                latest_qual.requires_human
                or latest_qual.category == QualificationCategory.HUMAN_REVIEW.value
            ):
                raise InvalidOperationError(
                    "Cannot schedule an appointment for a lead requiring human review "
                    "or safety escalation."
                )
            if latest_qual.category == QualificationCategory.COLD.value:
                raise InvalidOperationError(
                    "Cannot schedule an appointment for an unqualified lead."
                )

        # Check for active safety escalations or conversation locks
        convs = await self.conversation_repo.list_by_lead(self.organization_id, lead_id)
        for conv in convs:
            if (
                conv.status == ConversationStatus.ESCALATED_SAFETY.value
                or conv.is_automated_reply_locked
            ):
                raise InvalidOperationError(
                    "Cannot schedule an appointment for a lead with an active safety escalation "
                    "or conversation lock."
                )

        # Validate service if provided
        if service_id is not None:
            service = await self.service_repo.get_by_id(self.organization_id, service_id)
            if service is None:
                raise EntityNotFoundError("Service", service_id)
            if not service.active:
                raise InvalidOperationError(
                    f"Service '{service.service_name}' is inactive and cannot be scheduled."
                )

        target_status = status.value if isinstance(status, AppointmentStatus) else status
        if target_status not in (
            AppointmentStatus.CONFIRMED.value,
            AppointmentStatus.OFFERED.value,
        ):
            raise ValidationError(
                f"New appointments can only be created in CONFIRMED or OFFERED status, "
                f"got '{target_status}'."
            )

        # Expire stale holds (> 15 minutes) before checking capacity
        await self.appointment_repo.expire_stale_holds(self.organization_id)

        # Pre-check for overlapping active appointments
        conflicts = await self.appointment_repo.get_overlapping_active(
            self.organization_id,
            appointment_start,
            appointment_end,
        )
        if conflicts:
            raise InvalidOperationError(
                "The requested appointment slot overlaps with an existing booking."
            )

        # Lock the organization row for serialized concurrency (Section 6.1)
        await self.session.execute(
            select(Organization.id).where(Organization.id == self.organization_id).with_for_update()
        )

        # Construct appointment entity with TSTZRANGE
        appointment = Appointment(
            organization_id=self.organization_id,
            lead_id=lead_id,
            service_id=service_id,
            time_slot=Range(appointment_start, appointment_end, bounds="[)"),
            appointment_start=appointment_start,
            appointment_end=appointment_end,
            appointment_status=target_status,
            service_type=service_type.strip(),
            notes=notes.strip() if notes else None,
        )

        try:
            async with self.session.begin_nested():
                await self.appointment_repo.add(self.organization_id, appointment)
        except IntegrityError as exc:
            orig_msg = str(getattr(exc, "orig", exc)).lower()
            if "uq_contractor_no_double_booking" in orig_msg or "exclusion" in orig_msg:
                raise InvalidOperationError(
                    "The requested appointment slot overlaps with an existing booking."
                ) from exc
            raise

        # Update lead lifecycle status if appropriate
        if lead.status in (
            LeadStatus.QUALIFIED.value,
            LeadStatus.APPOINTMENT_OFFERED.value,
            LeadStatus.QUALIFYING.value,
            LeadStatus.NEW.value,
            LeadStatus.CONTACTED.value,
        ):
            if target_status == AppointmentStatus.CONFIRMED.value:
                lead.status = LeadStatus.APPOINTMENT_BOOKED.value
            elif target_status == AppointmentStatus.OFFERED.value:
                lead.status = LeadStatus.APPOINTMENT_OFFERED.value
            await self.flush()

        return appointment

    async def create_appointment(self, data: AppointmentCreate) -> Appointment:
        """Create an appointment from a validated AppointmentCreate schema."""
        self.validate_tenant_scope(data.organization_id)
        return await self.schedule_appointment(
            lead_id=data.lead_id,
            service_id=data.service_id,
            appointment_start=data.appointment_start,
            appointment_end=data.appointment_end,
            service_type=data.service_type,
            status=data.appointment_status,
            notes=data.notes,
        )

    async def get_appointment(self, appointment_id: uuid.UUID) -> Appointment:
        """Fetch an appointment strictly scoped to the organization."""
        return await self.appointment_repo.get_by_id_or_raise(self.organization_id, appointment_id)

    async def list_appointments(
        self,
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
        return await self.appointment_repo.list(
            self.organization_id,
            status=status,
            service_id=service_id,
            start_time=start_time,
            end_time=end_time,
            lead_id=lead_id,
            limit=limit,
            offset=offset,
        )

    async def count_appointments(
        self,
        *,
        status: AppointmentStatus | str | None = None,
        service_id: uuid.UUID | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        lead_id: uuid.UUID | None = None,
    ) -> int:
        """Count appointments scoped to organization with matching filters."""
        return await self.appointment_repo.count(
            self.organization_id,
            status=status,
            service_id=service_id,
            start_time=start_time,
            end_time=end_time,
            lead_id=lead_id,
        )

    async def cancel_appointment(
        self,
        appointment_id: uuid.UUID,
        reason: str | None = None,
    ) -> Appointment:
        """Cancel an appointment with an optional cancellation reason, releasing capacity."""
        appt = await self.get_appointment(appointment_id)
        if appt.appointment_status == AppointmentStatus.CANCELLED.value:
            raise InvalidOperationError("Appointment is already cancelled.")

        return await self.appointment_repo.cancel(
            self.organization_id,
            appointment_id,
            reason=reason,
        )

    async def reschedule_appointment(
        self,
        appointment_id: uuid.UUID,
        new_start_time: datetime,
        new_end_time: datetime,
        *,
        notes: str | None = None,
        reason: str | None = None,
    ) -> Appointment:
        """Transaction-safely reschedule an appointment to a new time window.

        Does not modify or cancel the original appointment until the replacement
        booking is successfully validated and scheduled.
        """
        original = await self.get_appointment(appointment_id)

        if original.appointment_status not in (
            AppointmentStatus.CONFIRMED.value,
            AppointmentStatus.OFFERED.value,
        ):
            raise InvalidOperationError(
                f"Cannot reschedule an appointment with status '{original.appointment_status}'."
            )

        # Retrieve the appointment's lead using tenant-scoped repository access
        lead = await self.lead_repo.get_by_id(self.organization_id, original.lead_id)
        if lead is None or lead.deleted_at is not None:
            raise EntityNotFoundError("Lead", original.lead_id)

        if lead.status in (
            LeadStatus.UNQUALIFIED.value,
            LeadStatus.LOST.value,
            LeadStatus.ARCHIVED.value,
            LeadStatus.QUALIFYING.value,
        ):
            raise InvalidOperationError(
                f"Cannot reschedule an appointment for lead with status '{lead.status}'."
            )

        # Check latest qualification result
        latest_qual = await self.qualification_repo.get_latest_for_lead(
            self.organization_id, original.lead_id
        )
        if latest_qual is not None and (
            latest_qual.requires_human
            or latest_qual.category == QualificationCategory.HUMAN_REVIEW.value
        ):
            raise InvalidOperationError(
                "Cannot reschedule an appointment for a lead requiring human review "
                "or safety escalation."
            )

        # Check for active safety escalations or conversation locks
        convs = await self.conversation_repo.list_by_lead(self.organization_id, original.lead_id)
        for conv in convs:
            if (
                conv.status == ConversationStatus.ESCALATED_SAFETY.value
                or conv.is_automated_reply_locked
            ):
                raise InvalidOperationError(
                    "Cannot reschedule an appointment for a lead with an active safety escalation "
                    "or conversation lock."
                )

        if new_start_time.tzinfo is None or new_start_time.utcoffset() is None:
            raise ValidationError("new_start_time must be a timezone-aware datetime.")
        if new_end_time.tzinfo is None or new_end_time.utcoffset() is None:
            raise ValidationError("new_end_time must be a timezone-aware datetime.")

        if new_end_time <= new_start_time:
            raise ValidationError("new_end_time must be strictly after new_start_time.")

        # Expire stale holds before checking capacity
        await self.appointment_repo.expire_stale_holds(self.organization_id)

        # Pre-check for conflicting active bookings (excluding the original appointment)
        conflicts = await self.appointment_repo.get_overlapping_active(
            self.organization_id,
            new_start_time,
            new_end_time,
            exclude_appointment_id=original.id,
        )
        if conflicts:
            raise InvalidOperationError(
                "The requested appointment slot overlaps with an existing booking."
            )

        # Lock the organization row for serialized concurrency
        await self.session.execute(
            select(Organization.id).where(Organization.id == self.organization_id).with_for_update()
        )

        # Atomic transaction-safe rescheduling using a nested savepoint
        try:
            async with self.session.begin_nested():
                # 1. Mark original as RESCHEDULED to free the old slot's capacity
                original.appointment_status = AppointmentStatus.RESCHEDULED.value
                original.cancellation_reason = (
                    reason or f"Rescheduled to {new_start_time.isoformat()}"
                )
                await self.flush()

                # 2. Create the replacement appointment in the new slot
                replacement = Appointment(
                    organization_id=self.organization_id,
                    lead_id=original.lead_id,
                    service_id=original.service_id,
                    service_type=original.service_type,
                    appointment_start=new_start_time,
                    appointment_end=new_end_time,
                    time_slot=Range(new_start_time, new_end_time, bounds="[)"),
                    appointment_status=AppointmentStatus.CONFIRMED.value,
                    notes=notes or original.notes,
                )
                await self.appointment_repo.add(self.organization_id, replacement)
        except (IntegrityError, Exception) as exc:
            if isinstance(exc, IntegrityError):
                orig_msg = str(getattr(exc, "orig", exc)).lower()
                if "uq_contractor_no_double_booking" in orig_msg or "exclusion" in orig_msg:
                    raise InvalidOperationError(
                        "The requested appointment slot overlaps with an existing booking."
                    ) from exc
            raise

        return replacement
