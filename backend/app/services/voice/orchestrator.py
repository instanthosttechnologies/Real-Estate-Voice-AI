import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.config import settings
from app.core.security import decrypt_transcript, encrypt_transcript
from app.models.audit_log import AuditLog
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.lead import Lead
from app.models.site_visit import SiteVisit
from app.services.agent.dispatcher import dispatch_agent_tool
from app.services.voice.base import (
    AudioFormat,
    VoiceDriver,
    VoiceEventType,
    VoiceServerEvent,
)
from app.services.voice.tools_spec import get_agent_tools_spec
from app.services.voice.session_state import SessionState
from app.services.real_estate.requirements import ExtractedCustomerRequirements

logger = logging.getLogger("voice_orchestrator")


class DryRunSessionProxy:
    """
    Wraps an active SQLAlchemy Session for DRY_RUN_TEST_MODE.
    All db.commit() calls are safely converted to db.flush() so that in-session
    entity IDs and relationships are generated and visible to subsequent multi-turn
    tool executions, but NO changes are ever committed to the persistent database.
    Upon session completion or rollback, all in-memory changes are discarded.
    """

    def __init__(self, session: Session):
        self._session = session

    def commit(self) -> None:
        logger.info("[DRY_RUN_TEST_MODE] Intercepted db.commit() -> executing db.flush() instead (no persistent write).")
        self._session.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)


class VoiceSessionOrchestrator:
    """
    Coordinates real-time voice conversations:
    - Mediates between the WebSocket connection and the VoiceDriver (Mock or Amazon Nova 2.5 Sonic).
    - Intercepts and executes agent tool use calls strictly through the validated Phase 2 dispatcher.
    - Accumulates conversational turns and persists AES-256-GCM encrypted transcripts.
    - Enforces backpressure, frame size limits, session ownership, and audit logging.
    """

    MAX_AUDIO_CHUNK_BYTES = 65536  # 64 KB per binary audio frame

    def __init__(
        self,
        session_id: str,
        driver: VoiceDriver,
        db: Session,
        customer_id: Optional[uuid.UUID] = None,
        user_role: str = "customer",
        user_id: Optional[uuid.UUID] = None,
        is_verified: bool = False,
    ):
        self.session_id = session_id
        self.driver = driver
        if getattr(settings, "DRY_RUN_TEST_MODE", False):
            self.db = DryRunSessionProxy(db)
        else:
            self.db = db
        self.customer_id = customer_id
        self.user_role = user_role
        self.user_id = user_id
        self.is_verified = is_verified

        self.start_time: datetime = datetime.now(timezone.utc)
        self.end_time: Optional[datetime] = None
        self.is_active: bool = False
        self.conversation_priority: str = "medium"

        self.transcript_entries: List[str] = []
        self._audio_queue: asyncio.Queue = asyncio.Queue(maxsize=100)  # Bounded backpressure queue

        # Multi-turn customer requirement memory and session state
        self.session_state = SessionState(
            session_id=self.session_id,
            customer_id=self.customer_id,
            user_id=self.user_id,
            user_role=self.user_role,
        )

    def _build_system_preamble(self, returning_context: Optional[str] = None) -> str:
        preamble = (
            "You are an expert, professional, and courteous Real Estate Voice AI Advisor. "
            "Your objective is to understand customer preferences (location, configuration, budget, currency, amenities), "
            "search genuine database inventory, verify live pricing and unit availability, and schedule site visits. "
            "\n\nSTRICT ANTI-HALLUCINATION RULES:\n"
            "1. NEVER invent property prices, availability, or configurations. "
            "Always call the designated database tools to retrieve authentic property records.\n"
            "2. Currencies must never be silently converted (e.g. USD vs INR). Support explicit ISO currencies.\n"
            "3. Site visits must only be scheduled within project operating hours (09:00 - 18:00 project local time).\n"
            "4. Human handoff creates a priority callback ticket; never claim an active phone transfer is ringing.\n"
            "5. Speak concisely in a natural, friendly tone suitable for voice conversations."
        )
        if returning_context:
            preamble += f"\n\nRETURNING CUSTOMER CONTEXT:\n{returning_context}"
        return preamble

    async def start(self) -> None:
        """Initializes the voice session with the underlying driver and pre-seeds returning customer context."""
        self.is_active = True
        returning_context = None

        # Task 4: Retrieve customer's saved preferences & scheduled visits upon session start
        if self.customer_id:
            cust = self.db.execute(
                select(Customer).where(Customer.id == self.customer_id)
            ).scalar_one_or_none()

            if cust:
                # Customer ownership check: If caller has customer role, prevent cross-customer access
                if self.user_role == "customer" and self.user_id and cust.user_id and cust.user_id != self.user_id:
                    logger.warning(
                        f"Access violation: User {self.user_id} attempted unauthorized access to customer {self.customer_id}"
                    )
                elif self.user_role == "customer" and not self.is_verified:
                    # Critical Anti-Information Disclosure: Unverified customer sessions start clean!
                    # Do not pre-seed previous leads, preferences, or scheduled site visits.
                    returning_context = (
                        f"Customer Name: {cust.full_name}\n"
                        "Note: Unverified session. Treat as a fresh conversation. "
                        "Do not disclose or reference prior private bookings or unverified history."
                    )
                else:
                    # Query latest CRM lead preferences
                    latest_lead = self.db.execute(
                        select(Lead)
                        .where(Lead.customer_id == self.customer_id)
                        .order_by(Lead.created_at.desc())
                    ).scalars().first()

                    # Query scheduled site visits
                    active_visits = self.db.execute(
                        select(SiteVisit)
                        .where(
                            SiteVisit.customer_id == self.customer_id,
                            SiteVisit.status.in_(["scheduled", "rescheduled"]),
                        )
                        .order_by(SiteVisit.scheduled_start.asc())
                    ).scalars().all()

                    ctx_parts = [f"Customer Name: {cust.full_name}"]
                    if latest_lead:
                        self.session_state.saved_requirements_from_profile = {
                            "preferred_config": latest_lead.preferred_config,
                            "preferred_location": latest_lead.preferred_location,
                            "budget_min": float(latest_lead.budget_min) if latest_lead.budget_min else None,
                            "budget_max": float(latest_lead.budget_max) if latest_lead.budget_max else None,
                            "qualification_status": latest_lead.qualification_status,
                            "lead_priority": latest_lead.lead_priority,
                        }
                        # Pre-seed session state requirements
                        preseeded = ExtractedCustomerRequirements(
                            preferred_location=latest_lead.preferred_location,
                            configuration_type=latest_lead.preferred_config,
                            budget_min=latest_lead.budget_min,
                            budget_max=latest_lead.budget_max,
                            currency="INR" if latest_lead.budget_max else None,
                        )
                        self.session_state.update_requirements(preseeded)

                        lead_details = []
                        if latest_lead.preferred_config:
                            lead_details.append(f"Configuration: {latest_lead.preferred_config}")
                        if latest_lead.preferred_location:
                            lead_details.append(f"Location: {latest_lead.preferred_location}")
                        if latest_lead.budget_max:
                            lead_details.append(f"Max Budget: {latest_lead.budget_max}")
                        if lead_details:
                            ctx_parts.append(f"Saved Preferences: {', '.join(lead_details)}")

                    if active_visits:
                        visit_lines = [
                            f"Site visit on {v.scheduled_start.strftime('%Y-%m-%d %H:%M')} (Status: {v.status})"
                            for v in active_visits
                        ]
                        ctx_parts.append(f"Scheduled Site Visits: {'; '.join(visit_lines)}")

                    ctx_parts.append(
                        "Guidance: Acknowledge the customer's prior profile and preferences warmly. "
                        "Do not read raw database IDs or financial metrics awkwardly."
                    )
                    returning_context = "\n".join(ctx_parts)

        tools_spec = get_agent_tools_spec()
        preamble = self._build_system_preamble(returning_context=returning_context)

        await self.driver.start_session(
            session_id=self.session_id,
            prompt_preamble=preamble,
            tools=tools_spec,
            audio_format=AudioFormat.PCM_24KHZ_16BIT_MONO,
        )

        # Audit log
        self._record_audit_log(
            action="VOICE_SESSION_STARTED",
            resource_type="voice_session",
            resource_id=self.session_id,
            meta_info={
                "model_id": self.driver.model_id,
                "provider": self.driver.provider_name,
                "customer_id": str(self.customer_id) if self.customer_id else None,
            },
        )

    async def handle_incoming_audio(self, audio_bytes: bytes) -> None:
        """Validates and processes incoming audio frames from client."""
        if not self.is_active:
            raise RuntimeError("Cannot stream audio to an inactive voice session.")

        if len(audio_bytes) > self.MAX_AUDIO_CHUNK_BYTES:
            raise ValueError(f"Audio frame exceeds maximum chunk limit ({len(audio_bytes)} > {self.MAX_AUDIO_CHUNK_BYTES}).")

        await self.driver.send_audio_chunk(self.session_id, audio_bytes)

    async def handle_incoming_text(self, text: str) -> None:
        """Handles textual user messages."""
        if not self.is_active:
            raise RuntimeError("Cannot process text in an inactive voice session.")

        self.transcript_entries.append(f"[Customer]: {text.strip()}")
        await self.driver.send_text_input(self.session_id, text)

    async def handle_interruption(self) -> None:
        """Handles user interruption event."""
        logger.info(f"User interrupted session {self.session_id}")
        await self.driver.interrupt(self.session_id)
        self._record_audit_log(
            action="VOICE_SESSION_INTERRUPTED",
            resource_type="voice_session",
            resource_id=self.session_id,
            meta_info={"timestamp": datetime.now(timezone.utc).isoformat()},
        )

    async def run_pipeline(
        self,
        send_text: Callable[[str], Coroutine[Any, Any, None]],
        send_bytes: Callable[[bytes], Coroutine[Any, Any, None]],
    ) -> None:
        """
        Consumes events from the voice driver, routes tool requests through the Phase 2 dispatcher,
        and streams audio/transcript deltas to the client.
        """
        try:
            async for evt in self.driver.receive_events(self.session_id):
                if not self.is_active:
                    break

                if evt.event_type == VoiceEventType.SESSION_STARTED:
                    await send_text(
                        json.dumps({
                            "type": "session_started",
                            "session_id": self.session_id,
                            "model": self.driver.model_id,
                            "provider": self.driver.provider_name,
                        })
                    )

                elif evt.event_type == VoiceEventType.AUDIO_OUTPUT and evt.audio_payload:
                    # Stream raw audio bytes to client
                    await send_bytes(evt.audio_payload.audio_bytes)

                elif evt.event_type == VoiceEventType.TRANSCRIPT_DELTA and evt.transcript_payload:
                    payload = evt.transcript_payload
                    role_label = "Assistant" if payload.role == "assistant" else "Customer"
                    if payload.is_final:
                        self.transcript_entries.append(f"[{role_label}]: {payload.delta}")

                    await send_text(
                        json.dumps({
                            "type": "transcript",
                            "role": payload.role,
                            "delta": payload.delta,
                            "is_final": payload.is_final,
                        })
                    )

                elif evt.event_type == VoiceEventType.TOOL_USE_REQUEST and evt.tool_request_payload:
                    tool_req = evt.tool_request_payload
                    logger.info(f"Voice session {self.session_id} executing tool: {tool_req.tool_name}")

                    # Multi-turn context enrichment before execution
                    if tool_req.tool_name == "extract_requirements":
                        if not tool_req.arguments.get("existing_requirements"):
                            active_req_dict = self.session_state.requirements.model_dump()
                            if any(v is not None and v != [] for v in active_req_dict.values()):
                                tool_req.arguments["existing_requirements"] = active_req_dict
                    elif tool_req.tool_name == "search_properties":
                        active_req = self.session_state.requirements
                        if not tool_req.arguments.get("city") and active_req.preferred_city:
                            tool_req.arguments["city"] = active_req.preferred_city
                        if not tool_req.arguments.get("configuration_type") and active_req.configuration_type:
                            tool_req.arguments["configuration_type"] = active_req.configuration_type
                        if not tool_req.arguments.get("max_budget") and active_req.budget_max:
                            tool_req.arguments["max_budget"] = float(active_req.budget_max)
                        if not tool_req.arguments.get("min_budget") and active_req.budget_min:
                            tool_req.arguments["min_budget"] = float(active_req.budget_min)
                        if not tool_req.arguments.get("preferred_amenities") and active_req.desired_amenities:
                            tool_req.arguments["preferred_amenities"] = active_req.desired_amenities

                    # Notify client of tool execution
                    await send_text(
                        json.dumps({
                            "type": "tool_call_start",
                            "tool_name": tool_req.tool_name,
                            "tool_use_id": tool_req.tool_use_id,
                        })
                    )
                    self.transcript_entries.append(
                        f"[Tool Call Request: {tool_req.tool_name}] args: {json.dumps(tool_req.arguments)}"
                    )

                    # Intercept and execute strictly via Phase 2 agent dispatcher
                    tool_resp = dispatch_agent_tool(
                        db=self.db,
                        tool_name=tool_req.tool_name,
                        raw_arguments=tool_req.arguments,
                    )

                    # Multi-turn state tracking upon successful tool execution
                    if tool_resp.success and tool_resp.data:
                        if tool_req.tool_name == "extract_requirements":
                            try:
                                extracted_obj = ExtractedCustomerRequirements(**tool_resp.data)
                                self.session_state.update_requirements(extracted_obj)
                            except Exception as parse_err:
                                logger.warning(f"Could not update session state requirements: {parse_err}")

                        elif tool_req.tool_name == "search_properties":
                            self.session_state.last_search_criteria = tool_req.arguments
                            props = tool_resp.data.get("properties") or []
                            for p in props:
                                uid_str = p.get("unit_id")
                                if uid_str:
                                    try:
                                        uid = uuid.UUID(uid_str)
                                        if uid not in self.session_state.viewed_properties:
                                            self.session_state.viewed_properties.append(uid)
                                    except Exception:
                                        pass

                        elif tool_req.tool_name == "compare_properties":
                            items = tool_resp.data.get("comparison_items") or []
                            for it in items:
                                uid_str = it.get("unit_id")
                                if uid_str:
                                    try:
                                        uid = uuid.UUID(uid_str)
                                        if uid not in self.session_state.compared_properties:
                                            self.session_state.compared_properties.append(uid)
                                    except Exception:
                                        pass

                        elif tool_req.tool_name == "book_site_visit":
                            visit_id_str = tool_resp.data.get("visit_id")
                            if visit_id_str:
                                try:
                                    self.session_state.booked_visit_id = uuid.UUID(visit_id_str)
                                except Exception:
                                    pass

                    # Record audit event for tool execution
                    self._record_audit_log(
                        action="VOICE_TOOL_EXECUTED",
                        resource_type="agent_tool",
                        resource_id=tool_req.tool_name,
                        meta_info={
                            "session_id": self.session_id,
                            "tool_use_id": tool_req.tool_use_id,
                            "success": tool_resp.success,
                        },
                    )

                    # Check priority elevation if human transfer requested
                    if tool_req.tool_name in ["transfer_to_human", "request_human_handoff"]:
                        self.conversation_priority = "urgent"

                    self.transcript_entries.append(
                        f"[Tool Call Result: {tool_req.tool_name}] success={tool_resp.success}, data={json.dumps(tool_resp.data, default=str)[:300]}"
                    )

                    await send_text(
                        json.dumps({
                            "type": "tool_call_complete",
                            "tool_name": tool_req.tool_name,
                            "tool_use_id": tool_req.tool_use_id,
                            "success": tool_resp.success,
                            "anti_hallucination_guidance": tool_resp.anti_hallucination_guidance,
                        })
                    )

                    # Stream tool result back to driver
                    await self.driver.send_tool_result(
                        session_id=self.session_id,
                        tool_use_id=tool_req.tool_use_id,
                        result=tool_resp.model_dump(mode="json"),
                        is_error=not tool_resp.success,
                    )

                elif evt.event_type == VoiceEventType.INTERRUPTED:
                    await send_text(json.dumps({"type": "interrupted"}))

                elif evt.event_type == VoiceEventType.SESSION_ENDED:
                    break

        except asyncio.CancelledError:
            logger.info(f"Pipeline cancelled for session {self.session_id}")
        except Exception as exc:
            logger.error(f"Error in pipeline for session {self.session_id}: {exc}")
            await send_text(json.dumps({"type": "error", "message": str(exc)}))
        finally:
            await self.close()

    async def close(self) -> None:
        """Closes the session, encrypts the transcript, and updates database records."""
        if not self.is_active:
            return

        self.is_active = False
        self.end_time = datetime.now(timezone.utc)
        duration = int((self.end_time - self.start_time).total_seconds())

        await self.driver.end_session(self.session_id)

        # 1. Check existing conversation for ownership and historical transcript preservation
        conv = self.db.execute(
            select(Conversation).where(Conversation.session_id == self.session_id)
        ).scalar_one_or_none()

        if conv and self.user_role == "customer" and conv.customer_id is not None and conv.customer_id != self.customer_id:
            logger.error(
                f"Unauthorized update attempt: Customer {self.customer_id} tried to overwrite session {self.session_id} "
                f"owned by {conv.customer_id}"
            )
            return

        new_transcript_block = "\n".join(self.transcript_entries)
        if conv and conv.encrypted_transcript:
            try:
                prev_transcript = decrypt_transcript(conv.encrypted_transcript)
                full_transcript = f"{prev_transcript}\n{new_transcript_block}".strip() if new_transcript_block else prev_transcript
            except Exception as e:
                logger.warning(f"Could not decrypt previous transcript for session {self.session_id}: {e}")
                full_transcript = new_transcript_block
        else:
            full_transcript = new_transcript_block

        # 2. Encrypt transcript with AES-256-GCM
        encrypted_transcript_payload = encrypt_transcript(full_transcript) if full_transcript else None

        # 3. Persist or update Conversation database record (unless DRY_RUN_TEST_MODE is enabled)
        if getattr(settings, "DRY_RUN_TEST_MODE", False):
            logger.info(
                f"[DRY_RUN_TEST_MODE] Active for session {self.session_id}: "
                "Rolling back all transactional changes and skipping persistent writes."
            )
            try:
                self.db.rollback()
            except Exception as rb_err:
                logger.warning(f"Rollback error in dry-run mode: {rb_err}")
            self.session_state.reset()
            return

        if not conv:
            conv = Conversation(
                session_id=self.session_id,
                customer_id=self.customer_id,
                duration_seconds=max(0, duration),
                conversation_priority=self.conversation_priority,
                encrypted_transcript=encrypted_transcript_payload,
            )
            self.db.add(conv)
        else:
            conv.duration_seconds = (conv.duration_seconds or 0) + max(0, duration)
            conv.conversation_priority = self.conversation_priority
            conv.encrypted_transcript = encrypted_transcript_payload

        self.db.commit()

        # 4. Record session completion audit event
        self._record_audit_log(
            action="VOICE_SESSION_COMPLETED",
            resource_type="conversation",
            resource_id=str(conv.id),
            meta_info={
                "session_id": self.session_id,
                "duration_seconds": duration,
                "turns_count": len(self.transcript_entries),
                "priority": self.conversation_priority,
                "encrypted": encrypted_transcript_payload is not None,
            },
        )

        # 5. Clean up session state memory safely
        self.session_state.reset()

    def _record_audit_log(
        self,
        action: str,
        resource_type: str,
        resource_id: str,
        meta_info: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Records an immutable audit event for voice actions."""
        if getattr(settings, "DRY_RUN_TEST_MODE", False):
            logger.debug(f"[DRY_RUN_TEST_MODE] Skipping audit log database write for {action}")
            return

        try:
            audit = AuditLog(
                user_id=self.user_id,
                user_role=self.user_role,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                meta_info=meta_info or {},
                timestamp=datetime.now(timezone.utc),
            )
            self.db.add(audit)
            self.db.commit()
        except Exception as exc:
            logger.error(f"Failed to record audit log for session {self.session_id}: {exc}")
            self.db.rollback()
