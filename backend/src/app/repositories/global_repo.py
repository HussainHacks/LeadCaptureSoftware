"""Global repository foundation for system-wide non-tenant entities."""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select

from app.core.database import Base
from app.core.exceptions import EntityNotFoundError
from app.repositories.base import BaseRepository


class GlobalRepository[ModelT: Base](BaseRepository[ModelT]):
    """Repository base class for global entities that are not scoped to an organization.

    Used strictly for global root entities such as User and Organization.
    Never use this repository for tenant-owned business records.
    """

    async def get_by_id(self, id: uuid.UUID) -> ModelT | None:
        """Fetch a global record by its primary key."""
        stmt = select(self.model_cls).where(self.model_cls.id == id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_or_raise(self, id: uuid.UUID) -> ModelT:
        """Fetch a global record by primary key or raise EntityNotFoundError."""
        entity = await self.get_by_id(id)
        if entity is None:
            raise EntityNotFoundError(self.model_cls.__name__, id)
        return entity

    async def list(self, *, limit: int = 100, offset: int = 0) -> Sequence[ModelT]:
        """List global records with pagination."""
        stmt = select(self.model_cls).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(self) -> int:
        """Count total global records."""
        stmt = select(func.count()).select_from(self.model_cls)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def add(self, entity: ModelT) -> ModelT:
        """Persist a new global entity.

        Does not commit the transaction. Flushes changes to populate generated
        columns and evaluate database constraints within the current transaction.
        """
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def delete(self, id: uuid.UUID) -> bool:
        """Delete a global record by its primary key.

        Returns True if the entity was found and deleted, False otherwise.
        """
        entity = await self.get_by_id(id)
        if entity is None:
            return False
        await self.session.delete(entity)
        await self.session.flush()
        return True

    async def delete_entity(self, entity: ModelT) -> None:
        """Delete an existing global entity instance."""
        await self.session.delete(entity)
        await self.session.flush()
