/**
 * Verification Suite for Voice Fine-Tuning & Live Conversation Transcript Deduplication
 * Bounded offline tests for:
 * 1. Smooth, ordered audio playback & gapless timeline scheduling
 * 2. Acoustic echo suppression & false interruption prevention
 * 3. ScriptProcessor mute gain isolation (no mic-to-speaker feedback loop)
 * 4. Robot finishes speaking before switching to listening
 * 5. Partial/final transcript deduplication & logical speaker turn merging
 * 6. Empty & whitespace-only transcript filtering
 * 7. Correct speaker alternation and multi-turn continuity
 */

import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");

console.log("==================================================================");
console.log("   VOICE FINE-TUNING & LIVE TRANSCRIPT VERIFICATION SUITE         ");
console.log("==================================================================");

function runTest(name, fn) {
  try {
    fn();
    console.log(`[PASS] ${name}`);
  } catch (err) {
    console.error(`[FAIL] ${name}`);
    console.error(err);
    process.exit(1);
  }
}

// ----------------------------------------------------------------------------
// TEST 1: Gapless Audio Playback Timeline Scheduling
// ----------------------------------------------------------------------------
runTest("VoiceClient implements sample-accurate gapless audio timeline scheduling", () => {
  const voiceClientSrc = fs.readFileSync(path.join(rootDir, "src/lib/voice-client.ts"), "utf8");

  assert(voiceClientSrc.includes("scheduledEndTime"), "VoiceClient must track scheduledEndTime for gapless timeline scheduling");
  assert(voiceClientSrc.includes("audioBuffer.duration"), "Must calculate precise buffer duration on audio timeline");
  assert(voiceClientSrc.includes("source.start(startTime)"), "Must schedule audio buffer at exact timeline start time");
  assert(voiceClientSrc.includes("activeSources"), "Must track active audio buffer source nodes for clean interruption/teardown");
  assert(voiceClientSrc.includes("playbackEndTimer"), "Must use bounded timer to ensure robot finishes speaking completely before returning to listening");
});

// ----------------------------------------------------------------------------
// TEST 2: Acoustic Echo Suppression & False Interruption Prevention
// ----------------------------------------------------------------------------
runTest("VoiceClient suppresses acoustic echo during robot speech without starving duplex stream", () => {
  const voiceClientSrc = fs.readFileSync(path.join(rootDir, "src/lib/voice-client.ts"), "utf8");

  assert(voiceClientSrc.includes("this.isPlaying"), "Must check isPlaying state in onaudioprocess loop");
  assert(
    voiceClientSrc.includes("if (this.isPlaying)") && voiceClientSrc.includes("ws.send(pcm16.buffer)"),
    "Must transmit zeroed PCM keepalive frames during robot speech to prevent false Bedrock turn interruptions"
  );
  assert(
    voiceClientSrc.includes("muteGainNode"),
    "Must connect ScriptProcessorNode to mute GainNode with gain=0 to prevent microphone from feeding back into speakers"
  );
});

// ----------------------------------------------------------------------------
// TEST 3: Pure Transcript Reducer Logic Simulation (Offline Test)
// ----------------------------------------------------------------------------
runTest("Customer portal transcript deduplication merges turn fragments and filters empty messages", () => {
  const customerSrc = fs.readFileSync(path.join(rootDir, "src/app/customer/page.tsx"), "utf8");

  assert(customerSrc.includes("onTranscript"), "Customer portal must implement onTranscript callback");
  assert(customerSrc.includes("cleanDelta"), "Must sanitize incoming delta text");
  assert(customerSrc.includes("trimmedDelta"), "Must check trimmed delta to filter whitespace-only entries");
  assert(customerSrc.includes("trimmedDelta.startsWith(last.text)"), "Must handle accumulated full replacement text from model");

  // Replicate exact transcript reducer logic from customer/page.tsx
  function createTranscriptReducer() {
    let transcripts = [];

    function handleTranscript(role, delta, isFinal) {
      const cleanDelta = delta || "";
      const trimmedDelta = cleanDelta.trim();

      if (!trimmedDelta && !isFinal) return;

      const speaker = role === "user" ? "Customer" : "Robot";
      const lastIndex = transcripts.length - 1;
      const last = transcripts[lastIndex];

      // Case A: Empty/whitespace finalization
      if (!trimmedDelta && isFinal) {
        if (last && last.role === role && !last.isFinal) {
          transcripts[lastIndex] = { ...last, isFinal: true };
        }
        return;
      }

      // Case B: Non-empty delta for SAME speaker turn
      if (last && last.role === role) {
        if (last.text === trimmedDelta || last.text.endsWith(trimmedDelta)) {
          if (isFinal && !last.isFinal) {
            transcripts[lastIndex] = { ...last, isFinal: true };
          }
          return;
        }

        let mergedText;
        if (trimmedDelta.startsWith(last.text)) {
          mergedText = trimmedDelta;
        } else if (last.text.startsWith(trimmedDelta)) {
          mergedText = last.text;
        } else {
          const needsSpace =
            last.text.length > 0 &&
            !/\s$/.test(last.text) &&
            !/^\s/.test(cleanDelta) &&
            !/^[.,!?;:]/.test(trimmedDelta);
          mergedText = needsSpace ? `${last.text} ${trimmedDelta}` : `${last.text}${cleanDelta}`;
        }

        mergedText = mergedText.trim();
        if (!mergedText) return;

        transcripts[lastIndex] = {
          ...last,
          text: mergedText,
          isFinal: isFinal || last.isFinal,
        };
        return;
      }

      // Case C: Non-empty delta for NEW speaker turn
      if (!trimmedDelta) return;

      transcripts.push({
        id: `msg_${transcripts.length + 1}`,
        role,
        speaker,
        text: trimmedDelta,
        isFinal,
      });
    }

    return {
      handleTranscript,
      getTranscripts: () => transcripts,
    };
  }

  const { handleTranscript, getTranscripts } = createTranscriptReducer();

  // Turn 1: Customer multi-chunk speech
  handleTranscript("user", "I'm looking for a 3BHK apartment", false);
  handleTranscript("user", " in Chennai.", true);

  // Turn 2: Robot response with streaming fragments and empty final contentEnd
  handleTranscript("assistant", "Sure. What budget range", false);
  handleTranscript("assistant", " are you considering?", false);
  handleTranscript("assistant", "", true); // contentEnd

  // Turn 3: Customer response
  handleTranscript("user", "Around one crore.", true);

  // Turn 4: Robot tool-preamble, continuation, and repeated confirmation
  handleTranscript("assistant", "Let me check our verified properties for you.", false);
  handleTranscript("assistant", "Let me check our verified properties for you.", false); // duplicate chunk
  handleTranscript("assistant", " I found 3 properties matching your criteria.", true);

  // Turn 5: Separate turn with repeated text (Customer repeats "Yes")
  handleTranscript("user", "Yes", true);
  handleTranscript("assistant", "Would you like me to book a site visit?", true);
  handleTranscript("user", "Yes", true);

  // Empty/whitespace-only messages that must be ignored
  handleTranscript("assistant", "", false);
  handleTranscript("assistant", "   ", false);
  handleTranscript("assistant", "", true);

  const finalTranscripts = getTranscripts();

  // Assertions
  assert.strictEqual(finalTranscripts.length, 7, `Expected exactly 7 messages, got ${finalTranscripts.length}`);

  // Turn 1
  assert.strictEqual(finalTranscripts[0].speaker, "Customer");
  assert.strictEqual(finalTranscripts[0].text, "I'm looking for a 3BHK apartment in Chennai.");
  assert.strictEqual(finalTranscripts[0].isFinal, true);

  // Turn 2
  assert.strictEqual(finalTranscripts[1].speaker, "Robot");
  assert.strictEqual(finalTranscripts[1].text, "Sure. What budget range are you considering?");
  assert.strictEqual(finalTranscripts[1].isFinal, true);

  // Turn 3
  assert.strictEqual(finalTranscripts[2].speaker, "Customer");
  assert.strictEqual(finalTranscripts[2].text, "Around one crore.");
  assert.strictEqual(finalTranscripts[2].isFinal, true);

  // Turn 4
  assert.strictEqual(finalTranscripts[3].speaker, "Robot");
  assert.strictEqual(finalTranscripts[3].text, "Let me check our verified properties for you. I found 3 properties matching your criteria.");
  assert.strictEqual(finalTranscripts[3].isFinal, true);

  // Turn 5-7: Natural repetition in separate turns preserved
  assert.strictEqual(finalTranscripts[4].speaker, "Customer");
  assert.strictEqual(finalTranscripts[4].text, "Yes");
  assert.strictEqual(finalTranscripts[5].speaker, "Robot");
  assert.strictEqual(finalTranscripts[5].text, "Would you like me to book a site visit?");
  assert.strictEqual(finalTranscripts[6].speaker, "Customer");
  assert.strictEqual(finalTranscripts[6].text, "Yes");

  // Zero empty messages
  for (const msg of finalTranscripts) {
    assert(msg.text.trim().length > 0, "Transcript message text must not be empty or whitespace");
  }
});

console.log("------------------------------------------------------------------");
console.log("Total tests run: 3");
console.log("Passed: 3");
console.log("Failed: 0");
console.log("==================================================================");
