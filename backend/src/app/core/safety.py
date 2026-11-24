"""Deterministic safety hazard detection and opt-out keyword utilities."""

import re

SAFETY_HAZARD_PATTERNS = [
    re.compile(r"\b(smell\s+gas|gas\s+leak|gas\s+odor|rotten\s+eggs)\b", re.IGNORECASE),
    re.compile(r"\b(carbon\s+monoxide|co\s+alarm|co\s+detector)\b", re.IGNORECASE),
    re.compile(
        r"\b(smoke|sparks|sparking|fire|scorched|burning\s+(?:odor|smell)|electrical\s+burning)\b",
        re.IGNORECASE,
    ),
]

OPT_OUT_KEYWORDS = {"STOP", "UNSUBSCRIBE", "CANCEL", "QUIT", "END"}
HELP_KEYWORDS = {"HELP", "INFO"}


def detect_safety_hazard(text: str) -> str | None:
    """Analyze text for critical residential HVAC safety hazards.

    Matches gas leaks, carbon monoxide alarms, and electrical/fire hazards.
    Returns the detected hazard category or phrase, or None if no hazard detected.
    """
    if not text:
        return None
    for pattern in SAFETY_HAZARD_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0).lower()
    return None


def is_opt_out_keyword(text: str) -> bool:
    """Determine whether an incoming message content matches standard opt-out keywords."""
    if not text:
        return False
    return text.strip().upper() in OPT_OUT_KEYWORDS


def is_help_keyword(text: str) -> bool:
    """Determine whether an incoming message content matches standard help keywords."""
    if not text:
        return False
    return text.strip().upper() in HELP_KEYWORDS
