"""Tenant-scoped OutboxService managing claiming, dispatching, settlement, and lease recovery."""

import hashlib
import json
import logging
import random
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import EventDispatcher, SimulatedEventDispatcher
from app.core.exceptions import (
    EntityAlreadyExistsError,
    EntityNotFoundError,
    PermanentDispatchError,
    RetryableDispatchError,
    StaleLeaseError,
)
from app.models.enums import OutboxStatus
from app.models.outbox import AutomationEvent
from app.repositories.entities import AuditLogRepository, AutomationEventRepository
from app.services.base import BaseService

logger = logging.getLogger(__name__)

DEFAULT_LEASE_DURATION_SECONDS = 300  # 5 minutes
DEFAULT_INITIAL_INTERVAL_SECONDS = 30  # 30 seconds initial backoff
DEFAULT_MAX_INTERVAL_SECONDS = 3600  # 1 hour max backoff
DEFAULT_MAX_RETRIES = 5  # Permits 1 initial attempt + 5 retries = 6 total attempts


def compute_deterministic_idempotency_key(event_type: str, logical_key: str) -> str:
    """Generate a bounded deterministic idempotency key (< 95 chars)."""
    hashed = hashlib.sha256(logical_key.encode("utf-8")).hexdigest()
    return f"{event_type}:{hashed}"


def calculate_exponential_backoff(
    retry_count: int,
    initial_interval: int = DEFAULT_INITIAL_INTERVAL_SECONDS,
    max_interval: int = DEFAULT_MAX_INTERVAL_SECONDS,
    jitter: bool = True,
) -> int:
    """Calculate exponential backoff in seconds for a given retry attempt."""
    factor = 2 ** max(0, retry_count - 1)
    base_backoff = min(max_interval, initial_interval * factor)
    if jitter:
        jitter_range = int(base_backoff * 0.1)
        if jitter_range > 0:
            base_backoff += random.randint(-jitter_range, jitter_range)
    return max(1, base_backoff)


class OutboxService(BaseService):
    """Service orchestrating event claiming, dispatching, settlement, and recovery."""

    def __init__(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID | None = None,
        dispatcher: EventDispatcher | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        lease_duration_seconds: int = DEFAULT_LEASE_DURATION_SECONDS,
    ) -> None:
        super().__init__(session)
        self.organization_id = organization_id
        self.dispatcher = dispatcher or SimulatedEventDispatcher()
        self.outbox_repo = AutomationEventRepository(session)
        self.audit_repo = AuditLogRepository(session)
        self.max_retries = max_retries
        self.lease_duration_seconds = lease_duration_seconds

    async def publish_event(
        self,
        event_type: str,
        payload: dict,
        *,
        organization_id: uuid.UUID | None = None,
        aggregate_id: uuid.UUID | None = None,
        aggregate_type: str | None = None,
        idempotency_key: str | None = None,
    ) -> AutomationEvent:
        """Persist a new outbox event within the caller's active database transaction.

        Flushes to evaluate constraints without committing the transaction.
        """
        org_id = organization_id or self.organization_id
        if org_id is None:
            raise ValueError(
                "organization_id must be provided to publish_event or in OutboxService.__init__"
            )

        if idempotency_key is None:
            if aggregate_id is not None and aggregate_type is not None:
                idempotency_key = f"{org_id}:{aggregate_type}:{aggregate_id}:{event_type}"
            else:
                raw_payload = json.dumps(payload, sort_keys=True)
                idempotency_key = compute_deterministic_idempotency_key(
                    event_type, f"{org_id}:{raw_payload}"
                )

        existing = await self.outbox_repo.get_by_idempotency_key(org_id, idempotency_key)
        if existing is not None:
            raise EntityAlreadyExistsError("AutomationEvent", "idempotency_key", idempotency_key)

        event = AutomationEvent(
            organization_id=org_id,
            event_type=event_type,
            payload=payload,
            idempotency_key=idempotency_key,
            processing_status=OutboxStatus.PENDING.value,
            retry_count=0,
            attempt_count=0,
            max_retries=self.max_retries,
            lease_token=None,
            lease_expires_at=None,
            next_retry_at=None,
            last_error=None,
        )
        return await self.outbox_repo.add(org_id, event)

    async def claim_batch(
        self,
        batch_size: int = 10,
        worker_id: str | None = None,
        lease_duration_seconds: int | None = None,
        now_utc: datetime | None = None,
    ) -> list[AutomationEvent]:
        """Claim a batch of eligible events using SELECT FOR UPDATE SKIP LOCKED (Session 1).

        Assigns unique lease token, sets expiration, increments attempt_count, and commits.
        """
        now = now_utc or datetime.now(UTC)
        duration = lease_duration_seconds or self.lease_duration_seconds

        stmt = select(AutomationEvent).where(
            AutomationEvent.processing_status.in_(
                [
                    OutboxStatus.PENDING.value,
                    OutboxStatus.FAILED.value,
                ]
            ),
            or_(
                AutomationEvent.next_retry_at.is_(None),
                AutomationEvent.next_retry_at <= now,
            ),
        )

        if self.organization_id is not None:
            stmt = stmt.where(AutomationEvent.organization_id == self.organization_id)

        stmt = (
            stmt.order_by(
                AutomationEvent.processing_status.asc(),
                AutomationEvent.next_retry_at.asc().nulls_first(),
                AutomationEvent.created_at.asc(),
            )
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )

        res = await self.session.execute(stmt)
        events = list(res.scalars().all())

        for event in events:
            token = uuid.uuid4().hex + uuid.uuid4().hex  # 64-char hex lease token
            event.processing_status = OutboxStatus.PROCESSING.value
            event.attempt_count += 1
            event.lease_token = token
            event.lease_expires_at = now + timedelta(seconds=duration)

        if events:
            await self.session.commit()

        return events

    async def settle_event(
        self,
        event_id: uuid.UUID,
        lease_token: str,
        *,
        status: OutboxStatus | str | None = None,
        success: bool = True,
        error_detail: str | None = None,
        error_message: str | None = None,
        is_retryable: bool = False,
        retryable: bool = False,
        now_utc: datetime | None = None,
    ) -> AutomationEvent:
        """Settle a processed event inside a short-lived transaction (Session 2).

        Verifies the lease_token matches before committing state changes (fencing).
        """
        now = now_utc or datetime.now(UTC)
        err_msg = error_detail or error_message
        is_ret = is_retryable or retryable

        # Determine success from status or bool
        if status is not None:
            status_val = status.value if hasattr(status, "value") else str(status)
            is_success = status_val == OutboxStatus.DELIVERED.value
        else:
            is_success = success

        # 1. Fetch event with row lock to check lease token
        stmt = select(AutomationEvent).where(AutomationEvent.id == event_id).with_for_update()
        res = await self.session.execute(stmt)
        event = res.scalar_one_or_none()

        if event is None:
            raise EntityNotFoundError("AutomationEvent", event_id)

        # 2. Verify lease token matches (Fencing protection against stale workers)
        if event.lease_token != lease_token:
            logger.warning(
                "Stale worker lease rejected for event %s. Expected token %s, received %s",
                event_id,
                event.lease_token,
                lease_token,
            )
            raise StaleLeaseError(
                f"Outbox lease for event {event_id} has expired or been reassigned.",
                event_id=str(event_id),
            )

        # 3. Apply state transition
        if is_success:
            event.processing_status = OutboxStatus.DELIVERED.value
            event.processed_at = now
            event.lease_token = None
            event.lease_expires_at = None
            event.last_error = None

            await self.audit_repo.log_system_event(
                event.organization_id,
                action="DISPATCH_SUCCESS",
                resource_type="AutomationEvent",
                resource_id=str(event.id),
                changes={
                    "event_type": event.event_type,
                    "attempt_count": event.attempt_count,
                    "processing_status": OutboxStatus.DELIVERED.value,
                },
            )
        else:
            if is_ret:
                event.retry_count += 1
                if event.retry_count >= event.max_retries:
                    # Retry limit reached -> Dead letter
                    event.processing_status = OutboxStatus.DEAD_LETTER.value
                    event.processed_at = now
                    event.next_retry_at = None
                    event.lease_token = None
                    event.lease_expires_at = None
                    event.last_error = err_msg or "Max retries exceeded"

                    await self.audit_repo.log_system_event(
                        event.organization_id,
                        action="DISPATCH_DEAD_LETTER",
                        resource_type="AutomationEvent",
                        resource_id=str(event.id),
                        changes={
                            "event_type": event.event_type,
                            "retry_count": event.retry_count,
                            "attempt_count": event.attempt_count,
                            "error": err_msg,
                            "final_status": OutboxStatus.DEAD_LETTER.value,
                        },
                    )
                else:
                    # Reschedule retry with exponential backoff
                    event.processing_status = OutboxStatus.FAILED.value
                    backoff = calculate_exponential_backoff(
                        event.retry_count,
                        initial_interval=DEFAULT_INITIAL_INTERVAL_SECONDS,
                        max_interval=DEFAULT_MAX_INTERVAL_SECONDS,
                    )
                    event.next_retry_at = now + timedelta(seconds=backoff)
                    event.lease_token = None
                    event.lease_expires_at = None
                    event.last_error = err_msg
            else:
                # Permanent unretryable failure -> Dead Letter immediately
                event.processing_status = OutboxStatus.DEAD_LETTER.value
                event.processed_at = now
                event.next_retry_at = None
                event.lease_token = None
                event.lease_expires_at = None
                event.last_error = err_msg or "Permanent dispatch error"

                await self.audit_repo.log_system_event(
                    event.organization_id,
                    action="DISPATCH_DEAD_LETTER",
                    resource_type="AutomationEvent",
                    resource_id=str(event.id),
                    changes={
                        "event_type": event.event_type,
                        "retry_count": event.retry_count,
                        "attempt_count": event.attempt_count,
                        "error": err_msg,
                        "permanent": True,
                        "final_status": OutboxStatus.DEAD_LETTER.value,
                    },
                )

        await self.session.commit()
        return event

    async def recover_expired_leases(
        self,
        batch_size: int = 10,
        now_utc: datetime | None = None,
    ) -> int:
        """Sweep expired worker leases matching Index B and reschedule or dead-letter them.

        Returns the number of expired events recovered.
        """
        now = now_utc or datetime.now(UTC)
        stmt = select(AutomationEvent).where(
            AutomationEvent.processing_status == OutboxStatus.PROCESSING.value,
            AutomationEvent.lease_expires_at.is_not(None),
            AutomationEvent.lease_expires_at <= now,
        )

        if self.organization_id is not None:
            stmt = stmt.where(AutomationEvent.organization_id == self.organization_id)

        stmt = (
            stmt.order_by(
                AutomationEvent.lease_expires_at.asc(),
                AutomationEvent.created_at.asc(),
            )
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )

        res = await self.session.execute(stmt)
        expired_events = list(res.scalars().all())

        for event in expired_events:
            event.retry_count += 1
            if event.retry_count >= event.max_retries:
                event.processing_status = OutboxStatus.DEAD_LETTER.value
                event.lease_token = None
                event.lease_expires_at = None
                event.last_error = "Worker lease expired; max retries exceeded"

                await self.audit_repo.log_system_event(
                    event.organization_id,
                    action="DISPATCH_DEAD_LETTER",
                    resource_type="AutomationEvent",
                    resource_id=str(event.id),
                    changes={
                        "event_type": event.event_type,
                        "retry_count": event.retry_count,
                        "attempt_count": event.attempt_count,
                        "reason": "LEASE_EXPIRED_MAX_RETRIES",
                        "final_status": OutboxStatus.DEAD_LETTER.value,
                    },
                )
            else:
                event.processing_status = OutboxStatus.FAILED.value
                backoff = calculate_exponential_backoff(
                    event.retry_count,
                    initial_interval=DEFAULT_INITIAL_INTERVAL_SECONDS,
                    max_interval=DEFAULT_MAX_INTERVAL_SECONDS,
                )
                event.next_retry_at = now + timedelta(seconds=backoff)
                event.lease_token = None
                event.lease_expires_at = None
                event.last_error = "Worker lease expired without settlement"

        if expired_events:
            await self.session.commit()

        return len(expired_events)

    async def process_next_batch(
        self,
        batch_size: int = 10,
        now_utc: datetime | None = None,
    ) -> int:
        """Complete one outbox cycle: recover expired leases, claim batch, and dispatch events.

        Returns total number of events dispatched.
        """
        now = now_utc or datetime.now(UTC)

        # 1. Recover expired leases
        await self.recover_expired_leases(batch_size=batch_size, now_utc=now)

        # 2. Claim next available batch
        claimed_events = await self.claim_batch(batch_size=batch_size, now_utc=now)
        if not claimed_events:
            return 0

        # 3. Dispatch outside open transaction
        processed_count = 0
        for event in claimed_events:
            token = event.lease_token
            if not token:
                continue

            try:
                # Dispatch external operation
                result = await self.dispatcher.dispatch(event)
                if not result.success:
                    if result.retryable:
                        raise RetryableDispatchError(
                            result.error_message or "Retryable dispatch error",
                            status_code=result.status_code,
                            event_id=str(event.id),
                        )
                    else:
                        raise PermanentDispatchError(
                            result.error_message or "Permanent dispatch error",
                            status_code=result.status_code,
                            event_id=str(event.id),
                        )

                await self.settle_event(
                    event.id,
                    token,
                    status=OutboxStatus.DELIVERED,
                    success=True,
                    now_utc=now,
                )
                processed_count += 1
            except RetryableDispatchError as exc:
                logger.warning("Retryable dispatch error for event %s: %s", event.id, exc)
                await self.settle_event(
                    event.id,
                    token,
                    status=OutboxStatus.FAILED,
                    success=False,
                    error_detail=str(exc),
                    is_retryable=True,
                    now_utc=now,
                )
                processed_count += 1
            except (PermanentDispatchError, Exception) as exc:
                logger.error("Permanent dispatch error for event %s: %s", event.id, exc)
                await self.settle_event(
                    event.id,
                    token,
                    status=OutboxStatus.DEAD_LETTER,
                    success=False,
                    error_detail=str(exc),
                    is_retryable=False,
                    now_utc=now,
                )
                processed_count += 1

        return processed_count
