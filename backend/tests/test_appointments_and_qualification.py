"""Comprehensive tests for services, appointments, capacity, and lead qualification."""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.auth_context import ActorContext
from app.core.config import get_settings
from app.core.exceptions import (
    EntityAlreadyExistsError,
    EntityNotFoundError,
    InvalidOperationError,
    ValidationError,
)
from app.models import Appointment, Base
from app.models.enums import (
    AppointmentStatus,
    ChannelType,
    ConsentStatus,
    ConversationStatus,
    LeadSource,
    LeadStatus,
    LeadUrgency,
    QualificationCategory,
    UserRole,
)
from app.repositories import AuditLogRepository
from app.schemas.appointment import AppointmentCreate, AppointmentUpdate
from app.schemas.conversation import ConversationCreate
from app.schemas.lead import LeadCreate, LeadUpdate
from app.schemas.organization import OrganizationCreate
from app.schemas.service import ServiceCreate, ServiceUpdate
from app.schemas.user import UserCreate
from app.services import (
    AppointmentService,
    ConversationService,
    LeadService,
    MembershipService,
    OrganizationService,
    QualificationService,
    ServiceService,
    UserService,
)

TEST_DB_NAME = "leadgen_test_appt_qual_db"


@pytest_asyncio.fixture(loop_scope="module", scope="module", autouse=True)
async def setup_test_db():
    """Create an isolated test database, enable btree_gist, and build schema."""
    settings = get_settings()
    base_url = settings.DATABASE_URL.rsplit("/", 1)[0]
    admin_url = f"{base_url}/postgres"

    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE);"))
        await conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME};"))
    await admin_engine.dispose()

    test_db_url = f"{base_url}/{TEST_DB_NAME}"
    test_engine = create_async_engine(test_db_url, poolclass=NullPool)

    async with test_engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist;"))
        await conn.run_sync(Base.metadata.create_all)

    await test_engine.dispose()

    yield

    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE);"))
    await admin_engine.dispose()


@pytest_asyncio.fixture(loop_scope="function", scope="function")
async def session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a transactional test session with an event-loop-safe NullPool engine."""
    settings = get_settings()
    base_url = settings.DATABASE_URL.rsplit("/", 1)[0]
    test_db_url = f"{base_url}/{TEST_DB_NAME}"

    engine = create_async_engine(test_db_url, poolclass=NullPool)
    session_maker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_maker() as session:
        yield session
        await session.rollback()

    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="function", scope="function")
async def seed_env(session: AsyncSession):
    """Seed base organizations and services for testing."""
    user_svc = UserService(session)
    org_svc = OrganizationService(session)

    u1 = await user_svc.register_user(
        UserCreate(
            email=f"owner1_{uuid.uuid4().hex[:6]}@example.com",
            password="SecurePassword123!",
            first_name="Alice",
            last_name="Owner",
        )
    )
    u2 = await user_svc.register_user(
        UserCreate(
            email=f"owner2_{uuid.uuid4().hex[:6]}@example.com",
            password="SecurePassword123!",
            first_name="Bob",
            last_name="Owner",
        )
    )

    org1, _ = await org_svc.create_organization(
        u1.id,
        OrganizationCreate(name="Apex Air LLC", slug=f"apex-air-{uuid.uuid4().hex[:6]}"),
    )
    org2, _ = await org_svc.create_organization(
        u2.id,
        OrganizationCreate(name="Breeze Heating", slug=f"breeze-heat-{uuid.uuid4().hex[:6]}"),
    )

    # Seed services for Org 1
    svc_service1 = ServiceService(session, org1.id)
    s1 = await svc_service1.create_service(
        ServiceCreate(
            organization_id=org1.id,
            service_name="AC Diagnostic & Repair",
            service_code="AC-DIAG-01",
            description="Comprehensive air conditioning diagnostic and repair.",
            estimated_duration_minutes=90,
            base_price=Decimal("129.00"),
            is_emergency_service=False,
            active=True,
        )
    )
    s2 = await svc_service1.create_service(
        ServiceCreate(
            organization_id=org1.id,
            service_name="Furnace Safety Inspection",
            service_code="FURNACE-INSP-01",
            description="Detailed furnace diagnostic and heating safety inspection.",
            estimated_duration_minutes=60,
            base_price=Decimal("99.00"),
            is_emergency_service=False,
            active=True,
        )
    )
    s3 = await svc_service1.create_service(
        ServiceCreate(
            organization_id=org1.id,
            service_name="Emergency HVAC Dispatch",
            service_code="EMERG-DISPATCH",
            description="Immediate emergency field response.",
            estimated_duration_minutes=120,
            base_price=Decimal("249.00"),
            is_emergency_service=True,
            active=True,
        )
    )

    # Seed services for Org 2
    svc_service2 = ServiceService(session, org2.id)
    s2_org2 = await svc_service2.create_service(
        ServiceCreate(
            organization_id=org2.id,
            service_name="Heat Pump Tune-up",
            service_code="HP-TUNE-01",
            description="Heat pump maintenance service.",
            estimated_duration_minutes=60,
            base_price=Decimal("89.00"),
            active=True,
        )
    )

    # Seed leads for Org 1
    lead_svc1 = LeadService(session, org1.id)
    l1 = await lead_svc1.create_lead(
        LeadCreate(
            organization_id=org1.id,
            first_name="Jane",
            last_name="Doe",
            phone="+15551234567",
            email="jane.doe@example.com",
            postal_code="75001",
            street_address="123 Main St",
            service_type="AC Diagnostic & Repair",
            equipment_type="Central AC",
            problem_description="AC unit is blowing warm air on hot afternoon.",
            urgency=LeadUrgency.HIGH,
            source=LeadSource.WEBSITE_FORM,
            sms_consent_status=ConsentStatus.OPTED_IN,
        )
    )
    # Qualify lead 1
    qual_svc1 = QualificationService(session, org1.id)
    await qual_svc1.evaluate_lead(l1.id)
    await lead_svc1.change_status(l1.id, LeadStatus.QUALIFIED)

    # Lead 2 for Org 1 (new)
    l2 = await lead_svc1.create_lead(
        LeadCreate(
            organization_id=org1.id,
            first_name="Charlie",
            last_name="Brown",
            phone="+15557654321",
            postal_code="75002",
            service_type="Furnace Safety Inspection",
            problem_description="Furnace making a rattling noise when cycling on.",
            urgency=LeadUrgency.MEDIUM,
            sms_consent_status=ConsentStatus.OPTED_IN,
        )
    )

    # Lead for Org 2
    lead_svc2 = LeadService(session, org2.id)
    qual_svc2 = QualificationService(session, org2.id)
    l_org2 = await lead_svc2.create_lead(
        LeadCreate(
            organization_id=org2.id,
            first_name="Dave",
            last_name="Miller",
            phone="+15559998888",
            postal_code="75003",
            service_type="Heat Pump Tune-up",
            problem_description="Heat pump routine maintenance.",
            urgency=LeadUrgency.LOW,
            sms_consent_status=ConsentStatus.OPTED_IN,
        )
    )
    await qual_svc2.evaluate_lead(l_org2.id)
    await lead_svc2.change_status(l_org2.id, LeadStatus.QUALIFIED)

    return {
        "u1": u1,
        "u2": u2,
        "org1": org1,
        "org2": org2,
        "s1": s1,
        "s2": s2,
        "s3": s3,
        "s2_org2": s2_org2,
        "l1": l1,
        "l2": l2,
        "l_org2": l_org2,
    }


# ============================================================================
# 1. SERVICE CATALOG TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_service_creation_and_retrieval(session: AsyncSession, seed_env: dict):
    """Verify contractor service creation, property defaults, and scoped retrieval."""
    org1 = seed_env["org1"]
    svc_service = ServiceService(session, org1.id)

    svc = await svc_service.create_service(
        ServiceCreate(
            organization_id=org1.id,
            service_name="Duct Cleaning",
            service_code="DUCT-CLEAN-01",
            description="Whole-home air duct sanitization.",
            estimated_duration_minutes=180,
            base_price=Decimal("350.00"),
            is_emergency_service=False,
            active=True,
        )
    )

    assert svc.id is not None
    assert svc.service_name == "Duct Cleaning"
    assert svc.service_code == "DUCT-CLEAN-01"
    assert svc.estimated_duration_minutes == 180
    assert svc.base_price == Decimal("350.00")
    assert svc.active is True

    # Retrieve by ID
    fetched = await svc_service.get_service(svc.id)
    assert fetched.id == svc.id
    assert fetched.service_code == "DUCT-CLEAN-01"


@pytest.mark.asyncio
async def test_service_duplicate_code_rejection_per_org(session: AsyncSession, seed_env: dict):
    """Verify unique constraint on (organization_id, service_code)."""
    org1 = seed_env["org1"]
    org2 = seed_env["org2"]
    svc_service1 = ServiceService(session, org1.id)
    svc_service2 = ServiceService(session, org2.id)

    # Org 1 cannot create duplicate code AC-DIAG-01
    with pytest.raises(EntityAlreadyExistsError) as exc_info:
        await svc_service1.create_service(
            ServiceCreate(
                organization_id=org1.id,
                service_name="Duplicate AC Service",
                service_code="AC-DIAG-01",  # Already exists in Org 1
            )
        )
    assert "AC-DIAG-01" in str(exc_info.value)

    # Org 2 CAN create AC-DIAG-01 (multi-tenant isolated)
    s_org2 = await svc_service2.create_service(
        ServiceCreate(
            organization_id=org2.id,
            service_name="Org 2 AC Service",
            service_code="AC-DIAG-01",
        )
    )
    assert s_org2.id is not None
    assert s_org2.organization_id == org2.id


@pytest.mark.asyncio
async def test_service_list_and_active_filtering(session: AsyncSession, seed_env: dict):
    """Verify listing services with active-only filtering and counts."""
    org1 = seed_env["org1"]
    svc_service = ServiceService(session, org1.id)

    # Deactivate one service
    s2 = seed_env["s2"]
    await svc_service.deactivate_service(s2.id)

    # List all services
    all_services = await svc_service.list_services(active_only=False)
    assert len(all_services) >= 3

    # List active only
    active_services = await svc_service.list_services(active_only=True)
    active_codes = {s.service_code for s in active_services}
    assert s2.service_code not in active_codes
    assert "AC-DIAG-01" in active_codes

    # Count matching
    active_count = await svc_service.count_services(active_only=True)
    assert active_count == len(active_services)


@pytest.mark.asyncio
async def test_service_update_and_activation(session: AsyncSession, seed_env: dict):
    """Verify updating service attributes, name, price, duration, and status."""
    org1 = seed_env["org1"]
    s1 = seed_env["s1"]
    svc_service = ServiceService(session, org1.id)

    updated = await svc_service.update_service(
        s1.id,
        ServiceUpdate(
            service_name="AC Diagnostic Premium",
            base_price=Decimal("149.00"),
            estimated_duration_minutes=105,
        ),
    )
    assert updated.service_name == "AC Diagnostic Premium"
    assert updated.base_price == Decimal("149.00")
    assert updated.estimated_duration_minutes == 105

    # Deactivate then activate
    await svc_service.deactivate_service(s1.id)
    fetched = await svc_service.get_service(s1.id)
    assert fetched.active is False

    await svc_service.activate_service(s1.id)
    fetched2 = await svc_service.get_service(s1.id)
    assert fetched2.active is True


@pytest.mark.asyncio
async def test_service_cross_tenant_isolation(session: AsyncSession, seed_env: dict):
    """Verify that Org 1 cannot access, update, or delete Org 2's service."""
    org1 = seed_env["org1"]
    s2_org2 = seed_env["s2_org2"]
    svc_service1 = ServiceService(session, org1.id)

    with pytest.raises(EntityNotFoundError):
        await svc_service1.get_service(s2_org2.id)

    with pytest.raises(EntityNotFoundError):
        await svc_service1.update_service(
            s2_org2.id,
            ServiceUpdate(service_name="Hacked Name"),
        )


# ============================================================================
# 2. APPOINTMENT SCHEDULING & CAPACITY TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_appointment_scheduling_confirmed(session: AsyncSession, seed_env: dict):
    """Verify successful appointment booking for a qualified lead in CONFIRMED status."""
    org1 = seed_env["org1"]
    l1 = seed_env["l1"]
    s1 = seed_env["s1"]
    appt_service = AppointmentService(session, org1.id)

    t_start = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)
    t_end = datetime(2026, 12, 1, 10, 30, tzinfo=UTC)

    appt = await appt_service.schedule_appointment(
        lead_id=l1.id,
        service_id=s1.id,
        appointment_start=t_start,
        appointment_end=t_end,
        service_type=s1.service_name,
        status=AppointmentStatus.CONFIRMED,
        notes="Gate code #1234. Dog in backyard.",
    )

    assert appt.id is not None
    assert appt.organization_id == org1.id
    assert appt.lead_id == l1.id
    assert appt.service_id == s1.id
    assert appt.appointment_status == AppointmentStatus.CONFIRMED.value
    assert appt.notes == "Gate code #1234. Dog in backyard."

    # Lead should be transitioned to APPOINTMENT_BOOKED
    lead_svc = LeadService(session, org1.id)
    updated_lead = await lead_svc.get_lead(l1.id)
    assert updated_lead.status == LeadStatus.APPOINTMENT_BOOKED.value


@pytest.mark.asyncio
async def test_appointment_rejects_overlapping_booking_same_org(
    session: AsyncSession, seed_env: dict
):
    """Verify contractor capacity = 1: overlapping booking in same org is rejected."""
    org1 = seed_env["org1"]
    org2 = seed_env["org2"]
    l1 = seed_env["l1"]
    s1 = seed_env["s1"]
    l_org2 = seed_env["l_org2"]
    s2_org2 = seed_env["s2_org2"]

    appt_service1 = AppointmentService(session, org1.id)
    appt_service2 = AppointmentService(session, org2.id)

    # 1. Book Org 1 slot: 10:00 to 12:00
    t_start1 = datetime(2026, 12, 2, 10, 0, tzinfo=UTC)
    t_end1 = datetime(2026, 12, 2, 12, 0, tzinfo=UTC)
    await appt_service1.schedule_appointment(
        lead_id=l1.id,
        service_id=s1.id,
        appointment_start=t_start1,
        appointment_end=t_end1,
        service_type=s1.service_name,
    )

    # 2. Attempt overlapping booking in Org 1: 11:00 to 13:00 -> REJECTED
    t_start2 = datetime(2026, 12, 2, 11, 0, tzinfo=UTC)
    t_end2 = datetime(2026, 12, 2, 13, 0, tzinfo=UTC)

    with pytest.raises(InvalidOperationError) as exc_info:
        await appt_service1.schedule_appointment(
            lead_id=l1.id,
            service_id=s1.id,
            appointment_start=t_start2,
            appointment_end=t_end2,
            service_type=s1.service_name,
        )
    assert "overlaps with an existing booking" in str(exc_info.value)

    # 3. Same overlapping slot in Org 2 is ALLOWED (tenant isolated capacity)
    appt_org2 = await appt_service2.schedule_appointment(
        lead_id=l_org2.id,
        service_id=s2_org2.id,
        appointment_start=t_start2,
        appointment_end=t_end2,
        service_type=s2_org2.service_name,
    )
    assert appt_org2.id is not None
    assert appt_org2.organization_id == org2.id


@pytest.mark.asyncio
async def test_appointment_cancellation_releases_capacity(session: AsyncSession, seed_env: dict):
    """Verify that cancelling an appointment immediately frees capacity for new bookings."""
    org1 = seed_env["org1"]
    l1 = seed_env["l1"]
    s1 = seed_env["s1"]
    appt_service = AppointmentService(session, org1.id)

    t_start = datetime(2026, 12, 3, 14, 0, tzinfo=UTC)
    t_end = datetime(2026, 12, 3, 16, 0, tzinfo=UTC)

    # Book slot
    appt1 = await appt_service.schedule_appointment(
        lead_id=l1.id,
        service_id=s1.id,
        appointment_start=t_start,
        appointment_end=t_end,
        service_type=s1.service_name,
    )

    # Cancel appointment
    cancelled = await appt_service.cancel_appointment(
        appt1.id,
        reason="Customer requested cancellation.",
    )
    assert cancelled.appointment_status == AppointmentStatus.CANCELLED.value
    assert cancelled.cancellation_reason == "Customer requested cancellation."

    # Cannot cancel again
    with pytest.raises(InvalidOperationError):
        await appt_service.cancel_appointment(appt1.id)

    # Exact same slot can now be booked by another lead immediately
    l2 = seed_env["l2"]
    # Qualify l2 first
    lead_svc = LeadService(session, org1.id)
    qual_svc = QualificationService(session, org1.id)
    await qual_svc.evaluate_lead(l2.id)
    await lead_svc.change_status(l2.id, LeadStatus.QUALIFIED)

    appt2 = await appt_service.schedule_appointment(
        lead_id=l2.id,
        service_id=s1.id,
        appointment_start=t_start,
        appointment_end=t_end,
        service_type=s1.service_name,
    )
    assert appt2.id is not None
    assert appt2.appointment_status == AppointmentStatus.CONFIRMED.value


@pytest.mark.asyncio
async def test_appointment_offered_hold_and_15min_expiration(session: AsyncSession, seed_env: dict):
    """Verify OFFERED holds consume capacity while active, and release capacity after 15 min."""
    org1 = seed_env["org1"]
    l1 = seed_env["l1"]
    l2 = seed_env["l2"]
    s1 = seed_env["s1"]
    appt_service = AppointmentService(session, org1.id)
    lead_svc = LeadService(session, org1.id)
    qual_svc = QualificationService(session, org1.id)
    await qual_svc.evaluate_lead(l2.id)
    await lead_svc.change_status(l2.id, LeadStatus.QUALIFIED)

    t_start = datetime(2026, 12, 4, 10, 0, tzinfo=UTC)
    t_end = datetime(2026, 12, 4, 11, 0, tzinfo=UTC)

    # 1. Create an OFFERED hold for l1
    offered_appt = await appt_service.schedule_appointment(
        lead_id=l1.id,
        service_id=s1.id,
        appointment_start=t_start,
        appointment_end=t_end,
        service_type=s1.service_name,
        status=AppointmentStatus.OFFERED,
    )
    assert offered_appt.appointment_status == AppointmentStatus.OFFERED.value

    # 2. While hold is fresh, competing booking is rejected
    with pytest.raises(InvalidOperationError):
        await appt_service.schedule_appointment(
            lead_id=l2.id,
            service_id=s1.id,
            appointment_start=t_start,
            appointment_end=t_end,
            service_type=s1.service_name,
        )

    # 3. Simulate hold expiration by shifting created_at to 16 minutes in the past
    past_time = datetime.now(UTC) - timedelta(minutes=16)
    offered_appt.created_at = past_time
    await session.flush()

    # 4. Now booking for l2 should automatically expire the hold and succeed
    appt_new = await appt_service.schedule_appointment(
        lead_id=l2.id,
        service_id=s1.id,
        appointment_start=t_start,
        appointment_end=t_end,
        service_type=s1.service_name,
    )
    assert appt_new.id is not None
    assert appt_new.appointment_status == AppointmentStatus.CONFIRMED.value

    # Verify old offered hold status is now CANCELLED
    fetched_old = await appt_service.get_appointment(offered_appt.id)
    assert fetched_old.appointment_status == AppointmentStatus.CANCELLED.value


@pytest.mark.asyncio
async def test_appointment_rescheduling_transaction_safe(session: AsyncSession, seed_env: dict):
    """Verify transaction-safe rescheduling: success creates replacement and frees old slot."""
    org1 = seed_env["org1"]
    l1 = seed_env["l1"]
    s1 = seed_env["s1"]
    appt_service = AppointmentService(session, org1.id)

    # Original booking: Dec 5, 9:00 - 10:00
    slot1_start = datetime(2026, 12, 5, 9, 0, tzinfo=UTC)
    slot1_end = datetime(2026, 12, 5, 10, 0, tzinfo=UTC)
    original = await appt_service.schedule_appointment(
        lead_id=l1.id,
        service_id=s1.id,
        appointment_start=slot1_start,
        appointment_end=slot1_end,
        service_type=s1.service_name,
    )

    # Reschedule to Dec 5, 14:00 - 15:00
    slot2_start = datetime(2026, 12, 5, 14, 0, tzinfo=UTC)
    slot2_end = datetime(2026, 12, 5, 15, 0, tzinfo=UTC)

    replacement = await appt_service.reschedule_appointment(
        original.id,
        new_start_time=slot2_start,
        new_end_time=slot2_end,
        reason="Customer requested afternoon window.",
    )

    assert replacement.id != original.id
    assert replacement.appointment_status == AppointmentStatus.CONFIRMED.value
    assert replacement.appointment_start == slot2_start
    assert replacement.appointment_end == slot2_end

    # Verify original appointment is marked RESCHEDULED
    fetched_orig = await appt_service.get_appointment(original.id)
    assert fetched_orig.appointment_status == AppointmentStatus.RESCHEDULED.value
    assert "Customer requested afternoon window" in (fetched_orig.cancellation_reason or "")

    # Slot 1 is now free and can be booked by someone else
    l2 = seed_env["l2"]
    lead_svc = LeadService(session, org1.id)
    qual_svc = QualificationService(session, org1.id)
    await qual_svc.evaluate_lead(l2.id)
    await lead_svc.change_status(l2.id, LeadStatus.QUALIFIED)

    slot1_rebooked = await appt_service.schedule_appointment(
        lead_id=l2.id,
        service_id=s1.id,
        appointment_start=slot1_start,
        appointment_end=slot1_end,
        service_type=s1.service_name,
    )
    assert slot1_rebooked.id is not None
    assert slot1_rebooked.appointment_status == AppointmentStatus.CONFIRMED.value


@pytest.mark.asyncio
async def test_appointment_rescheduling_conflict_preserves_original(
    session: AsyncSession, seed_env: dict
):
    """Verify failed reschedule (slot conflict) rolls back and preserves original appointment."""
    org1 = seed_env["org1"]
    l1 = seed_env["l1"]
    l2 = seed_env["l2"]
    s1 = seed_env["s1"]
    appt_service = AppointmentService(session, org1.id)
    lead_svc = LeadService(session, org1.id)
    qual_svc = QualificationService(session, org1.id)
    await qual_svc.evaluate_lead(l2.id)
    await lead_svc.change_status(l2.id, LeadStatus.QUALIFIED)

    # Appt 1: Dec 6, 9:00 - 10:00
    slot1_start = datetime(2026, 12, 6, 9, 0, tzinfo=UTC)
    slot1_end = datetime(2026, 12, 6, 10, 0, tzinfo=UTC)
    appt1 = await appt_service.schedule_appointment(
        lead_id=l1.id,
        service_id=s1.id,
        appointment_start=slot1_start,
        appointment_end=slot1_end,
        service_type=s1.service_name,
    )

    # Appt 2: Dec 6, 11:00 - 12:00
    slot2_start = datetime(2026, 12, 6, 11, 0, tzinfo=UTC)
    slot2_end = datetime(2026, 12, 6, 12, 0, tzinfo=UTC)
    await appt_service.schedule_appointment(
        lead_id=l2.id,
        service_id=s1.id,
        appointment_start=slot2_start,
        appointment_end=slot2_end,
        service_type=s1.service_name,
    )

    # Attempt to reschedule Appt 1 into slot 2 (which is occupied by Appt 2) -> REJECTED
    with pytest.raises(InvalidOperationError) as exc_info:
        await appt_service.reschedule_appointment(
            appt1.id,
            new_start_time=slot2_start,
            new_end_time=slot2_end,
        )
    assert "overlaps with an existing booking" in str(exc_info.value)

    # Verify Appt 1 is completely untouched: remains CONFIRMED in slot 1
    original_check = await appt_service.get_appointment(appt1.id)
    assert original_check.appointment_status == AppointmentStatus.CONFIRMED.value
    assert original_check.appointment_start == slot1_start
    assert original_check.appointment_end == slot1_end


@pytest.mark.asyncio
async def test_appointment_scheduling_validations(session: AsyncSession, seed_env: dict):
    """Verify input validation: invalid duration, inactive service, unqualified lead."""
    org1 = seed_env["org1"]
    l1 = seed_env["l1"]
    s1 = seed_env["s1"]
    appt_service = AppointmentService(session, org1.id)
    svc_service = ServiceService(session, org1.id)
    lead_svc = LeadService(session, org1.id)

    # 1. Invalid time range (end <= start)
    t_start = datetime(2026, 12, 7, 10, 0, tzinfo=UTC)
    t_end = datetime(2026, 12, 7, 9, 0, tzinfo=UTC)
    with pytest.raises(ValidationError):
        await appt_service.schedule_appointment(
            lead_id=l1.id,
            service_id=s1.id,
            appointment_start=t_start,
            appointment_end=t_end,
            service_type=s1.service_name,
        )

    # 2. Inactive service rejected
    await svc_service.deactivate_service(s1.id)
    with pytest.raises(InvalidOperationError) as exc_info:
        await appt_service.schedule_appointment(
            lead_id=l1.id,
            service_id=s1.id,
            appointment_start=datetime(2026, 12, 7, 10, 0, tzinfo=UTC),
            appointment_end=datetime(2026, 12, 7, 11, 0, tzinfo=UTC),
            service_type=s1.service_name,
        )
    assert "is inactive" in str(exc_info.value)
    await svc_service.activate_service(s1.id)

    # 3. Unqualified lead rejected
    unqual_lead = await lead_svc.create_lead(
        LeadCreate(
            organization_id=org1.id,
            first_name="Reject",
            last_name="Me",
            phone="+15550001111",
            problem_description="Out of area.",
        )
    )
    await lead_svc.change_status(unqual_lead.id, LeadStatus.UNQUALIFIED)

    with pytest.raises(InvalidOperationError) as exc_info:
        await appt_service.schedule_appointment(
            lead_id=unqual_lead.id,
            service_id=s1.id,
            appointment_start=datetime(2026, 12, 7, 10, 0, tzinfo=UTC),
            appointment_end=datetime(2026, 12, 7, 11, 0, tzinfo=UTC),
            service_type=s1.service_name,
        )
    assert "status 'UNQUALIFIED'" in str(exc_info.value)


# ============================================================================
# 3. LEAD QUALIFICATION TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_qualification_deterministic_hot_lead(session: AsyncSession, seed_env: dict):
    """Verify HOT lead evaluation: supported service, urgency, complete details."""
    org1 = seed_env["org1"]
    lead_svc = LeadService(session, org1.id)
    qual_svc = QualificationService(session, org1.id)

    lead = await lead_svc.create_lead(
        LeadCreate(
            organization_id=org1.id,
            first_name="Marcus",
            last_name="Vance",
            phone="+15553334444",
            email="marcus@example.com",
            postal_code="75001",
            street_address="456 Elm Court",
            service_type="AC Diagnostic & Repair",
            equipment_type="Central AC Carrier 4-ton",
            problem_description="AC compressor stopped spinning; house temperature is 84 degrees.",
            urgency=LeadUrgency.HIGH,
            sms_consent_status=ConsentStatus.OPTED_IN,
        )
    )

    result = await qual_svc.evaluate_lead(lead.id)

    assert result.category == QualificationCategory.HOT.value
    assert result.score >= 75
    assert result.recommended_action == "OFFER_APPOINTMENT_SLOTS"
    assert result.requires_human is False
    assert result.missing_information == []

    # Lead should be updated
    fetched_lead = await lead_svc.get_lead(lead.id)
    assert fetched_lead.qualification_score == result.score
    assert fetched_lead.status == LeadStatus.QUALIFIED.value


@pytest.mark.asyncio
async def test_qualification_deterministic_warm_lead(session: AsyncSession, seed_env: dict):
    """Verify WARM lead evaluation: flexible urgency, seasonal maintenance request."""
    org1 = seed_env["org1"]
    lead_svc = LeadService(session, org1.id)
    qual_svc = QualificationService(session, org1.id)

    lead = await lead_svc.create_lead(
        LeadCreate(
            organization_id=org1.id,
            first_name="Eleanor",
            last_name="Rigby",
            phone="+15555556666",
            postal_code="75001",
            street_address="789 Abbey Road",
            service_type="Furnace Safety Inspection",
            equipment_type="Gas Furnace",
            problem_description="Annual pre-winter furnace inspection and filter replacement.",
            urgency=LeadUrgency.LOW,
            sms_consent_status=ConsentStatus.PENDING,
        )
    )

    result = await qual_svc.evaluate_lead(lead.id)

    assert result.category == QualificationCategory.WARM.value
    assert result.score >= 50
    assert result.recommended_action == "NURTURE_OR_SCHEDULE"
    assert result.requires_human is False

    # Lead should be updated to QUALIFIED
    fetched_lead = await lead_svc.get_lead(lead.id)
    assert fetched_lead.status == LeadStatus.QUALIFIED.value


@pytest.mark.asyncio
async def test_qualification_deterministic_cold_lead_unsupported_service(
    session: AsyncSession, seed_env: dict
):
    """Verify COLD evaluation: requested trade is unsupported by contractor."""
    org1 = seed_env["org1"]
    lead_svc = LeadService(session, org1.id)
    qual_svc = QualificationService(session, org1.id)

    lead = await lead_svc.create_lead(
        LeadCreate(
            organization_id=org1.id,
            first_name="Victor",
            last_name="Stone",
            phone="+15557778888",
            postal_code="75001",
            service_type="Roof Repair",
            problem_description="Need complete commercial roofing inspection and shingle repair.",
            urgency=LeadUrgency.MEDIUM,
            sms_consent_status=ConsentStatus.PENDING,
        )
    )

    result = await qual_svc.evaluate_lead(lead.id)

    assert result.category == QualificationCategory.COLD.value
    assert result.recommended_action == "DECLINE_UNSUPPORTED_SERVICE"
    assert result.requires_human is False

    # Lead should be updated to UNQUALIFIED
    fetched_lead = await lead_svc.get_lead(lead.id)
    assert fetched_lead.status == LeadStatus.UNQUALIFIED.value


@pytest.mark.asyncio
async def test_qualification_deterministic_human_review_missing_critical_data(
    session: AsyncSession, seed_env: dict
):
    """Verify HUMAN_REVIEW evaluation: critical info (postal code) is missing."""
    org1 = seed_env["org1"]
    lead_svc = LeadService(session, org1.id)
    qual_svc = QualificationService(session, org1.id)

    # Missing postal_code
    lead = await lead_svc.create_lead(
        LeadCreate(
            organization_id=org1.id,
            first_name="Mystery",
            last_name="Customer",
            phone="+15558889999",
            service_type="AC Diagnostic & Repair",
            problem_description="AC is freezing up and forming thick ice outside.",
            urgency=LeadUrgency.HIGH,
            sms_consent_status=ConsentStatus.OPTED_IN,
        )
    )

    result = await qual_svc.evaluate_lead(lead.id)

    assert result.category == QualificationCategory.HUMAN_REVIEW.value
    assert "postal_code" in result.missing_information
    assert result.requires_human is True
    assert result.recommended_action == "REQUEST_MISSING_DETAILS"

    # Status moves to QUALIFYING (active conversational state gathering details)
    fetched_lead = await lead_svc.get_lead(lead.id)
    assert fetched_lead.status == LeadStatus.QUALIFYING.value


@pytest.mark.asyncio
async def test_qualification_safety_emergency_trigger(session: AsyncSession, seed_env: dict):
    """Verify critical safety hazards immediately trigger HUMAN_REVIEW with score 100."""
    org1 = seed_env["org1"]
    lead_svc = LeadService(session, org1.id)
    qual_svc = QualificationService(session, org1.id)

    hazard_descriptions = [
        "I smell gas near our basement furnace valve!",
        "Our carbon monoxide alarm is beeping loudly in the hallway!",
        "There is smoke and electrical burning coming from the AC disconnect box.",
    ]

    for desc in hazard_descriptions:
        lead = await lead_svc.create_lead(
            LeadCreate(
                organization_id=org1.id,
                first_name="Danger",
                last_name="Test",
                phone="+15559119111",
                postal_code="75001",
                problem_description=desc,
                urgency=LeadUrgency.EMERGENCY,
                sms_consent_status=ConsentStatus.OPTED_IN,
            )
        )

        result = await qual_svc.evaluate_lead(lead.id)

        assert result.category == QualificationCategory.HUMAN_REVIEW.value
        assert result.score == 100
        assert result.requires_human is True
        assert result.recommended_action == "EMERGENCY_SAFETY_DISPATCH"
        assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_qualification_history_and_cross_tenant_isolation(
    session: AsyncSession, seed_env: dict
):
    """Verify storing multiple evaluation runs for a lead and enforcing tenant boundary."""
    org1 = seed_env["org1"]
    org2 = seed_env["org2"]
    lead_svc1 = LeadService(session, org1.id)
    qual_svc1 = QualificationService(session, org1.id)
    qual_svc2 = QualificationService(session, org2.id)

    test_lead = await lead_svc1.create_lead(
        LeadCreate(
            organization_id=org1.id,
            first_name="Eval",
            last_name="History",
            phone="+15559876543",
            problem_description="AC repair needed",
        )
    )

    # First evaluation
    res1 = await qual_svc1.evaluate_lead(test_lead.id)
    # Re-evaluate
    res2 = await qual_svc1.evaluate_lead(test_lead.id)

    latest = await qual_svc1.get_latest_result(test_lead.id)
    assert latest is not None
    assert latest.id == res2.id

    history = await qual_svc1.list_results_for_lead(test_lead.id)
    assert len(history) == 2
    assert history[0].id == res2.id
    assert history[1].id == res1.id

    # Org 2 cannot access Org 1's lead evaluations
    with pytest.raises(EntityNotFoundError):
        await qual_svc2.get_latest_result(test_lead.id)

    with pytest.raises(EntityNotFoundError):
        await qual_svc2.list_results_for_lead(test_lead.id)


# ============================================================================
# 4. LEAD INTEGRATION & SCHEMA PROTECTION TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_lead_service_internal_update_qualification(session: AsyncSession, seed_env: dict):
    """Verify internal update_qualification method updates score and validates state transitions."""
    org1 = seed_env["org1"]
    lead_svc = LeadService(session, org1.id)

    lead = await lead_svc.create_lead(
        LeadCreate(
            organization_id=org1.id,
            first_name="Testing",
            last_name="Transitions",
            phone="+15554443333",
            postal_code="75001",
            problem_description="Checking lead status progression.",
        )
    )

    # 1. Update score only
    updated = await lead_svc.update_qualification(lead.id, qualification_score=85)
    assert updated.qualification_score == 85

    # 2. Update status through state machine: NEW -> QUALIFYING -> QUALIFIED
    await lead_svc.update_qualification(
        lead.id, qualification_score=85, status=LeadStatus.QUALIFYING
    )
    assert (await lead_svc.get_lead(lead.id)).status == LeadStatus.QUALIFYING.value

    await lead_svc.update_qualification(
        lead.id, qualification_score=90, status=LeadStatus.QUALIFIED
    )
    assert (await lead_svc.get_lead(lead.id)).status == LeadStatus.QUALIFIED.value

    # 3. Invalid score rejected
    with pytest.raises(ValidationError):
        await lead_svc.update_qualification(lead.id, qualification_score=150)

    with pytest.raises(ValidationError):
        await lead_svc.update_qualification(lead.id, qualification_score=-5)

    # 4. Invalid transition rejected by state machine (e.g. QUALIFIED -> NEW)
    with pytest.raises(InvalidOperationError):
        await lead_svc.update_qualification(lead.id, qualification_score=90, status=LeadStatus.NEW)


def test_public_lead_update_schema_excludes_qualification_score():
    """Verify client-facing LeadUpdate schema does not accept qualification_score or status."""
    fields = LeadUpdate.model_fields.keys()
    assert "qualification_score" not in fields
    assert "status" not in fields
    assert "deleted_at" not in fields


# ============================================================================
# 5. EXPANDED APPOINTMENT VALIDATION, CONCURRENCY & ISOLATION TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_appointment_datetime_validation_rejects_naive_and_validates_offsets(
    session: AsyncSession, seed_env: dict
):
    """Verify rejection of naive datetimes, start < end, and support for timezone offsets."""
    org1 = seed_env["org1"]
    l1 = seed_env["l1"]
    s1 = seed_env["s1"]
    appt_service = AppointmentService(session, org1.id)

    # 1. Naive start time rejected in service
    naive_start = datetime(2026, 12, 11, 10, 0)
    aware_end = datetime(2026, 12, 11, 11, 0, tzinfo=UTC)
    with pytest.raises(ValidationError) as exc:
        await appt_service.schedule_appointment(
            lead_id=l1.id,
            service_id=s1.id,
            appointment_start=naive_start,
            appointment_end=aware_end,
            service_type=s1.service_name,
        )
    assert "appointment_start must be a timezone-aware datetime" in str(exc.value)

    # 2. Naive end time rejected in service
    aware_start = datetime(2026, 12, 11, 10, 0, tzinfo=UTC)
    naive_end = datetime(2026, 12, 11, 11, 0)
    with pytest.raises(ValidationError) as exc:
        await appt_service.schedule_appointment(
            lead_id=l1.id,
            service_id=s1.id,
            appointment_start=aware_start,
            appointment_end=naive_end,
            service_type=s1.service_name,
        )
    assert "appointment_end must be a timezone-aware datetime" in str(exc.value)

    # 3. Naive datetimes rejected in AppointmentCreate schema
    with pytest.raises(ValueError) as exc:
        AppointmentCreate(
            organization_id=org1.id,
            lead_id=l1.id,
            service_id=s1.id,
            appointment_start=naive_start,
            appointment_end=aware_end,
            service_type=s1.service_name,
        )
    assert "appointment_start must be a timezone-aware datetime" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        AppointmentCreate(
            organization_id=org1.id,
            lead_id=l1.id,
            service_id=s1.id,
            appointment_start=aware_start,
            appointment_end=naive_end,
            service_type=s1.service_name,
        )
    assert "appointment_end must be a timezone-aware datetime" in str(exc.value)

    # 4. Naive datetimes rejected in AppointmentUpdate schema
    with pytest.raises(ValueError) as exc:
        AppointmentUpdate(appointment_start=naive_start)
    assert "appointment_start must be a timezone-aware datetime" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        AppointmentUpdate(appointment_end=naive_end)
    assert "appointment_end must be a timezone-aware datetime" in str(exc.value)

    # 5. Naive datetimes rejected during rescheduling
    valid_appt = await appt_service.schedule_appointment(
        lead_id=l1.id,
        service_id=s1.id,
        appointment_start=aware_start,
        appointment_end=aware_end,
        service_type=s1.service_name,
    )
    with pytest.raises(ValidationError) as exc:
        await appt_service.reschedule_appointment(
            valid_appt.id,
            new_start_time=naive_start,
            new_end_time=aware_end,
        )
    assert "new_start_time must be a timezone-aware datetime" in str(exc.value)

    with pytest.raises(ValidationError) as exc:
        await appt_service.reschedule_appointment(
            valid_appt.id,
            new_start_time=aware_start,
            new_end_time=naive_end,
        )
    assert "new_end_time must be a timezone-aware datetime" in str(exc.value)

    # 6. Valid non-UTC timezone-aware datetimes succeed and represent correct instant
    cst = timezone(timedelta(hours=-6))
    non_utc_start = datetime(2026, 12, 12, 9, 0, tzinfo=cst)  # 15:00 UTC
    non_utc_end = datetime(2026, 12, 12, 10, 30, tzinfo=cst)  # 16:30 UTC
    appt_non_utc = await appt_service.schedule_appointment(
        lead_id=l1.id,
        service_id=s1.id,
        appointment_start=non_utc_start,
        appointment_end=non_utc_end,
        service_type=s1.service_name,
    )
    assert appt_non_utc.id is not None
    assert appt_non_utc.appointment_start == non_utc_start
    assert appt_non_utc.appointment_end == non_utc_end

    # Competing booking in UTC that overlaps 15:30 to 17:00 UTC is rejected
    utc_conflict_start = datetime(2026, 12, 12, 15, 30, tzinfo=UTC)
    utc_conflict_end = datetime(2026, 12, 12, 17, 0, tzinfo=UTC)
    with pytest.raises(InvalidOperationError):
        await appt_service.schedule_appointment(
            lead_id=l1.id,
            service_id=s1.id,
            appointment_start=utc_conflict_start,
            appointment_end=utc_conflict_end,
            service_type=s1.service_name,
        )


@pytest.mark.asyncio
async def test_appointment_cross_tenant_operations_rejected(session: AsyncSession, seed_env: dict):
    """Verify cross-tenant appointment retrieval, cancellation, and rescheduling are rejected."""
    org1 = seed_env["org1"]
    org2 = seed_env["org2"]
    l1 = seed_env["l1"]
    s1 = seed_env["s1"]
    appt_svc1 = AppointmentService(session, org1.id)
    appt_svc2 = AppointmentService(session, org2.id)

    t_start = datetime(2026, 12, 13, 10, 0, tzinfo=UTC)
    t_end = datetime(2026, 12, 13, 11, 0, tzinfo=UTC)

    appt1 = await appt_svc1.schedule_appointment(
        lead_id=l1.id,
        service_id=s1.id,
        appointment_start=t_start,
        appointment_end=t_end,
        service_type=s1.service_name,
    )

    # 1. Org 2 cannot retrieve Org 1's appointment
    with pytest.raises(EntityNotFoundError):
        await appt_svc2.get_appointment(appt1.id)

    # 2. Org 2 cannot cancel Org 1's appointment
    with pytest.raises(EntityNotFoundError):
        await appt_svc2.cancel_appointment(appt1.id, reason="Malicious cross-tenant attempt")

    # 3. Org 2 cannot reschedule Org 1's appointment
    with pytest.raises(EntityNotFoundError):
        await appt_svc2.reschedule_appointment(
            appt1.id,
            new_start_time=datetime(2026, 12, 13, 14, 0, tzinfo=UTC),
            new_end_time=datetime(2026, 12, 13, 15, 0, tzinfo=UTC),
        )

    # 4. Org 2 cannot schedule an appointment for Org 1's lead
    with pytest.raises(EntityNotFoundError):
        await appt_svc2.schedule_appointment(
            lead_id=l1.id,
            service_id=seed_env["s2_org2"].id,
            appointment_start=t_start,
            appointment_end=t_end,
            service_type="Heat Pump Tune-up",
        )


@pytest.mark.asyncio
async def test_appointment_hold_15min_exact_boundaries_and_tenant_scoping(
    session: AsyncSession, seed_env: dict
):
    """Verify exact 15-minute OFFERED hold expiration cutoff and tenant-scoped expiration."""
    org1 = seed_env["org1"]
    org2 = seed_env["org2"]
    l1 = seed_env["l1"]
    l2 = seed_env["l2"]
    l_org2 = seed_env["l_org2"]
    s1 = seed_env["s1"]
    s2_org2 = seed_env["s2_org2"]

    appt_svc1 = AppointmentService(session, org1.id)
    appt_svc2 = AppointmentService(session, org2.id)
    lead_svc1 = LeadService(session, org1.id)
    qual_svc1 = QualificationService(session, org1.id)
    await qual_svc1.evaluate_lead(l2.id)
    await lead_svc1.change_status(l2.id, LeadStatus.QUALIFIED)

    slot_start = datetime(2026, 12, 14, 10, 0, tzinfo=UTC)
    slot_end = datetime(2026, 12, 14, 11, 0, tzinfo=UTC)

    # Create OFFERED hold in Org 1
    hold_org1 = await appt_svc1.schedule_appointment(
        lead_id=l1.id,
        service_id=s1.id,
        appointment_start=slot_start,
        appointment_end=slot_end,
        service_type=s1.service_name,
        status=AppointmentStatus.OFFERED,
    )

    # Create OFFERED hold in Org 2 for later time
    hold_org2 = await appt_svc2.schedule_appointment(
        lead_id=l_org2.id,
        service_id=s2_org2.id,
        appointment_start=datetime(2026, 12, 14, 14, 0, tzinfo=UTC),
        appointment_end=datetime(2026, 12, 14, 15, 0, tzinfo=UTC),
        service_type=s2_org2.service_name,
        status=AppointmentStatus.OFFERED,
    )

    # Use a fixed reference timestamp for deterministic boundary verification
    ref_time = datetime(2026, 12, 14, 12, 0, 0, tzinfo=UTC)
    cutoff_15m = ref_time - timedelta(minutes=15)

    # 1. Exactly 14m 59s old (1 second younger than cutoff) -> MUST REMAIN ACTIVE
    hold_org1.created_at = ref_time - timedelta(minutes=14, seconds=59)
    # Org 2 hold is 25 minutes old (stale in Org 2, but must not be touched by Org 1)
    hold_org2.created_at = ref_time - timedelta(minutes=25)
    await session.flush()

    expired_org1 = await appt_svc1.appointment_repo.expire_stale_holds(org1.id, cutoff=cutoff_15m)
    assert expired_org1 == 0

    fetched_org1 = await appt_svc1.get_appointment(hold_org1.id)
    assert fetched_org1.appointment_status == AppointmentStatus.OFFERED.value

    # Competing booking for Org 1 in that slot is STILL blocked by active hold
    with pytest.raises(InvalidOperationError):
        await appt_svc1.schedule_appointment(
            lead_id=l2.id,
            service_id=s1.id,
            appointment_start=slot_start,
            appointment_end=slot_end,
            service_type=s1.service_name,
        )

    # Org 2 hold is still OFFERED (tenant-scoping prevents cross-tenant expiration)
    fetched_org2 = await appt_svc2.get_appointment(hold_org2.id)
    assert fetched_org2.appointment_status == AppointmentStatus.OFFERED.value

    # 2. Exactly 15m 00s old (created_at == cutoff_15m) -> MUST EXPIRE
    hold_org1.created_at = ref_time - timedelta(minutes=15, seconds=0)
    await session.flush()

    expired_boundary = await appt_svc1.appointment_repo.expire_stale_holds(
        org1.id, cutoff=cutoff_15m
    )
    assert expired_boundary == 1

    fetched_org1_expired = await appt_svc1.get_appointment(hold_org1.id)
    assert fetched_org1_expired.appointment_status == AppointmentStatus.CANCELLED.value
    assert "expired" in (fetched_org1_expired.cancellation_reason or "").lower()

    # Org 2 hold remains OFFERED (untouched by Org 1 expiration at exact boundary)
    fetched_org2_still_offered = await appt_svc2.get_appointment(hold_org2.id)
    assert fetched_org2_still_offered.appointment_status == AppointmentStatus.OFFERED.value

    # 3. 15m 01s old (created_at < cutoff_15m) -> MUST ALSO EXPIRE
    slot3_start = datetime(2026, 12, 14, 16, 0, tzinfo=UTC)
    slot3_end = datetime(2026, 12, 14, 17, 0, tzinfo=UTC)
    hold3 = await appt_svc1.schedule_appointment(
        lead_id=l1.id,
        service_id=s1.id,
        appointment_start=slot3_start,
        appointment_end=slot3_end,
        service_type=s1.service_name,
        status=AppointmentStatus.OFFERED,
    )
    hold3.created_at = ref_time - timedelta(minutes=15, seconds=1)
    await session.flush()

    expired_older = await appt_svc1.appointment_repo.expire_stale_holds(org1.id, cutoff=cutoff_15m)
    assert expired_older == 1
    fetched_hold3 = await appt_svc1.get_appointment(hold3.id)
    assert fetched_hold3.appointment_status == AppointmentStatus.CANCELLED.value

    # 4. Now booking slot 1 for lead 2 succeeds because hold_org1 is cancelled
    new_confirmed = await appt_svc1.schedule_appointment(
        lead_id=l2.id,
        service_id=s1.id,
        appointment_start=slot_start,
        appointment_end=slot_end,
        service_type=s1.service_name,
    )
    assert new_confirmed.appointment_status == AppointmentStatus.CONFIRMED.value


@pytest.mark.asyncio
async def test_appointment_savepoint_rollback_allows_subsequent_operations(
    session: AsyncSession, seed_env: dict
):
    """Verify exclusion violation in savepoint rolls back and leaves transaction active."""
    org1 = seed_env["org1"]
    l1 = seed_env["l1"]
    l2 = seed_env["l2"]
    s1 = seed_env["s1"]
    appt_svc = AppointmentService(session, org1.id)
    lead_svc = LeadService(session, org1.id)
    qual_svc = QualificationService(session, org1.id)
    await qual_svc.evaluate_lead(l2.id)
    await lead_svc.change_status(l2.id, LeadStatus.QUALIFIED)

    slot1_start = datetime(2026, 12, 15, 9, 0, tzinfo=UTC)
    slot1_end = datetime(2026, 12, 15, 10, 0, tzinfo=UTC)

    # Book first appointment
    appt1 = await appt_svc.schedule_appointment(
        lead_id=l1.id,
        service_id=s1.id,
        appointment_start=slot1_start,
        appointment_end=slot1_end,
        service_type=s1.service_name,
    )
    assert appt1.id is not None

    # Simulate an exclusion violation directly inside a savepoint
    overlapping_start = datetime(2026, 12, 15, 9, 30, tzinfo=UTC)
    overlapping_end = datetime(2026, 12, 15, 10, 30, tzinfo=UTC)
    colliding_appt = Appointment(
        organization_id=org1.id,
        lead_id=l2.id,
        service_id=s1.id,
        time_slot=Range(overlapping_start, overlapping_end, bounds="[)"),
        appointment_start=overlapping_start,
        appointment_end=overlapping_end,
        appointment_status=AppointmentStatus.CONFIRMED.value,
        service_type=s1.service_name,
    )

    # Execute insert inside a nested savepoint
    async with session.begin_nested():
        session.add(colliding_appt)
        with pytest.raises(IntegrityError) as exc_info:
            await session.flush()
        assert "uq_contractor_no_double_booking" in str(exc_info.value).lower()

    # The outer transaction is STILL ACTIVE and usable:
    # Caller can immediately schedule another non-overlapping booking in the same transaction
    slot2_start = datetime(2026, 12, 15, 11, 0, tzinfo=UTC)
    slot2_end = datetime(2026, 12, 15, 12, 0, tzinfo=UTC)
    appt2 = await appt_svc.schedule_appointment(
        lead_id=l2.id,
        service_id=s1.id,
        appointment_start=slot2_start,
        appointment_end=slot2_end,
        service_type=s1.service_name,
    )
    assert appt2.id is not None
    assert appt2.appointment_status == AppointmentStatus.CONFIRMED.value

    # Verify appt1 remains CONFIRMED
    fetched1 = await appt_svc.get_appointment(appt1.id)
    assert fetched1.appointment_status == AppointmentStatus.CONFIRMED.value


@pytest.mark.asyncio
async def test_genuine_concurrent_appointment_booking():
    """Verify concurrent transactions: exactly one wins and losing session stays active."""
    settings = get_settings()
    base_url = settings.DATABASE_URL.rsplit("/", 1)[0]
    test_db_url = f"{base_url}/{TEST_DB_NAME}"

    engine1 = create_async_engine(test_db_url, poolclass=NullPool)
    engine2 = create_async_engine(test_db_url, poolclass=NullPool)

    # 1. Seed base data with an independent connection and commit
    async with async_sessionmaker(engine1, expire_on_commit=False)() as seed_session:
        user_svc = UserService(seed_session)
        org_svc = OrganizationService(seed_session)

        u = await user_svc.register_user(
            UserCreate(
                email=f"concurrent_test_{uuid.uuid4().hex[:6]}@example.com",
                password="SecurePassword123!",
                first_name="Concurrent",
                last_name="Tester",
            )
        )
        slug1 = f"conc-air-{uuid.uuid4().hex[:6]}"
        slug2 = f"conc-heat-{uuid.uuid4().hex[:6]}"
        org1, _ = await org_svc.create_organization(
            u.id, OrganizationCreate(name="Concurrent Air", slug=slug1)
        )
        org2, _ = await org_svc.create_organization(
            u.id, OrganizationCreate(name="Concurrent Heat", slug=slug2)
        )

        svc_svc1 = ServiceService(seed_session, org1.id)
        s1 = await svc_svc1.create_service(
            ServiceCreate(
                organization_id=org1.id,
                service_name="Emergency Diagnostic",
                service_code="EMERG-DIAG",
                base_price=Decimal("150.00"),
            )
        )
        svc_svc2 = ServiceService(seed_session, org2.id)
        s2 = await svc_svc2.create_service(
            ServiceCreate(
                organization_id=org2.id,
                service_name="Emergency Diagnostic",
                service_code="EMERG-DIAG",
                base_price=Decimal("150.00"),
            )
        )

        lead_svc1 = LeadService(seed_session, org1.id)
        l1 = await lead_svc1.create_lead(
            LeadCreate(
                organization_id=org1.id,
                first_name="Alice",
                last_name="Concurrent",
                phone="+15551112222",
                postal_code="75001",
                street_address="100 Main St",
                service_type="Emergency Diagnostic",
                problem_description="AC breakdown.",
                urgency=LeadUrgency.HIGH,
                sms_consent_status=ConsentStatus.OPTED_IN,
            )
        )
        qual_svc1 = QualificationService(seed_session, org1.id)
        await qual_svc1.evaluate_lead(l1.id)
        await lead_svc1.change_status(l1.id, LeadStatus.QUALIFIED)

        l2 = await lead_svc1.create_lead(
            LeadCreate(
                organization_id=org1.id,
                first_name="Bob",
                last_name="Concurrent",
                phone="+15553334444",
                postal_code="75001",
                street_address="101 Main St",
                service_type="Emergency Diagnostic",
                problem_description="AC breakdown.",
                urgency=LeadUrgency.HIGH,
                sms_consent_status=ConsentStatus.OPTED_IN,
            )
        )
        await qual_svc1.evaluate_lead(l2.id)
        await lead_svc1.change_status(l2.id, LeadStatus.QUALIFIED)

        lead_svc2 = LeadService(seed_session, org2.id)
        l_org2 = await lead_svc2.create_lead(
            LeadCreate(
                organization_id=org2.id,
                first_name="Charlie",
                last_name="Concurrent",
                phone="+15555556666",
                postal_code="75002",
                street_address="200 Elm St",
                service_type="Emergency Diagnostic",
                problem_description="Heat pump issue.",
                urgency=LeadUrgency.HIGH,
                sms_consent_status=ConsentStatus.OPTED_IN,
            )
        )
        qual_svc2 = QualificationService(seed_session, org2.id)
        await qual_svc2.evaluate_lead(l_org2.id)
        await lead_svc2.change_status(l_org2.id, LeadStatus.QUALIFIED)

        await seed_session.commit()

        org1_id = org1.id
        org2_id = org2.id
        s1_id = s1.id
        s2_id = s2.id
        l1_id = l1.id
        l2_id = l2.id
        l_org2_id = l_org2.id

    # 2. Execute genuine concurrent bookings across two distinct connections
    slot_start = datetime(2026, 12, 16, 14, 0, tzinfo=UTC)
    slot_end = datetime(2026, 12, 16, 16, 0, tzinfo=UTC)

    barrier = asyncio.Barrier(2)

    async def worker_1():
        async with async_sessionmaker(engine1, expire_on_commit=False)() as sess:
            svc = AppointmentService(sess, org1_id)
            await barrier.wait()
            try:
                appt = await svc.schedule_appointment(
                    lead_id=l1_id,
                    service_id=s1_id,
                    appointment_start=slot_start,
                    appointment_end=slot_end,
                    service_type="Emergency Diagnostic",
                )
                await sess.commit()
                return ("SUCCESS", appt, sess)
            except Exception as exc:
                return ("FAIL", exc, sess)

    async def worker_2():
        async with async_sessionmaker(engine2, expire_on_commit=False)() as sess:
            svc = AppointmentService(sess, org1_id)
            await barrier.wait()
            try:
                appt = await svc.schedule_appointment(
                    lead_id=l2_id,
                    service_id=s1_id,
                    appointment_start=slot_start,
                    appointment_end=slot_end,
                    service_type="Emergency Diagnostic",
                )
                await sess.commit()
                return ("SUCCESS", appt, sess)
            except Exception as exc:
                return ("FAIL", exc, sess)

    results = await asyncio.gather(worker_1(), worker_2())

    statuses = [r[0] for r in results]
    assert "SUCCESS" in statuses
    assert "FAIL" in statuses
    assert statuses.count("SUCCESS") == 1
    assert statuses.count("FAIL") == 1

    failed_result = next(r for r in results if r[0] == "FAIL")
    assert isinstance(failed_result[1], InvalidOperationError)
    assert "overlaps with an existing booking" in str(failed_result[1])

    # 3. Verify overlapping booking for DIFFERENT organization succeeds
    async with async_sessionmaker(engine1, expire_on_commit=False)() as sess_org2:
        svc_org2 = AppointmentService(sess_org2, org2_id)
        appt_org2 = await svc_org2.schedule_appointment(
            lead_id=l_org2_id,
            service_id=s2_id,
            appointment_start=slot_start,
            appointment_end=slot_end,
            service_type="Emergency Diagnostic",
        )
        await sess_org2.commit()
        assert appt_org2.id is not None
        assert appt_org2.organization_id == org2_id

    await engine1.dispose()
    await engine2.dispose()


# ============================================================================
# 6. REVISED SERVICE CATALOG QUALIFICATION & CONSENT SEPARATION TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_qualification_unsupported_service_outside_catalog_is_cold(
    session: AsyncSession, seed_env: dict
):
    """Verify trade not in catalog (even if not hardcoded keyword) is evaluated as COLD."""
    org1 = seed_env["org1"]
    lead_svc = LeadService(session, org1.id)
    qual_svc = QualificationService(session, org1.id)

    # "Geothermal Heat Pump Installation" is not offered by Org 1
    lead = await lead_svc.create_lead(
        LeadCreate(
            organization_id=org1.id,
            first_name="Gwen",
            last_name="Stacy",
            phone="+15556667777",
            postal_code="75001",
            street_address="100 Web Way",
            service_type="Geothermal Heat Pump Installation",
            equipment_type="Closed Loop Geothermal",
            problem_description="Want to install complete ground-source geothermal heating.",
            urgency=LeadUrgency.HIGH,
            sms_consent_status=ConsentStatus.OPTED_IN,
        )
    )

    result = await qual_svc.evaluate_lead(lead.id)

    assert result.category == QualificationCategory.COLD.value
    assert result.score <= 30
    assert result.recommended_action == "DECLINE_UNSUPPORTED_SERVICE"
    assert result.requires_human is False
    assert "is not offered in contractor active service catalog" in result.reasoning


@pytest.mark.asyncio
async def test_qualification_ambiguous_service_routes_to_human_review(
    session: AsyncSession, seed_env: dict
):
    """Verify ambiguous service request routes to HUMAN_REVIEW to clarify requirements."""
    org1 = seed_env["org1"]
    lead_svc = LeadService(session, org1.id)
    qual_svc = QualificationService(session, org1.id)

    lead = await lead_svc.create_lead(
        LeadCreate(
            organization_id=org1.id,
            first_name="Arthur",
            last_name="Dent",
            phone="+15553339999",
            postal_code="75001",
            street_address="42 Galaxy Road",
            service_type="Other",  # Ambiguous
            problem_description="Strange clicking noise somewhere in utility closet.",
            urgency=LeadUrgency.MEDIUM,
            sms_consent_status=ConsentStatus.OPTED_IN,
        )
    )

    result = await qual_svc.evaluate_lead(lead.id)

    assert result.category == QualificationCategory.HUMAN_REVIEW.value
    assert "service_type" in result.missing_information
    assert result.requires_human is True
    assert result.recommended_action == "CLARIFY_SERVICE_REQUIREMENTS"


@pytest.mark.asyncio
async def test_qualification_opt_out_does_not_degrade_commercial_score(
    session: AsyncSession, seed_env: dict
):
    """Verify customer opt-out does not degrade commercial qualification score or force COLD."""
    org1 = seed_env["org1"]
    lead_svc = LeadService(session, org1.id)
    qual_svc = QualificationService(session, org1.id)

    # Lead has explicitly opted out of both SMS and Email messaging,
    # but submits a high-intent, urgent request for a supported service
    lead = await lead_svc.create_lead(
        LeadCreate(
            organization_id=org1.id,
            first_name="Sarah",
            last_name="Connor",
            phone="+15558001000",
            email="sarah@example.com",
            postal_code="75001",
            street_address="1984 Cyber Lane",
            service_type="AC Diagnostic & Repair",
            equipment_type="Central AC Trane",
            problem_description="AC system fan motor is completely dead on a 100-degree day.",
            urgency=LeadUrgency.HIGH,
            sms_consent_status=ConsentStatus.OPTED_OUT,
            email_consent_status=ConsentStatus.OPTED_OUT,
        )
    )

    result = await qual_svc.evaluate_lead(lead.id)

    # Commercial qualification evaluates lead intent and requirements:
    # High intent + urgency + supported service -> HOT (score >= 75)
    assert result.category == QualificationCategory.HOT.value
    assert result.score >= 75
    assert result.recommended_action == "OFFER_APPOINTMENT_SLOTS"

    # Consent audit records are preserved in collected_information
    assert result.collected_information["sms_consent_status"] == ConsentStatus.OPTED_OUT.value
    assert result.collected_information["email_consent_status"] == ConsentStatus.OPTED_OUT.value


# ============================================================================
# 7. SAFETY BOOKING RESTRICTIONS & HUMAN RESOLUTION TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_safety_booking_unqualified_lead_status_rejected(
    session: AsyncSession, seed_env: dict
):
    """Verify leads in unverified lifecycle states cannot schedule appointments."""
    org1 = seed_env["org1"]
    s1 = seed_env["s1"]
    lead_svc = LeadService(session, org1.id)
    appt_svc = AppointmentService(session, org1.id)

    # Lead in NEW status
    lead_new = await lead_svc.create_lead(
        LeadCreate(
            organization_id=org1.id,
            first_name="New",
            last_name="Lead",
            phone="+15551000001",
            problem_description="AC issue",
        )
    )
    t_start = datetime(2026, 12, 17, 10, 0, tzinfo=UTC)
    t_end = datetime(2026, 12, 17, 11, 0, tzinfo=UTC)

    with pytest.raises(InvalidOperationError) as exc_info:
        await appt_svc.schedule_appointment(
            lead_id=lead_new.id,
            service_id=s1.id,
            appointment_start=t_start,
            appointment_end=t_end,
            service_type=s1.service_name,
        )
    assert "Lead must be qualified before scheduling" in str(exc_info.value)

    # Move to QUALIFYING (active gathering phase)
    await lead_svc.change_status(lead_new.id, LeadStatus.QUALIFYING)
    with pytest.raises(InvalidOperationError) as exc_info:
        await appt_svc.schedule_appointment(
            lead_id=lead_new.id,
            service_id=s1.id,
            appointment_start=t_start,
            appointment_end=t_end,
            service_type=s1.service_name,
        )
    assert "lead with status 'qualifying'" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_safety_booking_human_review_qualification_rejected(
    session: AsyncSession, seed_env: dict
):
    """Verify lead requiring human review cannot schedule appointments even if status is set."""
    org1 = seed_env["org1"]
    s1 = seed_env["s1"]
    lead_svc = LeadService(session, org1.id)
    qual_svc = QualificationService(session, org1.id)
    appt_svc = AppointmentService(session, org1.id)

    # Ambiguous service leads to HUMAN_REVIEW
    lead = await lead_svc.create_lead(
        LeadCreate(
            organization_id=org1.id,
            first_name="Ambiguous",
            last_name="Review",
            phone="+15551000002",
            service_type="Unknown Weird Noise",
            problem_description="Humming sound from crawlspace",
            sms_consent_status=ConsentStatus.OPTED_IN,
        )
    )
    qual_res = await qual_svc.evaluate_lead(lead.id)
    assert qual_res.category == QualificationCategory.HUMAN_REVIEW.value
    assert qual_res.requires_human is True

    # Even if status is manually set to QUALIFIED, the qualification check blocks scheduling
    await lead_svc.change_status(lead.id, LeadStatus.QUALIFIED)

    t_start = datetime(2026, 12, 17, 12, 0, tzinfo=UTC)
    t_end = datetime(2026, 12, 17, 13, 0, tzinfo=UTC)
    with pytest.raises(InvalidOperationError) as exc_info:
        await appt_svc.schedule_appointment(
            lead_id=lead.id,
            service_id=s1.id,
            appointment_start=t_start,
            appointment_end=t_end,
            service_type=s1.service_name,
        )
    assert "human review or safety escalation" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_safety_booking_safety_hazard_score_100_cannot_book(
    session: AsyncSession, seed_env: dict
):
    """Verify safety emergency with score 100 cannot bypass safety and schedule appointment."""
    org1 = seed_env["org1"]
    s1 = seed_env["s1"]
    lead_svc = LeadService(session, org1.id)
    qual_svc = QualificationService(session, org1.id)
    appt_svc = AppointmentService(session, org1.id)

    hazard_lead = await lead_svc.create_lead(
        LeadCreate(
            organization_id=org1.id,
            first_name="Hazard",
            last_name="Caller",
            phone="+15551000003",
            postal_code="75001",
            problem_description="I smell gas near our basement furnace valve!",
            urgency=LeadUrgency.EMERGENCY,
            sms_consent_status=ConsentStatus.OPTED_IN,
        )
    )
    qual_result = await qual_svc.evaluate_lead(hazard_lead.id)
    assert qual_result.score == 100
    assert qual_result.category == QualificationCategory.HUMAN_REVIEW.value
    assert qual_result.requires_human is True
    assert qual_result.recommended_action == "EMERGENCY_SAFETY_DISPATCH"

    # Even if lead status is changed, score 100 + requires_human blocks booking
    await lead_svc.change_status(hazard_lead.id, LeadStatus.QUALIFIED)

    t_start = datetime(2026, 12, 17, 14, 0, tzinfo=UTC)
    t_end = datetime(2026, 12, 17, 15, 0, tzinfo=UTC)
    with pytest.raises(InvalidOperationError) as exc_info:
        await appt_svc.schedule_appointment(
            lead_id=hazard_lead.id,
            service_id=s1.id,
            appointment_start=t_start,
            appointment_end=t_end,
            service_type=s1.service_name,
        )
    assert "human review or safety escalation" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_safety_booking_active_conversation_safety_lock_blocks_scheduling(
    session: AsyncSession, seed_env: dict
):
    """Verify an active safety escalation on a lead's conversation locks out scheduling."""
    org1 = seed_env["org1"]
    l1 = seed_env["l1"]
    s1 = seed_env["s1"]
    appt_svc = AppointmentService(session, org1.id)
    conv_svc = ConversationService(session, org1.id)

    # Lead 1 is qualified with HOT score, but starts an SMS conversation with safety hazard
    conv = await conv_svc.create_conversation(
        ConversationCreate(
            organization_id=org1.id,
            lead_id=l1.id,
            channel=ChannelType.SMS,
        )
    )
    # Trigger emergency safety lock
    await conv_svc.trigger_safety_lock(conv.id, hazard_reason="CARBON_MONOXIDE_ALARM")

    t_start = datetime(2026, 12, 17, 15, 0, tzinfo=UTC)
    t_end = datetime(2026, 12, 17, 16, 0, tzinfo=UTC)

    # Booking must be strictly rejected
    with pytest.raises(InvalidOperationError) as exc_info:
        await appt_svc.schedule_appointment(
            lead_id=l1.id,
            service_id=s1.id,
            appointment_start=t_start,
            appointment_end=t_end,
            service_type=s1.service_name,
        )
    assert "safety escalation or conversation lock" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_safety_booking_reschedule_blocked_on_safety_escalation_preserves_original(
    session: AsyncSession, seed_env: dict
):
    """Verify safety-escalated lead cannot reschedule and original booking remains intact."""
    org1 = seed_env["org1"]
    l1 = seed_env["l1"]
    s1 = seed_env["s1"]
    appt_svc = AppointmentService(session, org1.id)
    conv_svc = ConversationService(session, org1.id)

    # 1. Lead successfully books an initial appointment
    t1_start = datetime(2026, 12, 18, 9, 0, tzinfo=UTC)
    t1_end = datetime(2026, 12, 18, 10, 0, tzinfo=UTC)
    original_appt = await appt_svc.schedule_appointment(
        lead_id=l1.id,
        service_id=s1.id,
        appointment_start=t1_start,
        appointment_end=t1_end,
        service_type=s1.service_name,
    )
    assert original_appt.appointment_status == AppointmentStatus.CONFIRMED.value

    # 2. Customer later texts about smelling smoke -> safety lock triggered
    conv = await conv_svc.create_conversation(
        ConversationCreate(
            organization_id=org1.id,
            lead_id=l1.id,
            channel=ChannelType.SMS,
        )
    )
    await conv_svc.trigger_safety_lock(conv.id, hazard_reason="ELECTRICAL_SMOKE")

    # 3. Rescheduling attempt must be rejected
    t2_start = datetime(2026, 12, 18, 14, 0, tzinfo=UTC)
    t2_end = datetime(2026, 12, 18, 15, 0, tzinfo=UTC)
    with pytest.raises(InvalidOperationError) as exc_info:
        await appt_svc.reschedule_appointment(
            original_appt.id,
            new_start_time=t2_start,
            new_end_time=t2_end,
            reason="Customer wants afternoon instead.",
        )
    assert "safety escalation or conversation lock" in str(exc_info.value).lower()

    # 4. Crucial: Original appointment must remain CONFIRMED and completely unchanged!
    fetched_original = await appt_svc.get_appointment(original_appt.id)
    assert fetched_original.appointment_status == AppointmentStatus.CONFIRMED.value
    assert fetched_original.appointment_start == t1_start
    assert fetched_original.appointment_end == t1_end
    assert fetched_original.cancellation_reason is None


@pytest.mark.asyncio
async def test_safety_resolution_unauthorized_user_rejected(session: AsyncSession, seed_env: dict):
    """Verify unauthorized role (TECHNICIAN) or inactive user cannot resolve safety escalations."""
    org1 = seed_env["org1"]
    l1 = seed_env["l1"]
    user_svc = UserService(session)
    member_svc = MembershipService(session, org1.id)
    conv_svc = ConversationService(session, org1.id)
    qual_svc = QualificationService(session, org1.id)

    # Create technician user
    tech_user = await user_svc.register_user(
        UserCreate(
            email=f"tech_{uuid.uuid4().hex[:6]}@example.com",
            password="SecurePassword123!",
            first_name="Tim",
            last_name="Tech",
        )
    )
    await member_svc.add_member(tech_user.id, role=UserRole.TECHNICIAN)

    # Create inactive admin user
    inactive_user = await user_svc.register_user(
        UserCreate(
            email=f"inactive_{uuid.uuid4().hex[:6]}@example.com",
            password="SecurePassword123!",
            first_name="Ian",
            last_name="Inactive",
        )
    )
    await member_svc.add_member(inactive_user.id, role=UserRole.ADMIN, is_active=False)

    # Conversation in safety escalation
    conv = await conv_svc.create_conversation(
        ConversationCreate(
            organization_id=org1.id,
            lead_id=l1.id,
            channel=ChannelType.SMS,
        )
    )
    await conv_svc.trigger_safety_lock(conv.id, hazard_reason="GAS_LEAK")

    # 1. Technician rejected on conversation resolution
    with pytest.raises(InvalidOperationError) as exc_info:
        await conv_svc.resolve_safety_escalation(
            conv.id,
            tech_user.id,
            "Tech verified furnace valve is shut off safely.",
        )
    assert "not authorized to resolve safety escalations" in str(exc_info.value)

    # 2. Technician rejected on qualification safety review resolution
    with pytest.raises(InvalidOperationError) as exc_info:
        await qual_svc.resolve_safety_review(
            l1.id,
            tech_user.id,
            "Tech cleared safety hazard on site.",
        )
    assert "not authorized to resolve safety reviews" in str(exc_info.value)

    # 3. Inactive admin rejected on conversation resolution
    with pytest.raises(InvalidOperationError) as exc_info:
        await conv_svc.resolve_safety_escalation(
            conv.id,
            inactive_user.id,
            "Attempting resolution from inactive account.",
        )
    assert "is not an active member" in str(exc_info.value)

    # 4. Inactive admin rejected on qualification review
    with pytest.raises(InvalidOperationError) as exc_info:
        await qual_svc.resolve_safety_review(
            l1.id,
            inactive_user.id,
            "Attempting review resolution from inactive account.",
        )
    assert "is not an active member" in str(exc_info.value)


@pytest.mark.asyncio
async def test_safety_resolution_authorized_user_clears_locks_and_allows_booking(
    session: AsyncSession, seed_env: dict
):
    """Verify authorized staff (DISPATCHER/OWNER) resolves safety escalation and enables booking."""
    org1 = seed_env["org1"]
    s1 = seed_env["s1"]
    user_svc = UserService(session)
    member_svc = MembershipService(session, org1.id)
    conv_svc = ConversationService(session, org1.id)
    qual_svc = QualificationService(session, org1.id)
    lead_svc = LeadService(session, org1.id)
    appt_svc = AppointmentService(session, org1.id)

    # Create dispatcher user
    disp_user = await user_svc.register_user(
        UserCreate(
            email=f"dispatcher_{uuid.uuid4().hex[:6]}@example.com",
            password="SecurePassword123!",
            first_name="Dan",
            last_name="Dispatcher",
        )
    )
    await member_svc.add_member(disp_user.id, role=UserRole.DISPATCHER)

    # Create lead with safety emergency
    hazard_lead = await lead_svc.create_lead(
        LeadCreate(
            organization_id=org1.id,
            first_name="Resolved",
            last_name="Safety",
            phone="+15551000004",
            postal_code="75001",
            problem_description="Strong gas odor and gas leak detected near meter.",
            urgency=LeadUrgency.EMERGENCY,
            sms_consent_status=ConsentStatus.OPTED_IN,
        )
    )
    await qual_svc.evaluate_lead(hazard_lead.id)

    conv = await conv_svc.create_conversation(
        ConversationCreate(
            organization_id=org1.id,
            lead_id=hazard_lead.id,
            channel=ChannelType.SMS,
        )
    )
    await conv_svc.trigger_safety_lock(conv.id, hazard_reason="GAS_ODOR")

    # Scheduling blocked initially
    t_start = datetime(2026, 12, 19, 10, 0, tzinfo=UTC)
    t_end = datetime(2026, 12, 19, 11, 0, tzinfo=UTC)
    with pytest.raises(InvalidOperationError):
        await appt_svc.schedule_appointment(
            lead_id=hazard_lead.id,
            service_id=s1.id,
            appointment_start=t_start,
            appointment_end=t_end,
            service_type=s1.service_name,
        )

    # 1. Resolving conversation while qualification still requires human review is rejected
    with pytest.raises(InvalidOperationError) as exc_info:
        await conv_svc.resolve_safety_escalation(
            conv.id,
            disp_user.id,
            "Spoke with gas utility company. Main line inspected and clear of gas leaks.",
        )
    assert "qualification still requires human review" in str(exc_info.value).lower()

    # 2. Resolving lead safety review while conversation is active without flag is rejected
    with pytest.raises(InvalidOperationError) as exc_info:
        await qual_svc.resolve_safety_review(
            hazard_lead.id,
            disp_user.id,
            "Customer requests standard furnace tune-up after safety inspection clearance.",
            new_category=QualificationCategory.WARM,
            resolve_active_conversations=False,
        )
    assert "active safety-escalated or reply-locked conversation" in str(exc_info.value).lower()

    # 3. Dispatcher resolves lead qualification safety review AND active conversations together
    resolved_qual = await qual_svc.resolve_safety_review(
        hazard_lead.id,
        disp_user.id,
        "Customer requests standard furnace tune-up after safety inspection clearance.",
        new_category=QualificationCategory.WARM,
        resolve_active_conversations=True,
    )
    assert resolved_qual.requires_human is False
    assert resolved_qual.category == QualificationCategory.WARM.value

    # Verify conversation is now unlocked and in HUMAN_TAKEOVER
    fetched_conv = await conv_svc.get_conversation(conv.id)
    assert fetched_conv.is_automated_reply_locked is False
    assert fetched_conv.status == ConversationStatus.HUMAN_TAKEOVER.value
    assert fetched_conv.escalation_reason is None

    # Verify lead status is now QUALIFIED
    fetched_lead = await lead_svc.get_lead(hazard_lead.id)
    assert fetched_lead.status == LeadStatus.QUALIFIED.value

    # 4. Lead can now successfully book an appointment!
    appt = await appt_svc.schedule_appointment(
        lead_id=hazard_lead.id,
        service_id=s1.id,
        appointment_start=t_start,
        appointment_end=t_end,
        service_type=s1.service_name,
    )
    assert appt.id is not None
    assert appt.appointment_status == AppointmentStatus.CONFIRMED.value


# ============================================================================
# 8. REGRESSION TESTS: SAFETY RESOLUTION, IDENTITY & AUDIT LEDGER
# ============================================================================


@pytest.mark.asyncio
async def test_ordinary_unlock_cannot_clear_safety_lock(session: AsyncSession, seed_env: dict):
    """Verify ordinary unlock_automated_replies fails for safety escalations."""
    org1 = seed_env["org1"]
    l1 = seed_env["l1"]
    conv_svc = ConversationService(session, org1.id)

    # 1. ESCALATED_SAFETY status cannot be unlocked through ordinary unlock
    conv1 = await conv_svc.create_conversation(
        ConversationCreate(organization_id=org1.id, lead_id=l1.id, channel=ChannelType.SMS)
    )
    await conv_svc.trigger_safety_lock(conv1.id, hazard_reason="GAS_LEAK")
    with pytest.raises(InvalidOperationError) as exc_info:
        await conv_svc.unlock_automated_replies(conv1.id)
    assert "ordinary unlock method" in str(exc_info.value).lower()
    assert "resolve_safety_escalation" in str(exc_info.value).lower()

    # 2. HUMAN_TAKEOVER with escalation reason cannot be unlocked through ordinary unlock
    conv2 = await conv_svc.create_conversation(
        ConversationCreate(organization_id=org1.id, lead_id=l1.id, channel=ChannelType.WEB_CHAT)
    )
    await conv_svc.escalate_conversation(
        conv2.id, reason="Customer reported active chemical spill", lock_automated_reply=True
    )
    with pytest.raises(InvalidOperationError) as exc_info:
        await conv_svc.unlock_automated_replies(conv2.id)
    assert "ordinary unlock method" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_ordinary_unlock_preserves_non_safety_workflows(
    session: AsyncSession, seed_env: dict
):
    """Verify routine non-safety reply locks can still be cleared by ordinary unlock."""
    org1 = seed_env["org1"]
    l1 = seed_env["l1"]
    conv_svc = ConversationService(session, org1.id)

    # Create AI_ACTIVE conversation with temporary reply lock (e.g. rate limit pause)
    conv = await conv_svc.create_conversation(
        ConversationCreate(organization_id=org1.id, lead_id=l1.id, channel=ChannelType.SMS)
    )
    assert conv.status == ConversationStatus.AI_ACTIVE.value
    conv.is_automated_reply_locked = True
    conv.escalation_reason = None
    await session.flush()

    unlocked_conv = await conv_svc.unlock_automated_replies(conv.id)
    assert unlocked_conv.is_automated_reply_locked is False
    assert unlocked_conv.status == ConversationStatus.AI_ACTIVE.value


@pytest.mark.asyncio
async def test_safety_resolution_rejects_non_escalated_conversation(
    session: AsyncSession, seed_env: dict
):
    """Verify safety resolution cannot be called on normal non-escalated conversations."""
    org1 = seed_env["org1"]
    u1 = seed_env["u1"]
    l1 = seed_env["l1"]
    conv_svc = ConversationService(session, org1.id)

    conv = await conv_svc.create_conversation(
        ConversationCreate(organization_id=org1.id, lead_id=l1.id, channel=ChannelType.SMS)
    )
    assert conv.status == ConversationStatus.AI_ACTIVE.value
    assert conv.is_automated_reply_locked is False

    with pytest.raises(InvalidOperationError) as exc_info:
        await conv_svc.resolve_safety_escalation(
            conv.id,
            u1.id,
            "Attempting to resolve non-escalated conversation.",
        )
    assert "does not have an active safety escalation" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_repeated_safety_resolution_rejected(session: AsyncSession, seed_env: dict):
    """Verify repeated safety resolution on already resolved conversation is rejected."""
    org1 = seed_env["org1"]
    u1 = seed_env["u1"]
    l1 = seed_env["l1"]
    conv_svc = ConversationService(session, org1.id)

    # Lead 1 is already HOT (does not require human review)
    conv = await conv_svc.create_conversation(
        ConversationCreate(organization_id=org1.id, lead_id=l1.id, channel=ChannelType.SMS)
    )
    await conv_svc.trigger_safety_lock(conv.id, hazard_reason="SUSPECTED_ELECTRICAL_BURNING")

    # First resolution succeeds
    resolved = await conv_svc.resolve_safety_escalation(
        conv.id,
        u1.id,
        "Technician inspected and cleared wiring on site.",
    )
    assert resolved.status == ConversationStatus.HUMAN_TAKEOVER.value
    assert resolved.is_automated_reply_locked is False

    # Second resolution attempt fails
    with pytest.raises(InvalidOperationError) as exc_info:
        await conv_svc.resolve_safety_escalation(
            conv.id,
            u1.id,
            "Redundant second attempt to resolve.",
        )
    assert "already been resolved" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_safety_review_cannot_promote_cold_lead(session: AsyncSession, seed_env: dict):
    """Verify COLD lead cannot be upgraded to QUALIFIED via safety review resolution."""
    org1 = seed_env["org1"]
    u1 = seed_env["u1"]
    lead_svc = LeadService(session, org1.id)
    qual_svc = QualificationService(session, org1.id)

    cold_lead = await lead_svc.create_lead(
        LeadCreate(
            organization_id=org1.id,
            first_name="Cold",
            last_name="Caller",
            phone="+15559090001",
            postal_code="99999",
            service_type="Geothermal Heat Pump Installation",
            problem_description="Want to install ground source geothermal loops.",
            urgency=LeadUrgency.LOW,
            sms_consent_status=ConsentStatus.OPTED_IN,
        )
    )
    eval_res = await qual_svc.evaluate_lead(cold_lead.id)
    assert eval_res.category == QualificationCategory.COLD.value

    # Lead was automatically transitioned to UNQUALIFIED by evaluate_lead
    fetched_lead = await lead_svc.get_lead(cold_lead.id)
    assert fetched_lead.status == LeadStatus.UNQUALIFIED.value

    # Attempting to resolve safety review on UNQUALIFIED status is rejected
    with pytest.raises(InvalidOperationError) as exc_info:
        await qual_svc.resolve_safety_review(
            cold_lead.id,
            u1.id,
            "Attempting to clear safety review on COLD lead.",
        )
    assert "must be in qualifying status" in str(exc_info.value).lower()

    # Even if status is manually set to QUALIFYING, COLD qualification category is rejected
    fetched_lead.status = LeadStatus.QUALIFYING.value
    await session.flush()

    with pytest.raises(InvalidOperationError) as exc_info:
        await qual_svc.resolve_safety_review(
            cold_lead.id,
            u1.id,
            "Attempting to clear safety review on COLD evaluation.",
        )
    assert "does not require human review" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_safety_review_cannot_promote_unqualified_lead(session: AsyncSession, seed_env: dict):
    """Verify UNQUALIFIED lead cannot be upgraded to QUALIFIED via safety review resolution."""
    org1 = seed_env["org1"]
    u1 = seed_env["u1"]
    lead_svc = LeadService(session, org1.id)
    qual_svc = QualificationService(session, org1.id)

    unqual_lead = await lead_svc.create_lead(
        LeadCreate(
            organization_id=org1.id,
            first_name="Unqual",
            last_name="Caller",
            phone="+15559090002",
            postal_code="75001",
            service_type="AC Diagnostic & Repair",
            problem_description="Commercial chiller overhaul request.",
        )
    )
    await lead_svc.change_status(unqual_lead.id, LeadStatus.UNQUALIFIED)

    with pytest.raises(InvalidOperationError) as exc_info:
        await qual_svc.resolve_safety_review(
            unqual_lead.id,
            u1.id,
            "Attempting to clear safety review on UNQUALIFIED lead.",
        )
    assert "must be in qualifying status" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_safety_review_rejects_non_safety_human_review(session: AsyncSession, seed_env: dict):
    """Verify non-safety HUMAN_REVIEW (e.g. ambiguous service) cannot use safety resolution."""
    org1 = seed_env["org1"]
    u1 = seed_env["u1"]
    lead_svc = LeadService(session, org1.id)
    qual_svc = QualificationService(session, org1.id)

    ambiguous_lead = await lead_svc.create_lead(
        LeadCreate(
            organization_id=org1.id,
            first_name="Ambiguous",
            last_name="User",
            phone="+15559090003",
            postal_code="75001",
            service_type="Other",  # Ambiguous service
            problem_description="Weird rattle in attic.",
            urgency=LeadUrgency.MEDIUM,
            sms_consent_status=ConsentStatus.OPTED_IN,
        )
    )
    eval_res = await qual_svc.evaluate_lead(ambiguous_lead.id)
    assert eval_res.category == QualificationCategory.HUMAN_REVIEW.value
    assert eval_res.requires_human is True
    assert eval_res.recommended_action == "CLARIFY_SERVICE_REQUIREMENTS"

    # Attempting to resolve via safety pathway fails
    with pytest.raises(InvalidOperationError) as exc_info:
        await qual_svc.resolve_safety_review(
            ambiguous_lead.id,
            u1.id,
            "Staff clarified service code manually over phone.",
        )
    assert "not a safety-related emergency review" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_unresolved_safety_qualification_prevents_conversation_unlock(
    session: AsyncSession, seed_env: dict
):
    """Verify an active safety qualification prevents conversation unlocking."""
    org1 = seed_env["org1"]
    u1 = seed_env["u1"]
    lead_svc = LeadService(session, org1.id)
    qual_svc = QualificationService(session, org1.id)
    conv_svc = ConversationService(session, org1.id)

    hazard_lead = await lead_svc.create_lead(
        LeadCreate(
            organization_id=org1.id,
            first_name="Active",
            last_name="Hazard",
            phone="+15559090004",
            postal_code="75001",
            problem_description="Smell gas coming from heating vents!",
            urgency=LeadUrgency.EMERGENCY,
            sms_consent_status=ConsentStatus.OPTED_IN,
        )
    )
    qual_res = await qual_svc.evaluate_lead(hazard_lead.id)
    assert qual_res.requires_human is True

    conv = await conv_svc.create_conversation(
        ConversationCreate(organization_id=org1.id, lead_id=hazard_lead.id, channel=ChannelType.SMS)
    )
    await conv_svc.trigger_safety_lock(conv.id, hazard_reason="GAS_SMELL")

    with pytest.raises(InvalidOperationError) as exc_info:
        await conv_svc.resolve_safety_escalation(
            conv.id,
            u1.id,
            "Dispatcher spoke to customer and cleared chat lock.",
        )
    assert "qualification still requires human review" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_unresolved_safety_conversation_prevents_qualification_resolution(
    session: AsyncSession, seed_env: dict
):
    """Verify active safety conversation blocks qualification resolution unless flag is set."""
    org1 = seed_env["org1"]
    u1 = seed_env["u1"]
    lead_svc = LeadService(session, org1.id)
    qual_svc = QualificationService(session, org1.id)
    conv_svc = ConversationService(session, org1.id)

    hazard_lead = await lead_svc.create_lead(
        LeadCreate(
            organization_id=org1.id,
            first_name="Dual",
            last_name="Hazard",
            phone="+15559090005",
            postal_code="75001",
            problem_description="Carbon monoxide detector is beeping in basement!",
            urgency=LeadUrgency.EMERGENCY,
            sms_consent_status=ConsentStatus.OPTED_IN,
        )
    )
    await qual_svc.evaluate_lead(hazard_lead.id)

    conv = await conv_svc.create_conversation(
        ConversationCreate(organization_id=org1.id, lead_id=hazard_lead.id, channel=ChannelType.SMS)
    )
    await conv_svc.trigger_safety_lock(conv.id, hazard_reason="CO_ALARM")

    # Attempting to resolve qualification without resolving conversations fails
    with pytest.raises(InvalidOperationError) as exc_info:
        await qual_svc.resolve_safety_review(
            hazard_lead.id,
            u1.id,
            "Utility provider inspected meter and found zero CO ppm.",
            resolve_active_conversations=False,
        )
    assert "active safety-escalated or reply-locked conversation" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_safety_resolution_rejects_empty_or_trivial_notes(
    session: AsyncSession, seed_env: dict
):
    """Verify both conversation and qualification safety resolution reject empty/trivial notes."""
    org1 = seed_env["org1"]
    u1 = seed_env["u1"]
    l1 = seed_env["l1"]
    conv_svc = ConversationService(session, org1.id)
    qual_svc = QualificationService(session, org1.id)
    lead_svc = LeadService(session, org1.id)

    conv = await conv_svc.create_conversation(
        ConversationCreate(organization_id=org1.id, lead_id=l1.id, channel=ChannelType.SMS)
    )
    await conv_svc.trigger_safety_lock(conv.id, hazard_reason="GAS_LEAK")

    # Conversation resolution rejects empty or < 5 char notes
    for invalid_note in ["", "   ", "ok", "done"]:
        with pytest.raises(ValidationError) as exc_info:
            await conv_svc.resolve_safety_escalation(
                conv.id,
                u1.id,
                invalid_note,
            )
        assert "at least 5 characters" in str(exc_info.value).lower()

    # Lead qualification resolution rejects empty or < 5 char notes
    hazard_lead = await lead_svc.create_lead(
        LeadCreate(
            organization_id=org1.id,
            first_name="Note",
            last_name="Test",
            phone="+15559090006",
            postal_code="75001",
            problem_description="I smell gas near furnace burner!",
            urgency=LeadUrgency.EMERGENCY,
            sms_consent_status=ConsentStatus.OPTED_IN,
        )
    )
    await qual_svc.evaluate_lead(hazard_lead.id)

    for invalid_note in ["", "   ", "fix", "clr"]:
        with pytest.raises(ValidationError) as exc_info:
            await qual_svc.resolve_safety_review(
                hazard_lead.id,
                u1.id,
                invalid_note,
            )
        assert "at least 5 characters" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_safety_resolution_audit_records_verified(session: AsyncSession, seed_env: dict):
    """Verify audit log records capture exact context, timestamps, actor, and state transitions."""
    org1 = seed_env["org1"]
    u1 = seed_env["u1"]
    l1 = seed_env["l1"]
    conv_svc = ConversationService(session, org1.id)
    audit_repo = AuditLogRepository(session)

    # Lead l1 has HOT qualification (requires_human=False)
    conv = await conv_svc.create_conversation(
        ConversationCreate(organization_id=org1.id, lead_id=l1.id, channel=ChannelType.SMS)
    )
    await conv_svc.trigger_safety_lock(conv.id, hazard_reason="ELECTRICAL_ARCING")

    # Use ActorContext dataclass
    actor = ActorContext(user_id=u1.id, organization_id=org1.id)
    resolution_notes = "Master electrician replaced overloaded circuit breaker safely."

    resolved_conv = await conv_svc.resolve_safety_escalation(
        conv.id,
        actor,
        resolution_notes,
    )
    assert resolved_conv.status == ConversationStatus.HUMAN_TAKEOVER.value

    # Verify audit record persisted in same transaction
    audit_logs = await audit_repo.list_by_resource(org1.id, "conversation", str(conv.id))
    assert len(audit_logs) >= 1
    audit = audit_logs[0]

    assert audit.organization_id == org1.id
    assert audit.user_id == u1.id
    assert audit.action == "SAFETY_ESCALATION_RESOLVED"
    assert audit.resource_type == "conversation"
    assert audit.resource_id == str(conv.id)
    assert audit.changes["lead_id"] == str(l1.id)
    assert audit.changes["previous_status"] == ConversationStatus.ESCALATED_SAFETY.value
    assert audit.changes["new_status"] == ConversationStatus.HUMAN_TAKEOVER.value
    assert audit.changes["previous_reply_locked"] is True
    assert audit.changes["new_reply_locked"] is False
    assert audit.changes["previous_escalation_reason"] == "ELECTRICAL_ARCING"
    assert audit.changes["resolution_notes"] == resolution_notes
    assert audit.created_at is not None


@pytest.mark.asyncio
async def test_safety_resolution_audit_failure_rolls_back_transaction(
    session: AsyncSession, seed_env: dict
):
    """Verify failure to write audit log rolls back safety escalation resolution."""
    org1 = seed_env["org1"]
    u1 = seed_env["u1"]
    l1 = seed_env["l1"]
    conv_svc = ConversationService(session, org1.id)

    conv = await conv_svc.create_conversation(
        ConversationCreate(organization_id=org1.id, lead_id=l1.id, channel=ChannelType.SMS)
    )
    await conv_svc.trigger_safety_lock(conv.id, hazard_reason="FURNACE_CARBON_MONOXIDE")
    conv_id = conv.id

    # Monkeypatch audit_repo.log_event to simulate an unexpected persistence failure
    async def failing_log_event(*args, **kwargs):
        raise RuntimeError("Simulated AuditLog database failure")

    conv_svc.audit_repo.log_event = failing_log_event

    # Use a transaction savepoint to verify atomic rollback on audit failure
    try:
        async with session.begin_nested():
            await conv_svc.resolve_safety_escalation(
                conv_id,
                u1.id,
                "Dispatcher verified HVAC unit is turned off.",
            )
    except RuntimeError as exc:
        assert "Simulated AuditLog database failure" in str(exc)

    # Re-fetch conversation afresh: verify state is still ESCALATED_SAFETY and locked!
    refreshed_conv = await conv_svc.get_conversation(conv_id)
    assert refreshed_conv.status == ConversationStatus.ESCALATED_SAFETY.value
    assert refreshed_conv.is_automated_reply_locked is True
    assert refreshed_conv.escalation_reason == "FURNACE_CARBON_MONOXIDE"
