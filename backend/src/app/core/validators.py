"""Reusable domain input validation and normalization functions."""

import re

from app.core.exceptions import ValidationError

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def validate_email_address(raw_email: str | None) -> str | None:
    """Validate and normalize an optional email address.

    Returns:
        Normalized lowercased email string, or None if raw_email is None or empty.

    Raises:
        ValidationError: If raw_email is invalid or exceeds 255 characters.
    """
    if raw_email is None:
        return None

    email = raw_email.strip()
    if not email:
        return None

    if len(email) > 255:
        raise ValidationError("Email address cannot exceed 255 characters.")

    if not EMAIL_REGEX.match(email):
        raise ValidationError(f"Invalid email address format: '{raw_email}'.")

    return email.lower()
