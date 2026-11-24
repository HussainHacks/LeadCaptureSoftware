"""Tenant-scoped service managing the lifecycle, intake, and deduplication of leads."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    EntityNotFoundError,
    InvalidOperationError,
    ValidationError,
)
from app.core.phone import normalize_phone_number
from app.core.validators import validate_email_address
from app.models.enums import LeadSource, LeadStatus, LeadUrgency
from app.models.lead import Lead
from app.repositories.entities import LeadRepository, OrganizationRepository
from app.schemas.lead import LeadCreate, LeadUpdate
from app.services.base import TenantService

# Authoritative Lead Lifecycle State Machine (DATABASE_DESIGN.md Section 5.1)
VALID_LEAD_TRANSITIONS: dict[LeadStatus, set[LeadStatus]] = {
    LeadStatus.NEW: {
        LeadStatus.CONTACTED,
        LeadStatus.QUALIFYING,
        LeadStatus.UNQUALIFIED,
        LeadStatus.LOST,
        LeadStatus.ARCHIVED,
    },
    LeadStatus.CONTACTED: {
        LeadStatus.QUALIFYING,
        LeadStatus.UNQUALIFIED,
        LeadStatus.LOST,
        LeadStatus.ARCHIVED,
    },
    LeadStatus.QUALIFYING: {
        LeadStatus.QUALIFIED,
        LeadStatus.UNQUALIFIED,
        LeadStatus.LOST,
        LeadStatus.ARCHIVED,
    },
    LeadStatus.QUALIFIED: {
        LeadStatus.APPOINTMENT_OFFERED,
        LeadStatus.APPOINTMENT_BOOKED,
        LeadStatus.UNQUALIFIED,
        LeadStatus.LOST,
        LeadStatus.ARCHIVED,
    },
    LeadStatus.APPOINTMENT_OFFERED: {
        LeadStatus.APPOINTMENT_BOOKED,
        LeadStatus.LOST,
        LeadStatus.ARCHIVED,
    },
    LeadStatus.APPOINTMENT_BOOKED: {
        LeadStatus.LOST,
        LeadStatus.ARCHIVED,
    },
    LeadStatus.UNQUALIFIED: {
        LeadStatus.ARCHIVED,
        LeadStatus.QUALIFYING,
    },
    LeadStatus.LOST: {
        LeadStatus.ARCHIVED,
        LeadStatus.QUALIFYING,
    },
    LeadStatus.ARCHIVED: {
        LeadStatus.QUALIFYING,
    },
}

ACTIVE_QUALIFICATION_STATUSES = {
    LeadStatus.NEW.value,
    LeadStatus.CONTACTED.value,
    LeadStatus.QUALIFYING.value,
    LeadStatus.APPOINTMENT_OFFERED.value,
}


class LeadService(TenantService):
    """Tenant-scoped service managing leads, deduplication, and status transitions."""

    def __init__(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        lead_repo: LeadRepository | None = None,
        org_repo: OrganizationRepository | None = None,
    ) -> None:
        super().__init__(session, organization_id)
        self.lead_repo = lead_repo or LeadRepository(session)
        self.org_repo = org_repo or OrganizationRepository(session)

    async def create_lead(
        self,
        data: LeadCreate,
        *,
        dedup_window_days: int = 14,
    ) -> Lead:
        """Create a new lead or return an existing active lead on follow-up inquiries.

        Implements the approved 14-day rolling deduplication logic:
        - Normalizes phone numbers to standard E.164.
        - Scopes lookups strictly to self.organization_id (cross-tenant isolation).
        - Case A: If an active lead exists for the same issue within 14 days, returns
          the existing lead without creating a duplicate row.
        - Case B: If a previous lead is for a different HVAC issue or is concluded
          (APPOINTMENT_BOOKED, LOST, etc.), creates a new lead and links prior_lead_id.
        - Concurrency limitation: PostgreSQL schema intentionally has no unique constraint
          on (organization_id, phone). High-concurrency duplicate prevention is achieved
          via upstream serialization or application-level locks.
        """
        # 1. Enforce tenant scope
        self.validate_tenant_scope(data.organization_id)

        # 2. Validate organization exists
        org = await self.org_repo.get_by_id(self.organization_id)
        if org is None:
            raise EntityNotFoundError("Organization", self.organization_id)

        # 3. Validate and normalize inputs
        normalized_phone = normalize_phone_number(data.phone)
        normalized_email = validate_email_address(data.email)

        # Field length validations
        if data.first_name and len(data.first_name.strip()) > 80:
            raise ValidationError("First name cannot exceed 80 characters.")
        if data.last_name and len(data.last_name.strip()) > 80:
            raise ValidationError("Last name cannot exceed 80 characters.")
        if data.postal_code and len(data.postal_code.strip()) > 20:
            raise ValidationError("Postal code cannot exceed 20 characters.")
        if data.street_address and len(data.street_address.strip()) > 255:
            raise ValidationError("Street address cannot exceed 255 characters.")
        if data.service_type and len(data.service_type.strip()) > 80:
            raise ValidationError("Service type cannot exceed 80 characters.")
        if data.equipment_type and len(data.equipment_type.strip()) > 80:
            raise ValidationError("Equipment type cannot exceed 80 characters.")

        prior_lead_id = data.prior_lead_id

        # 4. If prior_lead_id explicitly passed, ensure it exists within this tenant
        if prior_lead_id is not None:
            prior = await self.lead_repo.get_by_id(self.organization_id, prior_lead_id)
            if prior is None:
                raise EntityNotFoundError("Lead", prior_lead_id)
        else:
            # 5. Evaluate rolling 14-day duplicate window within the organization
            since = datetime.now(UTC) - timedelta(days=dedup_window_days)
            recent_lead = await self.lead_repo.find_recent_by_phone(
                self.organization_id,
                normalized_phone,
                since=since,
            )

            if recent_lead is not None:
                new_service = (data.service_type or "").strip().lower()
                existing_service = (recent_lead.service_type or "").strip().lower()

                # Case B: Different HVAC system / distinct problem described
                is_different_issue = bool(
                    new_service and existing_service and new_service != existing_service
                )

                if is_different_issue:
                    # Separate issue: create new lead with prior_lead_id reference
                    prior_lead_id = recent_lead.id
                elif recent_lead.status in ACTIVE_QUALIFICATION_STATUSES:
                    # Case A: Same issue on active lead -> Return existing lead
                    return recent_lead
                else:
                    # Case B: Prior lead is concluded -> Create new lead referencing prior
                    prior_lead_id = recent_lead.id

        # 6. Instantiate and persist new Lead
        lead = Lead(
            organization_id=self.organization_id,
            first_name=data.first_name.strip() if data.first_name else None,
            last_name=data.last_name.strip() if data.last_name else None,
            phone=normalized_phone,
            email=normalized_email,
            postal_code=data.postal_code.strip() if data.postal_code else None,
            street_address=data.street_address.strip() if data.street_address else None,
            customer_timezone=data.customer_timezone.strip() if data.customer_timezone else None,
            timezone_source=data.timezone_source.value,
            service_type=data.service_type.strip() if data.service_type else None,
            equipment_type=data.equipment_type.strip() if data.equipment_type else None,
            problem_description=(
                data.problem_description.strip() if data.problem_description else None
            ),
            urgency=data.urgency.value,
            qualification_score=0,
            status=LeadStatus.NEW.value,
            sms_consent_status=data.sms_consent_status.value,
            email_consent_status=data.email_consent_status.value,
            source=data.source.value,
            prior_lead_id=prior_lead_id,
            metadata_=data.metadata,
        )

        return await self.lead_repo.add(self.organization_id, lead)

    async def get_lead(
        self,
        lead_id: uuid.UUID,
        *,
        include_deleted: bool = False,
    ) -> Lead:
        """Retrieve a lead by ID strictly scoped to the bound organization."""
        return await self.lead_repo.get_by_id_or_raise(
            self.organization_id,
            lead_id,
            include_deleted=include_deleted,
        )

    async def list_leads(
        self,
        *,
        status: LeadStatus | str | None = None,
        urgency: LeadUrgency | str | None = None,
        source: LeadSource | str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Lead]:
        """List leads scoped to the bound organization with filtering and pagination."""
        return await self.lead_repo.list(
            self.organization_id,
            status=status,
            urgency=urgency,
            source=source,
            created_after=created_after,
            created_before=created_before,
            include_deleted=include_deleted,
            limit=limit,
            offset=offset,
        )

    async def count_leads(
        self,
        *,
        status: LeadStatus | str | None = None,
        urgency: LeadUrgency | str | None = None,
        source: LeadSource | str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        include_deleted: bool = False,
    ) -> int:
        """Count leads scoped to the bound organization with filtering."""
        return await self.lead_repo.count(
            self.organization_id,
            status=status,
            urgency=urgency,
            source=source,
            created_after=created_after,
            created_before=created_before,
            include_deleted=include_deleted,
        )

    async def update_lead(
        self,
        lead_id: uuid.UUID,
        data: LeadUpdate,
    ) -> Lead:
        """Update permitted profile attributes of an active lead.

        Enforces:
        - Cannot update a soft-deleted lead.
        - Untrusted clients cannot modify qualification_score, status, or deleted_at.
        - Normalizes updated phone and email values.
        """
        lead = await self.lead_repo.get_by_id_or_raise(
            self.organization_id,
            lead_id,
            include_deleted=True,
        )

        if lead.deleted_at is not None:
            raise InvalidOperationError(f"Lead '{lead_id}' is soft-deleted and cannot be updated.")

        # Apply and validate permitted updates
        if data.phone is not None:
            lead.phone = normalize_phone_number(data.phone)
        if data.email is not None:
            lead.email = validate_email_address(data.email)
        if data.first_name is not None:
            lead.first_name = data.first_name.strip() if data.first_name else None
        if data.last_name is not None:
            lead.last_name = data.last_name.strip() if data.last_name else None
        if data.postal_code is not None:
            lead.postal_code = data.postal_code.strip() if data.postal_code else None
        if data.street_address is not None:
            lead.street_address = data.street_address.strip() if data.street_address else None
        if data.customer_timezone is not None:
            lead.customer_timezone = (
                data.customer_timezone.strip() if data.customer_timezone else None
            )
        if data.timezone_source is not None:
            lead.timezone_source = data.timezone_source.value
        if data.service_type is not None:
            lead.service_type = data.service_type.strip() if data.service_type else None
        if data.equipment_type is not None:
            lead.equipment_type = data.equipment_type.strip() if data.equipment_type else None
        if data.problem_description is not None:
            lead.problem_description = (
                data.problem_description.strip() if data.problem_description else None
            )
        if data.urgency is not None:
            lead.urgency = data.urgency.value
        if data.sms_consent_status is not None:
            lead.sms_consent_status = data.sms_consent_status.value
        if data.email_consent_status is not None:
            lead.email_consent_status = data.email_consent_status.value
        if data.metadata is not None:
            lead.metadata_ = data.metadata

        await self.flush()
        return lead

    async def change_status(
        self,
        lead_id: uuid.UUID,
        new_status: LeadStatus | str,
    ) -> Lead:
        """Transition a lead's lifecycle status using the approved state machine."""
        lead = await self.lead_repo.get_by_id_or_raise(
            self.organization_id,
            lead_id,
            include_deleted=False,
        )

        target_status = LeadStatus(new_status) if isinstance(new_status, str) else new_status
        current_status = LeadStatus(lead.status)

        if target_status == current_status:
            return lead

        allowed_targets = VALID_LEAD_TRANSITIONS.get(current_status, set())
        if target_status not in allowed_targets:
            raise InvalidOperationError(
                f"Invalid lead status transition from '{current_status.value}' to "
                f"'{target_status.value}'."
            )

        lead.status = target_status.value
        await self.flush()
        return lead

    async def change_urgency(
        self,
        lead_id: uuid.UUID,
        new_urgency: LeadUrgency | str,
    ) -> Lead:
        """Update a lead's urgency level through validated service methods."""
        lead = await self.lead_repo.get_by_id_or_raise(
            self.organization_id,
            lead_id,
            include_deleted=False,
        )

        target_urgency = LeadUrgency(new_urgency) if isinstance(new_urgency, str) else new_urgency
        lead.urgency = target_urgency.value
        await self.flush()
        return lead

    async def update_qualification(
        self,
        lead_id: uuid.UUID,
        qualification_score: int,
        status: LeadStatus | str | None = None,
    ) -> Lead:
        """Internal service method to update qualification score and lifecycle status.

        Protected from public client request schemas; invoked by QualificationService
        or internal automation workflows.
        """
        lead = await self.lead_repo.get_by_id_or_raise(
            self.organization_id,
            lead_id,
            include_deleted=False,
        )
        if not (0 <= qualification_score <= 100):
            raise ValidationError("qualification_score must be between 0 and 100.")
        lead.qualification_score = qualification_score

        if status is not None:
            target_status = LeadStatus(status) if isinstance(status, str) else status
            current_status = LeadStatus(lead.status)
            if target_status != current_status:
                allowed_targets = VALID_LEAD_TRANSITIONS.get(current_status, set())
                if target_status not in allowed_targets:
                    raise InvalidOperationError(
                        f"Invalid lead status transition from '{current_status.value}' to "
                        f"'{target_status.value}'."
                    )
                lead.status = target_status.value

        await self.flush()
        return lead

    async def soft_delete_lead(
        self,
        lead_id: uuid.UUID,
    ) -> Lead:
        """Soft delete an active lead."""
        return await self.lead_repo.soft_delete(self.organization_id, lead_id)
