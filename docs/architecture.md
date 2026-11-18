# Technical Architecture Document: Real Estate Agentic Voice AI

## 1. System Overview & Objectives
The Real Estate Agentic Voice AI platform is a production-grade system designed to converse naturally with home seekers via real-time voice, qualify leads, query normalized property inventories, evaluate availability, and schedule site visits.

The architecture strictly decouples voice transport from deterministic business logic, prevents LLM hallucinations through validated database tool execution, guarantees strict role-based access control (RBAC), and provides dynamic dataset ingestion with provenance and rollback.

---

## 2. Infrastructure & Runtime Architecture (MVP)

### 2.1 Lean Infrastructure Principle
To avoid infrastructure bloat and unnecessary cloud costs, the MVP uses:
- **Relational Core**: PostgreSQL 18 with standard relational indices, foreign keys, and check constraints.
- **Excluded from MVP**: Redis and `pgvector` are explicitly excluded. Relational filtering (price range, configuration, location, availability) and normalized foreign-key joins satisfy all query requirements cleanly without vector index management or cache synchronization overhead.
- **Zero-Cost Local Development**: Local testing runs entirely with `USE_MOCK_VOICE=true`. No AWS credentials or paid third-party APIs are required to run, test, and develop the full stack.

### 2.2 Component Diagram
```
+-----------------------------------------------------------------------------------+
|                                  Frontend Layer                                   |
|                        Next.js 14+ (React, TypeScript, Tailwind)                  |
|  +------------------------+  +-----------------------+  +----------------------+  |
|  | Customer Voice Portal  |  | Admin Dashboard       |  | Super Owner Console  |  |
|  | (AudioWorklet / PCM WS)|  | (Priority / Leads)    |  | (Ingest/Audit/Audio) |  |
|  +-----------+------------+  +-----------+-----------+  +----------+-----------+  |
+--------------|---------------------------|-------------------------|--------------+
               | Full-Duplex PCM WS        | HTTPS REST              | HTTPS REST
+--------------v---------------------------v-------------------------v--------------+
|                              FastAPI Application Server                           |
|  +-----------------------------------------------------------------------------+  |
|  | Security & RBAC Middleware (JWT, Argon2id, Role Gates, Field Projection)    |  |
|  +-----------------------------------------------------------------------------+  |
|                                                                                   |
|  +-------------------------------------+  +------------------------------------+  |
|  | Dynamic Ingestion Pipeline          |  | Real Estate Domain Logic & Tools   |  |
|  | - Format Parsing (CSV/XLSX/JSON/PDF)|  | - Property Search & Matching Engine|  |
|  | - Preview & AI Column Mapping       |  | - Verified Pricing & Availability  |  |
|  | - Manual Confirmation Engine        |  | - Lead Qualification & Scoring     |  |
|  | - Pydantic Validation & Deduplication| | - Site Visit Conflict Prevention   |  |
|  | - Provenance, Versioning & Rollback |  | - 13 Validated Agent Tools (SQL)   |  |
|  +------------------+------------------+  +-----------------+------------------+  |
+---------------------|---------------------------------------|---------------------+
                      | SQLAlchemy (psycopg2 / asyncpg)       |
+---------------------v---------------------------------------v---------------------+
|                              PostgreSQL 18 Storage                                |
|  - companies, locations, projects, properties, property_units, pricing,           |
|    availability, amenities, project_amenities                                     |
|  - customers, leads, site_visits, users                                           |
|  - ingestion_batches, ingestion_records (provenance & rollback)                   |
|  - conversations (encrypted_transcript [AES-256-GCM], audio_storage_path)         |
|  - audit_logs (immutable read/write audit trail)                                  |
+-----------------------------------------------------------------------------------+
```

---

## 3. Voice AI & Bedrock Integration Specification

### 3.1 Model Identification & AWS Regional Availability
- **Selected Model**: **Amazon Nova 2.5 Sonic**
- **Exact Bedrock Model ID**: `amazon.nova-2-5-sonic`
- **Supported AWS Regions**:
  - `us-east-1` (US East - N. Virginia) [Primary]
  - `us-west-2` (US West - Oregon)
  - `eu-north-1` (Europe - Stockholm)
  - `ap-northeast-1` (Asia Pacific - Tokyo)
- **Runtime Endpoint**: `https://bedrock-runtime.us-east-1.amazonaws.com`
- **Invocation API**: `InvokeModelWithBidirectionalStream` (bidirectional audio and tool-calling streaming).

### 3.2 Voice Processing vs. Business Logic Separation
```
[User Mic] ---> [WebSocket] ---> [FastAPI Audio Streamer] ---> [Bedrock Nova 2.5 Sonic]
                                                                        |
                                                               (Emits Tool Call Request)
                                                                        |
                                                                        v
[FastAPI Audio Streamer] <--- [Tool Call Result] <--- [Agent Tool Dispatcher + Pydantic]
                                                                        |
                                                             (Queries Normalized DB)
```
1. **Audio Ingestion**: Client captures 16kHz/24kHz mono PCM audio via Web Audio `AudioWorklet` and streams binary frames over secure WebSocket (`/api/v1/voice/stream`).
2. **Driver Decoupling**:
   - `MockVoiceDriver` (Default for local development): Simulates conversational turns, prompts, and tool calls without external network dependencies.
   - `BedrockNovaSonicDriver` (Production): Connects to `amazon.nova-2-5-sonic` using boto3/eventstream for bidirectional speech-to-speech.
3. **Anti-Hallucination Tool Boundary**:
   - Nova 2.5 Sonic is instructed via system prompt that it possesses zero direct knowledge of property pricing, inventory, or booking dates.
   - To convey any real estate detail, it **must** invoke one of the validated tools (`search_properties`, `check_availability`, `qualify_lead`, `schedule_site_visit`).
   - If a tool returns no matches or unavailable status, the model is strictly constrained to convey that factual result.

---

## 4. Validated Agent Tools Architecture (Phase 2)

All agent actions are dispatched through `dispatch_agent_tool` in `app/services/agent/dispatcher.py` with strict Pydantic v2 argument validation and structured error recovery:

| Tool Name | Domain Module | Description & Anti-Hallucination Constraints |
| :--- | :--- | :--- |
| `search_properties()` | `search.py` | Multi-criteria parameterized search across cities, BHK, budget bounds, and amenities. Returns real database records only. |
| `get_property_details()` | `details.py` | Complete specs of unit, tower, project, developer, and verified active pricing breakdown. |
| `get_property_price()` | `details.py` | Verified active base price, maintenance, parking, tax, total. Returns "under review" if unverified. |
| `check_property_availability()`| `availability.py` | Real-time status (`available`, `reserved`, `sold`, `blocked`, `unknown`). Never assumes availability. |
| `extract_requirements()` | `requirements.py` | Extracts intent, budget, location, configuration, timeline, amenities, and generates clarification prompts. |
| `create_lead()` | `leads.py` | Initializes CRM customer profile and qualified lead record. |
| `update_lead()` | `leads.py` | Updates requirements, qualification state, notes, or priority. |
| `calculate_lead_priority()` | `priority.py` | Deterministic priority classification (`urgent`, `high`, `medium`, `low`) based on intent and readiness. |
| `check_visit_slots()` | `site_visits.py` | Queries available 1-hour appointment slots for operating hours (9 AM - 6 PM). |
| `book_site_visit()` | `site_visits.py` | Books appointment with customer and unit double-booking checks; updates lead to `ready_to_visit`. |
| `reschedule_site_visit()` | `site_visits.py` | Validates capacity and moves appointment to new slot. |
| `cancel_site_visit()` | `site_visits.py` | Cancels appointment and logs reason. |
| `transfer_to_human()` | `tools.py` | Initiates warm transfer to sales/legal specialist, elevates lead to `urgent`, and generates audit log. |

---

## 5. Security & Isolation Architecture

1. **Dual-Layer Transcript Isolation**:
   - **Database Level**: Transcripts are encrypted with **AES-256-GCM** before writing to `conversations.encrypted_transcript`.
   - **API Level**: FastAPI dependencies enforce `RoleChecker(["super_owner"])` on endpoints returning transcript or audio data. Admin endpoints select only priority and customer aggregate fields, strictly omitting transcript/audio fields from the query and Pydantic serialization models.
2. **Audit Logging**:
   - Every decryption, audio stream request, priority override, or human handover is logged synchronously to `audit_logs` with the actor's identity, IP address, and timestamp.
3. **Password Security**:
   - Passwords hashed using **Argon2id** (RFC 9106, 64 MB memory cost, 3 iterations, 4 parallelism threads).
