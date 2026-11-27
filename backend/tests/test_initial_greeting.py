import asyncio
import json
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import settings
from app.services.voice.base import VoiceEventType
from app.services.voice.mock_driver import MockVoiceDriver
from app.services.voice.factory import get_voice_driver
from app.services.voice.orchestrator import VoiceSessionOrchestrator
from app.services.voice.nova_sonic_driver import AmazonNovaSonicDriver
from app.services.voice.bedrock_streaming import BedrockStreamTransport, BedrockStreamConnection
from app.services.voice.nova_validator import NovaSonicEventValidator
from app.services.voice.tools_spec import get_agent_tools_spec


@pytest.mark.asyncio
async def test_mock_voice_driver_emits_audio_greeting_first():
    """
    Verifies:
    1. Driver emits SESSION_STARTED.
    2. Driver emits TRANSCRIPT_DELTA with the expected initial greeting.
    3. Driver emits AUDIO_OUTPUT with non-empty 24kHz PCM audio frames.
    """
    driver = get_voice_driver(override_mock=True)
    session_id = "test_greet_001"

    await driver.start_session(
        session_id=session_id,
        prompt_preamble="Preamble",
        tools=[],
        customer_name="Sarah",
    )

    queue = driver._session_queues[session_id]
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    # Verify event types in order
    event_types = [e.event_type for e in events]
    assert VoiceEventType.SESSION_STARTED in event_types
    assert VoiceEventType.TRANSCRIPT_DELTA in event_types
    assert VoiceEventType.AUDIO_OUTPUT in event_types

    # Verify transcript text matches required greeting
    transcript_evt = next(e for e in events if e.event_type == VoiceEventType.TRANSCRIPT_DELTA)
    assert transcript_evt.transcript_payload.role == "assistant"
    greeting_text = transcript_evt.transcript_payload.delta
    assert "Hello Sarah!" in greeting_text
    assert "I'm your property assistant. How can I help you?" in greeting_text

    # Verify audio payload exists and has audible PCM bytes
    audio_evt = next(e for e in events if e.event_type == VoiceEventType.AUDIO_OUTPUT)
    assert audio_evt.audio_payload is not None
    assert len(audio_evt.audio_payload.audio_bytes) > 0
    assert audio_evt.audio_payload.sample_rate == 24000

    await driver.end_session(session_id)


@pytest.mark.asyncio
async def test_orchestrator_initial_greeting_pipeline_and_no_duplicates():
    """
    Verifies:
    1. Orchestrator starts session and streams greeting transcript and audio.
    2. has_greeted is set to True.
    3. Renewal / reconnection preamble avoids repeating the greeting.
    """
    driver = get_voice_driver(override_mock=True)
    session_id = "test_orch_greet_002"

    orchestrator = VoiceSessionOrchestrator(
        session_id=session_id,
        driver=driver,
        db=None,
        customer_id=None,
        user_role="customer",
    )
    orchestrator.customer_name = "Rahul"

    # Start session
    await orchestrator.start()
    assert orchestrator.has_greeted is True

    sent_texts = []
    sent_bytes = []

    async def mock_send_text(msg: str):
        sent_texts.append(json.loads(msg))

    async def mock_send_bytes(b: bytes):
        sent_bytes.append(b)

    # Run pipeline briefly to consume initial events
    pipeline_task = asyncio.create_task(
        orchestrator.run_pipeline(send_text=mock_send_text, send_bytes=mock_send_bytes)
    )

    await asyncio.sleep(0.1)

    # 1. Verify session_started sent
    assert any(m.get("type") == "session_started" for m in sent_texts)

    # 2. Verify transcript sent
    assistant_transcripts = [m for m in sent_texts if m.get("type") == "transcript" and m.get("role") == "assistant"]
    assert len(assistant_transcripts) >= 1
    assert "property assistant" in assistant_transcripts[0]["delta"]

    # 3. Verify audio output sent
    assert len(sent_bytes) >= 1
    assert len(sent_bytes[0]) > 0

    # 4. Verify continuation preamble does NOT repeat greeting
    renewal_preamble = orchestrator._build_renewal_preamble()
    assert "DO NOT repeat the initial greeting" in renewal_preamble

    # Cleanup
    await orchestrator.close()
    pipeline_task.cancel()
    try:
        await pipeline_task
    except (asyncio.CancelledError, Exception):
        pass


@pytest.mark.asyncio
async def test_nova_sonic_event_sequence_greeting_enabled():
    """
    Verifies that when ENABLE_AUTOMATIC_GREETING is True,
    AmazonNovaSonicDriver transmits:
    sessionStart -> promptStart -> SYSTEM block -> INIT_USER block -> AUDIO_USER block.
    """
    sent_events = []

    class MockConn(BedrockStreamConnection):
        async def send_event(self, event_dict):
            sent_events.append(event_dict)

        async def receive_events(self):
            if False:
                yield {}

        async def close(self):
            pass

    class MockTransport(BedrockStreamTransport):
        async def open_stream(self, *args, **kwargs):
            return MockConn()

    driver = AmazonNovaSonicDriver(transport=MockTransport())
    session_id = f"test_greet_seq_{uuid.uuid4().hex[:8]}"
    tools = get_agent_tools_spec()
    customer_name = "Sarah"

    orig_greet = settings.ENABLE_AUTOMATIC_GREETING
    settings.ENABLE_AUTOMATIC_GREETING = True
    try:
        await driver.start_session(
            session_id=session_id,
            prompt_preamble="System instructions",
            tools=tools,
            customer_name=customer_name,
        )

        event_names = [list(e["event"].keys())[0] for e in sent_events]
        assert event_names == [
            "sessionStart",
            "promptStart",
            "contentStart",  # SYSTEM
            "textInput",     # SYSTEM
            "contentEnd",    # SYSTEM
            "contentStart",  # INIT_USER
            "textInput",     # INIT_USER
            "contentEnd",    # INIT_USER
            "contentStart",  # AUDIO_USER
        ]

        # Validate INIT_USER block properties
        init_start = sent_events[5]["event"]["contentStart"]
        assert init_start["type"] == "TEXT"
        assert init_start["role"] == "USER"
        assert init_start["interactive"] is True

        init_text = sent_events[6]["event"]["textInput"]
        assert "Sarah" in init_text["content"]

        # Validate AUDIO_USER block properties
        audio_start = sent_events[8]["event"]["contentStart"]
        assert audio_start["type"] == "AUDIO"
        assert audio_start["role"] == "USER"
        assert audio_start["interactive"] is True

        # Validate strict event protocol ordering
        validator = NovaSonicEventValidator(strict_sequencing=True)
        for evt in sent_events:
            validator.validate_event(evt)

        await driver.end_session(session_id)
    finally:
        settings.ENABLE_AUTOMATIC_GREETING = orig_greet


@pytest.mark.asyncio
async def test_nova_sonic_event_sequence_greeting_disabled():
    """
    Verifies that when ENABLE_AUTOMATIC_GREETING is False,
    AmazonNovaSonicDriver bypasses INIT_USER and directly opens AUDIO_USER.
    """
    sent_events = []

    class MockConn(BedrockStreamConnection):
        async def send_event(self, event_dict):
            sent_events.append(event_dict)

        async def receive_events(self):
            if False:
                yield {}

        async def close(self):
            pass

    class MockTransport(BedrockStreamTransport):
        async def open_stream(self, *args, **kwargs):
            return MockConn()

    driver = AmazonNovaSonicDriver(transport=MockTransport())
    session_id = f"test_mic_first_{uuid.uuid4().hex[:8]}"
    tools = get_agent_tools_spec()

    orig_greet = settings.ENABLE_AUTOMATIC_GREETING
    settings.ENABLE_AUTOMATIC_GREETING = False
    try:
        await driver.start_session(
            session_id=session_id,
            prompt_preamble="System instructions",
            tools=tools,
            customer_name="Sarah",
        )

        event_names = [list(e["event"].keys())[0] for e in sent_events]
        assert event_names == [
            "sessionStart",
            "promptStart",
            "contentStart",  # SYSTEM
            "textInput",     # SYSTEM
            "contentEnd",    # SYSTEM
            "contentStart",  # AUDIO_USER
        ]

        # Validate strict event protocol ordering
        validator = NovaSonicEventValidator(strict_sequencing=True)
        for evt in sent_events:
            validator.validate_event(evt)

        await driver.end_session(session_id)
    finally:
        settings.ENABLE_AUTOMATIC_GREETING = orig_greet


@pytest.mark.asyncio
async def test_customer_interruption_supported():
    """
    Verifies customer interruption cleanly drains pending assistant audio.
    """
    driver = get_voice_driver(override_mock=True)
    session_id = f"test_interr_{uuid.uuid4().hex[:8]}"

    await driver.start_session(session_id=session_id, prompt_preamble="P", tools=[])
    queue = driver._session_queues[session_id]

    # Queue should contain initial audio
    initial_events = []
    while not queue.empty():
        initial_events.append(queue.get_nowait())
    assert any(e.event_type == VoiceEventType.AUDIO_OUTPUT for e in initial_events)

    # Re-queue an audio event and call interrupt
    await queue.put(initial_events[-1])
    await driver.interrupt(session_id)

    # Post-interruption queue must have INTERRUPTED event and no AUDIO_OUTPUT
    post_events = []
    while not queue.empty():
        post_events.append(queue.get_nowait())

    assert any(e.event_type == VoiceEventType.INTERRUPTED for e in post_events)
    assert not any(e.event_type == VoiceEventType.AUDIO_OUTPUT for e in post_events)

    await driver.end_session(session_id)


@pytest.mark.asyncio
async def test_customer_portal_voice_session_start_regression():
    """
    Regression test for:
    'Start New Conversation returns to STANDING BY / No Active Conversation without playing AI greeting.'
    Verifies:
    1. A customer session with customer_name (e.g. Ramesh Kumar) initializes cleanly.
    2. _build_system_preamble() executes regex cleaning without NameError: name 're' is not defined.
    3. The WebSocket pipeline emits session_started, assistant greeting transcript, and audible PCM audio chunks.
    4. Session can be stopped and a new conversation started cleanly without state corruption.
    """
    driver = get_voice_driver(override_mock=True)

    for iteration in [1, 2]:
        session_id = f"test_cust_portal_{uuid.uuid4().hex[:8]}"
        orchestrator = VoiceSessionOrchestrator(
            session_id=session_id,
            driver=driver,
            db=None,
            customer_id=None,
            user_role="customer",
        )
        orchestrator.customer_name = "Ramesh Kumar"

        # Start orchestrator - must not throw NameError
        await orchestrator.start()
        assert orchestrator.has_greeted is True

        sent_texts = []
        sent_bytes = []

        async def mock_send_text(msg: str):
            sent_texts.append(json.loads(msg))

        async def mock_send_bytes(b: bytes):
            sent_bytes.append(b)

        pipeline_task = asyncio.create_task(
            orchestrator.run_pipeline(send_text=mock_send_text, send_bytes=mock_send_bytes)
        )
        await asyncio.sleep(0.1)

        # 1. Verify session_started
        assert any(m.get("type") == "session_started" for m in sent_texts), f"Iteration {iteration}: missing session_started"

        # 2. Verify greeting transcript addressed to customer
        assistant_transcripts = [m for m in sent_texts if m.get("type") == "transcript" and m.get("role") == "assistant"]
        assert len(assistant_transcripts) >= 1, f"Iteration {iteration}: missing assistant greeting transcript"
        assert "Ramesh Kumar" in assistant_transcripts[0]["delta"], f"Iteration {iteration}: customer name not in greeting"

        # 3. Verify audio output
        assert len(sent_bytes) >= 1, f"Iteration {iteration}: missing greeting audio bytes"
        assert len(sent_bytes[0]) > 0, f"Iteration {iteration}: empty greeting audio"

        # 4. Clean close
        await orchestrator.close()
        pipeline_task.cancel()
        try:
            await pipeline_task
        except (asyncio.CancelledError, Exception):
            pass


async def run_all_checks():
    print("==================================================================", flush=True)
    print("   AI-FIRST GREETING & PROTOCOL BOUNDED VERIFICATION SUITE         ", flush=True)
    print("==================================================================", flush=True)

    print("[1/6] Testing mock voice driver initial greeting audio emission...", flush=True)
    await asyncio.wait_for(test_mock_voice_driver_emits_audio_greeting_first(), timeout=5.0)
    print("      -> PASS: Mock driver emits assistant greeting text and 24kHz audio frames", flush=True)

    print("[2/6] Testing voice session orchestrator greeting pipeline & deduplication...", flush=True)
    await asyncio.wait_for(test_orchestrator_initial_greeting_pipeline_and_no_duplicates(), timeout=5.0)
    print("      -> PASS: Orchestrator streams greeting, marks has_greeted, avoids duplicates", flush=True)

    print("[3/6] Testing customer portal voice session start & restart regression...", flush=True)
    await asyncio.wait_for(test_customer_portal_voice_session_start_regression(), timeout=5.0)
    print("      -> PASS: Fixed bug - customer portal starts cleanly, plays greeting, and restarts seamlessly", flush=True)

    print("[4/6] Testing Nova Sonic Bedrock EventStream sequence with greeting enabled...", flush=True)
    await asyncio.wait_for(test_nova_sonic_event_sequence_greeting_enabled(), timeout=5.0)
    print("      -> PASS: Bedrock sequence is sessionStart->promptStart->SYSTEM->INIT_USER->AUDIO_USER", flush=True)

    print("[5/6] Testing Nova Sonic Bedrock EventStream with greeting disabled (mic-first)...", flush=True)
    await asyncio.wait_for(test_nova_sonic_event_sequence_greeting_disabled(), timeout=5.0)
    print("      -> PASS: Disabled path bypasses INIT_USER and directly opens AUDIO_USER", flush=True)

    print("[6/6] Testing customer speech interruption handling...", flush=True)
    await asyncio.wait_for(test_customer_interruption_supported(), timeout=5.0)
    print("      -> PASS: Interruption drains queued audio and emits INTERRUPTED event", flush=True)

    print("==================================================================", flush=True)
    print("   ALL 6 OFFLINE GREETING VERIFICATION CHECKS PASSED CLEANLY!     ", flush=True)
    print("==================================================================", flush=True)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_all_checks())
    finally:
        loop.close()

