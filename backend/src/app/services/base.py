"""Service layer foundation orchestrating business logic and repositories."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import TenantAccessViolationError


class BaseService:
    """Base service orchestrating domain operations.

    Services coordinate business logic, enforce domain invariants, and interact
    with repositories for persistence. Services receive their database session
    and dependencies explicitly via constructor injection.

    Transaction boundaries:
    Services do not commit transactions unexpectedly. Database mutations are flushed
    to validate constraints, while committing is managed at explicit unit-of-work
    boundaries or request lifecycles.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def flush(self) -> None:
        """Flush pending changes to the database without committing the transaction."""
        await self.session.flush()

    async def commit(self) -> None:
        """Commit the current transaction explicitly."""
        await self.session.commit()

    async def rollback(self) -> None:
        """Roll back the current transaction."""
        await self.session.rollback()


class TenantService(BaseService):
    """Base service for tenant-scoped operations.

    Maintains explicit organization scoping for all business operations.
    Prevents cross-tenant leaks by ensuring that incoming payloads, parameters,
    and associated entities strictly match the bound organization_id.
    """

    def __init__(self, session: AsyncSession, organization_id: uuid.UUID) -> None:
        super().__init__(session)
        self.organization_id = organization_id

    def validate_tenant_scope(self, target_org_id: uuid.UUID) -> None:
        """Verify that an external or payload organization matches the service tenant scope."""
        if target_org_id != self.organization_id:
            raise TenantAccessViolationError(
                f"Target organization '{target_org_id}' does not match service "
                f"tenant scope '{self.organization_id}'."
            )
