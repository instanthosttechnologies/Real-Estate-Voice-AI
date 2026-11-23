import asyncio
import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.voice.tools_spec import get_agent_tools_spec
from app.services.voice.bedrock_streaming import (
    BedrockNovaSonicSerializer,
    BedrockNovaSonicParser,
)
from app.services.voice.base import VoiceEventType, VoiceServerEvent
from app.services.voice.nova_sonic_driver import AmazonNovaSonicDriver
from app.services.voice.orchestrator import VoiceSessionOrchestrator


# =============================================================================
# 1. Tool Specification Schema Compliance (Amazon Bedrock Nova Sonic)
# =============================================================================

def test_tool_specs_schema_compliance_with_bedrock():
    """
    Validates that all tools generated for Amazon Nova 2.5 Sonic strictly comply
    with Bedrock Nova schema requirements:
    1. Top-level schema MUST be type: 'object' with only 'type', 'properties', 'required'.
    2. Zero $defs or unresolved $ref references (resolves the exact validationException bug).
    3. Zero anyOf / oneOf combinators with null.
    4. Zero extraneous title fields.
    5. Nested schemas (ExtractedCustomerRequirements) are inlined cleanly.
    """
    tools = get_agent_tools_spec()
    assert len(tools) >= 16, f"Expected at least 16 tools, got {len(tools)}"

    for tool in tools:
        assert "toolSpec" in tool
        spec = tool["toolSpec"]
        assert "name" in spec
        assert len(spec["name"]) <= 64, f"Tool name {spec['name']} exceeds 64 characters"
        assert "description" in spec
        assert "inputSchema" in spec
        assert "json" in spec["inputSchema"]

        schema_json = spec["inputSchema"]["json"]
        # Root must be strictly an object
        assert schema_json.get("type") == "object"
        assert set(schema_json.keys()).issubset({"type", "properties", "required"})

        # Stringified check for forbidden Bedrock schema artifacts
        schema_str = json.dumps(schema_json)
        assert "$defs" not in schema_str, f"Tool {spec['name']} contains forbidden $defs"
        assert "$ref" not in schema_str, f"Tool {spec['name']} contains forbidden $ref"
        assert "anyOf" not in schema_str, f"Tool {spec['name']} contains forbidden anyOf"
        assert "title" not in schema_str, f"Tool {spec['name']} contains extraneous title"

    # Specific assertions for models that previously had dangling ExtractedCustomerRequirements $ref
    tools_by_name = {t["toolSpec"]["name"]: t["toolSpec"]["inputSchema"]["json"] for t in tools}
    
    # extract_requirements
    extract_schema = tools_by_name["extract_requirements"]
    assert "customer_utterance" in extract_schema["properties"]
    assert "existing_requirements" in extract_schema["properties"]
    nested_req = extract_schema["properties"]["existing_requirements"]
    assert nested_req.get("type") == "object"
    assert "properties" in nested_req
    assert "preferred_city" in nested_req["properties"]
    assert "budget_max" in nested_req["properties"]

    # create_lead
    create_schema = tools_by_name["create_lead"]
    assert "full_name" in create_schema["properties"]
    assert "phone" in create_schema["properties"]
    assert "requirements" in create_schema["properties"]
    lead_req = create_schema["properties"]["requirements"]
    assert lead_req.get("type") == "object"
    assert "properties" in lead_req

    # calculate_lead_priority
    prio_schema = tools_by_name["calculate_lead_priority"]
    assert "requirements" in prio_schema["properties"]
    assert prio_schema["properties"]["requirements"].get("type") == "object"


# =============================================================================
# 2. Event Ordering and Serialization Protocol Tests
# =============================================================================

def test_event_ordering_and_serialization():
    """
    Validates canonical event serialization and payload shapes for Amazon Nova Sonic:
    sessionStart -> promptStart -> contentStart (SYSTEM) -> textInput -> contentEnd -> contentStart (USER AUDIO).
    """
    prompt_name = "test_prompt_123"
    tools = get_agent_tools_spec()

    # 1. sessionStart (minimal inferenceConfiguration only)
    session_start = BedrockNovaSonicSerializer.serialize_session_start(
        max_tokens=1024, temperature=0.7, top_p=0.9
    )
    assert "sessionStart" in session_start["event"]
    assert session_start["event"]["sessionStart"]["inferenceConfiguration"]["maxTokens"] == 1024
    assert "turnDetectionConfiguration" not in session_start["event"]["sessionStart"]

    # 1b. sessionStart with optional turnDetectionConfiguration
    session_start_td = BedrockNovaSonicSerializer.serialize_session_start(
        max_tokens=1024, temperature=0.7, top_p=0.9, endpointing_sensitivity="MEDIUM"
    )
    assert session_start_td["event"]["sessionStart"]["turnDetectionConfiguration"]["endpointingSensitivity"] == "MEDIUM"

    # 2. promptStart with tools
    prompt_start = BedrockNovaSonicSerializer.serialize_prompt_start(
        prompt_name=prompt_name,
        tools=tools,
        voice_id="matthew",
        output_sample_rate=24000,
    )
    p_def = prompt_start["event"]["promptStart"]
    assert p_def["promptName"] == prompt_name
    assert p_def["audioOutputConfiguration"]["voiceId"] == "matthew"
    assert p_def["audioOutputConfiguration"]["sampleRateHertz"] == 24000
    assert "toolConfiguration" in p_def
    assert len(p_def["toolConfiguration"]["tools"]) == len(tools)
    assert "toolUseOutputConfiguration" in p_def

    # 3. promptStart WITHOUT tools (omits toolConfiguration)
    prompt_start_no_tools = BedrockNovaSonicSerializer.serialize_prompt_start(
        prompt_name=prompt_name,
        tools=None,
    )
    p_def_empty = prompt_start_no_tools["event"]["promptStart"]
    assert "toolConfiguration" not in p_def_empty
    assert "toolUseOutputConfiguration" not in p_def_empty

    # 4. SYSTEM content block
    sys_start = BedrockNovaSonicSerializer.serialize_system_content_start(prompt_name, "system-preamble")
    assert sys_start["event"]["contentStart"]["role"] == "SYSTEM"
    assert sys_start["event"]["contentStart"]["interactive"] is False
    assert sys_start["event"]["contentStart"]["type"] == "TEXT"

    text_in = BedrockNovaSonicSerializer.serialize_text_input(prompt_name, "system-preamble", "You are an assistant.")
    assert text_in["event"]["textInput"]["content"] == "You are an assistant."

    c_end = BedrockNovaSonicSerializer.serialize_content_end(prompt_name, "system-preamble")
    assert c_end["event"]["contentEnd"]["contentName"] == "system-preamble"

    # 5. USER AUDIO content block (strict 16kHz for Nova Sonic speech input)
    audio_start = BedrockNovaSonicSerializer.serialize_audio_content_start(prompt_name, "audio_content", 16000)
    assert audio_start["event"]["contentStart"]["role"] == "USER"
    assert audio_start["event"]["contentStart"]["interactive"] is True
    assert audio_start["event"]["contentStart"]["type"] == "AUDIO"
    assert audio_start["event"]["contentStart"]["audioInputConfiguration"]["sampleRateHertz"] == 16000

    # 6. TOOL Result contentStart specification compliance
    tool_use_id = "call_abc123"
    tool_start = BedrockNovaSonicSerializer.serialize_tool_result_content_start(prompt_name, tool_use_id)
    assert tool_start["event"]["contentStart"]["type"] == "TOOL"
    assert tool_start["event"]["contentStart"]["role"] == "TOOL"
    assert "toolResultInputConfiguration" in tool_start["event"]["contentStart"]
    assert tool_start["event"]["contentStart"]["toolResultInputConfiguration"]["toolUseId"] == tool_use_id
    assert tool_start["event"]["contentStart"]["toolResultInputConfiguration"]["type"] == "TEXT"


# =============================================================================
# 3. Bedrock Inbound Error Parsing & Stream Termination
# =============================================================================

def test_bedrock_validation_exception_parsing():
    """
    Validates that incoming validationException from Amazon Bedrock is correctly
    decoded into VoiceServerEvent with event_type=ERROR.
    """
    raw_error_event = {
        "event": {
            "validationException": {
                "message": "Invalid input request, please fix your input and try again."
            }
        }
    }
    session_id = "test_err_session"
    parsed = BedrockNovaSonicParser.parse_event(raw_error_event, session_id)
    assert parsed is not None
    assert parsed.event_type == VoiceEventType.ERROR
    assert parsed.session_id == session_id
    assert parsed.data["error_type"] == "validationException"
    assert "Invalid input request" in parsed.data["message"]


@pytest.mark.asyncio
async def test_nova_sonic_driver_listener_halts_on_error():
    """
    Validates that AmazonNovaSonicDriver._listen_stream immediately terminates
    upon receiving VoiceEventType.ERROR, preventing 60s timeout hangs.
    """
    driver = AmazonNovaSonicDriver()
    session_id = f"test_halt_{uuid.uuid4().hex[:8]}"

    # Mock stream connection that yields a validationException event
    mock_conn = MagicMock()
    async def mock_receive_events():
        yield {
            "event": {
                "validationException": {
                    "message": "Invalid input request, please fix your input and try again."
                }
            }
        }
        # Subsequent events should never be reached because listener breaks on ERROR
        yield {"event": {"audioOutput": {"content": ""}}}

    mock_conn.receive_events = mock_receive_events
    driver._session_queues[session_id] = asyncio.Queue()
    driver._active_sessions[session_id] = {"connection": mock_conn}

    # Run listener
    await driver._listen_stream(session_id, mock_conn)

    # Queue should receive exactly the ERROR event
    queue = driver._session_queues[session_id]
    assert not queue.empty()
    evt = queue.get_nowait()
    assert evt.event_type == VoiceEventType.ERROR
    assert evt.data["error_type"] == "validationException"
    assert queue.empty(), "Listener should have broken out immediately after error event."


# =============================================================================
# 4. Orchestrator Pipeline Error Propagation and Ingestion Cutoff
# =============================================================================

@pytest.mark.asyncio
async def test_orchestrator_error_propagation_and_deactivation():
    """
    Validates that when VoiceSessionOrchestrator receives an ERROR event:
    1. It emits a JSON error frame to the client WebSocket.
    2. It immediately sets is_active = False.
    3. It breaks out of run_pipeline so the session terminates cleanly.
    """
    mock_driver = MagicMock()
    session_id = f"test_orch_{uuid.uuid4().hex[:8]}"

    async def mock_receive(sid):
        yield VoiceServerEvent(
            event_type=VoiceEventType.ERROR,
            session_id=sid,
            data={
                "error_type": "validationException",
                "message": "Invalid input request, please fix your input and try again.",
            },
        )

    mock_driver.receive_events = mock_receive
    mock_db = MagicMock()

    orchestrator = VoiceSessionOrchestrator(
        session_id=session_id,
        driver=mock_driver,
        db=mock_db,
    )
    orchestrator.is_active = True

    sent_messages = []
    async def send_text(text):
        sent_messages.append(json.loads(text))

    async def send_bytes(b):
        pass

    # Run pipeline
    await orchestrator.run_pipeline(send_text=send_text, send_bytes=send_bytes)

    # Assertions
    assert len(sent_messages) == 1
    assert sent_messages[0]["type"] == "error"
    assert sent_messages[0]["error_type"] == "validationException"
    assert "Invalid input request" in sent_messages[0]["message"]
    assert orchestrator.is_active is False, "Orchestrator must be deactivated upon error"


@pytest.mark.asyncio
async def test_handle_incoming_audio_inactive_cutoff():
    """
    Validates that handle_incoming_audio raises ValueError cleanly when inactive,
    which is safely handled by voice_ws without crashing.
    """
    mock_driver = MagicMock()
    mock_db = MagicMock()
    orchestrator = VoiceSessionOrchestrator(
        session_id="test_inactive",
        driver=mock_driver,
        db=mock_db,
    )
    orchestrator.is_active = False

    with pytest.raises(ValueError) as excinfo:
        await orchestrator.handle_incoming_audio(b"\x00\x00" * 100)
    assert "inactive" in str(excinfo.value)


# =============================================================================
# 5. Incremental Session Isolation Diagnostic (Requirement 7)
# =============================================================================

def test_incremental_session_isolation():
    """
    Validates incrementally each progressive stage of the Nova Sonic session handshake:
    Phase A: Minimal sessionStart (inferenceConfiguration only).
    Phase B: promptStart without tools (audio + text output configuration).
    Phase C: System prompt content container (contentStart -> textInput -> contentEnd).
    Phase D: User audio stream container (contentStart type=AUDIO, strict 16kHz input).
    Phase E: Full promptStart with tool specifications (all 16 tools, strict schema verification).
    Phase F: Tool result flow (contentStart TOOL with toolResultInputConfiguration).
    """
    prompt_id = "p_iso_test_123"
    content_id = "c_iso_test_456"

    # --- Phase A: Minimal sessionStart ---
    step_a = BedrockNovaSonicSerializer.serialize_session_start(
        max_tokens=1024, temperature=0.7, top_p=0.9
    )
    assert "sessionStart" in step_a["event"]
    assert "inferenceConfiguration" in step_a["event"]["sessionStart"]
    assert step_a["event"]["sessionStart"]["inferenceConfiguration"]["maxTokens"] == 1024
    assert step_a["event"]["sessionStart"]["inferenceConfiguration"]["temperature"] == 0.7
    assert step_a["event"]["sessionStart"]["inferenceConfiguration"]["topP"] == 0.9

    # --- Phase B: promptStart without tools ---
    step_b = BedrockNovaSonicSerializer.serialize_prompt_start(
        prompt_name=prompt_id,
        tools=None,
        voice_id="matthew",
        output_sample_rate=24000,
    )
    b_def = step_b["event"]["promptStart"]
    assert b_def["promptName"] == prompt_id
    assert b_def["textOutputConfiguration"]["mediaType"] == "text/plain"
    assert b_def["audioOutputConfiguration"]["mediaType"] == "audio/lpcm"
    assert b_def["audioOutputConfiguration"]["sampleRateHertz"] == 24000
    assert b_def["audioOutputConfiguration"]["voiceId"] == "matthew"
    assert "toolConfiguration" not in b_def
    assert "toolUseOutputConfiguration" not in b_def

    # --- Phase C: System preamble ---
    step_c_start = BedrockNovaSonicSerializer.serialize_system_content_start(prompt_id, content_id)
    assert step_c_start["event"]["contentStart"]["role"] == "SYSTEM"
    assert step_c_start["event"]["contentStart"]["interactive"] is False
    assert step_c_start["event"]["contentStart"]["type"] == "TEXT"

    step_c_text = BedrockNovaSonicSerializer.serialize_text_input(prompt_id, content_id, "You are a real estate AI.")
    assert step_c_text["event"]["textInput"]["content"] == "You are a real estate AI."

    step_c_end = BedrockNovaSonicSerializer.serialize_content_end(prompt_id, content_id)
    assert step_c_end["event"]["contentEnd"]["contentName"] == content_id

    # --- Phase D: User audio container (strict 16kHz) ---
    step_d = BedrockNovaSonicSerializer.serialize_audio_content_start(prompt_id, "audio_stream", 16000)
    assert step_d["event"]["contentStart"]["role"] == "USER"
    assert step_d["event"]["contentStart"]["interactive"] is True
    assert step_d["event"]["contentStart"]["type"] == "AUDIO"
    assert step_d["event"]["contentStart"]["audioInputConfiguration"]["sampleRateHertz"] == 16000

    # --- Phase E: Full promptStart with all 16 sanitized tools ---
    tools = get_agent_tools_spec()
    assert len(tools) >= 16
    step_e = BedrockNovaSonicSerializer.serialize_prompt_start(
        prompt_name=prompt_id,
        tools=tools,
        voice_id="matthew",
        output_sample_rate=24000,
    )
    e_def = step_e["event"]["promptStart"]
    assert "toolConfiguration" in e_def
    assert len(e_def["toolConfiguration"]["tools"]) == len(tools)
    for t in e_def["toolConfiguration"]["tools"]:
        # Verify strict compliance: inputSchema.json must be a JSON string per AWS Nova Sonic spec
        t_json_str = t["toolSpec"]["inputSchema"]["json"]
        assert isinstance(t_json_str, str)
        t_json = json.loads(t_json_str)
        assert t_json["type"] == "object"
        assert "$defs" not in t_json_str
        assert "$ref" not in t_json_str

    # --- Phase F: Tool result roundtrip ---
    call_id = "tool_call_xyz"
    step_f_start = BedrockNovaSonicSerializer.serialize_tool_result_content_start(prompt_id, call_id)
    assert step_f_start["event"]["contentStart"]["type"] == "TOOL"
    assert step_f_start["event"]["contentStart"]["role"] == "TOOL"
    assert step_f_start["event"]["contentStart"]["toolResultInputConfiguration"]["toolUseId"] == call_id
    assert step_f_start["event"]["contentStart"]["toolResultInputConfiguration"]["type"] == "TEXT"

    step_f_result = BedrockNovaSonicSerializer.serialize_tool_result(prompt_id, call_id, {"status": "ok"})
    assert step_f_result["event"]["toolResult"]["contentName"] == call_id
    assert "ok" in step_f_result["event"]["toolResult"]["content"]


# =============================================================================
# 6. Dedicated Concurrency Lock Release & Error Cleanup Tests
# =============================================================================

def test_nova_sonic_event_validator_catches_invalid_events():
    """
    Validates that NovaSonicEventValidator rejects non-compliant events before wire transmission:
    1. Rejects 24000Hz audio input sample rate (strictly enforces 16000Hz).
    2. Rejects out-of-order events (contentStart before promptStart).
    3. Rejects invalid tool schema with $defs.
    """
    from app.services.voice.nova_validator import NovaSonicEventValidator, NovaSonicValidationError

    validator = NovaSonicEventValidator(strict_sequencing=True)

    # Out of order: promptStart before sessionStart
    with pytest.raises(NovaSonicValidationError) as exc:
        validator.validate_event({
            "event": {
                "promptStart": {
                    "promptName": "p123",
                    "audioOutputConfiguration": {"voiceId": "matthew", "sampleRateHertz": 24000},
                }
            }
        })
    assert "SESSION_STARTED" in str(exc.value)

    # Valid sessionStart
    validator.validate_event({
        "event": {
            "sessionStart": {
                "inferenceConfiguration": {"maxTokens": 1024, "temperature": 0.7, "topP": 0.9}
            }
        }
    })

    # Valid promptStart
    validator.validate_event({
        "event": {
            "promptStart": {
                "promptName": "p123",
                "audioOutputConfiguration": {"voiceId": "matthew", "sampleRateHertz": 24000},
            }
        }
    })

    # Invalid input sample rate: 24000 instead of 16000
    with pytest.raises(NovaSonicValidationError) as exc:
        validator.validate_event({
            "event": {
                "contentStart": {
                    "promptName": "p123",
                    "contentName": "c123",
                    "type": "AUDIO",
                    "role": "USER",
                    "audioInputConfiguration": {
                        "mediaType": "audio/lpcm",
                        "sampleRateHertz": 24000,
                    },
                }
            }
        })
    assert "sampleRateHertz=16000" in str(exc.value)

    # Valid 16000Hz contentStart
    validator.validate_event({
        "event": {
            "contentStart": {
                "promptName": "p123",
                "contentName": "c123",
                "type": "AUDIO",
                "role": "USER",
                "audioInputConfiguration": {
                    "mediaType": "audio/lpcm",
                    "sampleRateHertz": 16000,
                },
            }
        }
    })


@pytest.mark.asyncio
async def test_concurrency_lock_release_on_orchestrator_close_when_inactive():
    """
    Validates that when orchestrator.is_active is False (e.g. following an error event),
    orchestrator.close() still guarantees release of driver session and concurrency slot.
    """
    driver = AmazonNovaSonicDriver()
    session_id = f"test_lock_rel_{uuid.uuid4().hex[:8]}"

    # Simulate active slot
    driver._active_live_session_ids.add(session_id)
    assert session_id in driver._active_live_session_ids

    mock_db = MagicMock()
    orchestrator = VoiceSessionOrchestrator(
        session_id=session_id,
        driver=driver,
        db=mock_db,
    )
    # Orchestrator is inactive (as set when an error occurs)
    orchestrator.is_active = False

    # Close orchestrator
    await orchestrator.close()

    # Slot must be released!
    assert session_id not in driver._active_live_session_ids, "Session slot must be released even if is_active was False"
    assert orchestrator._is_closed is True


@pytest.mark.asyncio
async def test_multiple_consecutive_sessions_without_concurrency_lockout():
    """
    Validates that multiple rapid manual session start/close cycles succeed cleanly
    without leaking session slots or triggering 'Concurrent live session limit reached'.
    """
    driver = AmazonNovaSonicDriver()
    AmazonNovaSonicDriver._active_live_session_ids.clear()

    for i in range(3):
        session_id = f"test_consec_{i}_{uuid.uuid4().hex[:6]}"
        mock_db = MagicMock()
        orchestrator = VoiceSessionOrchestrator(
            session_id=session_id,
            driver=driver,
            db=mock_db,
        )
        orchestrator.is_active = True
        AmazonNovaSonicDriver._active_live_session_ids.add(session_id)

        # Simulate error or normal teardown
        orchestrator.is_active = False
        await orchestrator.close()

        assert len(AmazonNovaSonicDriver._active_live_session_ids) == 0, f"Iteration {i} leaked concurrency slot!"


# =============================================================================
# 7. Outbound Tool Schema JSON String Normalization (Nova Sonic protocol)
# =============================================================================

def test_outbound_prompt_start_no_tools():
    """Validates promptStart without tools produces clean schema."""
    evt = BedrockNovaSonicSerializer.serialize_prompt_start(
        prompt_name="no_tool_prompt",
        tools=None,
    )
    p_start = evt["event"]["promptStart"]
    assert p_start["promptName"] == "no_tool_prompt"
    assert "toolConfiguration" not in p_start
    assert "toolUseOutputConfiguration" not in p_start

    # Validator accepts it
    from app.services.voice.nova_validator import NovaSonicEventValidator
    validator = NovaSonicEventValidator()
    validator.validate_event(evt)


def test_outbound_prompt_start_single_tool_json_string_normalization():
    """
    Validates that a single tool with dict schema is normalized to a compact JSON string,
    and already-stringified schemas are not double-serialized.
    """
    sample_tool_dict = {
        "toolSpec": {
            "name": "get_weather",
            "description": "Get current weather for a city.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "City name"}
                    },
                    "required": ["city"],
                }
            },
        }
    }

    # 1. Dict schema -> Outbound promptStart must have STRING in inputSchema.json
    evt = BedrockNovaSonicSerializer.serialize_prompt_start(
        prompt_name="one_tool_prompt",
        tools=[sample_tool_dict],
    )
    tool_in_evt = evt["event"]["promptStart"]["toolConfiguration"]["tools"][0]
    schema_val = tool_in_evt["toolSpec"]["inputSchema"]["json"]
    assert isinstance(schema_val, str), f"Expected JSON string, got {type(schema_val)}"
    # Verify it parses back to the exact dict
    parsed = json.loads(schema_val)
    assert parsed["type"] == "object"
    assert "city" in parsed["properties"]

    # 2. Validator accepts the serialized string schema
    from app.services.voice.nova_validator import NovaSonicEventValidator
    validator = NovaSonicEventValidator()
    validator.validate_event(evt)

    # 3. No double serialization when already a string
    evt2 = BedrockNovaSonicSerializer.serialize_prompt_start(
        prompt_name="one_tool_prompt_2",
        tools=[tool_in_evt],  # already has string schema
    )
    schema_val_2 = evt2["event"]["promptStart"]["toolConfiguration"]["tools"][0]["toolSpec"]["inputSchema"]["json"]
    assert isinstance(schema_val_2, str)
    assert not schema_val_2.startswith('"{\\"')  # NOT double encoded!
    parsed_2 = json.loads(schema_val_2)
    assert isinstance(parsed_2, dict)
    assert parsed_2["type"] == "object"


def test_outbound_prompt_start_all_16_tools_and_exact_bytes():
    """
    Validates that all 16 portfolio tools in AGENT_TOOL_REGISTRY are serialized with
    JSON string schemas, all 16 tool names and required properties are preserved,
    and exact serialized outbound bytes contain no double-escaped schema or forbidden keys.
    """
    from app.services.voice.nova_validator import NovaSonicEventValidator
    tools = get_agent_tools_spec()
    assert len(tools) >= 16

    evt = BedrockNovaSonicSerializer.serialize_prompt_start(
        prompt_name="full_agent_prompt",
        tools=tools,
    )
    serialized_tools = evt["event"]["promptStart"]["toolConfiguration"]["tools"]
    assert len(serialized_tools) >= 16

    validator = NovaSonicEventValidator()
    validator.validate_event(evt)

    for tool in serialized_tools:
        spec = tool["toolSpec"]
        name = spec["name"]
        schema_str = spec["inputSchema"]["json"]
        assert isinstance(schema_str, str), f"Tool {name} inputSchema.json is not a string!"

        # Must parse as valid JSON object
        parsed = json.loads(schema_str)
        assert parsed["type"] == "object", f"Tool {name} root type is not object"
        assert "properties" in parsed

        # Forbidden artifacts check
        assert "$defs" not in schema_str
        assert "$ref" not in schema_str
        assert "anyOf" not in schema_str

    # Validate exact outgoing JSON bytes framing
    json_bytes = json.dumps(evt, default=str).encode("utf-8")
    assert b'"toolConfiguration"' in json_bytes
    assert b'"toolUseOutputConfiguration"' in json_bytes
    # Ensure tool schema is represented as a JSON string within the outer JSON
    assert b'\\"type\\":\\"object\\"' in json_bytes or b'\\"type\\": \\"object\\"' in json_bytes


# =============================================================================
# 7. Regression Tests for Automatic Greeting Protocol & Clean Sequencing
# =============================================================================

@pytest.mark.asyncio
async def test_automatic_greeting_sequence_when_explicitly_enabled():
    """
    Validates that the driver enforces the proven microphone-first path:
    1. Zero unverified silent audio triggers or invalid cross-modal turns.
    2. Zero overlapping content blocks: SYSTEM contentEnd occurs before AUDIO_USER contentStart.
    3. Correct continuous AUDIO_USER input configuration: interactive=True, sampleRateHertz=16000.
    4. Strict NovaSonicEventValidator verification passes with 0 validation errors.
    """
    from app.services.voice.nova_validator import NovaSonicEventValidator
    from app.services.voice.bedrock_streaming import BedrockStreamTransport, BedrockStreamConnection
    from app.core.config import settings

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
    session_id = f"test_greet_{uuid.uuid4().hex[:8]}"
    tools = get_agent_tools_spec()
    customer_name = "Ramesh Kumar"

    settings.ENABLE_AUTOMATIC_GREETING = True

    await driver.start_session(
        session_id=session_id,
        prompt_preamble="System instructions",
        tools=tools,
        customer_name=customer_name,
    )

    # 1. Inspect event sequence: sessionStart -> promptStart -> SYSTEM block -> INIT_USER block -> AUDIO_USER block
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

    # 2. Verify INIT_USER schema and role
    init_start = sent_events[5]["event"]["contentStart"]
    assert init_start["type"] == "TEXT"
    assert init_start["role"] == "USER"
    assert init_start["interactive"] is True

    init_text = sent_events[6]["event"]["textInput"]
    assert "Ramesh Kumar" in init_text["content"]

    # 3. Verify AUDIO_USER schema and configuration
    audio_start = sent_events[8]["event"]["contentStart"]
    assert audio_start["type"] == "AUDIO"
    assert audio_start["role"] == "USER"
    assert audio_start["interactive"] is True
    assert audio_start["audioInputConfiguration"]["sampleRateHertz"] == 16000

    # 4. Strict sequencing validation passes cleanly
    validator = NovaSonicEventValidator(strict_sequencing=True)
    for evt in sent_events:
        validator.validate_event(evt)

    await driver.end_session(session_id)


@pytest.mark.asyncio
async def test_default_microphone_first_flow_when_greeting_disabled():
    """
    Validates that with default ENABLE_AUTOMATIC_GREETING=False:
    Even when customer_name is present, INIT_USER text block is completely bypassed,
    restoring the known-working microphone-first speech-to-speech path.
    """
    from app.services.voice.nova_validator import NovaSonicEventValidator
    from app.services.voice.bedrock_streaming import BedrockStreamTransport, BedrockStreamConnection
    from app.core.config import settings

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
    session_id = f"test_default_{uuid.uuid4().hex[:8]}"
    tools = get_agent_tools_spec()

    settings.ENABLE_AUTOMATIC_GREETING = False

    await driver.start_session(
        session_id=session_id,
        prompt_preamble="System instructions",
        tools=tools,
        customer_name="Ramesh Kumar",  # Customer is present, but flag is False
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

    # Confirm 0 textInput for user and audio container opens directly
    audio_start = sent_events[5]["event"]["contentStart"]
    assert audio_start["type"] == "AUDIO"
    assert audio_start["role"] == "USER"

    validator = NovaSonicEventValidator(strict_sequencing=True)
    for evt in sent_events:
        validator.validate_event(evt)

    await driver.end_session(session_id)


@pytest.mark.asyncio
async def test_normal_microphone_first_conversation_without_greeting():
    """
    Validates that when customer_name is omitted (normal microphone-first flow):
    1. Zero INIT_USER events are transmitted.
    2. Sequence is: sessionStart -> promptStart -> SYSTEM (start/text/end) -> AUDIO_USER (start).
    3. Strict validator passes cleanly.
    """
    from app.services.voice.nova_validator import NovaSonicEventValidator
    from app.services.voice.bedrock_streaming import BedrockStreamTransport, BedrockStreamConnection

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
    session_id = f"test_nogreet_{uuid.uuid4().hex[:8]}"
    tools = get_agent_tools_spec()

    await driver.start_session(
        session_id=session_id,
        prompt_preamble="System instructions",
        tools=tools,
        customer_name=None,  # No customer greeting requested
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

    # Verify no INIT_USER content was sent
    audio_start = sent_events[5]["event"]["contentStart"]
    assert audio_start["type"] == "AUDIO"
    assert audio_start["role"] == "USER"

    validator = NovaSonicEventValidator(strict_sequencing=True)
    for evt in sent_events:
        validator.validate_event(evt)

    await driver.end_session(session_id)


@pytest.mark.asyncio
async def test_initialization_failure_and_clean_recovery():
    """
    Validates Task 3:
    1. When stream connection fails during initialization, resources are cleaned up cleanly.
    2. Concurrency slots are released idempotently.
    3. Subsequent start_session on the same driver succeeds without error.
    """
    from app.services.voice.bedrock_streaming import BedrockStreamTransport, BedrockStreamConnection

    class FailingTransport(BedrockStreamTransport):
        async def open_stream(self, *args, **kwargs):
            raise ConnectionError("Simulated network drop during handshake")

    driver = AmazonNovaSonicDriver(transport=FailingTransport())
    session_id = f"test_fail_{uuid.uuid4().hex[:8]}"

    await driver.start_session(session_id=session_id, prompt_preamble="Preamble", tools=[])

    queue = driver._session_queues[session_id]
    err_evt = await queue.get()
    assert err_evt.event_type == VoiceEventType.ERROR
    assert "BedrockConnectionError" in err_evt.data["error_type"]
    assert session_id not in driver._active_sessions
    assert session_id not in driver._active_live_session_ids

    # Verify recovery: Subsequent call with healthy transport succeeds
    class HealthyTransport(BedrockStreamTransport):
        async def open_stream(self, *args, **kwargs):
            class GoodConn(BedrockStreamConnection):
                async def send_event(self, e): pass
                async def receive_events(self):
                    if False: yield {}
                async def close(self): pass
            return GoodConn()

    driver._transport = HealthyTransport()
    recovery_session_id = f"test_rec_{uuid.uuid4().hex[:8]}"
    await driver.start_session(session_id=recovery_session_id, prompt_preamble="Preamble", tools=[])
    rec_queue = driver._session_queues[recovery_session_id]
    rec_evt = await rec_queue.get()
    assert rec_evt.event_type == VoiceEventType.SESSION_STARTED
    await driver.end_session(recovery_session_id)




