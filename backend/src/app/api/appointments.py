"""FastAPI routes for appointment scheduling, rescheduling, and cancellation."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_membership, require_role
from app.core.database import get_db
from app.core.exceptions import (
    EntityNotFoundError,
    InvalidOperationError,
    ValidationError,
)
from app.models.enums import AppointmentStatus, AutomationEventType, UserRole
from app.models.membership import OrganizationMembership
from app.repositories.entities import LeadRepository, ServiceRepository
from app.schemas.appointment import AppointmentRead
from app.services.appointment_service import AppointmentService
from app.services.outbox_service import OutboxService

router = APIRouter(prefix="/appointments", tags=["Appointments"])


class AppointmentBookRequest(BaseModel):
    lead_id: uuid.UUID
    service_id: uuid.UUID | None = None
    service_type: str = Field(..., min_length=1, max_length=100)
    appointment_start: datetime
    appointment_end: datetime
    appointment_status: AppointmentStatus = Field(default=AppointmentStatus.CONFIRMED)
    notes: str | None = Field(default=None, max_length=2000)


class RescheduleRequest(BaseModel):
    new_start_time: datetime
    new_end_time: datetime
    reason: str | None = None
    notes: str | None = None


class CancelRequest(BaseModel):
    cancellation_reason: str | None = Field(default=None, max_length=500)


@router.get("", response_model=list[dict[str, Any]])
async def list_appointments(
    membership: Annotated[OrganizationMembership, Depends(get_current_membership)],
    session: Annotated[AsyncSession, Depends(get_db)],
    status: AppointmentStatus | None = Query(default=None),
    lead_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """List appointments for the active organization."""
    service = AppointmentService(session, membership.organization_id)
    lead_repo = LeadRepository(session)
    service_repo = ServiceRepository(session)

    appointments = await service.list_appointments(
        status=status,
        lead_id=lead_id,
        limit=limit,
        offset=offset,
    )

    results = []
    for appt in appointments:
        lead = await lead_repo.get_by_id(membership.organization_id, appt.lead_id)
        svc = (
            await service_repo.get_by_id(membership.organization_id, appt.service_id)
            if appt.service_id
            else None
        )

        results.append(
            {
                "id": str(appt.id),
                "organization_id": str(appt.organization_id),
                "lead_id": str(appt.lead_id),
                "service_id": str(appt.service_id) if appt.service_id else None,
                "service_name": svc.service_name if svc else appt.service_type,
                "service_type": appt.service_type,
                "appointment_start": appt.appointment_start.isoformat(),
                "appointment_end": appt.appointment_end.isoformat(),
                "appointment_status": appt.appointment_status,
                "notes": appt.notes,
                "cancellation_reason": appt.cancellation_reason,
                "created_at": appt.created_at.isoformat(),
                "lead": (
                    {
                        "id": str(lead.id),
                        "first_name": lead.first_name,
                        "last_name": lead.last_name,
                        "phone": lead.phone,
                        "email": lead.email,
                        "street_address": lead.street_address,
                        "postal_code": lead.postal_code,
                    }
                    if lead
                    else None
                ),
            }
        )

    return results


@router.get("/{appointment_id}", response_model=dict[str, Any])
async def get_appointment(
    appointment_id: uuid.UUID,
    membership: Annotated[OrganizationMembership, Depends(get_current_membership)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Get appointment details by ID."""
    service = AppointmentService(session, membership.organization_id)
    lead_repo = LeadRepository(session)
    service_repo = ServiceRepository(session)

    try:
        appt = await service.get_appointment(appointment_id)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    lead = await lead_repo.get_by_id(membership.organization_id, appt.lead_id)
    svc = (
        await service_repo.get_by_id(membership.organization_id, appt.service_id)
        if appt.service_id
        else None
    )

    return {
        "id": str(appt.id),
        "organization_id": str(appt.organization_id),
        "lead_id": str(appt.lead_id),
        "service_id": str(appt.service_id) if appt.service_id else None,
        "service_name": svc.service_name if svc else appt.service_type,
        "service_type": appt.service_type,
        "appointment_start": appt.appointment_start.isoformat(),
        "appointment_end": appt.appointment_end.isoformat(),
        "appointment_status": appt.appointment_status,
        "notes": appt.notes,
        "cancellation_reason": appt.cancellation_reason,
        "created_at": appt.created_at.isoformat(),
        "lead": (
            {
                "id": str(lead.id),
                "first_name": lead.first_name,
                "last_name": lead.last_name,
                "phone": lead.phone,
                "email": lead.email,
                "street_address": lead.street_address,
                "postal_code": lead.postal_code,
            }
            if lead
            else None
        ),
    }


@router.post("", response_model=AppointmentRead, status_code=status.HTTP_201_CREATED)
async def create_appointment(
    data: AppointmentBookRequest,
    membership: Annotated[
        OrganizationMembership,
        Depends(require_role([UserRole.OWNER, UserRole.ADMIN, UserRole.DISPATCHER])),
    ],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AppointmentRead:
    """Schedule a new appointment for a qualified lead."""
    service = AppointmentService(session, membership.organization_id)
    outbox_service = OutboxService(session, membership.organization_id)

    try:
        appt = await service.schedule_appointment(
            lead_id=data.lead_id,
            appointment_start=data.appointment_start,
            appointment_end=data.appointment_end,
            service_type=data.service_type,
            service_id=data.service_id,
            status=data.appointment_status,
            notes=data.notes,
        )

        # Publish APPOINTMENT_SCHEDULED outbox event
        await outbox_service.publish_event(
            event_type=AutomationEventType.APPOINTMENT_SCHEDULED,
            aggregate_id=appt.id,
            aggregate_type="Appointment",
            payload={
                "appointment_id": str(appt.id),
                "lead_id": str(appt.lead_id),
                "start": appt.appointment_start.isoformat(),
                "end": appt.appointment_end.isoformat(),
                "service_type": appt.service_type,
            },
        )

        await session.commit()
        await session.refresh(appt)
        return AppointmentRead.model_validate(appt)
    except (ValidationError, InvalidOperationError) as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except EntityNotFoundError as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/{appointment_id}/reschedule", response_model=AppointmentRead)
async def reschedule_appointment(
    appointment_id: uuid.UUID,
    data: RescheduleRequest,
    membership: Annotated[
        OrganizationMembership,
        Depends(require_role([UserRole.OWNER, UserRole.ADMIN, UserRole.DISPATCHER])),
    ],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AppointmentRead:
    """Reschedule an existing appointment to a new time window."""
    service = AppointmentService(session, membership.organization_id)
    outbox_service = OutboxService(session, membership.organization_id)

    try:
        appt = await service.reschedule_appointment(
            appointment_id,
            new_start_time=data.new_start_time,
            new_end_time=data.new_end_time,
            reason=data.reason,
            notes=data.notes,
        )

        # Publish APPOINTMENT_RESCHEDULED outbox event
        await outbox_service.publish_event(
            event_type=AutomationEventType.APPOINTMENT_RESCHEDULED,
            aggregate_id=appt.id,
            aggregate_type="Appointment",
            payload={
                "appointment_id": str(appt.id),
                "lead_id": str(appt.lead_id),
                "new_start": appt.appointment_start.isoformat(),
                "new_end": appt.appointment_end.isoformat(),
                "reason": data.reason,
            },
        )

        await session.commit()
        await session.refresh(appt)
        return AppointmentRead.model_validate(appt)
    except (ValidationError, InvalidOperationError) as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except EntityNotFoundError as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/{appointment_id}/cancel", response_model=AppointmentRead)
async def cancel_appointment(
    appointment_id: uuid.UUID,
    data: CancelRequest,
    membership: Annotated[
        OrganizationMembership,
        Depends(require_role([UserRole.OWNER, UserRole.ADMIN, UserRole.DISPATCHER])),
    ],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AppointmentRead:
    """Cancel an appointment, releasing capacity."""
    service = AppointmentService(session, membership.organization_id)
    outbox_service = OutboxService(session, membership.organization_id)

    try:
        appt = await service.cancel_appointment(
            appointment_id,
            reason=data.cancellation_reason,
        )

        # Publish APPOINTMENT_CANCELLED outbox event
        await outbox_service.publish_event(
            event_type=AutomationEventType.APPOINTMENT_CANCELLED,
            aggregate_id=appt.id,
            aggregate_type="Appointment",
            payload={
                "appointment_id": str(appt.id),
                "lead_id": str(appt.lead_id),
                "reason": data.cancellation_reason,
            },
        )

        await session.commit()
        await session.refresh(appt)
        return AppointmentRead.model_validate(appt)
    except (ValidationError, InvalidOperationError) as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except EntityNotFoundError as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
