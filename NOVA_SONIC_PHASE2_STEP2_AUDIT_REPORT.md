# Real Estate Agentic Voice AI — Phase 2, Step 2: Complete Amazon Nova 2.5 Sonic Bidirectional Streaming Integration Audit & Implementation Report

**Status:** Implementation Complete & Offline Verified  
**Model Identifier:** `amazon.nova-2-5-sonic`  
**Protocol:** AWS Bedrock `InvokeModelWithBidirectionalStream`  
**Execution Environment:** Python 3.11.9 (Windows 64-bit), PostgreSQL 18.6  
**Safety Status:** Offline Mode Enforced (`USE_MOCK_VOICE=True`), Zero AWS Charges, Zero AWS Network Calls  

---

## 1. Executive Summary & Objective

In this phase, we completed the full implementation of the Amazon Nova 2.5 Sonic bidirectional streaming integration (`InvokeModelWithBidirectionalStream`) for the Real Estate Agentic Voice AI platform. The implementation replaces previously stubbed/buffered streaming routines with an authentic, production-grade AWS CRT HTTP/2 duplex streaming transport, official AWS EventStream binary wire framing (`application/vnd.amazon.eventstream`), AWS SigV4 cryptographic request signing, robust chunk defragmentation/concatenation handling, and 24 kHz audio sample rate alignment across the browser, orchestrator, and Nova Sonic model.

Strict safety constraints were maintained throughout:
- `USE_MOCK_VOICE=True` was preserved as the default setting.
- No live AWS credentials were configured or leaked.
- Zero outbound AWS Bedrock API calls or cloud charges occurred.
- Offline mock streaming fixtures were upgraded to encode and decode wire-accurate binary EventStream messages with CRC32 checksums.
- All 13 agentic real estate business tools, RBAC controls, Argon2id authentication, AES-256-GCM transcript encryption, and immutable database audit logging remain 100% operational.

---

## 2. Issues Confirmed & Root Causes

| # | Confirmed Issue | Root Cause Analysis | Status |
|---|---|---|---|
| 1 | `_CRTBedrockStreamConnection.send_event()` buffered serialized frames in memory rather than transmitting them down an active HTTP/2 stream. | The initial stub retained outgoing frames in a local list `self.sent_frames` without calling `_http2_stream.write_data()` on the AWS CRT stream handler. | **IMPLEMENTED & OFFLINE VERIFIED** |
| 2 | Absence of AWS EventStream binary wire framing (`application/vnd.amazon.eventstream`). | Raw JSON payloads were being sent instead of binary framed messages containing a 12-byte prelude, typed headers (`:message-type`, `:event-type`, `:content-type`), and CRC32 checksums required by AWS Bedrock. | **IMPLEMENTED & OFFLINE VERIFIED** |
| 3 | Fragile EventStream chunk decoding over network packets. | Network boundaries do not align with EventStream frame boundaries. Raw socket reads may produce fragmented frames (partial preludes/payloads) or concatenated frames (multiple frames in one TCP packet). | **IMPLEMENTED & OFFLINE VERIFIED** |
| 4 | Audio sample rate mismatch between frontend and backend. | The browser captures Web Audio at 24,000 Hz 16-bit linear PCM mono. The backend previously initialized Nova Sonic `audioInputConfiguration` at 16,000 Hz, causing sample-rate distortion and potential pipeline desynchronization. | **IMPLEMENTED & OFFLINE VERIFIED** |
| 5 | Lack of PCM frame validation and runtime resampling utility. | Malformed (odd-byte or empty) PCM chunks could crash or stall the voice driver; dynamic resampling between 16kHz and 24kHz was absent. | **IMPLEMENTED & OFFLINE VERIFIED** |
| 6 | AWS Bedrock stream error and timeout handling gaps. | Bedrock service-level exceptions (`modelTimeoutException`, `serviceUnavailableException`, `throttlingException`) were not mapped to the unified `VoiceEventType.ERROR` hierarchy. | **IMPLEMENTED & OFFLINE VERIFIED** |

---

## 3. Python 3.11.9 & AWS SDK Compatibility Findings

An exhaustive compatibility investigation was conducted regarding the AWS SDK ecosystem on Python 3.11.9:

1. **`aws-sdk-bedrock-runtime` Incompatibility**:
   - The standalone `aws-sdk-bedrock-runtime` package enforces a strict Python requirement: `Requires-Python >=3.12`.
   - The current development and production environment runs Python 3.11.9 (`C:\Users\shyam\AppData\Local\Programs\Python\Python311\python.exe`). Attempting to install `aws-sdk-bedrock-runtime` via pip on Python 3.11 fails resolution.
2. **Native Solution via `awscrt` & `botocore`**:
   - `awscrt` (v0.38.1 installed) is the underlying C-accelerated transport library officially developed and maintained by AWS for bidirectional streaming (HTTP/2 duplex, ALPN `h2`, TLS, EventStream framing).
   - `botocore` (installed as part of AWS tools) provides official `botocore.auth.SigV4Auth` for canonical request signing and `botocore.eventstream.EventStreamBuffer` for wire-level EventStream parsing.
   - **Conclusion**: Combining `awscrt.http.HttpClientConnection` with `botocore.auth.SigV4Auth` provides 100% native, official, high-performance bidirectional duplex streaming on Python 3.11.9 without requiring a Python upgrade.

---

## 4. Architecture & Implementation Details

### A. AWS EventStream Binary Wire Codec (`AWSEventStreamCodec`)
Implemented in `backend/app/services/voice/bedrock_streaming.py`:
- **Prelude (12 bytes)**:
  - `total_length` (uint32 big-endian): Total frame size including prelude, headers, payload, and message CRC.
  - `headers_length` (uint32 big-endian): Byte length of header block.
  - `prelude_crc` (uint32 big-endian): IEEE 802.3 CRC32 of first 8 bytes.
- **Headers**:
  - Encoded with 1-byte name length, name UTF-8, 1-byte value type (7 for String, 6 for Bytes), 2-byte value length, and value bytes.
  - Required headers included: `:message-type` ("event"), `:event-type` ("chunk"), `:content-type` ("application/json").
- **Message CRC32 (4 bytes)**:
  - Trailing 4-byte CRC32 computed across prelude, headers, and payload.
- **Buffer & Parsing**:
  - Powered by `botocore.eventstream.EventStreamBuffer`, providing robust incremental chunk ingestion that transparently yields complete messages regardless of packet fragmentation or concatenation.

### B. Production HTTP/2 Duplex Stream (`_CRTBedrockStreamConnection`)
Implemented in `backend/app/services/voice/bedrock_streaming.py`:
- **Request Signing**: Generates canonical AWS SigV4 signed headers (`Host`, `Content-Type`, `Accept`, `X-Amz-Date`, `Authorization`, `X-Amz-Security-Token`) using `botocore.auth.SigV4Auth` targeting service `bedrock` on the regional endpoint.
- **Active Transmission**: `send_event()` serializes payloads into EventStream frames and immediately writes them to `_http2_stream.write_data(frame_bytes, end_stream=False)` without buffering.
- **Full-Duplex Reception**: Asynchronous stream listener feeds incoming `DATA` frames from `on_body` directly into `feed_raw_bytes()`, which pushes decoded events into `_inbound_queue`.
- **Stream Lifecycle & Termination**: Gracefully closes stream by transmitting an empty frame with `end_stream=True`, closes the underlying HTTP/2 connection, and terminates the event queue cleanly.

### C. Audio Pipeline & Sample Rate Alignment
- **Native Alignment**: Set `NOVA_SONIC_INPUT_SAMPLE_RATE = 24000` in `backend/app/core/config.py`.
- **Browser Compatibility**: Matches browser Web Audio API capture (24 kHz, 16-bit linear PCM mono) directly to Amazon Nova Sonic's native 24 kHz speech recognition input and 24 kHz speech synthesis output, completely eliminating sample-rate conversion artifacts during standard calls.
- **Resampling & Validation Engine (`audio_utils.py`)**:
  - `validate_pcm_s16le()`: Validates that incoming PCM audio frames have a non-zero, even byte count (16-bit samples).
  - `calculate_pcm_duration_ms()`: Calculates precise millisecond duration based on sample rate and byte length.
  - `resample_pcm_s16le()`: Provides high-fidelity linear resampling between 16,000 Hz and 24,000 Hz using `audioop.ratecv` (with pure-Python fallback for future Python 3.13+ compatibility).
  - `pcm_s16le_to_base64()` / `base64_to_pcm_s16le()`: Optimized base64 translation for Bedrock JSON serialization.

### D. Offline Development & Mock Transport Parity
- `MockBedrockStreamConnection` and `MockBedrockStreamTransport` were updated to mirror the wire framing of `_CRTBedrockStreamConnection`:
  - Outgoing events are encoded through `AWSEventStreamCodec.encode_message()` to verify valid EventStream framing and CRC generation.
  - `send_raw_eventstream_bytes()` and `generate_binary_eventstream_response()` allow testing wire-level byte streams completely offline.

---

## 5. Files Created and Modified

| File Path | Nature of Change | Description |
|---|---|---|
| `backend/app/services/voice/audio_utils.py` | **NEW FILE** | Audio validation, duration calculation, 16kHz $\leftrightarrow$ 24kHz resampling, and base64 codecs. |
| `backend/app/core/config.py` | **MODIFIED** | Updated `NOVA_SONIC_INPUT_SAMPLE_RATE` to 24000 to achieve uniform 24kHz end-to-end alignment. |
| `backend/app/services/voice/bedrock_streaming.py` | **MODIFIED** | Implemented `AWSEventStreamCodec`, updated serializers for 24kHz `"audioType": "SPEECH"`, expanded Bedrock exception parsing, implemented active duplex `_CRTBedrockStreamConnection` with SigV4 signing, and updated `MockBedrockStreamConnection`. |
| `backend/app/services/voice/nova_sonic_driver.py` | **MODIFIED** | Added PCM frame validation and automatic resampling in `send_audio_chunk()`. |
| `backend/tests/test_voice_driver.py` | **MODIFIED** | Added 6 new comprehensive unit and offline integration tests for EventStream codec, duplex lifecycle, SigV4 headers, sample rate alignment, and audio utility functions. |

---

## 6. Detailed Test Execution & Results

The complete test suite was executed across all components. All 93 backend tests and 6 frontend verification suites passed with zero failures.

### Backend Test Breakdown (93 Passed, 0 Failed)

1. **Voice Driver & Nova Sonic Suite (`test_voice_driver.py`) — 19 Tests (100% Passed)**:
   - `test_mock_voice_driver_session_lifecycle`: PASSED
   - `test_mock_voice_driver_explicit_test_triggers`: PASSED
   - `test_amazon_nova_sonic_driver_initialization`: PASSED
   - `test_voice_driver_factory`: PASSED
   - `test_agent_tools_spec_generation`: PASSED
   - `test_bedrock_nova_sonic_serializer_all_events`: PASSED
   - `test_bedrock_nova_sonic_parser_all_events`: PASSED
   - `test_nova_sonic_driver_offline_bidirectional_streaming_lifecycle`: PASSED
   - `test_nova_sonic_driver_tool_use_and_result_offline_flow`: PASSED
   - `test_aws_eventstream_codec_binary_framing_and_crc`: PASSED
   - `test_aws_eventstream_fragmented_and_concatenated_decoding`: PASSED
   - `test_crt_bedrock_stream_signed_request_construction`: PASSED
   - `test_crt_bedrock_stream_live_duplex_lifecycle_offline`: PASSED
   - `test_audio_utils_sample_rate_validation_and_resampling`: PASSED
   - `test_nova_sonic_sample_rate_alignment_and_malformed_rejection`: PASSED
   - `test_nova_sonic_driver_interruption_drains_audio`: PASSED
   - `test_nova_sonic_orchestrator_end_to_end_tool_execution`: PASSED
   - `test_nova_sonic_orchestrator_invalid_tool_arguments_resilience`: PASSED
   - `test_nova_sonic_driver_timeout_and_error_propagation`: PASSED

2. **Live PostgreSQL 18.6 Suite (`test_postgresql_live.py`) — 7 Tests (100% Passed)**:
   - Verified against live PostgreSQL 18.6 daemon running on port 5433:
   - `test_postgresql_connection_and_version`: PASSED (PostgreSQL 18.6 confirmed)
   - `test_postgresql_alembic_tables_created`: PASSED
   - `test_postgresql_foreign_key_and_check_constraints`: PASSED
   - `test_postgresql_ingestion_and_rollback`: PASSED
   - `test_postgresql_phase2_currency_timezone_and_concurrency_locking`: PASSED
   - `test_postgresql_audit_log_immutability_trigger`: PASSED
   - `test_postgresql_least_privilege_audit_role`: PASSED

3. **Voice WebSocket Streaming & Security (`test_voice_websocket.py`) — 7 Tests (100% Passed)**:
   - Mandatory JSON auth handshake, query-token rejection, customer ownership, admin blocking (WS 1008), interruption handling, AES-256-GCM encrypted persistence.

4. **Phase 4 Auth, IDOR & Priority Suite (`test_phase4_auth_rbac.py`) — 12 Tests (100% Passed)**:
   - Argon2id password complexity, login brute-force lockouts, refresh token rotation, customer IDOR protection, admin priority triage (Urgent $\rightarrow$ High $\rightarrow$ Medium $\rightarrow$ Low), Super Owner audited transcripts.

5. **Agentic Domain Tools & Orchestration (`test_agent_tools.py`) — 10 Tests (100% Passed)**:
   - All 13 business tools verified with schema validation and edge-case execution.

6. **Real Estate Domain Engine (`test_real_estate_domain.py`) — 17 Tests (100% Passed)**:
   - Multi-currency (INR, USD), timezone scheduling, DST transitions, preference extraction, lead scoring.

7. **Data Ingestion & Conflict Resolution (`test_ingestion_pipeline.py`) — 7 Tests (100% Passed)**:
   - CSV/Excel/JSON/PDF ingestion, conflict strategy, provenance tracking, and atomic rollback.

8. **Security & Cryptography (`test_security.py`) — 7 Tests (100% Passed)**:
   - AES-256-GCM transcript encryption, nonce randomization, tamper detection, JWT validation.

9. **API Security & RBAC (`test_api_security_rbac.py`) — 4 Tests (100% Passed)**:
   - Role boundaries, Super Owner transcript access auditing, rollback endpoints.

10. **Database Schema & History (`test_database_models.py`) — 3 Tests (100% Passed)**:
    - Entity relationship graphs, price/availability history preservation, lead lifecycles.

### Frontend Verification Breakdown (6 Passed, 0 Failed)
- Password complexity alignment (Argon2id matching): PASSED
- WebSocket initial JSON auth handshake without query tokens: PASSED
- Customer portal zero-transcript/no-chat-history policy: PASSED
- Admin portal zero-transcript/zero-audio leakage: PASSED
- Super Owner audited transcript and audio access: PASSED
- API client JWT storage and rotation: PASSED

---

## 7. Component Status Matrix

| Component | Status | Notes |
|---|---|---|
| AWS Bedrock HTTP/2 Duplex Streaming (`_CRTBedrockStreamConnection`) | **IMPLEMENTED & OFFLINE VERIFIED** | Implemented using `awscrt.http` and `botocore.auth.SigV4Auth`. Actively writes frames via `write_data()`. |
| AWS EventStream Wire Framing (`AWSEventStreamCodec`) | **IMPLEMENTED & OFFLINE VERIFIED** | 12-byte prelude, typed headers, CRC32 checksums, validated with `botocore.eventstream.EventStreamBuffer`. |
| EventStream Chunk Defragmentation / Concatenation | **IMPLEMENTED & OFFLINE VERIFIED** | Verified with arbitrary frame splits and concatenated multi-frame chunks. |
| Model Identifier (`amazon.nova-2-5-sonic`) | **IMPLEMENTED & OFFLINE VERIFIED** | Configured in `settings.BEDROCK_MODEL_ID` and validated in all event serializers. |
| Audio Sample Rate Alignment (24,000 Hz) | **IMPLEMENTED & OFFLINE VERIFIED** | Uniform 24kHz pipeline (browser capture $\leftrightarrow$ Bedrock input $\leftrightarrow$ model output). |
| Audio Utility Module (`audio_utils.py`) | **IMPLEMENTED & OFFLINE VERIFIED** | Validates 16-bit PCM, calculates durations, resamples 16kHz $\leftrightarrow$ 24kHz, and encodes base64. |
| 13 Agentic Real Estate Business Tools | **IMPLEMENTED & OFFLINE VERIFIED** | Fully registered and preserved; tools execute through orchestrator, never invoked directly by Bedrock. |
| Live AWS Bedrock Network Call | **NOT VERIFIED / BLOCKED BY POLICY** | Offline development strictly enforced (`USE_MOCK_VOICE=True`). Zero AWS network calls or charges permitted. |
| AWS Live Cloud Credentials | **NOT CONFIGURED / BLOCKED BY POLICY** | `AWS_ACCESS_KEY_ID=None`, `AWS_SECRET_ACCESS_KEY=None`. Offline mock transport verifies all protocol mechanics. |

---

## 8. Remaining Limitations & Live Activation Readiness

1. **Live AWS Activation Pre-requisites**:
   - Live activation requires setting `USE_MOCK_VOICE=False` and provisioning valid IAM credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and optional `AWS_SESSION_TOKEN`) with `bedrock:InvokeModelWithBidirectionalStream` IAM permissions on ARN `arn:aws:bedrock:*::foundation-model/amazon.nova-2-5-sonic`.
   - Live streaming cannot be verified until explicit user approval is granted to configure credentials and make cloud API calls.
2. **Audio Processing Library Compatibility**:
   - `audioop` is standard in Python 3.11 but slated for deprecation in Python 3.13. `audio_utils.py` contains a built-in pure-Python linear interpolation fallback to ensure seamless operation across future Python runtime upgrades.
3. **Database Audit Log Immutability Boundaries**:
   - As documented in Phase 4, PostgreSQL triggers and least-privilege roles prevent `UPDATE` and `DELETE` actions by application roles. Database superusers (e.g., `postgres`) retain administrative capabilities by PostgreSQL design.

---

## 9. Conclusion

Phase 2, Step 2 is **100% complete and offline verified**. All confirmed issues have been addressed with production-grade implementations. The codebase adheres strictly to the offline safety rules, maintains model identifier `amazon.nova-2-5-sonic`, and boasts a clean 93/93 backend test pass rate alongside 6/6 frontend verification checks. The system is fully prepared for live AWS Bedrock testing whenever authorized by the user.
