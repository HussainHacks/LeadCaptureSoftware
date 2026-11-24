"""Tenant-scoped service managing organization memberships and role assignments."""

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    EntityAlreadyExistsError,
    EntityNotFoundError,
    InvalidOperationError,
)
from app.models.enums import UserRole
from app.models.membership import OrganizationMembership
from app.repositories.entities import (
    OrganizationMembershipRepository,
    OrganizationRepository,
    UserRepository,
)
from app.services.base import TenantService


class MembershipService(TenantService):
    """Tenant-scoped service managing membership lifecycle, roles, and status."""

    def __init__(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        membership_repo: OrganizationMembershipRepository | None = None,
        user_repo: UserRepository | None = None,
        org_repo: OrganizationRepository | None = None,
    ) -> None:
        super().__init__(session, organization_id)
        self.membership_repo = membership_repo or OrganizationMembershipRepository(session)
        self.user_repo = user_repo or UserRepository(session)
        self.org_repo = org_repo or OrganizationRepository(session)

    async def add_member(
        self,
        user_id: uuid.UUID,
        role: UserRole | str = UserRole.DISPATCHER,
        *,
        is_active: bool = True,
    ) -> OrganizationMembership:
        """Add an existing user to the bound organization.

        Enforces:
        1. Organization exists.
        2. User exists.
        3. No duplicate membership (uq_org_memberships_org_user).
        4. Untrusted role restriction: OWNER role cannot be granted through this method.
        5. Scoped strictly to the bound organization_id.
        """
        # Parse and validate role
        assigned_role = UserRole(role) if isinstance(role, str) else role

        # Security check: Prohibit self-granting or untrusted assignment of OWNER role
        if assigned_role == UserRole.OWNER:
            raise InvalidOperationError(
                "Cannot grant OWNER role through standard membership invitation. "
                "The OWNER role is assigned strictly during initial organization creation."
            )

        # Validate organization exists
        org = await self.org_repo.get_by_id(self.organization_id)
        if org is None:
            raise EntityNotFoundError("Organization", self.organization_id)

        # Validate user exists
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise EntityNotFoundError("User", user_id)

        # Prevent duplicate membership
        existing = await self.membership_repo.get_by_user_id(self.organization_id, user_id)
        if existing is not None:
            raise EntityAlreadyExistsError("OrganizationMembership", "user_id", user_id)

        membership = OrganizationMembership(
            organization_id=self.organization_id,
            user_id=user_id,
            role=assigned_role.value,
            is_active=is_active,
        )
        return await self.membership_repo.add(self.organization_id, membership)

    async def update_member_role(
        self,
        membership_id: uuid.UUID,
        new_role: UserRole | str,
    ) -> OrganizationMembership:
        """Update an existing member's role within the organization.

        Enforces:
        - Cannot promote a member to OWNER.
        - Cannot demote or alter the organization OWNER role.
        """
        role_enum = UserRole(new_role) if isinstance(new_role, str) else new_role

        if role_enum == UserRole.OWNER:
            raise InvalidOperationError("Cannot promote a member to OWNER through role update.")

        membership = await self.membership_repo.get_by_id_or_raise(
            self.organization_id, membership_id
        )

        if membership.role == UserRole.OWNER.value:
            raise InvalidOperationError("Cannot modify or demote the organization OWNER role.")

        membership.role = role_enum.value
        await self.flush()
        return membership

    async def deactivate_member(self, membership_id: uuid.UUID) -> OrganizationMembership:
        """Deactivate a member within the organization.

        Prevents deactivation of the organization OWNER.
        """
        membership = await self.membership_repo.get_by_id_or_raise(
            self.organization_id, membership_id
        )
        if membership.role == UserRole.OWNER.value:
            raise InvalidOperationError("Cannot deactivate the organization OWNER.")

        membership.is_active = False
        await self.flush()
        return membership

    async def activate_member(self, membership_id: uuid.UUID) -> OrganizationMembership:
        """Reactivate an inactive member within the organization."""
        membership = await self.membership_repo.get_by_id_or_raise(
            self.organization_id, membership_id
        )
        membership.is_active = True
        await self.flush()
        return membership

    async def get_membership_by_id(self, membership_id: uuid.UUID) -> OrganizationMembership:
        """Retrieve a membership strictly scoped to the bound organization."""
        return await self.membership_repo.get_by_id_or_raise(self.organization_id, membership_id)

    async def get_membership_by_user_id(self, user_id: uuid.UUID) -> OrganizationMembership | None:
        """Retrieve a user's membership strictly scoped to the bound organization."""
        return await self.membership_repo.get_by_user_id(self.organization_id, user_id)

    async def list_members(
        self,
        *,
        include_inactive: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[OrganizationMembership]:
        """List all members strictly scoped to the bound organization."""
        return await self.membership_repo.list_for_organization(
            self.organization_id,
            include_inactive=include_inactive,
            limit=limit,
            offset=offset,
        )

    async def is_active_member(self, user_id: uuid.UUID) -> bool:
        """Check whether a user is an active member of this organization."""
        membership = await self.membership_repo.get_by_user_id(self.organization_id, user_id)
        if membership is None:
            return False
        return membership.is_active
