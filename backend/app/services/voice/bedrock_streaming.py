import asyncio
import base64
import binascii
import json
import logging
import struct
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple

import botocore.eventstream

from app.core.config import settings
from app.services.voice.base import (
    AudioFormat,
    AudioOutputPayload,
    ToolUseRequestPayload,
    TranscriptDeltaPayload,
    VoiceEventType,
    VoiceServerEvent,
)

logger = logging.getLogger("bedrock_streaming")


# =============================================================================
# AWS EventStream Binary Codec
# =============================================================================

class AWSEventStreamCodec:
    """
    Implements AWS EventStream binary wire framing, header serialization,
    and CRC32 checksum generation/validation as specified by AWS.
    
    Wire Framing Specification:
      - Prelude (12 bytes):
          total_length (uint32 big-endian)
          headers_length (uint32 big-endian)
          prelude_crc (uint32 big-endian, CRC32 of first 8 bytes)
      - Headers (headers_length bytes):
          header_name_length (uint8) + header_name (UTF-8) +
          header_value_type (uint8, 7=String, 6=Bytes) +
          value_length (uint16 big-endian) + value_bytes
      - Payload (total_length - 12 - headers_length - 4 bytes)
      - Message CRC (uint32 big-endian, CRC32 of prelude + headers + payload)
    """

    HEADER_TYPE_STRING = 7
    HEADER_TYPE_BYTES = 6

    @classmethod
    def encode_header(cls, name: str, value: Any) -> bytes:
        name_bytes = name.encode("utf-8")
        if len(name_bytes) > 255:
            raise ValueError(f"Header name too long ({len(name_bytes)} bytes > 255): {name}")

        val_str = None
        val_bytes = None
        if hasattr(value, "value_as_string"):
            val_str = value.value_as_string()
        elif hasattr(value, "value_as_byte_buf"):
            val_bytes = bytes(value.value_as_byte_buf())
        elif isinstance(value, str):
            val_str = value
        elif isinstance(value, (bytes, bytearray)):
            val_bytes = bytes(value)
        else:
            val_str = str(value)

        if val_str is not None:
            raw_val = val_str.encode("utf-8")
            h_type = cls.HEADER_TYPE_STRING
        else:
            raw_val = val_bytes
            h_type = cls.HEADER_TYPE_BYTES

        if len(raw_val) > 65535:
            raise ValueError(f"Header value too long ({len(raw_val)} bytes > 65535)")

        return (
            struct.pack(">B", len(name_bytes))
            + name_bytes
            + struct.pack(">B", h_type)
            + struct.pack(">H", len(raw_val))
            + raw_val
        )

    @classmethod
    def encode_message(
        cls,
        payload: bytes,
        headers: Optional[Dict[str, Any]] = None,
        message_type: str = "event",
        event_type: str = "chunk",
        content_type: str = "application/json",
    ) -> bytes:
        """
        Frames raw payload bytes into an AWS EventStream binary message
        with headers and CRC32 checksums.
        """
        hdrs: Dict[str, Any] = {
            ":message-type": message_type,
            ":event-type": event_type,
            ":content-type": content_type,
        }
        if headers:
            hdrs.update(headers)

        encoded_hdrs = b"".join(cls.encode_header(k, v) for k, v in hdrs.items())
        headers_len = len(encoded_hdrs)
        total_len = 12 + headers_len + len(payload) + 4

        prelude_without_crc = struct.pack(">II", total_len, headers_len)
        prelude_crc = struct.pack(">I", binascii.crc32(prelude_without_crc) & 0xFFFFFFFF)
        prelude_full = prelude_without_crc + prelude_crc

        body = prelude_full + encoded_hdrs + payload
        message_crc = struct.pack(">I", binascii.crc32(body) & 0xFFFFFFFF)
        return body + message_crc

    @classmethod
    def decode_messages(cls, data: bytes) -> List[Dict[str, Any]]:
        """
        Parses binary stream data using botocore.eventstream.EventStreamBuffer,
        validating CRC32 and unpacking payload and headers.
        """
        buf = botocore.eventstream.EventStreamBuffer()
        buf.add_data(data)
        messages = []
        for msg in buf:
            headers = msg.headers
            raw_payload = msg.payload
            content_type = headers.get(":content-type", "")
            if "json" in content_type:
                try:
                    payload = json.loads(raw_payload.decode("utf-8"))
                except Exception:
                    payload = raw_payload
            else:
                payload = raw_payload
            messages.append({"headers": headers, "payload": payload})
        return messages


# =============================================================================
# 1. Event Serializer for Amazon Nova Sonic Bidirectional Streaming
# =============================================================================

class BedrockNovaSonicSerializer:
    """
    Serializes application events into Amazon Bedrock Nova Sonic
    bidirectional streaming event payloads over HTTP/2 EventStream.
    
    Protocol Event Hierarchy:
      1. sessionStart (inference configuration)
      2. promptStart (voice, audio config, tool definitions)
      3. contentStart (SYSTEM text prompt) -> textInput -> contentEnd
      4. contentStart (USER audio input) -> continuous audioInput chunks
      5. contentStart (TOOL result) -> toolResult -> contentEnd
      6. contentEnd -> promptEnd -> sessionEnd
    """

    @staticmethod
    def serialize_session_start(
        max_tokens: int = 1024,
        temperature: float = 0.7,
        top_p: float = 0.9,
    ) -> Dict[str, Any]:
        """Constructs the initial sessionStart event."""
        return {
            "event": {
                "sessionStart": {
                    "inferenceConfiguration": {
                        "maxTokens": max_tokens,
                        "temperature": temperature,
                        "topP": top_p,
                    }
                }
            }
        }

    @staticmethod
    def serialize_prompt_start(
        prompt_name: str,
        tools: List[Dict[str, Any]],
        voice_id: str = "matthew",
        output_sample_rate: int = 24000,
    ) -> Dict[str, Any]:
        """Constructs the promptStart event containing voice settings and tool definitions."""
        prompt_def: Dict[str, Any] = {
            "promptName": prompt_name,
            "textOutputConfiguration": {"mediaType": "text/plain"},
            "audioOutputConfiguration": {
                "mediaType": "audio/lpcm",
                "sampleRateHertz": output_sample_rate,
                "sampleSizeBits": 16,
                "channelCount": 1,
                "voiceId": voice_id,
                "encoding": "base64",
                "audioType": "SPEECH",
            },
            "toolUseOutputConfiguration": {
                "mediaType": "application/json"
            },
        }

        if tools:
            prompt_def["toolConfiguration"] = {
                "tools": tools
            }

        return {
            "event": {
                "promptStart": prompt_def
            }
        }

    @staticmethod
    def serialize_system_content_start(
        prompt_name: str,
        content_name: str = "system-preamble",
    ) -> Dict[str, Any]:
        """Opens a SYSTEM role content container for system instructions."""
        return {
            "event": {
                "contentStart": {
                    "promptName": prompt_name,
                    "contentName": content_name,
                    "type": "TEXT",
                    "role": "SYSTEM",
                }
            }
        }

    @staticmethod
    def serialize_text_input(
        prompt_name: str,
        content_name: str,
        text: str,
    ) -> Dict[str, Any]:
        """Serializes text content inside an active text content container."""
        return {
            "event": {
                "textInput": {
                    "promptName": prompt_name,
                    "contentName": content_name,
                    "content": text,
                }
            }
        }

    @staticmethod
    def serialize_audio_content_start(
        prompt_name: str,
        content_name: str,
        sample_rate: int = 24000,
    ) -> Dict[str, Any]:
        """Opens a USER role content container for real-time continuous audio streaming."""
        return {
            "event": {
                "contentStart": {
                    "promptName": prompt_name,
                    "contentName": content_name,
                    "type": "AUDIO",
                    "interactive": True,
                    "role": "USER",
                    "audioInputConfiguration": {
                        "mediaType": "audio/lpcm",
                        "sampleRateHertz": sample_rate,
                        "sampleSizeBits": 16,
                        "channelCount": 1,
                        "audioType": "SPEECH",
                        "encoding": "base64",
                    },
                }
            }
        }

    @staticmethod
    def serialize_audio_input(
        prompt_name: str,
        content_name: str,
        audio_bytes: bytes,
    ) -> Dict[str, Any]:
        """Serializes a raw PCM binary audio chunk as a base64 audioInput event."""
        encoded_audio = base64.b64encode(audio_bytes).decode("utf-8")
        return {
            "event": {
                "audioInput": {
                    "promptName": prompt_name,
                    "contentName": content_name,
                    "content": encoded_audio,
                }
            }
        }

    @staticmethod
    def serialize_tool_result_content_start(
        prompt_name: str,
        tool_use_id: str,
    ) -> Dict[str, Any]:
        """Opens a TOOL role content container for returning tool execution results."""
        return {
            "event": {
                "contentStart": {
                    "promptName": prompt_name,
                    "contentName": tool_use_id,
                    "type": "TOOL",
                    "role": "TOOL",
                }
            }
        }

    @staticmethod
    def serialize_tool_result(
        prompt_name: str,
        tool_use_id: str,
        result: Dict[str, Any],
        is_error: bool = False,
    ) -> Dict[str, Any]:
        """Serializes the executed tool result payload back into the stream."""
        return {
            "event": {
                "toolResult": {
                    "promptName": prompt_name,
                    "contentName": tool_use_id,
                    "content": json.dumps(result, default=str),
                    "status": "error" if is_error else "success",
                }
            }
        }

    @staticmethod
    def serialize_content_end(
        prompt_name: str,
        content_name: str,
    ) -> Dict[str, Any]:
        """Closes an active content container block."""
        return {
            "event": {
                "contentEnd": {
                    "promptName": prompt_name,
                    "contentName": content_name,
                }
            }
        }

    @staticmethod
    def serialize_prompt_end(prompt_name: str) -> Dict[str, Any]:
        """Signals the completion of an active prompt turn."""
        return {
            "event": {
                "promptEnd": {
                    "promptName": prompt_name
                }
            }
        }

    @staticmethod
    def serialize_session_end() -> Dict[str, Any]:
        """Gracefully closes the bidirectional streaming session."""
        return {
            "event": {
                "sessionEnd": {}
            }
        }


# =============================================================================
# 2. Event Parser for Amazon Nova Sonic Inbound EventStream
# =============================================================================

class BedrockNovaSonicParser:
    """
    Parses inbound Bedrock Nova Sonic streaming event chunks into
    application-level VoiceServerEvent objects.
    """

    @staticmethod
    def parse_event(
        raw_event: Dict[str, Any],
        session_id: str,
    ) -> Optional[VoiceServerEvent]:
        """
        Translates raw Bedrock streaming JSON event into standard VoiceServerEvent.
        Supports:
          - audioOutput (base64 PCM speech synthesis)
          - textOutput (companion transcript deltas)
          - toolUse (function calling requests)
          - contentEnd / promptEnd (turn boundary signaling)
          - error exceptions (throttling, validation, stream error)
        """
        event_dict = raw_event.get("event", raw_event)

        # 1. Synthesized Audio Output
        if "audioOutput" in event_dict:
            audio_info = event_dict["audioOutput"]
            raw_b64 = audio_info.get("content", "")
            try:
                audio_bytes = base64.b64decode(raw_b64)
                sample_rate = audio_info.get("sampleRateHertz", 24000)
                return VoiceServerEvent(
                    event_type=VoiceEventType.AUDIO_OUTPUT,
                    session_id=session_id,
                    audio_payload=AudioOutputPayload(
                        audio_bytes=audio_bytes,
                        sample_rate=sample_rate,
                        channels=1,
                        format="pcm_s16le",
                    ),
                )
            except Exception as e:
                logger.error(f"Failed to decode audioOutput chunk: {e}")
                return None

        # 2. Companion Text Output / Transcript Delta
        if "textOutput" in event_dict:
            text_info = event_dict["textOutput"]
            role = text_info.get("role", "ASSISTANT").lower()
            content = text_info.get("content", "")
            return VoiceServerEvent(
                event_type=VoiceEventType.TRANSCRIPT_DELTA,
                session_id=session_id,
                transcript_payload=TranscriptDeltaPayload(
                    role=role,
                    delta=content,
                    is_final=False,
                ),
            )

        # 3. Model Tool Use Request
        if "toolUse" in event_dict:
            tool_info = event_dict["toolUse"]
            tool_name = tool_info.get("toolName", "")
            tool_use_id = tool_info.get("toolUseId", str(uuid.uuid4()))
            raw_content = tool_info.get("content", {})

            # Arguments may arrive as stringified JSON or dict
            if isinstance(raw_content, str):
                try:
                    arguments = json.loads(raw_content)
                except json.JSONDecodeError:
                    arguments = {"raw_content": raw_content}
            elif isinstance(raw_content, dict):
                arguments = raw_content
            else:
                arguments = {}

            return VoiceServerEvent(
                event_type=VoiceEventType.TOOL_USE_REQUEST,
                session_id=session_id,
                tool_request_payload=ToolUseRequestPayload(
                    tool_name=tool_name,
                    tool_use_id=tool_use_id,
                    arguments=arguments,
                ),
            )

        # 4. Turn Completion / Content End
        if "contentEnd" in event_dict:
            return VoiceServerEvent(
                event_type=VoiceEventType.TRANSCRIPT_DELTA,
                session_id=session_id,
                transcript_payload=TranscriptDeltaPayload(
                    role="assistant",
                    delta="",
                    is_final=True,
                ),
            )

        # 5. Service Exceptions & Errors
        for err_key in [
            "modelStreamErrorException",
            "throttlingException",
            "validationException",
            "accessDeniedException",
            "internalServerException",
            "modelTimeoutException",
            "serviceUnavailableException",
            "serviceQuotaExceededException",
            "resourceNotFoundException",
            "modelNotReadyException",
            "modelErrorException",
        ]:
            if err_key in event_dict:
                err_msg = event_dict[err_key].get("message", f"Bedrock stream error: {err_key}")
                logger.error(f"Bedrock stream error in session {session_id}: {err_key} - {err_msg}")
                return VoiceServerEvent(
                    event_type=VoiceEventType.ERROR,
                    session_id=session_id,
                    data={"error_type": err_key, "message": err_msg},
                )

        return None


# =============================================================================
# 3. Transport Abstraction: BedrockStreamTransport
# =============================================================================

class BedrockStreamConnection(ABC):
    """Represents an active bidirectional stream connection with Bedrock."""

    @abstractmethod
    async def send_event(self, event_dict: Dict[str, Any]) -> None:
        """Sends an event payload down the stream to Bedrock."""
        pass

    @abstractmethod
    async def receive_events(self) -> AsyncIterator[Dict[str, Any]]:
        """Asynchronously iterates through inbound event payloads from Bedrock."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Closes the stream connection and releases all resources."""
        pass


class BedrockStreamTransport(ABC):
    """Factory interface for creating Bedrock bidirectional stream connections."""

    @abstractmethod
    async def open_stream(
        self,
        model_id: str,
        region: str,
        session_id: str,
    ) -> BedrockStreamConnection:
        pass


# =============================================================================
# 4. Production AWS CRT Transport (Real Bedrock HTTP/2 Duplex Stream)
# =============================================================================

import os
import botocore.session
from botocore.credentials import Credentials, ReadOnlyCredentials


def resolve_aws_credentials(
    profile_name: Optional[str] = None,
    access_key_id: Optional[str] = None,
    secret_access_key: Optional[str] = None,
    session_token: Optional[str] = None,
    botocore_session: Optional[Any] = None,
) -> Optional[Any]:
    """
    Resolves AWS credentials adhering to the standard AWS SDK credential provider chain,
    supporting configured AWS profiles, environment variables, STS session tokens, and
    backward-compatible explicit credential injection.
    
    Resolution Order:
    1. Explicit credentials passed in parameters or configured in settings.
    2. Botocore Session credential provider chain (using configured profile or default chain).
    
    Returns a credentials snapshot with .access_key, .secret_key, and .token,
    or None if no credentials can be located. Never exposes secrets in logs.
    """
    # 1. Explicit credentials (backward compatibility and test injection)
    eff_access_key = access_key_id or getattr(settings, "AWS_ACCESS_KEY_ID", None)
    eff_secret_key = secret_access_key or getattr(settings, "AWS_SECRET_ACCESS_KEY", None)
    eff_session_token = session_token or getattr(settings, "AWS_SESSION_TOKEN", None)

    if eff_access_key and eff_secret_key:
        return Credentials(
            eff_access_key,
            eff_secret_key,
            token=eff_session_token,
        )

    # 2. AWS SDK Provider Chain via botocore.session
    eff_profile = profile_name or getattr(settings, "AWS_PROFILE", None) or os.getenv("AWS_PROFILE")

    try:
        if botocore_session is not None:
            b_session = botocore_session
        elif eff_profile:
            b_session = botocore.session.Session(profile=eff_profile)
        else:
            b_session = botocore.session.get_session()

        raw_creds = b_session.get_credentials()
        if raw_creds is not None:
            if hasattr(raw_creds, "get_frozen_credentials"):
                return raw_creds.get_frozen_credentials()
            return raw_creds
    except Exception as exc:
        logger.warning(f"Error resolving AWS credentials via botocore provider chain: {exc}")

    return None


class BedrockCRTStreamTransport(BedrockStreamTransport):
    """
    Production transport utilizing AWS Common Runtime (awscrt) to establish
    HTTP/2 duplex bidirectional streaming with Amazon Bedrock.
    Supports standard AWS SDK credential chain (named profiles, IAM SSO, instance roles)
    as well as backward-compatible explicit credentials.
    """

    def __init__(
        self,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        session_token: Optional[str] = None,
        profile_name: Optional[str] = None,
        botocore_session: Optional[Any] = None,
        connection_factory: Optional[Callable] = None,
    ):
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.session_token = session_token
        self.profile_name = profile_name or getattr(settings, "AWS_PROFILE", None)
        self.botocore_session = botocore_session
        self.connection_factory = connection_factory

    def get_credentials(self) -> Optional[Any]:
        """Resolves current valid AWS credentials using provider chain or explicit parameters."""
        return resolve_aws_credentials(
            profile_name=self.profile_name,
            access_key_id=self.access_key_id,
            secret_access_key=self.secret_access_key,
            session_token=self.session_token,
            botocore_session=self.botocore_session,
        )

    async def open_stream(
        self,
        model_id: str,
        region: str,
        session_id: str,
    ) -> BedrockStreamConnection:
        # Strictly verify credentials before attempting any network call
        creds = self.get_credentials()
        if not creds or not getattr(creds, "access_key", None) or not getattr(creds, "secret_key", None):
            raise RuntimeError(
                "AWS credentials not configured. Configure an AWS profile (e.g., AWS_PROFILE=realestate-nova), "
                "set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env, or use USE_MOCK_VOICE=True for offline development."
            )

        endpoint = f"bedrock-runtime.{region}.amazonaws.com"
        path = f"/model/{model_id}/invoke-with-bidirectional-stream"
        logger.info(f"Opening Bedrock CRT bidirectional stream to {endpoint}{path} for session {session_id} (region: {region})")

        conn = _CRTBedrockStreamConnection(
            endpoint=endpoint,
            path=path,
            region=region,
            credentials=creds,
            credentials_resolver=self.get_credentials,
            connection_factory=self.connection_factory,
        )
        await conn.connect()
        return conn


class _CRTBedrockStreamConnection(BedrockStreamConnection):
    """
    Production HTTP/2 duplex connection managed via awscrt with AWS EventStream binary wire framing.
    Supports persistent bidirectional streaming with active frame transmission, SigV4 authorization,
    fragmented/concatenated chunk decoding, and clean lifecycle management.
    """

    def __init__(
        self,
        endpoint: str,
        path: str,
        region: str,
        credentials: Optional[Any] = None,
        credentials_resolver: Optional[Callable[[], Optional[Any]]] = None,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        session_token: Optional[str] = None,
        connection_factory: Optional[Callable] = None,
    ):
        self.endpoint = endpoint
        self.path = path
        self.region = region
        self.credentials = credentials
        self.credentials_resolver = credentials_resolver
        self.access_key_id = access_key_id or (getattr(credentials, "access_key", None) if credentials else None)
        self.secret_access_key = secret_access_key or (getattr(credentials, "secret_key", None) if credentials else None)
        self.session_token = session_token or (getattr(credentials, "token", None) if credentials else None)
        self._connection_factory = connection_factory

        self._inbound_queue: asyncio.Queue = asyncio.Queue()
        self._is_closed: bool = False
        self._http2_conn: Optional[Any] = None
        self._http2_stream: Optional[Any] = None
        self._stream_buffer = botocore.eventstream.EventStreamBuffer()
        self.sent_frames: List[bytes] = []
        self.response_status_code: Optional[int] = None
        self.response_headers: List[Tuple[str, str]] = []

    def _create_signed_request(self) -> Any:
        """Constructs an HttpRequest with AWS SigV4 authorization headers."""
        import awscrt.http as crt_http
        import botocore.auth as b_auth
        from botocore.awsrequest import AWSRequest
        from botocore.credentials import Credentials

        # Resolve active credentials snapshot (refreshed if resolver is present)
        current_creds = None
        if self.credentials_resolver:
            try:
                current_creds = self.credentials_resolver()
            except Exception:
                current_creds = None

        if not current_creds:
            if self.credentials and hasattr(self.credentials, "get_frozen_credentials"):
                current_creds = self.credentials.get_frozen_credentials()
            elif self.credentials:
                current_creds = self.credentials
            elif self.access_key_id and self.secret_access_key:
                current_creds = Credentials(
                    self.access_key_id,
                    self.secret_access_key,
                    token=self.session_token,
                )

        if not current_creds or not getattr(current_creds, "access_key", None) or not getattr(current_creds, "secret_key", None):
            raise RuntimeError("Cannot sign Bedrock request: No valid AWS credentials found.")

        headers_dict = {
            "Host": self.endpoint,
            "Content-Type": "application/vnd.amazon.eventstream",
            "Accept": "application/vnd.amazon.eventstream",
            "User-Agent": "RealEstate-Agentic-Voice-AI/1.0",
        }
        if getattr(current_creds, "token", None):
            headers_dict["X-Amz-Security-Token"] = current_creds.token

        aws_req = AWSRequest(
            method="POST",
            url=f"https://{self.endpoint}{self.path}",
            headers=headers_dict,
        )
        sigv4 = b_auth.SigV4Auth(current_creds, "bedrock", self.region)
        sigv4.add_auth(aws_req)

        signed_headers = [(k, v) for k, v in aws_req.headers.items()]
        return crt_http.HttpRequest(
            method="POST",
            path=self.path,
            headers=crt_http.HttpHeaders(signed_headers),
        )

    async def connect(self) -> None:
        """Establishes TLS HTTP/2 duplex connection and activates the signed stream."""
        signed_request = self._create_signed_request()

        if self._connection_factory:
            res = self._connection_factory()
            if asyncio.iscoroutine(res):
                self._http2_conn = await res
            else:
                self._http2_conn = res
        else:
            import awscrt.http as http
            import awscrt.io as io

            socket_options = io.SocketOptions()
            tls_ctx_opt = io.TlsContextOptions()
            tls_ctx = io.ClientTlsContext(tls_ctx_opt)
            tls_conn_opt = io.TlsConnectionOptions(tls_ctx)
            tls_conn_opt.server_name = self.endpoint
            tls_conn_opt.set_alpn_list(["h2"])

            conn_future = http.HttpClientConnection.new(
                host_name=self.endpoint,
                port=443,
                socket_options=socket_options,
                tls_connection_options=tls_conn_opt,
            )
            if hasattr(conn_future, "done") and conn_future.done():
                self._http2_conn = conn_future.result()
            elif hasattr(conn_future, "result") and not asyncio.iscoroutine(conn_future):
                self._http2_conn = await asyncio.wrap_future(conn_future)
            elif asyncio.iscoroutine(conn_future):
                self._http2_conn = await conn_future

        def on_response(http_stream, status_code, headers, **kwargs):
            self.response_status_code = status_code
            self.response_headers = headers
            if status_code != 200:
                logger.error(f"Bedrock stream returned HTTP {status_code}: {headers}")
                self._inbound_queue.put_nowait({
                    "event": {
                        "modelStreamErrorException": {
                            "message": f"Bedrock HTTP/2 stream error: status code {status_code}"
                        }
                    }
                })

        def on_body(http_stream, chunk, **kwargs):
            self.feed_raw_bytes(chunk)

        self._http2_stream = self._http2_conn.request(
            signed_request,
            on_response=on_response,
            on_body=on_body,
            manual_write=True,
        )
        self._http2_stream.activate()

    async def send_event(self, event_dict: Dict[str, Any]) -> None:
        """
        Encodes event payload into AWS EventStream binary message and
        transmits it actively down the full-duplex HTTP/2 connection.
        Never silently buffers outgoing events.
        """
        if self._is_closed:
            raise RuntimeError("Cannot send event to a closed Bedrock stream connection.")
        if not self._http2_stream:
            raise ConnectionError("Bedrock HTTP/2 duplex stream is not connected or active.")

        payload_bytes = json.dumps(event_dict, default=str).encode("utf-8")
        # Frame event using AWS EventStream binary wire specification
        frame_bytes = AWSEventStreamCodec.encode_message(
            payload=payload_bytes,
            headers={
                ":message-type": "event",
                ":event-type": "chunk",
                ":content-type": "application/json",
            },
        )
        self.sent_frames.append(frame_bytes)

        # Actively transmit frame over the HTTP/2 stream
        write_future = self._http2_stream.write_data(frame_bytes, end_stream=False)
        if hasattr(write_future, "done") and write_future.done():
            write_future.result()
        elif hasattr(write_future, "result") and not asyncio.iscoroutine(write_future):
            await asyncio.wrap_future(write_future)
        elif asyncio.iscoroutine(write_future):
            await write_future
        logger.debug(f"Transmitted EventStream binary chunk ({len(frame_bytes)} bytes, payload: {len(payload_bytes)} bytes)")

    def feed_raw_bytes(self, chunk: bytes) -> None:
        """
        Feeds raw bytes received from HTTP/2 DATA frames into the EventStream decoder
        and enqueues decoded event payloads into the inbound queue.
        Supports both fragmented frames and multiple concatenated frames in a chunk.
        """
        if self._is_closed or not chunk:
            return
        try:
            self._stream_buffer.add_data(chunk)
            for msg in self._stream_buffer:
                headers = msg.headers
                content_type = headers.get(":content-type", "")
                if "json" in content_type:
                    try:
                        payload = json.loads(msg.payload.decode("utf-8"))
                    except Exception:
                        payload = {"raw_payload": msg.payload}
                else:
                    payload = {"raw_payload": msg.payload}

                # Check for Bedrock error headers
                msg_type = headers.get(":message-type", "")
                if msg_type in ("exception", "error"):
                    err_type = headers.get(":exception-type", "modelStreamErrorException")
                    payload = {
                        "event": {
                            err_type: {
                                "message": payload.get("message", f"Stream error: {err_type}")
                            }
                        }
                    }

                self._inbound_queue.put_nowait(payload)
        except Exception as exc:
            logger.error(f"Error parsing inbound EventStream frame: {exc}")

    async def receive_events(self) -> AsyncIterator[Dict[str, Any]]:
        while not self._is_closed:
            event = await self._inbound_queue.get()
            if event is None:
                break
            yield event

    async def close(self) -> None:
        if self._is_closed:
            return
        self._is_closed = True

        if self._http2_stream:
            try:
                write_future = self._http2_stream.write_data(None, end_stream=True)
                if hasattr(write_future, "done") and write_future.done():
                    write_future.result()
                elif hasattr(write_future, "result") and not asyncio.iscoroutine(write_future):
                    await asyncio.wrap_future(write_future)
                elif asyncio.iscoroutine(write_future):
                    await write_future
            except Exception:
                pass

        if self._http2_conn:
            try:
                self._http2_conn.close()
            except Exception:
                pass

        await self._inbound_queue.put(None)


# =============================================================================
# 5. Offline Mock Transport for Local Development & Testing
# =============================================================================

class MockBedrockStreamConnection(BedrockStreamConnection):
    """
    Offline stream connection that simulates Bedrock Nova Sonic's
    bidirectional EventStream behavior without network or AWS credentials.
    Accurately validates wire-level AWS EventStream binary message framing.
    """

    def __init__(self, session_id: str, prompt_name: str = "offline_prompt"):
        self.session_id = session_id
        self.prompt_name = prompt_name
        self.inbound_queue: asyncio.Queue = asyncio.Queue()
        self.sent_events: List[Dict[str, Any]] = []
        self.sent_raw_frames: List[bytes] = []
        self._is_closed: bool = False

    async def send_event(self, event_dict: Dict[str, Any]) -> None:
        if self._is_closed:
            raise RuntimeError("Cannot send to closed mock stream.")
        
        # Verify event encodes cleanly into standard AWS EventStream binary message
        payload_bytes = json.dumps(event_dict, default=str).encode("utf-8")
        raw_frame = AWSEventStreamCodec.encode_message(
            payload=payload_bytes,
            headers={
                ":message-type": "event",
                ":event-type": "chunk",
                ":content-type": "application/json",
            },
        )
        self.sent_raw_frames.append(raw_frame)
        self.sent_events.append(event_dict)

        # Inspect sent event to simulate appropriate Nova Sonic response
        evt = event_dict.get("event", {})
        if "audioInput" in evt:
            # When audio arrives, simulate assistant transcript delta and speech
            await self.simulate_assistant_response("I can help you search genuine verified properties.")
        elif "toolResult" in evt:
            # When tool result arrives, simulate synthesized response incorporating data
            tool_res = evt["toolResult"]
            content = tool_res.get("content", "{}")
            await self.simulate_assistant_response(f"I found the property matching your requirements based on: {content[:40]}")

    async def send_raw_eventstream_bytes(self, raw_bytes: bytes) -> None:
        """Processes raw binary EventStream frames, verifying CRC and unpacking JSON."""
        messages = AWSEventStreamCodec.decode_messages(raw_bytes)
        for msg in messages:
            payload = msg.get("payload")
            if isinstance(payload, dict):
                await self.send_event(payload)

    def generate_binary_eventstream_response(self, text: str) -> bytes:
        """Encodes simulated assistant response into raw AWS EventStream binary bytes."""
        event_payload = {
            "event": {
                "textOutput": {
                    "role": "ASSISTANT",
                    "content": text,
                }
            }
        }
        payload_bytes = json.dumps(event_payload).encode("utf-8")
        return AWSEventStreamCodec.encode_message(payload_bytes)

    async def simulate_assistant_response(self, text: str) -> None:
        """Pushes simulated textOutput, audioOutput, and contentEnd events into the inbound queue."""
        # 1. Text transcript delta
        await self.inbound_queue.put({
            "event": {
                "textOutput": {
                    "role": "ASSISTANT",
                    "content": text,
                }
            }
        })
        # 2. Audio output chunk (synthetic 100ms PCM 24kHz)
        mock_pcm = b"\x00\x00" * 2400
        mock_pcm_b64 = base64.b64encode(mock_pcm).decode("utf-8")
        await self.inbound_queue.put({
            "event": {
                "audioOutput": {
                    "content": mock_pcm_b64,
                    "sampleRateHertz": 24000,
                }
            }
        })
        # 3. Content End
        await self.inbound_queue.put({
            "event": {
                "contentEnd": {
                    "promptName": self.prompt_name,
                    "contentName": "assistant-response",
                }
            }
        })

    async def simulate_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Injects a toolUse event as if requested by Nova Sonic."""
        tool_use_id = f"tooluse_{uuid.uuid4().hex[:8]}"
        await self.inbound_queue.put({
            "event": {
                "toolUse": {
                    "promptName": self.prompt_name,
                    "toolUseId": tool_use_id,
                    "toolName": tool_name,
                    "content": json.dumps(arguments),
                }
            }
        })
        return tool_use_id

    async def receive_events(self) -> AsyncIterator[Dict[str, Any]]:
        while not self._is_closed:
            event = await self.inbound_queue.get()
            if event is None:
                break
            yield event

    async def close(self) -> None:
        self._is_closed = True
        await self.inbound_queue.put(None)


class MockBedrockStreamTransport(BedrockStreamTransport):
    """Offline transport returning a MockBedrockStreamConnection for test suites."""

    def __init__(self):
        self.active_connections: Dict[str, MockBedrockStreamConnection] = {}

    async def open_stream(
        self,
        model_id: str,
        region: str,
        session_id: str,
    ) -> BedrockStreamConnection:
        conn = MockBedrockStreamConnection(session_id=session_id)
        self.active_connections[session_id] = conn
        return conn
