"""Integration and unit tests for organization, user, and membership management."""

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.exceptions import (
    EntityAlreadyExistsError,
    EntityNotFoundError,
    InvalidOperationError,
    ValidationError,
)
from app.core.security import verify_password
from app.models import Base
from app.models.enums import UserRole
from app.schemas.organization import OrganizationCreate
from app.schemas.user import UserCreate
from app.services import MembershipService, OrganizationService, UserService

TEST_DB_NAME = "leadgen_test_org_user_mgmt_db"


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


# ---------------------------------------------------------------------------
# 1. User Management Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_user_registration(session: AsyncSession):
    """Verify registering a new user sets attributes and generates a valid UUID."""
    user_service = UserService(session)
    user_data = UserCreate(
        email="john.doe@example.com",
        password="ValidPassword123!",
        first_name="John",
        last_name="Doe",
        phone="+15551234567",
    )

    user = await user_service.register_user(user_data)
    assert user.id is not None
    assert user.email == "john.doe@example.com"
    assert user.first_name == "John"
    assert user.last_name == "Doe"
    assert user.phone == "+15551234567"
    assert user.is_active is True

    # User retrieval by ID and by email
    fetched = await user_service.get_user_by_id(user.id)
    assert fetched.id == user.id

    fetched_by_email = await user_service.get_user_by_email("john.doe@example.com")
    assert fetched_by_email is not None
    assert fetched_by_email.id == user.id


@pytest.mark.asyncio
async def test_password_hashing_and_never_store_plaintext(session: AsyncSession):
    """Verify password is encrypted with bcrypt cost 12 and plaintext is never stored."""
    user_service = UserService(session)
    raw_pass = "MySecretPassword123!"
    user_data = UserCreate(
        email="security.test@example.com",
        password=raw_pass,
        first_name="Security",
        last_name="Tester",
    )

    user = await user_service.register_user(user_data)

    # 1. Plaintext password is never stored
    assert user.password_hash != raw_pass
    assert raw_pass not in user.password_hash

    # 2. Verify password hash format (bcrypt prefix $2b$12$)
    assert user.password_hash.startswith("$2b$12$")

    # 3. Password verification function succeeds with correct password
    assert verify_password(raw_pass, user.password_hash) is True
    assert verify_password("WrongPassword!", user.password_hash) is False

    # 4. User-facing read schema does not expose password_hash
    read_schema = user_service.to_read_schema(user)
    assert not hasattr(read_schema, "password_hash")
    assert not hasattr(read_schema, "password")


@pytest.mark.asyncio
async def test_duplicate_email_rejection(session: AsyncSession):
    """Verify registering a user with an existing email (case-insensitive) is rejected."""
    user_service = UserService(session)
    user_data1 = UserCreate(
        email="duplicate@example.com",
        password="Password123!",
        first_name="First",
        last_name="User",
    )
    await user_service.register_user(user_data1)

    # Attempt same email in uppercase
    user_data2 = UserCreate(
        email="DUPLICATE@EXAMPLE.COM",
        password="AnotherPassword123!",
        first_name="Second",
        last_name="User",
    )
    with pytest.raises(EntityAlreadyExistsError) as exc_info:
        await user_service.register_user(user_data2)

    assert "duplicate@example.com" in str(exc_info.value)


@pytest.mark.asyncio
async def test_invalid_email_and_password_validation(session: AsyncSession):
    """Verify email format and password length validation rules."""
    user_service = UserService(session)

    # 1. Invalid email rejected by service domain validation
    bad_email_data = UserCreate(
        email="invalid-email-no-domain",
        password="ValidPassword123!",
        first_name="Bad",
        last_name="Email",
    )
    with pytest.raises(ValidationError):
        await user_service.register_user(bad_email_data)

    # 2. Schema-level validation rejects short password
    with pytest.raises(PydanticValidationError):
        UserCreate(
            email="shortpass@example.com",
            password="short",
            first_name="Short",
            last_name="Pass",
        )

    # 3. Domain-level validation in service rejects short password even if constructed directly
    short_pass_data = UserCreate.model_construct(
        email="shortpass@example.com",
        password="short",
        first_name="Short",
        last_name="Pass",
    )
    with pytest.raises(ValidationError):
        await user_service.register_user(short_pass_data)


# ---------------------------------------------------------------------------
# 2. Organization Management Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_organization_creation_and_owner_membership(session: AsyncSession):
    """Verify organization creation creates both organization and initial OWNER membership."""
    user_service = UserService(session)
    org_service = OrganizationService(session)

    creator = await user_service.register_user(
        UserCreate(
            email="owner@example.com",
            password="StrongPassword123!",
            first_name="Alice",
            last_name="Owner",
        )
    )

    org_data = OrganizationCreate(
        name="Apex Heating & Air",
        slug="apex-air-austin",
        industry="HVAC",
        timezone="America/Chicago",
        dispatch_phone="+15125550100",
        utility_emergency_phone="+18005550199",
        default_slot_capacity=2,
    )

    org, membership = await org_service.create_organization(creator.id, org_data)

    # Verify organization attributes
    assert org.id is not None
    assert org.name == "Apex Heating & Air"
    assert org.slug == "apex-air-austin"
    assert org.timezone == "America/Chicago"
    assert org.default_slot_capacity == 2
    assert org.is_active is True

    # Verify automatic OWNER membership creation
    assert membership.id is not None
    assert membership.organization_id == org.id
    assert membership.user_id == creator.id
    assert membership.role == UserRole.OWNER.value
    assert membership.is_active is True

    # Verify retrieval
    fetched = await org_service.get_organization_by_id(org.id)
    assert fetched.slug == "apex-air-austin"

    fetched_slug = await org_service.get_organization_by_slug("apex-air-austin")
    assert fetched_slug.id == org.id


@pytest.mark.asyncio
async def test_organization_and_membership_transaction_rollback(session: AsyncSession):
    """Verify that if a transaction is rolled back, neither org nor membership persists."""
    user_service = UserService(session)
    org_service = OrganizationService(session)

    creator = await user_service.register_user(
        UserCreate(
            email="rollback.creator@example.com",
            password="StrongPassword123!",
            first_name="Rollback",
            last_name="Tester",
        )
    )

    org_data = OrganizationCreate(
        name="Temporary Heating Co",
        slug="temp-heating-co",
    )

    org, membership = await org_service.create_organization(creator.id, org_data)
    org_id = org.id
    membership_id = membership.id

    # Roll back transaction explicitly
    await session.rollback()

    # Verify neither organization nor membership exists in DB
    with pytest.raises(EntityNotFoundError):
        await org_service.get_organization_by_id(org_id)

    membership_service = MembershipService(session, org_id)
    with pytest.raises(EntityNotFoundError):
        await membership_service.get_membership_by_id(membership_id)


@pytest.mark.asyncio
async def test_duplicate_organization_slug_rejection(session: AsyncSession):
    """Verify duplicate organization slugs are rejected with EntityAlreadyExistsError."""
    user_service = UserService(session)
    org_service = OrganizationService(session)

    creator = await user_service.register_user(
        UserCreate(
            email="slug.creator@example.com",
            password="StrongPassword123!",
            first_name="Bob",
            last_name="Builder",
        )
    )

    org_data = OrganizationCreate(
        name="First Company",
        slug="shared-slug",
    )
    await org_service.create_organization(creator.id, org_data)

    # Attempt to create a second organization with identical slug
    duplicate_org_data = OrganizationCreate(
        name="Second Company",
        slug="shared-slug",
    )
    with pytest.raises(EntityAlreadyExistsError) as exc_info:
        await org_service.create_organization(creator.id, duplicate_org_data)

    assert "shared-slug" in str(exc_info.value)


@pytest.mark.asyncio
async def test_invalid_organization_inputs(session: AsyncSession):
    """Verify organization creation fails on invalid slug, empty name, or inactive user."""
    user_service = UserService(session)
    org_service = OrganizationService(session)

    creator = await user_service.register_user(
        UserCreate(
            email="inputs.creator@example.com",
            password="StrongPassword123!",
            first_name="Input",
            last_name="Validator",
        )
    )

    # Nonexistent creator user
    with pytest.raises(EntityNotFoundError):
        await org_service.create_organization(
            uuid.uuid4(), OrganizationCreate(name="Acme", slug="acme-valid")
        )

    # Empty name
    with pytest.raises(ValidationError):
        await org_service.create_organization(
            creator.id, OrganizationCreate(name="   ", slug="valid-slug")
        )

    # Invalid slug (uppercase, special characters, spaces)
    with pytest.raises(ValidationError):
        await org_service.create_organization(
            creator.id, OrganizationCreate(name="Acme Air", slug="Invalid_Slug!")
        )


# ---------------------------------------------------------------------------
# 3. Membership Management Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_membership_creation(session: AsyncSession):
    """Verify adding an existing user to an organization with a specific role."""
    user_service = UserService(session)
    org_service = OrganizationService(session)

    owner = await user_service.register_user(
        UserCreate(
            email="owner.member.test@example.com",
            password="Password123!",
            first_name="Org",
            last_name="Owner",
        )
    )
    dispatcher = await user_service.register_user(
        UserCreate(
            email="dispatcher.test@example.com",
            password="Password123!",
            first_name="Dave",
            last_name="Dispatcher",
        )
    )

    org, _ = await org_service.create_organization(
        owner.id, OrganizationCreate(name="City HVAC", slug="city-hvac-austin")
    )

    membership_service = MembershipService(session, org.id)
    membership = await membership_service.add_member(
        user_id=dispatcher.id,
        role=UserRole.DISPATCHER,
    )

    assert membership.id is not None
    assert membership.organization_id == org.id
    assert membership.user_id == dispatcher.id
    assert membership.role == UserRole.DISPATCHER.value
    assert membership.is_active is True

    # Check active membership status
    assert await membership_service.is_active_member(dispatcher.id) is True


@pytest.mark.asyncio
async def test_duplicate_membership_rejection(session: AsyncSession):
    """Verify adding a user who is already a member of the organization is rejected."""
    user_service = UserService(session)
    org_service = OrganizationService(session)

    owner = await user_service.register_user(
        UserCreate(
            email="dup.member.owner@example.com",
            password="Password123!",
            first_name="Owner",
            last_name="Two",
        )
    )
    tech = await user_service.register_user(
        UserCreate(
            email="tech.dup@example.com",
            password="Password123!",
            first_name="Tom",
            last_name="Tech",
        )
    )

    org, _ = await org_service.create_organization(
        owner.id, OrganizationCreate(name="Tech HVAC", slug="tech-hvac-co")
    )

    membership_service = MembershipService(session, org.id)
    await membership_service.add_member(tech.id, role=UserRole.TECHNICIAN)

    # Attempt to add same tech to same org
    with pytest.raises(EntityAlreadyExistsError):
        await membership_service.add_member(tech.id, role=UserRole.ADMIN)


@pytest.mark.asyncio
async def test_invalid_organization_or_user_references_in_membership(session: AsyncSession):
    """Verify adding nonexistent user or to nonexistent org raises EntityNotFoundError."""
    user_service = UserService(session)
    org_service = OrganizationService(session)

    owner = await user_service.register_user(
        UserCreate(
            email="ref.owner@example.com",
            password="Password123!",
            first_name="Ref",
            last_name="Owner",
        )
    )
    org, _ = await org_service.create_organization(
        owner.id, OrganizationCreate(name="Ref Air", slug="ref-air-co")
    )

    membership_service = MembershipService(session, org.id)

    # Nonexistent user
    with pytest.raises(EntityNotFoundError) as exc_info:
        await membership_service.add_member(uuid.uuid4(), role=UserRole.TECHNICIAN)
    assert "User" in str(exc_info.value)

    # Nonexistent organization
    invalid_org_service = MembershipService(session, uuid.uuid4())
    with pytest.raises(EntityNotFoundError) as exc_info:
        await invalid_org_service.add_member(owner.id, role=UserRole.TECHNICIAN)
    assert "Organization" in str(exc_info.value)


@pytest.mark.asyncio
async def test_membership_organization_scoping(session: AsyncSession):
    """Verify membership queries and operations strictly respect organization boundaries."""
    user_service = UserService(session)
    org_service = OrganizationService(session)

    user1 = await user_service.register_user(
        UserCreate(
            email="scope.u1@example.com",
            password="Password123!",
            first_name="User",
            last_name="One",
        )
    )
    user2 = await user_service.register_user(
        UserCreate(
            email="scope.u2@example.com",
            password="Password123!",
            first_name="User",
            last_name="Two",
        )
    )

    org_a, m_a = await org_service.create_organization(
        user1.id, OrganizationCreate(name="Org Alpha", slug="org-alpha-scope")
    )
    org_b, m_b = await org_service.create_organization(
        user2.id, OrganizationCreate(name="Org Beta", slug="org-beta-scope")
    )

    service_a = MembershipService(session, org_a.id)
    service_b = MembershipService(session, org_b.id)

    # Listing members for Org A returns only Org A's members
    members_a = await service_a.list_members()
    assert len(members_a) == 1
    assert members_a[0].id == m_a.id
    assert members_a[0].organization_id == org_a.id

    # Org A cannot fetch Org B's membership by ID
    with pytest.raises(EntityNotFoundError):
        await service_a.get_membership_by_id(m_b.id)

    # Org A sees user2 as not a member
    assert await service_a.get_membership_by_user_id(user2.id) is None
    assert await service_a.is_active_member(user2.id) is False

    # Org B sees user2 as active member
    assert await service_b.is_active_member(user2.id) is True


@pytest.mark.asyncio
async def test_role_assignment_restrictions(session: AsyncSession):
    """Verify standard operations cannot assign, promote, or alter the OWNER role."""
    user_service = UserService(session)
    org_service = OrganizationService(session)

    owner = await user_service.register_user(
        UserCreate(
            email="role.owner@example.com",
            password="Password123!",
            first_name="Role",
            last_name="Owner",
        )
    )
    staff = await user_service.register_user(
        UserCreate(
            email="role.staff@example.com",
            password="Password123!",
            first_name="Staff",
            last_name="Member",
        )
    )

    org, owner_m = await org_service.create_organization(
        owner.id, OrganizationCreate(name="Role Test Co", slug="role-test-co")
    )

    membership_service = MembershipService(session, org.id)

    # 1. Prohibit granting OWNER role when adding a member
    with pytest.raises(InvalidOperationError):
        await membership_service.add_member(staff.id, role=UserRole.OWNER)

    # Add staff as technician
    staff_m = await membership_service.add_member(staff.id, role=UserRole.TECHNICIAN)

    # 2. Prohibit promoting staff to OWNER via role update
    with pytest.raises(InvalidOperationError):
        await membership_service.update_member_role(staff_m.id, new_role=UserRole.OWNER)

    # 3. Allow updating staff to ADMIN
    updated = await membership_service.update_member_role(staff_m.id, new_role=UserRole.ADMIN)
    assert updated.role == UserRole.ADMIN.value

    # 4. Prohibit modifying or demoting the organization OWNER
    with pytest.raises(InvalidOperationError):
        await membership_service.update_member_role(owner_m.id, new_role=UserRole.ADMIN)


@pytest.mark.asyncio
async def test_inactive_membership_behavior(session: AsyncSession):
    """Verify deactivating and reactivating a membership, and protecting owner deactivation."""
    user_service = UserService(session)
    org_service = OrganizationService(session)

    owner = await user_service.register_user(
        UserCreate(
            email="inact.owner@example.com",
            password="Password123!",
            first_name="Inact",
            last_name="Owner",
        )
    )
    staff = await user_service.register_user(
        UserCreate(
            email="inact.staff@example.com",
            password="Password123!",
            first_name="Inact",
            last_name="Staff",
        )
    )

    org, owner_m = await org_service.create_organization(
        owner.id, OrganizationCreate(name="Active Status Co", slug="active-status-co")
    )

    membership_service = MembershipService(session, org.id)
    staff_m = await membership_service.add_member(staff.id, role=UserRole.DISPATCHER)

    # 1. Initial state is active
    assert await membership_service.is_active_member(staff.id) is True

    # 2. Deactivate member
    deactivated = await membership_service.deactivate_member(staff_m.id)
    assert deactivated.is_active is False
    assert await membership_service.is_active_member(staff.id) is False

    # 3. Filter inactive members
    active_members = await membership_service.list_members(include_inactive=False)
    assert len(active_members) == 1
    assert active_members[0].id == owner_m.id

    all_members = await membership_service.list_members(include_inactive=True)
    assert len(all_members) == 2

    # 4. Reactivate member
    reactivated = await membership_service.activate_member(staff_m.id)
    assert reactivated.is_active is True
    assert await membership_service.is_active_member(staff.id) is True

    # 5. Prohibit deactivating organization OWNER
    with pytest.raises(InvalidOperationError):
        await membership_service.deactivate_member(owner_m.id)
