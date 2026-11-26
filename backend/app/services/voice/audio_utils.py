import base64
import logging
import struct
from typing import Any, Optional, Tuple

logger = logging.getLogger("audio_utils")

# Try importing audioop (available in Python <= 3.12)
try:
    import audioop
    _HAS_AUDIOOP = True
except ImportError:
    _HAS_AUDIOOP = False


def validate_pcm_s16le(audio_bytes: bytes) -> bool:
    """
    Validates that the provided byte buffer represents valid signed 16-bit
    little-endian linear PCM audio data (non-empty and even byte count).
    """
    if not isinstance(audio_bytes, (bytes, bytearray)):
        return False
    if len(audio_bytes) == 0:
        return False
    if len(audio_bytes) % 2 != 0:
        return False
    return True


def calculate_pcm_duration_ms(audio_bytes: bytes, sample_rate: int = 24000) -> float:
    """
    Calculates duration in milliseconds of a mono 16-bit PCM buffer.
    """
    if not audio_bytes or sample_rate <= 0:
        return 0.0
    num_samples = len(audio_bytes) // 2
    return (num_samples / float(sample_rate)) * 1000.0


def resample_pcm_s16le(
    audio_bytes: bytes,
    in_rate: int,
    out_rate: int,
    state: Optional[Any] = None,
    return_state: bool = False,
) -> Any:
    """
    Resamples mono signed 16-bit linear PCM audio from in_rate to out_rate.
    Preserves converter filter state across audio chunks to guarantee seamless,
    click-free, bit-continuous streaming audio without transient distortion.

    When return_state is True, returns (resampled_bytes, new_state).
    When return_state is False (default), returns resampled_bytes for backward compatibility.
    """
    if not audio_bytes or in_rate == out_rate:
        return (audio_bytes, state) if return_state else audio_bytes

    if in_rate <= 0 or out_rate <= 0:
        raise ValueError(f"Invalid sample rates: in_rate={in_rate}, out_rate={out_rate}")

    # 1. Prefer audioop for C-speed conversion with exact filter continuity
    if _HAS_AUDIOOP:
        try:
            converted, new_state = audioop.ratecv(audio_bytes, 2, 1, in_rate, out_rate, state)
            return (converted, new_state) if return_state else converted
        except Exception as exc:
            logger.warning(f"audioop.ratecv failed ({exc}), falling back to linear interpolation")

    # 2. Pure Python linear interpolation fallback with state
    num_in_samples = len(audio_bytes) // 2
    if num_in_samples == 0:
        return (b"", state) if return_state else b""

    # Unpack signed 16-bit little-endian samples
    in_samples = struct.unpack(f"<{num_in_samples}h", audio_bytes)
    ratio = float(out_rate) / float(in_rate)

    # State holds (last_sample, phase_offset)
    last_sample, phase_offset = state if isinstance(state, tuple) and len(state) == 2 else (in_samples[0], 0.0)

    out_samples = []
    src_pos = phase_offset
    step = 1.0 / ratio
    while src_pos < num_in_samples:
        idx = int(src_pos)
        frac = src_pos - idx
        if idx == 0 and frac < 0.0001:
            val = float(in_samples[0])
        elif idx < num_in_samples - 1:
            val = in_samples[idx] * (1.0 - frac) + in_samples[idx + 1] * frac
        else:
            val = float(in_samples[-1])
        clamped_val = max(-32768, min(32767, int(round(val))))
        out_samples.append(clamped_val)
        src_pos += step

    new_phase = src_pos - num_in_samples
    new_state = (in_samples[-1], new_phase)
    converted_bytes = struct.pack(f"<{len(out_samples)}h", *out_samples)
    return (converted_bytes, new_state) if return_state else converted_bytes


def pcm_s16le_to_base64(audio_bytes: bytes) -> str:
    """Encodes raw PCM bytes to base64 string."""
    return base64.b64encode(audio_bytes).decode("utf-8")


def base64_to_pcm_s16le(b64_str: str) -> bytes:
    """Decodes base64 string back to raw PCM bytes."""
    return base64.b64decode(b64_str)
