"""Pydantic schemas package exporting public validation models and internal service DTOs.

IMPORTANT ARCHITECTURAL NOTICE:
Pydantic schema separation (e.g. InboundMessageRequest vs MessageCreate / InternalMessageCreate,
LeadUpdate vs LeadInternalUpdate) defines strict structural boundaries between client input
and trusted internal representations. However, schema typing alone is NOT an authorization
or access-control mechanism.

Future API route handlers MUST:
1. Explicitly bind only appropriate public request models (e.g., InboundMessageRequest,
   LeadUpdate, AppointmentCreate).
2. Never accept internal service DTOs (e.g., InternalMessageCreate, LeadInternalUpdate,
   InternalAutomationEventCreate, InternalAuditLogCreate) as public endpoint request bodies.
3. Enforce tenant boundary checks (organization_id scoping) and RBAC permissions in
   the FastAPI dependency / authorization layer prior to invoking service operations.
"""

from app.schemas.appointment import (
    AppointmentBase,
    AppointmentCreate,
    AppointmentRead,
    AppointmentUpdate,
)
from app.schemas.audit import AuditLogCreate, AuditLogRead, InternalAuditLogCreate
from app.schemas.common import ORMBase
from app.schemas.consent import CustomerConsentCreate, CustomerConsentRead
from app.schemas.conversation import (
    ConversationBase,
    ConversationCreate,
    ConversationEscalationRequest,
    ConversationInternalUpdate,
    ConversationRead,
    ConversationUpdate,
)
from app.schemas.enums import (
    AppointmentStatus,
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
from app.schemas.lead import (
    LeadBase,
    LeadCreate,
    LeadInternalUpdate,
    LeadRead,
    LeadUpdate,
)
from app.schemas.membership import (
    OrganizationMembershipBase,
    OrganizationMembershipCreate,
    OrganizationMembershipRead,
    OrganizationMembershipUpdate,
)
from app.schemas.message import (
    InboundMessageRequest,
    InternalMessageCreate,
    MessageBase,
    MessageCreate,
    MessageRead,
)
from app.schemas.organization import (
    OrganizationBase,
    OrganizationCreate,
    OrganizationRead,
    OrganizationUpdate,
)
from app.schemas.outbox import (
    AutomationEventBase,
    AutomationEventCreate,
    AutomationEventRead,
    AutomationEventUpdate,
    InternalAutomationEventCreate,
)
from app.schemas.qualification import (
    QualificationResultBase,
    QualificationResultCreate,
    QualificationResultRead,
)
from app.schemas.service import (
    ServiceBase,
    ServiceCreate,
    ServiceRead,
    ServiceUpdate,
)
from app.schemas.user import UserBase, UserCreate, UserRead, UserUpdate

__all__ = [
    "AppointmentBase",
    "AppointmentCreate",
    "AppointmentRead",
    "AppointmentStatus",
    "AppointmentUpdate",
    "AuditLogCreate",
    "AuditLogRead",
    "AutomationEventBase",
    "AutomationEventCreate",
    "AutomationEventRead",
    "AutomationEventUpdate",
    "ChannelType",
    "ConsentStatus",
    "ConversationBase",
    "ConversationCreate",
    "ConversationEscalationRequest",
    "ConversationInternalUpdate",
    "ConversationRead",
    "ConversationStatus",
    "ConversationUpdate",
    "CustomerConsentCreate",
    "CustomerConsentRead",
    "DeliveryStatus",
    "InboundMessageRequest",
    "InternalAuditLogCreate",
    "InternalAutomationEventCreate",
    "InternalMessageCreate",
    "LeadBase",
    "LeadCreate",
    "LeadInternalUpdate",
    "LeadRead",
    "LeadSource",
    "LeadStatus",
    "LeadUpdate",
    "LeadUrgency",
    "MessageBase",
    "MessageCreate",
    "MessageRead",
    "MessageSender",
    "ORMBase",
    "OrganizationBase",
    "OrganizationCreate",
    "OrganizationMembershipBase",
    "OrganizationMembershipCreate",
    "OrganizationMembershipRead",
    "OrganizationMembershipUpdate",
    "OrganizationRead",
    "OrganizationUpdate",
    "OutboxStatus",
    "QualificationCategory",
    "QualificationResultBase",
    "QualificationResultCreate",
    "QualificationResultRead",
    "ServiceBase",
    "ServiceCreate",
    "ServiceRead",
    "ServiceUpdate",
    "TimezoneSource",
    "UserBase",
    "UserCreate",
    "UserRead",
    "UserRole",
    "UserUpdate",
]
