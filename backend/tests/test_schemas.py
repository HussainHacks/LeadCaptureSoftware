"""Unit tests for Pydantic API validation schemas."""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas import (
    AppointmentCreate,
    AppointmentStatus,
    AuditLogCreate,
    AutomationEventCreate,
    ChannelType,
    ConsentStatus,
    ConversationCreate,
    ConversationEscalationRequest,
    ConversationInternalUpdate,
    ConversationUpdate,
    CustomerConsentCreate,
    DeliveryStatus,
    InboundMessageRequest,
    InternalAuditLogCreate,
    InternalAutomationEventCreate,
    InternalMessageCreate,
    LeadCreate,
    LeadInternalUpdate,
    LeadSource,
    LeadStatus,
    LeadUpdate,
    LeadUrgency,
    MessageSender,
    OrganizationCreate,
    ORMBase,
    OutboxStatus,
    QualificationCategory,
    QualificationResultCreate,
    TimezoneSource,
    UserCreate,
    UserRead,
)


def test_organization_schema_validation():
    """Verify OrganizationCreate accepts valid fields and defaults industry/capacity."""
    org = OrganizationCreate(
        name="Apex Heating & Air",
        slug="apex-air",
    )
    assert org.industry == "HVAC"
    assert org.default_slot_capacity == 1
    assert org.timezone == "America/New_York"


def test_user_schema_password_not_exposed_in_read():
    """Verify UserCreate requires password but UserRead completely excludes password_hash."""
    user_id = uuid.uuid4()
    now = datetime.now(UTC)

    # UserCreate requires password
    with pytest.raises(ValidationError):
        UserCreate(
            email="tech@example.com",
            first_name="Jane",
            last_name="Doe",
        )

    # Valid UserCreate
    user_create = UserCreate(
        email="tech@example.com",
        first_name="Jane",
        last_name="Doe",
        password="securepassword123",
    )
    assert user_create.password == "securepassword123"

    # UserRead has NO password or password_hash field
    assert "password_hash" not in UserRead.model_fields
    assert "password" not in UserRead.model_fields

    user_read = UserRead(
        id=user_id,
        email="tech@example.com",
        first_name="Jane",
        last_name="Doe",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    dumped = user_read.model_dump()
    assert "password" not in dumped
    assert "password_hash" not in dumped


def test_lead_schema_enums_and_defaults():
    """Verify LeadCreate validates enums and sets appropriate default statuses."""
    org_id = uuid.uuid4()
    lead = LeadCreate(
        organization_id=org_id,
        phone="+15551234567",
        first_name="John",
        last_name="Smith",
    )
    assert lead.urgency == LeadUrgency.MEDIUM
    assert lead.source == LeadSource.WEBSITE_FORM
    assert lead.sms_consent_status == ConsentStatus.PENDING
    assert lead.timezone_source == TimezoneSource.UNKNOWN

    # Invalid urgency enum value
    with pytest.raises(ValidationError):
        LeadCreate(
            organization_id=org_id,
            phone="+15551234567",
            urgency="EXTREME_DANGER",  # not in LeadUrgency
        )


def test_appointment_schema_validates_end_after_start():
    """Verify AppointmentCreate strictly rejects end time <= start time."""
    org_id = uuid.uuid4()
    lead_id = uuid.uuid4()
    t_start = datetime(2026, 11, 15, 10, 0, tzinfo=UTC)
    t_end_valid = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
    t_end_invalid = datetime(2026, 11, 15, 9, 0, tzinfo=UTC)

    # Valid range
    appt = AppointmentCreate(
        organization_id=org_id,
        lead_id=lead_id,
        appointment_start=t_start,
        appointment_end=t_end_valid,
        service_type="AC Diagnostic",
    )
    assert appt.appointment_status == AppointmentStatus.CONFIRMED

    # Invalid range: end before start
    with pytest.raises(ValidationError):
        AppointmentCreate(
            organization_id=org_id,
            lead_id=lead_id,
            appointment_start=t_start,
            appointment_end=t_end_invalid,
            service_type="AC Diagnostic",
        )

    # Invalid range: end equal to start
    with pytest.raises(ValidationError):
        AppointmentCreate(
            organization_id=org_id,
            lead_id=lead_id,
            appointment_start=t_start,
            appointment_end=t_start,
            service_type="AC Diagnostic",
        )


def test_qualification_schema_score_bounds():
    """Verify QualificationResultCreate validates score between 0 and 100."""
    org_id = uuid.uuid4()
    lead_id = uuid.uuid4()

    # Valid score
    res = QualificationResultCreate(
        organization_id=org_id,
        lead_id=lead_id,
        score=85,
        category=QualificationCategory.HOT,
        reasoning="Urgent no heat call within service zone",
        recommended_action="SCHEDULE_IMMEDIATE",
    )
    assert res.score == 85

    # Score > 100 rejected
    with pytest.raises(ValidationError):
        QualificationResultCreate(
            organization_id=org_id,
            lead_id=lead_id,
            score=105,
            category=QualificationCategory.HOT,
            reasoning="Invalid score",
            recommended_action="NONE",
        )

    # Negative score rejected
    with pytest.raises(ValidationError):
        QualificationResultCreate(
            organization_id=org_id,
            lead_id=lead_id,
            score=-5,
            category=QualificationCategory.COLD,
            reasoning="Invalid score",
            recommended_action="NONE",
        )


def test_automation_event_outbox_schema():
    """Verify outbox schema requires payload, event_type, and idempotency_key."""
    org_id = uuid.uuid4()
    event = AutomationEventCreate(
        organization_id=org_id,
        event_type="lead.created",
        idempotency_key=f"lead-created-{uuid.uuid4()}",
        payload={"lead_id": str(uuid.uuid4()), "urgency": "HIGH"},
    )
    assert event.processing_status == OutboxStatus.PENDING
    assert event.retry_count == 0
    assert event.max_retries == 5


def test_customer_consent_schema():
    """Verify consent schema records channel, status, and source."""
    org_id = uuid.uuid4()
    lead_id = uuid.uuid4()
    consent = CustomerConsentCreate(
        organization_id=org_id,
        lead_id=lead_id,
        channel=ChannelType.SMS,
        consent_status=ConsentStatus.OPTED_IN,
        consent_source="WEB_FORM_CHECKBOX",
        consent_text_snapshot="I agree to receive automated SMS updates.",
    )
    assert consent.channel == ChannelType.SMS
    assert consent.consent_status == ConsentStatus.OPTED_IN


def test_audit_log_schema():
    """Verify audit log schema records administrative action."""
    org_id = uuid.uuid4()
    audit = AuditLogCreate(
        organization_id=org_id,
        action="HUMAN_TAKEOVER",
        resource_type="conversation",
        resource_id=str(uuid.uuid4()),
        changes={"status": {"before": "AI_ACTIVE", "after": "HUMAN_TAKEOVER"}},
    )
    assert audit.action == "HUMAN_TAKEOVER"
    assert audit.user_id is None


def test_lead_client_update_restricts_sensitive_fields():
    """Verify client-facing LeadUpdate excludes score, status, and deleted_at."""
    # Client LeadUpdate fields must not include sensitive lifecycle columns
    client_fields = LeadUpdate.model_fields.keys()
    assert "qualification_score" not in client_fields
    assert "status" not in client_fields
    assert "deleted_at" not in client_fields

    # Client can update legitimate profile fields
    update = LeadUpdate(
        first_name="Jane",
        last_name="Doe",
        phone="+15559876543",
        service_type="Heating",
    )
    assert update.first_name == "Jane"

    # Internal update schema permits trusted workers to update score, status, and deletion
    internal_fields = LeadInternalUpdate.model_fields.keys()
    assert "qualification_score" in internal_fields
    assert "status" in internal_fields
    assert "deleted_at" in internal_fields

    now = datetime.now(UTC)
    internal_update = LeadInternalUpdate(
        qualification_score=95,
        status=LeadStatus.QUALIFIED,
        deleted_at=now,
    )
    assert internal_update.qualification_score == 95
    assert internal_update.status == LeadStatus.QUALIFIED
    assert internal_update.deleted_at == now


def test_inbound_message_request_schema_restricts_internal_fields():
    """Verify InboundMessageRequest accepts only customer message content and forbids extra."""
    fields = InboundMessageRequest.model_fields.keys()
    assert "message_content" in fields
    assert "channel" not in fields
    assert "sender" not in fields
    assert "delivery_status" not in fields
    assert "delivery_metadata" not in fields
    assert "external_message_id" not in fields

    # 1. Valid message-content request succeeds
    inbound = InboundMessageRequest(message_content="My furnace won't turn on!")
    assert inbound.message_content == "My furnace won't turn on!"

    # 2. Supplying channel is rejected
    with pytest.raises(ValidationError):
        InboundMessageRequest(
            message_content="My furnace won't turn on!",
            channel=ChannelType.SMS,
        )

    # 3. Supplying sender, delivery_status, or delivery_metadata is rejected
    with pytest.raises(ValidationError):
        InboundMessageRequest(
            message_content="My furnace won't turn on!",
            sender=MessageSender.CUSTOMER,
        )

    with pytest.raises(ValidationError):
        InboundMessageRequest(
            message_content="My furnace won't turn on!",
            delivery_status=DeliveryStatus.DELIVERED,
        )

    with pytest.raises(ValidationError):
        InboundMessageRequest(
            message_content="My furnace won't turn on!",
            delivery_metadata={"provider": "twilio"},
        )

    with pytest.raises(ValidationError):
        InboundMessageRequest(
            message_content="My furnace won't turn on!",
            external_message_id="ext-msg-12345",
        )

    # 4. Confirm internal message persistence still supports all required backend service fields
    internal_msg = InternalMessageCreate(
        organization_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        sender=MessageSender.CUSTOMER,
        message_content="My furnace won't turn on!",
        delivery_status=DeliveryStatus.RECEIVED,
        external_message_id="ext-sms-9988",
        delivery_metadata={"provider": "simulated", "latency_ms": 42},
    )
    assert internal_msg.organization_id is not None
    assert internal_msg.conversation_id is not None
    assert internal_msg.sender == MessageSender.CUSTOMER
    assert internal_msg.message_content == "My furnace won't turn on!"
    assert internal_msg.delivery_status == DeliveryStatus.RECEIVED
    assert internal_msg.external_message_id == "ext-sms-9988"
    assert internal_msg.delivery_metadata["provider"] == "simulated"


def test_conversation_schemas_protect_safety_lockouts():
    """Verify Conversation schemas prevent clients from tampering with safety lockouts."""
    create_fields = ConversationCreate.model_fields.keys()
    assert "is_automated_reply_locked" not in create_fields
    assert "escalation_reason" not in create_fields

    update_fields = ConversationUpdate.model_fields.keys()
    assert "is_automated_reply_locked" not in update_fields
    assert "escalation_reason" not in update_fields

    # Internal update schema permits safety lockouts
    internal_fields = ConversationInternalUpdate.model_fields.keys()
    assert "is_automated_reply_locked" in internal_fields
    assert "escalation_reason" in internal_fields

    internal = ConversationInternalUpdate(
        is_automated_reply_locked=True,
        escalation_reason="SUSPECTED_GAS_LEAK",
    )
    assert internal.is_automated_reply_locked is True
    assert internal.escalation_reason == "SUSPECTED_GAS_LEAK"

    # Explicit escalation request
    esc = ConversationEscalationRequest(escalation_reason="HVAC Emergency")
    assert esc.escalation_reason == "HVAC Emergency"
    assert esc.lock_automated_reply is True


def test_internal_dto_aliases_and_isolation():
    """Verify internal service DTO aliases match expected base types."""
    assert InternalAutomationEventCreate is AutomationEventCreate
    assert InternalAuditLogCreate is AuditLogCreate
    assert issubclass(InternalMessageCreate, ORMBase)
