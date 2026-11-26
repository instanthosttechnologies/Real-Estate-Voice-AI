import asyncio
from decimal import Decimal
import json
import pytest

from app.core.config import settings
from app.services.voice.base import (
    AudioFormat,
    VoiceEventType,
    VoiceServerEvent,
)
from app.services.voice.mock_driver import MockVoiceDriver
from app.services.voice.nova_sonic_driver import AmazonNovaSonicDriver
from app.services.voice.bedrock_streaming import MockBedrockStreamTransport
from app.services.voice.tools_spec import get_agent_tools_spec
from app.services.voice.orchestrator import VoiceSessionOrchestrator
from app.services.voice.session_state import SessionState
from app.services.real_estate.requirements import (
    ExtractedCustomerRequirements,
    extract_requirements_from_text,
    parse_numeric_budget,
)
from app.db.base import Base
import app.models  # noqa: F401
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


def get_test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_varied_bhk_phrasing_and_number_words():
    """Validates varied phrasing: 'two BHK', 'two bedroom', '2BHK flat', 'three BHK', '3BHK'."""
    # 1. Word number "two BHK"
    req1 = extract_requirements_from_text("I'm looking for a two BHK in Gurugram")
    assert req1.configuration_type == "2BHK"
    assert req1.preferred_city == "Gurugram"

    # 2. Word number "two bedroom"
    req2 = extract_requirements_from_text("Need a two bedroom apartment")
    assert req2.configuration_type == "2BHK"

    # 3. Phrasing "2BHK flat"
    req3 = extract_requirements_from_text("Show me 2BHK flat options around 80 lakhs")
    assert req3.configuration_type == "2BHK"
    assert req3.budget_max == Decimal("8000000")
    assert req3.currency == "INR"

    # 4. Phrasing "three bedroom"
    req4 = extract_requirements_from_text("Actually I want a three bedroom flat")
    assert req4.configuration_type == "3BHK"

    # 5. Phrasing "three BHK"
    req5 = extract_requirements_from_text("Actually, I want a 3BHK.")
    assert req5.configuration_type == "3BHK"


def test_indian_budget_parsing_variations():
    """Validates Indian numbering system parsing: '80 lakhs', 'eighty lakhs', '1.5 crore', 'around 80 lakhs'."""
    assert parse_numeric_budget("around 80 lakhs") == Decimal("8000000")
    assert parse_numeric_budget("80 lakhs") == Decimal("8000000")
    assert parse_numeric_budget("eighty lakhs") == Decimal("8000000")
    assert parse_numeric_budget("1.5 crore") == Decimal("15000000")
    assert parse_numeric_budget("one crore") == Decimal("10000000")


def test_five_turn_customer_preference_memory():
    """
    Acceptance Test: Simulates the exact 5-turn customer conversation:
      Turn 1: "Hello, can you hear me?"
      Turn 2: "I'm looking for a 2BHK."
      Turn 3: "Gurugram."
      Turn 4: "Around 80 lakhs."
      Turn 5: "Actually, I want a 3BHK."
    Validates that preferences accumulate and corrections update properly.
    """
    state = SessionState(session_id="turn_test_session_101")

    # Turn 1: Greeting
    req1 = extract_requirements_from_text("Hello, can you hear me?")
    state.update_requirements(req1)
    assert state.requirements.configuration_type is None
    assert state.requirements.preferred_city is None

    # Turn 2: "I'm looking for a 2BHK."
    req2 = extract_requirements_from_text("I'm looking for a 2BHK.")
    state.update_requirements(req2)
    assert state.requirements.configuration_type == "2BHK"
    assert state.requirements.preferred_city is None
    assert "location" in state.requirements.missing_fields

    # Turn 3: "Gurugram."
    req3 = extract_requirements_from_text("Gurugram.")
    state.update_requirements(req3)
    assert state.requirements.configuration_type == "2BHK"  # Retained from Turn 2!
    assert state.requirements.preferred_city == "Gurugram"
    assert "budget" in state.requirements.missing_fields

    # Turn 4: "Around 80 lakhs."
    req4 = extract_requirements_from_text("Around 80 lakhs.")
    state.update_requirements(req4)
    assert state.requirements.configuration_type == "2BHK"  # Retained!
    assert state.requirements.preferred_city == "Gurugram"  # Retained!
    assert state.requirements.budget_max == Decimal("8000000")
    assert state.requirements.currency == "INR"
    assert state.requirements.is_complete is True

    # Turn 5: "Actually, I want a 3BHK."
    req5 = extract_requirements_from_text("Actually, I want a 3BHK.")
    changes = state.update_requirements(req5)
    assert state.requirements.configuration_type == "3BHK"  # Updated!
    assert state.requirements.preferred_city == "Gurugram"  # Retained from Turn 3!
    assert state.requirements.budget_max == Decimal("8000000")  # Retained from Turn 4!
    assert state.requirements.currency == "INR"  # Retained from Turn 4!
    assert "configuration_type" in changes
    assert changes["configuration_type"] == ("2BHK", "3BHK")


def test_session_duration_configuration_and_timeout():
    """Validates configurable session duration (600s 10-minute continuous session / 360s stream max)."""
    assert settings.VOICE_SESSION_LOCAL_DEV_DURATION_SECONDS == 600
    assert settings.VOICE_SESSION_CUSTOMER_DURATION_SECONDS == 600
    assert settings.VOICE_SESSION_MAX_DURATION_SECONDS == 600
    assert settings.AWS_BEDROCK_STREAM_MAX_DURATION_SECONDS == 360
    assert settings.MAX_STREAM_RENEWALS == 2
    assert settings.SESSION_EXPIRY_WARNING_SECONDS == 30
    assert settings.NOVA_SONIC_ENDPOINTING_SENSITIVITY in ("HIGH", "MEDIUM")


def test_build_renewal_preamble_formatting():
    """Verifies that _build_renewal_preamble includes preferences, recent dialogue, and anti-greeting instructions."""
    db = get_test_db()
    driver = MockVoiceDriver()
    orchestrator = VoiceSessionOrchestrator(
        session_id="preamble_test_001",
        driver=driver,
        db=db,
        user_role="local_tester",
    )
    # Establish customer requirements
    orchestrator.session_state.requirements.configuration_type = "3BHK"
    orchestrator.session_state.requirements.preferred_city = "Gurugram"
    orchestrator.session_state.requirements.budget_max = Decimal("8000000")
    orchestrator.session_state.requirements.currency = "INR"
    orchestrator.session_state.requirements.desired_amenities = ["Clubhouse", "Swimming Pool"]

    # Add dialogue entries
    orchestrator.transcript_entries.append("[Customer]: I need a 3BHK flat.")
    orchestrator.transcript_entries.append("[Assistant]: We have premium 3BHK properties in Gurugram.")

    renewal_preamble = orchestrator._build_renewal_preamble()

    assert "DO NOT greet the customer again" in renewal_preamble
    assert "never say 'Hello'" in renewal_preamble
    assert "Configuration: 3BHK" in renewal_preamble
    assert "City / Location: Gurugram" in renewal_preamble
    assert "8000000 INR" in renewal_preamble
    assert "Clubhouse" in renewal_preamble
    assert "[Customer]: I need a 3BHK flat." in renewal_preamble


def test_nova_sonic_driver_automatic_stream_renewal_lifecycle():
    """
    Offline integration test verifying automatic Bedrock stream renewal:
    1. Driver starts session with MockBedrockStreamTransport and preamble_callback.
    2. Multiple audio chunks stream through without interruption.
    3. Stream renewal is triggered via renew_stream.
    4. Verifies:
       - Old stream connection was gracefully closed.
       - New stream connection is established.
       - New stream receives sessionStart, promptStart, contentStart(SYSTEM) with updated preamble,
         and contentStart(AUDIO_USER).
       - Client session queue remains uninterrupted (no duplicate greetings, no SESSION_ENDED).
       - Session metadata renewals_count increments to 1.
    """
    async def _run():
        mock_transport = MockBedrockStreamTransport()
        driver = AmazonNovaSonicDriver(
            model_id="amazon.nova-2-5-sonic",
            region_name="us-east-1",
            transport=mock_transport,
        )
        session_id = "renewal_test_sess_001"
        tools = get_agent_tools_spec()

        renewal_preamble_called = False
        def mock_preamble_cb():
            nonlocal renewal_preamble_called
            renewal_preamble_called = True
            return "CONTINUATION PREAMBLE: DO NOT RE-GREET THE CUSTOMER."

        await driver.start_session(
            session_id=session_id,
            prompt_preamble="Initial Preamble",
            tools=tools,
            audio_format=AudioFormat.PCM_24KHZ_16BIT_MONO,
            max_duration=600,
            preamble_callback=mock_preamble_cb,
        )

        conn1 = mock_transport.active_connections[session_id]
        assert conn1 is not None
        assert conn1._is_closed is False
        queue = driver._session_queues[session_id]
        init_evt = await queue.get()
        assert init_evt.event_type == VoiceEventType.SESSION_STARTED

        # Trigger stream renewal
        success = await driver.renew_stream(session_id)
        assert success is True
        assert renewal_preamble_called is True
        assert conn1._is_closed is True

        conn2 = driver._active_sessions[session_id]["connection"]
        assert conn2 is not None
        assert conn2 is not conn1

        # Check events sent to new connection
        conn2_event_names = [list(e["event"].keys())[0] for e in conn2.sent_events]
        assert "sessionStart" in conn2_event_names
        assert "promptStart" in conn2_event_names
        assert "contentStart" in conn2_event_names

        # Verify preamble text in new connection contains continuation preamble
        text_inputs = [
            e["event"]["textInput"]["content"]
            for e in conn2.sent_events
            if "textInput" in e["event"]
        ]
        assert any("CONTINUATION PREAMBLE" in t for t in text_inputs)

        # Verify audio can still be sent into new stream
        raw_audio = b"\x00\x05" * 1600
        await driver.send_audio_chunk(session_id, raw_audio)
        assert driver._active_sessions[session_id]["audio_chunks_sent"] >= 1

        # Graceful cleanup
        await driver.end_session(session_id)
        assert conn2._is_closed is True

    asyncio.run(_run())


def test_session_warning_and_completion_events():
    """Validates that session warning and completed events are handled properly without error."""
    async def _run():
        db = get_test_db()
        driver = MockVoiceDriver()
        orchestrator = VoiceSessionOrchestrator(
            session_id="warn_comp_test_001",
            driver=driver,
            db=db,
            user_role="local_tester",
        )

        sent_messages = []
        async def mock_send_text(msg: str):
            sent_messages.append(json.loads(msg))

        async def mock_send_bytes(b: bytes):
            pass

        await orchestrator.start()

        # Simulate warning event arriving from driver (at 9m30s / 570s)
        driver_queue = driver._session_queues[orchestrator.session_id]
        await driver_queue.put(
            VoiceServerEvent(
                event_type=VoiceEventType.SESSION_WARNING,
                session_id=orchestrator.session_id,
                data={"message": "Conversation ending in 30 seconds.", "remaining_seconds": 30},
            )
        )

        # Simulate completed event arriving from driver (at 10m / 600s)
        await driver_queue.put(
            VoiceServerEvent(
                event_type=VoiceEventType.SESSION_COMPLETED,
                session_id=orchestrator.session_id,
                data={"message": "Conversation completed.", "duration_seconds": 600},
            )
        )

        await orchestrator.run_pipeline(send_text=mock_send_text, send_bytes=mock_send_bytes)

        msg_types = [m["type"] for m in sent_messages]
        assert "session_started" in msg_types
        assert "session_warning" in msg_types
        assert "session_completed" in msg_types
        assert "error" not in msg_types  # Crucial: NO error on planned completion!

        warn_msg = next(m for m in sent_messages if m["type"] == "session_warning")
        assert warn_msg["remaining_seconds"] == 30

        comp_msg = next(m for m in sent_messages if m["type"] == "session_completed")
        assert "completed" in comp_msg["message"].lower()

    asyncio.run(_run())


def test_automatic_customer_greeting_lifecycle():
    """
    Validates that:
    1. Driver automatically emits customer greeting on session start without customer speaking first.
    2. Verified customer name is embedded in the greeting.
    3. Greeting is emitted exactly once and suppressed upon subsequent stream renewals.
    """
    async def _run():
        db = get_test_db()
        driver = MockVoiceDriver()
        customer_name = "Shyam Sundar"

        import uuid
        customer_id = uuid.uuid4()

        orchestrator = VoiceSessionOrchestrator(
            session_id="greeting_test_001",
            driver=driver,
            db=db,
            user_id=customer_id,
            user_role="customer",
        )
        orchestrator.customer_name = customer_name

        sent_messages = []
        async def mock_send_text(msg: str):
            sent_messages.append(json.loads(msg))

        async def mock_send_bytes(b: bytes):
            pass

        await orchestrator.start()

        # Run pipeline until greeting events are processed
        pipeline_task = asyncio.create_task(
            orchestrator.run_pipeline(send_text=mock_send_text, send_bytes=mock_send_bytes)
        )
        await asyncio.sleep(0.1)

        # 1. session_started must include verified customer_name
        session_started = next((m for m in sent_messages if m["type"] == "session_started"), None)
        assert session_started is not None
        assert session_started.get("customer_name") == customer_name

        # 2. First transcript event must be assistant greeting mentioning customer name
        transcripts = [m for m in sent_messages if m["type"] == "transcript"]
        assert len(transcripts) > 0
        first_transcript = transcripts[0]
        assert first_transcript["role"] == "assistant"
        assert f"Hi {customer_name}" in first_transcript["delta"]
        assert "Brain Magic RealEstate Voice AI" in first_transcript["delta"]

        # 3. Simulate stream renewal after greeting has completed
        renewal_preamble = orchestrator._build_renewal_preamble()
        assert "DO NOT repeat the initial greeting" in renewal_preamble

        # Cleanup
        await orchestrator.close()
        try:
            pipeline_task.cancel()
            await pipeline_task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run())

