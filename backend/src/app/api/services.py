"""FastAPI routes for contractor service catalog management."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_membership, require_role
from app.core.database import get_db
from app.core.exceptions import (
    EntityAlreadyExistsError,
    EntityNotFoundError,
    ValidationError,
)
from app.models.enums import UserRole
from app.models.membership import OrganizationMembership
from app.schemas.service import ServiceCreate, ServiceRead, ServiceUpdate
from app.services.service_service import ServiceService

router = APIRouter(prefix="/services", tags=["Services"])


@router.get("", response_model=list[ServiceRead])
async def list_services(
    membership: Annotated[OrganizationMembership, Depends(get_current_membership)],
    session: Annotated[AsyncSession, Depends(get_db)],
    active_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[ServiceRead]:
    """List service catalog offerings for the active organization."""
    svc_service = ServiceService(session, membership.organization_id)
    services = await svc_service.list_services(
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    return [ServiceRead.model_validate(s) for s in services]


@router.get("/{service_id}", response_model=ServiceRead)
async def get_service(
    service_id: uuid.UUID,
    membership: Annotated[OrganizationMembership, Depends(get_current_membership)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ServiceRead:
    """Retrieve service offering details."""
    svc_service = ServiceService(session, membership.organization_id)
    try:
        service = await svc_service.get_service(service_id)
        return ServiceRead.model_validate(service)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("", response_model=ServiceRead, status_code=status.HTTP_201_CREATED)
async def create_service(
    data: ServiceCreate,
    membership: Annotated[
        OrganizationMembership,
        Depends(require_role([UserRole.OWNER, UserRole.ADMIN])),
    ],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ServiceRead:
    """Create a new service catalog offering (Owner or Admin)."""
    if data.organization_id != membership.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="organization_id in payload must match active organization context.",
        )

    svc_service = ServiceService(session, membership.organization_id)
    try:
        service = await svc_service.create_service(data)
        await session.commit()
        await session.refresh(service)
        return ServiceRead.model_validate(service)
    except EntityAlreadyExistsError as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValidationError as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/{service_id}", response_model=ServiceRead)
async def update_service(
    service_id: uuid.UUID,
    data: ServiceUpdate,
    membership: Annotated[
        OrganizationMembership,
        Depends(require_role([UserRole.OWNER, UserRole.ADMIN])),
    ],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ServiceRead:
    """Update service catalog offering (Owner or Admin)."""
    svc_service = ServiceService(session, membership.organization_id)
    try:
        service = await svc_service.update_service(service_id, data)
        await session.commit()
        await session.refresh(service)
        return ServiceRead.model_validate(service)
    except EntityNotFoundError as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except (ValidationError, EntityAlreadyExistsError) as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
