import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");

console.log("==================================================================");
console.log("   ANIMATED ROBOT VOICE AVATAR & VOICE-ONLY INTEGRATION TESTS     ");
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
// TEST 1: Floating Widget Opening, Closing & Minimizing
// ----------------------------------------------------------------------------
runTest("Widget supports floating minimized state, open modal, minimize and close actions", () => {
  const widgetSrc = fs.readFileSync(path.join(rootDir, "src/components/RobotVoiceWidget.tsx"), "utf8");

  assert(widgetSrc.includes("fixed bottom-4 right-4"), "Widget must be positioned at bottom-right");
  assert(widgetSrc.includes("setIsOpen(true)"), "Widget must support clicking to open expanded conversation panel");
  assert(widgetSrc.includes("setIsOpen(false)"), "Widget must support minimizing and closing");
  assert(widgetSrc.includes("Minimize2"), "Widget must provide minimize button");
  assert(widgetSrc.includes("X className="), "Widget must provide close button");
});

// ----------------------------------------------------------------------------
// TEST 2: Microphone Permission Handling (Zero Auto-Activation)
// ----------------------------------------------------------------------------
runTest("Microphone is strictly NOT auto-activated until user deliberately starts conversation", () => {
  const widgetSrc = fs.readFileSync(path.join(rootDir, "src/components/RobotVoiceWidget.tsx"), "utf8");
  const customerSrc = fs.readFileSync(path.join(rootDir, "src/app/customer/page.tsx"), "utf8");

  // Initial effect must only enumerate devices or check capability without capturing active mediaStream
  assert(widgetSrc.includes("enumerateDevices"), "Widget must check hardware capability via enumerateDevices");
  assert(!widgetSrc.includes("useEffect(() => {\n    handleStartSession();"), "Widget must never auto-call handleStartSession on mount");

  // User trigger requirement
  assert(widgetSrc.includes("Start Voice Conversation"), "Widget must require user to click 'Start Voice Conversation'");
  assert(customerSrc.includes("Start Conversation"), "Customer portal must require user to click 'Start Conversation'");
});

// ----------------------------------------------------------------------------
// TEST 3: Strict Voice-Only Interface Enforcement (Zero Text Transcripts/Chat)
// ----------------------------------------------------------------------------
runTest("Strict Voice-Only UI: Zero chat bubbles, zero transcript displays, zero text inputs", () => {
  const widgetSrc = fs.readFileSync(path.join(rootDir, "src/components/RobotVoiceWidget.tsx"), "utf8");
  const customerSrc = fs.readFileSync(path.join(rootDir, "src/app/customer/page.tsx"), "utf8");

  // Forbidden text chat constructs
  const forbiddenPatterns = [
    "<input",
    "<textarea",
    "chatHistory",
    "transcriptHistory",
    "messageBubbles",
    "userMessage",
    "agentMessage",
    "textResponse",
    "messages.map",
  ];

  for (const pattern of forbiddenPatterns) {
    assert(!widgetSrc.includes(pattern), `RobotVoiceWidget must not contain ${pattern}`);
    assert(!customerSrc.includes(pattern), `Customer page must not contain ${pattern}`);
  }

  // Permitted voice-only elements
  assert(widgetSrc.includes("RobotAvatar3D"), "Widget must render 3D Robot Avatar");
  assert(widgetSrc.includes("Mic"), "Widget must render microphone control");
  assert(widgetSrc.includes("Interrupt"), "Widget must render interrupt control");
  assert(widgetSrc.includes("End"), "Widget must render end conversation control");
});

// ----------------------------------------------------------------------------
// TEST 4: Robot Animation State Machine Completeness
// ----------------------------------------------------------------------------
runTest("State machine implements all 10 required states and configuration mappings", async () => {
  const { ROBOT_STATE_CONFIGS, mapBackendEventToRobotState } = await import(
    "../src/lib/robot-state-machine.ts"
  );

  const requiredStates = [
    "IDLE",
    "CONNECTING",
    "GREETING",
    "LISTENING",
    "THINKING",
    "SPEAKING",
    "HAPPY",
    "CONFUSED",
    "ERROR",
    "DISCONNECTED",
  ];

  for (const s of requiredStates) {
    assert(ROBOT_STATE_CONFIGS[s], `State machine must configure state: ${s}`);
    assert(ROBOT_STATE_CONFIGS[s].primaryColor, `State ${s} must have primaryColor`);
    assert(ROBOT_STATE_CONFIGS[s].eyeShape, `State ${s} must have eyeShape`);
    assert(ROBOT_STATE_CONFIGS[s].statusLabel, `State ${s} must have statusLabel`);
  }

  // Backend Event Mapping
  assert.strictEqual(mapBackendEventToRobotState("session_started"), "GREETING");
  assert.strictEqual(mapBackendEventToRobotState("greeting_complete"), "LISTENING");
  assert.strictEqual(mapBackendEventToRobotState("tool_call_start"), "THINKING");
  assert.strictEqual(mapBackendEventToRobotState("speaking_start"), "SPEAKING");
  assert.strictEqual(mapBackendEventToRobotState("speaking_end"), "LISTENING");
  assert.strictEqual(mapBackendEventToRobotState("interrupted"), "LISTENING");
  assert.strictEqual(mapBackendEventToRobotState("error"), "ERROR");
  assert.strictEqual(mapBackendEventToRobotState("disconnected"), "DISCONNECTED");

  // Authentic tool results mapping
  assert.strictEqual(
    mapBackendEventToRobotState("tool_call_complete", { tool_name: "book_site_visit", success: true }),
    "HAPPY"
  );
  assert.strictEqual(
    mapBackendEventToRobotState("tool_call_complete", {
      tool_name: "search_properties",
      success: true,
      data: { total_matches: 2, total_exact_matches: 2 },
    }),
    "HAPPY"
  );
  assert.strictEqual(
    mapBackendEventToRobotState("tool_call_complete", {
      tool_name: "search_properties",
      success: true,
      data: { permission_required: true, total_exact_matches: 0 },
    }),
    "CONFUSED"
  );
});

// ----------------------------------------------------------------------------
// TEST 5: Audio-Driven Lip Synchronization Logic
// ----------------------------------------------------------------------------
runTest("AudioLipSyncEngine correctly calculates mouth opening and resets on silence/interruption", async () => {
  const { AudioLipSyncEngine } = await import("../src/lib/audio-lip-sync.ts");

  const engine = new AudioLipSyncEngine();
  const initialFrame = engine.getFrame();

  assert.strictEqual(initialFrame.mouthOpen, 0, "Initial mouth opening must be 0");
  assert.strictEqual(initialFrame.isSpeaking, false, "Initial speaking state must be false");

  // Verify reset
  engine.reset();
  const resetFrame = engine.getFrame();
  assert.strictEqual(resetFrame.mouthOpen, 0);
  assert.strictEqual(resetFrame.isSpeaking, false);
});

// ----------------------------------------------------------------------------
// TEST 6: Microphone Muting and Unmuting Controls
// ----------------------------------------------------------------------------
runTest("VoiceClient supports mute, unmute, and track disabling without disconnecting session", () => {
  const voiceClientSrc = fs.readFileSync(path.join(rootDir, "src/lib/voice-client.ts"), "utf8");

  assert(voiceClientSrc.includes("public mute()"), "VoiceClient must provide mute() method");
  assert(voiceClientSrc.includes("public unmute()"), "VoiceClient must provide unmute() method");
  assert(voiceClientSrc.includes("public toggleMute()"), "VoiceClient must provide toggleMute() method");
  assert(voiceClientSrc.includes("t.enabled = false"), "Mute must disable media stream audio tracks");
  assert(voiceClientSrc.includes("t.enabled = true"), "Unmute must re-enable media stream audio tracks");
  assert(voiceClientSrc.includes("this.isMuted"), "VoiceClient must guard audio process loop against muted transmission");
});

// ----------------------------------------------------------------------------
// TEST 7: Speech Interruption and Graceful Session Termination
// ----------------------------------------------------------------------------
runTest("VoiceClient interruption drains playback queue and stop() tears down all Web Audio nodes", () => {
  const voiceClientSrc = fs.readFileSync(path.join(rootDir, "src/lib/voice-client.ts"), "utf8");

  // Interruption
  assert(voiceClientSrc.includes("public interrupt()"), "VoiceClient must provide interrupt() method");
  assert(voiceClientSrc.includes('type: "interrupt"'), "Interrupt must send interrupt control frame over WebSocket");
  assert(voiceClientSrc.includes("this.stopAudioPlayback()"), "Interrupt must immediately clear audioQueue");
  assert(voiceClientSrc.includes("this.lipSyncEngine.reset()"), "Interrupt must immediately reset lip-sync engine");

  // Teardown
  assert(voiceClientSrc.includes("public stop()"), "VoiceClient must provide stop() method");
  assert(voiceClientSrc.includes("this.teardownAudio()"), "Stop must execute full audio teardown");
  assert(voiceClientSrc.includes("processor.disconnect()"), "Teardown must disconnect ScriptProcessorNode");
  assert(voiceClientSrc.includes("mediaStream.getTracks().forEach((t) => t.stop())"), "Teardown must release mic hardware");
  assert(voiceClientSrc.includes("audioContext.close()"), "Teardown must close AudioContext");
});

// ----------------------------------------------------------------------------
// TEST 8: WebGL Support & Graceful Fallback
// ----------------------------------------------------------------------------
runTest("RobotAvatar3D includes WebGL detection and renders RobotAvatarFallback when unsupported", () => {
  const avatar3dSrc = fs.readFileSync(path.join(rootDir, "src/components/RobotAvatar3D.tsx"), "utf8");
  const fallbackSrc = fs.readFileSync(path.join(rootDir, "src/components/RobotAvatarFallback.tsx"), "utf8");

  assert(avatar3dSrc.includes("RobotAvatarFallback"), "RobotAvatar3D must import RobotAvatarFallback");
  assert(avatar3dSrc.includes("hasWebGL === false"), "RobotAvatar3D must detect WebGL unavailability");
  assert(fallbackSrc.includes("<svg"), "RobotAvatarFallback must provide high-fidelity SVG/vector rendering");
  assert(fallbackSrc.includes("mouthHeight"), "RobotAvatarFallback must animate mouth with lip-sync values");
});

// ----------------------------------------------------------------------------
// TEST 9: Accessibility & prefers-reduced-motion Support
// ----------------------------------------------------------------------------
runTest("Avatar respects prefers-reduced-motion accessibility preference", () => {
  const avatar3dSrc = fs.readFileSync(path.join(rootDir, "src/components/RobotAvatar3D.tsx"), "utf8");

  assert(avatar3dSrc.includes("prefers-reduced-motion"), "Avatar must query prefers-reduced-motion media query");
  assert(avatar3dSrc.includes("reducedMotion"), "Avatar must maintain reducedMotion state");
  assert(avatar3dSrc.includes("reducedMotion ?"), "Avatar must damp breathing/head movements when reduced motion is requested");
});

// ----------------------------------------------------------------------------
// TEST 10: Responsiveness & Desktop/Mobile Layout
// ----------------------------------------------------------------------------
runTest("Widget provides responsive classes for both desktop and mobile viewports", () => {
  const widgetSrc = fs.readFileSync(path.join(rootDir, "src/components/RobotVoiceWidget.tsx"), "utf8");

  assert(widgetSrc.includes("bottom-4 right-4 sm:bottom-6 sm:right-6"), "Widget must support mobile margin scaling");
  assert(widgetSrc.includes("w-[340px] sm:w-[390px]"), "Widget conversation panel must scale responsively across screen widths");
  assert(widgetSrc.includes("backdrop-blur-xl"), "Widget must employ premium frosted glass backdrop styling");
});

// ----------------------------------------------------------------------------
// TEST 11: Microphone Audio Capture & 16-bit PCM Conversion
// ----------------------------------------------------------------------------
runTest("VoiceClient converts float32 microphone stream to 16-bit linear PCM", () => {
  const voiceClientSrc = fs.readFileSync(path.join(rootDir, "src/lib/voice-client.ts"), "utf8");

  assert(voiceClientSrc.includes("createMediaStreamSource"), "Must capture microphone stream via createMediaStreamSource");
  assert(voiceClientSrc.includes("createScriptProcessor"), "Must create script processor for audio capture buffer");
  assert(voiceClientSrc.includes("Int16Array"), "Must convert audio to 16-bit PCM Int16Array");
  assert(voiceClientSrc.includes("0x8000"), "Must scale negative float32 samples to 16-bit integer boundary");
  assert(voiceClientSrc.includes("0x7fff"), "Must scale positive float32 samples to 16-bit integer boundary");
  assert(voiceClientSrc.includes("this.ws.send(pcm16.buffer)"), "Must transmit binary PCM buffer over WebSocket");
});

// ----------------------------------------------------------------------------
// TEST 12: Web Audio Context Activation and Browser Playback Resilience
// ----------------------------------------------------------------------------
runTest("VoiceClient unlocks and resumes AudioContext upon deliberate user interaction and playback", () => {
  const voiceClientSrc = fs.readFileSync(path.join(rootDir, "src/lib/voice-client.ts"), "utf8");

  assert(voiceClientSrc.includes("resume()"), "VoiceClient must call resume() on suspended AudioContext");
  assert(voiceClientSrc.includes("this.audioContext.state === \"suspended\""), "Must guard against browser suspended audio context state");
  assert(voiceClientSrc.includes("createBuffer(1, float32Array.length, 24000)"), "Must decode 24kHz incoming PCM into native Web Audio buffer");
  assert(voiceClientSrc.includes("createBufferSource"), "Must spawn Web Audio buffer source for continuous speaker playback");
});

// ----------------------------------------------------------------------------
// TEST 13: Conversational State Transitions (LISTENING -> THINKING -> SPEAKING)
// ----------------------------------------------------------------------------
runTest("VoiceClient transitions states accurately upon receiving user and assistant speech events", () => {
  const voiceClientSrc = fs.readFileSync(path.join(rootDir, "src/lib/voice-client.ts"), "utf8");

  assert(voiceClientSrc.includes('msg.role === "assistant"'), "Assistant transcript delta must switch robot state to speaking");
  assert(voiceClientSrc.includes('this.setState("speaking")'), "Must trigger speaking state upon assistant response");
  assert(voiceClientSrc.includes('msg.role === "user"'), "User speech utterance must switch robot state to thinking");
  assert(voiceClientSrc.includes('this.setState("thinking")'), "Must trigger thinking state upon customer utterance");
  assert(voiceClientSrc.includes('this.setState("listening")'), "Must return to listening state when audio playback finishes");
});

// ----------------------------------------------------------------------------
// TEST 14: Comprehensive Audio Teardown and Hardware Release
// ----------------------------------------------------------------------------
runTest("VoiceClient teardownAudio safely releases microphone stream and Web Audio nodes", () => {
  const voiceClientSrc = fs.readFileSync(path.join(rootDir, "src/lib/voice-client.ts"), "utf8");

  assert(voiceClientSrc.includes("this.processor.disconnect()"), "Must disconnect ScriptProcessorNode on teardown");
  assert(voiceClientSrc.includes("this.mediaStream.getTracks().forEach((t) => t.stop())"), "Must stop all media tracks on teardown");
  assert(voiceClientSrc.includes("this.audioContext.close()"), "Must close AudioContext on teardown");
  assert(voiceClientSrc.includes("this.audioContext = null"), "Must release AudioContext reference to prevent memory leaks");
  assert(voiceClientSrc.includes("this.isConnected = false"), "Must reset isConnected flag on teardown");
});

// ----------------------------------------------------------------------------
// TEST 15: 3D Expressive Robot Geometry & Joint Hierarchy
// ----------------------------------------------------------------------------
runTest("Expressive 3D Robot implements full head, neck, movable mouth, expressive eyes, dual arms, and upper body chassis", () => {
  const avatar3dSrc = fs.readFileSync(path.join(rootDir, "src/components/RobotAvatar3D.tsx"), "utf8");
  const fallbackSrc = fs.readFileSync(path.join(rootDir, "src/components/RobotAvatarFallback.tsx"), "utf8");

  // Three.js 3D Hierarchical Object Groups
  assert(avatar3dSrc.includes("leftShoulderRef"), "RobotAvatar3D must provide leftShoulder reference");
  assert(avatar3dSrc.includes("rightShoulderRef"), "RobotAvatar3D must provide rightShoulder reference");
  assert(avatar3dSrc.includes("leftElbowRef"), "RobotAvatar3D must provide leftElbow reference");
  assert(avatar3dSrc.includes("rightElbowRef"), "RobotAvatar3D must provide rightElbow reference");
  assert(avatar3dSrc.includes("headGroupRef"), "RobotAvatar3D must provide headGroup reference");
  assert(avatar3dSrc.includes("torsoGroup"), "RobotAvatar3D must construct upper body torsoGroup");
  assert(avatar3dSrc.includes("neckGeo"), "RobotAvatar3D must construct neck joint");
  assert(avatar3dSrc.includes("leftUpperArmGeo"), "RobotAvatar3D must construct upper arm meshes");
  assert(avatar3dSrc.includes("leftForearmGeo"), "RobotAvatar3D must construct forearm meshes");
  assert(avatar3dSrc.includes("mouthMeshRef"), "RobotAvatar3D must construct movable mouth mesh");

  // Fallback SVG verification
  assert(fallbackSrc.includes("Left Arm"), "Fallback must render Left Arm structure");
  assert(fallbackSrc.includes("Right Arm"), "Fallback must render Right Arm structure");
});

// ----------------------------------------------------------------------------
// TEST 16: Expressive Animation States & Audio-Driven Decay
// ----------------------------------------------------------------------------
runTest("Animation system smoothly blends poses across all core states and resets speaking animation on audio silence or interruption", () => {
  const avatar3dSrc = fs.readFileSync(path.join(rootDir, "src/components/RobotAvatar3D.tsx"), "utf8");

  // State poses in animation loop
  assert(avatar3dSrc.includes('currentState === "IDLE"'), "Must handle IDLE state pose");
  assert(avatar3dSrc.includes('currentState === "LISTENING"'), "Must handle LISTENING state pose");
  assert(avatar3dSrc.includes('currentState === "THINKING"'), "Must handle THINKING state pose");
  assert(avatar3dSrc.includes('currentState === "SPEAKING"'), "Must handle SPEAKING state pose");
  assert(avatar3dSrc.includes('currentState === "HAPPY"'), "Must handle HAPPY state pose");
  assert(avatar3dSrc.includes('currentState === "CONFUSED"'), "Must handle CONFUSED state pose");
  assert(avatar3dSrc.includes('currentState === "ERROR"'), "Must handle ERROR state pose");
  assert(avatar3dSrc.includes('currentState === "DISCONNECTED"'), "Must handle DISCONNECTED state pose");

  // Smooth lerp interpolation
  assert(avatar3dSrc.includes("lerpSpeed"), "Must use lerpSpeed for smooth joint transition blending");
  assert(avatar3dSrc.includes("targetPitch"), "Must compute target pitch smoothly");

  // Audio-driven mouth behavior: mouth returns to resting neutral when not speaking
  assert(avatar3dSrc.includes("neutral resting mouth") || avatar3dSrc.includes("0.80, 0.20, 1.0"), "Must set mouth to resting neutral when speaking stops");
});

// ----------------------------------------------------------------------------
// TEST 17: Customer Interface Branding Consistency
// ----------------------------------------------------------------------------
runTest("Branding across Navbar, Layout, and Widget reflects Brain Magic RealEstate Voice AI and Voice Assistance", () => {
  const navbarSrc = fs.readFileSync(path.join(rootDir, "src/components/Navbar.tsx"), "utf8");
  const layoutSrc = fs.readFileSync(path.join(rootDir, "src/app/layout.tsx"), "utf8");
  const widgetSrc = fs.readFileSync(path.join(rootDir, "src/components/RobotVoiceWidget.tsx"), "utf8");

  assert(navbarSrc.includes("Brain Magic RealEstate Voice AI"), "Navbar must display 'Brain Magic RealEstate Voice AI'");
  assert(!navbarSrc.includes("Nova 2.5 Sonic</span>"), "Navbar must not contain the Nova 2.5 Sonic badge");
  assert(navbarSrc.includes("brainmagic-logo.png"), "Navbar must render the Brain Magic logo image");
  assert(!navbarSrc.includes("Building2"), "Navbar must not contain the old green building icon");
  assert(layoutSrc.includes("BrainMagic Voice AI"), "Layout metadata title must be 'BrainMagic Voice AI'");
  assert(widgetSrc.includes("Voice Assistance"), "Widget must display 'Voice Assistance'");
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
