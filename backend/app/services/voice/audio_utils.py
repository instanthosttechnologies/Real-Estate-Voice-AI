import base64
import logging
import struct
from typing import Optional, Tuple

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


def resample_pcm_s16le(audio_bytes: bytes, in_rate: int, out_rate: int) -> bytes:
    """
    Resamples mono signed 16-bit linear PCM audio from in_rate to out_rate.
    Uses audioop.ratecv when available, with a linear interpolation fallback.
    """
    if not audio_bytes or in_rate == out_rate:
        return audio_bytes

    if in_rate <= 0 or out_rate <= 0:
        raise ValueError(f"Invalid sample rates: in_rate={in_rate}, out_rate={out_rate}")

    # 1. Prefer audioop for C-speed conversion
    if _HAS_AUDIOOP:
        try:
            converted, _ = audioop.ratecv(audio_bytes, 2, 1, in_rate, out_rate, None)
            return converted
        except Exception as exc:
            logger.warning(f"audioop.ratecv failed ({exc}), falling back to linear interpolation")

    # 2. Pure Python linear interpolation fallback
    num_in_samples = len(audio_bytes) // 2
    if num_in_samples == 0:
        return b""

    # Unpack signed 16-bit little-endian samples
    in_samples = struct.unpack(f"<{num_in_samples}h", audio_bytes)
    ratio = float(out_rate) / float(in_rate)
    num_out_samples = int(num_in_samples * ratio)

    out_samples = []
    for i in range(num_out_samples):
        src_pos = i / ratio
        idx = int(src_pos)
        frac = src_pos - idx
        if idx >= num_in_samples - 1:
            val = in_samples[-1]
        else:
            val = in_samples[idx] * (1.0 - frac) + in_samples[idx + 1] * frac
        clamped_val = max(-32768, min(32767, int(round(val))))
        out_samples.append(clamped_val)

    return struct.pack(f"<{len(out_samples)}h", *out_samples)


def pcm_s16le_to_base64(audio_bytes: bytes) -> str:
    """Encodes raw PCM bytes to base64 string."""
    return base64.b64encode(audio_bytes).decode("utf-8")


def base64_to_pcm_s16le(b64_str: str) -> bytes:
    """Decodes base64 string back to raw PCM bytes."""
    return base64.b64decode(b64_str)
