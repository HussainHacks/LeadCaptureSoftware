"""Tenant-scoped repository enforcing strict organization isolation."""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select

from app.core.database import Base
from app.core.exceptions import EntityNotFoundError, TenantAccessViolationError
from app.repositories.base import BaseRepository


class TenantRepository[ModelT: Base](BaseRepository[ModelT]):
    """Repository base class for all tenant-owned models.

    Every operation strictly requires an explicit organization_id. Knowing a
    record's UUID alone is never sufficient to read, mutate, or delete tenant data.
    """

    async def get_by_id(self, organization_id: uuid.UUID, id: uuid.UUID) -> ModelT | None:
        """Fetch a record by primary key strictly scoped to the specified organization."""
        stmt = select(self.model_cls).where(
            self.model_cls.organization_id == organization_id,
            self.model_cls.id == id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_or_raise(self, organization_id: uuid.UUID, id: uuid.UUID) -> ModelT:
        """Fetch a record scoped to organization, or raise EntityNotFoundError."""
        entity = await self.get_by_id(organization_id, id)
        if entity is None:
            raise EntityNotFoundError(self.model_cls.__name__, id)
        return entity

    async def list(
        self,
        organization_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[ModelT]:
        """List records strictly scoped to the specified organization."""
        stmt = (
            select(self.model_cls)
            .where(self.model_cls.organization_id == organization_id)
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(self, organization_id: uuid.UUID) -> int:
        """Count total records belonging strictly to the specified organization."""
        stmt = (
            select(func.count())
            .select_from(self.model_cls)
            .where(self.model_cls.organization_id == organization_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def add(self, organization_id: uuid.UUID, entity: ModelT) -> ModelT:
        """Persist a new tenant-owned entity, validating organization scope.

        Does not commit the transaction. Flushes changes to populate generated
        columns and evaluate database constraints within the current transaction.
        """
        entity_org_id = getattr(entity, "organization_id", None)
        if entity_org_id != organization_id:
            raise TenantAccessViolationError(
                f"Cannot add {self.model_cls.__name__}: entity organization_id '{entity_org_id}' "
                f"does not match repository tenant scope '{organization_id}'."
            )
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def delete(self, organization_id: uuid.UUID, id: uuid.UUID) -> bool:
        """Delete a record by primary key within the specified organization scope.

        Returns True if the entity was found and deleted, False otherwise.
        """
        entity = await self.get_by_id(organization_id, id)
        if entity is None:
            return False
        await self.session.delete(entity)
        await self.session.flush()
        return True

    async def delete_entity(self, organization_id: uuid.UUID, entity: ModelT) -> None:
        """Delete an existing entity instance, validating organization scope."""
        entity_org_id = getattr(entity, "organization_id", None)
        if entity_org_id != organization_id:
            raise TenantAccessViolationError(
                f"Cannot delete {self.model_cls.__name__}: entity organization_id "
                f"'{entity_org_id}' does not match repository tenant scope '{organization_id}'."
            )
        await self.session.delete(entity)
        await self.session.flush()
