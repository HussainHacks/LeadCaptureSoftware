"""Authentication and user session API endpoints."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import bearer_scheme, get_current_membership, get_current_user, get_db
from app.core.exceptions import EntityAlreadyExistsError, ValidationError
from app.core.security import create_access_token, decode_access_token, revoke_access_token
from app.models.enums import UserRole
from app.models.membership import OrganizationMembership
from app.models.organization import Organization
from app.models.user import User
from app.schemas.organization import OrganizationCreate, OrganizationRead
from app.schemas.user import UserCreate, UserRead
from app.services.organization_service import OrganizationService
from app.services.user_service import UserService

router = APIRouter(prefix="/auth", tags=["Authentication"])


class RegisterRequest(BaseModel):
    """Payload for registering a user and their initial organization."""

    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    first_name: str = Field(..., max_length=80)
    last_name: str = Field(..., max_length=80)
    phone: str | None = Field(default=None, max_length=30)
    organization_name: str = Field(..., max_length=150)
    organization_slug: str = Field(..., max_length=60)
    timezone: str = Field(default="America/New_York", max_length=50)


class LoginRequest(BaseModel):
    """Payload for logging into an existing account."""

    email: str
    password: str


class OrganizationBrief(BaseModel):
    """Brief organization metadata returned in auth responses."""

    id: uuid.UUID
    name: str
    slug: str
    role: str
    timezone: str


class AuthResponse(BaseModel):
    """Token and identity payload returned on registration and login."""

    access_token: str
    token_type: str = "bearer"
    user: UserRead
    active_organization_id: uuid.UUID
    organizations: list[OrganizationBrief]


class CurrentUserResponse(BaseModel):
    """User profile with associated organizations and active membership."""

    user: UserRead
    active_organization: OrganizationRead | None = None
    role: str | None = None
    organizations: list[OrganizationBrief]


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(
    req: RegisterRequest,
    session: AsyncSession = Depends(get_db),
) -> Any:
    """Register a new contractor owner and initialize their primary organization."""
    user_service = UserService(session)
    org_service = OrganizationService(session)

    try:
        # 1. Register user
        user = await user_service.register_user(
            UserCreate(
                email=req.email,
                password=req.password,
                first_name=req.first_name,
                last_name=req.last_name,
                phone=req.phone,
            )
        )

        # 2. Create organization and assign creator as OWNER
        org, membership = await org_service.create_organization(
            creator_user_id=user.id,
            data=OrganizationCreate(
                name=req.organization_name,
                slug=req.organization_slug,
                timezone=req.timezone,
            ),
        )

        # 3. Commit user and organization atomically
        await session.commit()
    except (EntityAlreadyExistsError, ValidationError) as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {e}",
        )

    # 4. Issue token
    token = create_access_token({"sub": str(user.id), "org_id": str(org.id)})

    org_brief = OrganizationBrief(
        id=org.id,
        name=org.name,
        slug=org.slug,
        role=membership.role,
        timezone=org.timezone,
    )

    return AuthResponse(
        access_token=token,
        token_type="bearer",
        user=user_service.to_read_schema(user),
        active_organization_id=org.id,
        organizations=[org_brief],
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    req: LoginRequest,
    session: AsyncSession = Depends(get_db),
) -> Any:
    """Authenticate with email and password and return access token with org context."""
    user_service = UserService(session)
    user = await user_service.authenticate_user(req.email, req.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Fetch active memberships and organizations
    stmt = (
        select(OrganizationMembership, Organization)
        .join(Organization, Organization.id == OrganizationMembership.organization_id)
        .where(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.is_active.is_(True),
            Organization.is_active.is_(True),
        )
    )
    res = await session.execute(stmt)
    records = res.all()

    if not records:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account has no active organizations.",
        )

    orgs_list: list[OrganizationBrief] = []
    primary_org_id = records[0][1].id

    for membership, org in records:
        if membership.role in (UserRole.OWNER.value, UserRole.ADMIN.value):
            primary_org_id = org.id
        orgs_list.append(
            OrganizationBrief(
                id=org.id,
                name=org.name,
                slug=org.slug,
                role=membership.role,
                timezone=org.timezone,
            )
        )

    token = create_access_token({"sub": str(user.id), "org_id": str(primary_org_id)})

    return AuthResponse(
        access_token=token,
        token_type="bearer",
        user=user_service.to_read_schema(user),
        active_organization_id=primary_org_id,
        organizations=orgs_list,
    )


@router.post("/logout")
async def logout(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Revoke current access token and acknowledge client session termination."""
    if cred and cred.credentials:
        payload = decode_access_token(cred.credentials)
        if payload:
            await revoke_access_token(payload)
    return {"message": "Logged out successfully."}


@router.get("/me", response_model=CurrentUserResponse)
async def get_current_user_profile(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Any:
    """Return the profile, roles, and organizations of the authenticated user."""
    stmt = (
        select(OrganizationMembership, Organization)
        .join(Organization, Organization.id == OrganizationMembership.organization_id)
        .where(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.is_active.is_(True),
            Organization.is_active.is_(True),
        )
    )
    res = await session.execute(stmt)
    records = res.all()

    orgs_list: list[OrganizationBrief] = []
    active_org: Organization | None = None
    active_role: str | None = None

    if records:
        active_org = records[0][1]
        active_role = records[0][0].role
        for membership, org in records:
            if membership.role in (UserRole.OWNER.value, UserRole.ADMIN.value):
                active_org = org
                active_role = membership.role
            orgs_list.append(
                OrganizationBrief(
                    id=org.id,
                    name=org.name,
                    slug=org.slug,
                    role=membership.role,
                    timezone=org.timezone,
                )
            )

    return CurrentUserResponse(
        user=UserRead.model_validate(user),
        active_organization=OrganizationRead.model_validate(active_org) if active_org else None,
        role=active_role,
        organizations=orgs_list,
    )


@router.get("/current-organization", response_model=OrganizationRead)
async def get_active_organization(
    membership: OrganizationMembership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_db),
) -> Any:
    """Return the active tenant organization derived from verified membership."""
    stmt = select(Organization).where(Organization.id == membership.organization_id)
    res = await session.execute(stmt)
    org = res.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return OrganizationRead.model_validate(org)
