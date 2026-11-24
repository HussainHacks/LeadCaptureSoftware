"""Comprehensive tests for lead repository, service, deduplication, and lifecycle."""

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.exceptions import (
    EntityNotFoundError,
    InvalidOperationError,
    TenantAccessViolationError,
    ValidationError,
)
from app.core.phone import normalize_phone_number
from app.models import Base, Organization, User
from app.models.enums import LeadSource, LeadStatus, LeadUrgency
from app.schemas.lead import LeadCreate, LeadUpdate
from app.schemas.organization import OrganizationCreate
from app.schemas.user import UserCreate
from app.services import LeadService, OrganizationService, UserService

TEST_DB_NAME = "leadgen_test_lead_mgmt_db"


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


@pytest_asyncio.fixture
async def sample_org(session: AsyncSession) -> Organization:
    """Fixture creating an organization with an owner user."""
    user_service = UserService(session)
    org_service = OrganizationService(session)

    user = await user_service.register_user(
        UserCreate(
            email=f"owner.{uuid.uuid4().hex[:8]}@example.com",
            password="SecurePassword123!",
            first_name="Owner",
            last_name="Test",
        )
    )
    org, _ = await org_service.create_organization(
        user.id,
        OrganizationCreate(
            name="Austin Cool Air",
            slug=f"austin-cool-air-{uuid.uuid4().hex[:8]}",
        ),
    )
    return org


# ---------------------------------------------------------------------------
# 1. Lead Creation & Retrieval Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_lead_creation(session: AsyncSession, sample_org: Organization):
    """Verify creating a lead persists attributes, default status NEW, and score 0."""
    service = LeadService(session, sample_org.id)
    lead_data = LeadCreate(
        organization_id=sample_org.id,
        first_name="Jane",
        last_name="Smith",
        phone="(555) 234-5678",
        email="jane.smith@example.com",
        postal_code="78701",
        street_address="123 Congress Ave",
        service_type="Cooling",
        equipment_type="Central AC",
        problem_description="AC blowing warm air",
        urgency=LeadUrgency.HIGH,
        source=LeadSource.WEBSITE_FORM,
    )

    lead = await service.create_lead(lead_data)

    assert lead.id is not None
    assert lead.organization_id == sample_org.id
    assert lead.phone == "+15552345678"
    assert lead.email == "jane.smith@example.com"
    assert lead.status == LeadStatus.NEW.value
    assert lead.qualification_score == 0
    assert lead.urgency == LeadUrgency.HIGH.value
    assert lead.prior_lead_id is None
    assert lead.deleted_at is None


@pytest.mark.asyncio
async def test_lead_retrieval_by_id(session: AsyncSession, sample_org: Organization):
    """Verify retrieving a lead by ID returns matching record."""
    service = LeadService(session, sample_org.id)
    lead = await service.create_lead(
        LeadCreate(
            organization_id=sample_org.id,
            first_name="Robert",
            phone="555-345-6789",
        )
    )

    fetched = await service.get_lead(lead.id)
    assert fetched.id == lead.id
    assert fetched.first_name == "Robert"
    assert fetched.phone == "+15553456789"


@pytest.mark.asyncio
async def test_cross_tenant_retrieval_rejection(session: AsyncSession, sample_org: Organization):
    """Verify a lead owned by Org A cannot be fetched or accessed by Org B."""
    service_a = LeadService(session, sample_org.id)
    lead_a = await service_a.create_lead(
        LeadCreate(
            organization_id=sample_org.id,
            phone="555-456-7890",
            first_name="TenantA Lead",
        )
    )

    # Create Org B
    user_b = User(
        email=f"userb.{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hashed",
        first_name="User",
        last_name="B",
    )
    session.add(user_b)
    org_b = Organization(name="Org B HVAC", slug=f"org-b-{uuid.uuid4().hex[:8]}")
    session.add(org_b)
    await session.flush()

    service_b = LeadService(session, org_b.id)

    # Org B cannot get Org A's lead by ID
    with pytest.raises(EntityNotFoundError):
        await service_b.get_lead(lead_a.id)

    # Org B service rejects creating lead with Org A's ID
    with pytest.raises(TenantAccessViolationError):
        await service_b.create_lead(LeadCreate(organization_id=sample_org.id, phone="555-999-0000"))


# ---------------------------------------------------------------------------
# 2. Listing, Pagination & Filtering Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lead_listing_and_pagination(session: AsyncSession, sample_org: Organization):
    """Verify listing leads with pagination (limit and offset)."""
    service = LeadService(session, sample_org.id)

    for i in range(5):
        await service.create_lead(
            LeadCreate(
                organization_id=sample_org.id,
                phone=f"555-111-000{i}",
                first_name=f"Lead{i}",
                service_type=f"Type{i}",
            )
        )

    # First page: limit 2, offset 0
    page1 = await service.list_leads(limit=2, offset=0)
    assert len(page1) == 2

    # Second page: limit 2, offset 2
    page2 = await service.list_leads(limit=2, offset=2)
    assert len(page2) == 2
    assert page1[0].id != page2[0].id

    # Total count
    total = await service.count_leads()
    assert total == 5


@pytest.mark.asyncio
async def test_filtering_by_status_urgency_source_and_date(
    session: AsyncSession, sample_org: Organization
):
    """Verify filtering leads by status, urgency, source, and creation date bounds."""
    service = LeadService(session, sample_org.id)

    # Lead 1: Emergency, Web form
    l1 = await service.create_lead(
        LeadCreate(
            organization_id=sample_org.id,
            phone="555-222-0001",
            urgency=LeadUrgency.EMERGENCY,
            source=LeadSource.WEBSITE_FORM,
        )
    )
    # Lead 2: Low urgency, Webhook
    await service.create_lead(
        LeadCreate(
            organization_id=sample_org.id,
            phone="555-222-0002",
            urgency=LeadUrgency.LOW,
            source=LeadSource.WEBHOOK,
        )
    )

    # Transition Lead 1 to CONTACTED
    await service.change_status(l1.id, LeadStatus.CONTACTED)

    # Filter by status
    contacted_leads = await service.list_leads(status=LeadStatus.CONTACTED)
    assert len(contacted_leads) == 1
    assert contacted_leads[0].id == l1.id
    assert await service.count_leads(status=LeadStatus.CONTACTED) == 1

    # Filter by urgency
    emergency_leads = await service.list_leads(urgency=LeadUrgency.EMERGENCY)
    assert len(emergency_leads) == 1
    assert emergency_leads[0].id == l1.id

    # Filter by source
    webhook_leads = await service.list_leads(source=LeadSource.WEBHOOK)
    assert len(webhook_leads) == 1

    # Filter by date bounds
    now = datetime.now(UTC)
    recent = await service.list_leads(created_after=now - timedelta(hours=1))
    assert len(recent) == 2

    future = await service.list_leads(created_after=now + timedelta(hours=1))
    assert len(future) == 0


# ---------------------------------------------------------------------------
# 3. Update, State Machine & Soft-Delete Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_and_invalid_updates(session: AsyncSession, sample_org: Organization):
    """Verify permitted field updates and rejection of updates to soft-deleted leads."""
    service = LeadService(session, sample_org.id)
    lead = await service.create_lead(
        LeadCreate(
            organization_id=sample_org.id,
            phone="555-333-1111",
            first_name="Original",
        )
    )

    # Valid update
    update_data = LeadUpdate(
        first_name="UpdatedName",
        phone="555-333-2222",
        email="updated@example.com",
        problem_description="Updated description",
    )
    updated = await service.update_lead(lead.id, update_data)
    assert updated.first_name == "UpdatedName"
    assert updated.phone == "+15553332222"
    assert updated.email == "updated@example.com"
    assert updated.problem_description == "Updated description"

    # Soft delete lead
    await service.soft_delete_lead(lead.id)

    # Attempting update on soft-deleted lead must raise InvalidOperationError
    with pytest.raises(InvalidOperationError):
        await service.update_lead(lead.id, LeadUpdate(first_name="CannotUpdate"))


@pytest.mark.asyncio
async def test_status_transition_validation(session: AsyncSession, sample_org: Organization):
    """Verify valid status progression and rejection of invalid status transitions."""
    service = LeadService(session, sample_org.id)
    lead = await service.create_lead(
        LeadCreate(
            organization_id=sample_org.id,
            phone="555-444-1111",
        )
    )
    assert lead.status == LeadStatus.NEW.value

    # 1. Invalid jump directly to APPOINTMENT_BOOKED from NEW
    with pytest.raises(InvalidOperationError):
        await service.change_status(lead.id, LeadStatus.APPOINTMENT_BOOKED)

    # 2. Valid progression: NEW -> CONTACTED -> QUALIFYING -> QUALIFIED ->
    # APPOINTMENT_OFFERED -> APPOINTMENT_BOOKED
    await service.change_status(lead.id, LeadStatus.CONTACTED)
    assert lead.status == LeadStatus.CONTACTED.value

    await service.change_status(lead.id, LeadStatus.QUALIFYING)
    assert lead.status == LeadStatus.QUALIFYING.value

    await service.change_status(lead.id, LeadStatus.QUALIFIED)
    assert lead.status == LeadStatus.QUALIFIED.value

    await service.change_status(lead.id, LeadStatus.APPOINTMENT_OFFERED)
    assert lead.status == LeadStatus.APPOINTMENT_OFFERED.value

    await service.change_status(lead.id, LeadStatus.APPOINTMENT_BOOKED)
    assert lead.status == LeadStatus.APPOINTMENT_BOOKED.value

    # 3. Invalid backward transition: APPOINTMENT_BOOKED -> NEW
    with pytest.raises(InvalidOperationError):
        await service.change_status(lead.id, LeadStatus.NEW)


@pytest.mark.asyncio
async def test_urgency_updates(session: AsyncSession, sample_org: Organization):
    """Verify changing urgency levels through validated service methods."""
    service = LeadService(session, sample_org.id)
    lead = await service.create_lead(
        LeadCreate(
            organization_id=sample_org.id,
            phone="555-555-1111",
            urgency=LeadUrgency.LOW,
        )
    )
    assert lead.urgency == LeadUrgency.LOW.value

    # Upgrade to HIGH
    await service.change_urgency(lead.id, LeadUrgency.HIGH)
    assert lead.urgency == LeadUrgency.HIGH.value

    # Escalate to EMERGENCY
    await service.change_urgency(lead.id, LeadUrgency.EMERGENCY)
    assert lead.urgency == LeadUrgency.EMERGENCY.value


@pytest.mark.asyncio
async def test_soft_deletion(session: AsyncSession, sample_org: Organization):
    """Verify soft-deletion sets deleted_at and filters lead from active queries."""
    service = LeadService(session, sample_org.id)
    lead = await service.create_lead(
        LeadCreate(
            organization_id=sample_org.id,
            phone="555-666-1111",
            first_name="ActiveLead",
        )
    )

    deleted_lead = await service.soft_delete_lead(lead.id)
    assert deleted_lead.deleted_at is not None

    # Standard get_lead raises EntityNotFoundError
    with pytest.raises(EntityNotFoundError):
        await service.get_lead(lead.id, include_deleted=False)

    # get_lead with include_deleted=True returns the record
    fetched = await service.get_lead(lead.id, include_deleted=True)
    assert fetched.id == lead.id

    # Excluded from active count
    assert await service.count_leads(include_deleted=False) == 0
    assert await service.count_leads(include_deleted=True) == 1


# ---------------------------------------------------------------------------
# 4. Duplicate Detection & Multi-Issue Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_detection_within_14_days(session: AsyncSession, sample_org: Organization):
    """Case A: Second inquiry for the same issue on an active lead returns existing lead."""
    service = LeadService(session, sample_org.id)
    lead_data = LeadCreate(
        organization_id=sample_org.id,
        phone="(555) 777-1234",
        first_name="Followup Customer",
        service_type="Heating Repair",
    )

    # First inquiry creates the initial lead
    lead1 = await service.create_lead(lead_data)
    assert lead1.id is not None

    # Second inquiry within 14 days with same phone and issue
    lead2 = await service.create_lead(lead_data)

    # Case A: Same lead returned without creating duplicate row
    assert lead2.id == lead1.id
    assert await service.count_leads() == 1


@pytest.mark.asyncio
async def test_no_duplicate_match_outside_the_window(
    session: AsyncSession, sample_org: Organization
):
    """Verify an inquiry outside the rolling window creates a separate lead."""
    service = LeadService(session, sample_org.id)
    lead_data = LeadCreate(
        organization_id=sample_org.id,
        phone="555-888-1234",
        first_name="Old Customer",
    )

    lead1 = await service.create_lead(lead_data)

    # Manually age lead1 to 20 days ago
    lead1.created_at = datetime.now(UTC) - timedelta(days=20)
    await session.flush()

    # New inquiry with 14-day dedup window: should NOT match lead1
    lead2 = await service.create_lead(lead_data, dedup_window_days=14)

    assert lead2.id != lead1.id
    assert lead2.prior_lead_id is None
    assert await service.count_leads() == 2


@pytest.mark.asyncio
async def test_duplicate_matching_across_different_organizations(
    session: AsyncSession, sample_org: Organization
):
    """Verify duplicate detection is tenant-scoped; same phone in another org is not matched."""
    service_a = LeadService(session, sample_org.id)
    shared_phone = "555-999-5555"

    lead_a = await service_a.create_lead(
        LeadCreate(
            organization_id=sample_org.id,
            phone=shared_phone,
            first_name="Customer Org A",
        )
    )

    # Create Org B
    user_b = User(
        email=f"user.b.{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hash",
        first_name="User",
        last_name="B",
    )
    session.add(user_b)
    org_b = Organization(name="Org B Co", slug=f"org-b-{uuid.uuid4().hex[:8]}")
    session.add(org_b)
    await session.flush()

    service_b = LeadService(session, org_b.id)
    lead_b = await service_b.create_lead(
        LeadCreate(
            organization_id=org_b.id,
            phone=shared_phone,
            first_name="Customer Org B",
        )
    )

    # Must be distinct leads across tenants
    assert lead_b.id != lead_a.id
    assert lead_b.organization_id == org_b.id
    assert lead_b.prior_lead_id is None


@pytest.mark.asyncio
async def test_different_issues_remaining_distinct(session: AsyncSession, sample_org: Organization):
    """Case B: Distinct HVAC issues from same phone create new lead with prior_lead_id."""
    service = LeadService(session, sample_org.id)
    customer_phone = "(555) 123-9999"

    # 1. First inquiry: AC repair
    lead_ac = await service.create_lead(
        LeadCreate(
            organization_id=sample_org.id,
            phone=customer_phone,
            service_type="Cooling Repair",
            problem_description="AC unit not cooling",
        )
    )

    # 2. Second inquiry: Furnace installation (distinct HVAC issue)
    lead_heater = await service.create_lead(
        LeadCreate(
            organization_id=sample_org.id,
            phone=customer_phone,
            service_type="Heating Install",
            problem_description="Garage heater install quote",
        )
    )

    # Case B: Creates distinct lead and links prior_lead_id
    assert lead_heater.id != lead_ac.id
    assert lead_heater.prior_lead_id == lead_ac.id
    assert await service.count_leads() == 2


# ---------------------------------------------------------------------------
# 5. Validation & Transaction Safety Tests
# ---------------------------------------------------------------------------


def test_phone_normalization_formats():
    """Verify diverse North American phone formats normalize to E.164 (+1XXXXXXXXXX)."""
    assert normalize_phone_number("(555) 234-5678") == "+15552345678"
    assert normalize_phone_number("555.234.5678") == "+15552345678"
    assert normalize_phone_number("555-234-5678") == "+15552345678"
    assert normalize_phone_number("1-555-234-5678") == "+15552345678"
    assert normalize_phone_number("+1 555 234 5678") == "+15552345678"
    assert normalize_phone_number("+15552345678") == "+15552345678"


def test_invalid_phone_formats():
    """Verify malformed or incomplete phone numbers raise ValidationError."""
    with pytest.raises(ValidationError):
        normalize_phone_number("12345")

    with pytest.raises(ValidationError):
        normalize_phone_number("not-a-number")

    with pytest.raises(ValidationError):
        normalize_phone_number("   ")


@pytest.mark.asyncio
async def test_invalid_input_rejection(session: AsyncSession, sample_org: Organization):
    """Verify invalid email or excessive field lengths are rejected with ValidationError."""
    service = LeadService(session, sample_org.id)

    # 1. Invalid email rejected by service domain validation
    with pytest.raises(ValidationError):
        await service.create_lead(
            LeadCreate(
                organization_id=sample_org.id,
                phone="555-123-4567",
                email="invalid-no-domain",
            )
        )

    # 2. Schema-level validation rejects excessive first name length
    with pytest.raises(PydanticValidationError):
        LeadCreate(
            organization_id=sample_org.id,
            phone="555-123-4567",
            first_name="A" * 85,
        )

    # 3. Domain validation in service rejects excessive length even if constructed directly
    long_name_lead = LeadCreate.model_construct(
        organization_id=sample_org.id,
        phone="555-123-4567",
        first_name="A" * 85,
    )
    with pytest.raises(ValidationError):
        await service.create_lead(long_name_lead)


@pytest.mark.asyncio
async def test_repository_transaction_behavior(session: AsyncSession, sample_org: Organization):
    """Verify repository operations flush without committing, allowing transaction rollback."""
    service = LeadService(session, sample_org.id)

    lead = await service.create_lead(
        LeadCreate(
            organization_id=sample_org.id,
            phone="555-000-1111",
            first_name="Uncommitted",
        )
    )
    lead_id = lead.id
    assert lead_id is not None

    # Roll back transaction
    await session.rollback()

    # Lead must not exist in DB after rollback
    with pytest.raises(EntityNotFoundError):
        await service.get_lead(lead_id)
