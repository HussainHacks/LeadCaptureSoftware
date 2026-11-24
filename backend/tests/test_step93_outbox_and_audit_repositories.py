"""Focused integration tests for Phase 2, Step 9.3:
AutomationEvent and AuditLog Entities & Repositories.

Tests verify:
1. AutomationEvent ORM mapping includes attempt_count, lease_token, lease_expires_at.
2. Index definitions on AutomationEvent match Phase 9.1 migration
   (idx_outbox_retry_eligible, idx_outbox_lease_recovery).
3. AutomationEventRepository persistence, retrieval, and organization isolation.
4. AutomationEventRepository status filtering and counts.
5. AutomationEventRepository retry eligibility filtering (matching Index A).
6. AutomationEventRepository expired lease filtering (matching Index B).
7. AutomationEventRepository caller transaction control (flushes only, no auto-commit).
8. AuditLogRepository append-only creation, retrieval, and tenant isolation.
9. AuditLogRepository composable filtering by resource, action, and time range.
10. AuditLogRepository system worker records (user_id=None, actor_type=SYSTEM_WORKER).
11. AuditLogRepository rejection of update and delete operations.
12. Existing ORM immutability listeners remain active and effective.
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import Integer, String, UniqueConstraint, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.exceptions import (
    AuditLogImmutabilityError,
    EntityNotFoundError,
    InvalidOperationError,
    TenantAccessViolationError,
)
from app.models import (
    AutomationEvent,
    Base,
    Organization,
    User,
)
from app.models.enums import OutboxStatus
from app.repositories import (
    AuditLogRepository,
    AutomationEventRepository,
)

TEST_DB_NAME = "leadgen_test_step93_db"


# ==============================================================================
# Isolated Database Fixtures
# ==============================================================================


@pytest_asyncio.fixture(loop_scope="module", scope="module", autouse=True)
async def setup_test_db():
    """Create a temporary isolated test database, enable btree_gist, and build schema."""
    settings = get_settings()
    base_url = settings.DATABASE_URL.rsplit("/", 1)[0]
    admin_url = f"{base_url}/postgres"

    # Connect to default postgres DB to manage test database lifecycle
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE);"))
        await conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME};"))
    await admin_engine.dispose()

    # Connect to isolated test database and build schema
    test_db_url = f"{base_url}/{TEST_DB_NAME}"
    test_engine = create_async_engine(test_db_url, poolclass=NullPool)

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


@pytest_asyncio.fixture
async def sample_org(session: AsyncSession) -> Organization:
    """Fixture providing a persisted organization."""
    org = Organization(
        name="Step 9.3 Test Org",
        slug=f"org-step93-{uuid.uuid4().hex[:8]}",
        industry="hvac",
        timezone="America/Chicago",
        default_slot_capacity=2,
        settings={},
        is_active=True,
    )
    session.add(org)
    await session.flush()
    return org


@pytest_asyncio.fixture
async def second_org(session: AsyncSession) -> Organization:
    """Fixture providing a second organization for tenant isolation tests."""
    org = Organization(
        name="Step 9.3 Other Org",
        slug=f"org-step93-other-{uuid.uuid4().hex[:8]}",
        industry="hvac",
        timezone="America/Chicago",
        default_slot_capacity=2,
        settings={},
        is_active=True,
    )
    session.add(org)
    await session.flush()
    return org


@pytest_asyncio.fixture
async def sample_user(session: AsyncSession, sample_org: Organization) -> User:
    """Fixture providing a persisted user."""
    user = User(
        email=f"user-{uuid.uuid4().hex[:6]}@example.com",
        password_hash="mock_hashed_password",
        first_name="Jane",
        last_name="Technician",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


# ==============================================================================
# 1. AutomationEvent Model Mapping Tests
# ==============================================================================


def test_automation_event_model_fields_and_indexes():
    """Verify ORM model columns, defaults, nullability, and dual partial indexes."""
    table = AutomationEvent.__table__

    # 1. Column: attempt_count
    assert "attempt_count" in table.c
    col_attempt = table.c.attempt_count
    assert isinstance(col_attempt.type, Integer)
    assert col_attempt.nullable is False
    assert col_attempt.default.arg == 0
    server_def = col_attempt.server_default.arg
    assert (server_def.text if hasattr(server_def, "text") else str(server_def)) == "0"

    # 2. Column: lease_token
    assert "lease_token" in table.c
    col_lease_token = table.c.lease_token
    assert isinstance(col_lease_token.type, String)
    assert col_lease_token.type.length == 64
    assert col_lease_token.nullable is True

    # 3. Column: lease_expires_at
    assert "lease_expires_at" in table.c
    col_lease_expires = table.c.lease_expires_at
    assert col_lease_expires.type.timezone is True
    assert col_lease_expires.nullable is True

    # 4. Indexes
    index_names = {idx.name: idx for idx in table.indexes}
    assert "idx_outbox_retry_eligible" in index_names
    assert "idx_outbox_lease_recovery" in index_names
    assert "idx_outbox_unprocessed" not in index_names

    # Check Index A columns and predicate
    idx_retry = index_names["idx_outbox_retry_eligible"]
    assert [c.name for c in idx_retry.columns] == [
        "processing_status",
        "next_retry_at",
        "created_at",
    ]
    assert "PENDING" in str(idx_retry.dialect_options["postgresql"]["where"])
    assert "FAILED" in str(idx_retry.dialect_options["postgresql"]["where"])

    # Check Index B columns and predicate
    idx_lease = index_names["idx_outbox_lease_recovery"]
    assert [c.name for c in idx_lease.columns] == ["lease_expires_at", "created_at"]
    assert "PROCESSING" in str(idx_lease.dialect_options["postgresql"]["where"])

    # Check unique constraint on idempotency_key
    assert (
        any(
            isinstance(c, UniqueConstraint)
            and [col.name for col in c.columns] == ["idempotency_key"]
            for c in table.constraints
        )
        or table.c.idempotency_key.unique
    )


# ==============================================================================
# 2. AutomationEventRepository Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_automation_event_repo_add_and_get(session: AsyncSession, sample_org: Organization):
    """Verify adding an automation event and retrieving it by ID and idempotency key."""
    repo = AutomationEventRepository(session)
    idemp_key = f"lead.created:{sample_org.id}:{uuid.uuid4().hex}"

    event = AutomationEvent(
        organization_id=sample_org.id,
        event_type="lead.created",
        idempotency_key=idemp_key,
        payload={"lead_id": str(uuid.uuid4()), "service": "AC Repair"},
    )
    added = await repo.add(sample_org.id, event)
    assert added.id is not None
    assert added.attempt_count == 0
    assert added.retry_count == 0
    assert added.lease_token is None
    assert added.lease_expires_at is None
    assert added.processing_status == OutboxStatus.PENDING.value

    # Retrieval by ID
    fetched = await repo.get_by_id(sample_org.id, added.id)
    assert fetched is not None
    assert fetched.id == added.id
    assert fetched.idempotency_key == idemp_key

    # Retrieval by Idempotency Key
    by_key = await repo.get_by_idempotency_key(sample_org.id, idemp_key)
    assert by_key is not None
    assert by_key.id == added.id


@pytest.mark.asyncio
async def test_automation_event_repo_organization_isolation(
    session: AsyncSession, sample_org: Organization, second_org: Organization
):
    """Verify strict tenant isolation: cross-tenant additions, lookups, and lists are rejected."""
    repo = AutomationEventRepository(session)
    idemp_key = f"lead.created:{sample_org.id}:{uuid.uuid4().hex}"

    event_a = AutomationEvent(
        organization_id=sample_org.id,
        event_type="lead.created",
        idempotency_key=idemp_key,
        payload={"lead_id": str(uuid.uuid4())},
    )
    await repo.add(sample_org.id, event_a)

    # 1. Attempting to add event_a under second_org raises TenantAccessViolationError
    event_mismatched = AutomationEvent(
        organization_id=sample_org.id,
        event_type="lead.created",
        idempotency_key=f"lead.created:{uuid.uuid4().hex}",
        payload={"data": 123},
    )
    with pytest.raises(TenantAccessViolationError):
        await repo.add(second_org.id, event_mismatched)

    # 2. Querying second_org with event_a's ID returns None
    assert await repo.get_by_id(second_org.id, event_a.id) is None

    # 3. get_by_id_or_raise with wrong tenant raises EntityNotFoundError
    with pytest.raises(EntityNotFoundError):
        await repo.get_by_id_or_raise(second_org.id, event_a.id)

    # 4. Querying second_org by event_a's idempotency_key returns None
    assert await repo.get_by_idempotency_key(second_org.id, idemp_key) is None

    # 5. list under second_org returns 0 events
    second_org_events = await repo.list(second_org.id)
    assert len(second_org_events) == 0


@pytest.mark.asyncio
async def test_automation_event_repo_status_filtering(
    session: AsyncSession, sample_org: Organization
):
    """Verify listing and counting events by specific status."""
    repo = AutomationEventRepository(session)

    # Seed events with various statuses
    e_pending = AutomationEvent(
        organization_id=sample_org.id,
        event_type="lead.created",
        idempotency_key=f"k-pend-{uuid.uuid4().hex[:8]}",
        payload={"step": 1},
        processing_status=OutboxStatus.PENDING.value,
    )
    e_delivered = AutomationEvent(
        organization_id=sample_org.id,
        event_type="lead.qualified",
        idempotency_key=f"k-deliv-{uuid.uuid4().hex[:8]}",
        payload={"step": 2},
        processing_status=OutboxStatus.DELIVERED.value,
    )
    e_failed = AutomationEvent(
        organization_id=sample_org.id,
        event_type="emergency.dispatched",
        idempotency_key=f"k-fail-{uuid.uuid4().hex[:8]}",
        payload={"step": 3},
        processing_status=OutboxStatus.FAILED.value,
    )
    session.add_all([e_pending, e_delivered, e_failed])
    await session.flush()

    # Verify list_by_status
    pending_list = await repo.list_by_status(sample_org.id, OutboxStatus.PENDING)
    assert len(pending_list) == 1
    assert pending_list[0].id == e_pending.id

    delivered_list = await repo.list_by_status(sample_org.id, "DELIVERED")
    assert len(delivered_list) == 1
    assert delivered_list[0].id == e_delivered.id

    # Verify count_by_status
    assert await repo.count_by_status(sample_org.id, OutboxStatus.PENDING) == 1
    assert await repo.count_by_status(sample_org.id, OutboxStatus.DELIVERED) == 1
    assert await repo.count_by_status(sample_org.id, OutboxStatus.FAILED) == 1
    assert await repo.count_by_status(sample_org.id, OutboxStatus.DEAD_LETTER) == 0


@pytest.mark.asyncio
async def test_automation_event_repo_retry_eligibility_filtering(
    session: AsyncSession, sample_org: Organization
):
    """Verify list_retry_eligible returns only PENDING/FAILED events past retry timestamp."""
    repo = AutomationEventRepository(session)
    now = datetime.now(UTC)

    # 1. PENDING with next_retry_at = None -> Eligible
    e1 = AutomationEvent(
        organization_id=sample_org.id,
        event_type="e1",
        idempotency_key=f"k-e1-{uuid.uuid4().hex[:8]}",
        payload={},
        processing_status=OutboxStatus.PENDING.value,
        next_retry_at=None,
    )
    # 2. PENDING with next_retry_at in past -> Eligible
    e2 = AutomationEvent(
        organization_id=sample_org.id,
        event_type="e2",
        idempotency_key=f"k-e2-{uuid.uuid4().hex[:8]}",
        payload={},
        processing_status=OutboxStatus.PENDING.value,
        next_retry_at=now - timedelta(minutes=5),
    )
    # 3. FAILED with next_retry_at in past -> Eligible
    e3 = AutomationEvent(
        organization_id=sample_org.id,
        event_type="e3",
        idempotency_key=f"k-e3-{uuid.uuid4().hex[:8]}",
        payload={},
        processing_status=OutboxStatus.FAILED.value,
        next_retry_at=now - timedelta(minutes=2),
    )
    # 4. FAILED with next_retry_at in future -> NOT eligible (backoff active)
    e4 = AutomationEvent(
        organization_id=sample_org.id,
        event_type="e4",
        idempotency_key=f"k-e4-{uuid.uuid4().hex[:8]}",
        payload={},
        processing_status=OutboxStatus.FAILED.value,
        next_retry_at=now + timedelta(minutes=10),
    )
    # 5. DELIVERED with next_retry_at in past -> NOT eligible (already delivered)
    e5 = AutomationEvent(
        organization_id=sample_org.id,
        event_type="e5",
        idempotency_key=f"k-e5-{uuid.uuid4().hex[:8]}",
        payload={},
        processing_status=OutboxStatus.DELIVERED.value,
        next_retry_at=now - timedelta(hours=1),
    )
    # 6. PROCESSING with next_retry_at in past -> NOT eligible (in-flight)
    e6 = AutomationEvent(
        organization_id=sample_org.id,
        event_type="e6",
        idempotency_key=f"k-e6-{uuid.uuid4().hex[:8]}",
        payload={},
        processing_status=OutboxStatus.PROCESSING.value,
        next_retry_at=now - timedelta(minutes=1),
    )
    session.add_all([e1, e2, e3, e4, e5, e6])
    await session.flush()

    eligible = await repo.list_retry_eligible(sample_org.id, now_utc=now)
    eligible_ids = {e.id for e in eligible}

    assert len(eligible) == 3
    assert e1.id in eligible_ids
    assert e2.id in eligible_ids
    assert e3.id in eligible_ids
    assert e4.id not in eligible_ids
    assert e5.id not in eligible_ids
    assert e6.id not in eligible_ids


@pytest.mark.asyncio
async def test_automation_event_repo_expired_leases_filtering(
    session: AsyncSession, sample_org: Organization
):
    """Verify list_expired_leases returns only PROCESSING events whose lease_expires_at <= now."""
    repo = AutomationEventRepository(session)
    now = datetime.now(UTC)

    # 1. PROCESSING with expired lease -> Eligible for recovery
    e_expired = AutomationEvent(
        organization_id=sample_org.id,
        event_type="exp-proc",
        idempotency_key=f"k-exp-{uuid.uuid4().hex[:8]}",
        payload={},
        processing_status=OutboxStatus.PROCESSING.value,
        attempt_count=1,
        lease_token="lease-crashed-worker",
        lease_expires_at=now - timedelta(seconds=30),
    )
    # 2. PROCESSING with active lease -> NOT expired (in-flight)
    e_active = AutomationEvent(
        organization_id=sample_org.id,
        event_type="act-proc",
        idempotency_key=f"k-act-{uuid.uuid4().hex[:8]}",
        payload={},
        processing_status=OutboxStatus.PROCESSING.value,
        attempt_count=1,
        lease_token="lease-healthy-worker",
        lease_expires_at=now + timedelta(seconds=120),
    )
    # 3. PENDING with lease_expires_at = None -> NOT processing
    e_pending = AutomationEvent(
        organization_id=sample_org.id,
        event_type="pend-event",
        idempotency_key=f"k-pend-{uuid.uuid4().hex[:8]}",
        payload={},
        processing_status=OutboxStatus.PENDING.value,
        lease_expires_at=None,
    )
    session.add_all([e_expired, e_active, e_pending])
    await session.flush()

    expired_list = await repo.list_expired_leases(sample_org.id, now_utc=now)
    assert len(expired_list) == 1
    assert expired_list[0].id == e_expired.id
    assert expired_list[0].lease_token == "lease-crashed-worker"


@pytest.mark.asyncio
async def test_automation_event_repo_transaction_ownership(
    session: AsyncSession, sample_org: Organization
):
    """Verify repository methods flush but do not commit transactions."""
    repo = AutomationEventRepository(session)
    event = AutomationEvent(
        organization_id=sample_org.id,
        event_type="test.rollback",
        idempotency_key=f"k-rb-{uuid.uuid4().hex[:8]}",
        payload={"key": "value"},
    )
    added = await repo.add(sample_org.id, event)
    event_id = added.id

    # Roll back the active transaction
    await session.rollback()

    # Verify the event was not committed
    re_fetched = await repo.get_by_id(sample_org.id, event_id)
    assert re_fetched is None


# ==============================================================================
# 3. AuditLogRepository Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_audit_repo_creation_and_retrieval(
    session: AsyncSession, sample_org: Organization, sample_user: User
):
    """Verify creating an audit log entry via repo and retrieving it."""
    repo = AuditLogRepository(session)
    res_id = str(uuid.uuid4())

    entry = await repo.log_event(
        sample_org.id,
        action="LEAD_STATUS_CHANGED",
        resource_type="lead",
        resource_id=res_id,
        user_id=sample_user.id,
        changes={"old_status": "NEW", "new_status": "QUALIFIED"},
        ip_address="192.168.1.1",
    )
    assert entry.id is not None
    assert entry.action == "LEAD_STATUS_CHANGED"
    assert entry.resource_type == "lead"
    assert entry.resource_id == res_id
    assert entry.user_id == sample_user.id
    assert entry.changes["new_status"] == "QUALIFIED"

    # Fetch by ID
    fetched = await repo.get_by_id(sample_org.id, entry.id)
    assert fetched is not None
    assert fetched.id == entry.id


@pytest.mark.asyncio
async def test_audit_repo_tenant_isolation(
    session: AsyncSession, sample_org: Organization, second_org: Organization
):
    """Verify audit log records in Org A cannot be fetched by Org B."""
    repo = AuditLogRepository(session)
    res_id = str(uuid.uuid4())

    entry_a = await repo.log_event(
        sample_org.id,
        action="SAFETY_ESCALATED",
        resource_type="conversation",
        resource_id=res_id,
        changes={"reason": "GAS_LEAK"},
    )

    # 1. get_by_id under second_org returns None
    assert await repo.get_by_id(second_org.id, entry_a.id) is None

    # 2. list_by_resource under second_org returns empty
    res_second = await repo.list_by_resource(second_org.id, "conversation", res_id)
    assert len(res_second) == 0

    # 3. list_filtered under second_org returns empty
    filtered_second = await repo.list_filtered(second_org.id, action="SAFETY_ESCALATED")
    assert len(filtered_second) == 0


@pytest.mark.asyncio
async def test_audit_repo_filtering_by_resource_action_time(
    session: AsyncSession, sample_org: Organization
):
    """Verify list_filtered handles action, resource, user, and time-range filters."""
    repo = AuditLogRepository(session)
    t0 = datetime.now(UTC)

    # Entry 1: action A
    e1 = await repo.log_event(
        sample_org.id,
        action="ACTION_A",
        resource_type="lead",
        resource_id="res-1",
    )
    # Entry 2: action B
    e2 = await repo.log_event(
        sample_org.id,
        action="ACTION_B",
        resource_type="lead",
        resource_id="res-1",
    )
    # Entry 3: different resource
    e3 = await repo.log_event(
        sample_org.id,
        action="ACTION_A",
        resource_type="appointment",
        resource_id="res-2",
    )

    # 1. Filter by action
    by_action = await repo.list_filtered(sample_org.id, action="ACTION_A")
    assert len(by_action) == 2
    assert {e.id for e in by_action} == {e1.id, e3.id}

    # 2. Filter by resource_type
    by_resource_type = await repo.list_filtered(sample_org.id, resource_type="lead")
    assert len(by_resource_type) == 2
    assert {e.id for e in by_resource_type} == {e1.id, e2.id}

    # 3. Filter by resource_id
    by_res_id = await repo.list_filtered(sample_org.id, resource_id="res-1")
    assert len(by_res_id) == 2
    assert {e.id for e in by_res_id} == {e1.id, e2.id}

    # 4. Filter by time range
    by_time = await repo.list_filtered(
        sample_org.id,
        start_time=t0 - timedelta(seconds=1),
        end_time=datetime.now(UTC) + timedelta(seconds=1),
    )
    assert len(by_time) == 3


@pytest.mark.asyncio
async def test_audit_repo_system_worker_support(session: AsyncSession, sample_org: Organization):
    """Verify system-worker audit records support user_id=None and SYSTEM_WORKER actor metadata."""
    repo = AuditLogRepository(session)
    event_id = uuid.uuid4()

    entry = await repo.log_system_event(
        sample_org.id,
        action="EVENT_DEAD_LETTERED",
        resource_type="automation_event",
        resource_id=str(event_id),
        changes={"retry_count": 5, "last_error": "Connection timed out"},
    )

    assert entry.id is not None
    assert entry.organization_id == sample_org.id
    assert entry.user_id is None
    assert entry.changes["actor_type"] == "SYSTEM_WORKER"
    assert entry.changes["retry_count"] == 5
    assert entry.changes["last_error"] == "Connection timed out"


@pytest.mark.asyncio
async def test_audit_repo_user_agent_handling(session: AsyncSession, sample_org: Organization):
    """Verify user_agent is preserved inside changes JSONB without dedicated DB column."""
    repo = AuditLogRepository(session)

    # 1. Via log_event with user_agent argument
    entry1 = await repo.log_event(
        sample_org.id,
        action="LOGIN_ATTEMPT",
        resource_type="user",
        resource_id=str(uuid.uuid4()),
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    )
    assert entry1.changes is not None
    assert entry1.changes["user_agent"] == "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

    # 2. Via log_system_event with user_agent argument
    entry2 = await repo.log_system_event(
        sample_org.id,
        action="OUTBOX_SWEEP",
        resource_type="automation_worker",
        resource_id="worker-1",
        user_agent="LeadGenWorker/1.0",
    )
    assert entry2.changes is not None
    assert entry2.changes["actor_type"] == "SYSTEM_WORKER"
    assert entry2.changes["user_agent"] == "LeadGenWorker/1.0"
    assert entry2.user_id is None


@pytest.mark.asyncio
async def test_audit_repo_prohibits_delete_and_orm_immutability_active(
    session: AsyncSession, sample_org: Organization
):
    """Verify repo delete raises InvalidOperationError and ORM flush immutability holds."""
    repo = AuditLogRepository(session)
    entry = await repo.log_event(
        sample_org.id,
        action="IMMUTABLE_ACTION",
        resource_type="service",
        resource_id=str(uuid.uuid4()),
    )

    # 1. repo.delete raises InvalidOperationError
    with pytest.raises(InvalidOperationError) as exc_info:
        await repo.delete(sample_org.id, entry.id)
    assert "AuditLog records are immutable and cannot be deleted via repository" in str(
        exc_info.value
    )

    # 2. repo.delete_entity raises InvalidOperationError
    with pytest.raises(InvalidOperationError) as exc_info:
        await repo.delete_entity(sample_org.id, entry)
    assert "AuditLog records are immutable and cannot be deleted via repository" in str(
        exc_info.value
    )

    # 3. Direct ORM update raises AuditLogImmutabilityError on flush
    entry.action = "ILLEGAL_MUTATION"
    with pytest.raises(AuditLogImmutabilityError):
        await session.flush()
