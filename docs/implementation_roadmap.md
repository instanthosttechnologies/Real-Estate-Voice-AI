# Implementation Roadmap: Real Estate Agentic Voice AI

---

## Phase 0: Workspace Discovery & Architectural Blueprint (Completed)
- [x] Workspace inspection (empty workspace confirmed).
- [x] Verification of official Amazon Bedrock Model ID (`amazon.nova-2-5-sonic`) and supported regions (`us-east-1`, `us-west-2`, `eu-north-1`, `ap-northeast-1`).
- [x] Architectural design with lean infrastructure (PostgreSQL core; no Redis, no pgvector for MVP).
- [x] Normalized real-estate relational schema specification (companies, locations, projects, properties, units, pricing, availability, amenities, customers, leads, site visits).
- [x] Dynamic dataset ingestion specification (preview, AI column mapping, manual confirmation, validation, deduplication, conflict review, provenance, rollback).
- [x] Security architecture and RBAC matrix (Customer, Admin, Super Owner with dual-layer transcript/audio isolation).
- [x] Documentation generated: `architecture.md`, `dynamic_ingestion_spec.md`, `rbac_security_matrix.md`, `implementation_roadmap.md`.

---

## Phase 1: Security Foundations, Normalized DB Schemas & Dynamic Ingestion Pipeline (Completed & Verified)
- [x] **Security Foundations**:
  - Role definitions and permission boundaries (`customer`, `admin`, `super_owner`).
  - Argon2id password hashing (RFC 9106, 64 MB memory, 3 iterations) and JWT issuance.
  - AES-256-GCM authenticated symmetric encryption for sensitive transcripts with 96-bit random nonces.
  - Pydantic Settings configuration with secure defaults (`USE_MOCK_VOICE=true`, no AWS credentials needed).
  - Tamper-evident `audit_logs` service.
- [x] **Relational Core (PostgreSQL 18 + SQLAlchemy + Alembic)**:
  - Implement full normalized schema migrations for 17 tables (companies, locations, projects, properties, units, pricing, availability, amenities, customers, leads, site visits, users, conversations, audit_logs, ingestion_batches, ingestion_records).
  - Dual-layer transcript isolation: DB column encryption and API projection pruning.
  - Verified against live PostgreSQL 18.6 with check constraints, foreign keys, and rollbacks.
- [x] **Dynamic Ingestion Engine**:
  - Multi-format parser for Excel (`.xlsx`, `.xls`), CSV, JSON, and PDF documents.
  - Preview extraction endpoint (first 15 sample rows).
  - AI-assisted column mapping with confidence scoring.
  - Manual confirmation UI hooks for uncertain/ambiguous mappings ($c < 0.85$).
  - Pydantic v2 validation, deduplication logic, and conflict review resolver.
  - Provenance tracking (`ingestion_batches`, `ingestion_records`) and atomic rollback service.

---

## Phase 2: Core Domain Logic & Agent Tool Calling Engine (Completed & Verified)
- [x] **Property Search Engine**:
  - Multi-criteria parameterized search by city, location, company, project, property type, BHK, budget bounds, carpet area, and amenities.
  - Returns only genuine database records. Never fabricates records.
- [x] **Property Matching Engine**:
  - Multi-factor scoring (layout, budget, city, amenities) with transparent natural-language match explanations.
- [x] **Property Details and Verified Pricing**:
  - Complete unit, property, and project specification retrieval with verified active pricing breakdown (base price, maintenance, parking, tax, total).
  - Preserves pricing history; never quotes expired/unverified prices as current.
- [x] **Live Availability Engine**:
  - Distinguishes `available`, `reserved` (with hold expiration), `sold`, `blocked`, and `unknown`.
  - Never assumes availability.
- [x] **Customer Requirement Extraction**:
  - Natural-language extraction of buy/rent intent, configuration, budget (handles $1.2M, 800k, numeric ranges), city, amenities, and timeline.
  - Detects incomplete requirements and generates targeted clarification prompts.
- [x] **Lead Management & Deterministic Priority Engine**:
  - CRM customer profile creation/lookup and lead lifecycle tracking.
  - Deterministic priority classification (`urgent`, `high`, `medium`, `low`) based on intent, timeline, and booking requests.
  - Manual priority override with immutable audit logging.
- [x] **Site Visit Management**:
  - 1-hour appointment slot lookup for operating hours (9 AM - 6 PM).
  - Booking with double-booking prevention (customer, unit, and project capacity checks).
  - Appointment rescheduling, cancellation, and lead status progression (`ready_to_visit`).
- [x] **Validated Agent Tools**:
  - Implemented and verified all 13 tools with strict Pydantic schemas and structured error recovery:
    `search_properties()`, `get_property_details()`, `get_property_price()`, `check_property_availability()`,
    `extract_requirements()`, `create_lead()`, `update_lead()`, `calculate_lead_priority()`,
    `check_visit_slots()`, `book_site_visit()`, `reschedule_site_visit()`, `cancel_site_visit()`, `transfer_to_human()`.
- [x] **Automated Test Coverage**:
  - 23 dedicated domain and tool tests + 21 Phase 1 tests + 4 live PostgreSQL tests = **48 total automated tests passing**.

---

## Phase 3: Voice AI Orchestration Layer (Completed & Verified)
- [x] **Voice Driver Architecture**:
  - `VoiceDriver`: Common abstract interface (`start_session`, `send_audio_chunk`, `send_text_input`, `send_tool_result`, `interrupt`, `end_session`, `receive_events`).
  - `MockVoiceDriver`: Offline, zero-cost, credential-free local development simulator providing realistic speech recognition, transcript deltas, synthetic PCM audio generation, intent-based tool calling, and interruption handling.
  - `AmazonNovaSonicDriver`: Production driver for `amazon.nova-2-5-sonic` via AWS Bedrock runtime bidirectional streaming protocol. Isolates database access strictly to the backend orchestrator.
  - `get_voice_driver()`: Factory returning `MockVoiceDriver` when `USE_MOCK_VOICE=True` (default) or `AmazonNovaSonicDriver`.
- [x] **Amazon Nova 2.5 Sonic Integration**:
  - Verified model ID: `amazon.nova-2-5-sonic`.
  - JSON Schema tool specifications generated dynamically from the 13 validated Pydantic agent models (`get_agent_tools_spec`).
  - Intercepts model tool calls, routes to Phase 2 dispatcher, and returns structured tool results with anti-hallucination guidance.
- [x] **WebSocket Gateway & Session Orchestrator**:
  - FastAPI WebSocket endpoint at `/ws/voice/{session_id}` (and `/api/v1/ws/voice/{session_id}`).
  - Bidirectional streaming supporting binary PCM audio frames and JSON control messages.
  - Session lifecycle management: greeting synthesis, speech-to-text transcript streaming, and graceful teardown.
  - Barge-in / interruption handling: cancels pending audio frames on client interruption signal.
  - Backpressure handling (bounded audio queue) and chunk size validation (64 KB max frame limit).
- [x] **Voice Security & Transcript Encryption**:
  - JWT token authentication during WebSocket handshake (`?token=...` or initial auth message).
  - RBAC boundary enforcement: Customer accesses own session; Super Owner audited; Admin strictly forbidden (WS code 1008 policy violation) from private voice audio and transcripts.
  - Conversation transcript accumulation encrypted with AES-256-GCM authenticated cipher before saving to PostgreSQL/SQLite.
  - Immutable audit logging for `VOICE_SESSION_STARTED`, `VOICE_TOOL_EXECUTED`, `VOICE_SESSION_INTERRUPTED`, and `VOICE_SESSION_COMPLETED`.
- [x] **Automated Test Coverage**:
  - 5 voice driver tests (`test_voice_driver.py`) + 7 voice WebSocket tests (`test_voice_websocket.py`) + 53 existing Phase 1 & 2 tests = **65 total automated tests passing**.

---

## Phase 4: Authentication, RBAC Enforcements & Admin APIs (Upcoming)
- Front-facing API integration and session refresh.
- Admin reporting views and Super Owner audit console endpoints.

---

## Phase 5: Next.js Frontend Development (Upcoming)
- Customer Voice Portal (`AudioWorklet` / WebSocket streaming).
- Admin Dashboard (Priority & Customer tables).
- Super Owner Console (Audited transcripts, audio stream playback, dataset ingestion UI).

---

## Phase 6: End-to-End Hardening & Deployment (Upcoming)
- End-to-end integration tests, latency benchmarking, and deployment documentation.
