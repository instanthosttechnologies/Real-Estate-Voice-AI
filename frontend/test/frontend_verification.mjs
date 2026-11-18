import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");

console.log("==================================================================");
console.log("   PHASE 5 FRONTEND ARCHITECTURE & SECURITY VERIFICATION SUITE   ");
console.log("==================================================================");

let testsPassed = 0;
let testsFailed = 0;

function runTest(name, fn) {
  try {
    fn();
    console.log(`[PASS] ${name}`);
    testsPassed++;
  } catch (err) {
    console.error(`[FAIL] ${name}`);
    console.error(`       Error: ${err.message}`);
    testsFailed++;
  }
}

// ----------------------------------------------------------------------------
// TEST 1: Password Complexity Enforcement (Argon2id Compatibility)
// ----------------------------------------------------------------------------
runTest("Registration password rules match backend Argon2id complexity requirements", () => {
  const registerSrc = fs.readFileSync(path.join(rootDir, "src/app/register/page.tsx"), "utf8");

  assert(registerSrc.includes("password.length >= 8"), "Must require minimum 8 characters");
  assert(registerSrc.includes("/[A-Z]/.test(password)"), "Must require uppercase letter");
  assert(registerSrc.includes("/[a-z]/.test(password)"), "Must require lowercase letter");
  assert(registerSrc.includes("/\\d/.test(password)") || registerSrc.includes("/[0-9]/.test(password)"), "Must require number");
  assert(registerSrc.includes("special:"), "Must require special character");
});

// ----------------------------------------------------------------------------
// TEST 2: WebSocket Initial Authentication Handshake (Zero Query-String Tokens)
// ----------------------------------------------------------------------------
runTest("WebSocket client uses explicit JSON auth handshake and no query-string token", () => {
  const voiceClientSrc = fs.readFileSync(path.join(rootDir, "src/lib/voice-client.ts"), "utf8");

  // Verify that the WebSocket connection URL does NOT contain query params with token
  assert(!voiceClientSrc.includes("?token="), "WebSocket connection URL must not use ?token= query parameter");
  assert(!voiceClientSrc.includes("&token="), "WebSocket connection URL must not use &token= query parameter");

  // Verify that onopen sends the initial json auth message
  assert(voiceClientSrc.includes('type: "auth"'), "VoiceClient must send initial auth message with type 'auth'");
  assert(voiceClientSrc.includes("token: this.accessToken"), "VoiceClient must send accessToken in auth payload");
});

// ----------------------------------------------------------------------------
// TEST 3: Customer Portal Voice-First Privacy (Zero Chat History / Transcripts)
// ----------------------------------------------------------------------------
runTest("Customer portal displays strictly NO chat transcript, chat history, or text messages", () => {
  const customerSrc = fs.readFileSync(path.join(rootDir, "src/app/customer/page.tsx"), "utf8");

  // Ensure no chat history UI components or state exists
  assert(!customerSrc.includes("chatHistory"), "Customer portal must not track chatHistory");
  assert(!customerSrc.includes("transcriptHistory"), "Customer portal must not display transcriptHistory");
  assert(!customerSrc.includes("userMessage"), "Customer portal must not render user text messages");
  assert(!customerSrc.includes("agentMessage"), "Customer portal must not render agent text messages");

  // Must have microphone & voice controls
  assert(customerSrc.includes("VoiceOrb"), "Customer portal must feature VoiceOrb audio visualizer");
  assert(customerSrc.includes("handleStartSession"), "Customer portal must provide conversation start trigger");
  assert(customerSrc.includes("handleStopSession"), "Customer portal must provide conversation stop trigger");
  assert(customerSrc.includes("handleInterrupt"), "Customer portal must provide voice interruption control");
  assert(customerSrc.includes("Site Visit Confirmed"), "Customer portal must support dynamic site visit confirmation card");
});

// ----------------------------------------------------------------------------
// TEST 4: Admin Dashboard Zero-Leakage (Zero Transcript & Zero Audio Access)
// ----------------------------------------------------------------------------
runTest("Admin Dashboard interface contains strictly NO transcript or audio access", () => {
  const adminSrc = fs.readFileSync(path.join(rootDir, "src/app/admin/page.tsx"), "utf8");

  assert(!adminSrc.includes("encrypted_transcript"), "Admin dashboard must not reference encrypted_transcript");
  assert(!adminSrc.includes("decrypted_transcript"), "Admin dashboard must not reference decrypted_transcript");
  assert(!adminSrc.includes("audio_storage_path"), "Admin dashboard must not reference audio_storage_path");
  assert(!adminSrc.includes("audio_stream_url"), "Admin dashboard must not reference audio_stream_url");
  assert(!adminSrc.includes("<audio"), "Admin dashboard must not include audio elements");

  // Verify lead priority ordering
  assert(adminSrc.includes("Urgent → High → Medium → Low"), "Admin UI must display priority order Urgent → High → Medium → Low");
});

// ----------------------------------------------------------------------------
// TEST 5: Super Owner Audited Access & Dynamic Ingestion Suite
// ----------------------------------------------------------------------------
runTest("Super Owner console implements audited transcript/audio access and dynamic ingestion", () => {
  const superOwnerSrc = fs.readFileSync(path.join(rootDir, "src/app/super-owner/page.tsx"), "utf8");

  // Ingestion suite
  assert(superOwnerSrc.includes("previewIngestion"), "Super Owner must support previewIngestion");
  assert(superOwnerSrc.includes("executeIngestion"), "Super Owner must support executeIngestion");
  assert(superOwnerSrc.includes("rollbackIngestion"), "Super Owner must support rollbackIngestion");
  assert(superOwnerSrc.includes("conflictStrategy"), "Super Owner must support conflict strategy selection");
  assert(superOwnerSrc.includes("CANONICAL_TARGET_FIELDS"), "Super Owner must support canonical field mapping proposals");

  // Audited access controls
  assert(superOwnerSrc.includes("confirmAuditModal"), "Super Owner must require explicit modal confirmation before accessing transcript/audio");
  assert(superOwnerSrc.includes("Mandatory Audited Security Perimeter"), "Super Owner must show prominent security audit warning");
  assert(superOwnerSrc.includes("api.superOwner.getAuditLogs"), "Super Owner must provide system audit log inspection");
});

// ----------------------------------------------------------------------------
// TEST 6: Centralized API Client Token Rotation & Security Headers
// ----------------------------------------------------------------------------
runTest("API client implements JWT storage, automatic refresh rotation, and Bearer authorization", () => {
  const apiSrc = fs.readFileSync(path.join(rootDir, "src/lib/api.ts"), "utf8");

  assert(apiSrc.includes("Bearer"), "API client must send Bearer authorization header");
  assert(apiSrc.includes("/auth/refresh"), "API client must rotate tokens via /auth/refresh on 401");
  assert(apiSrc.includes("clearStoredSession"), "API client must clear credentials on logout or refresh expiration");
});

console.log("------------------------------------------------------------------");
console.log(`Total tests run: ${testsPassed + testsFailed}`);
console.log(`Passed: ${testsPassed}`);
console.log(`Failed: ${testsFailed}`);
console.log("==================================================================");

if (testsFailed > 0) {
  process.exit(1);
} else {
  process.exit(0);
}
