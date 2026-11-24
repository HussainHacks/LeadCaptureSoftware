"""Lead management API endpoints."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_membership, get_db, require_role
from app.core.exceptions import EntityNotFoundError, InvalidOperationError, ValidationError
from app.models.appointment import Appointment
from app.models.conversation import Conversation
from app.models.enums import (
    ChannelType,
    ConsentStatus,
    ConversationStatus,
    LeadSource,
    LeadStatus,
    LeadUrgency,
    QualificationCategory,
    UserRole,
)
from app.models.lead import Lead
from app.models.membership import OrganizationMembership
from app.models.qualification import QualificationResult
from app.schemas.conversation import ConversationCreate
from app.schemas.lead import LeadCreate, LeadRead, LeadUpdate
from app.services.consent_service import ConsentService
from app.services.conversation_service import ConversationService
from app.services.lead_service import LeadService
from app.services.outbox_service import OutboxService
from app.services.qualification_service import QualificationService

router = APIRouter(prefix="/leads", tags=["Leads"])


class LeadSummary(BaseModel):
    """Summary schema for leads list data table."""

    id: uuid.UUID
    first_name: str | None
    last_name: str | None
    customer_name: str
    phone: str
    email: str | None
    postal_code: str | None
    street_address: str | None
    service_type: str | None
    problem_description: str | None
    urgency: str
    status: str
    qualification_category: str | None
    qualification_score: int
    assigned_to: uuid.UUID | None
    assigned_name: str | None
    conversation_id: uuid.UUID | None
    created_at: str
    updated_at: str


class LeadDetail(BaseModel):
    """Comprehensive lead details schema including qualification and active conversation."""

    lead: LeadRead
    qualification: dict[str, Any] | None
    conversation_id: uuid.UUID | None
    conversation_status: str | None
    is_automated_reply_locked: bool
    appointments_count: int


class ManualLeadCreateRequest(BaseModel):
    """Payload for manually creating a lead from dashboard."""

    first_name: str | None = Field(default=None, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)
    phone: str = Field(..., max_length=30)
    email: str | None = Field(default=None, max_length=255)
    postal_code: str | None = Field(default=None, max_length=20)
    street_address: str | None = Field(default=None, max_length=255)
    service_type: str | None = Field(default=None, max_length=80)
    equipment_type: str | None = Field(default=None, max_length=80)
    problem_description: str | None = None
    urgency: LeadUrgency = Field(default=LeadUrgency.MEDIUM)
    source: LeadSource = Field(default=LeadSource.WEBSITE_FORM)
    sms_consent: bool = Field(default=True)


class AssignLeadRequest(BaseModel):
    """Payload for assigning a lead to a team member."""

    assigned_to: uuid.UUID | None = None


class LeadStatusUpdateRequest(BaseModel):
    """Payload for changing lead status."""

    status: LeadStatus


@router.get("", response_model=list[LeadSummary])
async def list_leads(
    status_filter: LeadStatus | None = Query(None, alias="status"),
    urgency_filter: LeadUrgency | None = Query(None, alias="urgency"),
    qualification_filter: QualificationCategory | None = Query(None, alias="qualification"),
    q: str | None = Query(None, description="Search term for name, phone, or email"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    membership: OrganizationMembership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_db),
) -> Any:
    """List and search leads strictly scoped to the active tenant organization."""
    org_id = membership.organization_id

    stmt = (
        select(Lead, Conversation, QualificationResult)
        .outerjoin(
            Conversation,
            (Conversation.lead_id == Lead.id) & (Conversation.organization_id == org_id),
        )
        .outerjoin(
            QualificationResult,
            (QualificationResult.lead_id == Lead.id)
            & (QualificationResult.organization_id == org_id),
        )
        .where(
            Lead.organization_id == org_id,
            Lead.deleted_at.is_(None),
        )
    )

    if status_filter:
        stmt = stmt.where(Lead.status == status_filter.value)
    if urgency_filter:
        stmt = stmt.where(Lead.urgency == urgency_filter.value)
    if q:
        search_pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            (Lead.first_name.ilike(search_pattern))
            | (Lead.last_name.ilike(search_pattern))
            | (Lead.phone.ilike(search_pattern))
            | (Lead.email.ilike(search_pattern))
            | (Lead.problem_description.ilike(search_pattern))
        )

    stmt = stmt.order_by(desc(Lead.created_at)).limit(limit).offset(offset)
    res = await session.execute(stmt)
    rows = res.all()

    results: list[LeadSummary] = []
    seen_lead_ids: set[uuid.UUID] = set()

    for lead, conv, qual in rows:
        if lead.id in seen_lead_ids:
            continue
        seen_lead_ids.add(lead.id)

        # Qualification filter in-memory if joined
        if qualification_filter and (not qual or qual.category != qualification_filter.value):
            continue

        c_name = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or "Unnamed Customer"

        results.append(
            LeadSummary(
                id=lead.id,
                first_name=lead.first_name,
                last_name=lead.last_name,
                customer_name=c_name,
                phone=lead.phone,
                email=lead.email,
                postal_code=lead.postal_code,
                street_address=lead.street_address,
                service_type=lead.service_type,
                problem_description=lead.problem_description,
                urgency=lead.urgency,
                status=lead.status,
                qualification_category=qual.category if qual else None,
                qualification_score=lead.qualification_score,
                assigned_to=conv.assigned_to if conv else None,
                assigned_name=None,
                conversation_id=conv.id if conv else None,
                created_at=lead.created_at.isoformat(),
                updated_at=lead.updated_at.isoformat(),
            )
        )

    return results


@router.post("", response_model=LeadSummary, status_code=status.HTTP_201_CREATED)
async def create_manual_lead(
    payload: ManualLeadCreateRequest,
    membership: OrganizationMembership = Depends(
        require_role([UserRole.OWNER, UserRole.ADMIN, UserRole.DISPATCHER])
    ),
    session: AsyncSession = Depends(get_db),
) -> Any:
    """Create a new customer lead, initialize conversation thread, and qualify."""
    org_id = membership.organization_id
    lead_service = LeadService(session, org_id)
    conv_service = ConversationService(session, org_id)
    qual_service = QualificationService(session, org_id)
    outbox_service = OutboxService(session)

    try:
        sms_consent = ConsentStatus.OPTED_IN if payload.sms_consent else ConsentStatus.OPTED_OUT
        lead = await lead_service.create_lead(
            LeadCreate(
                organization_id=org_id,
                first_name=payload.first_name,
                last_name=payload.last_name,
                phone=payload.phone,
                email=payload.email,
                postal_code=payload.postal_code,
                street_address=payload.street_address,
                service_type=payload.service_type,
                equipment_type=payload.equipment_type,
                problem_description=payload.problem_description,
                urgency=payload.urgency,
                source=payload.source,
                sms_consent_status=sms_consent,
                email_consent_status=ConsentStatus.PENDING,
            )
        )

        # Record explicit CustomerConsent row for SMS channel
        consent_service = ConsentService(session, org_id)
        await consent_service.record_consent(
            lead.id,
            ChannelType.SMS,
            consent_source="MANUAL_DASHBOARD_ENTRY",
            consent_status=sms_consent,
        )

        # Ensure conversation exists
        stmt = select(Conversation).where(
            Conversation.organization_id == org_id,
            Conversation.lead_id == lead.id,
        )
        res = await session.execute(stmt)
        conv = res.scalar_one_or_none()

        if not conv:
            conv = await conv_service.create_conversation(
                ConversationCreate(
                    organization_id=org_id,
                    lead_id=lead.id,
                    channel=ChannelType.SMS,
                    status=ConversationStatus.AI_ACTIVE,
                )
            )

        # Run initial deterministic qualification
        qual = await qual_service.evaluate_lead(lead.id)

        # Emit outbox event
        await outbox_service.publish_event(
            organization_id=org_id,
            event_type="LEAD_CREATED",
            payload={
                "lead_id": str(lead.id),
                "customer_phone": lead.phone,
                "urgency": lead.urgency,
                "qualification_category": qual.category,
                "source": lead.source,
            },
        )

        await session.commit()
        await session.refresh(lead)
        if conv:
            await session.refresh(conv)
        await session.refresh(qual)
    except (ValidationError, InvalidOperationError) as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create lead: {e}")

    c_name = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or "Unnamed Customer"
    return LeadSummary(
        id=lead.id,
        first_name=lead.first_name,
        last_name=lead.last_name,
        customer_name=c_name,
        phone=lead.phone,
        email=lead.email,
        postal_code=lead.postal_code,
        street_address=lead.street_address,
        service_type=lead.service_type,
        problem_description=lead.problem_description,
        urgency=lead.urgency,
        status=lead.status,
        qualification_category=qual.category,
        qualification_score=lead.qualification_score,
        assigned_to=conv.assigned_to if conv else None,
        assigned_name=None,
        conversation_id=conv.id if conv else None,
        created_at=lead.created_at.isoformat(),
        updated_at=lead.updated_at.isoformat(),
    )


@router.get("/{lead_id}", response_model=LeadDetail)
async def get_lead_details(
    lead_id: uuid.UUID,
    membership: OrganizationMembership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_db),
) -> Any:
    """Retrieve full details for a lead, including qualification and conversation state."""
    org_id = membership.organization_id
    lead_service = LeadService(session, org_id)

    lead = await lead_service.get_lead(lead_id)

    # Fetch conversation
    stmt_conv = select(Conversation).where(
        Conversation.organization_id == org_id,
        Conversation.lead_id == lead_id,
    )
    res_conv = await session.execute(stmt_conv)
    conv = res_conv.scalar_one_or_none()

    # Fetch latest qualification
    stmt_qual = (
        select(QualificationResult)
        .where(
            QualificationResult.organization_id == org_id,
            QualificationResult.lead_id == lead_id,
        )
        .order_by(desc(QualificationResult.created_at))
    )
    res_qual = await session.execute(stmt_qual)
    qual = res_qual.scalar_one_or_none()

    qual_dict: dict[str, Any] | None = None
    if qual:
        qual_dict = {
            "id": str(qual.id),
            "category": qual.category,
            "score": qual.score,
            "reasoning": qual.reasoning,
            "collected_information": qual.collected_information,
            "missing_information": qual.missing_information,
            "recommended_action": qual.recommended_action,
            "requires_human": qual.requires_human,
            "confidence": qual.confidence,
            "created_at": qual.created_at.isoformat(),
        }

    stmt_appts = select(func.count(Appointment.id)).where(
        Appointment.organization_id == org_id,
        Appointment.lead_id == lead_id,
    )
    appointments_count = (await session.execute(stmt_appts)).scalar() or 0

    return LeadDetail(
        lead=LeadRead.model_validate(lead),
        qualification=qual_dict,
        conversation_id=conv.id if conv else None,
        conversation_status=conv.status if conv else None,
        is_automated_reply_locked=conv.is_automated_reply_locked if conv else False,
        appointments_count=appointments_count,
    )


@router.post("/{lead_id}/qualify", response_model=dict[str, Any])
async def qualify_lead(
    lead_id: uuid.UUID,
    membership: OrganizationMembership = Depends(
        require_role([UserRole.OWNER, UserRole.ADMIN, UserRole.DISPATCHER])
    ),
    session: AsyncSession = Depends(get_db),
) -> Any:
    """Run deterministic qualification evaluation on a lead and persist result."""
    org_id = membership.organization_id
    qual_service = QualificationService(session, org_id)

    try:
        qual = await qual_service.evaluate_lead(lead_id)
        await session.commit()
        await session.refresh(qual)
        return {
            "id": str(qual.id),
            "lead_id": str(qual.lead_id),
            "category": qual.category,
            "score": qual.score,
            "reasoning": qual.reasoning,
            "recommended_action": qual.recommended_action,
            "requires_human": qual.requires_human,
            "confidence": qual.confidence,
            "created_at": qual.created_at.isoformat(),
        }
    except EntityNotFoundError as e:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(e))
    except (ValidationError, InvalidOperationError) as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{lead_id}", response_model=LeadRead)
async def update_lead(
    lead_id: uuid.UUID,
    payload: LeadUpdate,
    membership: OrganizationMembership = Depends(
        require_role([UserRole.OWNER, UserRole.ADMIN, UserRole.DISPATCHER])
    ),
    session: AsyncSession = Depends(get_db),
) -> Any:
    """Update contact and service details of an active lead."""
    org_id = membership.organization_id
    lead_service = LeadService(session, org_id)

    try:
        updated_lead = await lead_service.update_lead(lead_id, payload)
        await session.commit()
        await session.refresh(updated_lead)
        return LeadRead.model_validate(updated_lead)
    except (ValidationError, InvalidOperationError, EntityNotFoundError) as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{lead_id}/status", response_model=LeadRead)
async def update_lead_status(
    lead_id: uuid.UUID,
    payload: LeadStatusUpdateRequest,
    membership: OrganizationMembership = Depends(
        require_role([UserRole.OWNER, UserRole.ADMIN, UserRole.DISPATCHER])
    ),
    session: AsyncSession = Depends(get_db),
) -> Any:
    """Transition a lead's lifecycle status following authorized state transitions."""
    org_id = membership.organization_id
    lead_service = LeadService(session, org_id)

    try:
        lead = await lead_service.transition_status(lead_id, payload.status)
        await session.commit()
        await session.refresh(lead)
        return LeadRead.model_validate(lead)
    except (InvalidOperationError, EntityNotFoundError) as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(
    lead_id: uuid.UUID,
    membership: OrganizationMembership = Depends(
        require_role([UserRole.OWNER, UserRole.ADMIN, UserRole.DISPATCHER])
    ),
    session: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete/archive a lead."""
    org_id = membership.organization_id
    lead_service = LeadService(session, org_id)

    try:
        await lead_service.soft_delete_lead(lead_id)
        await session.commit()
    except EntityNotFoundError as e:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(e))
