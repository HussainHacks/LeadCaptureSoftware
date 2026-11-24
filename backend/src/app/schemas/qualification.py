"""Pydantic schemas for QualificationResult entity."""

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import ORMBase
from app.schemas.enums import QualificationCategory


class QualificationResultBase(ORMBase):
    """Base fields shared across qualification evaluation outputs."""

    score: int = Field(..., ge=0, le=100, description="Qualification score between 0 and 100")
    category: QualificationCategory
    reasoning: str
    collected_information: dict = Field(default_factory=dict)
    missing_information: list = Field(default_factory=list)
    recommended_action: str = Field(..., max_length=50)
    requires_human: bool = False
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class QualificationResultCreate(QualificationResultBase):
    """Schema for persisting qualification evaluation output."""

    organization_id: uuid.UUID
    lead_id: uuid.UUID


class QualificationResultRead(QualificationResultBase):
    """Schema for reading qualification result details."""

    id: uuid.UUID
    organization_id: uuid.UUID
    lead_id: uuid.UUID
    created_at: datetime
