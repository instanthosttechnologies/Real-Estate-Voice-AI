import json
import uuid
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.core.config import settings
from app.core.security import create_access_token
from app.services.voice.mock_driver import MockVoiceDriver
from app.services.voice.orchestrator import VoiceSessionOrchestrator
from app.services.voice.base import VoiceEventType


@pytest.fixture
def client():
    return TestClient(app)


# =============================================================================
# 1. LOCAL VOICE TEST MODE ACTIVATION & HOST SECURITY
# =============================================================================

def test_local_voice_test_mode_disabled_by_default(client):
    """
    By default, LOCAL_VOICE_TEST_MODE is False.
    Access to POST /api/v1/voice/local-test-session must be rejected with HTTP 403.
    """
    with patch.object(settings, "LOCAL_VOICE_TEST_MODE", False):
        response = client.post("/api/v1/voice/local-test-session")
        assert response.status_code == 403
        assert "disabled" in response.json()["detail"].lower()


def test_local_voice_test_mode_forbidden_in_production(client):
    """
    Even if LOCAL_VOICE_TEST_MODE is manually set to True, if ENVIRONMENT is 'production',
    the test session endpoint must strictly return HTTP 403.
    """
    with patch.object(settings, "LOCAL_VOICE_TEST_MODE", True), \
         patch.object(settings, "ENVIRONMENT", "production"):
        response = client.post("/api/v1/voice/local-test-session")
        assert response.status_code == 403
        assert "disabled" in response.json()["detail"].lower()


def test_local_voice_test_mode_rejects_remote_hosts(client):
    """
    Connections from non-loopback IP addresses (e.g. 192.168.1.55, 203.0.113.1)
    must be rejected with HTTP 403.
    """
    with patch.object(settings, "LOCAL_VOICE_TEST_MODE", True), \
         patch.object(settings, "ENVIRONMENT", "development"):
        # TestClient with custom remote client address
        remote_client = TestClient(app, client=("192.168.1.55", 54321))
        response = remote_client.post("/api/v1/voice/local-test-session")
        assert response.status_code == 403
        assert "loopback" in response.json()["detail"].lower()


def test_local_voice_test_mode_rejects_spoofed_forwarded_headers(client):
    """
    Client-supplied forwarded headers (X-Forwarded-For, X-Real-IP) must NEVER be trusted
    to verify localhost. A remote IP with spoofed headers must still be rejected.
    """
    with patch.object(settings, "LOCAL_VOICE_TEST_MODE", True), \
         patch.object(settings, "ENVIRONMENT", "development"):
        remote_client = TestClient(app, client=("203.0.113.195", 43210))
        response = remote_client.post(
            "/api/v1/voice/local-test-session",
            headers={
                "X-Forwarded-For": "127.0.0.1",
                "X-Real-IP": "127.0.0.1",
                "Forwarded": "for=127.0.0.1",
            },
        )
        assert response.status_code == 403
        assert "loopback" in response.json()["detail"].lower()


def test_local_voice_test_mode_grants_token_for_loopback(client):
    """
    When LOCAL_VOICE_TEST_MODE=True and request is from loopback (127.0.0.1),
    returns a short-lived token with role 'local_tester'.
    """
    with patch.object(settings, "LOCAL_VOICE_TEST_MODE", True), \
         patch.object(settings, "ENVIRONMENT", "development"):
        loopback_client = TestClient(app, client=("127.0.0.1", 50000))
        response = loopback_client.post("/api/v1/voice/local-test-session")
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert data["session_id"].startswith("test_session_")
        assert "token" in data
        assert data["mode"] == "LOCAL_TEST_MODE"
        assert "verified records" in data["dataset_name"]


# =============================================================================
# 2. PRIVILEGE ISOLATION: local_tester CANNOT ACCESS PROTECTED RESOURCES
# =============================================================================

def test_local_tester_token_cannot_access_customer_endpoints(client):
    """
    The temporary local_tester token must NOT allow access to private customer data,
    CRM leads, or saved site visits.
    """
    token = create_access_token(
        data={"sub": "local_tester_123", "role": "local_tester", "is_local_test": True}
    )
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Customer profile
    res1 = client.get("/api/v1/customer/profile", headers=headers)
    assert res1.status_code in (401, 403)

    # 2. Customer leads
    res2 = client.get("/api/v1/customer/leads", headers=headers)
    assert res2.status_code in (401, 403)

    # 3. Customer site visits
    res3 = client.get("/api/v1/customer/site-visits", headers=headers)
    assert res3.status_code in (401, 403)


def test_local_tester_token_cannot_access_admin_or_super_owner_endpoints(client):
    """
    The local_tester token must NOT allow access to admin dashboards,
    audit transcripts, or dataset management.
    """
    token = create_access_token(
        data={"sub": "local_tester_123", "role": "local_tester", "is_local_test": True}
    )
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Admin conversations
    res1 = client.get("/api/v1/admin/conversations", headers=headers)
    assert res1.status_code in (401, 403)

    # 2. Super owner audit logs
    res2 = client.get("/api/v1/super-owner/audit-logs", headers=headers)
    assert res2.status_code in (401, 403)

    # 3. Ingestion preview
    res3 = client.post("/api/v1/ingestion/preview", headers=headers)
    assert res3.status_code in (401, 403)


# =============================================================================
# 3. WEBSOCKET SECURITY & LOCAL TEST SESSION LIFECYCLE
# =============================================================================

def test_local_tester_websocket_loopback_connection_succeeds():
    """
    When LOCAL_VOICE_TEST_MODE=True and client connects from loopback,
    the WebSocket accepts the local_tester token and starts the session cleanly.
    """
    with patch.object(settings, "LOCAL_VOICE_TEST_MODE", True), \
         patch.object(settings, "ENVIRONMENT", "development"):
        loopback_client = TestClient(app, client=("127.0.0.1", 51234))
        token = create_access_token(
            data={
                "sub": "local_tester_456",
                "role": "local_tester",
                "is_local_test": True,
                "is_verified": True,
            }
        )
        session_id = f"test_ws_{uuid.uuid4().hex[:8]}"

        with loopback_client.websocket_connect(f"/api/v1/ws/voice/{session_id}") as ws:
            # Send initial auth frame
            ws.send_text(json.dumps({"type": "auth", "token": token}))

            # Expect session_started
            msg1 = ws.receive_json()
            assert msg1.get("type") == "session_started"

            # Graceful stop
            ws.send_text(json.dumps({"type": "stop"}))


def test_local_tester_websocket_remote_connection_rejected():
    """
    When a local_tester token is presented from a remote IP (e.g. 192.168.1.100),
    the WebSocket connection must be immediately closed with WS 1008 policy violation.
    """
    with patch.object(settings, "LOCAL_VOICE_TEST_MODE", True), \
         patch.object(settings, "ENVIRONMENT", "development"):
        remote_client = TestClient(app, client=("192.168.1.100", 51234))
        token = create_access_token(
            data={
                "sub": "local_tester_789",
                "role": "local_tester",
                "is_local_test": True,
                "is_verified": True,
            }
        )
        session_id = f"test_remote_{uuid.uuid4().hex[:8]}"

        with pytest.raises(WebSocketDisconnect) as exc:
            with remote_client.websocket_connect(f"/api/v1/ws/voice/{session_id}") as ws:
                ws.send_text(json.dumps({"type": "auth", "token": token}))
                ws.receive_json()
        assert exc.value.code == 1008


def test_local_tester_websocket_rejected_when_mode_disabled():
    """
    When LOCAL_VOICE_TEST_MODE is False, presenting a local_tester token
    must be rejected with WS 1008 policy violation even from loopback.
    """
    with patch.object(settings, "LOCAL_VOICE_TEST_MODE", False):
        loopback_client = TestClient(app, client=("127.0.0.1", 51234))
        token = create_access_token(
            data={
                "sub": "local_tester_999",
                "role": "local_tester",
                "is_local_test": True,
            }
        )
        session_id = f"test_dis_{uuid.uuid4().hex[:8]}"

        with pytest.raises(WebSocketDisconnect) as exc:
            with loopback_client.websocket_connect(f"/api/v1/ws/voice/{session_id}") as ws:
                ws.send_text(json.dumps({"type": "auth", "token": token}))
                ws.receive_json()
        assert exc.value.code == 1008


# =============================================================================
# 4. DATABASE DRY-RUN PROTECTION FOR local_tester
# =============================================================================

@pytest.mark.asyncio
async def test_local_tester_session_dry_run_protection():
    """
    Validates that a local_tester session wraps the database in DryRunSessionProxy
    and rolls back all transactions on close, guaranteeing zero database writes.
    """
    mock_db = MagicMock()
    mock_driver = MagicMock()
    session_id = f"test_dry_{uuid.uuid4().hex[:8]}"

    orchestrator = VoiceSessionOrchestrator(
        session_id=session_id,
        driver=mock_driver,
        db=mock_db,
        user_role="local_tester",
    )

    # Verify dry-run proxy was initialized
    from app.services.voice.orchestrator import DryRunSessionProxy
    assert isinstance(orchestrator.db, DryRunSessionProxy)

    # Simulate close
    orchestrator.is_active = True
    await orchestrator.close()

    # Verify mock_db.commit() was NEVER called, and rollback was called
    mock_db.commit.assert_not_called()
    mock_db.rollback.assert_called()
