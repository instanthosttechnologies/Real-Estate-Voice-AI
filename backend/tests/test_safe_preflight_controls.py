import asyncio
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.config import settings
from app.services.voice.factory import get_voice_driver
from app.services.voice.mock_driver import MockVoiceDriver
from app.services.voice.nova_sonic_driver import AmazonNovaSonicDriver
from app.services.voice.orchestrator import VoiceSessionOrchestrator
from app.services.voice.bedrock_streaming import MockBedrockStreamTransport


@pytest.mark.asyncio
async def test_use_mock_voice_default():
    """Verify USE_MOCK_VOICE is true by default and returns MockVoiceDriver."""
    from app.core.config import Settings
    assert Settings.model_fields["USE_MOCK_VOICE"].default is True
    with patch.object(settings, "USE_MOCK_VOICE", True):
        driver = get_voice_driver()
        assert isinstance(driver, MockVoiceDriver)
        assert driver.model_id == "amazon.nova-2-5-sonic"


@pytest.mark.asyncio
async def test_live_test_requires_explicit_approval():
    """Verify live driver activation fails without LIVE_TEST_APPROVED=True."""
    with patch.object(settings, "USE_MOCK_VOICE", False):
        with patch.object(settings, "LIVE_TEST_APPROVED", False):
            with pytest.raises(PermissionError) as exc_info:
                get_voice_driver()
            assert "LIVE_TEST_APPROVED is False" in str(exc_info.value)


@pytest.mark.asyncio
async def test_live_driver_concurrency_ceiling():
    """Verify maximum concurrent live test sessions limit (default 1)."""
    AmazonNovaSonicDriver._active_live_session_ids.clear()

    mock_transport = MockBedrockStreamTransport()
    driver = AmazonNovaSonicDriver(transport=mock_transport)

    session_1 = f"live_session_{uuid.uuid4().hex[:8]}"
    session_2 = f"live_session_{uuid.uuid4().hex[:8]}"

    # Start session 1
    await driver.start_session(session_id=session_1, prompt_preamble="test", tools=[])
    assert session_1 in AmazonNovaSonicDriver._active_live_session_ids

    # Attempting to start session 2 must be rejected by concurrency safety latch
    with pytest.raises(RuntimeError) as exc_info:
        await driver.start_session(session_id=session_2, prompt_preamble="test", tools=[])
    assert "limit reached" in str(exc_info.value)

    # End session 1 and verify lock is released
    await driver.end_session(session_1)
    assert session_1 not in AmazonNovaSonicDriver._active_live_session_ids

    # Session 2 can now start cleanly
    await driver.start_session(session_id=session_2, prompt_preamble="test", tools=[])
    assert session_2 in AmazonNovaSonicDriver._active_live_session_ids
    await driver.end_session(session_2)

    AmazonNovaSonicDriver._active_live_session_ids.clear()


@pytest.mark.asyncio
async def test_dry_run_test_mode_skips_database_write():
    """Verify DRY_RUN_TEST_MODE prevents database commits during preflight/live tests."""
    mock_db = MagicMock()
    mock_driver = MagicMock()
    mock_driver.end_session = AsyncMock()

    orchestrator = VoiceSessionOrchestrator(
        session_id=f"dry_run_{uuid.uuid4().hex[:8]}",
        driver=mock_driver,
        db=mock_db,
    )
    orchestrator.is_active = True

    with patch.object(settings, "DRY_RUN_TEST_MODE", True):
        await orchestrator.close()

    # DB add/commit must NOT have been called
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_called()
    mock_driver.end_session.assert_awaited_once()


@pytest.mark.asyncio
async def test_dry_run_test_mode_intercepts_tool_commits():
    """Verify DRY_RUN_TEST_MODE intercepts tool commits, flushing in memory and rolling back on close."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.base import Base
    from app.services.agent.dispatcher import dispatch_agent_tool
    from app.models.lead import Lead

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    db = TestSession()

    mock_driver = MagicMock()
    mock_driver.end_session = AsyncMock()
    session_id = f"dry_run_tool_{uuid.uuid4().hex[:8]}"

    with patch.object(settings, "DRY_RUN_TEST_MODE", True):
        orchestrator = VoiceSessionOrchestrator(
            session_id=session_id,
            driver=mock_driver,
            db=db,
        )
        orchestrator.is_active = True

        # Dispatch create_lead tool through orchestrator's proxy session
        unique_phone = f"+9198888{uuid.uuid4().hex[:5]}"
        tool_resp = dispatch_agent_tool(
            db=orchestrator.db,
            tool_name="create_lead",
            raw_arguments={
                "full_name": "Dry Run Tester",
                "phone": unique_phone,
                "email": "dryrun@example.com",
                "requirements": {"preferred_location": "OMR", "bhk": 2},
            },
        )
        assert tool_resp.success is True
        assert "lead_id" in tool_resp.data

        # Close session (triggers rollback)
        await orchestrator.close()

    # Verify that in a fresh clean query, this customer/lead was NOT persisted to disk/db
    from app.models.customer import Customer
    fresh_session = TestSession()
    persisted_cust = fresh_session.query(Customer).filter(Customer.phone == unique_phone).first()
    assert persisted_cust is None, "Customer was persisted to database during DRY_RUN_TEST_MODE!"


@pytest.mark.asyncio
async def test_runtime_watchdog_timeout_enforced():
    """Verify runtime watchdog task enforces hard session ceiling and emits SessionTimeout."""
    from app.services.voice.base import VoiceEventType

    mock_transport = MockBedrockStreamTransport()
    driver = AmazonNovaSonicDriver(transport=mock_transport)
    session_id = f"watchdog_{uuid.uuid4().hex[:8]}"

    # Use a 0.2 second timeout ceiling
    with patch.object(settings, "LIVE_TEST_MAX_SESSION_SECONDS", 0.2):
        await driver.start_session(session_id=session_id, prompt_preamble="test", tools=[])
        assert session_id in AmazonNovaSonicDriver._active_live_session_ids

        # Wait for watchdog to fire
        await asyncio.sleep(0.35)

        # Verify session has ended and lock is released
        assert session_id not in AmazonNovaSonicDriver._active_live_session_ids

        # Verify SessionTimeout event was delivered to queue
        queue = driver._session_queues[session_id]
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        error_events = [e for e in events if e.event_type == VoiceEventType.ERROR]
        assert len(error_events) > 0
        assert error_events[0].data.get("error_type") == "SessionTimeout"

