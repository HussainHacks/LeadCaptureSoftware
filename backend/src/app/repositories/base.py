"""Base repository foundation using SQLAlchemy asynchronous sessions."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Base


class BaseRepository[ModelT: Base]:
    """Abstract base repository providing common database session access.

    Repositories are responsible purely for data persistence and retrieval.
    Business rules, orchestration, and transaction boundary commitments belong
    exclusively to the service layer.
    """

    def __init__(self, session: AsyncSession, model_cls: type[ModelT]) -> None:
        self.session = session
        self.model_cls = model_cls
