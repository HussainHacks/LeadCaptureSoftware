"""Reusable enumeration types for database models and schemas."""

from enum import StrEnum


class UserRole(StrEnum):
    """User role within an organization."""

    OWNER = "owner"
    ADMIN = "admin"
    DISPATCHER = "dispatcher"
    TECHNICIAN = "technician"
    STAFF = "staff"


class TimezoneSource(StrEnum):
    """Origin of customer timezone assignment."""

    EXPLICIT_CUSTOMER = "EXPLICIT_CUSTOMER"
    POSTAL_CODE_ESTIMATE = "POSTAL_CODE_ESTIMATE"
    UNKNOWN = "UNKNOWN"


class LeadUrgency(StrEnum):
    """Urgency level of an inbound lead."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    EMERGENCY = "EMERGENCY"


class LeadStatus(StrEnum):
    """Lifecycle status of a lead."""

    NEW = "NEW"
    CONTACTED = "CONTACTED"
    QUALIFYING = "QUALIFYING"
    QUALIFIED = "QUALIFIED"
    UNQUALIFIED = "UNQUALIFIED"
    APPOINTMENT_OFFERED = "APPOINTMENT_OFFERED"
    APPOINTMENT_BOOKED = "APPOINTMENT_BOOKED"
    LOST = "LOST"
    ARCHIVED = "ARCHIVED"


class ConsentStatus(StrEnum):
    """Customer consent opt-in status."""

    OPTED_IN = "OPTED_IN"
    OPTED_OUT = "OPTED_OUT"
    PENDING = "PENDING"
    REVOKED = "REVOKED"


class ChannelType(StrEnum):
    """Communication channel."""

    SMS = "SMS"
    EMAIL = "EMAIL"
    WEB_CHAT = "WEB_CHAT"
    CALL = "CALL"


class LeadSource(StrEnum):
    """Intake origin for a lead."""

    WEBSITE_FORM = "WEBSITE_FORM"
    WEBHOOK = "WEBHOOK"
    INBOUND_SMS = "INBOUND_SMS"


class ConversationStatus(StrEnum):
    """State of an ongoing conversation thread."""

    AI_ACTIVE = "AI_ACTIVE"
    AWAITING_CUSTOMER = "AWAITING_CUSTOMER"
    HUMAN_TAKEOVER = "HUMAN_TAKEOVER"
    ESCALATED_SAFETY = "ESCALATED_SAFETY"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"


class MessageSender(StrEnum):
    """Sender type for conversation messages."""

    CUSTOMER = "CUSTOMER"
    AI_AGENT = "AI_AGENT"
    HUMAN_AGENT = "HUMAN_AGENT"
    SYSTEM = "SYSTEM"


class DeliveryStatus(StrEnum):
    """Dispatch status of an individual message."""

    QUEUED = "QUEUED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    RECEIVED = "RECEIVED"


class AppointmentStatus(StrEnum):
    """Status lifecycle of a booked appointment."""

    CONFIRMED = "CONFIRMED"
    OFFERED = "OFFERED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    RESCHEDULED = "RESCHEDULED"
    NO_SHOW = "NO_SHOW"


class QualificationCategory(StrEnum):
    """Outcome tier of qualification scoring."""

    HOT = "HOT"
    WARM = "WARM"
    COLD = "COLD"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class OutboxStatus(StrEnum):
    """Transactional outbox event delivery status."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"


class AutomationEventType(StrEnum):
    """Transactional outbox event type identifier."""

    LEAD_CREATED = "LEAD_CREATED"
    LEAD_UPDATED = "LEAD_UPDATED"
    MESSAGE_SENT = "MESSAGE_SENT"
    MESSAGE_RECEIVED = "MESSAGE_RECEIVED"
    APPOINTMENT_SCHEDULED = "APPOINTMENT_SCHEDULED"
    APPOINTMENT_RESCHEDULED = "APPOINTMENT_RESCHEDULED"
    APPOINTMENT_CANCELLED = "APPOINTMENT_CANCELLED"
    QUALIFICATION_COMPLETED = "QUALIFICATION_COMPLETED"
    SAFETY_ESCALATED = "SAFETY_ESCALATED"
