"""SQLAlchemy ORM models package exporting all entities and shared types."""

from app.core.database import Base
from app.models.appointment import Appointment
from app.models.audit import AuditLog
from app.models.consent import CustomerConsent
from app.models.conversation import Conversation
from app.models.enums import (
    AppointmentStatus,
    AutomationEventType,
    ChannelType,
    ConsentStatus,
    ConversationStatus,
    DeliveryStatus,
    LeadSource,
    LeadStatus,
    LeadUrgency,
    MessageSender,
    OutboxStatus,
    QualificationCategory,
    TimezoneSource,
    UserRole,
)
from app.models.lead import Lead
from app.models.membership import OrganizationMembership
from app.models.message import Message
from app.models.organization import Organization
from app.models.outbox import AutomationEvent
from app.models.qualification import QualificationResult
from app.models.service import Service
from app.models.user import User

__all__ = [
    "Appointment",
    "AppointmentStatus",
    "AuditLog",
    "AutomationEvent",
    "AutomationEventType",
    "Base",
    "ChannelType",
    "ConsentStatus",
    "Conversation",
    "ConversationStatus",
    "CustomerConsent",
    "DeliveryStatus",
    "Lead",
    "LeadSource",
    "LeadStatus",
    "LeadUrgency",
    "Message",
    "MessageSender",
    "Organization",
    "OrganizationMembership",
    "OutboxStatus",
    "QualificationCategory",
    "QualificationResult",
    "Service",
    "TimezoneSource",
    "User",
    "UserRole",
]
