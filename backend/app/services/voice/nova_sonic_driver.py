import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

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

    # Enforce safe session duration ceiling (configurable via settings, 180s local dev / 360s customer)
    MAX_SESSION_DURATION_SECONDS = getattr(settings, "VOICE_SESSION_CUSTOMER_DURATION_SECONDS", 360)
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
        # Prefer AWS's generated SDK for SigV4 and EventStream framing when available;
        # Injected test transports are preserved unchanged.
        if transport is not None:
            self._transport = transport
        else:
            try:
                import aws_sdk_bedrock_runtime  # noqa: F401
                from app.services.voice.sdk_transport import BedrockSDKStreamTransport
                self._transport = BedrockSDKStreamTransport(profile_name=self._profile_name)
                logger.info("[NovaSonicDriver] Using official AWS SDK bidirectional stream transport.")
            except ImportError:
                self._transport = BedrockCRTStreamTransport(
                    profile_name=self._profile_name,
                )
                logger.info("[NovaSonicDriver] aws-sdk-bedrock-runtime not installed; using CRT stream transport fallback.")
        self._session_queues: Dict[str, asyncio.Queue] = {}
        self._active_sessions: Dict[str, Dict[str, Any]] = {}

    @property
    def provider_name(self) -> str:
        return "amazon_nova_sonic"

    @property
    def model_id(self) -> str:
        return self._model_id

    async def _cleanup_failed_init(self, session_id: str, connection: Optional[BedrockStreamConnection] = None) -> None:
        """Guarantees cancellation of background tasks, closure of connection, and release of session slots upon initialization failure."""
        session_meta = self._active_sessions.pop(session_id, None)
        if session_meta:
            for task_key in ("watchdog_task", "receiver_task", "renewal_task"):
                task = session_meta.get(task_key)
                if task and not task.done():
                    task.cancel()
        conn = connection or (session_meta.get("connection") if session_meta else None)
        if conn:
            try:
                await conn.close()
            except Exception:
                pass
        self.release_session(session_id)

    async def start_session(
        self,
        session_id: str,
        prompt_preamble: str,
        tools: List[Dict[str, Any]],
        audio_format: AudioFormat = AudioFormat.PCM_24KHZ_16BIT_MONO,
        max_duration: Optional[int] = None,
        preamble_callback: Optional[Callable[[], str]] = None,
        customer_name: Optional[str] = None,
    ) -> None:
        """
        Initializes a bidirectional streaming session with Amazon Nova 2.5 Sonic:
        1. Checks concurrency limit for live sessions.
        2. Opens the duplex HTTP/2 transport connection.
        3. Sends sessionStart with inference and endpointing sensitivity parameters.
        4. Sends promptStart with voice settings and tool definitions.
        5. Transmits system instructions as a SYSTEM content block.
        6. Opens continuous USER audio container for streaming microphone frames.
        7. Spawns background task to receive and deserialize model output events.
        8. Spawns background stream renewal task if session duration exceeds AWS Bedrock stream limit.
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

        # Configurable session duration: honors explicit max_duration, test settings, or standard durations (up to 600s / 10 min)
        if max_duration is not None:
            timeout_ceiling = max_duration
        elif hasattr(settings, "LIVE_TEST_MAX_SESSION_SECONDS") and settings.LIVE_TEST_MAX_SESSION_SECONDS is not None:
            timeout_ceiling = settings.LIVE_TEST_MAX_SESSION_SECONDS
        else:
            timeout_ceiling = getattr(settings, "VOICE_SESSION_CUSTOMER_DURATION_SECONDS", 600)
        timeout_ceiling = min(timeout_ceiling, getattr(settings, "VOICE_SESSION_MAX_DURATION_SECONDS", 600))

        # Spawn runtime watchdog timer task for deterministic session duration enforcement
        watchdog_task = asyncio.create_task(
            self._enforce_session_timeout(session_id, timeout_ceiling)
        )

        # Automatic AWS Bedrock stream renewal monitor (AWS Bedrock limit is ~8 min / 480s; renewal at 360s)
        stream_max_duration = getattr(settings, "AWS_BEDROCK_STREAM_MAX_DURATION_SECONDS", 360)
        max_renewals = getattr(settings, "MAX_STREAM_RENEWALS", 2)
        renewal_task: Optional[asyncio.Task] = None
        if timeout_ceiling > stream_max_duration and max_renewals > 0:
            renewal_task = asyncio.create_task(
                self._monitor_stream_renewal(session_id, stream_max_duration)
            )

        stream_lock = asyncio.Lock()
        self._active_sessions[session_id] = {
            "preamble": prompt_preamble,
            "preamble_callback": preamble_callback,
            "tools": tools,
            "format": audio_format,
            "prompt_name": prompt_name,
            "audio_content_name": audio_content_name,
            "is_interrupted": False,
            "is_in_turn": False,
            "start_time": datetime.now(timezone.utc),
            "stream_start_time": datetime.now(timezone.utc),
            "connection": None,
            "receiver_task": None,
            "watchdog_task": watchdog_task,
            "renewal_task": renewal_task,
            "renewals_count": 0,
            "max_renewals": max_renewals,
            "stream_max_duration": stream_max_duration,
            "last_sent_event": "none",
            "max_duration": timeout_ceiling,
            "stream_lock": stream_lock,
            "audio_chunks_sent": 0,
            "resample_state": None,
        }

        # Initialize transport stream
        connection: Optional[BedrockStreamConnection] = None
        try:
            # Bounded timeout for opening duplex stream transport (Requirement 3 & 4)
            connection = await asyncio.wait_for(
                self._transport.open_stream(
                    model_id=self._model_id,
                    region=self._region_name,
                    session_id=session_id,
                ),
                timeout=10.0,
            )
            self._active_sessions[session_id]["connection"] = connection

            # Launch background listener immediately so inbound Bedrock events/errors are caught
            receiver_task = asyncio.create_task(self._listen_stream(session_id, connection))
            self._active_sessions[session_id]["receiver_task"] = receiver_task

            # Helper for bounded event transmission during initialization
            is_mock_transport = type(self._transport).__name__ in ("MockBedrockStreamTransport", "MockTransport")

            async def _send_init_event(event_dict: Dict[str, Any], event_name: str, delay: float = 0.04) -> None:
                self._active_sessions[session_id]["last_sent_event"] = event_name
                await asyncio.wait_for(connection.send_event(event_dict), timeout=5.0)
                if delay > 0 and not is_mock_transport:
                    await asyncio.sleep(delay)

            # 1. Send sessionStart (inference configuration & endpointing sensitivity)
            session_start_evt = BedrockNovaSonicSerializer.serialize_session_start(
                max_tokens=settings.NOVA_SONIC_MAX_TOKENS,
                temperature=settings.NOVA_SONIC_TEMPERATURE,
                top_p=settings.NOVA_SONIC_TOP_P,
                endpointing_sensitivity=getattr(settings, "NOVA_SONIC_ENDPOINTING_SENSITIVITY", "HIGH"),
            )
            await _send_init_event(session_start_evt, "sessionStart", 0.2)
            if session_id not in self._active_sessions:
                return

            # 2. Send promptStart with declared tools
            prompt_start_evt = BedrockNovaSonicSerializer.serialize_prompt_start(
                prompt_name=prompt_name,
                tools=tools,
                voice_id=settings.NOVA_SONIC_VOICE_ID,
                output_sample_rate=settings.NOVA_SONIC_OUTPUT_SAMPLE_RATE,
            )
            await _send_init_event(prompt_start_evt, "promptStart", 0.3)
            if session_id not in self._active_sessions:
                return

            # 3. Send system preamble in SYSTEM content block
            if prompt_preamble:
                await _send_init_event(
                    BedrockNovaSonicSerializer.serialize_system_content_start(
                        prompt_name=prompt_name,
                        content_name=system_content_name,
                    ),
                    "contentStart(SYSTEM)",
                    0.05,
                )
                if session_id not in self._active_sessions:
                    return

                await _send_init_event(
                    BedrockNovaSonicSerializer.serialize_text_input(
                        prompt_name=prompt_name,
                        content_name=system_content_name,
                        text=prompt_preamble,
                    ),
                    "textInput(SYSTEM)",
                    0.05,
                )
                if session_id not in self._active_sessions:
                    return

                await _send_init_event(
                    BedrockNovaSonicSerializer.serialize_content_end(
                        prompt_name=prompt_name,
                        content_name=system_content_name,
                    ),
                    "contentEnd(SYSTEM)",
                    0.3,
                )
                if session_id not in self._active_sessions:
                    return

            # 4. If automatic greeting is enabled, trigger Nova Sonic greeting via INIT_USER turn
            if getattr(settings, "ENABLE_AUTOMATIC_GREETING", False):
                init_user_content_name = f"init_user_{uuid.uuid4().hex[:8]}"
                init_text = f"Hello! I am {customer_name.strip()}." if customer_name else "Hello!"
                await _send_init_event(
                    BedrockNovaSonicSerializer.serialize_text_content_start(
                        prompt_name=prompt_name,
                        content_name=init_user_content_name,
                        role="USER",
                        interactive=True,
                    ),
                    "contentStart(INIT_USER)",
                    0.05,
                )
                if session_id not in self._active_sessions:
                    return

                await _send_init_event(
                    BedrockNovaSonicSerializer.serialize_text_input(
                        prompt_name=prompt_name,
                        content_name=init_user_content_name,
                        text=init_text,
                    ),
                    "textInput(INIT_USER)",
                    0.05,
                )
                if session_id not in self._active_sessions:
                    return

                await _send_init_event(
                    BedrockNovaSonicSerializer.serialize_content_end(
                        prompt_name=prompt_name,
                        content_name=init_user_content_name,
                    ),
                    "contentEnd(INIT_USER)",
                    0.1,
                )
                if session_id not in self._active_sessions:
                    return

            # 5. Open USER AUDIO content container for bidirectional microphone streaming (strict 16kHz for Nova Sonic input)
            await _send_init_event(
                BedrockNovaSonicSerializer.serialize_audio_content_start(
                    prompt_name=prompt_name,
                    content_name=audio_content_name,
                    sample_rate=settings.NOVA_SONIC_INPUT_SAMPLE_RATE,
                ),
                "contentStart(AUDIO_USER)",
                0.1,
            )

        except asyncio.TimeoutError as exc:
            logger.error(f"Bedrock duplex stream initialization timed out for session {session_id}")
            await self._cleanup_failed_init(session_id, connection)
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.ERROR,
                    session_id=session_id,
                    data={"error_type": "StreamInitTimeout", "message": f"Duplex stream initialization timed out for session {session_id}"},
                )
            )
            return
        except RuntimeError as exc:
            logger.warning(
                f"Bedrock stream transport not connected for session {session_id}: {exc}. "
                "Running in offline stub mode. Configure AWS credentials to activate live duplex stream."
            )
        except Exception as exc:
            logger.error(f"Unexpected error opening Bedrock duplex stream for session {session_id}: {exc}", exc_info=True)
            await self._cleanup_failed_init(session_id, connection)
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.ERROR,
                    session_id=session_id,
                    data={"error_type": "BedrockConnectionError", "message": f"Could not connect to Bedrock Nova Sonic: {exc}"},
                )
            )
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
            resample_state = session_meta.get("resample_state")
            audio_bytes, new_state = resample_pcm_s16le(
                audio_bytes, in_rate, target_rate, state=resample_state, return_state=True
            )
            session_meta["resample_state"] = new_state

        if connection:
            audio_evt = BedrockNovaSonicSerializer.serialize_audio_input(
                prompt_name=session_meta["prompt_name"],
                content_name=session_meta["audio_content_name"],
                audio_bytes=audio_bytes,
            )
            stream_lock = session_meta.get("stream_lock")
            if stream_lock:
                async with stream_lock:
                    await connection.send_event(audio_evt)
            else:
                await connection.send_event(audio_evt)
            session_meta["audio_chunks_sent"] = session_meta.get("audio_chunks_sent", 0) + 1
            chunks_count = session_meta["audio_chunks_sent"]
            if chunks_count <= 3 or chunks_count % 50 == 0:
                logger.info(
                    f"[NovaSonicDriver] Streamed mic audio chunk #{chunks_count} ({len(audio_bytes)} bytes) to Bedrock session {session_id}"
                )
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
            stream_lock = session_meta.get("stream_lock")
            # Enforce atomic transmission of tool result events to prevent audio chunk interleaving
            async def _send_tool_sequence():
                # 1. Open TOOL content block
                await connection.send_event(
                    BedrockNovaSonicSerializer.serialize_tool_result_content_start(
                        prompt_name=prompt_name,
                        tool_use_id=tool_use_id,
                    )
                )
                await asyncio.sleep(0.01)
                # 2. Send serialized tool result payload
                await connection.send_event(
                    BedrockNovaSonicSerializer.serialize_tool_result(
                        prompt_name=prompt_name,
                        tool_use_id=tool_use_id,
                        result=result,
                        is_error=is_error,
                    )
                )
                await asyncio.sleep(0.01)
                # 3. Close TOOL content block
                await connection.send_event(
                    BedrockNovaSonicSerializer.serialize_content_end(
                        prompt_name=prompt_name,
                        content_name=tool_use_id,
                    )
                )

            if stream_lock:
                async with stream_lock:
                    await _send_tool_sequence()
            else:
                await _send_tool_sequence()

            logger.info(f"[NovaSonicDriver] Dispatched atomic toolResult for {tool_use_id} to Bedrock session {session_id}")
        else:
            logger.debug(f"Offline mode: toolResult {tool_use_id} recorded for session {session_id}")

    async def interrupt(self, session_id: str) -> None:
        """Sends user interruption frame and drains audio playback queue."""
        if session_id not in self._session_queues:
            return

        if session_id in self._active_sessions:
            self._active_sessions[session_id]["is_interrupted"] = True
            self._active_sessions[session_id]["is_in_turn"] = False

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

            renewal_task: Optional[asyncio.Task] = session_meta.get("renewal_task")
            if renewal_task and not renewal_task.done():
                renewal_task.cancel()
                try:
                    await renewal_task
                except (asyncio.CancelledError, Exception):
                    pass

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

    async def renew_stream(
        self,
        session_id: str,
        updated_preamble: Optional[str] = None,
    ) -> bool:
        """
        Renews the underlying Amazon Bedrock duplex HTTP/2 EventStream connection
        while maintaining the active client session, session queue, and conversational state:
        1. Acquires stream_lock to prevent audio frame or tool result collisions.
        2. Gracefully closes old Bedrock stream (contentEnd, promptEnd, sessionEnd, close).
        3. Retrieves updated continuation preamble via callback if not explicitly provided.
        4. Generates fresh UUIDs for prompt and audio content containers.
        5. Connects a new Bedrock bidirectional stream with bounded retry.
        6. Transmits sessionStart, promptStart with tools, continuation SYSTEM preamble, and USER AUDIO container.
        7. Launches a new background listener piping model output directly into the existing session queue.
        8. Updates stream_start_time and releases stream_lock.
        """
        if session_id not in self._active_sessions:
            logger.warning(f"[NovaSonicDriver] Cannot renew stream: session {session_id} not active.")
            return False

        session_meta = self._active_sessions[session_id]
        stream_lock: Optional[asyncio.Lock] = session_meta.get("stream_lock")
        renewals_count = session_meta.get("renewals_count", 0) + 1

        logger.info(
            f"[NovaSonicDriver] Initiating automatic AWS Bedrock stream renewal #{renewals_count} "
            f"for session {session_id}..."
        )

        async def _do_renewal() -> bool:
            # 1. Gracefully close old connection & stop old receiver task
            old_conn: Optional[BedrockStreamConnection] = session_meta.get("connection")
            old_receiver: Optional[asyncio.Task] = session_meta.get("receiver_task")
            prompt_name = session_meta.get("prompt_name", f"prompt_{session_id}")
            audio_content_name = session_meta.get("audio_content_name", f"audio_{session_id}")

            if old_conn:
                try:
                    await old_conn.send_event(
                        BedrockNovaSonicSerializer.serialize_content_end(prompt_name, audio_content_name)
                    )
                    await old_conn.send_event(
                        BedrockNovaSonicSerializer.serialize_prompt_end(prompt_name)
                    )
                    await old_conn.send_event(
                        BedrockNovaSonicSerializer.serialize_session_end()
                    )
                    await old_conn.close()
                except Exception as exc:
                    logger.debug(f"[NovaSonicDriver] Graceful close of prior stream caught: {exc}")

            if old_receiver and not old_receiver.done():
                old_receiver.cancel()
                try:
                    await old_receiver
                except (asyncio.CancelledError, Exception):
                    pass

            # 2. Resolve continuation preamble
            preamble_to_use = updated_preamble
            if preamble_to_use is None:
                cb = session_meta.get("preamble_callback")
                if cb:
                    try:
                        preamble_to_use = cb()
                    except Exception as cb_err:
                        logger.error(f"[NovaSonicDriver] Preamble callback error during renewal: {cb_err}")
                        preamble_to_use = session_meta.get("preamble")
                else:
                    preamble_to_use = session_meta.get("preamble")
            session_meta["preamble"] = preamble_to_use

            # 3. Fresh UUID identifiers for new Bedrock stream
            new_prompt_name = str(uuid.uuid4())
            new_system_content_name = str(uuid.uuid4())
            new_audio_content_name = str(uuid.uuid4())
            session_meta["prompt_name"] = new_prompt_name
            session_meta["audio_content_name"] = new_audio_content_name

            # 4. Open new Bedrock duplex connection with bounded timeout
            new_conn: Optional[BedrockStreamConnection] = None
            try:
                new_conn = await asyncio.wait_for(
                    self._transport.open_stream(
                        model_id=self._model_id,
                        region=self._region_name,
                        session_id=session_id,
                    ),
                    timeout=10.0,
                )
            except Exception as conn_err:
                logger.error(
                    f"[NovaSonicDriver] Failed to open new Bedrock stream during renewal for session {session_id}: {conn_err}",
                    exc_info=True,
                )
                return False

            session_meta["connection"] = new_conn

            # 5. Launch listener for new stream
            new_receiver = asyncio.create_task(self._listen_stream(session_id, new_conn))
            session_meta["receiver_task"] = new_receiver

            # Helper for event send during renewal
            async def _send_renewal_event(event_dict: Dict[str, Any], event_name: str, delay: float = 0.04) -> None:
                session_meta["last_sent_event"] = event_name
                await asyncio.wait_for(new_conn.send_event(event_dict), timeout=5.0)
                if delay > 0:
                    await asyncio.sleep(delay)

            # 6. Re-handshake on new stream
            try:
                # sessionStart
                await _send_renewal_event(
                    BedrockNovaSonicSerializer.serialize_session_start(
                        max_tokens=settings.NOVA_SONIC_MAX_TOKENS,
                        temperature=settings.NOVA_SONIC_TEMPERATURE,
                        top_p=settings.NOVA_SONIC_TOP_P,
                        endpointing_sensitivity=getattr(settings, "NOVA_SONIC_ENDPOINTING_SENSITIVITY", "HIGH"),
                    ),
                    "sessionStart",
                    0.04,
                )
                # promptStart with declared tools
                await _send_renewal_event(
                    BedrockNovaSonicSerializer.serialize_prompt_start(
                        prompt_name=new_prompt_name,
                        tools=session_meta.get("tools", []),
                        voice_id=settings.NOVA_SONIC_VOICE_ID,
                        output_sample_rate=settings.NOVA_SONIC_OUTPUT_SAMPLE_RATE,
                    ),
                    "promptStart",
                    0.04,
                )
                # continuation system preamble
                if preamble_to_use:
                    await _send_renewal_event(
                        BedrockNovaSonicSerializer.serialize_system_content_start(
                            prompt_name=new_prompt_name,
                            content_name=new_system_content_name,
                        ),
                        "contentStart(SYSTEM)",
                        0.02,
                    )
                    await _send_renewal_event(
                        BedrockNovaSonicSerializer.serialize_text_input(
                            prompt_name=new_prompt_name,
                            content_name=new_system_content_name,
                            text=preamble_to_use,
                        ),
                        "textInput(SYSTEM)",
                        0.02,
                    )
                    await _send_renewal_event(
                        BedrockNovaSonicSerializer.serialize_content_end(
                            prompt_name=new_prompt_name,
                            content_name=new_system_content_name,
                        ),
                        "contentEnd(SYSTEM)",
                        0.02,
                    )
                # reopen USER AUDIO container
                await _send_renewal_event(
                    BedrockNovaSonicSerializer.serialize_audio_content_start(
                        prompt_name=new_prompt_name,
                        content_name=new_audio_content_name,
                        sample_rate=settings.NOVA_SONIC_INPUT_SAMPLE_RATE,
                    ),
                    "contentStart(AUDIO_USER)",
                    0.0,
                )
            except Exception as hs_err:
                logger.error(
                    f"[NovaSonicDriver] Handshake failed on renewed stream for session {session_id}: {hs_err}",
                    exc_info=True,
                )
                try:
                    await new_conn.close()
                except Exception:
                    pass
                return False

            session_meta["renewals_count"] = renewals_count
            session_meta["stream_start_time"] = datetime.now(timezone.utc)
            session_meta["is_in_turn"] = False
            logger.info(
                f"[NovaSonicDriver] Stream renewal #{renewals_count} completed successfully for session {session_id}."
            )
            return True

        if stream_lock:
            async with stream_lock:
                return await _do_renewal()
        else:
            return await _do_renewal()

    async def _monitor_stream_renewal(self, session_id: str, stream_interval: float) -> None:
        """
        Monitors elapsed stream duration and triggers seamless upstream Bedrock stream renewal
        at natural conversational boundaries prior to Bedrock's HTTP/2 connection limit (~8 minutes).
        Ensures the client browser WebSocket, audio stream, and session state remain uninterrupted.
        """
        logger.info(
            f"[NovaSonicDriver] Stream renewal monitor activated for session {session_id} "
            f"(stream renewal interval: {stream_interval}s)"
        )
        try:
            while session_id in self._active_sessions:
                session_meta = self._active_sessions.get(session_id)
                if not session_meta:
                    break
                stream_start = session_meta.get("stream_start_time", session_meta.get("start_time"))
                if not stream_start:
                    break

                elapsed_stream = (datetime.now(timezone.utc) - stream_start).total_seconds()
                time_until_renewal = stream_interval - elapsed_stream

                if time_until_renewal > 1.0:
                    await asyncio.sleep(min(time_until_renewal, 2.0))
                    continue

                renewals_count = session_meta.get("renewals_count", 0)
                max_renewals = session_meta.get("max_renewals", 2)
                if renewals_count >= max_renewals:
                    logger.info(
                        f"[NovaSonicDriver] Max stream renewals reached ({renewals_count}/{max_renewals}) "
                        f"for session {session_id}."
                    )
                    break

                # Wait up to 15s for natural conversation boundary (is_in_turn == False)
                wait_boundary_start = datetime.now(timezone.utc)
                while session_id in self._active_sessions:
                    curr_meta = self._active_sessions.get(session_id)
                    if not curr_meta or not curr_meta.get("is_in_turn", False):
                        break
                    boundary_elapsed = (datetime.now(timezone.utc) - wait_boundary_start).total_seconds()
                    if boundary_elapsed > 15.0:
                        logger.info(
                            f"[NovaSonicDriver] Forced renewal boundary reached after {boundary_elapsed:.1f}s "
                            f"for session {session_id}."
                        )
                        break
                    await asyncio.sleep(0.2)

                if session_id not in self._active_sessions:
                    break

                logger.info(
                    f"[NovaSonicDriver] Stream interval reached ({elapsed_stream:.1f}s >= {stream_interval}s). "
                    f"Triggering automatic stream renewal for session {session_id}..."
                )
                renewed = await self.renew_stream(session_id)
                if not renewed:
                    logger.warning(f"[NovaSonicDriver] Stream renewal attempt failed for session {session_id}")
                    await asyncio.sleep(5.0)

        except asyncio.CancelledError:
            logger.debug(f"[NovaSonicDriver] Stream renewal monitor cancelled for session {session_id}")
        except Exception as exc:
            logger.error(
                f"[NovaSonicDriver] Unexpected error in stream renewal monitor for session {session_id}: {exc}",
                exc_info=True,
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
            max_duration = session_meta.get("max_duration", self.MAX_SESSION_DURATION_SECONDS)
            async for raw_event in connection.receive_events():
                # Check maximum session duration ceiling
                elapsed_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()
                if elapsed_seconds > max_duration:
                    logger.info(
                        f"Session {session_id} completed planned duration ({elapsed_seconds:.0f}s >= {max_duration}s). "
                        "Ending session gracefully."
                    )
                    await queue.put(
                        VoiceServerEvent(
                            event_type=VoiceEventType.SESSION_COMPLETED,
                            session_id=session_id,
                            data={
                                "status": "completed",
                                "message": "Conversation completed. Thank you for speaking with our Real Estate AI Advisor.",
                                "duration_seconds": int(elapsed_seconds),
                            },
                        )
                    )
                    break

                # Parse inbound event
                parsed_event = BedrockNovaSonicParser.parse_event(raw_event, session_id)
                if parsed_event:
                    # Track conversational speech turn state and handle interruption
                    if parsed_event.event_type == VoiceEventType.AUDIO_OUTPUT:
                        if session_meta.get("is_interrupted", False):
                            continue
                        session_meta["is_in_turn"] = True

                    elif parsed_event.event_type == VoiceEventType.TOOL_USE_REQUEST:
                        session_meta["is_in_turn"] = True

                    elif (
                        parsed_event.event_type == VoiceEventType.TRANSCRIPT_DELTA
                        and parsed_event.transcript_payload
                        and parsed_event.transcript_payload.role == "assistant"
                    ):
                        session_meta["is_interrupted"] = False
                        if parsed_event.transcript_payload.is_final:
                            session_meta["is_in_turn"] = False

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

    async def _enforce_session_timeout(self, session_id: str, max_duration: float) -> None:
        """
        Enforces a deterministic runtime session duration ceiling.
        For test runs with short ceilings (< 5s), emits SessionTimeout error.
        For normal customer conversations, emits a friendly advance warning 30s before expiry
        without interrupting speech, then gracefully closes with SESSION_COMPLETED.
        """
        warn_seconds = getattr(settings, "SESSION_EXPIRY_WARNING_SECONDS", 30)
        is_short_test_watchdog = max_duration < 5.0
        try:
            if not is_short_test_watchdog and max_duration > warn_seconds:
                warn_delay = max(0.0, max_duration - warn_seconds)
                if warn_delay > 0:
                    await asyncio.sleep(warn_delay)
                    if session_id in self._active_sessions:
                        queue = self._session_queues.get(session_id)
                        if queue:
                            logger.info(
                                f"[SESSION TIMEOUT WARNING] Session {session_id} will reach planned duration in {warn_seconds}s. "
                                "Emitting session_warning."
                            )
                            await queue.put(
                                VoiceServerEvent(
                                    event_type=VoiceEventType.SESSION_WARNING,
                                    session_id=session_id,
                                    data={
                                        "message": f"Conversation ending in {warn_seconds} seconds.",
                                        "remaining_seconds": warn_seconds,
                                    },
                                )
                            )
                    remaining = max_duration - warn_delay
                    await asyncio.sleep(remaining)
                else:
                    await asyncio.sleep(max_duration)
            else:
                await asyncio.sleep(max_duration)

            if session_id in self._active_sessions:
                queue = self._session_queues.get(session_id)
                if is_short_test_watchdog:
                    logger.warning(
                        f"[SESSION WATCHDOG TIMEOUT] Session {session_id} exceeded watchdog limit ({max_duration}s). "
                        "Emitting SessionTimeout."
                    )
                    if queue:
                        await queue.put(
                            VoiceServerEvent(
                                event_type=VoiceEventType.ERROR,
                                session_id=session_id,
                                data={
                                    "error_type": "SessionTimeout",
                                    "message": f"Session exceeded maximum duration ceiling of {max_duration}s.",
                                },
                            )
                        )
                else:
                    logger.info(
                        f"[SESSION COMPLETED] Session {session_id} completed planned duration ({max_duration}s). "
                        "Gracefully ending session."
                    )
                    if queue:
                        await queue.put(
                            VoiceServerEvent(
                                event_type=VoiceEventType.SESSION_COMPLETED,
                                session_id=session_id,
                                data={
                                    "status": "completed",
                                    "message": "Conversation completed. Thank you for speaking with our Real Estate AI Advisor.",
                                    "duration_seconds": max_duration,
                                },
                            )
                        )
                await self.end_session(session_id)
        except asyncio.CancelledError:
            pass
