"""Tenant-scoped service managing the HVAC contractor service catalog."""

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    EntityAlreadyExistsError,
    EntityNotFoundError,
    ValidationError,
)
from app.models.service import Service
from app.repositories.entities import OrganizationRepository, ServiceRepository
from app.schemas.service import ServiceCreate, ServiceUpdate
from app.services.base import TenantService


class ServiceService(TenantService):
    """Tenant-scoped service managing contractor services, pricing, and availability."""

    def __init__(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        service_repo: ServiceRepository | None = None,
        org_repo: OrganizationRepository | None = None,
    ) -> None:
        super().__init__(session, organization_id)
        self.service_repo = service_repo or ServiceRepository(session)
        self.org_repo = org_repo or OrganizationRepository(session)

    async def create_service(self, data: ServiceCreate) -> Service:
        """Create a new service offering for an organization.

        Enforces organization isolation, verifies organization exists,
        and prevents duplicate service codes within the organization.
        """
        self.validate_tenant_scope(data.organization_id)

        org = await self.org_repo.get_by_id(self.organization_id)
        if org is None:
            raise EntityNotFoundError("Organization", self.organization_id)

        code = data.service_code.strip()
        if not code:
            raise ValidationError("service_code cannot be empty or whitespace.")

        existing = await self.service_repo.get_by_code(self.organization_id, code)
        if existing is not None:
            raise EntityAlreadyExistsError("Service", "service_code", code)

        name = data.service_name.strip()
        if not name:
            raise ValidationError("service_name cannot be empty or whitespace.")

        service = Service(
            organization_id=self.organization_id,
            service_name=name,
            service_code=code,
            description=data.description.strip() if data.description else None,
            estimated_duration_minutes=data.estimated_duration_minutes,
            base_price=data.base_price,
            is_emergency_service=data.is_emergency_service,
            active=data.active,
        )
        return await self.service_repo.add(self.organization_id, service)

    async def get_service(self, service_id: uuid.UUID) -> Service:
        """Fetch a service strictly scoped to the organization."""
        return await self.service_repo.get_by_id_or_raise(self.organization_id, service_id)

    async def list_services(
        self,
        *,
        active_only: bool = False,
        is_emergency_service: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Service]:
        """List services scoped to the organization with optional filtering."""
        return await self.service_repo.list(
            self.organization_id,
            active_only=active_only,
            is_emergency_service=is_emergency_service,
            limit=limit,
            offset=offset,
        )

    async def count_services(
        self,
        *,
        active_only: bool = False,
        is_emergency_service: bool | None = None,
    ) -> int:
        """Count services matching organization and filter criteria."""
        return await self.service_repo.count(
            self.organization_id,
            active_only=active_only,
            is_emergency_service=is_emergency_service,
        )

    async def update_service(
        self,
        service_id: uuid.UUID,
        data: ServiceUpdate,
    ) -> Service:
        """Update service attributes with uniqueness and validation enforcement."""
        service = await self.get_service(service_id)

        if data.service_code is not None:
            new_code = data.service_code.strip()
            if not new_code:
                raise ValidationError("service_code cannot be empty.")
            if new_code.lower() != service.service_code.lower():
                existing = await self.service_repo.get_by_code(self.organization_id, new_code)
                if existing is not None and existing.id != service.id:
                    raise EntityAlreadyExistsError("Service", "service_code", new_code)
            service.service_code = new_code

        if data.service_name is not None:
            new_name = data.service_name.strip()
            if not new_name:
                raise ValidationError("service_name cannot be empty.")
            service.service_name = new_name

        if data.description is not None:
            service.description = data.description.strip() if data.description else None
        if data.estimated_duration_minutes is not None:
            if data.estimated_duration_minutes < 15:
                raise ValidationError("estimated_duration_minutes must be at least 15.")
            service.estimated_duration_minutes = data.estimated_duration_minutes
        if data.base_price is not None:
            service.base_price = data.base_price
        if data.is_emergency_service is not None:
            service.is_emergency_service = data.is_emergency_service
        if data.active is not None:
            service.active = data.active

        await self.flush()
        return service

    async def activate_service(self, service_id: uuid.UUID) -> Service:
        """Activate an offering in the service catalog."""
        service = await self.get_service(service_id)
        service.active = True
        await self.flush()
        return service

    async def deactivate_service(self, service_id: uuid.UUID) -> Service:
        """Deactivate an offering so it is hidden from booking workflows."""
        service = await self.get_service(service_id)
        service.active = False
        await self.flush()
        return service
