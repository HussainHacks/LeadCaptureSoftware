"""FastAPI routes for transactional outbox monitoring, status counts, and batch processing."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_membership, require_role
from app.core.database import get_db
from app.models.enums import UserRole
from app.models.membership import OrganizationMembership
from app.models.outbox import AutomationEvent
from app.services.outbox_service import OutboxService

router = APIRouter(prefix="/outbox", tags=["Outbox"])


@router.get("/status", response_model=dict[str, Any])
async def get_outbox_status(
    membership: Annotated[OrganizationMembership, Depends(get_current_membership)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Retrieve outbox queue status counts for the active organization."""
    org_id = membership.organization_id

    stmt = (
        select(AutomationEvent.processing_status, func.count(AutomationEvent.id))
        .where(AutomationEvent.organization_id == org_id)
        .group_by(AutomationEvent.processing_status)
    )
    rows = (await session.execute(stmt)).all()
    counts = {status: count for status, count in rows}

    return {
        "status_counts": {
            "PENDING": counts.get("PENDING", 0),
            "PROCESSING": counts.get("PROCESSING", 0),
            "DELIVERED": counts.get("DELIVERED", 0),
            "FAILED": counts.get("FAILED", 0),
            "DEAD_LETTER": counts.get("DEAD_LETTER", 0),
        },
        "total": sum(counts.values()),
    }


@router.get("/events", response_model=list[dict[str, Any]])
async def list_outbox_events(
    membership: Annotated[OrganizationMembership, Depends(get_current_membership)],
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, Any]]:
    """List recent outbox events with delivery statuses and attempt counts."""
    org_id = membership.organization_id

    stmt = (
        select(AutomationEvent)
        .where(AutomationEvent.organization_id == org_id)
        .order_by(AutomationEvent.created_at.desc())
        .limit(limit)
    )
    events = (await session.execute(stmt)).scalars().all()

    return [
        {
            "id": str(e.id),
            "event_type": e.event_type,
            "processing_status": e.processing_status,
            "retry_count": e.retry_count,
            "attempt_count": e.attempt_count,
            "idempotency_key": e.idempotency_key,
            "last_error": e.last_error,
            "created_at": e.created_at.isoformat(),
            "processed_at": e.processed_at.isoformat() if e.processed_at else None,
        }
        for e in events
    ]


@router.post("/sweep", response_model=dict[str, Any])
async def trigger_outbox_sweep(
    membership: Annotated[
        OrganizationMembership,
        Depends(require_role([UserRole.OWNER, UserRole.ADMIN])),
    ],
    session: Annotated[AsyncSession, Depends(get_db)],
    batch_size: int = Query(default=10, ge=1, le=50),
) -> dict[str, Any]:
    """Execute outbox processing batch (expired lease recovery, claim, and simulated dispatch)."""
    outbox_service = OutboxService(session, membership.organization_id)
    recovered_count = await outbox_service.recover_expired_leases()
    processed_count = await outbox_service.process_next_batch(batch_size=batch_size)

    return {
        "status": "success",
        "recovered_leases": recovered_count,
        "processed_events": processed_count,
    }
