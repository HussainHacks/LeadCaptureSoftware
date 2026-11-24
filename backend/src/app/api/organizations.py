"""Organization and team membership management API endpoints."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_membership,
    get_current_user,
    get_db,
    require_role,
)
from app.core.exceptions import EntityAlreadyExistsError, EntityNotFoundError, ValidationError
from app.models.enums import UserRole
from app.models.membership import OrganizationMembership
from app.models.organization import Organization
from app.models.user import User
from app.schemas.organization import OrganizationRead, OrganizationUpdate
from app.services.membership_service import MembershipService
from app.services.organization_service import OrganizationService
from app.services.user_service import UserService

router = APIRouter(prefix="/organizations", tags=["Organizations"])


class MemberRead(BaseModel):
    """Schema for displaying team member details."""

    membership_id: uuid.UUID
    user_id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    phone: str | None
    role: str
    is_active: bool


class AddMemberRequest(BaseModel):
    """Payload for inviting/adding a user to the organization."""

    email: str = Field(..., max_length=255)
    first_name: str = Field(..., max_length=80)
    last_name: str = Field(..., max_length=80)
    role: UserRole = Field(default=UserRole.DISPATCHER)
    password: str = Field(default="ChangeMe123!", min_length=8, max_length=128)


class UpdateMemberRequest(BaseModel):
    """Payload for changing role or status of an existing member."""

    role: UserRole | None = None
    is_active: bool | None = None


@router.get("", response_model=list[OrganizationRead])
async def list_user_organizations(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Any:
    """List all active organizations that the authenticated user belongs to."""
    stmt = (
        select(Organization)
        .join(OrganizationMembership, Organization.id == OrganizationMembership.organization_id)
        .where(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.is_active.is_(True),
            Organization.is_active.is_(True),
        )
    )
    res = await session.execute(stmt)
    orgs = res.scalars().all()
    return [OrganizationRead.model_validate(org) for org in orgs]


@router.get("/{org_id}", response_model=OrganizationRead)
async def get_organization(
    org_id: uuid.UUID,
    membership: OrganizationMembership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_db),
) -> Any:
    """Retrieve details for the organization verified by tenancy."""
    if membership.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this organization.",
        )
    org_service = OrganizationService(session)
    org = await org_service.get_organization_by_id(org_id)
    return OrganizationRead.model_validate(org)


@router.put("/{org_id}", response_model=OrganizationRead)
async def update_organization(
    org_id: uuid.UUID,
    payload: OrganizationUpdate,
    membership: OrganizationMembership = Depends(require_role([UserRole.OWNER, UserRole.ADMIN])),
    session: AsyncSession = Depends(get_db),
) -> Any:
    """Update organization details, operating hours, and automation settings."""
    if membership.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot update an organization other than your active organization.",
        )

    org_service = OrganizationService(session)
    try:
        updated_org = await org_service.update_organization(
            org_id,
            name=payload.name,
            industry=payload.industry,
            timezone=payload.timezone,
            dispatch_phone=payload.dispatch_phone,
            utility_emergency_phone=payload.utility_emergency_phone,
            default_slot_capacity=payload.default_slot_capacity,
            settings=payload.settings,
        )
        await session.commit()
        return OrganizationRead.model_validate(updated_org)
    except (ValidationError, EntityNotFoundError) as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{org_id}/members", response_model=list[MemberRead])
async def list_members(
    org_id: uuid.UUID,
    membership: OrganizationMembership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_db),
) -> Any:
    """List all team members and their roles within the organization."""
    if membership.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to requested organization members.",
        )

    stmt = (
        select(OrganizationMembership, User)
        .join(User, OrganizationMembership.user_id == User.id)
        .where(OrganizationMembership.organization_id == org_id)
        .order_by(OrganizationMembership.created_at.asc())
    )
    res = await session.execute(stmt)
    records = res.all()

    members: list[MemberRead] = []
    for mem, usr in records:
        members.append(
            MemberRead(
                membership_id=mem.id,
                user_id=usr.id,
                email=usr.email,
                first_name=usr.first_name,
                last_name=usr.last_name,
                phone=usr.phone,
                role=mem.role,
                is_active=mem.is_active,
            )
        )
    return members


@router.post("/{org_id}/members", response_model=MemberRead, status_code=status.HTTP_201_CREATED)
async def add_member(
    org_id: uuid.UUID,
    payload: AddMemberRequest,
    membership: OrganizationMembership = Depends(require_role([UserRole.OWNER, UserRole.ADMIN])),
    session: AsyncSession = Depends(get_db),
) -> Any:
    """Add a new or existing user to the organization with a specified role."""
    if membership.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot add members to an organization outside your active context.",
        )

    user_service = UserService(session)
    mem_service = MembershipService(session, org_id)

    # Check if user already exists globally
    user = await user_service.get_user_by_email(payload.email)
    if not user:
        from app.schemas.user import UserCreate

        user = await user_service.register_user(
            UserCreate(
                email=payload.email,
                password=payload.password,
                first_name=payload.first_name,
                last_name=payload.last_name,
            )
        )

    try:
        new_membership = await mem_service.add_member(user.id, role=payload.role)
        await session.commit()
    except EntityAlreadyExistsError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already a member of this organization.",
        )
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return MemberRead(
        membership_id=new_membership.id,
        user_id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        phone=user.phone,
        role=new_membership.role,
        is_active=new_membership.is_active,
    )
