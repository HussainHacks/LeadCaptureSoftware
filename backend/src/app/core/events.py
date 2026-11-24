"""Event dispatch abstractions and simulation dispatcher for transactional outbox.

This module provides the core event dispatcher protocol, structured dispatch results,
and a deterministic simulation dispatcher for testing and development.

Guarantees:
- Phase 2 simulation-only (no Twilio, OpenAI, n8n, Stripe, or external network I/O).
- Zero database connections, row locks, or transactions committed inside the dispatcher.
- Structured, typed dispatch results consumed by the worker settlement lifecycle.
- Deterministic control over success, retryable failures, and permanent failures.
"""

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.core.exceptions import (
    PermanentDispatchError,
    RetryableDispatchError,
)

# Keys redacted during internal telemetry and event recording
SENSITIVE_FIELD_NAMES: set[str] = {
    "password",
    "secret",
    "token",
    "api_key",
    "auth",
    "authorization",
    "credit_card",
    "ssn",
    "phone",
    "email",
}


def sanitize_payload(obj: Any) -> Any:
    """Recursively sanitize a dictionary or list, masking sensitive fields."""
    if isinstance(obj, dict):
        sanitized: dict[str, Any] = {}
        for k, v in obj.items():
            if any(sensitive in k.lower() for sensitive in SENSITIVE_FIELD_NAMES):
                sanitized[k] = "[REDACTED]"
            elif isinstance(v, (dict, list)):
                sanitized[k] = sanitize_payload(v)
            else:
                sanitized[k] = v
        return sanitized
    elif isinstance(obj, list):
        return [sanitize_payload(item) for item in obj]
    return obj


class DispatchResult(BaseModel):
    """Structured result returned by EventDispatcher implementations.

    Consumed by the background outbox worker during Session 2 (Settlement Phase).
    """

    model_config = ConfigDict(frozen=True)

    success: bool = Field(..., description="True if delivery succeeded; False otherwise")
    event_id: str = Field(..., description="Unique event identifier")
    event_type: str = Field(..., description="Domain event category name")
    status_code: int = Field(default=200, description="Transport or simulated status code")
    dispatched_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp when dispatch completed",
    )
    provider_response_id: str | None = Field(
        default=None,
        description="Opaque upstream receipt ID returned by external provider if available",
    )
    error_message: str | None = Field(
        default=None,
        description="Detailed failure message when success is False",
    )
    retryable: bool = Field(
        default=False,
        description="Whether a failed delivery is eligible for retry with backoff",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Sanitized non-sensitive operational telemetry",
    )


@runtime_checkable
class EventDispatcher(Protocol):
    """Interface protocol for event dispatchers.

    Implementations must perform external I/O outside of any open database
    transactions to prevent holding database row locks during network latency.
    """

    async def dispatch(self, envelope: dict[str, Any] | Any) -> DispatchResult:
        """Dispatch an outbox event envelope to its intended destination."""
        ...


class SimulatedEventDispatcher:
    """Deterministic simulation-only event dispatcher for Phase 2.

    Strict Architectural Boundaries:
    1. Zero external network requests (no Twilio, n8n webhooks, Stripe, or HTTP calls).
    2. Zero database connections or transaction commits.
    3. Never mutates authoritative business state.
    4. Deterministic and configurable for comprehensive automated testing.
    5. Sanitizes recorded payloads to prevent sensitive data leakage.
    """

    def __init__(
        self,
        *,
        mode: str = "success",
        default_status_code: int = 200,
        raise_on_failure: bool = False,
        failure_matcher: Callable[[dict[str, Any]], DispatchResult | Exception | None]
        | None = None,
    ) -> None:
        """Initialize the simulated event dispatcher.

        Args:
            mode: Default behavior mode ("success", "fail_retryable", "fail_permanent").
            default_status_code: Default HTTP/simulation status code (200, 503, 400).
            raise_on_failure: If True, raises DispatchError instead of returning
                a failed DispatchResult.
            failure_matcher: Optional custom matcher callable returning specific
                results or exceptions.
        """
        self.mode = mode
        self.default_status_code = default_status_code
        self.raise_on_failure = raise_on_failure
        self.failure_matcher = failure_matcher
        self._dispatched_events: list[dict[str, Any]] = []
        self._dispatched_results: list[DispatchResult] = []

    @property
    def dispatched_events(self) -> list[dict[str, Any]]:
        """Return a copy of all dispatched event envelopes recorded in this session."""
        return list(self._dispatched_events)

    @property
    def dispatched_results(self) -> list[DispatchResult]:
        """Return a copy of all structured dispatch results recorded in this session."""
        return list(self._dispatched_results)

    @property
    def dispatch_count(self) -> int:
        """Return the number of events dispatched so far."""
        return len(self._dispatched_events)

    def clear(self) -> None:
        """Reset internal dispatch history."""
        self._dispatched_events.clear()
        self._dispatched_results.clear()

    def _normalize_envelope(
        self, envelope: dict[str, Any] | Any
    ) -> tuple[str, str, dict[str, Any]]:
        """Extract event_id, event_type, and raw payload from an envelope or model."""
        if isinstance(envelope, dict):
            event_id = str(envelope.get("event_id") or envelope.get("id") or uuid.uuid4())
            event_type = str(envelope.get("event_type") or "unknown.event")
            raw_payload = envelope.get("payload") or envelope.get("data") or envelope
            if not isinstance(raw_payload, dict):
                raw_payload = {"raw_value": raw_payload}
            return event_id, event_type, raw_payload
        else:
            # SQLAlchemy model or dataclass object
            event_id = str(getattr(envelope, "id", None) or uuid.uuid4())
            event_type = str(getattr(envelope, "event_type", "unknown.event"))
            raw_payload = getattr(envelope, "payload", {})
            if isinstance(raw_payload, str):
                try:
                    raw_payload = json.loads(raw_payload)
                except Exception:
                    raw_payload = {"raw_text": raw_payload}
            elif not isinstance(raw_payload, dict):
                raw_payload = {"raw_value": str(raw_payload)}
            return event_id, event_type, raw_payload

    async def dispatch(self, envelope: dict[str, Any] | Any) -> DispatchResult:
        """Simulate dispatching an event envelope with deterministic outcome.

        Args:
            envelope: Event dictionary or AutomationEvent-like model.

        Returns:
            Structured DispatchResult containing success, retryability, and telemetry.

        Raises:
            DispatchError: If raise_on_failure is enabled and dispatch fails,
                           or if envelope contains an explicit '_simulate_exception' directive.
        """
        event_id, event_type, payload = self._normalize_envelope(envelope)

        # 1. Check for simulation exception directives in envelope/payload
        sim_exc = payload.get("_simulate_exception") or (
            envelope.get("_simulate_exception") if isinstance(envelope, dict) else None
        )
        if sim_exc == "retryable":
            raise RetryableDispatchError(
                f"Simulated retryable exception for event {event_id}",
                status_code=503,
                event_id=event_id,
            )
        elif sim_exc == "permanent":
            raise PermanentDispatchError(
                f"Simulated permanent exception for event {event_id}",
                status_code=400,
                event_id=event_id,
            )
        elif sim_exc == "runtime":
            raise RuntimeError(f"Simulated unexpected simulator crash for event {event_id}")

        # 2. Check custom failure matcher callable if provided
        if self.failure_matcher is not None:
            matcher_result = self.failure_matcher(
                envelope
                if isinstance(envelope, dict)
                else {"event_id": event_id, "event_type": event_type, "payload": payload}
            )
            if isinstance(matcher_result, Exception):
                raise matcher_result
            elif isinstance(matcher_result, DispatchResult):
                self._record(envelope, matcher_result)
                return matcher_result

        # 3. Check for per-event simulation failure directives
        sim_failure = payload.get("_simulate_failure") or (
            envelope.get("_simulate_failure") if isinstance(envelope, dict) else None
        )
        sim_status = payload.get("_simulate_status") or (
            envelope.get("_simulate_status") if isinstance(envelope, dict) else None
        )

        if sim_failure is True:
            effective_mode = "fail_retryable"
        else:
            effective_mode = sim_failure or self.mode
        now = datetime.now(UTC)

        if effective_mode in ("fail_retryable", "retryable"):
            status_code = sim_status or 503
            result = DispatchResult(
                success=False,
                event_id=event_id,
                event_type=event_type,
                status_code=status_code,
                dispatched_at=now,
                provider_response_id=None,
                error_message=f"Simulated transient error (HTTP {status_code})",
                retryable=True,
                metadata={
                    "simulator": "SimulatedEventDispatcher",
                    "simulated_failure": "retryable",
                },
            )
        elif effective_mode in ("fail_permanent", "permanent"):
            status_code = sim_status or 400
            result = DispatchResult(
                success=False,
                event_id=event_id,
                event_type=event_type,
                status_code=status_code,
                dispatched_at=now,
                provider_response_id=None,
                error_message=f"Simulated permanent error (HTTP {status_code})",
                retryable=False,
                metadata={
                    "simulator": "SimulatedEventDispatcher",
                    "simulated_failure": "permanent",
                },
            )
        else:
            # Default to simulated success
            status_code = sim_status or self.default_status_code or 200
            provider_ref = f"sim-receipt-{uuid.uuid4().hex[:12]}"
            result = DispatchResult(
                success=True,
                event_id=event_id,
                event_type=event_type,
                status_code=status_code,
                dispatched_at=now,
                provider_response_id=provider_ref,
                error_message=None,
                retryable=False,
                metadata={"simulator": "SimulatedEventDispatcher", "mode": "simulated_delivery"},
            )

        self._record(envelope, result)

        if self.raise_on_failure and not result.success:
            if result.retryable:
                raise RetryableDispatchError(
                    result.error_message or "Simulated retryable dispatch error",
                    status_code=result.status_code,
                    event_id=event_id,
                )
            else:
                raise PermanentDispatchError(
                    result.error_message or "Simulated permanent dispatch error",
                    status_code=result.status_code,
                    event_id=event_id,
                )

        return result

    def _record(self, envelope: dict[str, Any] | Any, result: DispatchResult) -> None:
        """Record sanitized event copy and result for test assertions."""
        if isinstance(envelope, dict):
            sanitized_envelope = sanitize_payload(envelope)
        else:
            sanitized_envelope = {
                "id": str(getattr(envelope, "id", "")),
                "event_type": str(getattr(envelope, "event_type", "")),
                "payload": sanitize_payload(getattr(envelope, "payload", {})),
            }

        self._dispatched_events.append(sanitized_envelope)
        self._dispatched_results.append(result)
