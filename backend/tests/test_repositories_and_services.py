"""Tests validating repository and service foundations, multi-tenant isolation, and exceptions."""

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.exceptions import (
    AppException,
    EntityAlreadyExistsError,
    EntityNotFoundError,
    InvalidOperationError,
    TenantAccessViolationError,
)
from app.models import Base, Lead, Organization, Service, User
from app.repositories import (
    LeadRepository,
    ServiceRepository,
    UserRepository,
)
from app.services import TenantService

TEST_DB_NAME = "leadgen_test_repos_db"


@pytest_asyncio.fixture(loop_scope="module", scope="module", autouse=True)
async def setup_test_db():
    """Create a temporary isolated test database, enable btree_gist, and build schema."""
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


# ---------------------------------------------------------------------------
# 1. Tenant Scoping & Isolation Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_scoped_queries_return_only_own_records(session: AsyncSession):
    """Verify tenant repository list and count queries return only records for the requested org."""
    org_a = Organization(name="Company A", slug=f"comp-a-{uuid.uuid4().hex[:8]}")
    org_b = Organization(name="Company B", slug=f"comp-b-{uuid.uuid4().hex[:8]}")
    session.add_all([org_a, org_b])
    await session.flush()

    lead_repo = LeadRepository(session)

    # Add 3 leads for Org A and 2 leads for Org B
    for i in range(3):
        lead = Lead(organization_id=org_a.id, phone=f"+1555000000{i}", first_name=f"LeadA{i}")
        await lead_repo.add(org_a.id, lead)

    for i in range(2):
        lead = Lead(organization_id=org_b.id, phone=f"+1555111111{i}", first_name=f"LeadB{i}")
        await lead_repo.add(org_b.id, lead)

    # Verify count per tenant
    assert await lead_repo.count(org_a.id) == 3
    assert await lead_repo.count(org_b.id) == 2

    # Verify listing per tenant
    leads_a = await lead_repo.list(org_a.id)
    assert len(leads_a) == 3
    assert all(lead_item.organization_id == org_a.id for lead_item in leads_a)

    leads_b = await lead_repo.list(org_b.id)
    assert len(leads_b) == 2
    assert all(lead_item.organization_id == org_b.id for lead_item in leads_b)


@pytest.mark.asyncio
async def test_cross_tenant_record_cannot_be_retrieved_by_id(session: AsyncSession):
    """Verify a tenant-scoped repo cannot fetch records owned by a different organization."""
    org_a = Organization(name="Company A", slug=f"comp-a-{uuid.uuid4().hex[:8]}")
    org_b = Organization(name="Company B", slug=f"comp-b-{uuid.uuid4().hex[:8]}")
    session.add_all([org_a, org_b])
    await session.flush()

    lead_repo = LeadRepository(session)
    lead_a = Lead(organization_id=org_a.id, phone="+15552223333", first_name="TargetLead")
    await lead_repo.add(org_a.id, lead_a)

    # 1. Fetching lead_a via Org A succeeds
    fetched = await lead_repo.get_by_id(org_a.id, lead_a.id)
    assert fetched is not None
    assert fetched.id == lead_a.id

    # 2. Fetching lead_a using Org B returns None
    cross_fetched = await lead_repo.get_by_id(org_b.id, lead_a.id)
    assert cross_fetched is None

    # 3. get_by_id_or_raise with Org B raises EntityNotFoundError
    with pytest.raises(EntityNotFoundError) as exc_info:
        await lead_repo.get_by_id_or_raise(org_b.id, lead_a.id)
    assert "Lead" in str(exc_info.value)
    assert str(lead_a.id) in str(exc_info.value)


@pytest.mark.asyncio
async def test_record_uuid_alone_cannot_bypass_organization_filtering(session: AsyncSession):
    """Verify that knowing a record's UUID does not grant access across tenant boundaries."""
    org_a = Organization(name="Company A", slug=f"comp-a-{uuid.uuid4().hex[:8]}")
    org_b = Organization(name="Company B", slug=f"comp-b-{uuid.uuid4().hex[:8]}")
    session.add_all([org_a, org_b])
    await session.flush()

    service_repo = ServiceRepository(session)
    service_a = Service(
        organization_id=org_a.id,
        service_name="Furnace Tuneup",
        service_code="TUNEUP",
        estimated_duration_minutes=60,
    )
    await service_repo.add(org_a.id, service_a)
    known_uuid = service_a.id

    # Attempt access using random organization UUID
    random_org_id = uuid.uuid4()
    assert await service_repo.get_by_id(random_org_id, known_uuid) is None

    # Attempt cross-tenant deletion by ID: returns False and does NOT delete service_a
    deleted = await service_repo.delete(org_b.id, known_uuid)
    assert deleted is False
    assert await service_repo.get_by_id(org_a.id, known_uuid) is not None

    # Attempt cross-tenant addition with mismatched organization_id
    service_mismatched = Service(
        organization_id=org_a.id,
        service_name="Mismatched Org Service",
        service_code="MISMATCH",
        estimated_duration_minutes=30,
    )
    with pytest.raises(TenantAccessViolationError):
        await service_repo.add(org_b.id, service_mismatched)

    # Attempt cross-tenant entity deletion with mismatched organization_id
    with pytest.raises(TenantAccessViolationError):
        await service_repo.delete_entity(org_b.id, service_a)


# ---------------------------------------------------------------------------
# 2. Transaction Boundary Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repository_writes_do_not_commit_transactions(session: AsyncSession):
    """Verify repository operations flush but do not commit."""
    org = Organization(name="Company Test", slug=f"comp-{uuid.uuid4().hex[:8]}")
    session.add(org)
    await session.flush()

    lead_repo = LeadRepository(session)
    lead = Lead(organization_id=org.id, phone="+15554445555", first_name="UncommittedLead")

    # Repository add flushes entity (populating defaults/ID) without committing
    await lead_repo.add(org.id, lead)
    lead_id = lead.id
    assert lead_id is not None

    # Roll back the active transaction
    await session.rollback()

    # The lead must NOT exist in the database after rollback
    found = await lead_repo.get_by_id(org.id, lead_id)
    assert found is None


# ---------------------------------------------------------------------------
# 3. Service Layer Foundation Tests
# ---------------------------------------------------------------------------


class SampleTenantBusinessService(TenantService):
    """Example business service demonstrating repository injection and tenant scoping."""

    def __init__(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        lead_repo: LeadRepository | None = None,
    ) -> None:
        super().__init__(session, organization_id)
        self.lead_repo = lead_repo or LeadRepository(session)

    async def register_lead(self, phone: str, first_name: str) -> Lead:
        """Register a new lead within the bound organization scope."""
        lead = Lead(
            organization_id=self.organization_id,
            phone=phone,
            first_name=first_name,
        )
        return await self.lead_repo.add(self.organization_id, lead)

    async def retrieve_lead(self, lead_id: uuid.UUID) -> Lead:
        """Retrieve a lead within the bound organization scope."""
        return await self.lead_repo.get_by_id_or_raise(self.organization_id, lead_id)

    async def perform_cross_org_operation(self, foreign_org_id: uuid.UUID) -> None:
        """Demonstrate explicit service-level tenant scope validation."""
        self.validate_tenant_scope(foreign_org_id)


@pytest.mark.asyncio
async def test_service_foundation_with_injected_repository(session: AsyncSession):
    """Verify service uses injected repository and maintains tenant boundaries."""
    org_a = Organization(name="Company A", slug=f"comp-a-{uuid.uuid4().hex[:8]}")
    org_b = Organization(name="Company B", slug=f"comp-b-{uuid.uuid4().hex[:8]}")
    session.add_all([org_a, org_b])
    await session.flush()

    # Instantiate service with explicit dependency injection
    injected_repo = LeadRepository(session)
    service_a = SampleTenantBusinessService(
        session=session,
        organization_id=org_a.id,
        lead_repo=injected_repo,
    )

    # 1. Service operations operate strictly within bound tenant scope
    lead = await service_a.register_lead(phone="+15556667777", first_name="ServiceLead")
    assert lead.id is not None
    assert lead.organization_id == org_a.id

    fetched = await service_a.retrieve_lead(lead.id)
    assert fetched.id == lead.id

    # 2. Service tenant scope validation rejects foreign tenant IDs
    with pytest.raises(TenantAccessViolationError):
        await service_a.perform_cross_org_operation(org_b.id)

    # 3. Foreign service cannot retrieve lead belonging to Org A
    service_b = SampleTenantBusinessService(session=session, organization_id=org_b.id)
    with pytest.raises(EntityNotFoundError):
        await service_b.retrieve_lead(lead.id)


# ---------------------------------------------------------------------------
# 4. Global Entity Repository Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_global_entity_repository(session: AsyncSession):
    """Verify GlobalRepository handles non-tenant entities (User, Organization) correctly."""
    user_repo = UserRepository(session)
    user = User(
        email=f"global-user-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hashed_secret",
        first_name="Admin",
        last_name="User",
    )

    # Add global entity
    await user_repo.add(user)
    assert user.id is not None

    # Fetch by global ID
    fetched = await user_repo.get_by_id_or_raise(user.id)
    assert fetched.email == user.email

    # Count and list
    assert await user_repo.count() >= 1
    users = await user_repo.list(limit=10)
    assert any(u.id == user.id for u in users)

    # Delete global entity
    deleted = await user_repo.delete(user.id)
    assert deleted is True
    assert await user_repo.get_by_id(user.id) is None


# ---------------------------------------------------------------------------
# 5. Common Domain Exception Tests
# ---------------------------------------------------------------------------


def test_domain_exceptions_behavior():
    """Verify domain exceptions format messages correctly and inherit from AppException."""
    # 1. Base AppException
    app_exc = AppException("Generic application error")
    assert str(app_exc) == "Generic application error"
    assert isinstance(app_exc, Exception)

    # 2. EntityNotFoundError
    lead_id = uuid.uuid4()
    not_found = EntityNotFoundError("Lead", lead_id)
    assert isinstance(not_found, AppException)
    assert not_found.entity_name == "Lead"
    assert not_found.identifier == lead_id
    assert f"Lead with identifier '{lead_id}' was not found." in str(not_found)

    # 3. EntityAlreadyExistsError
    already_exists = EntityAlreadyExistsError("User", "email", "admin@example.com")
    assert isinstance(already_exists, AppException)
    assert already_exists.entity_name == "User"
    assert already_exists.field == "email"
    assert already_exists.value == "admin@example.com"
    assert "User with email 'admin@example.com' already exists." in str(already_exists)

    # 4. TenantAccessViolationError
    tenant_violation = TenantAccessViolationError("Access denied for tenant B.")
    assert isinstance(tenant_violation, AppException)
    assert str(tenant_violation) == "Access denied for tenant B."

    # 5. InvalidOperationError
    invalid_op = InvalidOperationError("Cannot transition lead from ARCHIVED to NEW.")
    assert isinstance(invalid_op, AppException)
    assert str(invalid_op) == "Cannot transition lead from ARCHIVED to NEW."
