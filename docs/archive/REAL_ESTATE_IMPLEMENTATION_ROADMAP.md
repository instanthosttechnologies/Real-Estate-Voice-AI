# Real Estate Agentic Voice AI — Implementation Roadmap

**Document Version:** 1.0  
**Status:** Approved for Planning (Implementation on Hold Pending External Review)  
**Derived From:** Real Estate Agentic Voice AI Full Requirements Gap Audit (November 2026)  
**Governing Principle:** Zero breaking changes to verified Phases 1–5; strictly additive enhancements; retain Amazon Nova 2.5 Sonic and FastAPI WebSocket architecture.

---

## 1. Prioritization Overview

```mermaid
flowchart LR
    P1["1. Voice Integration Blockers"] --> P2["2. Core Property Matching Gaps"]
    P2 --> P3["3. Dynamic Ingestion Improvements"]
    P3 --> P4["4. Lead & Visit Workflow Gaps"]
    P4 --> P5["5. Location Services & CRM"]
    P5 --> P6["6. Security & Production Readiness"]
```

The remediation work is structured into six sequential tracks ordered by business criticality and technical dependency:

1. **Track 1: Voice Integration Blockers** — Transition from offline mock mode to live AWS Bedrock bidirectional streaming upon credential authorization.
2. **Track 2: Core Property Matching Gaps** — Close matching deficiencies by connecting the scoring engine to search, implementing multi-property comparison, and persisting multi-turn session state.
3. **Track 3: Dynamic Database and Ingestion Improvements** — Scale dynamic file ingestion with asynchronous background workers and spatial query optimizations.
4. **Track 4: Lead and Site-Visit Workflow Gaps** — Enhance customer notifications, calendar invites, and advisor handoff escalation triggers.
5. **Track 5: Location Services and CRM Integration** — Build a verified nearby facilities data model and external CRM webhook dispatchers.
6. **Track 6: Security and Production Readiness** — Master key rotation, containerization, and enterprise load-balancing.

---

## Track 1: Voice Integration Blockers (Priority: P0 / Prerequisite)

### Objective
Enable live, cloud-native Amazon Nova 2.5 Sonic bidirectional streaming (`amazon.nova-2-5-sonic`) via AWS Bedrock Runtime when AWS credentials and billing permissions are authorized.

### Target Files
- `backend/app/core/config.py`
- `backend/app/services/voice/bedrock_streaming.py`
- `backend/app/services/voice/nova_sonic_driver.py`
- `.env.example`

### Action Items
1. **Configurable Environment Switch**:
   - Provide explicit environment toggles:
     ```env
     USE_MOCK_VOICE=false
     BEDROCK_MODEL_ID=amazon.nova-2-5-sonic
     AWS_REGION=us-east-1
     AWS_ACCESS_KEY_ID=<your-access-key-id>
     AWS_SECRET_ACCESS_KEY=<your-secret-access-key>
     AWS_SESSION_TOKEN=<optional-temporary-token>
     ```
2. **IAM Policy Provisioning Guide**:
   - Document the least-privilege IAM policy required for live Nova Sonic duplex streaming:
     ```json
     {
       "Version": "2012-10-17",
       "Statement": [
         {
           "Effect": "Allow",
           "Action": [
             "bedrock:InvokeModelWithBidirectionalStream"
           ],
           "Resource": [
             "arn:aws:bedrock:*::foundation-model/amazon.nova-2-5-sonic"
           ]
         }
       ]
     }
     ```
3. **Graceful Fallback & Circuit Breaker**:
   - If AWS Bedrock streaming returns HTTP 429 (Throttling) or HTTP 503 (Service Unavailable), the driver should gracefully emit a friendly voice warning to the customer and log an urgent audit event without dropping the WebSocket connection.
4. **Live Audio Latency Verification**:
   - Conduct end-to-end latency benchmarks measuring time from speech pause (VAD silence) to first assistant audio frame (target: $< 600$ ms).

### Acceptance Criteria
- [ ] Voice assistant streams live audio with `amazon.nova-2-5-sonic` on AWS Bedrock when `USE_MOCK_VOICE=false`.
- [ ] Offline regression tests pass with `USE_MOCK_VOICE=true` without requiring AWS credentials.

---

## Track 2: Core Property Matching Gaps (Priority: P1)

### Objective
Bridge the gap between exact SQL search and intelligent real estate advisory by automating partial-match recommendations, property comparisons, and multi-turn state accumulation.

### Target Files
- `backend/app/services/real_estate/matcher.py`
- `backend/app/services/agent/tools.py`
- `backend/app/services/agent/dispatcher.py`
- `backend/app/services/voice/orchestrator.py`
- `backend/app/schemas/agent_tools.py`

### Action Items
1. **Wire `rank_and_explain_matches` into Search Pipeline (GAP-01)**:
   - Update `tool_search_properties` in `backend/app/services/agent/tools.py`:
     - If exact SQL search returns fewer than 3 properties, perform an automatic relaxed search (relaxing strict amenity constraints or allowing $\pm 10\%$ budget flex).
     - Run relaxed results through `rank_and_explain_matches()`.
     - Output both `exact_matches` and `recommended_alternatives` with match percentage scores and natural-language explanations (e.g., *"Alternative: 85% match — within budget, 3BHK instead of requested 2BHK"*).
2. **Implement Dedicated Property Comparison Tool (GAP-02)**:
   - Add `tool_compare_properties` to `backend/app/services/agent/tools.py`:
     - **Input:** `unit_ids: List[UUID]` (2 to 4 properties).
     - **Output:** Structured comparison matrix:
       - Price comparison (base price, maintenance, total price, price per sqft).
       - Configuration, floor level, carpet area, facing.
       - Amenity differences (unique amenities in Property A vs Property B).
       - Proximity and location comparison.
       - Concise summary highlighting pros and cons of each option.
   - Register `tool_compare_properties` in `tools_spec.py` and `dispatcher.py`.
3. **Multi-Turn Session State Context (`SessionState`) (GAP-03)**:
   - Enhance `VoiceSessionOrchestrator` in `backend/app/services/voice/orchestrator.py`:
     - Maintain an active `CustomerSessionContext` in memory during the conversation:
       ```python
       class CustomerSessionContext:
           customer_id: Optional[UUID]
           accumulated_requirements: ExtractedCustomerRequirements
           inspected_unit_ids: List[UUID]
           booked_visit_id: Optional[UUID]
       ```
     - When `extract_requirements` is executed in Turn 2, merge new fields into `accumulated_requirements` without overwriting unmentioned previous requirements.
4. **Returning Customer Profile Pre-loading (GAP-04)**:
   - In `VoiceSessionOrchestrator.start()`:
     - Query existing active `Lead` and `Customer` records for `customer_id`.
     - Pre-seed the system preamble with customer context (e.g. *"Customer has previous interest in 2BHK apartments in Whitefield with a budget of ₹1.2 Cr"*).

### Acceptance Criteria
- [ ] When an exact search produces zero matches, verified alternatives with match percentages are automatically suggested.
- [ ] Agent can call `compare_properties` to return a side-by-side spec comparison of 2 or more units.
- [ ] Customer preferences updated in Turn 2 preserve untouched preferences from Turn 1.

---

## Track 3: Dynamic Database and Ingestion Improvements (Priority: P2)

### Objective
Ensure dynamic dataset ingestion scales smoothly to tens of thousands of property units while maintaining transactional integrity and rollback guarantees.

### Target Files
- `backend/app/services/ingestion/pipeline.py`
- `backend/app/services/ingestion/parsers/csv_excel.py`
- `backend/app/api/v1/ingestion.py`
- `backend/app/models/ingestion.py`

### Action Items
1. **Chunked Streaming Ingestion**:
   - For files larger than 10 MB or exceeding 5,000 rows, execute parsing and database inserts in configurable batches (e.g., 500 rows per transaction) with an async task runner (`FastAPI BackgroundTasks` or Celery).
2. **Composite Database Indexing**:
   - Add composite B-tree indexes to optimize multi-condition real estate queries on PostgreSQL:
     ```sql
     CREATE INDEX idx_units_search ON property_units (configuration_type, carpet_area_sqft);
     CREATE INDEX idx_pricing_active_search ON pricing (unit_id, is_active, base_price, currency);
     CREATE INDEX idx_locations_city_query ON locations (lower(city), lower(postal_code));
     ```
3. **Automated Geocoding on Ingestion**:
   - When a dataset includes address/landmark without latitude/longitude, optionally trigger an offline geocoding utility during preview confirmation to populate spatial coordinates.

### Acceptance Criteria
- [ ] Ingestion of a 10,000-row property catalog completes within 30 seconds without blocking WebSocket voice traffic.
- [ ] Property search queries execute in $< 25$ ms on PostgreSQL with composite indexes.

---

## Track 4: Lead and Site-Visit Workflow Gaps (Priority: P2)

### Objective
Elevate the lead and site-visit lifecycle from database records into an active sales workflow with real-time advisor notification triggers.

### Target Files
- `backend/app/services/real_estate/site_visits.py`
- `backend/app/services/real_estate/leads.py`
- `backend/app/services/agent/tools.py`

### Action Items
1. **Site Visit Calendar Invites & Notifications**:
   - Generate standard `.ics` iCalendar invites upon successful `book_site_visit` execution.
   - Provide email/SMS notification hooks (`NotificationService`) to send confirmation links with rescheduling tokens to customers.
2. **Automated Sales Advisor Allocation**:
   - Implement round-robin or territory-based sales advisor assignment in `book_site_visit` based on project location.
3. **Telephony Call Escalation Webhook (GAP-07)**:
   - When `transfer_to_human` creates a high-priority handoff ticket, optionally dispatch an outbound webhook payload to the customer support telephony desk (e.g. Twilio / Amazon Connect / Genesys) to queue an immediate advisor callback.

### Acceptance Criteria
- [ ] Site visit bookings generate verifiable calendar payloads with project timezone.
- [ ] Human handoff requests dispatch structured escalation webhooks with customer conversation summaries.

---

## Track 5: Location Services and CRM Integration (Priority: P2)

### Objective
Provide verified, structured proximity data for nearby infrastructure (schools, hospitals, transit, shopping) and support bi-directional synchronization with external CRM platforms.

### Target Files
- `backend/app/models/project.py`
- `backend/app/models/location.py`
- `backend/app/services/real_estate/search.py`
- `backend/app/services/agent/tools.py`
- `backend/app/schemas/agent_tools.py`

### Action Items
1. **Normalized `nearby_facilities` Relational Model (GAP-05)**:
   - Add `NearbyFacility` model:
     ```python
     class NearbyFacility(Base, TimestampMixin):
         __tablename__ = "nearby_facilities"
         id: Mapped[UUID] = mapped_column(GUID(), primary_key=True, default=uuid4)
         project_id: Mapped[UUID] = mapped_column(GUID(), ForeignKey("projects.id", ondelete="CASCADE"), index=True)
         facility_name: Mapped[str] = mapped_column(String(255), nullable=False)
         facility_type: Mapped[str] = mapped_column(String(50), index=True) # 'school', 'hospital', 'metro', 'mall', 'airport'
         distance_km: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
         travel_time_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
         is_verified: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
     ```
2. **Agent Tool: `get_nearby_facilities`**:
   - Add tool enabling the voice agent to answer customer inquiries such as *"Are there international schools or metro stations near Pinnacle Tower?"* using verified database records.
3. **External CRM Webhook Dispatcher (GAP-06)**:
   - Build an asynchronous webhook event emitter in `backend/app/services/crm/webhook_sync.py`:
     - Dispatches `LEAD_CREATED`, `LEAD_PRIORITY_ELEVATED`, and `SITE_VISIT_BOOKED` events to external CRM webhook endpoints (Salesforce, HubSpot, Zoho CRM) with HMAC-SHA256 signature verification.

### Acceptance Criteria
- [ ] Agent can query nearby verified schools, hospitals, and transit hubs with exact distance metrics.
- [ ] Lead creation and priority changes trigger signed external CRM webhook events.

---

## Track 6: Security and Production Readiness (Priority: P3)

### Objective
Solidify enterprise operational readiness, disaster recovery, cryptographic hygiene, and containerized deployment.

### Target Files
- `backend/Dockerfile`
- `frontend/Dockerfile`
- `docker-compose.yml`
- `backend/app/core/security.py`

### Action Items
1. **Master Encryption Key Rotation Procedure**:
   - Implement versioned AES-256-GCM key IDs (`KEY_V1`, `KEY_V2`) in transcript headers to allow zero-downtime key rotation.
2. **Production Containerization**:
   - Create optimized multi-stage `Dockerfile` for FastAPI backend (Python 3.11-slim) and Next.js frontend (Node 20-alpine).
   - Provide a production-ready `docker-compose.yml` bundling PostgreSQL 18, FastAPI, and Next.js.
3. **Health & Readiness Probes**:
   - Expand `/health` endpoint into distinct `/health/liveness` and `/health/readiness` probes checking database connection pool availability and voice driver status.

### Acceptance Criteria
- [ ] Containerized application launches cleanly via Docker Compose with automated database migrations.
- [ ] Health probes accurately report database and voice engine readiness.

---

## 7. Implementation Schedule & Effort Estimate

| Track | Name | Estimated Effort | Target Phase | Dependencies |
|:---:|:---|:---:|:---:|:---|
| **Track 1** | Voice Integration Blockers | 1–2 Days | Phase 6 | AWS Bedrock IAM Credentials Authorization |
| **Track 2** | Core Property Matching Gaps | 2–3 Days | Phase 6 | None (Fully self-contained in existing domain code) |
| **Track 3** | Dynamic Ingestion Improvements | 2 Days | Phase 7 | Track 2 completion |
| **Track 4** | Lead & Visit Workflow Gaps | 2 Days | Phase 7 | Track 2 completion |
| **Track 5** | Location Services & CRM Integration | 3 Days | Phase 8 | Database migration for `nearby_facilities` |
| **Track 6** | Security & Production Readiness | 2–3 Days | Phase 8 | Tracks 1–5 completion |
| **TOTAL** | Full Roadmap Execution | **12–15 Days** | Phases 6–8 | Explicit user review and authorization |
