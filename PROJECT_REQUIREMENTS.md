# Brain Magic RealEstate Voice AI — Project Functional Requirements Document

**Document Title:** Project Functional Requirements Specification  
**Project Path:** `D:\Brain Magic\RealEstate_Agentic_Voice_AI`  
**Current Version:** 1.0.0  
**Effective Date:** November 20, 2026  
**Status Legend:**
- **`Implemented`**: Architecture and code exist in the running codebase.
- **`Offline Tested`**: Verified via automated mock/unit/integration/E2E test suites with 0 cloud charges.
- **`Live Verified`**: Verified against live, third-party production cloud services (e.g. active AWS Bedrock endpoint).
- **`Pending`**: Feature requested or attempted, but not yet functional or verified in live production.

---

## 1. Project Overview & Brand Identity

### 1.1 Branding & Purpose
- **Application Name:** **Brain Magic RealEstate Voice AI**
- **Domain:** Autonomous AI Voice Advisor for Real Estate Inquiry, Property Matching, and Site Visit Scheduling.
- **Theme & Aesthetics:** Modern, clean white and sky-blue color palette (`#0284c7`, `#0ea5e9`, `#f0f9ff`, slate-800, with emerald `#10b981` accents) applied consistently across customer, admin, and super owner interfaces.
- **Status:** **`Implemented & Offline Tested`**

---

## 2. User Roles & Access Control (RBAC)

The system enforces strict Role-Based Access Control (RBAC) with cryptographic separation:

| Role | Permissions & Boundaries | Privacy & Security Guarantees | Status |
|---|---|---|:---:|
| **Customer** | OTP-verified voice access, personal requirement memory, viewing matched properties, booking site visits. | Can only access own session transcripts and bookings. | **`Implemented & Offline Tested`** |
| **Admin** | Real estate inventory management, lead monitoring, sales team management, dataset upload. | **Strictly prohibited** from accessing live voice audio, private customer transcripts, or encryption keys (`WS/HTTP 1008 Policy Violation`). | **`Implemented & Offline Tested`** |
| **Super Owner** | System administration, user management, dataset activation, security audit history, system health. | May view decrypted transcripts and audio recordings **only** via explicit, audited modal confirmation. | **`Implemented & Offline Tested`** |

- **Authentication:** Email OTP verification (HMAC-SHA256, 10-minute expiry, rate-limited) and Argon2id password hashing with short-lived JWT access tokens (15 minutes) and rotating refresh tokens (7 days).
- **Audit Logging:** Every login, voice session start, tool execution, priority change, and transcript decryption is recorded in the PostgreSQL `audit_logs` table.
- **Status:** **`Implemented & Offline Tested`**

---

## 3. Customer Dashboard & Conversation Interface

### 3.1 Single Expanding Container
- **Before Conversation Started:**
  - One clean, centered white and sky-blue rounded container (`rounded-3xl border-sky-100 shadow-sm max-w-xl`).
  - Animated 3D robot avatar centered prominently in relaxed floating/breathing idle pose.
  - Clear, prominent **Start Conversation** button with microphone icon.
  - Helpful sample inquiries displayed underneath (*"Show me 2BHK flats under 80 Lakhs in Whitefield"*).
  - Live Conversation panel is hidden to eliminate visual clutter.
- **After Clicking Start Conversation:**
  - The **same container smoothly expands** into a wide, 2-column layout (`max-w-6xl`):
    - **Left Section (Desktop):** Scrollable **Live Conversation** transcript panel (`lg:col-span-7`).
    - **Right Section (Desktop):** Animated **3D Robot Avatar** with live status badge and controls (`lg:col-span-5`).
  - Maintains responsive ordering on mobile devices (3D avatar on top, Live Conversation below).
- **Status:** **`Implemented & Offline Tested`**

### 3.2 Live Conversation Transcript Panel
- **Speaker Labels:** Clean uppercase badges:
  - **`CUSTOMER`**: Emerald badge (`bg-emerald-600`) with User icon.
  - **`ROBOT`**: Sky-blue badge (`bg-sky-600`) with Bot icon.
- **Message Content:** Spoken utterances formatted in standard sentence case enclosed in double quotation marks (e.g., `“Hello! How can I help you today?”`).
- **Real-Time State Feedback:** When no transcripts exist yet:
  - `connecting`: *"Connecting to Voice AI... Establishing real-time secure audio stream."*
  - `listening`: Pulsing emerald `Microphone Active` badge + *"I'm Listening — Go Ahead and Speak"*.
  - `thinking`: *"Processing Your Request... Searching verified inventory."*
  - `speaking`: *"Advisor is Speaking..."*
- **Transcript Deduplication & Turn Merging:** Streaming speech deltas from the same turn merge cleanly without duplicate speech bubbles or empty entries.
- **Scroll Management:** Smooth auto-scrolling to newest turns with a floating *"Latest messages"* button when user scrolls up.
- **Status:** **`Implemented & Offline Tested`**

### 3.3 Animated 3D Robot Voice Avatar
- **Visual Model:** Full Three.js 3D robot incorporating head, neck, movable mouth, expressive visor eyes, dual arms, and upper body chassis (`RobotAvatar3D.tsx`).
- **Animation States:** Relaxed idle, connecting amber pulse, joyful greeting wave, focused listening with pulsing ears, thoughtful upward tilt for thinking, and real-time audio lip-sync for speech.
- **Accessibility & Fallback:** WebGL capability detection with 2D SVG canvas fallback (`RobotAvatarFallback.tsx`) and `prefers-reduced-motion` compliance.
- **Status:** **`Implemented & Offline Tested`**

---

## 4. Voice Pipeline & Amazon Nova 2.5 Sonic Integration

### 4.1 Voice Architecture
- **Model ID:** `amazon.nova-2-5-sonic` via Amazon Bedrock bidirectional HTTP/2 EventStream transport (`InvokeModelWithBidirectionalStream`).
- **Audio Framing:** Full-duplex WebSocket gateway streaming raw 16-bit linear PCM audio.
  - **Microphone Input:** Client captures 24 kHz audio, converted to 16 kHz mono PCM for Bedrock.
  - **Speaker Playback:** Web Audio API scheduled gapless 24 kHz playback.
- **Turn-Taking & Barge-In:** Real-time acoustic echo suppression during robot speech to avoid false interruptions, coupled with immediate playback queue draining upon customer speech (`interrupt`).
- **Status:** **`Implemented & Offline Tested (Live In-Flight Audio Not Fully Verified)`**

### 4.2 Robot-First vs Customer-First Conversation Flow
1. **Personalized Robot-First Greeting:**
   - **Requirement:** When the customer clicks Start Conversation, the robot speaks first, addressing the customer by name:  
     *"Hello [Customer Name]! Welcome to Brain Magic RealEstate Voice AI. How can I assist you today?"*
   - **Current Technical Reality:** Previous attempts using an `INIT_USER` text block produced AWS Bedrock `modelStreamErrorException: (Last sent event: contentEnd(INIT_USER))`. Subsequent attempts using a 100 ms silent PCM audio trigger failed because Nova Sonic's Voice Activity Detector (VAD) discarded silence, producing zero speech output and leaving the UI stuck on initializing.
   - **Status:** **`PENDING / NOT WORKING` (Requested, but neither functional nor live-verified).**
2. **Current Working Fallback (Customer Speaks First):**
   - **Requirement:** Reliable, proven speech-to-speech conversation where the customer speaks first into the microphone.
   - **Behavior:** Session starts cleanly; Live Conversation displays *"Microphone Active — I'm Listening — Go Ahead and Speak"*; the 3D robot enters listening mode; the model is instructed to greet the customer warmly in its very first spoken response.
   - **Status:** **`Implemented & Offline Tested`**

### 4.3 Ten-Minute Continuous Session & Stream Renewal
- **Session Duration:** 600 seconds (10 minutes) maximum session duration enforced by server-side watchdog timers.
- **Advance Warning:** `session_warning` event dispatched at 30 seconds remaining (9m 30s mark).
- **Stream Renewal:** Amazon Bedrock stream renewed seamlessly at 360 seconds (`AWS_BEDROCK_STREAM_MAX_DURATION_SECONDS`) without disconnecting the customer or losing accumulated requirement context (`SessionState`).
- **Status:** **`Implemented & Offline Tested`**

### 4.4 Bounded Session Initialization & Timeout
- **Timeout Watchdog:** 10-second client-side and 12-second page-level watchdog timers terminate hanging or failed connection attempts.
- **Clean Failure Recovery:** If initialization fails, an alert banner is displayed, resources are torn down cleanly, and the customer is prompted to retry. The interface **never** remains permanently on *"Initializing Conversation..."*.
- **Status:** **`Implemented & Offline Tested`**

---

## 5. Real Estate Domain Capabilities & Inventory Grounding

### 5.1 166 Verified Property Records
- **Data Grounding:** All property inquiries are answered strictly from the active dataset: **`Real Estate Master Portfolio` (Version 1, 166 verified property records in `Unified_AI_Dataset`)**.
- **Anti-Hallucination Guardrail:** The model is strictly forbidden from fabricating property names, prices, locations, or availability. If a requested property or configuration is not in inventory, the advisor explicitly reports zero matches.
- **Status:** **`Implemented & Offline Tested`**

### 5.2 Property Matching & Preference Memory
- **Entity Extraction:** Automatic parsing of configuration (1BHK to 5BHK, duplex, penthouse), location/city, budget bounds (handling Indian numbering: Lakhs, Crores, and global currencies: INR, USD, EUR, AED), amenities, and possession timeline.
- **Multi-Turn Memory:** `SessionState` preserves requirements across turns, allowing the customer to correct or update individual criteria without resetting previous preferences.
- **Intelligent Matcher:** Weighted multi-factor matching engine (layout, budget, city, amenities) with natural language explanations for partial matches.
- **Status:** **`Implemented & Offline Tested`**

### 5.3 Site Visit Scheduling Workflow
- **Slot Discovery:** Checking real-time visit slots within project operating hours (09:00 - 18:00 project local time).
- **Booking & Concurrency Protection:** Booking site visits with PostgreSQL row-level locking (`FOR UPDATE`) to prevent double-booking.
- **Frontend Confirmation:** Dynamic visual booking card presented directly within the customer interface upon successful confirmation.
- **Status:** **`Implemented & Offline Tested`**

---

## 6. Security, Privacy & Data Protection

- **Encrypted Transcripts:** All conversation transcripts are encrypted at rest using AES-256-GCM (`ENCRYPTION_MASTER_KEY`).
- **Data Minimization:** Admin dashboard displays zero audio links and zero decrypted transcripts.
- **Preflight & Cost Controls:**
  - `USE_MOCK_VOICE=True` by default to prevent accidental AWS Bedrock billing during local development.
  - `LIVE_TEST_APPROVED=False` mandatory safety latch preventing unauthorized live inference.
  - `DRY_RUN_TEST_MODE=True` supported for preflight validation without persistent database mutation.
  - Launcher script (`Start_BrainMagic_Voice_AI.bat`) requires explicit interactive confirmation (`[2] LIVE` + `Y/N`) before running paid AWS sessions.
- **Status:** **`Implemented & Offline Tested`**

---

## 7. Requirements Traceability & Verification Status Matrix

| Req # | Requirement Name | Implemented | Offline Tested | Live Verified | Pending Work |
|:---:|---|:---:|:---:|:---:|---|
| **1** | Brain Magic RealEstate Voice AI Branding | **YES** | **YES** | N/A | None. Full visual and label branding verified. |
| **2** | Customer, Admin, Super Owner Roles & RBAC | **YES** | **YES** | N/A | None. Role isolation and token rotation verified. |
| **3** | Single Expanding Customer Dashboard Container | **YES** | **YES** | N/A | None. Responsive container expansion verified. |
| **4** | Animated 3D Robot Centered Before Conversation | **YES** | **YES** | N/A | None. Three.js canvas and fallback verified. |
| **5** | Robot on Right & Live Conversation on Left | **YES** | **YES** | N/A | None. 2-column layout and mobile ordering verified. |
| **6** | Uppercase Labels (`CUSTOMER` / `ROBOT`) & Quotes | **YES** | **YES** | N/A | None. Label styling and quote formatting verified. |
| **7** | Amazon Nova 2.5 Sonic Voice Streaming | **YES** | **YES** | **NO** | Awaiting authorized live AWS Bedrock session. |
| **8** | Smooth Speech & Strict Turn-Taking | **YES** | **YES** | **NO** | Real-world acoustic smoothness requires live verification. |
| **9** | Personalized Robot-First Greeting | **NO** | **NO** | **NO** | **PENDING / NOT WORKING.** Audio/text triggers fail on AWS. |
| **10** | Working Fallback: Customer Speaks First | **YES** | **YES** | N/A | Active working baseline. |
| **11** | Grounding on 166 Verified Property Records | **YES** | **YES** | N/A | Verified on PostgreSQL `Unified_AI_Dataset`. |
| **12** | Preferences, Recommendations & Site Visits | **YES** | **YES** | N/A | Multi-turn state, matching, and booking verified. |
| **13** | 10-Minute Sessions & Stream Renewal | **YES** | **YES** | N/A | Watchdog and renewal logic verified. |
| **14** | Authentication, AES-256-GCM & Audit Logs | **YES** | **YES** | N/A | Full cryptographic security verified. |
| **15** | White & Sky-Blue Website Theme | **YES** | **YES** | N/A | Tailwind palette styling verified across views. |
| **16** | 94 Automated Tests & Live Verification Gap | **YES** | **YES** | **NO** | 94/94 tests pass offline; live AWS run pending. |

---

## 8. Summary of Outstanding Verification

1. **Personalized Robot-First Greeting:**  
   Must be treated as **Pending / Experimental**. The application operates strictly in the verified **Customer Speaks First** microphone-first mode until an AWS-sanctioned speak-first pattern is proven on live Bedrock.
2. **Live Voice Acoustic Smoothness:**  
   Offline timeline scheduling and echo suppression are verified via automated browser tests, but human acoustic assessment over live AWS Bedrock streaming remains outstanding until a controlled live test is authorized.
