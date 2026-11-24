"""FastAPI request dependencies for authentication, tenancy, and authorization."""

import uuid
from collections.abc import Callable

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_context import ActorContext
from app.core.database import get_db
from app.core.security import decode_access_token, is_token_revoked
from app.models.enums import UserRole
from app.models.membership import OrganizationMembership
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> User:
    """Validate JWT access token and return the authenticated User."""
    if not cred or not cred.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(cred.credentials)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if await is_token_revoked(payload):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token has been revoked.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = uuid.UUID(payload["sub"])
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed user token identity.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    stmt = select(User).where(User.id == user_id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account does not exist or has been deactivated.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_current_membership(
    user: User = Depends(get_current_user),
    x_organization_id: str | None = Header(None, alias="X-Organization-ID"),
    session: AsyncSession = Depends(get_db),
) -> OrganizationMembership:
    """Resolve and validate active organization tenancy for the authenticated user."""
    stmt = select(OrganizationMembership).where(
        OrganizationMembership.user_id == user.id,
        OrganizationMembership.is_active.is_(True),
    )

    if x_organization_id:
        try:
            target_org_id = uuid.UUID(x_organization_id)
            stmt = stmt.where(OrganizationMembership.organization_id == target_org_id)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-Organization-ID header format; expected a valid UUID.",
            )

    res = await session.execute(stmt)
    memberships = res.scalars().all()

    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have an active membership in the requested organization.",
        )

    # Prefer owner or admin role if multiple memberships exist and none was explicitly requested
    if len(memberships) > 1 and not x_organization_id:
        for m in memberships:
            if m.role in (UserRole.OWNER.value, UserRole.ADMIN.value):
                return m

    return memberships[0]


def require_role(
    allowed_roles: list[UserRole] | list[str],
) -> Callable[..., OrganizationMembership]:
    """Dependency factory checking that active organization role matches allowed permissions."""
    role_values = {r.value if isinstance(r, UserRole) else str(r) for r in allowed_roles}

    async def _role_checker(
        membership: OrganizationMembership = Depends(get_current_membership),
    ) -> OrganizationMembership:
        if membership.role not in role_values:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Insufficient permissions: role '{membership.role}' is not authorized. "
                    f"Required one of: {sorted(role_values)}"
                ),
            )
        return membership

    return _role_checker


async def get_actor_context(
    membership: OrganizationMembership = Depends(get_current_membership),
) -> ActorContext:
    """Build ActorContext from verified cryptographic credentials and active membership."""
    return ActorContext(
        user_id=membership.user_id,
        organization_id=membership.organization_id,
    )
