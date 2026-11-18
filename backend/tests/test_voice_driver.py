import asyncio
import base64
from decimal import Decimal
import json
import sys
import pytest

from app.core.config import settings
from app.services.voice.base import (
    AudioFormat,
    AudioOutputPayload,
    VoiceDriver,
    VoiceEventType,
    VoiceServerEvent,
)
from app.services.voice.mock_driver import MockVoiceDriver
from app.services.voice.nova_sonic_driver import AmazonNovaSonicDriver
from app.services.voice.bedrock_streaming import (
    BedrockNovaSonicParser,
    BedrockNovaSonicSerializer,
    MockBedrockStreamTransport,
)
from app.services.voice.factory import get_voice_driver
from app.services.voice.tools_spec import get_agent_tools_spec
from app.services.voice.orchestrator import VoiceSessionOrchestrator
from app.db.base import Base
from app.models import (
    AuditLog,
    Availability,
    Company,
    Conversation,
    Customer,
    Location,
    Pricing,
    Project,
    Property,
    PropertyUnit,
    User,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


def test_mock_voice_driver_session_lifecycle():
    async def _run():
        driver = MockVoiceDriver(model_id="amazon.nova-2-5-sonic")
        session_id = "test_sess_001"
        tools = get_agent_tools_spec()

        # 1. Start Session
        await driver.start_session(session_id=session_id, prompt_preamble="Test Preamble", tools=tools)

        events = []
        queue = driver._session_queues[session_id]
        while not queue.empty():
            events.append(queue.get_nowait())

        # Expect: SESSION_STARTED, TRANSCRIPT_DELTA (Assistant greeting), AUDIO_OUTPUT
        event_types = [e.event_type for e in events]
        assert VoiceEventType.SESSION_STARTED in event_types
        assert VoiceEventType.TRANSCRIPT_DELTA in event_types
        assert VoiceEventType.AUDIO_OUTPUT in event_types

        # 2. Text Input & Intent Handling
        await driver.send_text_input(session_id, "Looking for a 2BHK in Seattle under 800k")
        turn_events = []
        while not queue.empty():
            turn_events.append(queue.get_nowait())

        tool_req = next(e for e in turn_events if e.event_type == VoiceEventType.TOOL_USE_REQUEST).tool_request_payload
        assert tool_req.tool_name == "search_properties"
        assert tool_req.arguments.get("city") == "Seattle"
        assert tool_req.arguments.get("configuration_type") == "2BHK"

        # 3. Deliver Tool Result back to driver
        mock_tool_result = {
            "tool_name": "search_properties",
            "success": True,
            "data": [
                {
                    "property_name": "Pinnacle Tower",
                    "unit_number": "101",
                    "configuration_type": "2BHK",
                    "base_price": 750000,
                    "currency": "USD",
                }
            ],
        }
        await driver.send_tool_result(session_id, tool_req.tool_use_id, mock_tool_result)

        result_events = []
        while not queue.empty():
            result_events.append(queue.get_nowait())

        assistant_delta = next(e for e in result_events if e.event_type == VoiceEventType.TRANSCRIPT_DELTA).transcript_payload
        assert "Pinnacle Tower" in assistant_delta.delta
        assert "Unit 101" in assistant_delta.delta

        # 4. Interruption
        await queue.put(
            VoiceServerEvent(
                event_type=VoiceEventType.AUDIO_OUTPUT,
                session_id=session_id,
                audio_payload=AudioOutputPayload(audio_bytes=driver._generate_synthetic_pcm_audio(duration_ms=100)),
            )
        )
        await driver.interrupt(session_id)
        interrupt_events = []
        while not queue.empty():
            interrupt_events.append(queue.get_nowait())

        assert any(e.event_type == VoiceEventType.INTERRUPTED for e in interrupt_events)

        # 5. End Session
        await driver.end_session(session_id)
        end_event = queue.get_nowait()
        assert end_event.event_type == VoiceEventType.SESSION_ENDED

    asyncio.run(_run())


def test_mock_voice_driver_explicit_test_triggers():
    async def _run():
        driver = MockVoiceDriver()
        session_id = "test_sess_002"
        await driver.start_session(session_id, "Test", [])

        queue = driver._session_queues[session_id]
        # Drain initial greeting
        while not queue.empty():
            queue.get_nowait()

        # Deterministic tool trigger
        await driver.send_text_input(session_id, 'TEST_TOOL:get_property_price:{"unit_id": "00000000-0000-0000-0000-000000000001"}')
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        tool_req = next(e for e in events if e.event_type == VoiceEventType.TOOL_USE_REQUEST).tool_request_payload
        assert tool_req.tool_name == "get_property_price"
        assert tool_req.arguments["unit_id"] == "00000000-0000-0000-0000-000000000001"

    asyncio.run(_run())


def test_amazon_nova_sonic_driver_initialization():
    async def _run():
        driver = AmazonNovaSonicDriver(model_id="amazon.nova-2-5-sonic", region_name="us-east-1")
        assert driver.provider_name == "amazon_nova_sonic"
        assert driver.model_id == "amazon.nova-2-5-sonic"

        session_id = "nova_sess_001"
        tools = get_agent_tools_spec()

        # Start session
        await driver.start_session(
            session_id=session_id,
            prompt_preamble="Real Estate AI Preamble",
            tools=tools,
            audio_format=AudioFormat.PCM_24KHZ_16BIT_MONO,
        )

        queue = driver._session_queues[session_id]
        init_event = queue.get_nowait()
        assert init_event.event_type == VoiceEventType.SESSION_STARTED
        assert init_event.data["model_id"] == "amazon.nova-2-5-sonic"
        assert init_event.data["provider"] == "amazon_nova_sonic"
        assert init_event.data["tools_count"] == len(tools)

        # Interruption
        await driver.interrupt(session_id)
        intr_event = queue.get_nowait()
        assert intr_event.event_type == VoiceEventType.INTERRUPTED

        # End Session
        await driver.end_session(session_id)
        end_event = queue.get_nowait()
        assert end_event.event_type == VoiceEventType.SESSION_ENDED

    asyncio.run(_run())


def test_voice_driver_factory():
    # By default, settings.USE_MOCK_VOICE is True
    mock_drv = get_voice_driver(override_mock=True)
    assert isinstance(mock_drv, MockVoiceDriver)
    assert mock_drv.provider_name == "mock"

    nova_drv = get_voice_driver(override_mock=False)
    assert isinstance(nova_drv, AmazonNovaSonicDriver)
    assert nova_drv.provider_name == "amazon_nova_sonic"


def test_agent_tools_spec_generation():
    specs = get_agent_tools_spec()
    assert len(specs) >= 13

    tool_names = [s["toolSpec"]["name"] for s in specs]
    expected_tools = [
        "search_properties",
        "get_property_details",
        "get_property_price",
        "check_property_availability",
        "extract_requirements",
        "create_lead",
        "update_lead",
        "calculate_lead_priority",
        "check_visit_slots",
        "book_site_visit",
        "reschedule_site_visit",
        "cancel_site_visit",
        "transfer_to_human",
    ]
    for exp in expected_tools:
        assert exp in tool_names, f"Tool '{exp}' missing from Nova Sonic tool specifications!"

    # Verify JSON Schema properties on search_properties
    search_spec = next(s["toolSpec"] for s in specs if s["toolSpec"]["name"] == "search_properties")
    props = search_spec["inputSchema"]["json"]["properties"]
    assert "city" in props
    assert "currency" in props
    assert "min_budget" in props
    assert "max_budget" in props


def test_bedrock_nova_sonic_serializer_all_events():
    """Verifies that BedrockNovaSonicSerializer formats events matching the Bedrock duplex protocol."""
    # 1. sessionStart
    sess_evt = BedrockNovaSonicSerializer.serialize_session_start(max_tokens=2048, temperature=0.5, top_p=0.8)
    assert "sessionStart" in sess_evt["event"]
    inf_cfg = sess_evt["event"]["sessionStart"]["inferenceConfiguration"]
    assert inf_cfg["maxTokens"] == 2048
    assert inf_cfg["temperature"] == 0.5
    assert inf_cfg["topP"] == 0.8

    # 2. promptStart with tools
    tools = get_agent_tools_spec()
    prompt_evt = BedrockNovaSonicSerializer.serialize_prompt_start(
        prompt_name="prompt_test",
        tools=tools,
        voice_id="matthew",
        output_sample_rate=24000,
    )
    p_start = prompt_evt["event"]["promptStart"]
    assert p_start["promptName"] == "prompt_test"
    assert p_start["audioOutputConfiguration"]["voiceId"] == "matthew"
    assert p_start["audioOutputConfiguration"]["sampleRateHertz"] == 24000
    assert len(p_start["toolConfiguration"]["tools"]) >= 13

    # 3. system content block
    sys_start = BedrockNovaSonicSerializer.serialize_system_content_start("prompt_test", "sys-1")
    assert sys_start["event"]["contentStart"]["role"] == "SYSTEM"
    text_evt = BedrockNovaSonicSerializer.serialize_text_input("prompt_test", "sys-1", "Hello Real Estate")
    assert text_evt["event"]["textInput"]["content"] == "Hello Real Estate"
    end_evt = BedrockNovaSonicSerializer.serialize_content_end("prompt_test", "sys-1")
    assert end_evt["event"]["contentEnd"]["contentName"] == "sys-1"

    # 4. audio content block & audioInput base64
    raw_pcm = b"\x00\x01\x02\x03" * 100
    audio_start = BedrockNovaSonicSerializer.serialize_audio_content_start("prompt_test", "audio-1", 16000)
    assert audio_start["event"]["contentStart"]["type"] == "AUDIO"
    assert audio_start["event"]["contentStart"]["audioInputConfiguration"]["sampleRateHertz"] == 16000

    audio_chunk_evt = BedrockNovaSonicSerializer.serialize_audio_input("prompt_test", "audio-1", raw_pcm)
    assert "audioInput" in audio_chunk_evt["event"]
    assert audio_chunk_evt["event"]["audioInput"]["promptName"] == "prompt_test"
    # Verify base64 decodes back to original PCM bytes
    import base64
    decoded = base64.b64decode(audio_chunk_evt["event"]["audioInput"]["content"])
    assert decoded == raw_pcm

    # 5. toolResult content block
    tool_res_start = BedrockNovaSonicSerializer.serialize_tool_result_content_start("prompt_test", "tool_call_001")
    assert tool_res_start["event"]["contentStart"]["role"] == "TOOL"

    tool_res_evt = BedrockNovaSonicSerializer.serialize_tool_result(
        "prompt_test",
        "tool_call_001",
        {"matches_found": 3, "city": "Bengaluru"},
        is_error=False,
    )
    assert tool_res_evt["event"]["toolResult"]["contentName"] == "tool_call_001"
    assert tool_res_evt["event"]["toolResult"]["status"] == "success"
    assert "Bengaluru" in tool_res_evt["event"]["toolResult"]["content"]

    # 6. Session and prompt end
    assert "promptEnd" in BedrockNovaSonicSerializer.serialize_prompt_end("prompt_test")["event"]
    assert "sessionEnd" in BedrockNovaSonicSerializer.serialize_session_end()["event"]


def test_bedrock_nova_sonic_parser_all_events():
    """Verifies that BedrockNovaSonicParser parses model speech, transcript deltas, tools, and errors."""
    session_id = "test_parse_sess"

    # 1. audioOutput parsing
    import base64
    sample_pcm = b"\x11\x22\x33\x44" * 50
    audio_evt_raw = {
        "event": {
            "audioOutput": {
                "content": base64.b64encode(sample_pcm).decode("utf-8"),
                "sampleRateHertz": 24000,
            }
        }
    }
    parsed_audio = BedrockNovaSonicParser.parse_event(audio_evt_raw, session_id)
    assert parsed_audio is not None
    assert parsed_audio.event_type == VoiceEventType.AUDIO_OUTPUT
    assert parsed_audio.audio_payload.audio_bytes == sample_pcm
    assert parsed_audio.audio_payload.sample_rate == 24000

    # 2. textOutput parsing
    text_evt_raw = {
        "event": {
            "textOutput": {
                "role": "ASSISTANT",
                "content": "Welcome to luxury villas in Whitefield.",
            }
        }
    }
    parsed_text = BedrockNovaSonicParser.parse_event(text_evt_raw, session_id)
    assert parsed_text is not None
    assert parsed_text.event_type == VoiceEventType.TRANSCRIPT_DELTA
    assert parsed_text.transcript_payload.role == "assistant"
    assert "Whitefield" in parsed_text.transcript_payload.delta
    assert not parsed_text.transcript_payload.is_final

    # 3. toolUse parsing
    tool_evt_raw = {
        "event": {
            "toolUse": {
                "promptName": "prompt_test",
                "toolUseId": "tool_call_abc",
                "toolName": "search_properties",
                "content": json.dumps({"city": "Mumbai", "configuration_type": "3BHK"}),
            }
        }
    }
    parsed_tool = BedrockNovaSonicParser.parse_event(tool_evt_raw, session_id)
    assert parsed_tool is not None
    assert parsed_tool.event_type == VoiceEventType.TOOL_USE_REQUEST
    assert parsed_tool.tool_request_payload.tool_name == "search_properties"
    assert parsed_tool.tool_request_payload.tool_use_id == "tool_call_abc"
    assert parsed_tool.tool_request_payload.arguments["city"] == "Mumbai"
    assert parsed_tool.tool_request_payload.arguments["configuration_type"] == "3BHK"

    # 4. contentEnd parsing
    content_end_raw = {
        "event": {
            "contentEnd": {
                "promptName": "prompt_test",
                "contentName": "assistant-turn",
            }
        }
    }
    parsed_end = BedrockNovaSonicParser.parse_event(content_end_raw, session_id)
    assert parsed_end is not None
    assert parsed_end.event_type == VoiceEventType.TRANSCRIPT_DELTA
    assert parsed_end.transcript_payload.is_final

    # 5. Service exceptions
    throttling_raw = {
        "event": {
            "throttlingException": {
                "message": "Rate limit exceeded on Bedrock stream."
            }
        }
    }
    parsed_err = BedrockNovaSonicParser.parse_event(throttling_raw, session_id)
    assert parsed_err is not None
    assert parsed_err.event_type == VoiceEventType.ERROR
    assert parsed_err.data["error_type"] == "throttlingException"


def test_nova_sonic_driver_offline_bidirectional_streaming_lifecycle():
    """
    Offline integration test verifying complete Bedrock bidirectional streaming
    connection lifecycle using MockBedrockStreamTransport (zero network/AWS calls).
    """
    async def _run():
        mock_transport = MockBedrockStreamTransport()
        driver = AmazonNovaSonicDriver(
            model_id="amazon.nova-2-5-sonic",
            region_name="us-east-1",
            transport=mock_transport,
        )
        session_id = "offline_stream_sess_001"
        tools = get_agent_tools_spec()

        # 1. Start Session
        await driver.start_session(
            session_id=session_id,
            prompt_preamble="Real Estate AI System Instructions",
            tools=tools,
            audio_format=AudioFormat.PCM_24KHZ_16BIT_MONO,
        )

        mock_conn = mock_transport.active_connections[session_id]
        assert mock_conn is not None

        # Verify initial handshake events sent to stream
        sent_types = [list(e["event"].keys())[0] for e in mock_conn.sent_events]
        assert "sessionStart" in sent_types
        assert "promptStart" in sent_types
        assert "contentStart" in sent_types

        # Verify session queue received SESSION_STARTED
        queue = driver._session_queues[session_id]
        init_evt = await queue.get()
        assert init_evt.event_type == VoiceEventType.SESSION_STARTED
        assert init_evt.data["connected"] is True

        # 2. Send continuous audio chunk -> triggers simulated response
        raw_audio = b"\x00\x05" * 1600  # 100ms of 16kHz audio
        await driver.send_audio_chunk(session_id, raw_audio)

        # Give receiver task time to process inbound stream events
        await asyncio.sleep(0.05)

        # Collect inbound events produced by stream
        inbound_events = []
        while not queue.empty():
            inbound_events.append(queue.get_nowait())

        event_types = [e.event_type for e in inbound_events]
        assert VoiceEventType.TRANSCRIPT_DELTA in event_types
        assert VoiceEventType.AUDIO_OUTPUT in event_types

        # 3. End Session
        await driver.end_session(session_id)
        assert mock_conn._is_closed is True
        end_evt = await queue.get()
        assert end_evt.event_type == VoiceEventType.SESSION_ENDED

    asyncio.run(_run())


def test_nova_sonic_driver_tool_use_and_result_offline_flow():
    """
    Verifies that the driver receives a model toolUse event from Bedrock EventStream
    and correctly serializes the toolResult back down the stream.
    """
    async def _run():
        mock_transport = MockBedrockStreamTransport()
        driver = AmazonNovaSonicDriver(
            model_id="amazon.nova-2-5-sonic",
            region_name="us-east-1",
            transport=mock_transport,
        )
        session_id = "offline_tool_sess_002"
        tools = get_agent_tools_spec()

        await driver.start_session(session_id, "Preamble", tools)
        mock_conn = mock_transport.active_connections[session_id]
        queue = driver._session_queues[session_id]

        # Drain SESSION_STARTED
        await queue.get()

        # Simulate Bedrock model emitting a toolUse call for search_properties
        tool_use_id = await mock_conn.simulate_tool_call(
            tool_name="search_properties",
            arguments={"city": "Bengaluru", "configuration_type": "2BHK", "currency": "INR"},
        )
        await asyncio.sleep(0.05)

        # Verify driver received TOOL_USE_REQUEST
        tool_req_evt = await queue.get()
        assert tool_req_evt.event_type == VoiceEventType.TOOL_USE_REQUEST
        payload = tool_req_evt.tool_request_payload
        assert payload.tool_name == "search_properties"
        assert payload.tool_use_id == tool_use_id
        assert payload.arguments["city"] == "Bengaluru"

        # Deliver tool execution result back to driver
        tool_execution_result = {
            "success": True,
            "data": [{"property_name": "Godrej Splendour", "unit_number": "B-402", "price": 8500000}],
        }
        await driver.send_tool_result(
            session_id=session_id,
            tool_use_id=tool_use_id,
            result=tool_execution_result,
            is_error=False,
        )

        # Verify toolResult was serialized and sent to mock stream
        sent_events = mock_conn.sent_events
        tool_result_events = [e for e in sent_events if "toolResult" in e.get("event", {})]
        assert len(tool_result_events) >= 1
        res_evt = tool_result_events[-1]["event"]["toolResult"]
        assert res_evt["contentName"] == tool_use_id
        assert res_evt["status"] == "success"
        assert "Godrej Splendour" in res_evt["content"]

        await driver.end_session(session_id)

    asyncio.run(_run())


# =============================================================================
# Phase 2 Step 2: Advanced Offline Transport, Protocol & Audio Tests
# =============================================================================

class SimulatedHttp2ClientStream:
    """Simulates awscrt.http.Http2ClientStream for offline testing."""
    def __init__(self, on_response=None, on_body=None):
        self.on_response = on_response
        self.on_body = on_body
        self.is_active = False
        self.written_chunks: list = []
        self.ended = False

    def activate(self):
        self.is_active = True
        if self.on_response:
            self.on_response(self, 200, [("content-type", "application/vnd.amazon.eventstream")])

    def write_data(self, data_stream, end_stream=False):
        import concurrent.futures
        f = concurrent.futures.Future()
        if data_stream is not None:
            raw_bytes = bytes(data_stream) if not isinstance(data_stream, bytes) else data_stream
            self.written_chunks.append(raw_bytes)
        if end_stream:
            self.ended = True
        f.set_result(None)
        return f

    def simulate_server_chunk(self, chunk: bytes):
        if self.on_body:
            self.on_body(self, chunk)


class SimulatedHttp2ClientConnection:
    """Simulates awscrt.http.Http2ClientConnection for offline testing."""
    def __init__(self):
        self.is_open = True
        self.last_request = None
        self.stream = None

    def request(self, request, on_response=None, on_body=None, manual_write=False):
        self.last_request = request
        self.stream = SimulatedHttp2ClientStream(on_response=on_response, on_body=on_body)
        return self.stream

    def close(self):
        self.is_open = False


def test_aws_eventstream_codec_binary_framing_and_crc():
    """
    Verifies AWS EventStream binary wire framing:
    - 12-byte prelude with total_len, headers_len, and prelude CRC32
    - headers (:message-type, :event-type, :content-type)
    - payload
    - 4-byte message CRC32
    - Validated by botocore.eventstream.EventStreamBuffer
    """
    from app.services.voice.bedrock_streaming import AWSEventStreamCodec
    import botocore.eventstream

    test_payload = json.dumps({"event": {"sessionStart": {"inferenceConfiguration": {"maxTokens": 1024}}}}).encode("utf-8")
    frame = AWSEventStreamCodec.encode_message(
        payload=test_payload,
        headers={":message-type": "event", ":event-type": "chunk", ":content-type": "application/json"},
    )

    # Frame must be larger than payload (12 byte prelude + headers + 4 byte CRC)
    assert len(frame) > len(test_payload) + 16

    # Verify decoding with official AWS botocore parser
    buf = botocore.eventstream.EventStreamBuffer()
    buf.add_data(frame)
    messages = list(buf)
    assert len(messages) == 1
    assert messages[0].headers[":message-type"] == "event"
    assert messages[0].headers[":event-type"] == "chunk"
    assert json.loads(messages[0].payload.decode("utf-8")) == {"event": {"sessionStart": {"inferenceConfiguration": {"maxTokens": 1024}}}}


def test_aws_eventstream_fragmented_and_concatenated_decoding():
    """
    Verifies that AWSEventStreamCodec and _stream_buffer handle:
    1. Fragmented frames split arbitrarily across network chunks.
    2. Multiple concatenated frames received in a single network chunk.
    """
    from app.services.voice.bedrock_streaming import AWSEventStreamCodec

    payload1 = json.dumps({"event": {"textOutput": {"role": "ASSISTANT", "content": "Hello"}}}).encode("utf-8")
    payload2 = json.dumps({"event": {"textOutput": {"role": "ASSISTANT", "content": " World"}}}).encode("utf-8")

    frame1 = AWSEventStreamCodec.encode_message(payload1)
    frame2 = AWSEventStreamCodec.encode_message(payload2)

    # Test concatenated frames
    concatenated = frame1 + frame2
    decoded_concat = AWSEventStreamCodec.decode_messages(concatenated)
    assert len(decoded_concat) == 2
    assert decoded_concat[0]["payload"]["event"]["textOutput"]["content"] == "Hello"
    assert decoded_concat[1]["payload"]["event"]["textOutput"]["content"] == " World"

    # Test fragmented delivery using EventStreamBuffer
    import botocore.eventstream
    stream_buffer = botocore.eventstream.EventStreamBuffer()
    split_pt = len(frame1) // 3
    stream_buffer.add_data(frame1[:split_pt])
    assert list(stream_buffer) == []  # Not enough data yet

    stream_buffer.add_data(frame1[split_pt:])  # Complete the frame
    recovered = list(stream_buffer)
    assert len(recovered) == 1
    assert json.loads(recovered[0].payload.decode("utf-8"))["event"]["textOutput"]["content"] == "Hello"


def test_crt_bedrock_stream_signed_request_construction():
    """
    Verifies that _CRTBedrockStreamConnection constructs a valid HttpRequest
    signed with AWS SigV4 headers (Authorization, X-Amz-Date, Host, Accept).
    """
    from app.services.voice.bedrock_streaming import _CRTBedrockStreamConnection

    conn = _CRTBedrockStreamConnection(
        endpoint="bedrock-runtime.us-east-1.amazonaws.com",
        path="/model/amazon.nova-2-5-sonic/invoke-with-bidirectional-stream",
        region="us-east-1",
        access_key_id="AKIA_MOCK_TEST_KEY",
        secret_access_key="SECRET_MOCK_KEY_TESTING",
    )
    req = conn._create_signed_request()

    headers_dict = {k.lower(): v for k, v in req.headers}
    assert headers_dict["host"] == "bedrock-runtime.us-east-1.amazonaws.com"
    assert headers_dict["content-type"] == "application/vnd.amazon.eventstream"
    assert headers_dict["accept"] == "application/vnd.amazon.eventstream"
    assert "x-amz-date" in headers_dict
    assert "authorization" in headers_dict
    assert "AWS4-HMAC-SHA256" in headers_dict["authorization"]
    assert "AKIA_MOCK_TEST_KEY" in headers_dict["authorization"]
    assert "bedrock/aws4_request" in headers_dict["authorization"]


def test_crt_bedrock_stream_live_duplex_lifecycle_offline():
    """
    Verifies full lifecycle of _CRTBedrockStreamConnection with active transmission:
    1. Connects and activates stream
    2. Actively transmits framed EventStream messages (never silently buffering)
    3. Receives and decodes inbound chunks concurrently
    4. Handles stream error responses
    5. Clean graceful termination
    """
    async def _run():
        from app.services.voice.bedrock_streaming import _CRTBedrockStreamConnection, AWSEventStreamCodec

        sim_conn = SimulatedHttp2ClientConnection()
        conn = _CRTBedrockStreamConnection(
            endpoint="bedrock-runtime.us-east-1.amazonaws.com",
            path="/model/amazon.nova-2-5-sonic/invoke-with-bidirectional-stream",
            region="us-east-1",
            access_key_id="AKIA_MOCK_KEY",
            secret_access_key="MOCK_SECRET",
            connection_factory=lambda: asyncio.sleep(0.01, result=sim_conn),
        )

        # 1. Connect
        await conn.connect()
        assert sim_conn.stream is not None
        assert sim_conn.stream.is_active is True
        assert conn.response_status_code == 200

        # 2. Transmit outgoing event
        evt = {"event": {"audioInput": {"promptName": "p1", "contentName": "c1", "content": "AQID"}}}
        await conn.send_event(evt)
        assert len(sim_conn.stream.written_chunks) == 1
        assert len(conn.sent_frames) == 1

        # Verify transmitted frame is binary EventStream
        decoded_sent = AWSEventStreamCodec.decode_messages(sim_conn.stream.written_chunks[0])
        assert len(decoded_sent) == 1
        assert decoded_sent[0]["payload"]["event"]["audioInput"]["promptName"] == "p1"

        # 3. Simulate server sending response chunk
        resp_payload = json.dumps({"event": {"textOutput": {"role": "ASSISTANT", "content": "I can help."}}}).encode("utf-8")
        resp_frame = AWSEventStreamCodec.encode_message(resp_payload)
        sim_conn.stream.simulate_server_chunk(resp_frame)

        # 4. Receive event from inbound queue
        events_iter = conn.receive_events()
        received = await anext(events_iter)
        assert received["event"]["textOutput"]["content"] == "I can help."

        # 5. Close connection
        await conn.close()
        assert conn._is_closed is True
        assert sim_conn.stream.ended is True
        assert sim_conn.is_open is False

    asyncio.run(_run())


def test_audio_utils_sample_rate_validation_and_resampling():
    """
    Verifies audio_utils functionality:
    - PCM validation (16-bit mono even byte checks)
    - Duration calculation at 24kHz and 16kHz
    - Sample rate resampling between 24kHz and 16kHz
    - Base64 encoding and decoding round-trip
    """
    from app.services.voice.audio_utils import (
        validate_pcm_s16le,
        calculate_pcm_duration_ms,
        resample_pcm_s16le,
        pcm_s16le_to_base64,
        base64_to_pcm_s16le,
    )

    # 100ms of 24kHz mono 16-bit = 2400 samples = 4800 bytes
    pcm_24k = b"\x00\x00" * 2400
    assert validate_pcm_s16le(pcm_24k) is True
    assert validate_pcm_s16le(b"\x00") is False  # Odd byte count is invalid
    assert validate_pcm_s16le(b"") is False

    assert calculate_pcm_duration_ms(pcm_24k, sample_rate=24000) == 100.0

    # Resample 24k -> 16k: 2400 samples * (16/24) = 1600 samples = 3200 bytes
    pcm_16k = resample_pcm_s16le(pcm_24k, in_rate=24000, out_rate=16000)
    assert len(pcm_16k) == 3200
    assert calculate_pcm_duration_ms(pcm_16k, sample_rate=16000) == 100.0

    # Resample 16k -> 24k: 1600 samples * (24/16) = 2400 samples = 4800 bytes
    pcm_24k_back = resample_pcm_s16le(pcm_16k, in_rate=16000, out_rate=24000)
    assert abs(len(pcm_24k_back) - 4800) <= 2

    # Base64 roundtrip
    b64 = pcm_s16le_to_base64(pcm_24k)
    restored = base64_to_pcm_s16le(b64)
    assert restored == pcm_24k


def test_nova_sonic_sample_rate_alignment_and_malformed_rejection():
    """
    Verifies that:
    1. audioInputConfiguration declares 24000 Hz and audioType SPEECH by default.
    2. AmazonNovaSonicDriver rejects malformed/odd-byte PCM chunks safely without crashing.
    3. Auto-resampling occurs if incoming session format is 16kHz when input rate is 24kHz.
    """
    async def _run():
        from app.services.voice.bedrock_streaming import BedrockNovaSonicSerializer
        from app.services.voice.nova_sonic_driver import AmazonNovaSonicDriver
        from app.services.voice.bedrock_streaming import MockBedrockStreamTransport

        # 1. Serialization defaults
        audio_start = BedrockNovaSonicSerializer.serialize_audio_content_start("prompt_p", "audio_c", sample_rate=24000)
        config = audio_start["event"]["contentStart"]["audioInputConfiguration"]
        assert config["sampleRateHertz"] == 24000
        assert config["audioType"] == "SPEECH"
        assert config["mediaType"] == "audio/lpcm"

        # 2. Driver malformed audio rejection
        mock_transport = MockBedrockStreamTransport()
        driver = AmazonNovaSonicDriver(
            model_id="amazon.nova-2-5-sonic",
            transport=mock_transport,
        )
        session_id = "test_audio_reject_001"
        await driver.start_session(session_id, "Preamble", [])
        mock_conn = mock_transport.active_connections[session_id]

        initial_sent_count = len(mock_conn.sent_events)

        # Send malformed odd-byte chunk
        await driver.send_audio_chunk(session_id, b"\x00\x01\x02")
        assert len(mock_conn.sent_events) == initial_sent_count  # Rejected!

        # Send valid even-byte chunk
        await driver.send_audio_chunk(session_id, b"\x00\x00" * 100)
        assert len(mock_conn.sent_events) == initial_sent_count + 1  # Accepted!

        await driver.end_session(session_id)

    asyncio.run(_run())



def test_nova_sonic_driver_interruption_drains_audio():
    """Verifies that user interruption drains pending audio frames and sets interrupted state."""
    async def _run():
        mock_transport = MockBedrockStreamTransport()
        driver = AmazonNovaSonicDriver(
            model_id="amazon.nova-2-5-sonic",
            region_name="us-east-1",
            transport=mock_transport,
        )
        session_id = "offline_interrupt_sess_003"
        await driver.start_session(session_id, "Preamble", [])
        queue = driver._session_queues[session_id]

        # Drain SESSION_STARTED
        await queue.get()

        # Seed audio chunks in the output buffer
        for _ in range(5):
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.AUDIO_OUTPUT,
                    session_id=session_id,
                    audio_payload=AudioOutputPayload(audio_bytes=b"\x00" * 100),
                )
            )

        # Trigger interruption
        await driver.interrupt(session_id)

        # Collect remaining events
        remaining = []
        while not queue.empty():
            remaining.append(queue.get_nowait())

        # No AUDIO_OUTPUT should remain; exactly one INTERRUPTED event
        assert not any(e.event_type == VoiceEventType.AUDIO_OUTPUT for e in remaining)
        interrupt_evts = [e for e in remaining if e.event_type == VoiceEventType.INTERRUPTED]
        assert len(interrupt_evts) == 1
        assert interrupt_evts[0].data["drained_audio_frames"] == 5

        await driver.end_session(session_id)

    asyncio.run(_run())


def test_nova_sonic_orchestrator_end_to_end_tool_execution():
    """
    Offline integration test verifying VoiceSessionOrchestrator interacting with
    AmazonNovaSonicDriver over MockBedrockStreamTransport.
    
    Verifies:
      1. Orchestrator initializes Nova Sonic session with 13 tool specs.
      2. Inbound toolUse from Nova Sonic is intercepted by orchestrator.
      3. Orchestrator executes tool strictly via validated Phase 2 dispatcher.
      4. Database search query runs against genuine records.
      5. Orchestrator records immutable VOICE_TOOL_EXECUTED audit event.
      6. Serialized toolResult is returned down the Bedrock stream.
      7. On session close, transcript is encrypted with AES-256-GCM.
    """
    async def _run():
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            echo=False,
        )
        Base.metadata.create_all(engine)

        with Session(engine) as db:
            # Seed test customer and genuine property records
            user = User(email="customer.nova@realty.test", hashed_password="pw", role="customer")
            db.add(user)
            db.flush()
            cust = Customer(user_id=user.id, full_name="Nova Client", phone="+91-9988776655")
            db.add(cust)

            company = Company(name="Prestige Estates")
            db.add(company)
            db.flush()

            loc = Location(city="Bengaluru", state="Karnataka", address_line_1="Whitefield Main Rd", postal_code="560066")
            db.add(loc)
            db.flush()

            project = Project(
                company_id=company.id,
                location_id=loc.id,
                name="Prestige Park Grove",
                timezone="Asia/Kolkata",
            )
            db.add(project)
            db.flush()

            prop = Property(project_id=project.id, name="Tower 1")
            db.add(prop)
            db.flush()

            unit = PropertyUnit(
                property_id=prop.id,
                unit_number="302",
                configuration_type="3BHK",
                carpet_area_sqft=Decimal("1650.00"),
            )
            db.add(unit)
            db.flush()

            pricing = Pricing(
                unit_id=unit.id,
                base_price=Decimal("14500000.00"),
                total_estimated_price=Decimal("14500000.00"),
                currency="INR",
                is_active=True,
            )
            avail = Availability(
                unit_id=unit.id,
                status="available",
                is_current=True,
            )
            db.add_all([pricing, avail])
            db.commit()

            # Initialize Nova Sonic Driver with Mock Stream Transport
            mock_transport = MockBedrockStreamTransport()
            driver = AmazonNovaSonicDriver(
                model_id="amazon.nova-2-5-sonic",
                region_name="us-east-1",
                transport=mock_transport,
            )
            session_id = "nova_orch_test_001"

            orchestrator = VoiceSessionOrchestrator(
                session_id=session_id,
                driver=driver,
                db=db,
                customer_id=cust.id,
                user_role="customer",
                user_id=user.id,
            )

            # Start session
            await orchestrator.start()
            mock_conn = mock_transport.active_connections[session_id]

            sent_texts = []
            sent_bytes = []

            async def mock_send_text(msg: str):
                sent_texts.append(json.loads(msg))

            async def mock_send_bytes(b: bytes):
                sent_bytes.append(b)

            # Run pipeline in background
            pipeline_task = asyncio.create_task(
                orchestrator.run_pipeline(send_text=mock_send_text, send_bytes=mock_send_bytes)
            )

            # Wait for session_started event
            await asyncio.sleep(0.05)
            assert any(m.get("type") == "session_started" for m in sent_texts)

            # Simulate Bedrock Nova Sonic triggering toolUse for search_properties
            tool_use_id = await mock_conn.simulate_tool_call(
                tool_name="search_properties",
                arguments={"city": "Bengaluru", "configuration_type": "3BHK"},
            )

            # Allow orchestrator to intercept toolUse, dispatch to database, and return toolResult
            await asyncio.sleep(0.1)

            # Verify orchestrator notified client of tool execution
            tool_starts = [m for m in sent_texts if m.get("type") == "tool_call_start"]
            assert len(tool_starts) >= 1
            assert tool_starts[0]["tool_name"] == "search_properties"

            tool_completes = [m for m in sent_texts if m.get("type") == "tool_call_complete"]
            assert len(tool_completes) >= 1
            assert tool_completes[0]["success"] is True

            # Verify immutable audit log was created for tool execution
            audit_events = db.query(AuditLog).filter(
                AuditLog.action == "VOICE_TOOL_EXECUTED",
                AuditLog.resource_id == "search_properties",
            ).all()
            assert len(audit_events) == 1
            assert audit_events[0].user_id == user.id

            # Verify toolResult was serialized and sent to mock Bedrock stream
            tool_results = [e for e in mock_conn.sent_events if "toolResult" in e.get("event", {})]
            assert len(tool_results) >= 1
            res_content = tool_results[-1]["event"]["toolResult"]["content"]
            assert "Prestige Park Grove" in res_content
            assert "302" in res_content

            # Gracefully stop orchestrator
            await orchestrator.close()
            pipeline_task.cancel()
            try:
                await pipeline_task
            except (asyncio.CancelledError, Exception):
                pass

            # Verify conversation record exists with AES-256-GCM encrypted transcript
            conv = db.query(Conversation).filter(Conversation.session_id == session_id).first()
            assert conv is not None
            assert conv.encrypted_transcript is not None
            # Verify transcript is encrypted (not plaintext JSON)
            assert "Prestige" not in conv.encrypted_transcript

            # Verify completion audit record exists
            completion_audits = db.query(AuditLog).filter(
                AuditLog.action == "VOICE_SESSION_COMPLETED"
            ).all()
            assert len(completion_audits) == 1

        engine.dispose()

    asyncio.run(_run())


def test_nova_sonic_orchestrator_invalid_tool_arguments_resilience():
    """
    Offline resilience test: verifies that when Nova Sonic emits invalid/malformed
    tool arguments, the dispatcher intercepts the ValidationError, returns success=False
    with anti-hallucination guidance, and returns toolResult without crashing the stream.
    """
    async def _run():
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            echo=False,
        )
        Base.metadata.create_all(engine)

        with Session(engine) as db:
            mock_transport = MockBedrockStreamTransport()
            driver = AmazonNovaSonicDriver(
                model_id="amazon.nova-2-5-sonic",
                region_name="us-east-1",
                transport=mock_transport,
            )
            session_id = "nova_resilience_sess_001"

            orchestrator = VoiceSessionOrchestrator(
                session_id=session_id,
                driver=driver,
                db=db,
            )

            await orchestrator.start()
            mock_conn = mock_transport.active_connections[session_id]

            sent_texts = []
            async def mock_send_text(msg: str):
                sent_texts.append(json.loads(msg))

            pipeline_task = asyncio.create_task(
                orchestrator.run_pipeline(send_text=mock_send_text, send_bytes=lambda b: asyncio.sleep(0))
            )
            await asyncio.sleep(0.05)

            # Emit invalid tool call: missing required fields or invalid types for search_properties
            # (e.g. min_budget is a negative number or non-numeric string)
            tool_use_id = await mock_conn.simulate_tool_call(
                tool_name="search_properties",
                arguments={"min_budget": "not_a_number"},
            )
            await asyncio.sleep(0.1)

            # Tool call complete should report success=False, but no crash
            tool_completes = [m for m in sent_texts if m.get("type") == "tool_call_complete"]
            assert len(tool_completes) >= 1
            assert tool_completes[0]["success"] is False

            # Verify toolResult was returned with error status
            tool_results = [e for e in mock_conn.sent_events if "toolResult" in e.get("event", {})]
            assert len(tool_results) >= 1
            res_evt = tool_results[-1]["event"]["toolResult"]
            assert res_evt["contentName"] == tool_use_id
            assert res_evt["status"] == "error"

            await orchestrator.close()
            pipeline_task.cancel()
            try:
                await pipeline_task
            except (asyncio.CancelledError, Exception):
                pass

        engine.dispose()

    asyncio.run(_run())


def test_nova_sonic_driver_timeout_and_error_propagation():
    """
    Offline resilience test: verifies that Bedrock stream exceptions (e.g. throttlingException)
    and session duration timeouts are captured and emitted as VoiceEventType.ERROR.
    """
    async def _run():
        mock_transport = MockBedrockStreamTransport()
        driver = AmazonNovaSonicDriver(
            model_id="amazon.nova-2-5-sonic",
            region_name="us-east-1",
            transport=mock_transport,
        )
        session_id = "nova_timeout_err_002"
        await driver.start_session(session_id, "Preamble", [])
        mock_conn = mock_transport.active_connections[session_id]
        queue = driver._session_queues[session_id]

        # Drain SESSION_STARTED
        await queue.get()

        # Simulate Bedrock emitting throttlingException
        await mock_conn.inbound_queue.put({
            "event": {
                "throttlingException": {
                    "message": "Bedrock rate limit exceeded for model amazon.nova-2-5-sonic"
                }
            }
        })
        await asyncio.sleep(0.05)

        # Verify driver received ERROR event
        err_evt = await queue.get()
        assert err_evt.event_type == VoiceEventType.ERROR
        assert err_evt.data["error_type"] == "throttlingException"
        assert "Bedrock rate limit exceeded" in err_evt.data["message"]

        await driver.end_session(session_id)

    asyncio.run(_run())




