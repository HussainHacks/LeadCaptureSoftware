"""Repository pattern package exporting base and entity repositories."""

from app.repositories.base import BaseRepository
from app.repositories.entities import (
    AppointmentRepository,
    AuditLogRepository,
    AutomationEventRepository,
    ConsentRepository,
    ConversationRepository,
    LeadRepository,
    MessageRepository,
    OrganizationMembershipRepository,
    OrganizationRepository,
    QualificationRepository,
    ServiceRepository,
    UserRepository,
)
from app.repositories.global_repo import GlobalRepository
from app.repositories.tenant import TenantRepository

__all__ = [
    "AppointmentRepository",
    "AuditLogRepository",
    "AutomationEventRepository",
    "BaseRepository",
    "ConsentRepository",
    "ConversationRepository",
    "GlobalRepository",
    "LeadRepository",
    "MessageRepository",
    "OrganizationMembershipRepository",
    "OrganizationRepository",
    "QualificationRepository",
    "ServiceRepository",
    "TenantRepository",
    "UserRepository",
]
