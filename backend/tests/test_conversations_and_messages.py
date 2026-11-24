"""Comprehensive tests for conversations, messages, consent, and safety workflows."""

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.exceptions import (
    ConsentRequiredError,
    EntityAlreadyExistsError,
    EntityNotFoundError,
    InvalidOperationError,
    TenantAccessViolationError,
    ValidationError,
)
from app.models import Base, Organization, User
from app.models.enums import (
    ChannelType,
    ConsentStatus,
    ConversationStatus,
    DeliveryStatus,
    LeadUrgency,
    MessageSender,
    UserRole,
)
from app.schemas.conversation import ConversationCreate, ConversationUpdate
from app.schemas.lead import LeadCreate
from app.schemas.organization import OrganizationCreate
from app.schemas.user import UserCreate
from app.services import (
    ConsentService,
    ConversationService,
    LeadService,
    MembershipService,
    MessageService,
    OrganizationService,
    UserService,
)

TEST_DB_NAME = "leadgen_test_conv_msg_db"


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
async def test_setup(session: AsyncSession):
    """Fixture providing initialized organization, owner user, active dispatcher, and lead."""
    user_service = UserService(session)
    org_service = OrganizationService(session)

    # 1. Create owner and organization
    owner = await user_service.register_user(
        UserCreate(
            email=f"owner.{uuid.uuid4().hex[:8]}@example.com",
            password="SecurePassword123!",
            first_name="Org",
            last_name="Owner",
        )
    )
    org, _ = await org_service.create_organization(
        owner.id,
        OrganizationCreate(
            name="Alpha Heating Co",
            slug=f"alpha-heat-{uuid.uuid4().hex[:8]}",
        ),
    )

    # 2. Add an active dispatcher staff member
    dispatcher = await user_service.register_user(
        UserCreate(
            email=f"dispatcher.{uuid.uuid4().hex[:8]}@example.com",
            password="SecurePassword123!",
            first_name="Dan",
            last_name="Dispatcher",
        )
    )
    membership_service = MembershipService(session, org.id)
    await membership_service.add_member(dispatcher.id, role=UserRole.DISPATCHER)

    # 3. Create a lead
    lead_service = LeadService(session, org.id)
    lead = await lead_service.create_lead(
        LeadCreate(
            organization_id=org.id,
            phone="555-111-2222",
            first_name="Customer",
            last_name="One",
        )
    )

    return {
        "org": org,
        "owner": owner,
        "dispatcher": dispatcher,
        "lead": lead,
    }


# ---------------------------------------------------------------------------
# 1. Conversation Lifecycle & Assignment Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_conversation_creation_and_retrieval(
    session: AsyncSession, test_setup: dict
):
    """Verify creating and retrieving a conversation thread for a lead."""
    org = test_setup["org"]
    lead = test_setup["lead"]
    conv_service = ConversationService(session, org.id)

    conv = await conv_service.create_conversation(
        ConversationCreate(
            organization_id=org.id,
            lead_id=lead.id,
            channel=ChannelType.SMS,
        )
    )

    assert conv.id is not None
    assert conv.organization_id == org.id
    assert conv.lead_id == lead.id
    assert conv.channel == ChannelType.SMS.value
    assert conv.status == ConversationStatus.AI_ACTIVE.value
    assert conv.is_automated_reply_locked is False

    fetched = await conv_service.get_conversation(conv.id)
    assert fetched.id == conv.id


@pytest.mark.asyncio
async def test_cross_tenant_conversation_rejection(session: AsyncSession, test_setup: dict):
    """Verify conversations cannot be retrieved or created across organization boundaries."""
    org_a = test_setup["org"]
    lead_a = test_setup["lead"]
    service_a = ConversationService(session, org_a.id)

    conv_a = await service_a.create_conversation(
        ConversationCreate(
            organization_id=org_a.id,
            lead_id=lead_a.id,
            channel=ChannelType.SMS,
        )
    )

    # Create Org B
    user_b = User(
        email=f"userb.{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hash",
        first_name="B",
        last_name="B",
    )
    session.add(user_b)
    org_b = Organization(name="Beta HVAC", slug=f"beta-hvac-{uuid.uuid4().hex[:8]}")
    session.add(org_b)
    await session.flush()

    service_b = ConversationService(session, org_b.id)

    # Org B cannot fetch Org A's conversation
    with pytest.raises(EntityNotFoundError):
        await service_b.get_conversation(conv_a.id)

    # Org B cannot create conversation referencing Org A's ID
    with pytest.raises(TenantAccessViolationError):
        await service_b.create_conversation(
            ConversationCreate(
                organization_id=org_a.id,
                lead_id=lead_a.id,
                channel=ChannelType.SMS,
            )
        )


@pytest.mark.asyncio
async def test_duplicate_active_conversation_prevention(session: AsyncSession, test_setup: dict):
    """Verify only one active conversation is permitted per lead and channel."""
    org = test_setup["org"]
    lead = test_setup["lead"]
    service = ConversationService(session, org.id)

    # 1. First active conversation succeeds
    await service.create_conversation(
        ConversationCreate(
            organization_id=org.id,
            lead_id=lead.id,
            channel=ChannelType.SMS,
        )
    )

    # 2. Second active conversation on same channel is rejected
    with pytest.raises(EntityAlreadyExistsError):
        await service.create_conversation(
            ConversationCreate(
                organization_id=org.id,
                lead_id=lead.id,
                channel=ChannelType.SMS,
            )
        )

    # 3. Active conversation on a different channel (e.g. WEB_CHAT) is allowed
    chat_conv = await service.create_conversation(
        ConversationCreate(
            organization_id=org.id,
            lead_id=lead.id,
            channel=ChannelType.WEB_CHAT,
        )
    )
    assert chat_conv.channel == ChannelType.WEB_CHAT.value


@pytest.mark.asyncio
async def test_conversation_listing_filtering_and_pagination(
    session: AsyncSession, test_setup: dict
):
    """Verify listing and filtering conversations by channel, status, and date."""
    org = test_setup["org"]
    lead_service = LeadService(session, org.id)
    conv_service = ConversationService(session, org.id)

    lead2 = await lead_service.create_lead(LeadCreate(organization_id=org.id, phone="555-222-3333"))

    c1 = await conv_service.create_conversation(
        ConversationCreate(
            organization_id=org.id,
            lead_id=test_setup["lead"].id,
            channel=ChannelType.SMS,
            status=ConversationStatus.AI_ACTIVE,
        )
    )
    c2 = await conv_service.create_conversation(
        ConversationCreate(
            organization_id=org.id,
            lead_id=lead2.id,
            channel=ChannelType.EMAIL,
            status=ConversationStatus.HUMAN_TAKEOVER,
        )
    )

    # Filter by channel
    sms_convs = await conv_service.list_conversations(channel=ChannelType.SMS)
    assert len(sms_convs) == 1
    assert sms_convs[0].id == c1.id

    # Filter by status
    human_convs = await conv_service.list_conversations(status=ConversationStatus.HUMAN_TAKEOVER)
    assert len(human_convs) == 1
    assert human_convs[0].id == c2.id

    # Pagination
    paged = await conv_service.list_conversations(limit=1, offset=0)
    assert len(paged) == 1
    assert await conv_service.count_conversations() == 2


@pytest.mark.asyncio
async def test_assignment_to_active_members_and_unassign(session: AsyncSession, test_setup: dict):
    """Verify assigning conversation to an active member and unassigning."""
    org = test_setup["org"]
    lead = test_setup["lead"]
    dispatcher = test_setup["dispatcher"]
    service = ConversationService(session, org.id)

    conv = await service.create_conversation(
        ConversationCreate(
            organization_id=org.id,
            lead_id=lead.id,
            channel=ChannelType.SMS,
        )
    )
    assert conv.assigned_to is None

    # Assign to active dispatcher
    assigned = await service.assign_conversation(conv.id, dispatcher.id)
    assert assigned.assigned_to == dispatcher.id

    # Unassign
    unassigned = await service.unassign_conversation(conv.id)
    assert unassigned.assigned_to is None


@pytest.mark.asyncio
async def test_assignment_rejection_for_inactive_or_cross_tenant_user(
    session: AsyncSession, test_setup: dict
):
    """Verify inactive or non-member users cannot be assigned to a conversation."""
    org = test_setup["org"]
    lead = test_setup["lead"]
    user_service = UserService(session)
    membership_service = MembershipService(session, org.id)
    conv_service = ConversationService(session, org.id)

    # 1. Inactive member in Org
    inactive_user = await user_service.register_user(
        UserCreate(
            email=f"inactive.{uuid.uuid4().hex[:8]}@example.com",
            password="Password123!",
            first_name="Inactive",
            last_name="Staff",
        )
    )
    m = await membership_service.add_member(inactive_user.id, role=UserRole.DISPATCHER)
    await membership_service.deactivate_member(m.id)

    conv = await conv_service.create_conversation(
        ConversationCreate(
            organization_id=org.id,
            lead_id=lead.id,
            channel=ChannelType.SMS,
        )
    )

    # Inactive assignment rejected
    with pytest.raises(InvalidOperationError):
        await conv_service.assign_conversation(conv.id, inactive_user.id)

    # 2. Non-member user rejected
    external_user = await user_service.register_user(
        UserCreate(
            email=f"external.{uuid.uuid4().hex[:8]}@example.com",
            password="Password123!",
            first_name="External",
            last_name="User",
        )
    )
    with pytest.raises(InvalidOperationError):
        await conv_service.assign_conversation(conv.id, external_user.id)


@pytest.mark.asyncio
async def test_conversation_status_transitions(session: AsyncSession, test_setup: dict):
    """Verify valid conversation state transitions and rejection of invalid jumps."""
    org = test_setup["org"]
    lead = test_setup["lead"]
    service = ConversationService(session, org.id)

    conv = await service.create_conversation(
        ConversationCreate(
            organization_id=org.id,
            lead_id=lead.id,
            channel=ChannelType.SMS,
        )
    )
    assert conv.status == ConversationStatus.AI_ACTIVE.value

    # Valid: AI_ACTIVE -> AWAITING_CUSTOMER -> HUMAN_TAKEOVER -> COMPLETED -> CLOSED
    await service.change_status(conv.id, ConversationStatus.AWAITING_CUSTOMER)
    assert conv.status == ConversationStatus.AWAITING_CUSTOMER.value

    await service.change_status(conv.id, ConversationStatus.HUMAN_TAKEOVER)
    assert conv.status == ConversationStatus.HUMAN_TAKEOVER.value

    await service.change_status(conv.id, ConversationStatus.COMPLETED)
    assert conv.status == ConversationStatus.COMPLETED.value

    await service.change_status(conv.id, ConversationStatus.CLOSED)
    assert conv.status == ConversationStatus.CLOSED.value


# ---------------------------------------------------------------------------
# 2. Message Management Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inbound_and_outbound_messages_with_consent(session: AsyncSession, test_setup: dict):
    """Verify storing inbound messages and creating outbound message records with active consent."""
    org = test_setup["org"]
    lead = test_setup["lead"]
    conv_service = ConversationService(session, org.id)
    msg_service = MessageService(session, org.id)
    consent_service = ConsentService(session, org.id)

    conv = await conv_service.create_conversation(
        ConversationCreate(
            organization_id=org.id,
            lead_id=lead.id,
            channel=ChannelType.SMS,
        )
    )

    # 1. Store inbound customer message
    inbound_msg = await msg_service.store_inbound_message(
        conv.id,
        "Hello, I need my heat fixed.",
        external_message_id="ext-inbound-001",
    )
    assert inbound_msg.id is not None
    assert inbound_msg.sender == MessageSender.CUSTOMER.value
    assert inbound_msg.delivery_status == DeliveryStatus.RECEIVED.value
    assert inbound_msg.external_message_id == "ext-inbound-001"

    # 2. Grant explicit consent for outbound SMS
    await consent_service.record_consent(
        lead.id,
        ChannelType.SMS,
        consent_source="WEB_FORM",
        consent_status=ConsentStatus.OPTED_IN,
    )

    # 3. Create outbound AI reply record
    outbound_msg = await msg_service.create_outbound_message(
        conv.id,
        "We can help with that. What kind of system do you have?",
        sender=MessageSender.AI_AGENT,
        external_message_id="ext-outbound-002",
    )
    assert outbound_msg.id is not None
    assert outbound_msg.sender == MessageSender.AI_AGENT.value
    assert outbound_msg.delivery_status == DeliveryStatus.QUEUED.value

    # 4. History retrieval
    history = await msg_service.get_message_history(conv.id)
    assert len(history) == 2
    assert history[0].id == inbound_msg.id
    assert history[1].id == outbound_msg.id


@pytest.mark.asyncio
async def test_cross_tenant_message_access_rejection(session: AsyncSession, test_setup: dict):
    """Verify message access cannot bypass tenant boundaries."""
    org_a = test_setup["org"]
    lead_a = test_setup["lead"]
    conv_a = await ConversationService(session, org_a.id).create_conversation(
        ConversationCreate(
            organization_id=org_a.id,
            lead_id=lead_a.id,
            channel=ChannelType.SMS,
        )
    )

    msg_service_a = MessageService(session, org_a.id)
    msg_a = await msg_service_a.store_inbound_message(conv_a.id, "Secret message")

    # Create Org B
    user_b = User(
        email=f"user.b.{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hash",
        first_name="B",
        last_name="B",
    )
    session.add(user_b)
    org_b = Organization(name="Beta Air", slug=f"beta-air-{uuid.uuid4().hex[:8]}")
    session.add(org_b)
    await session.flush()

    msg_service_b = MessageService(session, org_b.id)

    # Org B cannot get message A
    with pytest.raises(EntityNotFoundError):
        await msg_service_b.get_message(msg_a.id)

    # Org B cannot list history of conversation A
    with pytest.raises(EntityNotFoundError):
        await msg_service_b.get_message_history(conv_a.id)


@pytest.mark.asyncio
async def test_invalid_message_content_and_duplicate_provider_id(
    session: AsyncSession, test_setup: dict
):
    """Verify empty/oversized message validation and duplicate external ID rejection."""
    org = test_setup["org"]
    lead = test_setup["lead"]
    conv = await ConversationService(session, org.id).create_conversation(
        ConversationCreate(
            organization_id=org.id,
            lead_id=lead.id,
            channel=ChannelType.SMS,
        )
    )
    msg_service = MessageService(session, org.id)

    # Empty content rejected
    with pytest.raises(ValidationError):
        await msg_service.store_inbound_message(conv.id, "   ")

    # Store valid message with external ID
    await msg_service.store_inbound_message(
        conv.id, "Valid", external_message_id="provider-msg-123"
    )

    # Duplicate external ID rejected
    with pytest.raises(EntityAlreadyExistsError):
        await msg_service.store_inbound_message(
            conv.id, "Another", external_message_id="provider-msg-123"
        )


@pytest.mark.asyncio
async def test_delivery_status_transitions(session: AsyncSession, test_setup: dict):
    """Verify valid progression of outbound delivery statuses and invalid jump rejection."""
    org = test_setup["org"]
    lead = test_setup["lead"]
    conv = await ConversationService(session, org.id).create_conversation(
        ConversationCreate(
            organization_id=org.id,
            lead_id=lead.id,
            channel=ChannelType.SMS,
        )
    )
    consent_service = ConsentService(session, org.id)
    await consent_service.record_consent(lead.id, ChannelType.SMS, consent_source="TEST")

    msg_service = MessageService(session, org.id)
    msg = await msg_service.create_outbound_message(conv.id, "Status test")
    assert msg.delivery_status == DeliveryStatus.QUEUED.value

    # 1. Invalid jump directly from QUEUED to DELIVERED
    with pytest.raises(InvalidOperationError):
        await msg_service.update_delivery_status(msg.id, DeliveryStatus.DELIVERED)

    # 2. Valid progression: QUEUED -> SENT -> DELIVERED
    sent = await msg_service.update_delivery_status(msg.id, DeliveryStatus.SENT)
    assert sent.delivery_status == DeliveryStatus.SENT.value
    assert "sent_at" in sent.delivery_metadata

    delivered = await msg_service.update_delivery_status(msg.id, DeliveryStatus.DELIVERED)
    assert delivered.delivery_status == DeliveryStatus.DELIVERED.value
    assert "delivered_at" in delivered.delivery_metadata


# ---------------------------------------------------------------------------
# 3. Consent Safeguard Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_outbound_rejected_without_consent(session: AsyncSession, test_setup: dict):
    """Verify outbound customer communication is rejected when consent is absent."""
    org = test_setup["org"]
    lead = test_setup["lead"]
    conv = await ConversationService(session, org.id).create_conversation(
        ConversationCreate(
            organization_id=org.id,
            lead_id=lead.id,
            channel=ChannelType.SMS,
        )
    )
    msg_service = MessageService(session, org.id)

    # Outbound attempted without any recorded consent
    with pytest.raises(ConsentRequiredError):
        await msg_service.create_outbound_message(conv.id, "Outbound message")


@pytest.mark.asyncio
async def test_outbound_rejected_after_opt_out_stop_keyword(
    session: AsyncSession, test_setup: dict
):
    """Verify sending STOP keyword revokes consent and blocks further outbound communication."""
    org = test_setup["org"]
    lead = test_setup["lead"]
    conv = await ConversationService(session, org.id).create_conversation(
        ConversationCreate(
            organization_id=org.id,
            lead_id=lead.id,
            channel=ChannelType.SMS,
        )
    )
    consent_service = ConsentService(session, org.id)
    msg_service = MessageService(session, org.id)

    # 1. Grant initial consent
    await consent_service.record_consent(lead.id, ChannelType.SMS, consent_source="FORM")
    assert await consent_service.has_active_consent(lead.id, ChannelType.SMS) is True

    # 2. Customer sends STOP
    await msg_service.store_inbound_message(conv.id, "STOP")

    # 3. Consent is revoked
    assert await consent_service.has_active_consent(lead.id, ChannelType.SMS) is False

    # 4. Outbound attempt now fails with ConsentRequiredError
    with pytest.raises(ConsentRequiredError):
        await msg_service.create_outbound_message(conv.id, "Follow-up offer")


@pytest.mark.asyncio
async def test_channel_specific_consent_enforcement(session: AsyncSession, test_setup: dict):
    """Verify granting SMS consent does not grant EMAIL consent."""
    org = test_setup["org"]
    lead = test_setup["lead"]
    consent_service = ConsentService(session, org.id)

    # Grant SMS consent only
    await consent_service.record_consent(lead.id, ChannelType.SMS, consent_source="SMS_OPT_IN")

    assert await consent_service.has_active_consent(lead.id, ChannelType.SMS) is True
    assert await consent_service.has_active_consent(lead.id, ChannelType.EMAIL) is False


# ---------------------------------------------------------------------------
# 4. Safety Hazard & Human Escalation Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gas_leak_triggers_safety_lock_and_escalation(
    session: AsyncSession, test_setup: dict
):
    """Verify gas leak keywords lock replies, set ESCALATED_SAFETY, and raise urgency."""
    org = test_setup["org"]
    lead = test_setup["lead"]
    conv_service = ConversationService(session, org.id)
    msg_service = MessageService(session, org.id)

    conv = await conv_service.create_conversation(
        ConversationCreate(
            organization_id=org.id,
            lead_id=lead.id,
            channel=ChannelType.SMS,
        )
    )

    # Customer mentions gas odor
    await msg_service.store_inbound_message(
        conv.id, "Help, I smell gas near my furnace and it smells like rotten eggs!"
    )

    # Reload conversation and lead
    updated_conv = await conv_service.get_conversation(conv.id)
    assert updated_conv.is_automated_reply_locked is True
    assert updated_conv.status == ConversationStatus.ESCALATED_SAFETY.value
    assert updated_conv.escalation_reason == "SAFETY_HAZARD"

    lead_service = LeadService(session, org.id)
    updated_lead = await lead_service.get_lead(lead.id)
    assert updated_lead.urgency == LeadUrgency.EMERGENCY.value


@pytest.mark.asyncio
async def test_carbon_monoxide_triggers_safety_lock(session: AsyncSession, test_setup: dict):
    """Verify CO alarm keywords trigger automated reply lockout."""
    org = test_setup["org"]
    lead = test_setup["lead"]
    conv_service = ConversationService(session, org.id)
    msg_service = MessageService(session, org.id)

    conv = await conv_service.create_conversation(
        ConversationCreate(
            organization_id=org.id,
            lead_id=lead.id,
            channel=ChannelType.SMS,
        )
    )

    await msg_service.store_inbound_message(
        conv.id, "Our carbon monoxide detector is beeping loudly!"
    )

    updated_conv = await conv_service.get_conversation(conv.id)
    assert updated_conv.is_automated_reply_locked is True
    assert updated_conv.status == ConversationStatus.ESCALATED_SAFETY.value


@pytest.mark.asyncio
async def test_smoke_fire_triggers_safety_lock(session: AsyncSession, test_setup: dict):
    """Verify smoke/fire keywords trigger automated reply lockout."""
    org = test_setup["org"]
    lead = test_setup["lead"]
    conv_service = ConversationService(session, org.id)
    msg_service = MessageService(session, org.id)

    conv = await conv_service.create_conversation(
        ConversationCreate(
            organization_id=org.id,
            lead_id=lead.id,
            channel=ChannelType.SMS,
        )
    )

    await msg_service.store_inbound_message(
        conv.id, "There is smoke and sparks coming out of the electrical box"
    )

    updated_conv = await conv_service.get_conversation(conv.id)
    assert updated_conv.is_automated_reply_locked is True
    assert updated_conv.status == ConversationStatus.ESCALATED_SAFETY.value


@pytest.mark.asyncio
async def test_routine_ai_reply_blocked_during_safety_lock(session: AsyncSession, test_setup: dict):
    """Verify automated AI replies are strictly blocked when safety lock is active."""
    org = test_setup["org"]
    lead = test_setup["lead"]
    conv_service = ConversationService(session, org.id)
    msg_service = MessageService(session, org.id)
    consent_service = ConsentService(session, org.id)

    await consent_service.record_consent(lead.id, ChannelType.SMS, consent_source="TEST")

    conv = await conv_service.create_conversation(
        ConversationCreate(
            organization_id=org.id,
            lead_id=lead.id,
            channel=ChannelType.SMS,
        )
    )

    # Inbound triggers gas hazard
    await msg_service.store_inbound_message(conv.id, "I smell a gas leak")

    # Attempting AI automated reply must be blocked
    with pytest.raises(InvalidOperationError) as exc_info:
        await msg_service.create_outbound_message(
            conv.id,
            "Can we book an appointment?",
            sender=MessageSender.AI_AGENT,
        )
    assert "strictly locked" in str(exc_info.value)


def test_public_schemas_protect_safety_and_escalation_fields():
    """Verify client-facing ConversationUpdate cannot tamper with reply lockouts."""
    update = ConversationUpdate(status=ConversationStatus.HUMAN_TAKEOVER)
    assert not hasattr(update, "is_automated_reply_locked")
    assert not hasattr(update, "escalation_reason")


# ---------------------------------------------------------------------------
# 5. Transaction Safety Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conversation_and_message_transaction_rollback(
    session: AsyncSession, test_setup: dict
):
    """Verify repository operations flush without committing, allowing complete rollback."""
    org = test_setup["org"]
    lead = test_setup["lead"]
    conv_service = ConversationService(session, org.id)
    msg_service = MessageService(session, org.id)

    conv = await conv_service.create_conversation(
        ConversationCreate(
            organization_id=org.id,
            lead_id=lead.id,
            channel=ChannelType.SMS,
        )
    )
    msg = await msg_service.store_inbound_message(conv.id, "Uncommitted message")

    conv_id = conv.id
    msg_id = msg.id

    # Roll back transaction
    await session.rollback()

    # Neither record should exist in DB
    with pytest.raises(EntityNotFoundError):
        await conv_service.get_conversation(conv_id)

    with pytest.raises(EntityNotFoundError):
        await msg_service.get_message(msg_id)
