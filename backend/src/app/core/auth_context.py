"""Authorization context data structures for service-layer operations.

IMPORTANT ARCHITECTURAL NOTICE:
There is currently no public authentication middleware (e.g. JWT tokens, session
cookies, OAuth providers) implemented in this platform. The ActorContext structure
represents the explicit authorization identity passed to internal service-layer
methods.

Checking an actor's role against OrganizationMembership in the service layer
validates permissions for that identity, but DOES NOT authenticate that the caller
actually owns or controls that identity. Secure cryptographic identity authentication
must be enforced in Phase 3 at the FastAPI middleware boundary (e.g. get_current_user).
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
