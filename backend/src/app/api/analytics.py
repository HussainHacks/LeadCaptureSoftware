"""FastAPI routes for HVAC lead conversion analytics and qualification distributions."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_membership
from app.core.database import get_db
from app.models.lead import Lead
from app.models.membership import OrganizationMembership
from app.models.qualification import QualificationResult

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("", response_model=dict[str, Any])
async def get_analytics_data(
    membership: Annotated[OrganizationMembership, Depends(get_current_membership)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Retrieve conversion analytics, qualification distributions, and urgency breakdown."""
    org_id = membership.organization_id

    # 1. Lead Funnel Breakdown by status
    status_counts_stmt = (
        select(Lead.status, func.count(Lead.id))
        .where(Lead.organization_id == org_id, Lead.deleted_at.is_(None))
        .group_by(Lead.status)
    )
    status_rows = (await session.execute(status_counts_stmt)).all()
    funnel = {status: count for status, count in status_rows}

    # 2. Urgency Breakdown
    urgency_counts_stmt = (
        select(Lead.urgency, func.count(Lead.id))
        .where(Lead.organization_id == org_id, Lead.deleted_at.is_(None))
        .group_by(Lead.urgency)
    )
    urgency_rows = (await session.execute(urgency_counts_stmt)).all()
    urgency_breakdown = {urgency: count for urgency, count in urgency_rows}

    # 3. Qualification Categories
    qual_counts_stmt = (
        select(QualificationResult.category, func.count(QualificationResult.id))
        .where(QualificationResult.organization_id == org_id)
        .group_by(QualificationResult.category)
    )
    qual_rows = (await session.execute(qual_counts_stmt)).all()
    qualification_breakdown = {cat: count for cat, count in qual_rows}

    # 4. Service Type Breakdown
    service_counts_stmt = (
        select(Lead.service_type, func.count(Lead.id))
        .where(Lead.organization_id == org_id, Lead.deleted_at.is_(None))
        .group_by(Lead.service_type)
    )
    service_rows = (await session.execute(service_counts_stmt)).all()
    service_breakdown = {svc: count for svc, count in service_rows if svc}

    return {
        "funnel": funnel,
        "urgency_breakdown": urgency_breakdown,
        "qualification_breakdown": qualification_breakdown,
        "service_breakdown": service_breakdown,
    }
