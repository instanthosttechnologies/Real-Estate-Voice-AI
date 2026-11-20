import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

from app.core.config import settings
from app.services.voice.base import (
    AudioFormat,
    AudioOutputPayload,
    ToolUseRequestPayload,
    TranscriptDeltaPayload,
    VoiceDriver,
    VoiceEventType,
    VoiceServerEvent,
)
from app.services.voice.bedrock_streaming import (
    BedrockCRTStreamTransport,
    BedrockNovaSonicParser,
    BedrockNovaSonicSerializer,
    BedrockStreamConnection,
    BedrockStreamTransport,
)

logger = logging.getLogger("amazon_nova_sonic_driver")


class AmazonNovaSonicDriver(VoiceDriver):
    """
    Production driver for Amazon Nova 2.5 Sonic (model ID: amazon.nova-2-5-sonic)
    via Amazon Bedrock bidirectional EventStream runtime.
    
    Architectural Guarantees:
    - Never executes direct database operations. Tool use requests are emitted to the orchestrator.
    - Adheres to Bedrock streaming event protocols (sessionStart, promptStart, audioInput, toolResult).
    - Encapsulates bidirectional streaming connection lifecycle over HTTP/2 duplex transport.
    - Preserves VoiceDriver interface contract with graceful fallback for offline development.
    - Safe Preflight Controls: Enforces concurrency ceiling and short session limit for live tests.
    """

    # Enforce safe short session ceiling (configurable via settings, default 60s for preflight/live tests)
    MAX_SESSION_DURATION_SECONDS = getattr(settings, "LIVE_TEST_MAX_SESSION_SECONDS", 60)
    _active_live_session_ids: set = set()

    @classmethod
    def release_session(cls, session_id: str) -> None:
        """Guaranteed idempotent release of the active live session concurrency slot."""
        if session_id in cls._active_live_session_ids:
            cls._active_live_session_ids.discard(session_id)
            logger.info(
                f"[NovaSonicDriver] Released session slot {session_id}. "
                f"Remaining active: {len(cls._active_live_session_ids)}"
            )

    def __init__(
        self,
        model_id: str = "amazon.nova-2-5-sonic",
        region_name: Optional[str] = None,
        profile_name: Optional[str] = None,
        transport: Optional[BedrockStreamTransport] = None,
    ):
        self._model_id = model_id or getattr(settings, "BEDROCK_MODEL_ID", "amazon.nova-2-5-sonic")
        self._region_name = region_name or settings.AWS_REGION
        self._profile_name = profile_name or getattr(settings, "AWS_PROFILE", None)
        # Prefer AWS's generated SDK for SigV4 and EventStream framing.
        # Injected test transports are preserved unchanged.
        if transport is not None:
            self._transport = transport
        else:
            from app.services.voice.sdk_transport import BedrockSDKStreamTransport
            self._transport = BedrockSDKStreamTransport(profile_name=self._profile_name)
        self._session_queues: Dict[str, asyncio.Queue] = {}
        self._active_sessions: Dict[str, Dict[str, Any]] = {}

    @property
    def provider_name(self) -> str:
        return "amazon_nova_sonic"

    @property
    def model_id(self) -> str:
        return self._model_id

    async def start_session(
        self,
        session_id: str,
        prompt_preamble: str,
        tools: List[Dict[str, Any]],
        audio_format: AudioFormat = AudioFormat.PCM_24KHZ_16BIT_MONO,
    ) -> None:
        """
        Initializes a bidirectional streaming session with Amazon Nova 2.5 Sonic:
        1. Checks concurrency limit for live sessions.
        2. Opens the duplex HTTP/2 transport connection.
        3. Sends sessionStart with inference parameters.
        4. Sends promptStart with voice settings and tool definitions.
        5. Transmits system instructions as a SYSTEM content block.
        6. Opens continuous USER audio container for streaming microphone frames.
        7. Spawns background task to receive and deserialize model output events.
        """
        # Prune stale session IDs not present in active sessions to self-heal orphaned slots
        stale_ids = [sid for sid in list(self._active_live_session_ids) if sid not in self._active_sessions and sid != session_id]
        for sid in stale_ids:
            self._active_live_session_ids.discard(sid)

        max_concurrent = getattr(settings, "MAX_CONCURRENT_LIVE_SESSIONS", 1)
        if len(self._active_live_session_ids) >= max_concurrent:
            raise RuntimeError(
                f"Concurrent live session limit reached: Only {max_concurrent} active live session "
                f"is permitted during testing."
            )
        self._active_live_session_ids.add(session_id)

        queue: asyncio.Queue = asyncio.Queue()
        self._session_queues[session_id] = queue

        # Generate compliant UUID identifiers matching official Amazon Nova 2 Sonic specification
        prompt_name = str(uuid.uuid4())
        system_content_name = str(uuid.uuid4())
        audio_content_name = str(uuid.uuid4())

        # Spawn runtime watchdog timer task for deterministic session duration enforcement
        timeout_ceiling = getattr(settings, "LIVE_TEST_MAX_SESSION_SECONDS", 60)
        watchdog_task = asyncio.create_task(
            self._enforce_session_timeout(session_id, timeout_ceiling)
        )

        self._active_sessions[session_id] = {
            "preamble": prompt_preamble,
            "tools": tools,
            "format": audio_format,
            "prompt_name": prompt_name,
            "audio_content_name": audio_content_name,
            "is_interrupted": False,
            "start_time": datetime.now(timezone.utc),
            "connection": None,
            "receiver_task": None,
            "watchdog_task": watchdog_task,
            "last_sent_event": "none",
        }

        # Initialize transport stream
        connection: Optional[BedrockStreamConnection] = None
        try:
            connection = await self._transport.open_stream(
                model_id=self._model_id,
                region=self._region_name,
                session_id=session_id,
            )
            self._active_sessions[session_id]["connection"] = connection

            # Launch background listener immediately so inbound Bedrock events/errors are caught
            receiver_task = asyncio.create_task(self._listen_stream(session_id, connection))
            self._active_sessions[session_id]["receiver_task"] = receiver_task

            # 1. Send sessionStart (inference configuration)
            self._active_sessions[session_id]["last_sent_event"] = "sessionStart"
            session_start_evt = BedrockNovaSonicSerializer.serialize_session_start(
                max_tokens=settings.NOVA_SONIC_MAX_TOKENS,
                temperature=settings.NOVA_SONIC_TEMPERATURE,
                top_p=settings.NOVA_SONIC_TOP_P,
            )
            await connection.send_event(session_start_evt)
            await asyncio.sleep(0.04)
            if session_id not in self._active_sessions:
                return

            # 2. Send promptStart with declared tools
            self._active_sessions[session_id]["last_sent_event"] = "promptStart"
            prompt_start_evt = BedrockNovaSonicSerializer.serialize_prompt_start(
                prompt_name=prompt_name,
                tools=tools,
                voice_id=settings.NOVA_SONIC_VOICE_ID,
                output_sample_rate=settings.NOVA_SONIC_OUTPUT_SAMPLE_RATE,
            )
            await connection.send_event(prompt_start_evt)
            await asyncio.sleep(0.04)
            if session_id not in self._active_sessions:
                return

            # 3. Send system preamble in SYSTEM content block
            if prompt_preamble:
                self._active_sessions[session_id]["last_sent_event"] = "contentStart(SYSTEM)"
                await connection.send_event(
                    BedrockNovaSonicSerializer.serialize_system_content_start(
                        prompt_name=prompt_name,
                        content_name=system_content_name,
                    )
                )
                await asyncio.sleep(0.02)
                if session_id not in self._active_sessions:
                    return

                self._active_sessions[session_id]["last_sent_event"] = "textInput(SYSTEM)"
                await connection.send_event(
                    BedrockNovaSonicSerializer.serialize_text_input(
                        prompt_name=prompt_name,
                        content_name=system_content_name,
                        text=prompt_preamble,
                    )
                )
                await asyncio.sleep(0.02)
                if session_id not in self._active_sessions:
                    return

                self._active_sessions[session_id]["last_sent_event"] = "contentEnd(SYSTEM)"
                await connection.send_event(
                    BedrockNovaSonicSerializer.serialize_content_end(
                        prompt_name=prompt_name,
                        content_name=system_content_name,
                    )
                )
                await asyncio.sleep(0.02)
                if session_id not in self._active_sessions:
                    return

            # 4. Open USER AUDIO content block for incoming voice chunks (strict 16kHz for Nova Sonic input)
            self._active_sessions[session_id]["last_sent_event"] = "contentStart(AUDIO_USER)"
            await connection.send_event(
                BedrockNovaSonicSerializer.serialize_audio_content_start(
                    prompt_name=prompt_name,
                    content_name=audio_content_name,
                    sample_rate=settings.NOVA_SONIC_INPUT_SAMPLE_RATE,
                )
            )

        except Exception as exc:
            logger.error(f"Unexpected error opening Bedrock duplex stream for session {session_id}: {exc}", exc_info=True)
            self.release_session(session_id)
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.ERROR,
                    session_id=session_id,
                    data={"error_type": "BedrockConnectionError", "message": f"Could not connect to Bedrock Nova Sonic: {exc}"},
                )
            )
            # A failed live connection must not be reported as a started session.
            session_meta = self._active_sessions.pop(session_id, None)
            if session_meta:
                for task_key in ("watchdog_task", "receiver_task"):
                    task = session_meta.get(task_key)
                    if task and not task.done():
                        task.cancel()
            if connection is not None:
                try:
                    await connection.close()
                except Exception:
                    logger.debug("Error closing failed Bedrock stream", exc_info=True)
            return

        # Emit standard session started event to application queue
        await queue.put(
            VoiceServerEvent(
                event_type=VoiceEventType.SESSION_STARTED,
                session_id=session_id,
                data={
                    "model_id": self._model_id,
                    "provider": self.provider_name,
                    "region": self._region_name,
                    "audio_format": audio_format.value,
                    "tools_count": len(tools),
                    "connected": connection is not None,
                },
            )
        )

    async def send_audio_chunk(self, session_id: str, audio_bytes: bytes) -> None:
        """
        Serializes raw PCM binary audio chunk into base64 Bedrock audioInput event
        and pushes it down the active bidirectional stream.
        """
        if session_id not in self._active_sessions:
            raise ValueError(f"Session {session_id} not initialized.")

        # Audio frame validation: 16-bit PCM little-endian must have non-zero, even byte count
        if not audio_bytes or len(audio_bytes) % 2 != 0:
            logger.warning(
                f"Ignored malformed audio chunk in session {session_id} "
                f"({len(audio_bytes) if audio_bytes else 0} bytes)"
            )
            return

        session_meta = self._active_sessions[session_id]
        connection: Optional[BedrockStreamConnection] = session_meta.get("connection")

        # Rate matching / resampling if incoming format differs from configured stream input rate
        format_enum = session_meta.get("format", AudioFormat.PCM_24KHZ_16BIT_MONO)
        in_rate = 16000 if format_enum == AudioFormat.PCM_16KHZ_16BIT_MONO else 24000
        target_rate = settings.NOVA_SONIC_INPUT_SAMPLE_RATE
        if in_rate != target_rate:
            from app.services.voice.audio_utils import resample_pcm_s16le
            audio_bytes = resample_pcm_s16le(audio_bytes, in_rate, target_rate)

        if connection:
            audio_evt = BedrockNovaSonicSerializer.serialize_audio_input(
                prompt_name=session_meta["prompt_name"],
                content_name=session_meta["audio_content_name"],
                audio_bytes=audio_bytes,
            )
            await connection.send_event(audio_evt)
        else:
            logger.debug(f"Offline mode: buffered {len(audio_bytes)} audio bytes for session {session_id}")

    async def send_text_input(self, session_id: str, text: str) -> None:
        """Sends user text into the Amazon Nova 2.5 Sonic session."""
        if session_id not in self._session_queues:
            raise ValueError(f"Session {session_id} not initialized.")

        session_meta = self._active_sessions.get(session_id, {})
        connection: Optional[BedrockStreamConnection] = session_meta.get("connection")
        prompt_name = session_meta.get("prompt_name", f"prompt_{session_id}")
        content_name = f"user_text_{uuid.uuid4().hex[:8]}"

        # 1. Echo user transcript to client
        queue = self._session_queues[session_id]
        await queue.put(
            VoiceServerEvent(
                event_type=VoiceEventType.TRANSCRIPT_DELTA,
                session_id=session_id,
                transcript_payload=TranscriptDeltaPayload(
                    role="user",
                    delta=text.strip(),
                    is_final=True,
                ),
            )
        )

        # 2. Forward to Bedrock stream if connected
        if connection:
            await connection.send_event({
                "event": {
                    "contentStart": {
                        "promptName": prompt_name,
                        "contentName": content_name,
                        "type": "TEXT",
                        "role": "USER",
                    }
                }
            })
            await connection.send_event(
                BedrockNovaSonicSerializer.serialize_text_input(
                    prompt_name=prompt_name,
                    content_name=content_name,
                    text=text,
                )
            )
            await connection.send_event(
                BedrockNovaSonicSerializer.serialize_content_end(
                    prompt_name=prompt_name,
                    content_name=content_name,
                )
            )

    async def send_tool_result(
        self,
        session_id: str,
        tool_use_id: str,
        result: Dict[str, Any],
        is_error: bool = False,
    ) -> None:
        """
        Streams tool execution results back to Amazon Nova 2.5 Sonic:
        Wraps result in a TOOL content block (contentStart -> toolResult -> contentEnd).
        """
        if session_id not in self._active_sessions:
            raise ValueError(f"Session {session_id} not initialized.")

        session_meta = self._active_sessions[session_id]
        connection: Optional[BedrockStreamConnection] = session_meta.get("connection")
        prompt_name = session_meta["prompt_name"]

        if connection:
            # 1. Open TOOL content block
            await connection.send_event(
                BedrockNovaSonicSerializer.serialize_tool_result_content_start(
                    prompt_name=prompt_name,
                    tool_use_id=tool_use_id,
                )
            )
            # 2. Send serialized tool result payload
            await connection.send_event(
                BedrockNovaSonicSerializer.serialize_tool_result(
                    prompt_name=prompt_name,
                    tool_use_id=tool_use_id,
                    result=result,
                    is_error=is_error,
                )
            )
            # 3. Close TOOL content block
            await connection.send_event(
                BedrockNovaSonicSerializer.serialize_content_end(
                    prompt_name=prompt_name,
                    content_name=tool_use_id,
                )
            )
            logger.debug(f"Dispatched toolResult for {tool_use_id} to Bedrock session {session_id}")
        else:
            logger.debug(f"Offline mode: toolResult {tool_use_id} recorded for session {session_id}")

    async def interrupt(self, session_id: str) -> None:
        """Sends user interruption frame and drains audio playback queue."""
        if session_id not in self._session_queues:
            return

        if session_id in self._active_sessions:
            self._active_sessions[session_id]["is_interrupted"] = True

        queue = self._session_queues[session_id]

        # Drain queued audio from output buffer
        drained_count = 0
        items_to_keep = []
        while not queue.empty():
            try:
                evt = queue.get_nowait()
                if evt.event_type == VoiceEventType.AUDIO_OUTPUT:
                    drained_count += 1
                else:
                    items_to_keep.append(evt)
            except asyncio.QueueEmpty:
                break

        for item in items_to_keep:
            await queue.put(item)

        await queue.put(
            VoiceServerEvent(
                event_type=VoiceEventType.INTERRUPTED,
                session_id=session_id,
                data={"status": "interrupted", "drained_audio_frames": drained_count},
            )
        )

    async def end_session(self, session_id: str) -> None:
        """Gracefully closes stream connection and cleans up background tasks."""
        self._active_live_session_ids.discard(session_id)
        if session_id in self._active_sessions:
            session_meta = self._active_sessions.pop(session_id)
            connection: Optional[BedrockStreamConnection] = session_meta.get("connection")
            receiver_task: Optional[asyncio.Task] = session_meta.get("receiver_task")
            prompt_name = session_meta.get("prompt_name", f"prompt_{session_id}")
            audio_content_name = session_meta.get("audio_content_name", f"audio_{session_id}")

            if connection:
                try:
                    # Close audio content container and session
                    await connection.send_event(
                        BedrockNovaSonicSerializer.serialize_content_end(prompt_name, audio_content_name)
                    )
                    await connection.send_event(
                        BedrockNovaSonicSerializer.serialize_prompt_end(prompt_name)
                    )
                    await connection.send_event(
                        BedrockNovaSonicSerializer.serialize_session_end()
                    )
                    await connection.close()
                except Exception as exc:
                    logger.warning(f"Error gracefully terminating Bedrock stream: {exc}")

            watchdog_task: Optional[asyncio.Task] = session_meta.get("watchdog_task")
            if watchdog_task and not watchdog_task.done():
                watchdog_task.cancel()

            if receiver_task and not receiver_task.done():
                receiver_task.cancel()
                try:
                    await receiver_task
                except (asyncio.CancelledError, Exception):
                    pass

        if session_id in self._session_queues:
            queue = self._session_queues[session_id]
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.SESSION_ENDED,
                    session_id=session_id,
                )
            )

    async def receive_events(self, session_id: str) -> AsyncIterator[VoiceServerEvent]:
        """Asynchronously streams model output events (audio, transcript deltas, tool requests)."""
        if session_id not in self._session_queues:
            raise ValueError(f"Session {session_id} not found.")

        queue = self._session_queues[session_id]
        while True:
            evt = await queue.get()
            yield evt
            if evt.event_type == VoiceEventType.SESSION_ENDED:
                break

    async def _listen_stream(
        self,
        session_id: str,
        connection: BedrockStreamConnection,
    ) -> None:
        """
        Background listener task consuming raw events from Bedrock stream connection
        and routing parsed VoiceServerEvent items into the application session queue.
        """
        queue = self._session_queues.get(session_id)
        if not queue:
            return

        session_meta = self._active_sessions.get(session_id, {})
        start_time: datetime = session_meta.get("start_time", datetime.now(timezone.utc))

        try:
            async for raw_event in connection.receive_events():
                # Check 8-minute maximum session ceiling
                elapsed_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()
                if elapsed_seconds > self.MAX_SESSION_DURATION_SECONDS:
                    logger.warning(f"Session {session_id} exceeded maximum Bedrock duration ({elapsed_seconds:.0f}s).")
                    await queue.put(
                        VoiceServerEvent(
                            event_type=VoiceEventType.ERROR,
                            session_id=session_id,
                            data={
                                "error_type": "SessionTimeout",
                                "message": f"Bedrock session duration limit exceeded ({self.MAX_SESSION_DURATION_SECONDS}s).",
                            },
                        )
                    )
                    break

                # Parse inbound event
                parsed_event = BedrockNovaSonicParser.parse_event(raw_event, session_id)
                if parsed_event:
                    # Drop audio output if session has been interrupted
                    if (
                        parsed_event.event_type == VoiceEventType.AUDIO_OUTPUT
                        and session_meta.get("is_interrupted", False)
                    ):
                        continue

                    # If model begins a new speech/transcript turn, reset interruption flag
                    if (
                        parsed_event.event_type == VoiceEventType.TRANSCRIPT_DELTA
                        and parsed_event.transcript_payload
                        and parsed_event.transcript_payload.role == "assistant"
                    ):
                        session_meta["is_interrupted"] = False

                    await queue.put(parsed_event)

                    # Immediately halt listener loop if Bedrock returned a service error
                    if parsed_event.event_type == VoiceEventType.ERROR:
                        last_sent = session_meta.get("last_sent_event", "unknown")
                        err_type = parsed_event.data.get("error_type") if parsed_event.data else "Unknown"
                        raw_msg = parsed_event.data.get("message", "") if parsed_event.data else ""
                        logger.error(
                            f"[NovaSonicDriver] Bedrock returned error event for session {session_id}: "
                            f"{err_type} - {raw_msg}. Last transmitted event: {last_sent}. "
                            "Terminating stream listener immediately."
                        )
                        if parsed_event.data:
                            parsed_event.data["last_sent_event"] = last_sent
                            parsed_event.data["message"] = f"{raw_msg} (Last sent event: {last_sent})"
                        self.release_session(session_id)
                        break

        except asyncio.CancelledError:
            logger.debug(f"Stream listener cancelled for session {session_id}")
        except Exception as exc:
            logger.error(f"Error in Bedrock stream listener for session {session_id}: {exc}")
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.ERROR,
                    session_id=session_id,
                    data={"error_type": "StreamListenerException", "message": str(exc)},
                )
            )

    async def _enforce_session_timeout(self, session_id: str, max_duration: int) -> None:
        """
        Enforces a deterministic runtime session duration ceiling.
        When max_duration expires, terminates Bedrock connection and emits SessionTimeout for cost safety.
        """
        try:
            await asyncio.sleep(max_duration)
            if session_id in self._active_sessions:
                logger.warning(
                    f"[RUNTIME TIMEOUT] Live session {session_id} reached {max_duration}s runtime ceiling. "
                    "Terminating session for cost safety."
                )
                queue = self._session_queues.get(session_id)
                if queue:
                    await queue.put(
                        VoiceServerEvent(
                            event_type=VoiceEventType.ERROR,
                            session_id=session_id,
                            data={
                                "error_type": "SessionTimeout",
                                "message": f"Live test session duration limit exceeded ({max_duration}s). Closed for cost safety.",
                            },
                        )
                    )
                await self.end_session(session_id)
        except asyncio.CancelledError:
            pass
