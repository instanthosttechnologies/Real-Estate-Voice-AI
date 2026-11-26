import math
import struct
import pytest
from app.services.voice.audio_utils import resample_pcm_s16le, calculate_pcm_duration_ms, validate_pcm_s16le


def test_audio_resampling_backward_compatible():
    """Verify resample_pcm_s16le returns bytes by default when return_state is False."""
    sample_rate_in = 24000
    sample_rate_out = 16000
    # 2400 samples (100ms) of 440Hz sine wave
    samples = [int(15000 * math.sin(2 * math.pi * 440 * i / sample_rate_in)) for i in range(2400)]
    raw = struct.pack(f"<{len(samples)}h", *samples)

    result = resample_pcm_s16le(raw, sample_rate_in, sample_rate_out)
    assert isinstance(result, bytes)
    assert len(result) == 1600 * 2  # Exactly 1600 samples of 16-bit PCM (100ms at 16kHz)


def test_audio_resampling_streaming_continuity():
    """
    Verify that chunked streaming audio resampling with state preservation
    is 100% bit-exact to continuous single-buffer resampling without filter
    discontinuities, clicks, pops, or sample drift.
    """
    sr_in = 24000
    sr_out = 16000
    duration_s = 2.0
    total_samples = int(sr_in * duration_s)

    # 2 seconds of 350Hz tone
    samples = [int(18000 * math.sin(2 * math.pi * 350 * i / sr_in)) for i in range(total_samples)]
    raw = struct.pack(f"<{len(samples)}h", *samples)

    # Reference full resample
    ref_resampled = resample_pcm_s16le(raw, sr_in, sr_out)

    # Streamed chunk-by-chunk resample (4096 samples / 8192 bytes per chunk, matching voice client)
    chunk_bytes = 4096 * 2
    streamed_chunks = []
    state = None

    for i in range(0, len(raw), chunk_bytes):
        chunk = raw[i:i + chunk_bytes]
        resampled_chunk, state = resample_pcm_s16le(
            chunk, sr_in, sr_out, state=state, return_state=True
        )
        streamed_chunks.append(resampled_chunk)

    streamed_all = b"".join(streamed_chunks)

    # Both lengths must be exact
    assert len(streamed_all) == len(ref_resampled)

    # Compare sample-by-sample difference
    num_out = len(streamed_all) // 2
    out_samples_streamed = struct.unpack(f"<{num_out}h", streamed_all)
    out_samples_ref = struct.unpack(f"<{num_out}h", ref_resampled)

    max_diff = max(abs(s - r) for s, r in zip(out_samples_streamed, out_samples_ref))
    assert max_diff == 0, f"Streaming resampling deviated from continuous reference: max diff {max_diff}"


def test_audio_resampling_edge_cases():
    """Verify edge cases: empty audio, same in/out rate, invalid rates."""
    # Empty
    assert resample_pcm_s16le(b"", 24000, 16000) == b""
    res, state = resample_pcm_s16le(b"", 24000, 16000, return_state=True)
    assert res == b""

    # Same rate
    test_bytes = b"\x01\x00\x02\x00"
    assert resample_pcm_s16le(test_bytes, 16000, 16000) == test_bytes

    # Invalid rates
    with pytest.raises(ValueError):
        resample_pcm_s16le(test_bytes, 0, 16000)
    with pytest.raises(ValueError):
        resample_pcm_s16le(test_bytes, 24000, -1)


def test_resampling_state_persistence_and_clean_session_reset():
    """
    Verify:
    1. Resampling state persists across consecutive chunks within session 1.
    2. Session 2 starts fresh with state=None, ensuring zero cross-session state bleeding.
    """
    sr_in, sr_out = 24000, 16000
    chunk1 = b"\x10\x00\x20\x00" * 500  # 1000 samples
    chunk2 = b"\x30\x00\x40\x00" * 500

    # Session 1: sequential chunks with state persistence
    session1_state = None
    out1_a, session1_state = resample_pcm_s16le(chunk1, sr_in, sr_out, state=session1_state, return_state=True)
    assert session1_state is not None, "State must be generated after first chunk"

    out1_b, session1_state = resample_pcm_s16le(chunk2, sr_in, sr_out, state=session1_state, return_state=True)
    assert len(out1_a) > 0 and len(out1_b) > 0

    # Session 2: new session starts fresh (state reset to None)
    session2_state = None
    out2_fresh, session2_state = resample_pcm_s16le(chunk1, sr_in, sr_out, state=session2_state, return_state=True)

    # Identical input from clean state produces identical output
    assert out2_fresh == out1_a

