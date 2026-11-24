"""SMS outbound integration supporting Twilio REST API with simulated default fallback."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

import httpx
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class SmsDeliveryResult(BaseModel):
    """Structured result of an outbound SMS dispatch attempt."""

    success: bool
    provider: str
    external_message_id: str | None = None
    status_code: int = 200
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class SmsSender(Protocol):
    """Protocol for outbound SMS providers."""

    async def send_sms(self, *, to_phone: str, body: str) -> SmsDeliveryResult:
        """Send an SMS message to a recipient phone number."""
        ...


class SimulatedSmsSender:
    """Zero-cost local simulated SMS sender used when Twilio credentials are absent."""

    async def send_sms(self, *, to_phone: str, body: str) -> SmsDeliveryResult:
        """Simulate SMS delivery without making any external network requests."""
        receipt_id = f"sim-sms-{uuid.uuid4().hex[:12]}"
        return SmsDeliveryResult(
            success=True,
            provider="simulated",
            external_message_id=receipt_id,
            status_code=200,
            metadata={
                "provider": "simulated",
                "simulated_at": datetime.now(UTC).isoformat(),
            },
        )


class TwilioSmsSender:
    """Real outbound SMS sender using the Twilio Messages REST API."""

    def __init__(
        self,
        *,
        account_sid: str,
        auth_token: str,
        from_phone: str,
        api_base_url: str = "https://api.twilio.com/2010-04-01",
    ) -> None:
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_phone = from_phone
        self.api_base_url = api_base_url.rstrip("/")

    async def send_sms(self, *, to_phone: str, body: str) -> SmsDeliveryResult:
        """Send an SMS via Twilio REST API and return structured delivery metadata."""
        url = f"{self.api_base_url}/Accounts/{self.account_sid}/Messages.json"
        payload = {
            "From": self.from_phone,
            "To": to_phone,
            "Body": body,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    data=payload,
                    auth=(self.account_sid, self.auth_token),
                )

            if response.status_code in (200, 201):
                resp_json = response.json()
                sid = resp_json.get("sid")
                return SmsDeliveryResult(
                    success=True,
                    provider="twilio",
                    external_message_id=sid,
                    status_code=response.status_code,
                    metadata={
                        "provider": "twilio",
                        "twilio_status": resp_json.get("status"),
                        "sent_at": datetime.now(UTC).isoformat(),
                    },
                )

            error_detail = response.text[:300]
            logger.warning(
                "Twilio SMS send failed with status %s: %s",
                response.status_code,
                error_detail,
            )
            return SmsDeliveryResult(
                success=False,
                provider="twilio",
                status_code=response.status_code,
                error_message=f"Twilio API error ({response.status_code}): {error_detail}",
                metadata={"provider": "twilio", "status_code": response.status_code},
            )
        except Exception as exc:
            logger.error("Twilio SMS transport error: %s", exc)
            return SmsDeliveryResult(
                success=False,
                provider="twilio",
                status_code=502,
                error_message=f"Twilio transport error: {exc}",
                metadata={"provider": "twilio"},
            )


def get_sms_sender(app_settings: Settings | None = None) -> SmsSender:
    """Return TwilioSmsSender when configured via env vars, otherwise SimulatedSmsSender."""
    cfg = app_settings or get_settings()
    if (
        cfg.MESSAGING_MODE.lower() == "twilio"
        and cfg.TWILIO_ACCOUNT_SID
        and cfg.TWILIO_AUTH_TOKEN
        and cfg.TWILIO_PHONE_NUMBER
    ):
        return TwilioSmsSender(
            account_sid=cfg.TWILIO_ACCOUNT_SID,
            auth_token=cfg.TWILIO_AUTH_TOKEN,
            from_phone=cfg.TWILIO_PHONE_NUMBER,
        )
    return SimulatedSmsSender()
