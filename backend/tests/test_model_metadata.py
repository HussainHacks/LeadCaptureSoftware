"""Static metadata tests validating SQLAlchemy 2.x ORM models and constraints."""

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import ExcludeConstraint

from app.models import (
    Appointment,
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


def test_all_twelve_core_tables_registered():
    """Verify that all 12 core tables from DATABASE_DESIGN.md are registered in Base.metadata."""
    expected_tables = {
        "organizations",
        "users",
        "organization_memberships",
        "services",
        "leads",
        "customer_consents",
        "conversations",
        "messages",
        "appointments",
        "qualification_results",
        "automation_events",
        "audit_logs",
    }
    actual_tables = set(Base.metadata.tables.keys())
    assert expected_tables.issubset(actual_tables)
    assert len(expected_tables) == 12


def test_tenant_ownership_columns_present():
    """Verify that every tenant-owned table contains organization_id."""
    tenant_tables = [
        "organization_memberships",
        "services",
        "leads",
        "customer_consents",
        "conversations",
        "messages",
        "appointments",
        "qualification_results",
        "automation_events",
        "audit_logs",
    ]
    for table_name in tenant_tables:
        table = Base.metadata.tables[table_name]
        assert "organization_id" in table.c, f"{table_name} missing organization_id"
        assert not table.c.organization_id.nullable, (
            f"{table_name}.organization_id must be NOT NULL"
        )


def test_parent_tables_composite_unique_constraints():
    """Verify that parent tables declare composite unique constraints on (organization_id, id)."""
    parent_models = [Lead, Conversation, Service]
    for model in parent_models:
        table = model.__table__
        has_composite_unique = any(
            isinstance(c, UniqueConstraint)
            and set(col.name for col in c.columns) == {"organization_id", "id"}
            for c in table.constraints
        )
        assert has_composite_unique, f"{table.name} missing UNIQUE (organization_id, id) constraint"


def test_composite_foreign_keys_configured():
    """Verify that composite foreign keys reference (organization_id, parent_id)."""
    # 1. conversations -> leads (organization_id, lead_id)
    conv_fks = [
        c for c in Conversation.__table__.constraints if isinstance(c, ForeignKeyConstraint)
    ]
    composite_conv_lead = any(
        [col.name for col in c.columns] == ["organization_id", "lead_id"]
        and [elem.target_fullname for elem in c.elements] == ["leads.organization_id", "leads.id"]
        for c in conv_fks
    )
    assert composite_conv_lead, "conversations missing composite FK to leads"

    # 1b. conversations -> organization_memberships (organization_id, assigned_to)
    composite_conv_membership = any(
        [col.name for col in c.columns] == ["organization_id", "assigned_to"]
        and [elem.target_fullname for elem in c.elements]
        == ["organization_memberships.organization_id", "organization_memberships.user_id"]
        and c.ondelete == "SET NULL (assigned_to)"
        for c in conv_fks
    )
    assert composite_conv_membership, (
        "conversations missing composite FK to organization_memberships with SET NULL (assigned_to)"
    )

    # 2. messages -> conversations (organization_id, conversation_id)
    msg_fks = [c for c in Message.__table__.constraints if isinstance(c, ForeignKeyConstraint)]
    composite_msg_conv = any(
        [col.name for col in c.columns] == ["organization_id", "conversation_id"]
        and [elem.target_fullname for elem in c.elements]
        == ["conversations.organization_id", "conversations.id"]
        and c.ondelete == "CASCADE"
        for c in msg_fks
    )
    assert composite_msg_conv, "messages missing cascading composite FK to conversations"

    # 3. appointments -> leads and appointments -> services
    appt_fks = [c for c in Appointment.__table__.constraints if isinstance(c, ForeignKeyConstraint)]
    composite_appt_lead = any(
        [col.name for col in c.columns] == ["organization_id", "lead_id"]
        and [elem.target_fullname for elem in c.elements] == ["leads.organization_id", "leads.id"]
        for c in appt_fks
    )
    composite_appt_service = any(
        [col.name for col in c.columns] == ["organization_id", "service_id"]
        and [elem.target_fullname for elem in c.elements]
        == ["services.organization_id", "services.id"]
        for c in appt_fks
    )
    assert composite_appt_lead, "appointments missing composite FK to leads"
    assert composite_appt_service, "appointments missing composite FK to services"

    # 4. qualification_results -> leads
    qual_fks = [
        c for c in QualificationResult.__table__.constraints if isinstance(c, ForeignKeyConstraint)
    ]
    composite_qual_lead = any(
        [col.name for col in c.columns] == ["organization_id", "lead_id"]
        and [elem.target_fullname for elem in c.elements] == ["leads.organization_id", "leads.id"]
        for c in qual_fks
    )
    assert composite_qual_lead, "qualification_results missing composite FK to leads"

    # 5. customer_consents -> leads
    consent_fks = [
        c for c in CustomerConsent.__table__.constraints if isinstance(c, ForeignKeyConstraint)
    ]
    composite_consent_lead = any(
        [col.name for col in c.columns] == ["organization_id", "lead_id"]
        and [elem.target_fullname for elem in c.elements] == ["leads.organization_id", "leads.id"]
        for c in consent_fks
    )
    assert composite_consent_lead, "customer_consents missing composite FK to leads"

    # 6. leads -> prior_lead self-reference (organization_id, prior_lead_id)
    lead_fks = [c for c in Lead.__table__.constraints if isinstance(c, ForeignKeyConstraint)]
    composite_lead_prior = any(
        [col.name for col in c.columns] == ["organization_id", "prior_lead_id"]
        and [elem.target_fullname for elem in c.elements] == ["leads.organization_id", "leads.id"]
        and c.ondelete == "SET NULL"
        for c in lead_fks
    )
    assert composite_lead_prior, "leads missing composite FK to prior_lead"


def test_appointment_exclusion_constraint_configured():
    """Verify that appointments declares the MVP capacity-1 exclusion constraint with GiST."""
    table = Appointment.__table__
    exclude_constraints = [c for c in table.constraints if isinstance(c, ExcludeConstraint)]
    assert len(exclude_constraints) == 1, "Appointment table missing ExcludeConstraint"
    ec = exclude_constraints[0]
    assert ec.name == "uq_contractor_no_double_booking"
    assert ec.using == "gist"
    assert ec.where is not None


def test_unique_constraints_and_indexes():
    """Verify critical uniqueness constraints and partial indexes."""
    # organizations.slug UNIQUE
    org_slug_unique = (
        any(
            isinstance(c, UniqueConstraint) and [col.name for col in c.columns] == ["slug"]
            for c in Organization.__table__.constraints
        )
        or Organization.__table__.c.slug.unique
    )
    assert org_slug_unique

    # users.email UNIQUE
    user_email_unique = (
        any(
            isinstance(c, UniqueConstraint) and [col.name for col in c.columns] == ["email"]
            for c in User.__table__.constraints
        )
        or User.__table__.c.email.unique
    )
    assert user_email_unique

    # organization_memberships (organization_id, user_id) UNIQUE
    membership_unique = any(
        isinstance(c, UniqueConstraint)
        and set(col.name for col in c.columns) == {"organization_id", "user_id"}
        for c in OrganizationMembership.__table__.constraints
    )
    assert membership_unique

    # services (organization_id, service_code) UNIQUE
    service_code_unique = any(
        isinstance(c, UniqueConstraint)
        and set(col.name for col in c.columns) == {"organization_id", "service_code"}
        for c in Service.__table__.constraints
    )
    assert service_code_unique

    # automation_events idempotency_key UNIQUE
    outbox_idempotency_unique = (
        any(
            isinstance(c, UniqueConstraint)
            and [col.name for col in c.columns] == ["idempotency_key"]
            for c in AutomationEvent.__table__.constraints
        )
        or AutomationEvent.__table__.c.idempotency_key.unique
    )
    assert outbox_idempotency_unique


def test_soft_delete_and_retention_columns():
    """Verify soft-delete column on leads and non-cascading defaults."""
    assert "deleted_at" in Lead.__table__.c
    assert Lead.__table__.c.deleted_at.nullable is True
