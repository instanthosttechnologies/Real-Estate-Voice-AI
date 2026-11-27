import asyncio
import json
import logging
import math
import struct
import uuid
from typing import Any, AsyncIterator, Callable, Dict, List, Optional
from app.services.voice.base import (
    AudioFormat,
    AudioOutputPayload,
    ToolUseRequestPayload,
    TranscriptDeltaPayload,
    VoiceDriver,
    VoiceEventType,
    VoiceServerEvent,
)

logger = logging.getLogger("mock_voice_driver")


class MockVoiceDriver(VoiceDriver):
    """
    Mock Voice Driver providing zero-cost, deterministic local testing of real-time voice sessions.
    Simulates speech-to-text, text-to-speech PCM audio generation, LLM reasoning,
    tool invocation requests, and interruption handling without any AWS credentials or cloud calls.
    """

    def __init__(
        self,
        model_id: str = "amazon.nova-2-5-sonic",
        enable_synthetic_tones: bool = True,
    ):
        self._model_id = model_id
        self.enable_synthetic_tones = enable_synthetic_tones
        self._session_queues: Dict[str, asyncio.Queue] = {}
        self._interrupted_sessions: Dict[str, bool] = {}
        self._session_tools: Dict[str, List[Dict[str, Any]]] = {}
        self._session_preambles: Dict[str, str] = {}
        self._session_speech_frames: Dict[str, int] = {}
        self._session_silence_frames: Dict[str, int] = {}
        self._session_turn_count: Dict[str, int] = {}
        self._session_audio_frame_count: Dict[str, int] = {}
        self._session_renewals: Dict[str, int] = {}
        self._session_preamble_callbacks: Dict[str, Optional[Callable[[], str]]] = {}
        self._session_languages: Dict[str, str] = {}
        self._session_voices: Dict[str, str] = {}
        self._last_searched_properties: Dict[str, List[Dict[str, Any]]] = {}

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_id(self) -> str:
        return self._model_id

    def _generate_synthetic_pcm_audio(
        self,
        duration_ms: int = 500,
        sample_rate: int = 24000,
        freq: float = 440.0,
    ) -> bytes:
        """Generates an audible, pleasant 16-bit mono PCM acoustic waveform representing synthesized speech."""
        num_samples = int(sample_rate * (duration_ms / 1000.0))
        samples = bytearray()
        fade_samples = max(1, int(sample_rate * 0.05))
        for i in range(num_samples):
            t = i / sample_rate
            fade_in = min(1.0, i / fade_samples)
            fade_out = min(1.0, (num_samples - i) / fade_samples)
            envelope = min(fade_in, fade_out)
            # Harmonic blend simulating pleasant synthesized voice phoneme
            wave = (
                0.60 * math.sin(2.0 * math.pi * freq * t)
                + 0.25 * math.sin(2.0 * math.pi * (freq * 1.5) * t)
                + 0.15 * math.sin(2.0 * math.pi * (freq * 2.0) * t)
            )
            sample_val = int(wave * envelope * 12000.0)
            sample_val = max(-32768, min(32767, sample_val))
            samples.extend(struct.pack("<h", sample_val))
        return bytes(samples)

    def _calculate_audio_energy(self, audio_bytes: bytes) -> float:
        """Calculates RMS amplitude of 16-bit linear PCM audio chunk without logging raw audio."""
        if len(audio_bytes) < 2:
            return 0.0
        num_samples = len(audio_bytes) // 2
        sum_squares = 0
        stride = 4
        sampled_count = 0
        for i in range(0, len(audio_bytes) - 1, 2 * stride):
            sample = struct.unpack_from("<h", audio_bytes, i)[0]
            sum_squares += sample * sample
            sampled_count += 1
        if sampled_count == 0:
            return 0.0
        return math.sqrt(sum_squares / sampled_count)

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
        queue: asyncio.Queue = asyncio.Queue()
        self._session_queues[session_id] = queue
        self._interrupted_sessions[session_id] = False
        self._session_tools[session_id] = tools
        self._session_preambles[session_id] = prompt_preamble
        self._session_speech_frames[session_id] = 0
        self._session_silence_frames[session_id] = 0
        self._session_turn_count[session_id] = 0
        self._session_audio_frame_count[session_id] = 0
        self._session_preamble_callbacks[session_id] = preamble_callback
        lang = language or "en-US"
        self._session_languages[session_id] = lang
        chosen_voice = voice_id or ("kiara" if lang.lower().startswith("hi") else "matthew")
        self._session_voices[session_id] = chosen_voice

        # 1. Emit SESSION_STARTED
        await queue.put(
            VoiceServerEvent(
                event_type=VoiceEventType.SESSION_STARTED,
                session_id=session_id,
                data={
                    "model_id": self._model_id,
                    "provider": "mock",
                    "driver_mode": "MOCK",
                    "audio_format": audio_format.value,
                    "sample_rate": 24000 if audio_format == AudioFormat.PCM_24KHZ_16BIT_MONO else 16000,
                    "speech_enabled": self.enable_synthetic_tones,
                    "customer_name": customer_name,
                    "language": lang,
                    "voice_id": chosen_voice,
                },
            )
        )

        # 2. Emit initial conversational greeting from voice assistant
        display_name = customer_name.strip() if customer_name else None
        is_hindi = lang.lower().startswith("hi")
        is_male = chosen_voice.lower() in ("arjun", "matthew")

        if is_hindi:
            if is_male:
                greeting = f"नमस्ते {display_name} जी! मैं आपका प्रॉपर्टी असिस्टेंट हूँ। मैं आपकी कैसे मदद कर सकता हूँ?" if display_name else "नमस्ते! मैं आपका प्रॉपर्टी असिस्टेंट हूँ। मैं आपकी कैसे मदद कर सकता हूँ?"
            else:
                greeting = f"नमस्ते {display_name} जी! मैं आपकी प्रॉपर्टी असिस्टेंट हूँ। मैं आपकी कैसे मदद कर सकती हूँ?" if display_name else "नमस्ते! मैं आपकी प्रॉपर्टी असिस्टेंट हूँ। मैं आपकी कैसे मदद कर सकती हूँ?"
        else:
            if display_name:
                greeting = f"Hello {display_name}! I'm your property assistant. How can I help you?"
            else:
                greeting = "Hello, I'm your property assistant. How can I help you?"

        await queue.put(
            VoiceServerEvent(
                event_type=VoiceEventType.TRANSCRIPT_DELTA,
                session_id=session_id,
                transcript_payload=TranscriptDeltaPayload(
                    role="assistant",
                    delta=greeting,
                    is_final=True,
                ),
            )
        )
        if self.enable_synthetic_tones:
            # Emit greeting synthetic audible audio for playback and robot lip-sync
            greeting_audio = self._generate_synthetic_pcm_audio(duration_ms=1800, freq=440.0)
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.AUDIO_OUTPUT,
                    session_id=session_id,
                    audio_payload=AudioOutputPayload(
                        audio_bytes=greeting_audio,
                        sample_rate=24000,
                    ),
                )
            )

    async def send_audio_chunk(self, session_id: str, audio_bytes: bytes) -> None:
        """Processes incoming raw user microphone PCM audio and simulates voice conversation."""
        if session_id not in self._session_queues:
            logger.warning(f"[MockVoiceDriver] Audio chunk received for unknown session: {session_id[:8]}...")
            return

        queue = self._session_queues[session_id]
        if self._interrupted_sessions.get(session_id, False):
            self._interrupted_sessions[session_id] = False

        self._session_audio_frame_count[session_id] = (
            self._session_audio_frame_count.get(session_id, 0) + 1
        )
        total_frames = self._session_audio_frame_count[session_id]

        # Calculate RMS energy of 16-bit linear PCM chunk
        energy = self._calculate_audio_energy(audio_bytes)

        # Voice Activity Detection (VAD) threshold based strictly on acoustic vocal energy
        # (Fix: never treat empty silent mic buffers as speech simply because buffer length >= 4096)
        is_speech = energy > 1200.0

        if is_speech:
            self._session_speech_frames[session_id] = (
                self._session_speech_frames.get(session_id, 0) + 1
            )
            self._session_silence_frames[session_id] = 0
        else:
            if self._session_speech_frames.get(session_id, 0) > 0:
                self._session_silence_frames[session_id] = (
                    self._session_silence_frames.get(session_id, 0) + 1
                )

        speech_count = self._session_speech_frames.get(session_id, 0)
        silence_count = self._session_silence_frames.get(session_id, 0)

        # End of utterance detection:
        # User spoke at least 3 chunks (~500ms) and paused for 2 chunks (~300ms)
        # OR accumulated 6 speech chunks (~1 second of speaking)
        if (speech_count >= 3 and silence_count >= 2) or speech_count >= 6:
            self._session_speech_frames[session_id] = 0
            self._session_silence_frames[session_id] = 0
            self._session_turn_count[session_id] = (
                self._session_turn_count.get(session_id, 0) + 1
            )
            turn = self._session_turn_count[session_id]

            logger.info(
                f"[MockVoiceDriver] Session {session_id[:8]}... detected speech turn #{turn} "
                f"(total audio frames received: {total_frames})"
            )

            await self._simulate_speech_turn(session_id, turn, queue)

    async def _simulate_speech_turn(self, session_id: str, turn: int, queue: asyncio.Queue) -> None:
        """Simulates conversational turn from user speech with realistic multi-turn progression."""
        if turn == 1:
            # Turn 1: Initial user greeting / acoustic check: "Hey, hello, can you hear me?"
            user_text = "Hey, hello, can you hear me?"
            assistant_reply = (
                "Hello! Yes, I hear you loud and clear. I am your real estate AI advisor. "
                "I can search genuine property inventory, check live prices, and book site visits. "
                "What type of property or location are you looking for?"
            )
            # 1. User utterance
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.TRANSCRIPT_DELTA,
                    session_id=session_id,
                    transcript_payload=TranscriptDeltaPayload(role="user", delta=user_text, is_final=True),
                )
            )
            # Brief pause for thinking state
            await asyncio.sleep(0.05)
            # 2. Assistant response transcript
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.TRANSCRIPT_DELTA,
                    session_id=session_id,
                    transcript_payload=TranscriptDeltaPayload(role="assistant", delta=assistant_reply, is_final=True),
                )
            )
            # 3. Audible synthetic PCM audio response only if explicitly enabled
            if self.enable_synthetic_tones:
                await queue.put(
                    VoiceServerEvent(
                        event_type=VoiceEventType.AUDIO_OUTPUT,
                        session_id=session_id,
                        audio_payload=AudioOutputPayload(
                            audio_bytes=self._generate_synthetic_pcm_audio(duration_ms=1000, freq=440.0),
                            sample_rate=24000,
                        ),
                    )
                )

        elif turn == 2:
            # Turn 2: Property search inquiry -> triggers genuine database search tool!
            user_text = "I am looking for a 2BHK flat in Mumbai within 1.5 crore."
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.TRANSCRIPT_DELTA,
                    session_id=session_id,
                    transcript_payload=TranscriptDeltaPayload(role="user", delta=user_text, is_final=True),
                )
            )
            await asyncio.sleep(0.05)
            # Trigger real search_properties tool on DB
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.TOOL_USE_REQUEST,
                    session_id=session_id,
                    tool_request_payload=ToolUseRequestPayload(
                        tool_name="search_properties",
                        tool_use_id=f"mock_call_{uuid.uuid4().hex[:8]}",
                        arguments={
                            "city": "Mumbai",
                            "configuration_type": "2BHK",
                            "currency": "INR",
                            "limit": 5,
                        },
                    ),
                )
            )

        elif turn == 3:
            # Turn 3: Site visit request
            user_text = "Can I schedule a site visit for this weekend?"
            assistant_reply = (
                "I would be delighted to arrange a site visit! Our model residences and sales galleries are open this Saturday and Sunday from 9 AM to 6 PM. "
                "Would you prefer a morning or afternoon appointment?"
            )
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.TRANSCRIPT_DELTA,
                    session_id=session_id,
                    transcript_payload=TranscriptDeltaPayload(role="user", delta=user_text, is_final=True),
                )
            )
            await asyncio.sleep(0.05)
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.TRANSCRIPT_DELTA,
                    session_id=session_id,
                    transcript_payload=TranscriptDeltaPayload(role="assistant", delta=assistant_reply, is_final=True),
                )
            )
            if self.enable_synthetic_tones:
                await queue.put(
                    VoiceServerEvent(
                        event_type=VoiceEventType.AUDIO_OUTPUT,
                        session_id=session_id,
                        audio_payload=AudioOutputPayload(
                            audio_bytes=self._generate_synthetic_pcm_audio(duration_ms=1200, freq=493.88),
                            sample_rate=24000,
                        ),
                    )
                )

        else:
            # Turn 4+: General assistance
            user_text = "Thank you, that was very helpful."
            assistant_reply = (
                "You are very welcome! Feel free to ask about floor plans, payment schedules, or nearby amenities whenever you are ready."
            )
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.TRANSCRIPT_DELTA,
                    session_id=session_id,
                    transcript_payload=TranscriptDeltaPayload(role="user", delta=user_text, is_final=True),
                )
            )
            await asyncio.sleep(0.05)
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.TRANSCRIPT_DELTA,
                    session_id=session_id,
                    transcript_payload=TranscriptDeltaPayload(role="assistant", delta=assistant_reply, is_final=True),
                )
            )
            if self.enable_synthetic_tones:
                await queue.put(
                    VoiceServerEvent(
                        event_type=VoiceEventType.AUDIO_OUTPUT,
                        session_id=session_id,
                        audio_payload=AudioOutputPayload(
                            audio_bytes=self._generate_synthetic_pcm_audio(duration_ms=800, freq=523.25),
                            sample_rate=24000,
                        ),
                    )
                )

    async def send_text_input(self, session_id: str, text: str) -> None:
        """Processes conversational customer utterances and generates simulated model turns / tool calls."""
        if session_id not in self._session_queues:
            raise ValueError(f"Session {session_id} not initialized.")

        queue = self._session_queues[session_id]
        clean_text = text.strip()

        # 1. Echo user transcript
        await queue.put(
            VoiceServerEvent(
                event_type=VoiceEventType.TRANSCRIPT_DELTA,
                session_id=session_id,
                transcript_payload=TranscriptDeltaPayload(
                    role="user",
                    delta=clean_text,
                    is_final=True,
                ),
            )
        )

        # 2. Check for deterministic test tool triggers: "TEST_TOOL:<tool_name>:<json_args>"
        if clean_text.startswith("TEST_TOOL:"):
            parts = clean_text.split(":", 2)
            tool_name = parts[1]
            args = json.loads(parts[2]) if len(parts) > 2 else {}
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.TOOL_USE_REQUEST,
                    session_id=session_id,
                    tool_request_payload=ToolUseRequestPayload(
                        tool_name=tool_name,
                        tool_use_id=f"mock_call_{uuid.uuid4().hex[:8]}",
                        arguments=args,
                    ),
                )
            )
            return

        # 3. Conversational intent detection for natural simulation
        t = clean_text.lower()
        is_hindi = self._session_languages.get(session_id, "en-US").lower().startswith("hi") or any(
            "\u0900" <= c <= "\u097f" for c in clean_text
        )

        # A. Show Property Images intent
        if any(w in t for w in ["picture", "pictures", "photo", "photos", "image", "images", "gallery", "तस्वीरें", "तस्वीर", "फोटो", "फोटोज", "इमेज"]):
            last_props = self._last_searched_properties.get(session_id, [])
            proj_ident = last_props[0].get("property_name", "Godrej Aristocrat") if last_props else "Godrej Aristocrat"
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.TOOL_USE_REQUEST,
                    session_id=session_id,
                    tool_request_payload=ToolUseRequestPayload(
                        tool_name="show_property_images",
                        tool_use_id=f"mock_call_{uuid.uuid4().hex[:8]}",
                        arguments={"property_identifier": proj_ident},
                    ),
                )
            )
            return

        # B. Site Visit booking intent
        if any(w in t for w in ["visit", "tour", "appointment", "book", "विजिट", "देखने आना", "घूमने आना", "रविवार", "सोमवार", "मंगलवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "कल", "परसों"]):
            last_props = self._last_searched_properties.get(session_id, [])
            proj_ident = last_props[0].get("property_name", "Godrej Aristocrat") if last_props else "Godrej Aristocrat"
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.TOOL_USE_REQUEST,
                    session_id=session_id,
                    tool_request_payload=ToolUseRequestPayload(
                        tool_name="book_site_visit",
                        tool_use_id=f"mock_call_{uuid.uuid4().hex[:8]}",
                        arguments={
                            "project_name": proj_ident,
                            "visit_date": "day after tomorrow",
                            "time_slot": "02:00 PM - 03:00 PM",
                        },
                    ),
                )
            )
            return

        # C. Property Search intent
        if any(w in t for w in ["search", "apartment", "flat", "bhk", "villa", "looking for", "property in", "budget", "प्रॉपर्टी", "फ्लैट", "अपार्टमेंट", "बीएचके", "चाहिए", "देखना", "बजट"]):
            # Trigger search_properties
            city = None
            city_map = {
                "chennai": "Chennai", "चेन्नई": "Chennai", "चेन्नै": "Chennai",
                "mumbai": "Mumbai", "मुंबई": "Mumbai",
                "bengaluru": "Bengaluru", "bangalore": "Bengaluru", "बेंगलुरु": "Bengaluru", "बैंगलोर": "Bengaluru",
                "pune": "Pune", "पुणे": "Pune",
                "delhi": "Delhi", "दिल्ली": "Delhi",
                "gurgaon": "Gurugram", "gurugram": "Gurugram", "गुड़गांव": "Gurugram", "गुरुग्राम": "Gurugram",
                "hyderabad": "Hyderabad", "हैदराबाद": "Hyderabad",
                "kolkata": "Kolkata", "कोलकाता": "Kolkata",
                "seattle": "Seattle", "austin": "Austin", "denver": "Denver",
            }
            for c_kw, c_val in city_map.items():
                if c_kw in t:
                    city = c_val
                    break

            config = None
            if any(w in t for w in ["2bhk", "2 bhk", "2 बीएचके", "दो बीएचके"]):
                config = "2BHK"
            elif any(w in t for w in ["3bhk", "3 bhk", "3 बीएचके", "तीन बीएचके"]):
                config = "3BHK"
            elif any(w in t for w in ["1bhk", "1 bhk", "1 बीएचके", "एक बीएचके"]):
                config = "1BHK"
            elif any(w in t for w in ["4bhk", "4 bhk", "4 बीएचके", "चार बीएचके"]):
                config = "4BHK"

            currency = "USD" if any(w in t for w in ["dollar", "usd", "$"]) else "INR"

            args_dict: Dict[str, Any] = {"limit": 5, "currency": currency}
            if city:
                args_dict["city"] = city
            if config:
                args_dict["configuration_type"] = config

            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.TOOL_USE_REQUEST,
                    session_id=session_id,
                    tool_request_payload=ToolUseRequestPayload(
                        tool_name="search_properties",
                        tool_use_id=f"mock_call_{uuid.uuid4().hex[:8]}",
                        arguments=args_dict,
                    ),
                )
            )
        elif "price" in t or "cost" in t or "कीमत" in t or "दाम" in t:
            reply_delta = "मैं नवीनतम मूल्य निर्धारण विवरण प्राप्त कर सकती हूँ। क्या आप यूनिट आईडी या प्रोजेक्ट का नाम बता सकते हैं?" if is_hindi else "I can certainly retrieve the latest active pricing breakdown. Could you provide the unit ID or property name?"
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.TRANSCRIPT_DELTA,
                    session_id=session_id,
                    transcript_payload=TranscriptDeltaPayload(
                        role="assistant",
                        delta=reply_delta,
                        is_final=True,
                    ),
                )
            )
        elif any(w in t for w in ["human", "agent", "broker", "transfer", "representative", "एजेंट", "सलाहकार"]):
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.TOOL_USE_REQUEST,
                    session_id=session_id,
                    tool_request_payload=ToolUseRequestPayload(
                        tool_name="transfer_to_human",
                        tool_use_id=f"mock_call_{uuid.uuid4().hex[:8]}",
                        arguments={
                            "reason": "Customer requested human advisor assistance",
                            "department": "sales",
                        },
                    ),
                )
            )
        else:
            # Default conversational response
            if is_hindi:
                reply = (
                    f"मैं आपकी आवश्यकता समझ गई: '{clean_text}'। "
                    "क्या आप चाहेंगे कि मैं हमारे डेटाबेस में उपलब्ध प्रॉपर्टी खोजूँ या कीमतें बताऊँ?"
                )
            else:
                reply = (
                    f"I understand your requirement: '{clean_text}'. "
                    "Would you like me to search available units in our database or check pricing?"
                )
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.TRANSCRIPT_DELTA,
                    session_id=session_id,
                    transcript_payload=TranscriptDeltaPayload(
                        role="assistant",
                        delta=reply,
                        is_final=True,
                    ),
                )
            )
            if self.enable_synthetic_tones:
                await queue.put(
                    VoiceServerEvent(
                        event_type=VoiceEventType.AUDIO_OUTPUT,
                        session_id=session_id,
                        audio_payload=AudioOutputPayload(
                            audio_bytes=self._generate_synthetic_pcm_audio(duration_ms=150),
                        ),
                    )
                )

    async def send_tool_result(
        self,
        session_id: str,
        tool_use_id: str,
        result: Dict[str, Any],
        is_error: bool = False,
    ) -> None:
        """Synthesizes grounded conversational response from verified tool execution output."""
        if session_id not in self._session_queues:
            return

        queue = self._session_queues[session_id]
        is_hindi = self._session_languages.get(session_id, "en-US").lower().startswith("hi")

        if is_error:
            reply = f"क्षमा करें, समस्या आई: {result.get('error_message', 'Tool execution failed')}." if is_hindi else f"I apologize, but I encountered an issue: {result.get('error_message', 'Tool execution failed')}."
        else:
            data = result.get("data", {})
            tool_name = result.get("tool_name", "")

            if tool_name == "search_properties":
                props = data if isinstance(data, list) else data.get("properties", [])
                if props:
                    self._last_searched_properties[session_id] = props
                    p = props[0]
                    try:
                        price_num = float(p.get("base_price", 0))
                        price_str = f"{price_num:,.0f}"
                    except Exception:
                        price_str = str(p.get("base_price", ""))

                    if is_hindi:
                        reply = (
                            f"मैंने हमारे सत्यापित डेटाबेस में {len(props)} प्रॉपर्टी खोजी हैं। "
                            f"जैसे कि {p.get('property_name', 'प्रोजेक्ट')} में {p.get('configuration_type', '')} लेआउट "
                            f"उपलब्ध है। क्या आप इसके बारे में और जानना चाहेंगे?"
                        )
                    else:
                        reply = (
                            f"I found {len(props)} verified properties in our database. "
                            f"For example, {p.get('property_name', 'Tower')} Unit {p.get('unit_number', '')} "
                            f"offers a {p.get('configuration_type', '')} layout at {p.get('currency', '$')} "
                            f"{price_str}. All details come directly from our verified inventory."
                        )
                else:
                    reply = "मैंने सत्यापित रिकॉर्ड देखे, लेकिन इस विवरण से मेल खाती कोई प्रॉपर्टी नहीं मिली। क्या आप बजट या लोकेशन बदलना चाहेंगे?" if is_hindi else "I checked our live records, but no properties currently match those exact specifications. Would you like to adjust your budget or location?"
            elif tool_name == "show_property_images":
                reply = "ज़रूर, मैं आपको इसकी तस्वीरें दिखाती हूँ।" if is_hindi else "Certainly! Here are representative pictures of the property on your screen."
            elif tool_name == "book_site_visit":
                if is_hindi:
                    reply = (
                        f"आपकी साइट विजिट {data.get('project_name', 'प्रोजेक्ट')} के लिए "
                        f"{data.get('scheduled_start', '')} पर सफलतापूर्वक बुक हो गई है। "
                        f"हमारे प्रतिनिधि {data.get('assigned_agent_name', '')} आपका स्वागत करेंगे।"
                    )
                else:
                    reply = (
                        f"Your site visit appointment is successfully confirmed for "
                        f"{data.get('scheduled_start', '')} at {data.get('project_name', 'the project')}. "
                        f"Our sales advisor {data.get('assigned_agent_name', '')} will welcome you."
                    )
            elif tool_name in ["transfer_to_human", "request_human_handoff"]:
                reply = (
                    f"मैंने आपकी प्राथमिकता टिकट #{data.get('handoff_ticket_id', data.get('ticket_id', 'QUEUED'))} दर्ज कर दी है। वरिष्ठ सलाहकार आपसे संपर्क करेंगे।" if is_hindi else
                    f"I have logged a priority handoff ticket #{data.get('handoff_ticket_id', data.get('ticket_id', 'QUEUED'))}. A senior property specialist will follow up with you directly."
                )
            else:
                reply = f"अनुरोध निष्पादित: {json.dumps(data)[:200]}" if is_hindi else f"I have executed the request. Details: {json.dumps(data)[:200]}"

        # Emit assistant response
        await queue.put(
            VoiceServerEvent(
                event_type=VoiceEventType.TRANSCRIPT_DELTA,
                session_id=session_id,
                transcript_payload=TranscriptDeltaPayload(
                    role="assistant",
                    delta=reply,
                    is_final=True,
                ),
            )
        )
        if self.enable_synthetic_tones:
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.AUDIO_OUTPUT,
                    session_id=session_id,
                    audio_payload=AudioOutputPayload(
                        audio_bytes=self._generate_synthetic_pcm_audio(duration_ms=250),
                    ),
                )
            )

    async def interrupt(self, session_id: str) -> None:
        """Interrupts assistant speech and drains queued audio."""
        if session_id not in self._session_queues:
            return

        self._interrupted_sessions[session_id] = True
        queue = self._session_queues[session_id]

        # Drain pending audio output events from queue
        remaining_events: List[VoiceServerEvent] = []
        while not queue.empty():
            try:
                evt = queue.get_nowait()
                if evt.event_type != VoiceEventType.AUDIO_OUTPUT:
                    remaining_events.append(evt)
            except asyncio.QueueEmpty:
                break

        for evt in remaining_events:
            await queue.put(evt)

        # Emit INTERRUPTED event
        await queue.put(
            VoiceServerEvent(
                event_type=VoiceEventType.INTERRUPTED,
                session_id=session_id,
                data={"status": "interrupted_by_user"},
            )
        )

    async def end_session(self, session_id: str) -> None:
        if session_id in self._session_queues:
            queue = self._session_queues[session_id]
            await queue.put(
                VoiceServerEvent(
                    event_type=VoiceEventType.SESSION_ENDED,
                    session_id=session_id,
                )
            )
            self._session_speech_frames.pop(session_id, None)
            self._session_silence_frames.pop(session_id, None)
            self._session_turn_count.pop(session_id, None)
            self._session_audio_frame_count.pop(session_id, None)
            self._session_renewals.pop(session_id, None)
            self._session_preamble_callbacks.pop(session_id, None)

    async def renew_stream(
        self,
        session_id: str,
        updated_preamble: Optional[str] = None,
    ) -> bool:
        """Simulates seamless stream renewal for mock sessions without disconnecting."""
        if session_id not in self._session_queues:
            return False
        if updated_preamble:
            self._session_preambles[session_id] = updated_preamble
        elif session_id in self._session_preamble_callbacks and self._session_preamble_callbacks[session_id]:
            try:
                cb = self._session_preamble_callbacks[session_id]
                self._session_preambles[session_id] = cb()
            except Exception as e:
                logger.warning(f"Error calling preamble callback in mock: {e}")
        self._session_renewals[session_id] = self._session_renewals.get(session_id, 0) + 1
        logger.info(f"[MockVoiceDriver] Simulated stream renewal #{self._session_renewals[session_id]} for session {session_id}")
        return True

    async def receive_events(self, session_id: str) -> AsyncIterator[VoiceServerEvent]:
        if session_id not in self._session_queues:
            raise ValueError(f"Session {session_id} not found.")

        queue = self._session_queues[session_id]
        while True:
            evt = await queue.get()
            yield evt
            if evt.event_type == VoiceEventType.SESSION_ENDED:
                break
