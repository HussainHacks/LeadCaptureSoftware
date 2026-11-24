"""Tenant-scoped service managing customer communication consents and opt-outs."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consent import CustomerConsent
from app.models.enums import ChannelType, ConsentStatus
from app.repositories.entities import ConsentRepository, LeadRepository
from app.services.base import TenantService


class ConsentService(TenantService):
    """Tenant-scoped service for managing explicit channel consents and opt-out history."""

    def __init__(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        consent_repo: ConsentRepository | None = None,
        lead_repo: LeadRepository | None = None,
    ) -> None:
        super().__init__(session, organization_id)
        self.consent_repo = consent_repo or ConsentRepository(session)
        self.lead_repo = lead_repo or LeadRepository(session)

    async def has_active_consent(
        self,
        lead_id: uuid.UUID,
        channel: ChannelType | str,
    ) -> bool:
        """Check whether a lead has an active OPTED_IN consent for the given channel."""
        chan_enum = ChannelType(channel) if isinstance(channel, str) else channel

        lead = await self.lead_repo.get_by_id(self.organization_id, lead_id)
        if lead is None:
            return False

        if chan_enum == ChannelType.SMS:
            if lead.sms_consent_status != ConsentStatus.OPTED_IN.value:
                return False
        elif chan_enum == ChannelType.EMAIL:
            if lead.email_consent_status != ConsentStatus.OPTED_IN.value:
                return False

        record = await self.consent_repo.get_latest_consent(
            self.organization_id,
            lead_id,
            channel,
        )
        if record is None:
            return False
        return record.consent_status == ConsentStatus.OPTED_IN.value

    async def record_consent(
        self,
        lead_id: uuid.UUID,
        channel: ChannelType | str,
        consent_source: str,
        *,
        consent_status: ConsentStatus | str = ConsentStatus.OPTED_IN,
        consent_text_snapshot: str | None = None,
        ip_address: str | None = None,
    ) -> CustomerConsent:
        """Record explicit consent and update lead status accordingly."""
        lead = await self.lead_repo.get_by_id_or_raise(self.organization_id, lead_id)

        chan_enum = ChannelType(channel) if isinstance(channel, str) else channel
        status_enum = (
            ConsentStatus(consent_status) if isinstance(consent_status, str) else consent_status
        )

        now = datetime.now(UTC)
        consent = CustomerConsent(
            organization_id=self.organization_id,
            lead_id=lead.id,
            channel=chan_enum.value,
            consent_status=status_enum.value,
            consent_source=consent_source,
            consent_text_snapshot=consent_text_snapshot,
            ip_address=ip_address,
            consent_timestamp=now,
            created_at=now,
        )
        await self.consent_repo.add(self.organization_id, consent)

        # Synchronize corresponding lead column
        if chan_enum == ChannelType.SMS:
            lead.sms_consent_status = status_enum.value
        elif chan_enum == ChannelType.EMAIL:
            lead.email_consent_status = status_enum.value

        await self.flush()
        return consent

    async def revoke_consent(
        self,
        lead_id: uuid.UUID,
        channel: ChannelType | str,
        *,
        opt_out_keyword: str = "STOP",
        consent_source: str = "INBOUND_KEYWORD",
    ) -> CustomerConsent:
        """Revoke consent upon receipt of STOP or opt-out keyword."""
        lead = await self.lead_repo.get_by_id_or_raise(self.organization_id, lead_id)
        chan_enum = ChannelType(channel) if isinstance(channel, str) else channel

        now = datetime.now(UTC)
        consent = CustomerConsent(
            organization_id=self.organization_id,
            lead_id=lead.id,
            channel=chan_enum.value,
            consent_status=ConsentStatus.OPTED_OUT.value,
            consent_source=consent_source,
            consent_timestamp=now,
            opt_out_timestamp=now,
            opt_out_keyword=opt_out_keyword,
            created_at=now,
        )
        await self.consent_repo.add(self.organization_id, consent)

        if chan_enum == ChannelType.SMS:
            lead.sms_consent_status = ConsentStatus.OPTED_OUT.value
        elif chan_enum == ChannelType.EMAIL:
            lead.email_consent_status = ConsentStatus.OPTED_OUT.value

        await self.flush()
        return consent
