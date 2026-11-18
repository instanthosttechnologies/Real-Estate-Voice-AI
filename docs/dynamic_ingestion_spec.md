# Dynamic Dataset Ingestion Specification

## 1. Objective & Non-Negotiable Constraints
- **Universal Multi-Format Ingestion**: Ingest property, project, pricing, and availability records from Excel (`.xlsx`, `.xls`), CSV (`.csv`), JSON (`.json`, `.jsonl`), and PDF (`.pdf`) documents.
- **Zero Table Generation**: Never execute `CREATE TABLE` or alter database schemas dynamically when a file is uploaded. All records must normalize into the predefined relational schema (`companies`, `locations`, `projects`, `properties`, `property_units`, `pricing`, `availability`, `amenities`).
- **Complete Ingestion Lifecycle**: Support File Upload -> Extract & Preview -> AI-Assisted Column Mapping -> Manual Confirmation -> Strict Validation -> Deduplication & Conflict Review -> Normalized Batch Commit -> Provenance & Version Tracking -> Atomic Rollback.

---

## 2. Ingestion Lifecycle Pipeline

```mermaid
flowchart TD
    Upload[1. File Upload (Excel, CSV, JSON, PDF)] --> Parse[2. File Parser & Normalizer]
    Parse --> Preview[3. Sample Preview Extraction (First 15 Rows)]
    Preview --> AIMap[4. AI-Assisted Semantic Column Mapping]
    AIMap --> ConfCheck{Confidence >= 0.85 & Unambiguous?}
    ConfCheck -- No --> ManualConfirm[5. Manual Column Mapping Confirmation in UI]
    ConfCheck -- Yes --> UserApproval[6. User Final Inspection & Approval]
    ManualConfirm --> UserApproval
    UserApproval --> Validate[7. Pydantic v2 Strict Entity Validation]
    Validate --> Dedupe[8. Deduplication & Conflict Detection]
    Dedupe --> ConflictCheck{Conflicts Found?}
    ConflictCheck -- Yes --> ConflictReview[9. Conflict Review: Overwrite / Skip / Version]
    ConflictCheck -- No --> BatchCommit[10. Atomic Multi-Table Relational Commit]
    ConflictReview --> BatchCommit
    BatchCommit --> Provenance[11. Ingestion Log & Provenance Record Created]
    BatchCommit -.->|Rollback Triggered| Rollback[12. Atomic Rollback Handler]
```

---

## 3. Pipeline Stages in Detail

### Stage 1 & 2: Parsing & Document Extraction
- **Excel (`.xlsx`, `.xls`)**: Parsed via `pandas` / `openpyxl`, handling multi-sheet workbooks with sheet selector.
- **CSV (`.csv`)**: Handled via `pandas` with robust delimiter sniffing (comma, semicolon, tab) and CSV formula sanitization (`=`, `+`, `-`, `@` escaped to prevent injection).
- **JSON / JSONLines (`.json`, `.jsonl`)**: Validated via Pydantic; supports flat record arrays and nested property hierarchies.
- **PDF (`.pdf`)**: Extracted using `PyMuPDF` (`fitz`) table recognition and structural text blocks, returning tabular JSON records.

### Stage 3: Preview Extraction
- Returns the first 15 records of raw data alongside inferred data types (integer, float, date, string) for user review in the UI before mapping or database execution.

### Stage 4 & 5: AI-Assisted Column Mapping & Manual Confirmation
- **Canonical Schema Targets**:
  - `company.name`
  - `location.city`, `location.state`, `location.postal_code`, `location.address_line_1`
  - `project.name`, `project.status`, `project.completion_date`
  - `property.name` (Tower/Phase), `property.property_type`
  - `property_unit.unit_number`, `property_unit.configuration_type`, `property_unit.carpet_area_sqft`
  - `pricing.base_price`, `pricing.maintenance_charge_monthly`, `pricing.total_estimated_price`
  - `availability.status`, `availability.available_from`
  - `amenity.names` (comma-separated list)
- **AI Matching Engine**:
  - Evaluates source column headers and sample cell values against target canonical attributes using fuzzy lexical matching and semantic synonyms (e.g., `["Beds", "BHK", "Bedrooms", "Layout"] -> property_unit.configuration_type`; `["Cost", "Rate", "Price", "Ask"] -> pricing.base_price`).
  - Assigns a confidence score ($0.0 \le c \le 1.0$) to each column.
- **Manual Confirmation Barrier**:
  - Any mapping with $c < 0.85$ or multiple conflicting target matches is marked `REQUIRES_CONFIRMATION`.
  - The ingestion job pauses in `mapping_pending` state until an Admin or Super Owner confirms or updates the column mapping via the UI.

### Stage 6 & 7: Pydantic Validation & Normalization
- Every mapped row is instantiated into typed Pydantic models:
  - Negative values rejected for `price`, `carpet_area_sqft`, and `floor_number`.
  - Date strings normalized to ISO 8601 (`YYYY-MM-DD`).
  - Configuration types normalized to standard enums (`1BHK`, `2BHK`, `3BHK`, `Studio`, `Penthouse`, `Villa`).
  - Invalid rows are segregated into a `validation_errors` report with row index and exact error messages.

### Stage 8 & 9: Deduplication & Conflict Review
- **Natural Entity Keys**:
  - `Company`: `company.name`
  - `Project`: `(company_id, project.name, location.postal_code)`
  - `Property`: `(project_id, property.name)`
  - `PropertyUnit`: `(property_id, unit_number)`
- **Conflict Detection**:
  - If a unit with identical `(property_id, unit_number)` already exists but has conflicting attributes (e.g., different `base_price` or `availability.status`), it is flagged as a `CONFLICT`.
  - **Resolution Policy Options**:
    1. `SKIP`: Retain existing database record, log skipped entry.
    2. `OVERWRITE`: Update existing record and archive previous pricing/availability.
    3. `NEW_VERSION`: Increment version tracking and set historical pricing `is_active = FALSE`.

### Stage 10 & 11: Batch Commit, Provenance & Ingestion Tables

```sql
CREATE TABLE ingestion_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename VARCHAR(255) NOT NULL,
    file_format VARCHAR(20) NOT NULL,
    file_hash VARCHAR(64) NOT NULL, -- SHA-256 for audit and duplicate file checks
    uploaded_by_user_id UUID NOT NULL REFERENCES users(id),
    status VARCHAR(50) NOT NULL, -- 'pending_mapping', 'processing', 'completed', 'failed', 'rolled_back'
    total_rows INT NOT NULL DEFAULT 0,
    imported_rows INT NOT NULL DEFAULT 0,
    skipped_rows INT NOT NULL DEFAULT 0,
    failed_rows INT NOT NULL DEFAULT 0,
    error_summary JSONB,
    mapping_config JSONB NOT NULL,
    can_rollback BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE ingestion_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID NOT NULL REFERENCES ingestion_batches(id) ON DELETE CASCADE,
    entity_type VARCHAR(50) NOT NULL, -- 'project', 'property_unit', 'pricing'
    entity_id UUID NOT NULL,
    source_row_index INT NOT NULL,
    action_taken VARCHAR(50) NOT NULL, -- 'INSERT', 'UPDATE', 'SKIP'
    previous_state JSONB, -- Snapshot of prior state for atomic rollback
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Stage 12: Atomic Rollback Engine
- When an administrator initiates a rollback for `batch_id`:
  1. Verifies `ingestion_batches.can_rollback = TRUE` and no downstream dependent transactions have locked the entities.
  2. Queries `ingestion_records` for that batch in reverse order:
     - For `action_taken = 'INSERT'`: Safely deletes the inserted entity records.
     - For `action_taken = 'UPDATE'`: Reverts the entity columns to `previous_state`.
  3. Updates `ingestion_batches.status = 'rolled_back'` and `can_rollback = FALSE`.
  4. Records an immutable event in `audit_logs` detailing the user ID, timestamp, and batch ID.
