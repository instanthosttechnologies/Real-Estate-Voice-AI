import asyncio
import json
import logging
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional
from app.services.voice.base import (
    AudioFormat,
    AudioOutputPayload,
    ToolUseRequestPayload,
    TranscriptDeltaPayload,
    VoiceDriver,
    VoiceEventType,
    VoiceServerEvent,
)

logger = logging.getLogger("mock_voice_driver")


class MockVoiceDriver(VoiceDriver):
    """
    Mock Voice Driver providing zero-cost, deterministic local testing of real-time voice sessions.
    Simulates speech-to-text, text-to-speech PCM audio generation, LLM reasoning,
    tool invocation requests, and interruption handling without any AWS credentials or cloud calls.
    """

    def __init__(self, model_id: str = "amazon.nova-2-5-sonic"):
        self._model_id = model_id
        self._session_queues: Dict[str, asyncio.Queue] = {}
        self._interrupted_sessions: Dict[str, bool] = {}
        self._session_tools: Dict[str, List[Dict[str, Any]]] = {}
        self._session_preambles: Dict[str, str] = {}

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_id(self) -> str:
        return self._model_id

    def _generate_synthetic_pcm_audio(self, duration_ms: int = 100, sample_rate: int = 24000) -> bytes:
        """Generates a small synthetic 16-bit mono PCM audio chunk representing silence/tone."""
        num_samples = int(sample_rate * (duration_ms / 1000.0))
        # 16-bit mono = 2 bytes per sample
        return b"\x00\x00" * num_samples

    async def start_session(
        self,
        session_id: str,
        prompt_preamble: str,
        tools: List[Dict[str, Any]],
        audio_format: AudioFormat = AudioFormat.PCM_24KHZ_16BIT_MONO,
    ) -> None:
        queue: asyncio.Queue = asyncio.Queue()
        self._session_queues[session_id] = queue
        self._interrupted_sessions[session_id] = False
        self._session_tools[session_id] = tools
        self._session_preambles[session_id] = prompt_preamble

        # 1. Emit SESSION_STARTED
        await queue.put(
            VoiceServerEvent(
                event_type=VoiceEventType.SESSION_STARTED,
                session_id=session_id,
                data={
                    "model_id": self._model_id,
                    "provider": "mock",
                    "audio_format": audio_format.value,
                    "sample_rate": 24000 if audio_format == AudioFormat.PCM_24KHZ_16BIT_MONO else 16000,
                },
            )
        )

        # 2. Emit initial conversational greeting from voice assistant
        greeting = (
            "Hello! I am your AI real estate assistant. I can search properties, "
            "check prices, verify availability, and schedule site visits. How may I help you?"
        )
        await queue.put(
            VoiceServerEvent(
                event_type=VoiceEventType.TRANSCRIPT_DELTA,
                session_id=session_id,
                transcript_payload=TranscriptDeltaPayload(
                    role="assistant",
                    delta=greeting,
                    is_final=True,
                ),
            )
        )
        # Emit greeting synthetic audio
        await queue.put(
            VoiceServerEvent(
                event_type=VoiceEventType.AUDIO_OUTPUT,
                session_id=session_id,
                audio_payload=AudioOutputPayload(
                    audio_bytes=self._generate_synthetic_pcm_audio(duration_ms=200),
                    sample_rate=24000,
                ),
            )
        )

    async def send_audio_chunk(self, session_id: str, audio_bytes: bytes) -> None:
        """Simulates receiving raw user microphone PCM audio and converting to text."""
        if session_id not in self._session_queues:
            logger.warning(f"Audio chunk received for unknown session: {session_id}")
            return

        # In mock mode, if raw audio is streamed without prior text, simulate speech recognition
        # by acknowledging receipt of audio frames
        queue = self._session_queues[session_id]
        if self._interrupted_sessions.get(session_id, False):
            self._interrupted_sessions[session_id] = False

    async def send_text_input(self, session_id: str, text: str) -> None:
        """Processes conversational customer utterances and generates simulated model turns / tool calls."""
        if session_id not in self._session_queues:
            raise ValueError(f"Session {session_id} not initialized.")

        queue = self._session_queues[session_id]
        clean_text = text.strip()

        # 1. Echo user transcript
        await queue.put(
            VoiceServerEvent(
                event_type=VoiceEventType.TRANSCRIPT_DELTA,
                session_id=session_id,
                transcript_payload=TranscriptDeltaPayload(
                    role="user",
                    delta=clean_text,
                    is_final=True,
                ),
            )
        )

        # 2. Check for deterministic test tool triggers: "TEST_TOOL:<tool_name>:<json_args>"
        if clean_text.startswith("TEST_TOOL:"):
            parts = clean_text.split(":", 2)
            tool_name = parts[1]
            args = json.loads(parts[2]) if len(parts) > 2 else {}
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.TOOL_USE_REQUEST,
                    session_id=session_id,
                    tool_request_payload=ToolUseRequestPayload(
                        tool_name=tool_name,
                        tool_use_id=f"mock_call_{uuid.uuid4().hex[:8]}",
                        arguments=args,
                    ),
                )
            )
            return

        # 3. Conversational intent detection for natural simulation
        t = clean_text.lower()
        if any(w in t for w in ["search", "apartment", "flat", "bhk", "villa", "looking for", "property in", "budget"]):
            # Trigger search_properties
            city = None
            for c in ["seattle", "austin", "mumbai", "bengaluru", "denver"]:
                if c in t:
                    city = c.title()
                    break

            config = None
            if "2bhk" in t or "2 bhk" in t:
                config = "2BHK"
            elif "3bhk" in t or "3 bhk" in t:
                config = "3BHK"

            currency = "INR" if any(w in t for w in ["crore", "cr", "lakh", "rs", "inr"]) else "USD"

            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.TOOL_USE_REQUEST,
                    session_id=session_id,
                    tool_request_payload=ToolUseRequestPayload(
                        tool_name="search_properties",
                        tool_use_id=f"mock_call_{uuid.uuid4().hex[:8]}",
                        arguments={
                            "city": city,
                            "configuration_type": config,
                            "currency": currency,
                            "limit": 5,
                        },
                    ),
                )
            )
        elif "price" in t or "cost" in t:
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.TRANSCRIPT_DELTA,
                    session_id=session_id,
                    transcript_payload=TranscriptDeltaPayload(
                        role="assistant",
                        delta="I can certainly retrieve the latest active pricing breakdown. Could you provide the unit ID or property name?",
                        is_final=True,
                    ),
                )
            )
        elif any(w in t for w in ["human", "agent", "broker", "transfer", "representative"]):
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.TOOL_USE_REQUEST,
                    session_id=session_id,
                    tool_request_payload=ToolUseRequestPayload(
                        tool_name="transfer_to_human",
                        tool_use_id=f"mock_call_{uuid.uuid4().hex[:8]}",
                        arguments={
                            "reason": "Customer requested human advisor assistance",
                            "department": "sales",
                        },
                    ),
                )
            )
        else:
            # Default conversational response
            reply = (
                f"I understand your requirement: '{clean_text}'. "
                "Would you like me to search available units in our database or check pricing?"
            )
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.TRANSCRIPT_DELTA,
                    session_id=session_id,
                    transcript_payload=TranscriptDeltaPayload(
                        role="assistant",
                        delta=reply,
                        is_final=True,
                    ),
                )
            )
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.AUDIO_OUTPUT,
                    session_id=session_id,
                    audio_payload=AudioOutputPayload(
                        audio_bytes=self._generate_synthetic_pcm_audio(duration_ms=150),
                    ),
                )
            )

    async def send_tool_result(
        self,
        session_id: str,
        tool_use_id: str,
        result: Dict[str, Any],
        is_error: bool = False,
    ) -> None:
        """Synthesizes grounded conversational response from verified tool execution output."""
        if session_id not in self._session_queues:
            return

        queue = self._session_queues[session_id]

        if is_error:
            reply = f"I apologize, but I encountered an issue: {result.get('error_message', 'Tool execution failed')}."
        else:
            data = result.get("data", {})
            tool_name = result.get("tool_name", "")

            if tool_name == "search_properties":
                props = data if isinstance(data, list) else data.get("properties", [])
                if props:
                    p = props[0]
                    try:
                        price_num = float(p.get("base_price", 0))
                        price_str = f"{price_num:,.0f}"
                    except Exception:
                        price_str = str(p.get("base_price", ""))

                    reply = (
                        f"I found {len(props)} verified properties in our database. "
                        f"For example, {p.get('property_name', 'Tower')} Unit {p.get('unit_number', '')} "
                        f"offers a {p.get('configuration_type', '')} layout at {p.get('currency', '$')} "
                        f"{price_str}. All details come directly from our verified inventory."
                    )
                else:
                    reply = "I checked our live records, but no properties currently match those exact specifications. Would you like to adjust your budget or location?"
            elif tool_name == "book_site_visit":
                reply = (
                    f"Your site visit appointment is successfully confirmed for "
                    f"{data.get('scheduled_start', '')} at {data.get('project_name', 'the project')}. "
                    f"Our sales advisor {data.get('assigned_agent_name', '')} will welcome you."
                )
            elif tool_name in ["transfer_to_human", "request_human_handoff"]:
                reply = (
                    f"I have logged a priority handoff ticket #{data.get('handoff_ticket_id', data.get('ticket_id', 'QUEUED'))}. "
                    "A senior property specialist will follow up with you directly."
                )
            else:
                reply = f"I have executed the request. Details: {json.dumps(data)[:200]}"

        # Emit assistant response
        await queue.put(
            VoiceServerEvent(
                event_type=VoiceEventType.TRANSCRIPT_DELTA,
                session_id=session_id,
                transcript_payload=TranscriptDeltaPayload(
                    role="assistant",
                    delta=reply,
                    is_final=True,
                ),
            )
        )
        await queue.put(
            VoiceServerEvent(
                event_type=VoiceEventType.AUDIO_OUTPUT,
                session_id=session_id,
                audio_payload=AudioOutputPayload(
                    audio_bytes=self._generate_synthetic_pcm_audio(duration_ms=250),
                ),
            )
        )

    async def interrupt(self, session_id: str) -> None:
        """Interrupts assistant speech and drains queued audio."""
        if session_id not in self._session_queues:
            return

        self._interrupted_sessions[session_id] = True
        queue = self._session_queues[session_id]

        # Drain pending audio output events from queue
        remaining_events: List[VoiceServerEvent] = []
        while not queue.empty():
            try:
                evt = queue.get_nowait()
                if evt.event_type != VoiceEventType.AUDIO_OUTPUT:
                    remaining_events.append(evt)
            except asyncio.QueueEmpty:
                break

        for evt in remaining_events:
            await queue.put(evt)

        # Emit INTERRUPTED event
        await queue.put(
            VoiceServerEvent(
                event_type=VoiceEventType.INTERRUPTED,
                session_id=session_id,
                data={"status": "interrupted_by_user"},
            )
        )

    async def end_session(self, session_id: str) -> None:
        if session_id in self._session_queues:
            queue = self._session_queues[session_id]
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.SESSION_ENDED,
                    session_id=session_id,
                )
            )

    async def receive_events(self, session_id: str) -> AsyncIterator[VoiceServerEvent]:
        if session_id not in self._session_queues:
            raise ValueError(f"Session {session_id} not found.")

        queue = self._session_queues[session_id]
        while True:
            evt = await queue.get()
            yield evt
            if evt.event_type == VoiceEventType.SESSION_ENDED:
                break
