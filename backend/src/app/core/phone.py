"""Phone number validation and E.164 normalization utilities."""

import re

from app.core.exceptions import ValidationError


def normalize_phone_number(raw_phone: str) -> str:
    """Normalize a phone number to standard E.164 format (+1XXXXXXXXXX for NANP).

    Supported formats:
    - 10-digit North American: '(555) 123-4567', '555-123-4567' -> '+15551234567'
    - 11-digit with country 1: '1-555-123-4567', '15551234567' -> '+15551234567'
    - Existing E.164 format: '+15551234567' -> '+15551234567'
    - International numbers: '+442071838750' -> '+442071838750'

    Raises:
        ValidationError: If the phone number is empty, malformed, or has an invalid digit count.
    """
    if not raw_phone or not raw_phone.strip():
        raise ValidationError("Phone number cannot be empty.")

    cleaned = raw_phone.strip()
    # Remove whitespace, parentheses, hyphens, and dots
    cleaned = re.sub(r"[\s\(\)\-\.]", "", cleaned)

    if not re.match(r"^\+?[0-9]+$", cleaned):
        raise ValidationError(f"Invalid phone number format: '{raw_phone}'.")

    if cleaned.startswith("+"):
        digits = cleaned[1:]
        if len(digits) < 10 or len(digits) > 15:
            raise ValidationError(
                f"Phone number '{raw_phone}' has invalid length for E.164 "
                f"format ({len(digits)} digits)."
            )
        return f"+{digits}"

    # Handle standard numbers without leading '+'
    if len(cleaned) == 10:
        return f"+1{cleaned}"
    elif len(cleaned) == 11 and cleaned.startswith("1"):
        return f"+{cleaned}"
    else:
        raise ValidationError(
            f"Phone number '{raw_phone}' must be a valid 10-digit North American "
            "number or include an international country code."
        )
