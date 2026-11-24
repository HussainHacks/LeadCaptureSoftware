"""Service orchestrating organization creation, validation, and initial tenancy."""

import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    EntityAlreadyExistsError,
    EntityNotFoundError,
    InvalidOperationError,
    ValidationError,
)
from app.models.enums import UserRole
from app.models.membership import OrganizationMembership
from app.models.organization import Organization
from app.repositories.entities import (
    OrganizationMembershipRepository,
    OrganizationRepository,
    UserRepository,
)
from app.schemas.organization import OrganizationCreate

SLUG_REGEX = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class OrganizationService:
    """Service managing organization onboarding, validation, and retrieval."""

    def __init__(
        self,
        session: AsyncSession,
        org_repo: OrganizationRepository | None = None,
        user_repo: UserRepository | None = None,
        membership_repo: OrganizationMembershipRepository | None = None,
    ) -> None:
        self.session = session
        self.org_repo = org_repo or OrganizationRepository(session)
        self.user_repo = user_repo or UserRepository(session)
        self.membership_repo = membership_repo or OrganizationMembershipRepository(session)

    async def create_organization(
        self,
        creator_user_id: uuid.UUID,
        data: OrganizationCreate,
    ) -> tuple[Organization, OrganizationMembership]:
        """Create a new organization and assign the creator the initial OWNER role.

        Guarantees:
        1. Creator user must exist and be active.
        2. Organization name and slug are validated.
        3. Duplicate slugs are rejected.
        4. Both Organization and initial OWNER OrganizationMembership are persisted
           within the same database transaction. If either fails, neither persists.
        """
        # 1. Validate creator user exists and is active
        creator = await self.user_repo.get_by_id(creator_user_id)
        if creator is None:
            raise EntityNotFoundError("User", creator_user_id)
        if not creator.is_active:
            raise InvalidOperationError(
                f"Inactive user '{creator_user_id}' cannot create an organization."
            )

        # 2. Validate organization name
        name = data.name.strip() if data.name else ""
        if not name:
            raise ValidationError("Organization name cannot be empty.")
        if len(name) > 150:
            raise ValidationError("Organization name cannot exceed 150 characters.")

        # 3. Validate organization slug
        raw_slug = data.slug.strip() if data.slug else ""
        if not raw_slug:
            raise ValidationError("Organization slug cannot be empty.")
        slug = raw_slug.lower()
        if len(slug) > 60:
            raise ValidationError("Organization slug cannot exceed 60 characters.")
        if not SLUG_REGEX.match(slug):
            raise ValidationError(
                f"Invalid organization slug '{slug}'. Slugs must contain only lowercase "
                "alphanumeric characters and hyphens, and cannot start or end with a hyphen."
            )

        # 4. Check for duplicate slug
        existing_org = await self.org_repo.get_by_slug(slug)
        if existing_org is not None:
            raise EntityAlreadyExistsError("Organization", "slug", slug)

        # 5. Persist Organization (flushes to generate org.id within transaction)
        org = Organization(
            name=name,
            slug=slug,
            industry=data.industry,
            timezone=data.timezone,
            dispatch_phone=data.dispatch_phone,
            utility_emergency_phone=data.utility_emergency_phone,
            default_slot_capacity=data.default_slot_capacity,
            settings=data.settings,
            is_active=True,
        )
        await self.org_repo.add(org)

        # 6. Persist initial OWNER membership atomically in same transaction
        owner_membership = OrganizationMembership(
            organization_id=org.id,
            user_id=creator.id,
            role=UserRole.OWNER.value,
            is_active=True,
        )
        await self.membership_repo.add(org.id, owner_membership)

        return org, owner_membership

    async def get_organization_by_id(self, org_id: uuid.UUID) -> Organization:
        """Retrieve an organization by its primary key ID or raise EntityNotFoundError."""
        return await self.org_repo.get_by_id_or_raise(org_id)

    async def get_organization_by_slug(self, slug: str) -> Organization:
        """Retrieve an organization by its slug or raise EntityNotFoundError."""
        org = await self.org_repo.get_by_slug(slug.strip().lower())
        if org is None:
            raise EntityNotFoundError("Organization", slug)
        return org

    async def update_organization(
        self,
        org_id: uuid.UUID,
        *,
        name: str | None = None,
        industry: str | None = None,
        timezone: str | None = None,
        dispatch_phone: str | None = None,
        utility_emergency_phone: str | None = None,
        default_slot_capacity: int | None = None,
        settings: dict | None = None,
    ) -> Organization:
        """Update organization details and settings."""
        org = await self.get_organization_by_id(org_id)
        if name is not None:
            stripped_name = name.strip()
            if not stripped_name:
                raise ValidationError("Organization name cannot be empty.")
            org.name = stripped_name
        if industry is not None:
            org.industry = industry.strip()
        if timezone is not None:
            org.timezone = timezone.strip()
        if dispatch_phone is not None:
            org.dispatch_phone = dispatch_phone.strip() if dispatch_phone else None
        if utility_emergency_phone is not None:
            org.utility_emergency_phone = (
                utility_emergency_phone.strip() if utility_emergency_phone else None
            )
        if default_slot_capacity is not None:
            if default_slot_capacity < 1:
                raise ValidationError("default_slot_capacity must be at least 1.")
            org.default_slot_capacity = default_slot_capacity
        if settings is not None:
            current_settings = dict(org.settings or {})
            current_settings.update(settings)
            org.settings = current_settings

        await self.session.flush()
        return org
