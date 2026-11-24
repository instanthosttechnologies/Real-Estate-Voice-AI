/**
 * Robot Animation State Machine for Real Estate Voice AI Avatar.
 * 
 * States:
 * - IDLE: Relaxed floating/breathing, natural blinking, gentle head drift.
 * - CONNECTING: Active handshaking, scanning eye visor, amber pulse.
 * - GREETING: Warm welcoming smile, head nod, joyful greeting wave.
 * - LISTENING: Attentive forward tilt, green pulsing ear/sensor lights, active focus.
 * - THINKING: Head tilted upward, processing visor sweep, indigo antenna pulse.
 * - SPEAKING: Vocal rhythm head motion, real-time lip sync mouth movements.
 * - HAPPY: Joyful bounce, inverted-crescent smiling eyes (^_^), emerald celebration.
 * - CONFUSED: Thoughtful head tilt, questioning expression (o_O), soft amber glow.
 * - ERROR: Concerned expression, red warning glow, alert visor.
 * - DISCONNECTED: Eyes dimmed, head lowered into resting pose.
 */

export type RobotState =
  | "IDLE"
  | "CONNECTING"
  | "GREETING"
  | "LISTENING"
  | "THINKING"
  | "SPEAKING"
  | "HAPPY"
  | "CONFUSED"
  | "ERROR"
  | "DISCONNECTED";

export interface RobotReactionConfig {
  state: RobotState;
  primaryColor: string;
  glowColor: string;
  eyeShape: "normal" | "blink" | "happy" | "confused" | "focused" | "closed";
  headTiltX: number; // Pitch: Look up / down
  headTiltY: number; // Yaw: Look left / right
  headTiltZ: number; // Roll: Side tilt
  floatingSpeed: number;
  breathingAmplitude: number;
  antennaPulseSpeed: number;
  statusLabel: string;
}

export const ROBOT_STATE_CONFIGS: Record<RobotState, RobotReactionConfig> = {
  IDLE: {
    state: "IDLE",
    primaryColor: "#38BDF8", // Sky blue
    glowColor: "rgba(56, 189, 248, 0.4)",
    eyeShape: "normal",
    headTiltX: 0,
    headTiltY: 0,
    headTiltZ: 0,
    floatingSpeed: 1.0,
    breathingAmplitude: 0.05,
    antennaPulseSpeed: 1.0,
    statusLabel: "Standing By",
  },
  CONNECTING: {
    state: "CONNECTING",
    primaryColor: "#f59e0b", // Amber
    glowColor: "rgba(245, 158, 11, 0.5)",
    eyeShape: "focused",
    headTiltX: 0.05,
    headTiltY: 0,
    headTiltZ: 0,
    floatingSpeed: 1.5,
    breathingAmplitude: 0.08,
    antennaPulseSpeed: 3.0,
    statusLabel: "Connecting...",
  },
  GREETING: {
    state: "GREETING",
    primaryColor: "#38BDF8", // Sky blue
    glowColor: "rgba(14, 165, 233, 0.6)",
    eyeShape: "happy",
    headTiltX: -0.05,
    headTiltY: 0.05,
    headTiltZ: -0.05,
    floatingSpeed: 2.0,
    breathingAmplitude: 0.1,
    antennaPulseSpeed: 2.0,
    statusLabel: "Hello! Welcome",
  },
  LISTENING: {
    state: "LISTENING",
    primaryColor: "#38BDF8", // Sky blue listening glow
    glowColor: "rgba(56, 189, 248, 0.6)",
    eyeShape: "focused",
    headTiltX: 0.08,
    headTiltY: 0,
    headTiltZ: 0,
    floatingSpeed: 1.2,
    breathingAmplitude: 0.06,
    antennaPulseSpeed: 1.5,
    statusLabel: "Listening...",
  },
  THINKING: {
    state: "THINKING",
    primaryColor: "#38BDF8", // Soft blue thinking pulse
    glowColor: "rgba(56, 189, 248, 0.6)",
    eyeShape: "focused",
    headTiltX: -0.15, // Looking slightly up in thought
    headTiltY: 0.1,
    headTiltZ: 0.05,
    floatingSpeed: 0.8,
    breathingAmplitude: 0.04,
    antennaPulseSpeed: 4.0,
    statusLabel: "Searching & Verifying...",
  },
  SPEAKING: {
    state: "SPEAKING",
    primaryColor: "#0ea5e9", // Glowing blue speaking
    glowColor: "rgba(14, 165, 233, 0.7)",
    eyeShape: "normal",
    headTiltX: 0.02,
    headTiltY: 0,
    headTiltZ: 0,
    floatingSpeed: 1.8,
    breathingAmplitude: 0.08,
    antennaPulseSpeed: 2.5,
    statusLabel: "Speaking...",
  },
  HAPPY: {
    state: "HAPPY",
    primaryColor: "#38BDF8", // Sky blue celebration
    glowColor: "rgba(14, 165, 233, 0.7)",
    eyeShape: "happy",
    headTiltX: -0.08,
    headTiltY: 0,
    headTiltZ: 0.08,
    floatingSpeed: 3.0,
    breathingAmplitude: 0.15,
    antennaPulseSpeed: 3.5,
    statusLabel: "Great Match Found!",
  },
  CONFUSED: {
    state: "CONFUSED",
    primaryColor: "#38BDF8", // Sky blue
    glowColor: "rgba(56, 189, 248, 0.5)",
    eyeShape: "confused",
    headTiltX: 0.05,
    headTiltY: -0.15,
    headTiltZ: 0.2, // Puzzled side tilt
    floatingSpeed: 0.8,
    breathingAmplitude: 0.05,
    antennaPulseSpeed: 1.2,
    statusLabel: "Checking Alternatives...",
  },
  ERROR: {
    state: "ERROR",
    primaryColor: "#ef4444", // Rose
    glowColor: "rgba(239, 68, 68, 0.6)",
    eyeShape: "closed",
    headTiltX: 0.15,
    headTiltY: 0,
    headTiltZ: -0.1,
    floatingSpeed: 0.5,
    breathingAmplitude: 0.02,
    antennaPulseSpeed: 0.5,
    statusLabel: "Connection Disrupted",
  },
  DISCONNECTED: {
    state: "DISCONNECTED",
    primaryColor: "#94a3b8", // Soft muted slate
    glowColor: "rgba(148, 163, 184, 0.2)",
    eyeShape: "closed",
    headTiltX: 0.2, // Head bowed in sleep
    headTiltY: 0,
    headTiltZ: 0,
    floatingSpeed: 0.3,
    breathingAmplitude: 0.01,
    antennaPulseSpeed: 0.2,
    statusLabel: "Session Ended",
  },
};

/**
 * Maps incoming backend session and agent tool events into corresponding RobotState transitions.
 */
export function mapBackendEventToRobotState(
  eventType: string,
  eventData?: any,
  currentState: RobotState = "IDLE"
): RobotState {
  switch (eventType) {
    case "session_started":
      return "GREETING";

    case "greeting_complete":
      return "LISTENING";

    case "tool_call_start":
      return "THINKING";

    case "tool_call_complete":
      if (!eventData) return "LISTENING";

      const toolName = eventData.tool_name;
      const success = eventData.success;

      // Positive celebration for successful site visit booking
      if (toolName === "book_site_visit" && success) {
        return "HAPPY";
      }

      // Check search / matching tool outcome
      if (toolName === "search_properties" && success) {
        const data = eventData.data || {};
        if (data.permission_required === true || data.total_exact_matches === 0) {
          // Alternative options found; polite thoughtful inquiry
          return "CONFUSED";
        }
        if (data.total_matches > 0 || data.total_exact_matches > 0) {
          // Exact verified properties found!
          return "HAPPY";
        }
      }

      return "SPEAKING";

    case "speaking_start":
      return "SPEAKING";

    case "speaking_end":
      return "LISTENING";

    case "interrupted":
      return "LISTENING";

    case "error":
      return "ERROR";

    case "disconnected":
    case "closed":
      return "DISCONNECTED";

    default:
      return currentState;
  }
}
