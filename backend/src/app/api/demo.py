"""FastAPI routes for synthetic HVAC demo dataset seeding and credentials discovery."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import hash_password
from app.models.appointment import Appointment
from app.models.consent import CustomerConsent
from app.models.conversation import Conversation
from app.models.enums import (
    AppointmentStatus,
    ChannelType,
    ConsentStatus,
    ConversationStatus,
    DeliveryStatus,
    LeadStatus,
    LeadUrgency,
    MessageSender,
    QualificationCategory,
    UserRole,
)
from app.models.lead import Lead
from app.models.membership import OrganizationMembership
from app.models.message import Message
from app.models.organization import Organization
from app.models.qualification import QualificationResult
from app.models.service import Service
from app.models.user import User


def _ensure_demo_enabled() -> None:
    """Reject demo endpoints when running in production configuration."""
    settings = get_settings()
    if settings.ENVIRONMENT.lower() == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo endpoints are disabled in production configuration.",
        )


router = APIRouter(
    prefix="/demo",
    tags=["Demo"],
    dependencies=[Depends(_ensure_demo_enabled)],
)

DEMO_ORG_SLUG = "apex-air"
DEMO_PASSWORD = "Password123!"


@router.get("/info", response_model=dict[str, Any])
async def get_demo_info() -> dict[str, Any]:
    """Retrieve demo accounts, credentials, and test scenario presets."""
    return {
        "organization": {
            "name": "Apex Air Heating & Cooling",
            "slug": DEMO_ORG_SLUG,
            "service_area_zips": ["75001", "75002", "75003", "75004", "75005"],
        },
        "credentials": {
            "owner": {"email": "owner@apexair.com", "password": DEMO_PASSWORD, "role": "owner"},
            "dispatcher": {
                "email": "dispatcher@apexair.com",
                "password": DEMO_PASSWORD,
                "role": "dispatcher",
            },
            "technician": {
                "email": "tech@apexair.com",
                "password": DEMO_PASSWORD,
                "role": "technician",
            },
        },
        "scenarios": [
            {
                "name": "Emergency AC Outage",
                "customer": "Marcus Johnson",
                "phone": "+15550100001",
                "type": "AC blowing warm air, 84F indoor temp",
            },
            {
                "name": "Safety Hazard Lockout",
                "customer": "Sarah Jenkins",
                "phone": "+15550100002",
                "type": "Strong rotten egg odor (Gas leak), safety lock engaged",
            },
            {
                "name": "Booked Maintenance",
                "customer": "David Chen",
                "phone": "+15550100003",
                "type": "Annual Trane AC Tune-up scheduled for tomorrow",
            },
            {
                "name": "Commercial Human Review",
                "customer": "Elena Rodriguez",
                "phone": "+15550100004",
                "type": "4,000 sq ft office rooftop unit replacement",
            },
            {
                "name": "Out of Service Area",
                "customer": "Robert Smith",
                "phone": "+15550100005",
                "type": "Alaska ZIP 99999 (Unqualified Cold)",
            },
            {
                "name": "SMS Consent Revocation",
                "customer": "Amanda Taylor",
                "phone": "+15550100006",
                "type": "Sent STOP keyword, automated messaging locked",
            },
        ],
    }


@router.post("/seed", response_model=dict[str, Any], status_code=status.HTTP_201_CREATED)
async def seed_demo_data(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Seed comprehensive HVAC contractor demo data."""
    # 1. Check if demo organization already exists
    stmt = select(Organization).where(Organization.slug == DEMO_ORG_SLUG)
    existing_org = (await session.execute(stmt)).scalar_one_or_none()

    if existing_org:
        return {
            "status": "already_seeded",
            "message": "Demo organization 'Apex Air Heating & Cooling' is already present.",
            "organization_id": str(existing_org.id),
        }

    # 2. Create Demo Organization
    now = datetime.now(UTC)
    org = Organization(
        name="Apex Air Heating & Cooling",
        slug=DEMO_ORG_SLUG,
        settings={
            "operating_hours": {
                "monday": {"open": "07:30", "close": "18:00"},
                "tuesday": {"open": "07:30", "close": "18:00"},
                "wednesday": {"open": "07:30", "close": "18:00"},
                "thursday": {"open": "07:30", "close": "18:00"},
                "friday": {"open": "07:30", "close": "18:00"},
                "saturday": {"open": "08:00", "close": "16:00"},
                "sunday": {"closed": True},
            },
            "service_area_zips": ["75001", "75002", "75003", "75004", "75005"],
            "safety_escalation_phone": "+15559114822",
            "automation_enabled": True,
        },
    )
    session.add(org)
    await session.flush()

    # 3. Create Users & Memberships
    hashed_pwd = hash_password(DEMO_PASSWORD)
    user_specs = [
        ("owner@apexair.com", "Robert", "Sterling", UserRole.OWNER),
        ("dispatcher@apexair.com", "Jessica", "Vance", UserRole.DISPATCHER),
        ("tech@apexair.com", "Carlos", "Mendez", UserRole.TECHNICIAN),
    ]

    users_map = {}
    for email, first_name, last_name, role in user_specs:
        u_stmt = select(User).where(User.email == email)
        u = (await session.execute(u_stmt)).scalar_one_or_none()
        if not u:
            u = User(
                email=email,
                first_name=first_name,
                last_name=last_name,
                password_hash=hashed_pwd,
                is_active=True,
            )
            session.add(u)
            await session.flush()
        users_map[role] = u

        # Create membership
        mem = OrganizationMembership(
            organization_id=org.id,
            user_id=u.id,
            role=role.value,
        )
        session.add(mem)

    await session.flush()

    # 4. Create Contractor Service Catalog
    services_data = [
        ("Diagnostic Service Call", "DIAG-01", 60, 89.00, False),
        ("Emergency AC Repair", "EMERG-AC", 90, 189.00, True),
        ("Furnace Safety Inspection & Tune-Up", "FURN-TUNE", 60, 129.00, False),
        ("Heat Pump Installation", "HP-INSTALL", 240, 4500.00, False),
        ("Ductwork Sealing & Air Quality", "DUCT-SEAL", 120, 299.00, False),
    ]
    services_map = {}
    for name, code, dur, price, emerg in services_data:
        svc = Service(
            organization_id=org.id,
            service_name=name,
            service_code=code,
            estimated_duration_minutes=dur,
            base_price=price,
            is_emergency_service=emerg,
            active=True,
        )
        session.add(svc)
        await session.flush()
        services_map[code] = svc

    # 5. Seed Leads, Qualifications, Conversations, Messages, and Appointments
    # Lead 1: Emergency AC Outage (Hot Qualified)
    l1 = Lead(
        organization_id=org.id,
        first_name="Marcus",
        last_name="Johnson",
        phone="+15550100001",
        email="marcus.j@example.com",
        street_address="1402 Oak Ridge Dr, Dallas, TX",
        postal_code="75001",
        service_type="Air Conditioning Repair",
        problem_description=(
            "AC stopped cooling entirely. Inside temp is 84 degrees. Outdoor unit buzzing."
        ),
        status=LeadStatus.QUALIFIED.value,
        urgency=LeadUrgency.HIGH.value,
    )
    session.add(l1)
    await session.flush()

    session.add(
        CustomerConsent(
            organization_id=org.id,
            lead_id=l1.id,
            channel=ChannelType.SMS.value,
            consent_status=ConsentStatus.OPTED_IN.value,
            consent_source="WEB_FORM",
            consent_timestamp=now - timedelta(hours=2),
            ip_address="192.168.1.10",
        )
    )
    session.add(
        QualificationResult(
            organization_id=org.id,
            lead_id=l1.id,
            category=QualificationCategory.HOT.value,
            score=92,
            reasoning=(
                "Valid ZIP 75001 in service area. High urgency cooling outage. "
                "Equipment age 8 years."
            ),
            recommended_action="SCHEDULE_APPOINTMENT",
            requires_human=False,
            confidence=0.95,
        )
    )
    c1 = Conversation(
        organization_id=org.id,
        lead_id=l1.id,
        channel=ChannelType.SMS.value,
        status=ConversationStatus.AI_ACTIVE.value,
        last_message_at=now - timedelta(minutes=15),
    )
    session.add(c1)
    await session.flush()

    session.add(
        Message(
            organization_id=org.id,
            conversation_id=c1.id,
            sender=MessageSender.CUSTOMER.value,
            message_content=(
                "Hi, our AC just died and it is 84 degrees in the house with our newborn baby. "
                "Can someone come today?"
            ),
            delivery_status=DeliveryStatus.RECEIVED.value,
            created_at=now - timedelta(minutes=20),
        )
    )
    session.add(
        Message(
            organization_id=org.id,
            conversation_id=c1.id,
            sender=MessageSender.AI_AGENT.value,
            message_content=(
                "Hello Marcus, this is Apex Air. We treat cooling outages with high priority. "
                "We have a technician available in 75001 between 1:00 PM and 3:00 PM today. "
                "Would that work?"
            ),
            delivery_status=DeliveryStatus.DELIVERED.value,
            created_at=now - timedelta(minutes=15),
        )
    )

    # Lead 2: Active Safety Hazard (Gas Leak)
    l2 = Lead(
        organization_id=org.id,
        first_name="Sarah",
        last_name="Jenkins",
        phone="+15550100002",
        email="sjenkins@example.com",
        street_address="782 Maplewood Ave, Plano, TX",
        postal_code="75002",
        service_type="Heating Repair",
        problem_description=(
            "Furnace made a loud pop and we smell strong rotten egg odor near the utility room."
        ),
        status=LeadStatus.CONTACTED.value,
        urgency=LeadUrgency.EMERGENCY.value,
    )
    session.add(l2)
    await session.flush()

    session.add(
        CustomerConsent(
            organization_id=org.id,
            lead_id=l2.id,
            channel=ChannelType.SMS.value,
            consent_status=ConsentStatus.OPTED_IN.value,
            consent_source="WEB_FORM",
            consent_timestamp=now - timedelta(hours=1),
        )
    )
    session.add(
        QualificationResult(
            organization_id=org.id,
            lead_id=l2.id,
            category=QualificationCategory.HUMAN_REVIEW.value,
            score=99,
            reasoning=(
                "EMERGENCY SAFETY HAZARD: Suspected gas leak detected. "
                "Automated routing locked out."
            ),
            recommended_action="ESCALATE_SAFETY",
            requires_human=True,
            confidence=1.0,
        )
    )
    c2 = Conversation(
        organization_id=org.id,
        lead_id=l2.id,
        channel=ChannelType.SMS.value,
        status=ConversationStatus.ESCALATED_SAFETY.value,
        is_automated_reply_locked=True,
        escalation_reason="SAFETY_HAZARD",
        last_message_at=now - timedelta(minutes=5),
    )
    session.add(c2)
    await session.flush()

    session.add(
        Message(
            organization_id=org.id,
            conversation_id=c2.id,
            sender=MessageSender.CUSTOMER.value,
            message_content="Help, I smell a strong gas odor by the heater!",
            delivery_status=DeliveryStatus.RECEIVED.value,
            created_at=now - timedelta(minutes=5),
        )
    )
    session.add(
        Message(
            organization_id=org.id,
            conversation_id=c2.id,
            sender=MessageSender.SYSTEM.value,
            message_content=(
                "SAFETY WARNING: Potential gas leak detected. Evacuate the premises immediately "
                "and dial 911 or your local gas utility. Automated replies locked."
            ),
            delivery_status=DeliveryStatus.DELIVERED.value,
            created_at=now - timedelta(minutes=4),
        )
    )

    # Lead 3: Booked Appointment
    l3 = Lead(
        organization_id=org.id,
        first_name="David",
        last_name="Chen",
        phone="+15550100003",
        email="dchen@example.com",
        street_address="310 Meadow Lane, Frisco, TX",
        postal_code="75003",
        service_type="Maintenance & Tune-Up",
        problem_description="Annual pre-summer AC maintenance tune-up for 2-ton Trane unit.",
        status=LeadStatus.APPOINTMENT_BOOKED.value,
        urgency=LeadUrgency.MEDIUM.value,
    )
    session.add(l3)
    await session.flush()

    session.add(
        CustomerConsent(
            organization_id=org.id,
            lead_id=l3.id,
            channel=ChannelType.SMS.value,
            consent_status=ConsentStatus.OPTED_IN.value,
            consent_source="WEB_FORM",
            consent_timestamp=now - timedelta(days=1),
        )
    )
    session.add(
        QualificationResult(
            organization_id=org.id,
            lead_id=l3.id,
            category=QualificationCategory.WARM.value,
            score=85,
            reasoning="Routine tune-up in active territory. System in working order.",
            recommended_action="SCHEDULE_APPOINTMENT",
            requires_human=False,
            confidence=0.9,
        )
    )
    c3 = Conversation(
        organization_id=org.id,
        lead_id=l3.id,
        channel=ChannelType.SMS.value,
        status=ConversationStatus.COMPLETED.value,
        last_message_at=now - timedelta(hours=4),
    )
    session.add(c3)
    await session.flush()

    appt_start = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    appt_end = appt_start + timedelta(minutes=60)
    session.add(
        Appointment(
            organization_id=org.id,
            lead_id=l3.id,
            service_id=services_map["FURN-TUNE"].id,
            service_type="Furnace Safety Inspection & Tune-Up",
            time_slot=Range(appt_start, appt_end, bounds="[)"),
            appointment_start=appt_start,
            appointment_end=appt_end,
            appointment_status=AppointmentStatus.CONFIRMED.value,
            notes="Customer requested morning arrival; gate code is #4412.",
        )
    )

    # Lead 4: Commercial Unit Human Review
    l4 = Lead(
        organization_id=org.id,
        first_name="Elena",
        last_name="Rodriguez",
        phone="+15550100004",
        email="elena@northdallaslaw.com",
        street_address="5000 Executive Pkwy, Dallas, TX",
        postal_code="75001",
        service_type="Commercial HVAC Replacement",
        problem_description="Rooftop packaged unit replacement for 4,000 sq ft office building.",
        status=LeadStatus.QUALIFIED.value,
        urgency=LeadUrgency.MEDIUM.value,
    )
    session.add(l4)
    await session.flush()

    session.add(
        CustomerConsent(
            organization_id=org.id,
            lead_id=l4.id,
            channel=ChannelType.SMS.value,
            consent_status=ConsentStatus.OPTED_IN.value,
            consent_source="PHONE_VERIFICATION",
            consent_timestamp=now - timedelta(hours=6),
        )
    )
    session.add(
        QualificationResult(
            organization_id=org.id,
            lead_id=l4.id,
            category=QualificationCategory.HUMAN_REVIEW.value,
            score=75,
            reasoning=(
                "Commercial property requires on-site engineering estimate. "
                "Flagged for senior dispatcher."
            ),
            recommended_action="MANUAL_REVIEW",
            requires_human=True,
            confidence=0.85,
        )
    )
    c4 = Conversation(
        organization_id=org.id,
        lead_id=l4.id,
        channel=ChannelType.SMS.value,
        status=ConversationStatus.HUMAN_TAKEOVER.value,
        assigned_to=users_map[UserRole.DISPATCHER].id,
        last_message_at=now - timedelta(hours=2),
    )
    session.add(c4)

    # Lead 5: Unqualified Out of Area
    l5 = Lead(
        organization_id=org.id,
        first_name="Robert",
        last_name="Smith",
        phone="+15550100005",
        email="rsmith@example.com",
        street_address="12 Remote Way, Anchorage, AK",
        postal_code="99999",
        service_type="Window AC Repair",
        problem_description="Window AC repair needed in Alaska.",
        status=LeadStatus.UNQUALIFIED.value,
        urgency=LeadUrgency.LOW.value,
    )
    session.add(l5)
    await session.flush()

    session.add(
        QualificationResult(
            organization_id=org.id,
            lead_id=l5.id,
            category=QualificationCategory.COLD.value,
            score=10,
            reasoning="ZIP 99999 outside contractor service area. Window unit not supported.",
            recommended_action="DISMISS",
            requires_human=False,
            confidence=0.99,
        )
    )

    # Lead 6: Customer Opted Out (STOP)
    l6 = Lead(
        organization_id=org.id,
        first_name="Amanda",
        last_name="Taylor",
        phone="+15550100006",
        email="ataylor@example.com",
        street_address="88 Preston Rd, Dallas, TX",
        postal_code="75001",
        service_type="Smart Thermostat Installation",
        problem_description="Interested in Ecobee thermostat installation.",
        status=LeadStatus.CONTACTED.value,
        urgency=LeadUrgency.LOW.value,
    )
    session.add(l6)
    await session.flush()

    session.add(
        CustomerConsent(
            organization_id=org.id,
            lead_id=l6.id,
            channel=ChannelType.SMS.value,
            consent_status=ConsentStatus.REVOKED.value,
            consent_source="INBOUND_SMS",
            consent_timestamp=now - timedelta(days=2),
            opt_out_timestamp=now - timedelta(hours=3),
            opt_out_keyword="STOP",
        )
    )
    c6 = Conversation(
        organization_id=org.id,
        lead_id=l6.id,
        channel=ChannelType.SMS.value,
        status=ConversationStatus.CLOSED.value,
        last_message_at=now - timedelta(hours=3),
    )
    session.add(c6)
    await session.flush()

    session.add(
        Message(
            organization_id=org.id,
            conversation_id=c6.id,
            sender=MessageSender.CUSTOMER.value,
            message_content="STOP",
            delivery_status=DeliveryStatus.RECEIVED.value,
            created_at=now - timedelta(hours=3),
        )
    )

    # Lead 7: New Unread Inbound
    l7 = Lead(
        organization_id=org.id,
        first_name="Michael",
        last_name="Brown",
        phone="+15550100007",
        email="mbrown@example.com",
        street_address="904 Hillside Dr, Plano, TX",
        postal_code="75002",
        service_type="Heat Pump Repair",
        problem_description=(
            "Heat pump won't turn on and error code E4 is flashing on the thermostat."
        ),
        status=LeadStatus.NEW.value,
        urgency=LeadUrgency.HIGH.value,
    )
    session.add(l7)
    await session.flush()

    c7 = Conversation(
        organization_id=org.id,
        lead_id=l7.id,
        channel=ChannelType.SMS.value,
        status=ConversationStatus.AWAITING_CUSTOMER.value,
        last_message_at=now - timedelta(minutes=10),
    )
    session.add(c7)

    await session.commit()

    return {
        "status": "success",
        "message": "Demo data successfully seeded for Apex Air Heating & Cooling.",
        "organization_id": str(org.id),
        "leads_seeded": 7,
        "users_seeded": 3,
        "services_seeded": 5,
        "credentials": {
            "owner": "owner@apexair.com / Password123!",
            "dispatcher": "dispatcher@apexair.com / Password123!",
            "technician": "tech@apexair.com / Password123!",
        },
    }
