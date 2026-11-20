import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
import jwt

from app.core.config import settings
from app.core.security import create_access_token, decode_access_token
from app.db.session import SessionLocal
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.services.voice.factory import get_voice_driver
from app.services.voice.orchestrator import VoiceSessionOrchestrator

logger = logging.getLogger("voice_websocket")

router = APIRouter(tags=["Voice AI WebSocket"])

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def is_loopback_client(host: Optional[str]) -> bool:
    """
    Checks if client host socket is strictly a local loopback address.
    Never trusts client-supplied forwarded headers (X-Forwarded-For, X-Real-IP).
    """
    if not host:
        return False
    return host in LOOPBACK_HOSTS


def get_db_session() -> SessionLocal:
    """Returns a database session for voice WebSocket processing. Overridable in tests."""
    return SessionLocal()


@router.post("/voice/local-test-session")
async def create_local_voice_test_session(request: Request):
    """
    Temporary Customer-Free Real-Time Voice Testing Mode.
    Provides short-lived authorized test sessions for local loopback development without registration/OTP.
    
    Security Controls:
    1. Only active when settings.LOCAL_VOICE_TEST_MODE is True.
    2. Strictly disabled in production (settings.ENVIRONMENT == 'production').
    3. Loopback restricted: strictly checks request.client.host in ('127.0.0.1', '::1', 'localhost').
       Does NOT trust client-supplied forwarded headers (X-Forwarded-For, etc.).
    4. Grants role 'local_tester' with zero access to CRM customer profiles, leads, or admin routes.
    """
    if not getattr(settings, "LOCAL_VOICE_TEST_MODE", False) or getattr(settings, "ENVIRONMENT", "").lower() == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Local voice test mode is disabled.",
        )

    client_host = request.client.host if request.client else None
    if not is_loopback_client(client_host):
        logger.warning(f"Forbidden local test session request from non-loopback IP: {client_host}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Local voice test mode is strictly restricted to local loopback connections.",
        )

    session_id = f"test_session_{int(datetime.now(timezone.utc).timestamp() * 1000)}"
    token = create_access_token(
        data={
            "sub": f"local_tester_{uuid.uuid4().hex[:8]}",
            "role": "local_tester",
            "is_verified": True,
            "session_id": session_id,
            "is_local_test": True,
        },
        expires_delta=timedelta(minutes=15),
    )

    dataset_name = "Real Estate Master Portfolio (166 verified records)"
    try:
        from app.services.dataset.manager import get_active_dataset
        with get_db_session() as db:
            active_ds = get_active_dataset(db)
            if active_ds:
                dataset_name = f"{active_ds.name} ({active_ds.total_rows} verified records)"
    except Exception:
        pass

    driver_mode = "MOCK" if getattr(settings, "USE_MOCK_VOICE", True) else "LIVE"
    driver_message = (
        "Mock mode — real speech is disabled. Enable live Bedrock Nova Sonic testing to hear real spoken English."
        if driver_mode == "MOCK"
        else f"Live Amazon Nova 2.5 Sonic ({getattr(settings, 'BEDROCK_MODEL_ID', 'amazon.nova-2-5-sonic')}) active in {getattr(settings, 'AWS_REGION', 'ap-northeast-1')}."
    )

    return {
        "session_id": session_id,
        "token": token,
        "mode": "LOCAL_TEST_MODE",
        "dataset_name": dataset_name,
        "expires_in_seconds": 900,
        "driver_mode": driver_mode,
        "driver_message": driver_message,
        "model_id": getattr(settings, "BEDROCK_MODEL_ID", "amazon.nova-2-5-sonic"),
        "aws_region": getattr(settings, "AWS_REGION", "ap-northeast-1"),
    }


@router.websocket("/ws/voice/{session_id}")
async def voice_websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
):
    """
    Bidirectional streaming WebSocket endpoint for real-time voice interactions.
    Supports binary PCM audio frames, JSON control messages, speech-to-text transcript deltas,
    interruption signaling, and agent tool execution.
    
    Security & RBAC:
    - MANDATORY: Initial JSON handshake frame {"type": "auth", "token": "..."} within 5.0 seconds.
      Query-string tokens are completely removed to prevent credential leakage in server/proxy logs.
    - Customer role: interacts with their own voice session.
    - Super Owner role: authorized with audit logging.
    - Admin role: strictly blocked (HTTP/WS 1008 policy violation) from private voice audio/transcripts.
    """
    await websocket.accept()

    # 1. Mandatory Initial Authentication Handshake
    auth_token = None
    try:
        # Wait up to 5.0 seconds for initial auth handshake frame: {"type": "auth", "token": "..."}
        init_msg = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
        data = json.loads(init_msg)
        if isinstance(data, dict) and data.get("type") == "auth":
            auth_token = data.get("token")
        else:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="First message must be an auth handshake: {'type': 'auth', 'token': '...'}",
            )
            return
    except (asyncio.TimeoutError, json.JSONDecodeError, WebSocketDisconnect):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Authentication handshake timeout.")
        return

    if not auth_token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing authentication token.")
        return

    if isinstance(auth_token, str):
        auth_token = auth_token.strip()
        if auth_token.startswith("Bearer "):
            auth_token = auth_token[7:].strip()

    # Validate JWT Token
    try:
        payload = decode_access_token(auth_token)
        user_id_str = payload.get("sub")
        user_role = payload.get("role", "customer")
        user_id = None
        if user_id_str:
            try:
                user_id = uuid.UUID(user_id_str)
            except (ValueError, TypeError):
                user_id = None
    except (jwt.PyJWTError, ValueError) as exc:
        logger.warning(f"WebSocket auth failed for session {session_id}: {exc}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid or expired authentication token.")
        return

    # 2. RBAC Policy Enforcement: Admin is strictly prohibited from accessing private voice sessions
    if user_role == "admin":
        logger.warning(f"Forbidden voice session access attempt by Admin user {user_id}")
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Admins are restricted from accessing live voice audio or customer transcripts.",
        )
        return

    # Check local_tester authorization
    if user_role == "local_tester":
        if not getattr(settings, "LOCAL_VOICE_TEST_MODE", False) or getattr(settings, "ENVIRONMENT", "").lower() == "production":
            logger.warning("Rejected local_tester session: LOCAL_VOICE_TEST_MODE is disabled.")
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Local voice test mode is disabled.",
            )
            return

        client_host = websocket.client.host if websocket.client else None
        if not is_loopback_client(client_host):
            logger.warning(f"Rejected non-loopback local test connection from {client_host}")
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Local voice test mode is strictly restricted to local loopback connections.",
            )
            return

    # 3. Setup Session Dependencies
    db = get_db_session()
    driver = get_voice_driver()

    # Determine customer id and audit user_id
    customer_id = None
    audit_user_id = None
    is_verified = bool(payload.get("is_verified", False))
    cust = None

    if user_role == "customer":
        cid_str = payload.get("customer_id")
        if cid_str:
            try:
                customer_id = uuid.UUID(cid_str)
            except (ValueError, TypeError):
                pass
        if not customer_id and user_id:
            cust = db.query(Customer).filter(
                (Customer.id == user_id) | (Customer.user_id == user_id) | (Customer.email == payload.get("email"))
            ).first()
            if cust:
                customer_id = cust.id
                if "is_verified" not in payload:
                    is_verified = cust.is_verified
        elif customer_id:
            cust = db.get(Customer, customer_id)
            if cust and "is_verified" not in payload:
                is_verified = cust.is_verified

        # Only link audit user_id if the customer has an underlying User account in users table
        if cust and cust.user_id:
            audit_user_id = cust.user_id
    elif user_role == "local_tester":
        customer_id = None
        audit_user_id = None
        is_verified = True
    else:
        audit_user_id = user_id

    # 4. Anti-Hijacking / Session Ownership Enforcement
    existing_conv = db.query(Conversation).filter(Conversation.session_id == session_id).first()
    if existing_conv:
        if user_role == "customer" and existing_conv.customer_id is not None and existing_conv.customer_id != customer_id:
            logger.warning(
                f"Unauthorized session access attempt: Customer {customer_id} tried to hijack session {session_id} "
                f"owned by Customer {existing_conv.customer_id}"
            )
            db.close()
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Session does not belong to the authenticated customer.",
            )
            return

    orchestrator = VoiceSessionOrchestrator(
        session_id=session_id,
        driver=driver,
        db=db,
        customer_id=customer_id,
        user_role=user_role,
        user_id=audit_user_id,
        is_verified=is_verified,
    )

    try:
        await orchestrator.start()

        # Helper callbacks for sending text/binary across WebSocket
        async def send_text_msg(msg: str) -> None:
            try:
                await websocket.send_text(msg)
            except Exception:
                pass

        async def send_binary_bytes(b: bytes) -> None:
            try:
                await websocket.send_bytes(b)
            except Exception:
                pass

        # Launch consumer pipeline
        pipeline_task = asyncio.create_task(
            orchestrator.run_pipeline(send_text=send_text_msg, send_bytes=send_binary_bytes)
        )

        audio_frames_received = 0

        # 4. Bidirectional Ingestion Loop
        while True:
            if not orchestrator.is_active or (pipeline_task.done() and not pipeline_task.cancelled()):
                logger.info(f"[VoiceWS] Session {session_id[:8]}... is no longer active. Halting audio ingestion.")
                break

            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                logger.info(
                    f"[VoiceWS] Client disconnected from session {session_id[:8]}... "
                    f"Total audio frames received: {audio_frames_received}"
                )
                break

            # Process binary audio chunks
            if "bytes" in msg and msg["bytes"]:
                if not orchestrator.is_active:
                    break

                audio_frames_received += 1
                if audio_frames_received <= 3 or audio_frames_received % 25 == 0:
                    logger.info(
                        f"[VoiceWS] Session {session_id[:8]}... received audio frame #{audio_frames_received} "
                        f"({len(msg['bytes'])} bytes)"
                    )
                try:
                    await orchestrator.handle_incoming_audio(msg["bytes"])
                except (ValueError, RuntimeError) as err:
                    await websocket.send_text(json.dumps({"type": "error", "message": str(err)}))
                    break

            # Process JSON control / text messages
            elif "text" in msg and msg["text"]:
                try:
                    payload_json = json.loads(msg["text"])
                    msg_type = payload_json.get("type", "text")

                    if msg_type == "text":
                        content = payload_json.get("content", "")
                        if len(content) > 10000:
                            await websocket.send_text(json.dumps({"type": "error", "message": "Text frame exceeds maximum length limit (10,000 characters)."}))
                            continue
                        await orchestrator.handle_incoming_text(content)

                    elif msg_type == "interrupt":
                        await orchestrator.handle_interruption()

                    elif msg_type == "ping":
                        await websocket.send_text(json.dumps({"type": "pong"}))

                    elif msg_type == "stop":
                        logger.info(f"Client requested graceful session stop for {session_id}")
                        break

                except json.JSONDecodeError:
                    # Raw plain text message
                    if len(msg["text"]) > 10000:
                        await websocket.send_text(json.dumps({"type": "error", "message": "Text frame exceeds maximum length limit (10,000 characters)."}))
                        continue
                    await orchestrator.handle_incoming_text(msg["text"])

    except WebSocketDisconnect:
        logger.info(f"Client disconnected from voice session {session_id}")
    except Exception as exc:
        logger.error(f"Error in voice websocket {session_id}: {exc}")
    finally:
        if 'pipeline_task' in locals() and not pipeline_task.done():
            pipeline_task.cancel()
        try:
            await orchestrator.close()
        except Exception as e:
            logger.warning(f"Error closing orchestrator for {session_id}: {e}")
        finally:
            if hasattr(driver, "release_session"):
                driver.release_session(session_id)
            db.close()
