import base64
import json
import re
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class NovaSonicValidationError(ValueError):
    """Raised when an outbound Amazon Nova 2.5 Sonic event violates protocol specifications or sequencing."""
    pass


class NovaSonicProtocolState(str, Enum):
    INITIAL = "INITIAL"
    SESSION_STARTED = "SESSION_STARTED"
    PROMPT_STARTED = "PROMPT_STARTED"
    SESSION_ENDED = "SESSION_ENDED"


class NovaSonicEventValidator:
    """
    Stateful protocol and schema validator for Amazon Nova 2.5 Sonic bidirectional EventStream.
    Enforces official Bedrock constraints:
    1. Envelope structure and required parameters.
    2. Input sample rate strictness (16000 Hz Linear PCM).
    3. Tool schema compliance (type: 'object', no $defs, no $ref, no anyOf/oneOf with null, no titles).
    4. Canonical event ordering and turn state machine supporting concurrent USER AUDIO & TOOL content containers:
       sessionStart -> promptStart -> [contentStart -> (textInput|audioInput|toolResult) -> contentEnd]* -> promptEnd -> sessionEnd.
    """

    PROMPT_NAME_PATTERN = re.compile(r"^([0-9a-zA-Z][_-]?){1,100}$")
    VALID_ROLES = {"USER", "SYSTEM", "ASSISTANT", "TOOL"}
    VALID_CONTENT_TYPES = {"AUDIO", "TEXT", "TOOL"}

    def __init__(self, strict_sequencing: bool = False):
        self.strict_sequencing = strict_sequencing
        self.state = NovaSonicProtocolState.INITIAL
        self.current_prompt_name: Optional[str] = None
        self.active_contents: Dict[str, Dict[str, Any]] = {}

    def reset(self) -> None:
        self.state = NovaSonicProtocolState.INITIAL
        self.current_prompt_name = None
        self.active_contents.clear()

    def validate_event(self, event_dict: Dict[str, Any]) -> None:
        """Validates a single outgoing event envelope against Bedrock Nova Sonic specifications."""
        if not isinstance(event_dict, dict):
            raise NovaSonicValidationError(f"Outbound event must be a dictionary, got {type(event_dict)}")

        # Unpack "event" wrapper if present
        body = event_dict.get("event", event_dict)
        if not isinstance(body, dict) or not body:
            raise NovaSonicValidationError("Event body must be a non-empty dictionary.")

        keys = list(body.keys())
        if len(keys) != 1:
            raise NovaSonicValidationError(f"Event body must contain exactly one event payload, found: {keys}")

        event_name = keys[0]
        payload = body[event_name]
        if not isinstance(payload, dict):
            raise NovaSonicValidationError(f"Payload for '{event_name}' must be a dictionary.")

        if event_name == "sessionStart":
            self._validate_session_start(payload)
        elif event_name == "promptStart":
            self._validate_prompt_start(payload)
        elif event_name == "contentStart":
            self._validate_content_start(payload)
        elif event_name == "textInput":
            self._validate_text_input(payload)
        elif event_name == "audioInput":
            self._validate_audio_input(payload)
        elif event_name == "toolResult":
            self._validate_tool_result(payload)
        elif event_name == "contentEnd":
            self._validate_content_end(payload)
        elif event_name == "promptEnd":
            self._validate_prompt_end(payload)
        elif event_name == "sessionEnd":
            self._validate_session_end(payload)
        else:
            raise NovaSonicValidationError(f"Unknown Bedrock Nova Sonic event: '{event_name}'")

    def _validate_session_start(self, payload: Dict[str, Any]) -> None:
        if self.strict_sequencing and self.state not in (
            NovaSonicProtocolState.INITIAL,
            NovaSonicProtocolState.SESSION_ENDED,
        ):
            raise NovaSonicValidationError(
                f"sessionStart is only valid in INITIAL or SESSION_ENDED state, currently in {self.state.value}"
            )

        if "inferenceConfiguration" not in payload:
            raise NovaSonicValidationError("sessionStart requires 'inferenceConfiguration'.")

        inf_cfg = payload["inferenceConfiguration"]
        if not isinstance(inf_cfg, dict):
            raise NovaSonicValidationError("'inferenceConfiguration' must be a dictionary.")

        if "maxTokens" in inf_cfg and (not isinstance(inf_cfg["maxTokens"], int) or inf_cfg["maxTokens"] <= 0):
            raise NovaSonicValidationError(f"Invalid maxTokens: {inf_cfg.get('maxTokens')}")

        if "temperature" in inf_cfg:
            temp = inf_cfg["temperature"]
            if not isinstance(temp, (int, float)) or not (0.0 <= temp <= 1.0):
                raise NovaSonicValidationError(f"Invalid temperature (must be 0.0-1.0): {temp}")

        if "topP" in inf_cfg:
            top_p = inf_cfg["topP"]
            if not isinstance(top_p, (int, float)) or not (0.0 <= top_p <= 1.0):
                raise NovaSonicValidationError(f"Invalid topP (must be 0.0-1.0): {top_p}")

        self.state = NovaSonicProtocolState.SESSION_STARTED

    def _validate_prompt_start(self, payload: Dict[str, Any]) -> None:
        if self.strict_sequencing and self.state != NovaSonicProtocolState.SESSION_STARTED:
            raise NovaSonicValidationError(
                f"promptStart is only valid in SESSION_STARTED state, currently in {self.state.value}"
            )

        prompt_name = payload.get("promptName")
        if not prompt_name or not isinstance(prompt_name, str):
            raise NovaSonicValidationError("promptStart requires a string 'promptName'.")
        if not self.PROMPT_NAME_PATTERN.match(prompt_name):
            raise NovaSonicValidationError(
                f"promptName '{prompt_name}' does not match Bedrock regex pattern ^([0-9a-zA-Z][_-]?){{1,100}}$"
            )

        if "audioOutputConfiguration" not in payload:
            raise NovaSonicValidationError("promptStart requires 'audioOutputConfiguration'.")
        audio_out = payload["audioOutputConfiguration"]
        if not isinstance(audio_out, dict):
            raise NovaSonicValidationError("'audioOutputConfiguration' must be a dictionary.")
        if not audio_out.get("voiceId"):
            raise NovaSonicValidationError("'audioOutputConfiguration' requires a non-empty 'voiceId'.")

        # Validate tools if present
        if "toolConfiguration" in payload:
            tool_cfg = payload["toolConfiguration"]
            if not isinstance(tool_cfg, dict) or "tools" not in tool_cfg:
                raise NovaSonicValidationError("'toolConfiguration' must contain 'tools' list.")
            tools = tool_cfg["tools"]
            if not isinstance(tools, list):
                raise NovaSonicValidationError("'tools' must be a list.")
            for idx, tool in enumerate(tools):
                self._validate_tool_spec(tool, idx)

        self.current_prompt_name = prompt_name
        self.state = NovaSonicProtocolState.PROMPT_STARTED

    def _validate_tool_spec(self, tool: Dict[str, Any], idx: int) -> None:
        if not isinstance(tool, dict) or "toolSpec" not in tool:
            raise NovaSonicValidationError(f"Tool at index {idx} missing 'toolSpec'.")
        spec = tool["toolSpec"]
        if not spec.get("name") or len(spec["name"]) > 64:
            raise NovaSonicValidationError(f"Tool at index {idx} has invalid name (must be 1-64 chars).")
        if "inputSchema" not in spec or "json" not in spec["inputSchema"]:
            raise NovaSonicValidationError(f"Tool '{spec.get('name')}' missing 'inputSchema.json'.")

        schema_raw = spec["inputSchema"]["json"]
        if isinstance(schema_raw, str):
            try:
                schema_json = json.loads(schema_raw)
            except Exception as e:
                raise NovaSonicValidationError(f"Tool '{spec.get('name')}' inputSchema.json is not valid JSON string: {e}")
        elif isinstance(schema_raw, dict):
            schema_json = schema_raw
        else:
            raise NovaSonicValidationError(
                f"Tool '{spec.get('name')}' inputSchema.json must be a dict or a JSON string, got {type(schema_raw).__name__}."
            )

        if not isinstance(schema_json, dict) or schema_json.get("type") != "object":
            raise NovaSonicValidationError(f"Tool '{spec.get('name')}' inputSchema root must be 'object'.")

        # Ensure no forbidden artifacts
        raw_schema = json.dumps(schema_json)
        if "$defs" in raw_schema:
            raise NovaSonicValidationError(f"Tool '{spec.get('name')}' contains forbidden '$defs'.")
        if "$ref" in raw_schema:
            raise NovaSonicValidationError(f"Tool '{spec.get('name')}' contains unresolved '$ref'.")
        if "anyOf" in raw_schema or "oneOf" in raw_schema:
            raise NovaSonicValidationError(f"Tool '{spec.get('name')}' contains forbidden anyOf/oneOf combinator.")

    def _validate_content_start(self, payload: Dict[str, Any]) -> None:
        if self.strict_sequencing and self.state != NovaSonicProtocolState.PROMPT_STARTED:
            raise NovaSonicValidationError(
                f"contentStart is only valid in PROMPT_STARTED state, currently in {self.state.value}"
            )

        prompt_name = payload.get("promptName")
        if self.strict_sequencing and self.current_prompt_name and prompt_name != self.current_prompt_name:
            raise NovaSonicValidationError(
                f"contentStart promptName '{prompt_name}' does not match active prompt '{self.current_prompt_name}'"
            )

        content_name = payload.get("contentName")
        if not content_name or not isinstance(content_name, str):
            raise NovaSonicValidationError("contentStart requires a string 'contentName'.")

        c_type = payload.get("type")
        if c_type not in self.VALID_CONTENT_TYPES:
            raise NovaSonicValidationError(
                f"contentStart type '{c_type}' is invalid. Expected one of {self.VALID_CONTENT_TYPES}"
            )

        role = payload.get("role")
        if role not in self.VALID_ROLES:
            raise NovaSonicValidationError(
                f"contentStart role '{role}' is invalid. Expected one of {self.VALID_ROLES}"
            )

        # Audio configuration check
        if c_type == "AUDIO":
            if "audioInputConfiguration" not in payload:
                raise NovaSonicValidationError("contentStart(AUDIO) requires 'audioInputConfiguration'.")
            audio_in = payload["audioInputConfiguration"]
            if audio_in.get("mediaType") != "audio/lpcm":
                raise NovaSonicValidationError(
                    f"Invalid audioInputConfiguration mediaType: '{audio_in.get('mediaType')}', expected 'audio/lpcm'"
                )
            # Strict Nova Sonic input sample rate check: must be 16000
            rate = audio_in.get("sampleRateHertz")
            if rate != 16000:
                raise NovaSonicValidationError(
                    f"Nova Sonic input speech encoder requires sampleRateHertz=16000, got {rate}"
                )

        # Text configuration check
        if c_type == "TEXT":
            if "textInputConfiguration" not in payload:
                raise NovaSonicValidationError("contentStart(TEXT) requires 'textInputConfiguration'.")
            text_cfg = payload["textInputConfiguration"]
            if not isinstance(text_cfg, dict) or text_cfg.get("mediaType") != "text/plain":
                raise NovaSonicValidationError(
                    f"Invalid textInputConfiguration mediaType: '{text_cfg.get('mediaType') if isinstance(text_cfg, dict) else text_cfg}', expected 'text/plain'"
                )

        # Tool result configuration check
        if c_type == "TOOL":
            if "toolResultInputConfiguration" not in payload:
                raise NovaSonicValidationError("contentStart(TOOL) requires 'toolResultInputConfiguration'.")
            tool_cfg = payload["toolResultInputConfiguration"]
            if not tool_cfg.get("toolUseId"):
                raise NovaSonicValidationError("'toolResultInputConfiguration' requires 'toolUseId'.")

        # Disallow opening concurrent content blocks for the same role in strict sequencing
        if self.strict_sequencing:
            for active_name, active_meta in self.active_contents.items():
                if active_meta.get("role") == role:
                    raise NovaSonicValidationError(
                        f"Cannot open contentStart('{content_name}', role='{role}') while content block '{active_name}' "
                        f"for role '{role}' is still active. Send contentEnd first."
                    )

        self.active_contents[content_name] = {
            "type": c_type,
            "role": role,
            "promptName": prompt_name,
        }

    def _validate_text_input(self, payload: Dict[str, Any]) -> None:
        content_name = payload.get("contentName")
        if self.strict_sequencing and content_name:
            if content_name not in self.active_contents:
                raise NovaSonicValidationError(f"textInput references inactive contentName '{content_name}'")
            if self.active_contents[content_name]["type"] != "TEXT":
                raise NovaSonicValidationError(
                    f"textInput cannot be sent in content block '{content_name}' of type '{self.active_contents[content_name]['type']}'"
                )

        if "content" not in payload or not isinstance(payload["content"], str):
            raise NovaSonicValidationError("textInput requires a string 'content' field.")

    def _validate_audio_input(self, payload: Dict[str, Any]) -> None:
        content_name = payload.get("contentName")
        if self.strict_sequencing and content_name:
            if content_name not in self.active_contents:
                raise NovaSonicValidationError(f"audioInput references inactive contentName '{content_name}'")
            if self.active_contents[content_name]["type"] != "AUDIO":
                raise NovaSonicValidationError(
                    f"audioInput cannot be sent in content block '{content_name}' of type '{self.active_contents[content_name]['type']}'"
                )

        raw_b64 = payload.get("content")
        if not raw_b64 or not isinstance(raw_b64, str):
            raise NovaSonicValidationError("audioInput requires a non-empty base64 string in 'content'.")

        try:
            base64.b64decode(raw_b64)
        except Exception as e:
            raise NovaSonicValidationError(f"audioInput content is not valid base64: {e}")

    def _validate_tool_result(self, payload: Dict[str, Any]) -> None:
        content_name = payload.get("contentName")
        if self.strict_sequencing and content_name:
            if content_name not in self.active_contents:
                raise NovaSonicValidationError(f"toolResult references inactive contentName '{content_name}'")
            if self.active_contents[content_name]["type"] != "TOOL":
                raise NovaSonicValidationError(
                    f"toolResult cannot be sent in content block '{content_name}' of type '{self.active_contents[content_name]['type']}'"
                )

        if "content" not in payload:
            raise NovaSonicValidationError("toolResult requires a 'content' field.")

    def _validate_content_end(self, payload: Dict[str, Any]) -> None:
        content_name = payload.get("contentName")
        if self.strict_sequencing and content_name:
            if content_name not in self.active_contents:
                raise NovaSonicValidationError(f"contentEnd references inactive contentName '{content_name}'")

        if content_name:
            self.active_contents.pop(content_name, None)

    def _validate_prompt_end(self, payload: Dict[str, Any]) -> None:
        if self.strict_sequencing and self.state != NovaSonicProtocolState.PROMPT_STARTED:
            raise NovaSonicValidationError(f"promptEnd is only valid in PROMPT_STARTED state, currently in {self.state.value}")

        prompt_name = payload.get("promptName")
        if self.strict_sequencing and self.current_prompt_name and prompt_name != self.current_prompt_name:
            raise NovaSonicValidationError(
                f"promptEnd promptName '{prompt_name}' does not match active prompt '{self.current_prompt_name}'"
            )

        self.current_prompt_name = None
        self.active_contents.clear()
        self.state = NovaSonicProtocolState.SESSION_STARTED

    def _validate_session_end(self, payload: Dict[str, Any]) -> None:
        self.reset()
        self.state = NovaSonicProtocolState.SESSION_ENDED


def validate_bedrock_event(event_dict: Dict[str, Any], validator: Optional[NovaSonicEventValidator] = None) -> None:
    """Convenience helper to validate an event using an optional or default non-strict validator."""
    v = validator or NovaSonicEventValidator(strict_sequencing=False)
    v.validate_event(event_dict)
