"""FastAPI routes for conversation management, messaging, and simulation."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_actor_context, get_current_membership, require_role
from app.core.auth_context import ActorContext
from app.core.database import get_db
from app.core.exceptions import (
    ConsentRequiredError,
    EntityNotFoundError,
    InvalidOperationError,
    ValidationError,
)
from app.core.safety import is_help_keyword, is_opt_out_keyword
from app.integrations.sms import get_sms_sender
from app.models.enums import (
    AutomationEventType,
    ChannelType,
    ConversationStatus,
    DeliveryStatus,
    MessageSender,
    QualificationCategory,
    UserRole,
)
from app.models.membership import OrganizationMembership
from app.models.message import Message
from app.repositories.entities import LeadRepository, QualificationRepository
from app.schemas.conversation import (
    ConversationEscalationRequest,
    ConversationRead,
)
from app.schemas.message import MessageRead
from app.services.conversation_service import ConversationService
from app.services.message_service import MessageService
from app.services.outbox_service import OutboxService
from app.services.qualification_service import QualificationService

router = APIRouter(prefix="/conversations", tags=["Conversations"])


class OutboundMessageRequest(BaseModel):
    message_content: str = Field(..., min_length=1, max_length=10000)
    sender: str = Field(default="staff")


class InboundSimulateRequest(BaseModel):
    message_content: str = Field(..., min_length=1, max_length=10000)
    preset: str | None = None


class AssignRequest(BaseModel):
    user_id: uuid.UUID


class StatusChangeRequest(BaseModel):
    status: str = Field(..., description="Target conversation status")


class SafetyResolutionRequest(BaseModel):
    resolution_notes: str = Field(..., min_length=5, max_length=1000)


class ConversationDetailResponse(ConversationRead):
    lead: dict[str, Any] | None = None
    messages: list[MessageRead] = []
    has_safety_hazard: bool = False


@router.get("", response_model=list[dict[str, Any]])
async def list_conversations(
    membership: Annotated[OrganizationMembership, Depends(get_current_membership)],
    session: Annotated[AsyncSession, Depends(get_db)],
    status: ConversationStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """List conversations for the active organization."""
    conv_service = ConversationService(session, membership.organization_id)
    lead_repo = LeadRepository(session)
    msg_service = MessageService(session, membership.organization_id)

    conversations = await conv_service.list_conversations(
        status=status,
        limit=limit,
        offset=offset,
    )

    results = []
    for conv in conversations:
        lead = await lead_repo.get_by_id(membership.organization_id, conv.lead_id)
        recent_messages = await msg_service.get_message_history(conv.id, limit=1)
        last_msg = recent_messages[0] if recent_messages else None

        results.append(
            {
                "id": str(conv.id),
                "organization_id": str(conv.organization_id),
                "lead_id": str(conv.lead_id),
                "channel": conv.channel,
                "status": conv.status,
                "assigned_to": str(conv.assigned_to) if conv.assigned_to else None,
                "is_automated_reply_locked": conv.is_automated_reply_locked,
                "escalation_reason": conv.escalation_reason,
                "last_message_at": (
                    conv.last_message_at.isoformat() if conv.last_message_at else None
                ),
                "lead": (
                    {
                        "id": str(lead.id),
                        "first_name": lead.first_name,
                        "last_name": lead.last_name,
                        "phone": lead.phone,
                        "email": lead.email,
                        "status": lead.status,
                        "urgency": lead.urgency,
                    }
                    if lead
                    else None
                ),
                "last_message": (
                    {
                        "sender": last_msg.sender,
                        "message_content": last_msg.message_content,
                        "created_at": (
                            last_msg.created_at.isoformat() if last_msg.created_at else None
                        ),
                    }
                    if last_msg
                    else None
                ),
            }
        )

    return results


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: uuid.UUID,
    membership: Annotated[OrganizationMembership, Depends(get_current_membership)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationDetailResponse:
    """Retrieve full conversation details including message history and lead info."""
    conv_service = ConversationService(session, membership.organization_id)
    msg_service = MessageService(session, membership.organization_id)
    lead_repo = LeadRepository(session)

    try:
        conv = await conv_service.get_conversation(conversation_id)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    lead = await lead_repo.get_by_id(membership.organization_id, conv.lead_id)
    messages = await msg_service.get_message_history(conversation_id, limit=100)

    lead_dict = None
    if lead:
        lead_dict = {
            "id": str(lead.id),
            "first_name": lead.first_name,
            "last_name": lead.last_name,
            "phone": lead.phone,
            "email": lead.email,
            "street_address": lead.street_address,
            "postal_code": lead.postal_code,
            "status": lead.status,
            "urgency": lead.urgency,
            "service_type": lead.service_type,
            "problem_description": lead.problem_description,
        }

    return ConversationDetailResponse(
        id=conv.id,
        organization_id=conv.organization_id,
        lead_id=conv.lead_id,
        channel=conv.channel,
        status=conv.status,
        assigned_to=conv.assigned_to,
        is_automated_reply_locked=conv.is_automated_reply_locked,
        escalation_reason=conv.escalation_reason,
        last_message_at=conv.last_message_at,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        lead=lead_dict,
        messages=[MessageRead.model_validate(m) for m in messages],
        has_safety_hazard=conv.is_automated_reply_locked,
    )


@router.post("/{conversation_id}/messages", response_model=MessageRead)
async def send_outbound_message(
    conversation_id: uuid.UUID,
    request: OutboundMessageRequest,
    membership: Annotated[
        OrganizationMembership,
        Depends(require_role([UserRole.OWNER, UserRole.ADMIN, UserRole.DISPATCHER])),
    ],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> MessageRead:
    """Staff sending an outbound message to the customer."""
    msg_service = MessageService(session, membership.organization_id)
    outbox_service = OutboxService(session, membership.organization_id)

    sender_enum = (
        MessageSender.HUMAN_AGENT
        if request.sender.lower() in ("staff", "human_agent")
        else MessageSender.AI_AGENT
    )

    try:
        conv_service = ConversationService(session, membership.organization_id)
        lead_repo = LeadRepository(session)

        msg = await msg_service.create_outbound_message(
            conversation_id,
            request.message_content,
            sender=sender_enum,
        )

        # Dispatch via configured SMS sender (Twilio when configured, Simulated by default)
        conv = await conv_service.get_conversation(conversation_id)
        lead = await lead_repo.get_by_id(membership.organization_id, conv.lead_id)
        if conv.channel == ChannelType.SMS.value and lead is not None:
            sms_res = await get_sms_sender().send_sms(
                to_phone=lead.phone,
                body=msg.message_content,
            )
            if sms_res.external_message_id:
                msg.external_message_id = sms_res.external_message_id
            await msg_service.update_delivery_status(
                msg.id,
                DeliveryStatus.SENT if sms_res.success else DeliveryStatus.FAILED,
                metadata={
                    **sms_res.metadata,
                    **({"error": sms_res.error_message} if sms_res.error_message else {}),
                },
            )

        # Publish MESSAGE_SENT outbox event
        await outbox_service.publish_event(
            event_type=AutomationEventType.MESSAGE_SENT,
            aggregate_id=msg.id,
            aggregate_type="Message",
            payload={
                "message_id": str(msg.id),
                "conversation_id": str(conversation_id),
                "sender": msg.sender,
                "delivery_status": msg.delivery_status,
                "content_preview": msg.message_content[:100],
            },
        )

        await session.commit()
        await session.refresh(msg)
        return MessageRead.model_validate(msg)
    except ConsentRequiredError as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except (ValidationError, InvalidOperationError) as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except EntityNotFoundError as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/{conversation_id}/simulate-inbound")
async def simulate_inbound_customer_message(
    conversation_id: uuid.UUID,
    request: InboundSimulateRequest,
    membership: Annotated[
        OrganizationMembership,
        Depends(require_role([UserRole.OWNER, UserRole.ADMIN, UserRole.DISPATCHER])),
    ],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Simulate an incoming customer SMS message for testing or demonstration."""
    msg_service = MessageService(session, membership.organization_id)
    conv_service = ConversationService(session, membership.organization_id)
    outbox_service = OutboxService(session, membership.organization_id)

    try:
        prev_conv = await conv_service.get_conversation(conversation_id)
        was_locked = prev_conv.is_automated_reply_locked

        inbound_msg = await msg_service.store_inbound_message(
            conversation_id,
            request.message_content,
        )

        # Check updated conversation state
        conv = await conv_service.get_conversation(conversation_id)

        safety_triggered = conv.is_automated_reply_locked
        opt_out_triggered = is_opt_out_keyword(request.message_content)
        help_triggered = is_help_keyword(request.message_content)
        ai_reply_generated = False
        ai_reply_content = None

        if safety_triggered and not was_locked:
            # Record immediate emergency safety advisory instructing evacuation & 911
            advisory = Message(
                organization_id=membership.organization_id,
                conversation_id=conv.id,
                sender=MessageSender.SYSTEM.value,
                message_content=(
                    "SAFETY WARNING (Simulated): Potential life-safety hazard detected. "
                    "Please leave the building immediately and call 911 or your local gas/electric "
                    "utility from a safe location. Automated replies are now locked."
                ),
                delivery_status=DeliveryStatus.DELIVERED.value,
            )
            session.add(advisory)
            await session.flush()

            await outbox_service.publish_event(
                event_type=AutomationEventType.SAFETY_ESCALATED,
                aggregate_id=conv.id,
                aggregate_type="Conversation",
                payload={
                    "conversation_id": str(conv.id),
                    "lead_id": str(conv.lead_id),
                    "reason": conv.escalation_reason or "SAFETY_HAZARD",
                },
            )

        if opt_out_triggered:
            conv.status = ConversationStatus.CLOSED.value
            await session.flush()

        # If not safety locked, not opt-out, and conversation is AI_ACTIVE,
        # generate simulated AI reply
        if (
            not safety_triggered
            and not opt_out_triggered
            and conv.status == ConversationStatus.AI_ACTIVE.value
        ):
            text_lower = request.message_content.lower()
            if help_triggered:
                ai_reply_content = (
                    "Apex Air HVAC Support (Simulated): Reply with your HVAC issue for assistance, "
                    "or reply STOP to opt out of SMS updates. For gas leaks or CO alarms, "
                    "evacuate immediately and call 911."
                )
            elif any(k in text_lower for k in ["ac", "cool", "heat", "furnace", "leak", "noise"]):
                ai_reply_content = (
                    "Thank you for contacting Apex Air! We understand how important "
                    "comfort is. Could you confirm your home address and if you need service today?"
                )
            elif any(k in text_lower for k in ["cost", "price", "quote", "rate"]):
                ai_reply_content = (
                    "Our diagnostic visit is $89, which is credited toward repairs if you "
                    "move forward with our technician. Would morning or afternoon work best?"
                )
            elif any(k in text_lower for k in ["tune", "maintenance", "check"]):
                ai_reply_content = (
                    "We offer complete 21-point HVAC system tune-ups. What type of "
                    "system do you have (heat pump, gas furnace, or central AC)?"
                )
            else:
                ai_reply_content = (
                    "Thank you for reaching out! Our dispatch team has received your details. "
                    "Is there a preferred time of day for a service visit?"
                )

            try:
                ai_msg = await msg_service.create_outbound_message(
                    conversation_id,
                    ai_reply_content,
                    sender=MessageSender.AI_AGENT,
                )
                ai_reply_generated = True

                lead = await LeadRepository(session).get_by_id(
                    membership.organization_id, conv.lead_id
                )
                if conv.channel == ChannelType.SMS.value and lead is not None:
                    sms_res = await get_sms_sender().send_sms(
                        to_phone=lead.phone,
                        body=ai_msg.message_content,
                    )
                    if sms_res.external_message_id:
                        ai_msg.external_message_id = sms_res.external_message_id
                    await msg_service.update_delivery_status(
                        ai_msg.id,
                        DeliveryStatus.SENT if sms_res.success else DeliveryStatus.FAILED,
                        metadata=sms_res.metadata,
                    )

                await outbox_service.publish_event(
                    event_type=AutomationEventType.MESSAGE_SENT,
                    aggregate_id=ai_msg.id,
                    aggregate_type="Message",
                    payload={"message_id": str(ai_msg.id), "sender": ai_msg.sender},
                )
            except ConsentRequiredError:
                ai_reply_content = None
                ai_reply_generated = False

        await session.commit()

        return {
            "status": "success",
            "inbound_message": MessageRead.model_validate(inbound_msg).model_dump(mode="json"),
            "safety_escalation_triggered": safety_triggered,
            "opt_out_triggered": opt_out_triggered,
            "help_triggered": help_triggered,
            "conversation_status": conv.status,
            "is_automated_reply_locked": conv.is_automated_reply_locked,
            "ai_reply_generated": ai_reply_generated,
            "ai_reply_content": ai_reply_content,
        }
    except (ValidationError, InvalidOperationError) as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except EntityNotFoundError as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/{conversation_id}/assign")
async def assign_conversation(
    conversation_id: uuid.UUID,
    request: AssignRequest,
    membership: Annotated[
        OrganizationMembership,
        Depends(require_role([UserRole.OWNER, UserRole.ADMIN, UserRole.DISPATCHER])),
    ],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Assign a conversation to a staff member."""
    conv_service = ConversationService(session, membership.organization_id)
    try:
        conv = await conv_service.assign_conversation(conversation_id, request.user_id)
        await session.commit()
        return {
            "success": True,
            "conversation_id": str(conv.id),
            "assigned_to": str(conv.assigned_to) if conv.assigned_to else None,
        }
    except (ValidationError, EntityNotFoundError) as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{conversation_id}/status")
async def change_conversation_status(
    conversation_id: uuid.UUID,
    request: StatusChangeRequest,
    membership: Annotated[
        OrganizationMembership,
        Depends(require_role([UserRole.OWNER, UserRole.ADMIN, UserRole.DISPATCHER])),
    ],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Transition conversation status."""
    conv_service = ConversationService(session, membership.organization_id)
    try:
        target_status = ConversationStatus(request.status)
        conv = await conv_service.change_status(conversation_id, target_status)
        await session.commit()
        return {"success": True, "conversation_id": str(conv.id), "status": conv.status}
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status: {request.status}",
        )
    except (ValidationError, InvalidOperationError) as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{conversation_id}/escalate")
async def escalate_conversation(
    conversation_id: uuid.UUID,
    request: ConversationEscalationRequest,
    membership: Annotated[
        OrganizationMembership,
        Depends(require_role([UserRole.OWNER, UserRole.ADMIN, UserRole.DISPATCHER])),
    ],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Manually escalate conversation to a human dispatcher."""
    conv_service = ConversationService(session, membership.organization_id)
    try:
        conv = await conv_service.escalate_conversation(
            conversation_id,
            reason=request.escalation_reason,
            lock_automated_reply=request.lock_automated_reply,
        )
        await session.commit()
        return {
            "success": True,
            "conversation_id": str(conv.id),
            "status": conv.status,
            "is_automated_reply_locked": conv.is_automated_reply_locked,
        }
    except (ValidationError, InvalidOperationError) as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{conversation_id}/resolve-safety")
async def resolve_safety_escalation(
    conversation_id: uuid.UUID,
    request: SafetyResolutionRequest,
    membership: Annotated[
        OrganizationMembership,
        Depends(require_role([UserRole.OWNER, UserRole.ADMIN, UserRole.DISPATCHER])),
    ],
    actor_ctx: Annotated[ActorContext, Depends(get_actor_context)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Resolve an emergency safety lock on a conversation. Requires supervisor note."""
    conv_service = ConversationService(session, membership.organization_id)
    qual_repo = QualificationRepository(session)
    qual_service = QualificationService(session, membership.organization_id)

    try:
        conv = await conv_service.get_conversation(conversation_id)
        latest_qual = await qual_repo.get_latest_for_lead(membership.organization_id, conv.lead_id)

        if latest_qual is not None and (
            latest_qual.requires_human
            or latest_qual.category == QualificationCategory.HUMAN_REVIEW.value
        ):
            is_safety_qual = (
                latest_qual.recommended_action in ("EMERGENCY_SAFETY_DISPATCH", "ESCALATE_SAFETY")
                or bool(
                    latest_qual.collected_information
                    and latest_qual.collected_information.get("safety_hazard")
                )
                or "SAFETY" in (latest_qual.reasoning or "").upper()
            )
            if is_safety_qual:
                await qual_service.resolve_safety_review(
                    conv.lead_id,
                    actor_ctx,
                    request.resolution_notes,
                    resolve_active_conversations=True,
                )
                conv = await conv_service.get_conversation(conversation_id)
            else:
                conv = await conv_service.resolve_safety_escalation(
                    conversation_id,
                    actor_ctx,
                    request.resolution_notes,
                )
        else:
            conv = await conv_service.resolve_safety_escalation(
                conversation_id,
                actor_ctx,
                request.resolution_notes,
            )

        await session.commit()
        return {
            "success": True,
            "conversation_id": str(conv.id),
            "status": conv.status,
            "is_automated_reply_locked": conv.is_automated_reply_locked,
        }
    except (ValidationError, InvalidOperationError) as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except EntityNotFoundError as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
