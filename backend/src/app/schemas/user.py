"""Pydantic schemas for User entity."""

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import ORMBase


class UserBase(ORMBase):
    """Base fields shared across User operations."""

    email: str = Field(..., max_length=255, description="Normalized lower-case login email")
    first_name: str = Field(..., max_length=80)
    last_name: str = Field(..., max_length=80)
    phone: str | None = Field(default=None, max_length=30)


class UserCreate(UserBase):
    """Schema for creating a new user account."""

    password: str = Field(
        ..., min_length=8, max_length=128, description="Plaintext password to be hashed"
    )


class UserUpdate(ORMBase):
    """Schema for updating an existing user."""

    first_name: str | None = Field(default=None, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=30)
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserRead(UserBase):
    """Safe schema for reading user details. Never exposes password hash."""

    id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime
