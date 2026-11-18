import asyncio
import json
import logging
import uuid
from typing import Optional
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
import jwt

from app.core.security import decode_access_token
from app.db.session import SessionLocal
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.services.voice.factory import get_voice_driver
from app.services.voice.orchestrator import VoiceSessionOrchestrator

logger = logging.getLogger("voice_websocket")

router = APIRouter(tags=["Voice AI WebSocket"])


def get_db_session() -> SessionLocal:
    """Returns a database session for voice WebSocket processing. Overridable in tests."""
    return SessionLocal()


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

    # Validate JWT Token
    try:
        payload = decode_access_token(auth_token)
        user_id_str = payload.get("sub")
        user_role = payload.get("role", "customer")
        user_id = uuid.UUID(user_id_str) if user_id_str else None
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

    # 3. Setup Session Dependencies
    db = get_db_session()
    driver = get_voice_driver()

    # Determine customer id if user is customer
    customer_id = None
    is_verified = bool(payload.get("is_verified", False))
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
        user_id=user_id,
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

        # 4. Bidirectional Ingestion Loop
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                break

            # Process binary audio chunks
            if "bytes" in msg and msg["bytes"]:
                try:
                    await orchestrator.handle_incoming_audio(msg["bytes"])
                except ValueError as err:
                    await websocket.send_text(json.dumps({"type": "error", "message": str(err)}))

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
        await orchestrator.close()
        db.close()
