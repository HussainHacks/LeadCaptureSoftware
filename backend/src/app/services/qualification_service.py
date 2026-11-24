"""Deterministic lead qualification engine and structured evaluation service."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_context import ActorContext
from app.core.exceptions import (
    EntityNotFoundError,
    InvalidOperationError,
    ValidationError,
)
from app.core.safety import detect_safety_hazard
from app.models.enums import (
    ConversationStatus,
    LeadStatus,
    LeadUrgency,
    QualificationCategory,
    UserRole,
)
from app.models.lead import Lead
from app.models.qualification import QualificationResult
from app.models.service import Service
from app.repositories.entities import (
    AuditLogRepository,
    ConversationRepository,
    LeadRepository,
    OrganizationMembershipRepository,
    QualificationRepository,
    ServiceRepository,
)
from app.services.base import TenantService


class QualificationService(TenantService):
    """Tenant-scoped service evaluating leads deterministically with structured rules."""

    def __init__(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        qualification_repo: QualificationRepository | None = None,
        lead_repo: LeadRepository | None = None,
        service_repo: ServiceRepository | None = None,
        membership_repo: OrganizationMembershipRepository | None = None,
        conversation_repo: ConversationRepository | None = None,
        audit_repo: AuditLogRepository | None = None,
    ) -> None:
        super().__init__(session, organization_id)
        self.qualification_repo = qualification_repo or QualificationRepository(session)
        self.lead_repo = lead_repo or LeadRepository(session)
        self.service_repo = service_repo or ServiceRepository(session)
        self.membership_repo = membership_repo or OrganizationMembershipRepository(session)
        self.conversation_repo = conversation_repo or ConversationRepository(session)
        self.audit_repo = audit_repo or AuditLogRepository(session)

    async def evaluate_lead(self, lead_id: uuid.UUID) -> QualificationResult:
        """Deterministically evaluate and score a lead based on structured criteria.

        Evaluates safety hazards, critical data completeness, contractor service match,
        urgency, and customer consent status. Persists the result and updates the lead.
        """
        lead = await self.lead_repo.get_by_id(self.organization_id, lead_id)
        if lead is None or lead.deleted_at is not None:
            raise EntityNotFoundError("Lead", lead_id)

        # Retrieve active contractor services
        active_services = await self.service_repo.list(self.organization_id, active_only=True)

        result = self._evaluate_deterministic(lead, active_services)

        # Persist to database
        saved_result = await self.qualification_repo.add(self.organization_id, result)

        # Update lead's internal qualification score
        lead.qualification_score = saved_result.score

        # Transition lead lifecycle status according to evaluation category
        cat = QualificationCategory(saved_result.category)
        if cat in (QualificationCategory.HOT, QualificationCategory.WARM):
            if lead.status in (
                LeadStatus.NEW.value,
                LeadStatus.CONTACTED.value,
                LeadStatus.QUALIFYING.value,
            ):
                lead.status = LeadStatus.QUALIFIED.value
        elif cat == QualificationCategory.COLD:
            if lead.status in (
                LeadStatus.NEW.value,
                LeadStatus.CONTACTED.value,
                LeadStatus.QUALIFYING.value,
            ):
                lead.status = LeadStatus.UNQUALIFIED.value
        elif cat == QualificationCategory.HUMAN_REVIEW:
            if lead.status in (LeadStatus.NEW.value, LeadStatus.CONTACTED.value):
                lead.status = LeadStatus.QUALIFYING.value

        await self.flush()
        return saved_result

    def _evaluate_deterministic(
        self,
        lead: Lead,
        active_services: Sequence[Service],
    ) -> QualificationResult:
        """Pure deterministic evaluation function implementing business rules."""
        full_text = (
            f"{lead.problem_description or ''} {lead.service_type or ''} "
            f"{lead.equipment_type or ''}"
        )

        # 1. IMMEDIATE SAFETY HAZARD CHECK (Highest Priority Rule)
        hazard = detect_safety_hazard(full_text)
        if hazard:
            return QualificationResult(
                organization_id=self.organization_id,
                lead_id=lead.id,
                score=100,
                category=QualificationCategory.HUMAN_REVIEW.value,
                reasoning=(
                    f"Immediate residential HVAC safety hazard detected: '{hazard}'. "
                    "Automated replies halted; directed customer to safe location and 911; "
                    "triggered urgent human safety escalation."
                ),
                collected_information={
                    "safety_hazard": hazard,
                    "hazard_detected": True,
                    "phone": lead.phone,
                    "postal_code": lead.postal_code,
                },
                missing_information=[],
                recommended_action="EMERGENCY_SAFETY_DISPATCH",
                requires_human=True,
                confidence=1.0,
                created_at=datetime.now(UTC),
            )

        # 2. CHECK CRITICAL INFORMATION COMPLETENESS
        missing_information: list[str] = []
        if not lead.phone or len(lead.phone.strip()) < 7:
            missing_information.append("phone")
        if not lead.problem_description or len(lead.problem_description.strip()) < 5:
            missing_information.append("problem_description")
        if not lead.postal_code or len(lead.postal_code.strip()) < 3:
            missing_information.append("postal_code")

        # 3. SERVICE MATCH CHECK AGAINST CONTRACTOR'S ACTIVE CATALOG
        matched_service: Service | None = None
        service_query = (lead.service_type or "").strip().lower()
        desc_query = (lead.problem_description or "").strip().lower()

        for svc in active_services:
            code_lower = svc.service_code.lower()
            name_lower = svc.service_name.lower()
            if (service_query and (code_lower in service_query or name_lower in service_query)) or (
                desc_query and (code_lower in desc_query or name_lower in desc_query)
            ):
                matched_service = svc
                break

        # Check whether the service request is clearly identified vs unknown/ambiguous
        ambiguous_terms = {
            "other",
            "general",
            "service",
            "help",
            "repair",
            "unknown",
            "n/a",
            "na",
            "hvac",
            "issue",
            "maintenance",
            "check",
            "consultation",
            "question",
        }
        has_specific_service = bool(service_query) and service_query not in ambiguous_terms

        is_unsupported = False
        is_ambiguous_service = False

        if matched_service is None:
            if has_specific_service:
                # Clearly identified service that this contractor does not offer in their catalog
                is_unsupported = True
            else:
                # Unknown or ambiguous service request
                is_ambiguous_service = True

        # 4. COMPUTE FACTOR SCORES (Commercial intent scale 0 to 100)
        # Factor A: Contractor service match (up to 30 pts)
        service_score = 0
        if matched_service is not None:
            service_score = 30
        elif is_ambiguous_service:
            service_score = 10
        elif is_unsupported:
            service_score = 0

        # Factor B: Contact completeness (up to 25 pts)
        contact_score = 0
        if lead.phone and len(lead.phone.strip()) >= 7:
            contact_score += 10
        if lead.first_name and lead.last_name:
            contact_score += 5
        elif lead.first_name or lead.last_name:
            contact_score += 2
        if lead.street_address and lead.postal_code:
            contact_score += 10
        elif lead.postal_code:
            contact_score += 5

        # Factor C: Issue & equipment completeness (up to 25 pts)
        desc_score = 0
        if lead.problem_description and len(lead.problem_description.strip()) >= 20:
            desc_score += 15
        elif lead.problem_description and len(lead.problem_description.strip()) >= 5:
            desc_score += 8
        if lead.equipment_type and len(lead.equipment_type.strip()) > 0:
            desc_score += 10

        # Factor D: Urgency (up to 20 pts)
        urgency = LeadUrgency(lead.urgency) if lead.urgency else LeadUrgency.MEDIUM
        if urgency == LeadUrgency.EMERGENCY:
            urgency_score = 20
        elif urgency == LeadUrgency.HIGH:
            urgency_score = 18
        elif urgency == LeadUrgency.MEDIUM:
            urgency_score = 12
        elif urgency == LeadUrgency.LOW:
            urgency_score = 8
        else:
            urgency_score = 10

        # Note: Messaging consent is recorded in collected_information for routing audit,
        # but does NOT reduce commercial intent score or force COLD status.
        sms_consent = lead.sms_consent_status
        email_consent = lead.email_consent_status

        total_score = contact_score + desc_score + service_score + urgency_score
        total_score = max(0, min(100, total_score))

        collected_information = {
            "contact_score": contact_score,
            "desc_score": desc_score,
            "service_score": service_score,
            "urgency_score": urgency_score,
            "matched_service": matched_service.service_code if matched_service else None,
            "equipment_type": lead.equipment_type,
            "service_type": lead.service_type,
            "postal_code": lead.postal_code,
            "sms_consent_status": sms_consent,
            "email_consent_status": email_consent,
        }

        # 5. DETERMINISTIC CATEGORIZATION
        # Rule: Missing critical contact/problem info -> HUMAN_REVIEW
        if missing_information:
            return QualificationResult(
                organization_id=self.organization_id,
                lead_id=lead.id,
                score=total_score,
                category=QualificationCategory.HUMAN_REVIEW.value,
                reasoning=(
                    f"Critical information missing: {', '.join(missing_information)}. "
                    "Cannot complete automated qualification without complete details."
                ),
                collected_information=collected_information,
                missing_information=missing_information,
                recommended_action="REQUEST_MISSING_DETAILS",
                requires_human=True,
                confidence=0.85,
                created_at=datetime.now(UTC),
            )

        # Rule: Clearly identified unsupported service -> COLD (score capped at 30)
        if is_unsupported:
            return QualificationResult(
                organization_id=self.organization_id,
                lead_id=lead.id,
                score=min(total_score, 30),
                category=QualificationCategory.COLD.value,
                reasoning=(
                    f"Requested service '{lead.service_type}' is not offered in contractor "
                    "active service catalog."
                ),
                collected_information=collected_information,
                missing_information=[],
                recommended_action="DECLINE_UNSUPPORTED_SERVICE",
                requires_human=False,
                confidence=0.95,
                created_at=datetime.now(UTC),
            )

        # Rule: Unknown or ambiguous service request -> HUMAN_REVIEW
        if is_ambiguous_service:
            return QualificationResult(
                organization_id=self.organization_id,
                lead_id=lead.id,
                score=total_score,
                category=QualificationCategory.HUMAN_REVIEW.value,
                reasoning=(
                    "Service request is unknown or ambiguous; requires human review to clarify "
                    "customer needs and match with contractor capabilities."
                ),
                collected_information=collected_information,
                missing_information=["service_type"],
                recommended_action="CLARIFY_SERVICE_REQUIREMENTS",
                requires_human=True,
                confidence=0.85,
                created_at=datetime.now(UTC),
            )

        # Rule: High intent, high urgency, supported service -> HOT (score >= 75)
        if (
            total_score >= 75
            and matched_service is not None
            and urgency
            in (
                LeadUrgency.EMERGENCY,
                LeadUrgency.HIGH,
            )
        ):
            return QualificationResult(
                organization_id=self.organization_id,
                lead_id=lead.id,
                score=total_score,
                category=QualificationCategory.HOT.value,
                reasoning=(
                    "High-intent qualified lead with confirmed service match, "
                    "complete contact details, and urgent timeline."
                ),
                collected_information=collected_information,
                missing_information=[],
                recommended_action="OFFER_APPOINTMENT_SLOTS",
                requires_human=False,
                confidence=0.95,
                created_at=datetime.now(UTC),
            )

        # Rule: Qualified with flexible timing or maintenance -> WARM (score >= 50)
        if total_score >= 50 and matched_service is not None:
            return QualificationResult(
                organization_id=self.organization_id,
                lead_id=lead.id,
                score=total_score,
                category=QualificationCategory.WARM.value,
                reasoning=(
                    "Qualified residential HVAC lead with confirmed service match and "
                    "standard maintenance requirements."
                ),
                collected_information=collected_information,
                missing_information=[],
                recommended_action="NURTURE_OR_SCHEDULE",
                requires_human=False,
                confidence=0.90,
                created_at=datetime.now(UTC),
            )

        # Default low intent / unverified -> COLD
        return QualificationResult(
            organization_id=self.organization_id,
            lead_id=lead.id,
            score=total_score,
            category=QualificationCategory.COLD.value,
            reasoning="Lead score falls below qualification threshold.",
            collected_information=collected_information,
            missing_information=[],
            recommended_action="CLOSE_OR_ARCHIVE",
            requires_human=False,
            confidence=0.85,
            created_at=datetime.now(UTC),
        )

    async def get_latest_result(self, lead_id: uuid.UUID) -> QualificationResult | None:
        """Fetch the most recent qualification evaluation for a lead."""
        await self.lead_repo.get_by_id_or_raise(self.organization_id, lead_id)
        return await self.qualification_repo.get_latest_for_lead(self.organization_id, lead_id)

    async def list_results_for_lead(
        self,
        lead_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[QualificationResult]:
        """List historical evaluations for a lead in reverse chronological order."""
        await self.lead_repo.get_by_id_or_raise(self.organization_id, lead_id)
        return await self.qualification_repo.list_by_lead(
            self.organization_id,
            lead_id,
            limit=limit,
            offset=offset,
        )

    async def resolve_safety_review(
        self,
        lead_id: uuid.UUID,
        authorized_user_id: uuid.UUID | ActorContext,
        resolution_notes: str,
        *,
        new_category: QualificationCategory = QualificationCategory.WARM,
        resolve_active_conversations: bool = False,
    ) -> QualificationResult:
        """Explicitly resolve a safety review for a lead by an authorized human staff member.

        Verifies that:
        1. Lead exists and belongs to the organization.
        2. Lead is genuinely in active QUALIFYING status.
        3. Latest qualification result actually requires human review for a critical safety hazard.
        4. Acting member is active and has role OWNER, ADMIN, or DISPATCHER.
        5. Meaningful resolution notes (>= 5 chars) are supplied.
        6. Lead has no unresolved safety conversations (unless resolve_active_conversations=True).
        7. Persists a new human-resolved QualificationResult (requires_human=False), logs audit
           records, and advances the lead to QUALIFIED status.
        """
        actor_id = (
            authorized_user_id.user_id
            if isinstance(authorized_user_id, ActorContext)
            else authorized_user_id
        )

        membership = await self.membership_repo.get_by_user_id(self.organization_id, actor_id)
        if membership is None or not membership.is_active:
            raise InvalidOperationError(
                f"User '{actor_id}' is not an active member of organization "
                f"'{self.organization_id}'."
            )
        if membership.role not in (
            UserRole.OWNER.value,
            UserRole.ADMIN.value,
            UserRole.DISPATCHER.value,
        ):
            raise InvalidOperationError(
                f"User with role '{membership.role}' is not authorized to resolve safety reviews."
            )

        if not resolution_notes or len(resolution_notes.strip()) < 5:
            raise ValidationError(
                "A detailed resolution note (at least 5 characters) is required to resolve "
                "a safety review."
            )

        lead = await self.lead_repo.get_by_id(self.organization_id, lead_id)
        if lead is None or lead.deleted_at is not None:
            raise EntityNotFoundError("Lead", lead_id)

        # 1. Lead must be genuinely in active QUALIFYING status
        if lead.status != LeadStatus.QUALIFYING.value:
            raise InvalidOperationError(
                f"Cannot resolve safety review for lead with status '{lead.status}'. "
                "Lead must be in QUALIFYING status."
            )

        # 2. Latest evaluation must exist and genuinely require human review for a safety hazard
        latest_qual = await self.qualification_repo.get_latest_for_lead(
            self.organization_id, lead_id
        )
        if latest_qual is None:
            raise InvalidOperationError("Lead has no prior qualification evaluation to resolve.")

        if (
            not latest_qual.requires_human
            or latest_qual.category != QualificationCategory.HUMAN_REVIEW.value
        ):
            raise InvalidOperationError(
                f"Latest evaluation for lead is in category '{latest_qual.category}' "
                "and does not require human review."
            )

        is_safety_hazard = (
            latest_qual.recommended_action == "EMERGENCY_SAFETY_DISPATCH"
            or bool(
                latest_qual.collected_information
                and latest_qual.collected_information.get("safety_hazard")
            )
            or "SAFETY" in (latest_qual.reasoning or "").upper()
        )
        if not is_safety_hazard:
            raise InvalidOperationError(
                "The latest qualification result is not a safety-related emergency review. "
                "Cannot resolve non-safety reviews through the safety resolution pathway."
            )

        # 3. Check for active safety-escalated or reply-locked conversations
        convs = await self.conversation_repo.list_by_lead(self.organization_id, lead_id)
        active_safety_convs = [
            c
            for c in convs
            if c.status == ConversationStatus.ESCALATED_SAFETY.value or c.is_automated_reply_locked
        ]

        if active_safety_convs and not resolve_active_conversations:
            raise InvalidOperationError(
                "Cannot resolve safety review while lead has an active safety-escalated or "
                "reply-locked conversation. Resolve conversation safety escalation first or "
                "specify resolve_active_conversations=True."
            )

        # If resolve_active_conversations is True, resolve each active safety conversation
        if active_safety_convs and resolve_active_conversations:
            for c in active_safety_convs:
                prev_status = c.status
                prev_locked = c.is_automated_reply_locked
                prev_reason = c.escalation_reason

                c.status = ConversationStatus.HUMAN_TAKEOVER.value
                c.is_automated_reply_locked = False
                c.escalation_reason = None

                await self.audit_repo.log_event(
                    self.organization_id,
                    action="SAFETY_ESCALATION_RESOLVED",
                    resource_type="conversation",
                    resource_id=str(c.id),
                    user_id=actor_id,
                    changes={
                        "lead_id": str(lead.id),
                        "previous_status": prev_status,
                        "new_status": ConversationStatus.HUMAN_TAKEOVER.value,
                        "previous_reply_locked": prev_locked,
                        "new_reply_locked": False,
                        "previous_escalation_reason": prev_reason,
                        "resolution_notes": resolution_notes.strip(),
                        "resolved_via": "qualification_safety_review",
                    },
                )

        # 4. Create and persist new resolved QualificationResult (requires_human=False)
        target_category = (
            new_category
            if new_category in (QualificationCategory.HOT, QualificationCategory.WARM)
            else QualificationCategory.WARM
        )
        resolved_score = 85 if target_category == QualificationCategory.HOT else 75

        resolved_result = QualificationResult(
            organization_id=self.organization_id,
            lead_id=lead.id,
            score=resolved_score,
            category=target_category.value,
            reasoning=(
                f"Safety review resolved by authorized staff member: {resolution_notes.strip()}"
            ),
            collected_information={
                "resolved_by": str(actor_id),
                "resolution_notes": resolution_notes.strip(),
                "hazard_cleared": True,
            },
            missing_information=[],
            recommended_action=(
                "OFFER_APPOINTMENT_SLOTS"
                if target_category == QualificationCategory.HOT
                else "NURTURE_OR_SCHEDULE"
            ),
            requires_human=False,
            confidence=1.0,
            created_at=datetime.now(UTC),
        )

        saved = await self.qualification_repo.add(self.organization_id, resolved_result)
        lead.qualification_score = saved.score
        lead.status = LeadStatus.QUALIFIED.value

        # 5. Log immutable audit entry for lead qualification resolution
        await self.audit_repo.log_event(
            self.organization_id,
            action="SAFETY_REVIEW_RESOLVED",
            resource_type="lead",
            resource_id=str(lead.id),
            user_id=actor_id,
            changes={
                "previous_qualification_score": latest_qual.score,
                "new_qualification_score": saved.score,
                "previous_category": latest_qual.category,
                "new_category": target_category.value,
                "previous_lead_status": LeadStatus.QUALIFYING.value,
                "new_lead_status": LeadStatus.QUALIFIED.value,
                "resolution_notes": resolution_notes.strip(),
            },
        )

        await self.flush()
        return saved
