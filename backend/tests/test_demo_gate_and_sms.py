"""DB-free unit tests for Demo Mode security gate, Twilio/Simulated SMS, and input sanitization."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.public import (
    _LOCAL_RATE_LIMIT_BUCKETS,
    RATE_LIMIT_MAX_REQUESTS,
    check_rate_limit,
    sanitize_text,
)
from app.core.config import Settings
from app.integrations.sms import SimulatedSmsSender, TwilioSmsSender, get_sms_sender
from app.main import create_application


def test_demo_disabled_by_default_and_returns_404() -> None:
    """When DEMO_ENABLED is false (default), demo router is not registered and returns 404."""
    cfg = Settings(DEMO_ENABLED=False)
    assert cfg.DEMO_ENABLED is False

    app = create_application(cfg)
    client = TestClient(app)

    res_info = client.get("/api/demo/info")
    res_seed = client.post("/api/demo/seed")
    assert res_info.status_code == 404
    assert res_seed.status_code == 404


def test_demo_enabled_without_password_fails_startup() -> None:
    """Enabling DEMO_ENABLED without DEMO_PASSWORD must fail Settings validation and app startup."""
    with pytest.raises(ValueError, match="DEMO_PASSWORD"):
        Settings(DEMO_ENABLED=True, DEMO_PASSWORD=None)

    with pytest.raises(ValueError, match="DEMO_PASSWORD"):
        Settings(DEMO_ENABLED=True, DEMO_PASSWORD="   ")


def test_demo_enabled_in_production_fails_startup() -> None:
    """DEMO_ENABLED=true must be rejected when ENVIRONMENT is production."""
    with pytest.raises(ValueError, match="production"):
        Settings(DEMO_ENABLED=True, ENVIRONMENT="production", DEMO_PASSWORD="dev-only-password")


def test_demo_enabled_with_password_registers_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    """When DEMO_ENABLED=true and DEMO_PASSWORD is set, /api/demo/info uses env DEMO_PASSWORD."""
    cfg = Settings(DEMO_ENABLED=True, DEMO_PASSWORD="ephemeral-test-password")
    monkeypatch.setattr("app.api.demo.get_settings", lambda: cfg)

    app = create_application(cfg)
    client = TestClient(app)

    res = client.get("/api/demo/info")
    assert res.status_code == 200
    body = res.json()
    assert body["credentials"]["owner"]["password"] == "ephemeral-test-password"


@pytest.mark.asyncio
async def test_sms_sender_defaults_to_simulated_when_twilio_absent() -> None:
    """get_sms_sender returns SimulatedSmsSender when Twilio creds are absent."""
    assert isinstance(get_sms_sender(Settings(MESSAGING_MODE="simulated")), SimulatedSmsSender)
    assert isinstance(
        get_sms_sender(Settings(MESSAGING_MODE="twilio", TWILIO_ACCOUNT_SID=None)),
        SimulatedSmsSender,
    )

    sender = SimulatedSmsSender()
    result = await sender.send_sms(to_phone="+15550101234", body="Hello from LeadGen")
    assert result.success is True
    assert result.provider == "simulated"
    assert result.external_message_id is not None
    assert result.external_message_id.startswith("sim-sms-")


@pytest.mark.asyncio
async def test_twilio_sms_sender_sends_and_handles_errors() -> None:
    """TwilioSmsSender sends via Twilio REST API and returns structured success/failure."""
    cfg = Settings(
        MESSAGING_MODE="twilio",
        TWILIO_ACCOUNT_SID="AC_TEST_SID",
        TWILIO_AUTH_TOKEN="TEST_AUTH_TOKEN",
        TWILIO_PHONE_NUMBER="+15559998888",
    )
    sender = get_sms_sender(cfg)
    assert isinstance(sender, TwilioSmsSender)

    mock_ok_response = MagicMock()
    mock_ok_response.status_code = 201
    mock_ok_response.json.return_value = {"sid": "SM1234567890abcdef", "status": "queued"}

    with patch("app.integrations.sms.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_ok_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        res = await sender.send_sms(to_phone="+15550109999", body="Tech arriving at 2pm")
        assert res.success is True
        assert res.provider == "twilio"
        assert res.external_message_id == "SM1234567890abcdef"
        mock_client.post.assert_awaited_once()

    mock_err_response = MagicMock()
    mock_err_response.status_code = 400
    mock_err_response.text = "Invalid To phone number"

    with patch("app.integrations.sms.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_err_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        res_err = await sender.send_sms(to_phone="+1555", body="Bad number")
        assert res_err.success is False
        assert res_err.provider == "twilio"
        assert res_err.status_code == 400
        assert "Invalid To phone number" in (res_err.error_message or "")


def test_public_sanitize_and_honeypot_and_missing_key() -> None:
    """Verify input sanitization, honeypot spam trap, and missing site key rejection (DB-free)."""
    assert (
        sanitize_text("<script>alert(1)</script>  John   Doe\x00 ", max_length=80)
        == "alert(1) John Doe"
    )
    assert sanitize_text("   ", max_length=80) is None

    app = create_application(Settings(DEMO_ENABLED=False))
    client = TestClient(app)

    # Honeypot populated -> silently accepted without DB call
    hp_res = client.post(
        "/api/public/leads",
        json={
            "name": "Bot User",
            "phone": "+15550102222",
            "website": "https://spam.example.com",
        },
    )
    assert hp_res.status_code == 201
    assert hp_res.json()["lead_id"] is None

    # Missing site key -> 401
    no_key_res = client.post(
        "/api/public/leads",
        json={"name": "Real User", "phone": "+15550102222"},
    )
    assert no_key_res.status_code == 401


@pytest.mark.asyncio
async def test_public_rate_limiter_fallback_blocks_excess_requests() -> None:
    """Rate limiter raises HTTP 429 after RATE_LIMIT_MAX_REQUESTS when Redis is unavailable."""
    from fastapi import HTTPException

    _LOCAL_RATE_LIMIT_BUCKETS.clear()
    with patch("app.api.public.redis_client.incr", side_effect=ConnectionError("no redis")):
        for _ in range(RATE_LIMIT_MAX_REQUESTS):
            await check_rate_limit("127.0.0.1:testsitekey")
        with pytest.raises(HTTPException) as exc_info:
            await check_rate_limit("127.0.0.1:testsitekey")
        assert exc_info.value.status_code == 429
