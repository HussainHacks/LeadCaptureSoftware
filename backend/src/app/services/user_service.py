"""Service orchestrating global user account lifecycle and credentials."""

import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EntityAlreadyExistsError, ValidationError
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.repositories.entities import UserRepository
from app.schemas.user import UserCreate, UserRead

# RFC 5322 simplified email validation pattern
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


class UserService:
    """Service handling user account registration and retrieval.

    Operates globally across the platform. Never persists plaintext passwords
    and never exposes password hashes in user-facing schemas.
    """

    def __init__(
        self,
        session: AsyncSession,
        user_repo: UserRepository | None = None,
    ) -> None:
        self.session = session
        self.user_repo = user_repo or UserRepository(session)

    async def register_user(self, data: UserCreate) -> User:
        """Register a new global user.

        Performs:
        1. Email format normalization and validation.
        2. Duplicate account prevention (uniqueness check on email).
        3. Plaintext password validation and secure bcrypt hashing (cost >= 12).
        4. User entity instantiation without storing plaintext passwords.
        5. Flush to session to evaluate constraints without premature commit.
        """
        # 1. Normalize and validate email
        raw_email = data.email.strip() if data.email else ""
        if not raw_email or not EMAIL_REGEX.match(raw_email):
            raise ValidationError(f"Invalid email address format: '{data.email}'.")

        normalized_email = raw_email.lower()

        # 2. Check for duplicate account
        existing = await self.user_repo.get_by_email(normalized_email)
        if existing is not None:
            raise EntityAlreadyExistsError("User", "email", normalized_email)

        # 3. Validate and hash password
        if not data.password or len(data.password) < 8:
            raise ValidationError("Password must be at least 8 characters long.")
        if len(data.password) > 128:
            raise ValidationError("Password cannot exceed 128 characters.")

        hashed = hash_password(data.password)

        # 4. Instantiate and persist user
        user = User(
            email=normalized_email,
            password_hash=hashed,
            first_name=data.first_name.strip(),
            last_name=data.last_name.strip(),
            phone=data.phone.strip() if data.phone else None,
            is_active=True,
        )

        return await self.user_repo.add(user)

    async def get_user_by_id(self, user_id: uuid.UUID) -> User:
        """Retrieve a user by ID or raise EntityNotFoundError."""
        return await self.user_repo.get_by_id_or_raise(user_id)

    async def get_user_by_email(self, email: str) -> User | None:
        """Retrieve a user by email, or None if not found."""
        return await self.user_repo.get_by_email(email.strip().lower())

    async def authenticate_user(self, email: str, password: str) -> User | None:
        """Authenticate a user by email and plaintext password."""
        user = await self.get_user_by_email(email)
        if not user or not user.is_active:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user

    def to_read_schema(self, user: User) -> UserRead:
        """Convert a User entity to a safe, user-facing UserRead schema.

        Ensures password hashes are never returned to client-facing callers.
        """
        return UserRead.model_validate(user)
