"""Pydantic schemas for CustomerConsent entity."""

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import ORMBase
from app.schemas.enums import ChannelType, ConsentStatus


class CustomerConsentCreate(ORMBase):
    """Schema for recording customer communication consent."""

    organization_id: uuid.UUID
    lead_id: uuid.UUID
    channel: ChannelType = ChannelType.SMS
    consent_status: ConsentStatus = ConsentStatus.OPTED_IN
    consent_source: str = Field(..., max_length=50)
    consent_text_snapshot: str | None = None
    ip_address: str | None = Field(default=None, max_length=45)
    opt_out_keyword: str | None = Field(default=None, max_length=30)


class CustomerConsentRead(ORMBase):
    """Schema for reading consent audit record."""

    id: uuid.UUID
    organization_id: uuid.UUID
    lead_id: uuid.UUID
    channel: ChannelType
    consent_status: ConsentStatus
    consent_source: str
    consent_text_snapshot: str | None
    ip_address: str | None
    consent_timestamp: datetime
    opt_out_timestamp: datetime | None
    opt_out_keyword: str | None
    created_at: datetime
