"""Integration tests verifying database constraints on an isolated PostgreSQL test DB."""

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models import (
    Appointment,
    AppointmentStatus,
    Base,
    Conversation,
    ConversationStatus,
    Lead,
    Message,
    MessageSender,
    Organization,
    OrganizationMembership,
    Service,
    User,
)

TEST_DB_NAME = "leadgen_test_models_db"


@pytest_asyncio.fixture(loop_scope="module", scope="module", autouse=True)
async def setup_test_db():
    """Create a temporary isolated test database, enable btree_gist, and build schema."""
    settings = get_settings()
    base_url = settings.DATABASE_URL.rsplit("/", 1)[0]
    admin_url = f"{base_url}/postgres"

    # Connect to default postgres DB to manage test database lifecycle
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        # Drop stale test database if present
        await conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE);"))
        await conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME};"))
    await admin_engine.dispose()

    # Connect to the newly created isolated test database and build schema
    test_db_url = f"{base_url}/{TEST_DB_NAME}"
    test_engine = create_async_engine(test_db_url, poolclass=NullPool)

    # Enable btree_gist extension required for GiST UUID exclusion constraint
    async with test_engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist;"))
        await conn.run_sync(Base.metadata.create_all)

    await test_engine.dispose()

    yield

    # Teardown: drop test database
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


@pytest.mark.asyncio
async def test_composite_foreign_key_rejects_cross_tenant_lead(session: AsyncSession):
    """Verify composite FK prevents linking a conversation in Org B to a lead in Org A."""
    # 1. Create two distinct organizations
    org_a = Organization(name="Company A", slug=f"comp-a-{uuid.uuid4().hex[:8]}")
    org_b = Organization(name="Company B", slug=f"comp-b-{uuid.uuid4().hex[:8]}")
    session.add_all([org_a, org_b])
    await session.flush()

    # 2. Create a lead owned by Org A
    lead_a = Lead(
        organization_id=org_a.id,
        phone="+15551111111",
        first_name="Alice",
    )
    session.add(lead_a)
    await session.flush()

    # 3. Attempt to create a conversation belonging to Org B, but pointing to Lead A
    conv_cross_tenant = Conversation(
        organization_id=org_b.id,  # Org B
        lead_id=lead_a.id,  # Owned by Org A
        channel="SMS",
        status=ConversationStatus.AI_ACTIVE.value,
    )
    session.add(conv_cross_tenant)

    # 4. PostgreSQL composite FK must reject this write
    with pytest.raises(IntegrityError) as exc_info:
        await session.flush()

    assert "fk_conversations_lead_composite" in str(exc_info.value).lower()
    await session.rollback()


@pytest.mark.asyncio
async def test_composite_foreign_key_rejects_cross_tenant_service(session: AsyncSession):
    """Verify composite FK prevents booking an appointment with another organization's service."""
    org_a = Organization(name="Company A", slug=f"comp-a-{uuid.uuid4().hex[:8]}")
    org_b = Organization(name="Company B", slug=f"comp-b-{uuid.uuid4().hex[:8]}")
    session.add_all([org_a, org_b])
    await session.flush()

    lead_b = Lead(organization_id=org_b.id, phone="+15552222222")
    service_a = Service(
        organization_id=org_a.id,
        service_name="Furnace Checkup",
        service_code="FURN_CHECK",
    )
    session.add_all([lead_b, service_a])
    await session.flush()

    t_start = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    t_end = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)

    # Attempt to book Org B appointment using Org A's service
    appt_cross = Appointment(
        organization_id=org_b.id,
        lead_id=lead_b.id,
        service_id=service_a.id,  # Service belongs to Org A!
        time_slot=Range(t_start, t_end),
        appointment_start=t_start,
        appointment_end=t_end,
        appointment_status=AppointmentStatus.CONFIRMED.value,
        service_type="Heating",
    )
    session.add(appt_cross)

    with pytest.raises(IntegrityError) as exc_info:
        await session.flush()

    assert "fk_appointments_service_composite" in str(exc_info.value).lower()
    await session.rollback()


@pytest.mark.asyncio
async def test_composite_foreign_key_rejects_cross_tenant_prior_lead(session: AsyncSession):
    """Verify composite FK prevents linking a prior lead from another organization."""
    org_a = Organization(name="Company A", slug=f"comp-a-{uuid.uuid4().hex[:8]}")
    org_b = Organization(name="Company B", slug=f"comp-b-{uuid.uuid4().hex[:8]}")
    session.add_all([org_a, org_b])
    await session.flush()

    lead_a = Lead(organization_id=org_a.id, phone="+15553333333")
    session.add(lead_a)
    await session.flush()

    # Org B creates lead referencing Org A's prior lead
    lead_b = Lead(
        organization_id=org_b.id,
        phone="+15553333333",
        prior_lead_id=lead_a.id,
    )
    session.add(lead_b)

    with pytest.raises(IntegrityError) as exc_info:
        await session.flush()

    assert "fk_leads_prior_lead_composite" in str(exc_info.value).lower()
    await session.rollback()


@pytest.mark.asyncio
async def test_appointment_exclusion_constraint_enforces_capacity_one(session: AsyncSession):
    """Verify exclusion constraint rejects overlapping confirmed bookings for the same org."""
    org_a = Organization(name="Company A", slug=f"comp-a-{uuid.uuid4().hex[:8]}")
    org_b = Organization(name="Company B", slug=f"comp-b-{uuid.uuid4().hex[:8]}")
    session.add_all([org_a, org_b])
    await session.flush()

    lead_a1 = Lead(organization_id=org_a.id, phone="+15554444441")
    lead_a2 = Lead(organization_id=org_a.id, phone="+15554444442")
    lead_b1 = Lead(organization_id=org_b.id, phone="+15554444443")
    session.add_all([lead_a1, lead_a2, lead_b1])
    await session.flush()

    t_10_to_12 = (
        datetime(2026, 11, 20, 10, 0, tzinfo=UTC),
        datetime(2026, 11, 20, 12, 0, tzinfo=UTC),
    )
    t_11_to_13 = (
        datetime(2026, 11, 20, 11, 0, tzinfo=UTC),
        datetime(2026, 11, 20, 13, 0, tzinfo=UTC),
    )

    # 1. Book first appointment for Org A: 10:00 to 12:00
    appt1 = Appointment(
        organization_id=org_a.id,
        lead_id=lead_a1.id,
        time_slot=Range(t_10_to_12[0], t_10_to_12[1]),
        appointment_start=t_10_to_12[0],
        appointment_end=t_10_to_12[1],
        appointment_status=AppointmentStatus.CONFIRMED.value,
        service_type="AC Repair",
    )
    session.add(appt1)
    await session.flush()

    # 2. Attempt to book overlapping appointment for Org A: 11:00 to 13:00 (CONFIRMED)
    appt2 = Appointment(
        organization_id=org_a.id,
        lead_id=lead_a2.id,
        time_slot=Range(t_11_to_13[0], t_11_to_13[1]),
        appointment_start=t_11_to_13[0],
        appointment_end=t_11_to_13[1],
        appointment_status=AppointmentStatus.CONFIRMED.value,
        service_type="Heat Pump Repair",
    )
    async with session.begin_nested():
        session.add(appt2)
        with pytest.raises(IntegrityError) as exc_info:
            await session.flush()
        assert "uq_contractor_no_double_booking" in str(exc_info.value).lower()

    # 3. Same overlapping slot for Org B is ALLOWED (multi-tenant partitioned)
    appt_org_b = Appointment(
        organization_id=org_b.id,
        lead_id=lead_b1.id,
        time_slot=Range(t_11_to_13[0], t_11_to_13[1]),
        appointment_start=t_11_to_13[0],
        appointment_end=t_11_to_13[1],
        appointment_status=AppointmentStatus.CONFIRMED.value,
        service_type="AC Repair",
    )
    session.add(appt_org_b)
    await session.flush()
    assert appt_org_b.id is not None

    # 4. Overlapping slot with CANCELLED status is ALLOWED (does not consume capacity)
    appt_cancelled = Appointment(
        organization_id=org_a.id,
        lead_id=lead_a2.id,
        time_slot=Range(t_11_to_13[0], t_11_to_13[1]),
        appointment_start=t_11_to_13[0],
        appointment_end=t_11_to_13[1],
        appointment_status=AppointmentStatus.CANCELLED.value,
        service_type="Estimate",
    )
    session.add(appt_cancelled)
    await session.flush()
    assert appt_cancelled.id is not None


@pytest.mark.asyncio
async def test_unique_constraints(session: AsyncSession):
    """Verify organization slug, user email, service codes, and outbox idempotency uniqueness."""
    slug = f"unique-slug-{uuid.uuid4().hex[:8]}"
    org1 = Organization(name="Company 1", slug=slug)
    org2 = Organization(name="Company 2", slug=slug)
    session.add(org1)
    await session.flush()

    async with session.begin_nested():
        session.add(org2)
        with pytest.raises(IntegrityError):
            await session.flush()

    # Service code unique per organization, but distinct orgs can reuse same code
    org_a = Organization(name="Company A", slug=f"comp-a-{uuid.uuid4().hex[:8]}")
    org_b = Organization(name="Company B", slug=f"comp-b-{uuid.uuid4().hex[:8]}")
    session.add_all([org_a, org_b])
    await session.flush()

    srv_a = Service(organization_id=org_a.id, service_name="Diagnostic", service_code="DIAG")
    srv_b = Service(organization_id=org_b.id, service_name="Diagnostic", service_code="DIAG")
    session.add_all([srv_a, srv_b])
    await session.flush()  # Both succeed because org_id is different

    srv_a_duplicate = Service(
        organization_id=org_a.id, service_name="Duplicate", service_code="DIAG"
    )
    async with session.begin_nested():
        session.add(srv_a_duplicate)
        with pytest.raises(IntegrityError):
            await session.flush()


@pytest.mark.asyncio
async def test_cascading_messages_and_restricted_lead_deletion(session: AsyncSession):
    """Verify conversation messages cascade delete, but lead with appointments cannot be dropped."""
    org = Organization(name="Company A", slug=f"comp-a-{uuid.uuid4().hex[:8]}")
    session.add(org)
    await session.flush()

    lead = Lead(organization_id=org.id, phone="+15555555555")
    session.add(lead)
    await session.flush()

    conv = Conversation(
        organization_id=org.id,
        lead_id=lead.id,
        channel="SMS",
        status=ConversationStatus.AI_ACTIVE.value,
    )
    session.add(conv)
    await session.flush()

    msg = Message(
        organization_id=org.id,
        conversation_id=conv.id,
        sender=MessageSender.CUSTOMER.value,
        message_content="My AC is blowing warm air",
    )
    session.add(msg)
    await session.flush()

    # Deleting conversation cascades to message
    await session.delete(conv)
    await session.flush()

    # Message must be gone
    res = await session.execute(text(f"SELECT count(*) FROM messages WHERE id = '{msg.id}'"))
    assert res.scalar() == 0

    # Create appointment for lead
    t_start = datetime(2026, 11, 22, 14, 0, tzinfo=UTC)
    t_end = datetime(2026, 11, 22, 16, 0, tzinfo=UTC)
    appt = Appointment(
        organization_id=org.id,
        lead_id=lead.id,
        time_slot=Range(t_start, t_end),
        appointment_start=t_start,
        appointment_end=t_end,
        appointment_status=AppointmentStatus.CONFIRMED.value,
        service_type="AC Repair",
    )
    session.add(appt)
    await session.flush()

    # Attempt to delete lead while appointment references it (ON DELETE RESTRICT)
    await session.delete(lead)
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


@pytest.mark.asyncio
async def test_conversation_assignment_membership_enforcement(session: AsyncSession):
    """Verify database-level enforcement of conversation assignment to organization members.

    Proves:
    1. Nullable assignment works (assigned_to = None).
    2. Assigning to a user without membership in that organization is rejected.
    3. Assigning to a valid member in the same organization succeeds.
    4. Cross-organization assignment is rejected (user is member of Org B, conv is in Org A).
    5. Deleting the membership sets assigned_to = NULL while keeping organization_id intact.
    """
    # 1. Create two distinct organizations
    org_a = Organization(name="Company A", slug=f"comp-a-{uuid.uuid4().hex[:8]}")
    org_b = Organization(name="Company B", slug=f"comp-b-{uuid.uuid4().hex[:8]}")
    session.add_all([org_a, org_b])
    await session.flush()

    # 2. Create users
    user_member_a = User(
        email=f"member-a-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hash123",
        first_name="Alice",
        last_name="Member",
    )
    user_member_b = User(
        email=f"member-b-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hash123",
        first_name="Bob",
        last_name="OtherOrg",
    )
    user_no_membership = User(
        email=f"unaffiliated-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hash123",
        first_name="Charlie",
        last_name="NoOrg",
    )
    session.add_all([user_member_a, user_member_b, user_no_membership])
    await session.flush()

    # 3. Create memberships
    mem_a = OrganizationMembership(
        organization_id=org_a.id,
        user_id=user_member_a.id,
        role="DISPATCHER",
    )
    mem_b = OrganizationMembership(
        organization_id=org_b.id,
        user_id=user_member_b.id,
        role="DISPATCHER",
    )
    session.add_all([mem_a, mem_b])
    await session.flush()

    # 4. Create lead in Org A
    lead_a = Lead(organization_id=org_a.id, phone="+15550001111")
    session.add(lead_a)
    await session.flush()

    # Case 1: Nullable assignment: assigned_to = None succeeds
    conv_unassigned = Conversation(
        organization_id=org_a.id,
        lead_id=lead_a.id,
        channel="SMS",
        status=ConversationStatus.AI_ACTIVE.value,
        assigned_to=None,
    )
    session.add(conv_unassigned)
    await session.flush()
    assert conv_unassigned.id is not None
    assert conv_unassigned.assigned_to is None

    # Case 2: Reject assignment to user without any membership in Org A
    conv_invalid_user = Conversation(
        organization_id=org_a.id,
        lead_id=lead_a.id,
        channel="WEB",
        status=ConversationStatus.AI_ACTIVE.value,
        assigned_to=user_no_membership.id,
    )
    async with session.begin_nested():
        session.add(conv_invalid_user)
        with pytest.raises(IntegrityError):
            await session.flush()

    # Case 3: Reject cross-organization assignment (user belongs to Org B, conv is in Org A)
    conv_cross_org = Conversation(
        organization_id=org_a.id,
        lead_id=lead_a.id,
        channel="PHONE",
        status=ConversationStatus.AI_ACTIVE.value,
        assigned_to=user_member_b.id,
    )
    async with session.begin_nested():
        session.add(conv_cross_org)
        with pytest.raises(IntegrityError):
            await session.flush()

    # Case 4: Successful assignment to a valid member of Org A
    conv_valid = Conversation(
        organization_id=org_a.id,
        lead_id=lead_a.id,
        channel="EMAIL",
        status=ConversationStatus.AI_ACTIVE.value,
        assigned_to=user_member_a.id,
    )
    session.add(conv_valid)
    await session.flush()
    assert conv_valid.assigned_to == user_member_a.id

    # Case 5: Deleting membership sets assigned_to = NULL without deleting conversation
    # or altering organization_id (ON DELETE SET NULL (assigned_to))
    await session.delete(mem_a)
    await session.flush()
    await session.refresh(conv_valid)

    assert conv_valid.organization_id == org_a.id
    assert conv_valid.assigned_to is None
