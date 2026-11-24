"""FastAPI routes for real-time dashboard KPIs, safety alerts, and activity feed."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_membership
from app.core.database import get_db
from app.models.appointment import Appointment
from app.models.conversation import Conversation
from app.models.enums import AppointmentStatus, ConversationStatus, LeadStatus, LeadUrgency
from app.models.lead import Lead
from app.models.membership import OrganizationMembership
from app.models.service import Service

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("", response_model=dict[str, Any])
async def get_dashboard_data(
    membership: Annotated[OrganizationMembership, Depends(get_current_membership)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Retrieve real-time contractor dashboard metrics, safety alerts, and recent activities."""
    org_id = membership.organization_id

    # 1. Total leads count
    leads_count_stmt = select(func.count(Lead.id)).where(
        Lead.organization_id == org_id,
        Lead.deleted_at.is_(None),
    )
    total_leads = (await session.execute(leads_count_stmt)).scalar() or 0

    # 2. Leads by status
    new_leads_stmt = select(func.count(Lead.id)).where(
        Lead.organization_id == org_id,
        Lead.status == LeadStatus.NEW.value,
        Lead.deleted_at.is_(None),
    )
    new_leads = (await session.execute(new_leads_stmt)).scalar() or 0

    qualified_leads_stmt = select(func.count(Lead.id)).where(
        Lead.organization_id == org_id,
        Lead.status.in_(
            [
                LeadStatus.QUALIFIED.value,
                LeadStatus.APPOINTMENT_OFFERED.value,
                LeadStatus.APPOINTMENT_BOOKED.value,
            ]
        ),
        Lead.deleted_at.is_(None),
    )
    qualified_leads = (await session.execute(qualified_leads_stmt)).scalar() or 0

    emergency_leads_stmt = select(func.count(Lead.id)).where(
        Lead.organization_id == org_id,
        Lead.urgency == LeadUrgency.EMERGENCY.value,
        Lead.deleted_at.is_(None),
    )
    emergency_leads_count = (await session.execute(emergency_leads_stmt)).scalar() or 0

    # 3. Active conversations
    active_conv_stmt = select(func.count(Conversation.id)).where(
        Conversation.organization_id == org_id,
        Conversation.status.in_(
            [
                ConversationStatus.AI_ACTIVE.value,
                ConversationStatus.AWAITING_CUSTOMER.value,
                ConversationStatus.HUMAN_TAKEOVER.value,
            ]
        ),
    )
    active_conversations_count = (await session.execute(active_conv_stmt)).scalar() or 0

    # 4. Total and confirmed appointments
    confirmed_appt_stmt = select(func.count(Appointment.id)).where(
        Appointment.organization_id == org_id,
        Appointment.appointment_status == AppointmentStatus.CONFIRMED.value,
    )
    confirmed_appointments_count = (await session.execute(confirmed_appt_stmt)).scalar() or 0

    # Conversion rate
    conversion_rate = 0.0
    if total_leads > 0:
        conversion_rate = round((confirmed_appointments_count / total_leads) * 100, 1)

    # 5. Critical Safety Alerts (locked automated replies or ESCALATED_SAFETY)
    safety_alerts_stmt = (
        select(Conversation, Lead)
        .join(Lead, Conversation.lead_id == Lead.id)
        .where(
            Conversation.organization_id == org_id,
            (Conversation.is_automated_reply_locked.is_(True))
            | (Conversation.status == ConversationStatus.ESCALATED_SAFETY.value),
        )
        .order_by(Conversation.updated_at.desc())
        .limit(10)
    )
    safety_rows = (await session.execute(safety_alerts_stmt)).all()
    safety_alerts = [
        {
            "conversation_id": str(conv.id),
            "lead_id": str(lead.id),
            "customer_name": f"{lead.first_name} {lead.last_name}",
            "phone": lead.phone,
            "escalation_reason": conv.escalation_reason or "Safety Hazard Alert",
            "is_automated_reply_locked": conv.is_automated_reply_locked,
            "problem_description": lead.problem_description,
            "detected_at": conv.updated_at.isoformat() if conv.updated_at else None,
        }
        for conv, lead in safety_rows
    ]

    # 6. Recent leads (latest 5)
    recent_leads_stmt = (
        select(Lead)
        .where(Lead.organization_id == org_id, Lead.deleted_at.is_(None))
        .order_by(Lead.created_at.desc())
        .limit(5)
    )
    recent_leads_rows = (await session.execute(recent_leads_stmt)).scalars().all()
    recent_leads = [
        {
            "id": str(row.id),
            "first_name": row.first_name,
            "last_name": row.last_name,
            "phone": row.phone,
            "postal_code": row.postal_code,
            "street_address": row.street_address,
            "status": row.status,
            "urgency": row.urgency,
            "service_type": row.service_type,
            "created_at": row.created_at.isoformat(),
        }
        for row in recent_leads_rows
    ]

    # 7. Upcoming appointments (next 5)
    upcoming_appt_stmt = (
        select(Appointment, Lead, Service)
        .join(Lead, Appointment.lead_id == Lead.id)
        .outerjoin(Service, Appointment.service_id == Service.id)
        .where(
            Appointment.organization_id == org_id,
            Appointment.appointment_status == AppointmentStatus.CONFIRMED.value,
        )
        .order_by(Appointment.appointment_start.asc())
        .limit(5)
    )
    upcoming_rows = (await session.execute(upcoming_appt_stmt)).all()
    upcoming_appointments = [
        {
            "id": str(appt.id),
            "customer_name": f"{lead.first_name} {lead.last_name}",
            "phone": lead.phone,
            "service_name": svc.service_name if svc else appt.service_type,
            "start": appt.appointment_start.isoformat(),
            "end": appt.appointment_end.isoformat(),
            "status": appt.appointment_status,
        }
        for appt, lead, svc in upcoming_rows
    ]

    return {
        "kpis": {
            "total_leads": total_leads,
            "new_leads": new_leads,
            "qualified_leads": qualified_leads,
            "emergency_leads": emergency_leads_count,
            "active_conversations": active_conversations_count,
            "confirmed_appointments": confirmed_appointments_count,
            "conversion_rate_percent": conversion_rate,
        },
        "safety_alerts": safety_alerts,
        "recent_leads": recent_leads,
        "upcoming_appointments": upcoming_appointments,
    }
