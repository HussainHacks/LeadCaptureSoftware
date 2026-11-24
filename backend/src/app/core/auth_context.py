"""Authorization context data structures for service-layer operations.

ARCHITECTURAL NOTE:
Callers are authenticated at the FastAPI boundary: app.api.deps.get_current_user
validates the JWT bearer token, checks revocation, and resolves the caller's
active OrganizationMembership before any service runs. The ActorContext
structure below is the verified identity that boundary hands to internal
service-layer methods, which additionally check the actor's role against
OrganizationMembership for each operation.
"""

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class ActorContext:
    """Internal service context representing the acting staff member.

    Attributes:
        user_id: The UUID of the staff user performing the action.
        organization_id: The UUID of the organization tenant scope.
    """

    user_id: uuid.UUID
    organization_id: uuid.UUID
