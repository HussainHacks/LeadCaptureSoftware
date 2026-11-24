"""Focused unit and integration tests for OutboxService and Lease Fencing."""

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.events import SimulatedEventDispatcher
from app.core.exceptions import (
    EntityAlreadyExistsError,
    PermanentDispatchError,
    RetryableDispatchError,
    StaleLeaseError,
)
from app.models import (
    Base,
    Organization,
)
from app.models.enums import AutomationEventType, OutboxStatus
from app.repositories import AuditLogRepository, AutomationEventRepository
from app.services.outbox_service import OutboxService

TEST_DB_NAME = "leadgen_test_step94_outbox_db"


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
    async with session_maker() as sess:
        yield sess
    await engine.dispose()


@pytest_asyncio.fixture
async def organization(session: AsyncSession) -> Organization:
    """Create a verified test organization."""
    org = Organization(
        name=f"Test Outbox Org {uuid.uuid4().hex[:6]}",
        slug=f"test-outbox-{uuid.uuid4().hex[:6]}",
    )
    session.add(org)
    await session.commit()
    await session.refresh(org)
    return org


@pytest.mark.asyncio
async def test_publish_event_flushes_with_deterministic_key(
    session: AsyncSession,
    organization: Organization,
) -> None:
    """Verifies publish_event() flushes pending event with deterministic idempotency key."""
    service = OutboxService(session, organization.id)
    aggregate_id = uuid.uuid4()

    event = await service.publish_event(
        event_type=AutomationEventType.LEAD_CREATED,
        aggregate_id=aggregate_id,
        aggregate_type="Lead",
        payload={"lead_id": str(aggregate_id), "name": "John Doe"},
    )
    await session.commit()

    assert event.id is not None
    assert event.processing_status == OutboxStatus.PENDING.value
    assert event.attempt_count == 0
    assert event.lease_token is None

    # Duplicate with same aggregate & event_type produces same idempotency key
    # and fails unique constraint
    with pytest.raises(EntityAlreadyExistsError):
        await service.publish_event(
            event_type=AutomationEventType.LEAD_CREATED,
            aggregate_id=aggregate_id,
            aggregate_type="Lead",
            payload={"lead_id": str(aggregate_id), "name": "John Doe"},
        )
    await session.rollback()


@pytest.mark.asyncio
async def test_claim_batch_sets_lease_and_increments_attempt(
    session: AsyncSession,
    organization: Organization,
) -> None:
    """Verifies claim_batch() sets lease token, expires_at, and increments attempt_count."""
    service = OutboxService(session, organization.id)

    # Publish 2 events
    agg1 = uuid.uuid4()
    agg2 = uuid.uuid4()
    await service.publish_event(
        event_type=AutomationEventType.LEAD_CREATED,
        aggregate_id=agg1,
        aggregate_type="Lead",
        payload={"test": 1},
    )
    await service.publish_event(
        event_type=AutomationEventType.MESSAGE_SENT,
        aggregate_id=agg2,
        aggregate_type="Message",
        payload={"test": 2},
    )
    await session.commit()

    # Claim batch
    claimed = await service.claim_batch(batch_size=10, lease_duration_seconds=60)
    assert len(claimed) >= 2

    for ev in claimed:
        assert ev.processing_status == OutboxStatus.PROCESSING.value
        assert ev.lease_token is not None
        assert len(ev.lease_token) == 64
        assert ev.lease_expires_at is not None
        assert ev.lease_expires_at > datetime.now(UTC)
        assert ev.attempt_count == 1


@pytest.mark.asyncio
async def test_settle_event_delivered_creates_immutable_audit_log(
    session: AsyncSession,
    organization: Organization,
) -> None:
    """Verifies settling an event as DELIVERED logs system audit and sets processed_at."""
    service = OutboxService(session, organization.id)
    audit_repo = AuditLogRepository(session)

    agg = uuid.uuid4()
    await service.publish_event(
        event_type=AutomationEventType.APPOINTMENT_SCHEDULED,
        aggregate_id=agg,
        aggregate_type="Appointment",
        payload={"appt": str(agg)},
    )
    await session.commit()

    claimed = await service.claim_batch(batch_size=1)
    ev = claimed[0]

    # Settle delivered
    settled = await service.settle_event(
        event_id=ev.id,
        lease_token=ev.lease_token,
        status=OutboxStatus.DELIVERED,
    )

    assert settled.processing_status == OutboxStatus.DELIVERED.value
    assert settled.processed_at is not None
    assert settled.lease_token is None

    # Verify audit log was recorded
    audit_logs = await audit_repo.list_filtered(
        organization_id=organization.id,
        resource_type="AutomationEvent",
        action="DISPATCH_SUCCESS",
    )
    assert len(audit_logs) >= 1
    log = audit_logs[0]
    assert log.changes.get("actor_type") == "SYSTEM_WORKER"
    assert log.user_id is None
    assert log.resource_id == str(ev.id)


@pytest.mark.asyncio
async def test_settle_event_retryable_failure_backoff(
    session: AsyncSession,
    organization: Organization,
) -> None:
    """Verifies settling with retryable failure increments retry_count and sets next_retry_at."""
    service = OutboxService(session, organization.id)

    agg = uuid.uuid4()
    await service.publish_event(
        event_type=AutomationEventType.MESSAGE_SENT,
        aggregate_id=agg,
        aggregate_type="Message",
        payload={"msg": 1},
    )
    await session.commit()

    claimed = await service.claim_batch(batch_size=1)
    ev = claimed[0]

    # Settle with retryable error
    err = RetryableDispatchError("Webhook 503 gateway error")
    settled = await service.settle_event(
        event_id=ev.id,
        lease_token=ev.lease_token,
        status=OutboxStatus.FAILED,
        error_detail=str(err),
        is_retryable=True,
    )

    assert settled.processing_status == OutboxStatus.FAILED.value
    assert settled.retry_count == 1
    assert settled.next_retry_at is not None
    assert settled.next_retry_at > datetime.now(UTC)
    assert settled.lease_token is None
    assert "503 gateway error" in (settled.last_error or "")


@pytest.mark.asyncio
async def test_settle_event_permanent_failure_transitions_to_dead_letter(
    session: AsyncSession,
    organization: Organization,
) -> None:
    """Verifies settling with permanent error immediately marks DEAD_LETTER."""
    service = OutboxService(session, organization.id)

    agg = uuid.uuid4()
    await service.publish_event(
        event_type=AutomationEventType.MESSAGE_SENT,
        aggregate_id=agg,
        aggregate_type="Message",
        payload={"msg": 2},
    )
    await session.commit()

    claimed = await service.claim_batch(batch_size=1)
    ev = claimed[0]

    err = PermanentDispatchError("Payload unparseable 400 Bad Request")
    settled = await service.settle_event(
        event_id=ev.id,
        lease_token=ev.lease_token,
        status=OutboxStatus.DEAD_LETTER,
        error_detail=str(err),
        is_retryable=False,
    )

    assert settled.processing_status == OutboxStatus.DEAD_LETTER.value
    assert settled.processed_at is not None
    assert settled.next_retry_at is None
    assert settled.lease_token is None


@pytest.mark.asyncio
async def test_stale_worker_lease_fencing_protection(
    session: AsyncSession,
    organization: Organization,
) -> None:
    """Verifies that settling with a stolen/expired lease token raises StaleLeaseError."""
    service = OutboxService(session, organization.id)

    agg = uuid.uuid4()
    await service.publish_event(
        event_type=AutomationEventType.LEAD_CREATED,
        aggregate_id=agg,
        aggregate_type="Lead",
        payload={"msg": "fencing"},
    )
    await session.commit()

    # Worker A claims
    claimed = await service.claim_batch(batch_size=1)
    ev = claimed[0]
    stale_token = ev.lease_token

    # Simulate Worker B taking over by replacing the lease token
    new_token = "b" * 64
    ev.lease_token = new_token
    session.add(ev)
    await session.commit()

    # Worker A tries to settle with stale token
    with pytest.raises(StaleLeaseError) as exc_info:
        await service.settle_event(
            event_id=ev.id,
            lease_token=stale_token,
            status=OutboxStatus.DELIVERED,
        )

    assert "has expired or been reassigned" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_recover_expired_leases(
    session: AsyncSession,
    organization: Organization,
) -> None:
    """Verifies that recover_expired_leases() resets expired leases to FAILED for reclaim."""
    service = OutboxService(session, organization.id)

    agg = uuid.uuid4()
    await service.publish_event(
        event_type=AutomationEventType.LEAD_CREATED,
        aggregate_id=agg,
        aggregate_type="Lead",
        payload={"msg": "expired"},
    )
    await session.commit()

    claimed = await service.claim_batch(batch_size=1)
    ev = claimed[0]

    # Force expiration into past
    ev.lease_expires_at = datetime.now(UTC) - timedelta(seconds=10)
    session.add(ev)
    await session.commit()

    # Run recovery sweep
    recovered = await service.recover_expired_leases()
    assert recovered == 1

    await session.refresh(ev)
    assert ev.processing_status == OutboxStatus.FAILED.value
    assert ev.lease_token is None
    assert ev.retry_count == 1
    assert ev.next_retry_at is not None


@pytest.mark.asyncio
async def test_process_next_batch_e2e_with_simulated_dispatcher(
    session: AsyncSession,
    organization: Organization,
) -> None:
    """Verifies end-to-end batch processing with the SimulatedEventDispatcher."""
    dispatcher = SimulatedEventDispatcher()
    service = OutboxService(session, organization.id, dispatcher=dispatcher)

    # 1. Normal event (should succeed and become DELIVERED)
    agg1 = uuid.uuid4()
    await service.publish_event(
        event_type=AutomationEventType.LEAD_CREATED,
        aggregate_id=agg1,
        aggregate_type="Lead",
        payload={"lead_id": str(agg1)},
    )

    # 2. Simulated failure event (should fail and become FAILED with backoff)
    agg2 = uuid.uuid4()
    await service.publish_event(
        event_type=AutomationEventType.MESSAGE_SENT,
        aggregate_id=agg2,
        aggregate_type="Message",
        payload={"msg_id": str(agg2), "_simulate_failure": True},
    )
    await session.commit()

    processed_count = await service.process_next_batch(batch_size=10)
    assert processed_count == 2

    # Check database states
    repo = AutomationEventRepository(session)
    ev1 = await repo.get_by_idempotency_key(
        organization.id,
        f"{organization.id}:Lead:{agg1}:{AutomationEventType.LEAD_CREATED}",
    )
    ev2 = await repo.get_by_idempotency_key(
        organization.id,
        f"{organization.id}:Message:{agg2}:{AutomationEventType.MESSAGE_SENT}",
    )

    assert ev1 is not None
    assert ev1.processing_status == OutboxStatus.DELIVERED.value
    assert ev1.processed_at is not None

    assert ev2 is not None
    assert ev2.processing_status == OutboxStatus.FAILED.value
    assert ev2.retry_count == 1
    assert ev2.next_retry_at is not None
