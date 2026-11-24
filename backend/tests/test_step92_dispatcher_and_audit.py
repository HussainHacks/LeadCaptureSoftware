"""Focused tests for Phase 2, Step 9.2: Core Dispatcher & Audit ORM Immutability.

Tests verify:
1. SimulatedEventDispatcher deterministic success, retryable failure, permanent failure.
2. Structured result typing and fields.
3. Envelope simulation overrides and exception directives.
4. Custom failure matchers.
5. PII and sensitive secret masking in recorded telemetry.
6. Absolute absence of external network calls.
7. AuditLog ORM insertion succeeds.
8. AuditLog ORM update raises AuditLogImmutabilityError on flush.
9. AuditLog ORM deletion raises AuditLogImmutabilityError on flush.
10. Unrelated ORM operations (create, update, delete) function normally.
"""

import socket
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.events import (
    DispatchResult,
    EventDispatcher,
    SimulatedEventDispatcher,
)
from app.core.exceptions import (
    AuditLogImmutabilityError,
    InvalidOperationError,
    PermanentDispatchError,
    RetryableDispatchError,
)
from app.models import (
    AuditLog,
    Base,
    Organization,
    User,
)

TEST_DB_NAME = "leadgen_test_step92_db"


# ==============================================================================
# Isolated Database Fixtures (Strict Isolation from leadgen and n8n)
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


# ==============================================================================
# 1. SimulatedEventDispatcher Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_simulated_dispatcher_conforms_to_protocol():
    """Verify SimulatedEventDispatcher implements the EventDispatcher protocol."""
    dispatcher = SimulatedEventDispatcher()
    assert isinstance(dispatcher, EventDispatcher)


@pytest.mark.asyncio
async def test_simulated_dispatcher_successful_dispatch():
    """Verify successful simulated dispatch produces structured result and records history."""
    dispatcher = SimulatedEventDispatcher()
    event_id = str(uuid.uuid4())
    envelope = {
        "event_id": event_id,
        "event_type": "lead.created",
        "payload": {"lead_id": str(uuid.uuid4()), "service_type": "HVAC Repair"},
    }

    result = await dispatcher.dispatch(envelope)

    assert isinstance(result, DispatchResult)
    assert result.success is True
    assert result.event_id == event_id
    assert result.event_type == "lead.created"
    assert result.status_code == 200
    assert result.retryable is False
    assert result.error_message is None
    assert result.provider_response_id is not None
    assert result.provider_response_id.startswith("sim-receipt-")
    assert isinstance(result.dispatched_at, datetime)
    assert result.metadata["simulator"] == "SimulatedEventDispatcher"
    assert result.metadata["mode"] == "simulated_delivery"

    # History verification
    assert dispatcher.dispatch_count == 1
    assert len(dispatcher.dispatched_events) == 1
    assert len(dispatcher.dispatched_results) == 1
    assert dispatcher.dispatched_events[0]["event_id"] == event_id


@pytest.mark.asyncio
async def test_simulated_dispatcher_deterministic_retryable_failure():
    """Verify mode='fail_retryable' deterministically returns retryable failure."""
    dispatcher = SimulatedEventDispatcher(mode="fail_retryable")
    event_id = str(uuid.uuid4())
    envelope = {
        "event_id": event_id,
        "event_type": "emergency.dispatched",
        "payload": {"hazard": "GAS_LEAK"},
    }

    result = await dispatcher.dispatch(envelope)

    assert result.success is False
    assert result.retryable is True
    assert result.status_code == 503
    assert result.provider_response_id is None
    assert "Simulated transient error" in str(result.error_message)
    assert result.metadata["simulated_failure"] == "retryable"


@pytest.mark.asyncio
async def test_simulated_dispatcher_deterministic_permanent_failure():
    """Verify mode='fail_permanent' deterministically returns permanent non-retryable failure."""
    dispatcher = SimulatedEventDispatcher(mode="fail_permanent")
    event_id = str(uuid.uuid4())
    envelope = {
        "event_id": event_id,
        "event_type": "lead.qualified",
        "payload": {"score": 85},
    }

    result = await dispatcher.dispatch(envelope)

    assert result.success is False
    assert result.retryable is False
    assert result.status_code == 400
    assert result.provider_response_id is None
    assert "Simulated permanent error" in str(result.error_message)
    assert result.metadata["simulated_failure"] == "permanent"


@pytest.mark.asyncio
async def test_simulated_dispatcher_envelope_overrides():
    """Verify per-event directives in payload override dispatcher default mode."""
    dispatcher = SimulatedEventDispatcher(mode="success")

    # Override 1: Retryable failure directive
    res_retryable = await dispatcher.dispatch(
        {
            "event_id": str(uuid.uuid4()),
            "event_type": "lead.created",
            "payload": {"_simulate_failure": "retryable", "_simulate_status": 504},
        }
    )
    assert res_retryable.success is False
    assert res_retryable.retryable is True
    assert res_retryable.status_code == 504

    # Override 2: Permanent failure directive
    res_permanent = await dispatcher.dispatch(
        {
            "event_id": str(uuid.uuid4()),
            "event_type": "lead.created",
            "payload": {"_simulate_failure": "permanent", "_simulate_status": 422},
        }
    )
    assert res_permanent.success is False
    assert res_permanent.retryable is False
    assert res_permanent.status_code == 422


@pytest.mark.asyncio
async def test_simulated_dispatcher_simulated_exception_directives():
    """Verify exception directives simulate unhandled dispatcher crashes."""
    dispatcher = SimulatedEventDispatcher()

    # Retryable exception
    with pytest.raises(RetryableDispatchError) as exc_info:
        await dispatcher.dispatch(
            {
                "event_id": "test-retry-exc",
                "event_type": "lead.created",
                "payload": {"_simulate_exception": "retryable"},
            }
        )
    assert exc_info.value.retryable is True
    assert exc_info.value.status_code == 503

    # Permanent exception
    with pytest.raises(PermanentDispatchError) as exc_info:
        await dispatcher.dispatch(
            {
                "event_id": "test-perm-exc",
                "event_type": "lead.created",
                "payload": {"_simulate_exception": "permanent"},
            }
        )
    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == 400

    # Unexpected runtime crash
    with pytest.raises(RuntimeError) as exc_info:
        await dispatcher.dispatch(
            {
                "event_id": "test-crash",
                "event_type": "lead.created",
                "payload": {"_simulate_exception": "runtime"},
            }
        )
    assert "Simulated unexpected simulator crash" in str(exc_info.value)


@pytest.mark.asyncio
async def test_simulated_dispatcher_raise_on_failure_flag():
    """Verify raise_on_failure=True raises typed exceptions instead of returning failed results."""
    dispatcher_retry = SimulatedEventDispatcher(mode="fail_retryable", raise_on_failure=True)
    with pytest.raises(RetryableDispatchError):
        await dispatcher_retry.dispatch({"event_id": "e1", "payload": {}})

    dispatcher_perm = SimulatedEventDispatcher(mode="fail_permanent", raise_on_failure=True)
    with pytest.raises(PermanentDispatchError):
        await dispatcher_perm.dispatch({"event_id": "e2", "payload": {}})


@pytest.mark.asyncio
async def test_simulated_dispatcher_custom_matcher():
    """Verify custom failure_matcher callback handles conditional routing."""

    def custom_matcher(env: dict[str, Any]):
        if env.get("event_type") == "special.fatal":
            return PermanentDispatchError("Custom matcher fatal error", status_code=403)
        if env.get("event_type") == "special.retry":
            return DispatchResult(
                success=False,
                event_id="custom-id",
                event_type="special.retry",
                status_code=502,
                retryable=True,
                error_message="Custom matcher retryable",
            )
        return None  # Fallback to default dispatcher mode

    dispatcher = SimulatedEventDispatcher(failure_matcher=custom_matcher)

    # 1. Custom exception from matcher
    with pytest.raises(PermanentDispatchError) as exc_info:
        await dispatcher.dispatch({"event_type": "special.fatal", "payload": {}})
    assert exc_info.value.status_code == 403

    # 2. Custom DispatchResult from matcher
    res = await dispatcher.dispatch({"event_type": "special.retry", "payload": {}})
    assert res.success is False
    assert res.retryable is True
    assert res.status_code == 502

    # 3. Fallback to normal behavior
    res_normal = await dispatcher.dispatch({"event_type": "normal.event", "payload": {}})
    assert res_normal.success is True


@pytest.mark.asyncio
async def test_simulated_dispatcher_redacts_sensitive_payload_fields():
    """Verify sensitive customer PII and credential keys are masked in telemetry."""
    dispatcher = SimulatedEventDispatcher()
    envelope = {
        "event_id": "redaction-test",
        "event_type": "lead.created",
        "payload": {
            "lead_id": "l-123",
            "customer_phone": "+15551234567",
            "customer_email": "alice@example.com",
            "secret_token": "secret_abc_123",
            "api_key": "sk-12345",
            "auth_password": "supersecretpassword",
            "nested": {
                "user_phone": "+15559876543",
                "clean_metadata": "allowed",
            },
        },
    }

    await dispatcher.dispatch(envelope)

    recorded_payload = dispatcher.dispatched_events[0]["payload"]
    assert recorded_payload["lead_id"] == "l-123"
    assert recorded_payload["customer_phone"] == "[REDACTED]"
    assert recorded_payload["customer_email"] == "[REDACTED]"
    assert recorded_payload["secret_token"] == "[REDACTED]"
    assert recorded_payload["api_key"] == "[REDACTED]"
    assert recorded_payload["auth_password"] == "[REDACTED]"
    assert recorded_payload["nested"]["user_phone"] == "[REDACTED]"
    assert recorded_payload["nested"]["clean_metadata"] == "allowed"


@pytest.mark.asyncio
async def test_simulated_dispatcher_clear_history():
    """Verify clear() resets internal recording buffers."""
    dispatcher = SimulatedEventDispatcher()
    await dispatcher.dispatch({"event_id": "e1", "payload": {}})
    await dispatcher.dispatch({"event_id": "e2", "payload": {}})
    assert dispatcher.dispatch_count == 2

    dispatcher.clear()
    assert dispatcher.dispatch_count == 0
    assert dispatcher.dispatched_events == []
    assert dispatcher.dispatched_results == []


@pytest.mark.asyncio
async def test_simulated_dispatcher_zero_network_io(monkeypatch):
    """Verify that SimulatedEventDispatcher makes zero network/socket calls."""

    def forbidden_connect(*args, **kwargs):
        raise AssertionError("SimulatedEventDispatcher attempted a network socket connection!")

    monkeypatch.setattr(socket.socket, "connect", forbidden_connect)

    dispatcher = SimulatedEventDispatcher()
    res1 = await dispatcher.dispatch({"event_id": "net-1", "payload": {}})
    assert res1.success is True

    dispatcher.mode = "fail_retryable"
    res2 = await dispatcher.dispatch({"event_id": "net-2", "payload": {}})
    assert res2.success is False


# ==============================================================================
# 2. AuditLog ORM Immutability Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_audit_log_creation_succeeds(session: AsyncSession):
    """Verify legitimate creation and insertion of AuditLog records succeeds cleanly."""
    org = Organization(
        name="Audit Test Org",
        slug=f"audit-org-{uuid.uuid4().hex[:8]}",
        industry="hvac",
        timezone="America/Chicago",
        default_slot_capacity=2,
        settings={},
        is_active=True,
    )
    session.add(org)
    await session.flush()

    audit_entry = AuditLog(
        organization_id=org.id,
        user_id=None,
        action="LEAD_SAFETY_TRIGGERED",
        resource_type="conversation",
        resource_id=str(uuid.uuid4()),
        changes={"hazard_type": "GAS_LEAK", "severity": "HIGH"},
        ip_address="127.0.0.1",
    )
    session.add(audit_entry)
    await session.flush()

    # Verify record was persisted with attributes intact
    saved = await session.get(AuditLog, audit_entry.id)
    assert saved is not None
    assert saved.action == "LEAD_SAFETY_TRIGGERED"
    assert saved.resource_type == "conversation"
    assert saved.changes["hazard_type"] == "GAS_LEAK"


@pytest.mark.asyncio
async def test_audit_log_update_blocked_by_orm_listener(session: AsyncSession):
    """Verify ORM updates on existing AuditLog records raise AuditLogImmutabilityError on flush."""
    org = Organization(
        name="Audit Update Org",
        slug=f"audit-upd-{uuid.uuid4().hex[:8]}",
        industry="hvac",
        timezone="America/Chicago",
        default_slot_capacity=2,
        settings={},
        is_active=True,
    )
    session.add(org)
    await session.flush()

    audit_entry = AuditLog(
        organization_id=org.id,
        user_id=None,
        action="ORIGINAL_ACTION",
        resource_type="lead",
        resource_id=str(uuid.uuid4()),
        changes={"field": "original"},
    )
    session.add(audit_entry)
    await session.flush()

    # Attempt to modify the existing audit log
    audit_entry.action = "TAMPERED_ACTION"
    audit_entry.changes = {"field": "tampered"}

    with pytest.raises(AuditLogImmutabilityError) as exc_info:
        await session.flush()

    assert "AuditLog records are immutable and cannot be updated" in str(exc_info.value)
    assert isinstance(exc_info.value, InvalidOperationError)


@pytest.mark.asyncio
async def test_audit_log_delete_blocked_by_orm_listener(session: AsyncSession):
    """Verify ORM deletes of existing AuditLog records raise AuditLogImmutabilityError on flush."""
    org = Organization(
        name="Audit Delete Org",
        slug=f"audit-del-{uuid.uuid4().hex[:8]}",
        industry="hvac",
        timezone="America/Chicago",
        default_slot_capacity=2,
        settings={},
        is_active=True,
    )
    session.add(org)
    await session.flush()

    audit_entry = AuditLog(
        organization_id=org.id,
        user_id=None,
        action="CANNOT_DELETE_ME",
        resource_type="appointment",
        resource_id=str(uuid.uuid4()),
    )
    session.add(audit_entry)
    await session.flush()

    # Attempt to delete the existing audit log
    await session.delete(audit_entry)

    with pytest.raises(AuditLogImmutabilityError) as exc_info:
        await session.flush()

    assert "AuditLog records are immutable and cannot be deleted" in str(exc_info.value)
    assert isinstance(exc_info.value, InvalidOperationError)


@pytest.mark.asyncio
async def test_unrelated_orm_operations_continue_to_work(session: AsyncSession):
    """Verify ORM update and delete operations on unrelated models are not impacted."""
    # 1. Create Organization and User
    org = Organization(
        name="Unrelated Org",
        slug=f"unrel-{uuid.uuid4().hex[:8]}",
        industry="hvac",
        timezone="America/Chicago",
        default_slot_capacity=2,
        settings={},
        is_active=True,
    )
    session.add(org)
    await session.flush()

    user = User(
        email=f"user-{uuid.uuid4().hex[:6]}@example.com",
        password_hash="mock_hashed_secret_value",
        first_name="John",
        last_name="Doe",
        is_active=True,
    )
    session.add(user)
    await session.flush()

    # 2. Update Organization (must succeed!)
    org.name = "Updated Organization Name"
    await session.flush()
    assert org.name == "Updated Organization Name"

    # 3. Delete User (must succeed!)
    await session.delete(user)
    await session.flush()

    deleted_user = await session.get(User, user.id)
    assert deleted_user is None
