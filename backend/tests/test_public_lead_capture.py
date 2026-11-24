"""Database integration tests for public lead capture endpoint and SMS thread logging."""

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.integrations.sms import SmsDeliveryResult
from app.main import create_application
from app.models import (
    AutomationEvent,
    Base,
    Conversation,
    CustomerConsent,
    Lead,
    Message,
    Organization,
    OrganizationMembership,
    QualificationResult,
    Service,
    User,
)
from app.models.enums import DeliveryStatus, UserRole

TEST_DB_NAME = "leadgen_test_public_capture_db"


@pytest_asyncio.fixture(loop_scope="module", scope="module", autouse=True)
async def setup_test_db():
    """Create an isolated temporary test database for public lead capture tests."""
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
    """Yield an async session bound to the isolated test database."""
    settings = get_settings()
    base_url = settings.DATABASE_URL.rsplit("/", 1)[0]
    test_db_url = f"{base_url}/{TEST_DB_NAME}"

    engine = create_async_engine(test_db_url, poolclass=NullPool)
    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as sess:
        yield sess
    await engine.dispose()


@pytest.mark.asyncio
async def test_public_lead_capture_end_to_end(session: AsyncSession) -> None:
    """Verify public POST /api/public/leads resolves tenant and runs intake."""
    site_key = f"site_{uuid.uuid4().hex}"
    org = Organization(
        name="Public Test HVAC",
        slug=f"pub-hvac-{uuid.uuid4().hex[:6]}",
        settings={
            "site_key": site_key,
            "service_area_zips": ["75001"],
        },
    )
    session.add(org)
    await session.flush()

    svc = Service(
        organization_id=org.id,
        service_name="AC Repair",
        service_code="AC-REPAIR",
        estimated_duration_minutes=60,
        base_price=125.0,
        active=True,
    )
    session.add(svc)
    await session.commit()

    app = create_application(Settings(DEMO_ENABLED=False))

    async def _override_db():
        yield session

    app.dependency_overrides[get_db] = _override_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Invalid site key -> 401
        bad_res = await client.post(
            "/api/public/leads",
            headers={"X-Site-Key": "invalid-key"},
            json={"name": "Jane Doe", "phone": "+15550103333"},
        )
        assert bad_res.status_code == 401

        # Valid site key -> 201 and full intake flow
        ok_res = await client.post(
            "/api/public/leads",
            headers={"X-Site-Key": site_key},
            json={
                "name": "Jane <b>Doe</b>",
                "phone": "+1 (555) 010-4444",
                "email": "jane@example.com",
                "service_needed": "AC Repair",
                "message": "Cooling stopped working today.",
                "postal_code": "75001",
                "consent": True,
                "source_page": "https://pubhvac.example.com/contact",
            },
        )
        assert ok_res.status_code == 201, ok_res.text
        lead_id = uuid.UUID(ok_res.json()["lead_id"])

    lead = (await session.execute(select(Lead).where(Lead.id == lead_id))).scalar_one()
    assert lead.organization_id == org.id
    assert lead.first_name == "Jane"
    assert lead.last_name == "Doe"
    assert lead.phone == "+15550104444"

    consent = (
        await session.execute(select(CustomerConsent).where(CustomerConsent.lead_id == lead.id))
    ).scalar_one()
    assert consent.consent_status == "OPTED_IN"

    conv = (
        await session.execute(select(Conversation).where(Conversation.lead_id == lead.id))
    ).scalar_one()
    assert conv.status == "AI_ACTIVE"

    qual = (
        await session.execute(
            select(QualificationResult).where(QualificationResult.lead_id == lead.id)
        )
    ).scalar_one()
    assert qual.category in ("HOT", "WARM")

    ev = (
        await session.execute(
            select(AutomationEvent).where(AutomationEvent.organization_id == org.id)
        )
    ).scalar_one()
    assert ev.event_type == "LEAD_CREATED"


@pytest.mark.asyncio
async def test_outbound_sms_logs_delivery_on_conversation_thread(session: AsyncSession) -> None:
    """Verify outbound SMS dispatch (Twilio / Simulated) updates Message delivery_status & SID."""
    org = Organization(name="SMS Log HVAC", slug=f"sms-hvac-{uuid.uuid4().hex[:6]}")
    user = User(
        email=f"owner_{uuid.uuid4().hex[:6]}@example.com",
        first_name="Owner",
        last_name="User",
        password_hash=hash_password("TestPassword123!"),
        is_active=True,
    )
    session.add_all([org, user])
    await session.flush()

    session.add(
        OrganizationMembership(
            organization_id=org.id,
            user_id=user.id,
            role=UserRole.OWNER.value,
            is_active=True,
        )
    )
    lead = Lead(
        organization_id=org.id,
        first_name="Bob",
        last_name="Builder",
        phone="+15550105555",
        sms_consent_status="OPTED_IN",
    )
    session.add(lead)
    await session.flush()

    session.add(
        CustomerConsent(
            organization_id=org.id,
            lead_id=lead.id,
            channel="SMS",
            consent_status="OPTED_IN",
            consent_source="WEB_FORM",
        )
    )
    conv = Conversation(
        organization_id=org.id,
        lead_id=lead.id,
        channel="SMS",
        status="AI_ACTIVE",
    )
    session.add(conv)
    await session.commit()

    token = create_access_token({"sub": str(user.id), "org_id": str(org.id)})
    app = create_application(Settings(DEMO_ENABLED=False))

    async def _override_db():
        yield session

    app.dependency_overrides[get_db] = _override_db

    fake_sender = AsyncMock()
    fake_sender.send_sms.return_value = SmsDeliveryResult(
        success=True,
        provider="twilio",
        external_message_id="SM_TEST_RECEIPT_001",
        status_code=201,
        metadata={"provider": "twilio", "twilio_status": "queued"},
    )

    with patch("app.api.conversations.get_sms_sender", return_value=fake_sender):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.post(
                f"/api/conversations/{conv.id}/messages",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Organization-ID": str(org.id),
                },
                json={"message_content": "Your technician is on the way.", "sender": "staff"},
            )
            assert res.status_code == 200, res.text
            body = res.json()
            assert body["delivery_status"] == DeliveryStatus.SENT.value
            assert body["external_message_id"] == "SM_TEST_RECEIPT_001"

    msg_row = (
        await session.execute(select(Message).where(Message.conversation_id == conv.id))
    ).scalar_one()
    assert msg_row.delivery_status == DeliveryStatus.SENT.value
    assert msg_row.external_message_id == "SM_TEST_RECEIPT_001"
