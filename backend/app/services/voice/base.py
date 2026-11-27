import abc
import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Dict, List, Optional


class VoiceEventType(str, enum.Enum):
    SESSION_STARTED = "session_started"
    AUDIO_OUTPUT = "audio_output"
    TRANSCRIPT_DELTA = "transcript_delta"
    TOOL_USE_REQUEST = "tool_use_request"
    TOOL_USE_RESULT = "tool_use_result"
    INTERRUPTED = "interrupted"
    SESSION_WARNING = "session_warning"
    SESSION_COMPLETED = "session_completed"
    SESSION_ENDED = "session_ended"
    ERROR = "error"


class AudioFormat(str, enum.Enum):
    PCM_16KHZ_16BIT_MONO = "pcm_16000_16bit_mono"
    PCM_24KHZ_16BIT_MONO = "pcm_24000_16bit_mono"


@dataclass
class AudioOutputPayload:
    audio_bytes: bytes
    sample_rate: int = 24000
    channels: int = 1
    format: str = "pcm_s16le"


@dataclass
class TranscriptDeltaPayload:
    role: str  # "user" | "assistant" | "system"
    delta: str
    is_final: bool = False


@dataclass
class ToolUseRequestPayload:
    tool_name: str
    tool_use_id: str
    arguments: Dict[str, Any]


@dataclass
class VoiceServerEvent:
    event_type: VoiceEventType
    session_id: str
    data: Dict[str, Any] = field(default_factory=dict)
    audio_payload: Optional[AudioOutputPayload] = None
    transcript_payload: Optional[TranscriptDeltaPayload] = None
    tool_request_payload: Optional[ToolUseRequestPayload] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class VoiceDriver(abc.ABC):
    """
    Abstract interface for streaming voice drivers (Mock driver or Amazon Nova 2.5 Sonic driver).
    Enforces a standardized contract for bidirectional audio, transcription, and validated tool-calling.
    """

    @property
    @abc.abstractmethod
    def provider_name(self) -> str:
        """Returns the driver provider identifier (e.g. 'mock', 'amazon_nova_sonic')."""
        pass

    @property
    @abc.abstractmethod
    def model_id(self) -> str:
        """Returns the underlying voice AI model ID."""
        pass

    @abc.abstractmethod
    async def start_session(
        self,
        session_id: str,
        prompt_preamble: str,
        tools: List[Dict[str, Any]],
        audio_format: AudioFormat = AudioFormat.PCM_24KHZ_16BIT_MONO,
        max_duration: Optional[int] = None,
        preamble_callback: Optional[Callable[[], str]] = None,
        customer_name: Optional[str] = None,
        voice_id: Optional[str] = None,
        language: Optional[str] = None,
    ) -> None:
        """Initializes a bidirectional streaming session with the voice model."""
        pass

    @abc.abstractmethod
    async def send_audio_chunk(self, session_id: str, audio_bytes: bytes) -> None:
        """Streams an incoming user audio frame into the session."""
        pass

    @abc.abstractmethod
    async def send_text_input(self, session_id: str, text: str) -> None:
        """Sends textual user input into the session."""
        pass

    @abc.abstractmethod
    async def send_tool_result(
        self,
        session_id: str,
        tool_use_id: str,
        result: Dict[str, Any],
        is_error: bool = False,
    ) -> None:
        """Returns the result of an executed agent tool back to the voice model."""
        pass

    @abc.abstractmethod
    async def interrupt(self, session_id: str) -> None:
        """Signals user interruption to abort pending model speech and audio generation."""
        pass

    @abc.abstractmethod
    async def end_session(self, session_id: str) -> None:
        """Terminates the voice session and releases associated resources."""
        pass

    async def renew_stream(
        self,
        session_id: str,
        updated_preamble: Optional[str] = None,
    ) -> bool:
        """
        Renews the underlying upstream stream connection while maintaining
        the active logical session, session queue, and client conversation.
        """
        return True

    @abc.abstractmethod
    async def receive_events(self, session_id: str) -> AsyncIterator[VoiceServerEvent]:
        """Asynchronously streams model output events (audio, transcript deltas, tool requests)."""
        pass
