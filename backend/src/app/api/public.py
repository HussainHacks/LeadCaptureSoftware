"""Public unauthenticated lead capture endpoint for contractor website embeds."""

import hmac
import re
import time
import uuid
from collections import defaultdict, deque
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import InvalidOperationError, ValidationError
from app.core.redis import redis_client
from app.models.conversation import Conversation
from app.models.enums import (
    ChannelType,
    ConsentStatus,
    ConversationStatus,
    LeadSource,
    LeadUrgency,
)
from app.models.organization import Organization
from app.schemas.conversation import ConversationCreate
from app.schemas.lead import LeadCreate
from app.services.consent_service import ConsentService
from app.services.conversation_service import ConversationService
from app.services.lead_service import LeadService
from app.services.outbox_service import OutboxService
from app.services.qualification_service import QualificationService

router = APIRouter(prefix="/public", tags=["Public Lead Capture"])

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

RATE_LIMIT_MAX_REQUESTS = 10
RATE_LIMIT_WINDOW_SECONDS = 60

# In-memory fallback rate limiter when Redis is unavailable (e.g., unit tests)
_LOCAL_RATE_LIMIT_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


def sanitize_text(value: str | None, *, max_length: int) -> str | None:
    """Strip HTML tags, control characters, and excess whitespace from user input."""
    if value is None:
        return None
    cleaned = _HTML_TAG_RE.sub("", value)
    cleaned = _CONTROL_CHAR_RE.sub("", cleaned)
    cleaned = " ".join(cleaned.split()).strip()
    if not cleaned:
        return None
    return cleaned[:max_length]


async def check_rate_limit(key: str) -> None:
    """Enforce sliding-window rate limit using Redis with an in-memory fallback."""
    redis_key = f"public_lead_rl:{key}"
    try:
        count = await redis_client.incr(redis_key)
        if count == 1:
            await redis_client.expire(redis_key, RATE_LIMIT_WINDOW_SECONDS)
        if count > RATE_LIMIT_MAX_REQUESTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please try again later.",
            )
        return
    except HTTPException:
        raise
    except Exception:
        # Fall back to in-memory sliding window when Redis is unavailable
        now = time.monotonic()
        bucket = _LOCAL_RATE_LIMIT_BUCKETS[key]
        while bucket and now - bucket[0] > RATE_LIMIT_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT_MAX_REQUESTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please try again later.",
            )
        bucket.append(now)


async def resolve_organization_by_site_key(
    session: AsyncSession,
    site_key: str,
) -> Organization | None:
    """Resolve an active organization matching the provided site_key / api_key."""
    stmt = select(Organization).where(Organization.is_active.is_(True))
    res = await session.execute(stmt)
    orgs = res.scalars().all()
    for org in orgs:
        settings_dict = org.settings or {}
        for candidate_field in ("site_key", "api_key"):
            stored = settings_dict.get(candidate_field)
            if isinstance(stored, str) and stored and hmac.compare_digest(stored, site_key):
                return org
    return None


class PublicLeadCaptureRequest(BaseModel):
    """Payload accepted from an embedded HVAC contractor website lead form."""

    name: str = Field(..., min_length=1, max_length=160)
    phone: str = Field(..., min_length=7, max_length=30)
    email: str | None = Field(default=None, max_length=255)
    service_needed: str | None = Field(default=None, max_length=80)
    message: str | None = Field(default=None, max_length=4000)
    consent: bool = Field(default=False)
    source_page: str | None = Field(default=None, max_length=500)
    postal_code: str | None = Field(default=None, max_length=20)
    street_address: str | None = Field(default=None, max_length=255)
    site_key: str | None = Field(default=None, max_length=128)
    # Honeypot spam trap field (must remain empty for legitimate submissions)
    website: str | None = Field(default=None, max_length=255)


class PublicLeadCaptureResponse(BaseModel):
    """Public response returned to the embedded website widget."""

    status: str
    lead_id: uuid.UUID | None = None
    message: str


@router.post(
    "/leads",
    response_model=PublicLeadCaptureResponse,
    status_code=status.HTTP_201_CREATED,
)
async def capture_public_lead(
    payload: PublicLeadCaptureRequest,
    request: Request,
    x_site_key: str | None = Header(default=None, alias="X-Site-Key"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    session: AsyncSession = Depends(get_db),
) -> PublicLeadCaptureResponse:
    """Capture an inbound lead from a contractor website embed using a site/API key."""
    # 1. Honeypot spam check (silently drop bot submissions)
    if payload.website and payload.website.strip():
        return PublicLeadCaptureResponse(
            status="accepted",
            lead_id=None,
            message="Thank you. Your inquiry has been received.",
        )

    # 2. Resolve site/API key
    provided_key = (x_site_key or x_api_key or payload.site_key or "").strip()
    if not provided_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing site key or API key.",
        )

    # 3. Rate limit per client IP + site key prefix
    client_ip = request.client.host if request.client else "unknown"
    await check_rate_limit(f"{client_ip}:{provided_key[:16]}")

    # 4. Resolve tenant organization
    org = await resolve_organization_by_site_key(session, provided_key)
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid site key or inactive organization.",
        )

    # 5. Sanitize inputs
    clean_name = sanitize_text(payload.name, max_length=160)
    if not clean_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A valid name is required.",
        )
    name_parts = clean_name.split(" ", 1)
    first_name = name_parts[0][:80]
    last_name = name_parts[1][:80] if len(name_parts) > 1 else None

    clean_service = sanitize_text(payload.service_needed, max_length=80)
    clean_message = sanitize_text(payload.message, max_length=4000)
    clean_source_page = sanitize_text(payload.source_page, max_length=500)
    clean_postal = sanitize_text(payload.postal_code, max_length=20)
    clean_address = sanitize_text(payload.street_address, max_length=255)
    clean_email = sanitize_text(payload.email, max_length=255)

    # 6. Run existing lead intake flow (Lead -> Consent -> Conversation -> Qualification -> Outbox)
    lead_service = LeadService(session, org.id)
    consent_service = ConsentService(session, org.id)
    conv_service = ConversationService(session, org.id)
    qual_service = QualificationService(session, org.id)
    outbox_service = OutboxService(session, org.id)

    sms_consent = ConsentStatus.OPTED_IN if payload.consent else ConsentStatus.OPTED_OUT
    metadata: dict[str, Any] = {"intake": "public_web_embed"}
    if clean_source_page:
        metadata["source_page"] = clean_source_page

    try:
        lead = await lead_service.create_lead(
            LeadCreate(
                organization_id=org.id,
                first_name=first_name,
                last_name=last_name,
                phone=payload.phone,
                email=clean_email,
                postal_code=clean_postal,
                street_address=clean_address,
                service_type=clean_service,
                problem_description=clean_message,
                urgency=LeadUrgency.MEDIUM,
                source=LeadSource.WEBSITE_FORM,
                sms_consent_status=sms_consent,
                email_consent_status=ConsentStatus.PENDING,
                metadata=metadata,
            )
        )

        consent_source = f"WEB_EMBED:{clean_source_page}"[:50] if clean_source_page else "WEB_EMBED"
        await consent_service.record_consent(
            lead.id,
            ChannelType.SMS,
            consent_source=consent_source,
            consent_status=sms_consent,
            consent_text_snapshot=(
                f"Public web form consent={payload.consent} page={clean_source_page or 'unknown'}"
            ),
            ip_address=client_ip,
        )

        stmt_conv = select(Conversation).where(
            Conversation.organization_id == org.id,
            Conversation.lead_id == lead.id,
        )
        conv = (await session.execute(stmt_conv)).scalar_one_or_none()
        if not conv:
            await conv_service.create_conversation(
                ConversationCreate(
                    organization_id=org.id,
                    lead_id=lead.id,
                    channel=ChannelType.SMS,
                    status=ConversationStatus.AI_ACTIVE,
                )
            )

        qual = await qual_service.evaluate_lead(lead.id)

        await outbox_service.publish_event(
            organization_id=org.id,
            event_type="LEAD_CREATED",
            aggregate_id=lead.id,
            aggregate_type="Lead",
            payload={
                "lead_id": str(lead.id),
                "urgency": lead.urgency,
                "qualification_category": qual.category,
                "source": lead.source,
                "source_page": clean_source_page,
            },
        )

        await session.commit()
    except (ValidationError, InvalidOperationError) as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return PublicLeadCaptureResponse(
        status="received",
        lead_id=lead.id,
        message="Thank you. Your inquiry has been received.",
    )
