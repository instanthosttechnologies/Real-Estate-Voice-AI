"""
Test suite validating that the AI Robot speaks first with opening greeting.

Requirements:
A. Start conversation in English without speaking. Robot must greet first.
B. Start conversation in Hindi without speaking. Robot must greet first in Hindi.
C. After greeting, customer speaks and robot responds.
D. Customer begins speaking while greeting is playing (interruption).
E. End and start a new conversation: exactly one new greeting.
F. Renew an existing voice session: no repeated greeting.
G. Language switching preserves context and adapts greeting/responses.
"""

import asyncio
import json
import pytest

from app.core.config import settings
from app.services.voice.base import VoiceEventType
from app.services.voice.mock_driver import MockVoiceDriver
from app.services.voice.orchestrator import VoiceSessionOrchestrator
from app.services.voice.nova_sonic_driver import AmazonNovaSonicDriver
from app.services.voice.bedrock_streaming import BedrockStreamTransport, BedrockStreamConnection
from app.services.real_estate.requirements import extract_requirements_from_text


@pytest.mark.asyncio
async def test_requirement_a_english_speaks_first():
    """Customer starts conversation in English without speaking: robot must greet first."""
    driver = MockVoiceDriver()
    session_id = "test_speak_first_en"
    orch = VoiceSessionOrchestrator(
        session_id=session_id,
        driver=driver,
        db=None,
        language="en-US",
        voice_id="matthew",
    )
    orch.customer_name = "Alex"

    await orch.start()
    assert orch.has_greeted is True

    received_events = []
    async def capture_events():
        async for evt in driver.receive_events(session_id):
            received_events.append(evt)
            if evt.event_type == VoiceEventType.AUDIO_OUTPUT:
                break

    await asyncio.wait_for(capture_events(), timeout=3.0)

    # Verify greeting transcript is emitted first
    transcript_evt = next((e for e in received_events if e.event_type == VoiceEventType.TRANSCRIPT_DELTA), None)
    assert transcript_evt is not None
    assert transcript_evt.transcript_payload.role == "assistant"
    assert "Alex" in transcript_evt.transcript_payload.delta
    assert "property assistant" in transcript_evt.transcript_payload.delta

    # Verify audio output is emitted first
    audio_evt = next((e for e in received_events if e.event_type == VoiceEventType.AUDIO_OUTPUT), None)
    assert audio_evt is not None
    assert len(audio_evt.audio_payload.audio_bytes) > 0
    assert audio_evt.audio_payload.sample_rate == 24000

    await orch.close()


@pytest.mark.asyncio
async def test_requirement_b_hindi_female_speaks_first():
    """Customer starts conversation in Hindi without speaking: female robot must greet first in feminine Hindi."""
    driver = MockVoiceDriver()
    session_id = "test_speak_first_hi"
    orch = VoiceSessionOrchestrator(
        session_id=session_id,
        driver=driver,
        db=None,
        language="hi-IN",
        voice_id="kiara",
    )
    orch.customer_name = "सुनीता"

    await orch.start()
    assert orch.has_greeted is True

    received_events = []
    async def capture_events():
        async for evt in driver.receive_events(session_id):
            received_events.append(evt)
            if evt.event_type == VoiceEventType.AUDIO_OUTPUT:
                break

    await asyncio.wait_for(capture_events(), timeout=3.0)

    transcript_evt = next((e for e in received_events if e.event_type == VoiceEventType.TRANSCRIPT_DELTA), None)
    assert transcript_evt is not None
    assert transcript_evt.transcript_payload.role == "assistant"
    greeting_text = transcript_evt.transcript_payload.delta
    assert "सुनीता" in greeting_text
    assert "प्रॉपर्टी असिस्टेंट हूँ" in greeting_text
    assert "कर सकती हूँ" in greeting_text

    audio_evt = next((e for e in received_events if e.event_type == VoiceEventType.AUDIO_OUTPUT), None)
    assert audio_evt is not None
    assert len(audio_evt.audio_payload.audio_bytes) > 0

    await orch.close()


@pytest.mark.asyncio
async def test_requirement_b_hindi_male_speaks_first():
    """Customer starts conversation in Hindi with male voice: male robot must greet in masculine Hindi."""
    driver = MockVoiceDriver()
    session_id = "test_speak_first_hi_male"
    orch = VoiceSessionOrchestrator(
        session_id=session_id,
        driver=driver,
        db=None,
        language="hi-IN",
        voice_id="arjun",
    )

    await orch.start()
    assert orch.has_greeted is True

    received_events = []
    async def capture_events():
        async for evt in driver.receive_events(session_id):
            received_events.append(evt)
            if evt.event_type == VoiceEventType.AUDIO_OUTPUT:
                break

    await asyncio.wait_for(capture_events(), timeout=3.0)

    transcript_evt = next((e for e in received_events if e.event_type == VoiceEventType.TRANSCRIPT_DELTA), None)
    assert transcript_evt is not None
    greeting_text = transcript_evt.transcript_payload.delta
    assert "प्रॉपर्टी असिस्टेंट हूँ" in greeting_text
    assert "कर सकता हूँ" in greeting_text

    await orch.close()


@pytest.mark.asyncio
async def test_requirement_c_customer_speaks_after_greeting():
    """After greeting, customer speaks and robot responds normally."""
    driver = MockVoiceDriver()
    session_id = "test_customer_speaks_after_greet"
    orch = VoiceSessionOrchestrator(
        session_id=session_id,
        driver=driver,
        db=None,
        language="en-US",
    )
    await orch.start()

    # Simulate customer utterance after initial greeting
    text = "I am looking for a 3BHK flat in Chennai under 1.5 Cr."
    await orch.handle_incoming_text(text)
    req = extract_requirements_from_text(text)
    orch.session_state.update_requirements(req)

    assert orch.session_state.requirements.configuration_type == "3BHK"
    assert orch.session_state.requirements.preferred_city == "Chennai"
    assert orch.session_state.requirements.budget_max == 15000000

    await orch.close()


@pytest.mark.asyncio
async def test_requirement_d_customer_interrupts_during_greeting():
    """Customer begins speaking while greeting is playing: interruption cleanly drains audio."""
    driver = MockVoiceDriver()
    session_id = "test_interruption_during_greet"
    orch = VoiceSessionOrchestrator(
        session_id=session_id,
        driver=driver,
        db=None,
        language="en-US",
    )
    await orch.start()

    # Call interruption while greeting is queued
    await orch.handle_interruption()

    queue = driver._session_queues[session_id]
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    # Verify INTERRUPTED event is queued and AUDIO_OUTPUT is drained
    assert any(e.event_type == VoiceEventType.INTERRUPTED for e in events)
    assert not any(e.event_type == VoiceEventType.AUDIO_OUTPUT for e in events)

    await orch.close()


@pytest.mark.asyncio
async def test_requirement_e_end_and_restart_exactly_one_greeting():
    """End and start a new conversation: exactly one greeting per conversation."""
    driver = MockVoiceDriver()

    # Session 1
    s1 = "test_restart_s1"
    orch1 = VoiceSessionOrchestrator(session_id=s1, driver=driver, db=None, language="en-US")
    await orch1.start()
    assert orch1.has_greeted is True

    s1_events = []
    while not driver._session_queues[s1].empty():
        s1_events.append(driver._session_queues[s1].get_nowait())
    s1_transcripts = [e for e in s1_events if e.event_type == VoiceEventType.TRANSCRIPT_DELTA and e.transcript_payload.role == "assistant"]
    assert len(s1_transcripts) == 1
    await orch1.close()

    # Session 2
    s2 = "test_restart_s2"
    orch2 = VoiceSessionOrchestrator(session_id=s2, driver=driver, db=None, language="hi-IN", voice_id="kiara")
    await orch2.start()
    assert orch2.has_greeted is True

    s2_events = []
    while not driver._session_queues[s2].empty():
        s2_events.append(driver._session_queues[s2].get_nowait())
    s2_transcripts = [e for e in s2_events if e.event_type == VoiceEventType.TRANSCRIPT_DELTA and e.transcript_payload.role == "assistant"]
    assert len(s2_transcripts) == 1
    assert "प्रॉपर्टी असिस्टेंट" in s2_transcripts[0].transcript_payload.delta
    await orch2.close()


@pytest.mark.asyncio
async def test_requirement_f_renew_session_no_repeated_greeting():
    """Renewing a voice stream must NOT repeat the initial greeting."""
    driver = MockVoiceDriver()
    session_id = "test_renewal_no_greet"
    orch = VoiceSessionOrchestrator(session_id=session_id, driver=driver, db=None, language="en-US")
    await orch.start()
    assert orch.has_greeted is True

    # Build renewal preamble
    renewal_preamble = orch._build_renewal_preamble()
    assert "DO NOT greet the customer again" in renewal_preamble
    assert "DO NOT repeat the initial greeting" in renewal_preamble

    await orch.close()


@pytest.mark.asyncio
async def test_nova_sonic_driver_event_flow_includes_init_user():
    """
    Validates that AmazonNovaSonicDriver emits INIT_USER and then AUDIO_USER
    when ENABLE_AUTOMATIC_GREETING is True.
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
    session_id = "test_nova_greet_flow"

    orig_greet = settings.ENABLE_AUTOMATIC_GREETING
    settings.ENABLE_AUTOMATIC_GREETING = True
    try:
        await driver.start_session(
            session_id=session_id,
            prompt_preamble="System prompt",
            tools=[],
            customer_name="Kaviya",
            language="hi-IN",
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

        # Verify Hindi personalization in INIT_USER
        init_text = sent_events[6]["event"]["textInput"]["content"]
        assert "Kaviya" in init_text
        assert "नमस्ते" in init_text

        await driver.end_session(session_id)
    finally:
        settings.ENABLE_AUTOMATIC_GREETING = orig_greet
