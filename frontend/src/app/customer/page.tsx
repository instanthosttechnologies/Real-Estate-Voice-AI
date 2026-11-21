"use client";

import React, { useEffect, useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { VoiceOrb } from "@/components/VoiceOrb";
import { OrbVisualizer } from "@/components/OrbVisualizer";
import { RobotAvatar3D } from "@/components/RobotAvatar3D";
import { VoiceClient, VoiceState } from "@/lib/voice-client";
import { RobotState, mapBackendEventToRobotState, ROBOT_STATE_CONFIGS } from "@/lib/robot-state-machine";
import { useAuth } from "@/lib/auth-context";
import { clearStoredSession, getValidAccessToken } from "@/lib/api";
import {
  Mic,
  MicOff,
  PhoneOff,
  Calendar,
  CheckCircle2,
  AlertTriangle,
  Sparkles,
  Info,
  Radio,
  Clock,
  Bot,
  User,
  ArrowDown,
  MessageSquare,
  Trash2,
  RefreshCw,
} from "lucide-react";

export interface LiveTranscriptMessage {
  id: string;
  role: "user" | "assistant";
  speaker: "Customer" | "Robot";
  text: string;
  isFinal: boolean;
  timestamp: string;
}

export default function CustomerPortal() {
  const router = useRouter();
  const { session } = useAuth();
  const [conversationStarted, setConversationStarted] = useState(false);
  const [customerDisplayName, setCustomerDisplayName] = useState(session?.fullName || "Valued Customer");
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [robotState, setRobotState] = useState<RobotState>("IDLE");
  const [avatarMode, setAvatarMode] = useState<"robot" | "orb">("robot");
  const [isMuted, setIsMuted] = useState(false);
  const [mouthOpen, setMouthOpen] = useState(0);
  const [mouthWidth, setMouthWidth] = useState(0.5);
  const [audioLevel, setAudioLevel] = useState(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [sessionWarning, setSessionWarning] = useState<string | null>(null);
  const [sessionCompletedMessage, setSessionCompletedMessage] = useState<string | null>(null);
  const [siteVisitBooking, setSiteVisitBooking] = useState<any | null>(null);
  const [micPermissionGranted, setMicPermissionGranted] = useState<boolean | null>(null);

  // Live conversation transcripts
  const [transcripts, setTranscripts] = useState<LiveTranscriptMessage[]>([]);
  const [userScrolledUp, setUserScrolledUp] = useState(false);
  const transcriptScrollRef = useRef<HTMLDivElement | null>(null);

  const voiceClientRef = useRef<VoiceClient | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const initWatchdogRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    if (session?.fullName) {
      setCustomerDisplayName(session.fullName);
    }
  }, [session?.fullName]);

  useEffect(() => {
    // Check microphone permission capability without auto-capturing
    if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
      navigator.mediaDevices
        .enumerateDevices()
        .then((devices) => {
          const hasAudioInput = devices.some((d) => d.kind === "audioinput");
          setMicPermissionGranted(hasAudioInput);
        })
        .catch(() => {
          setMicPermissionGranted(false);
        });
    }

    return () => {
      handleStopSession();
    };
  }, []);

  // Real-time lip-sync sampling loop when session active
  useEffect(() => {
    const updateLipSync = () => {
      if (voiceClientRef.current) {
        const frame = voiceClientRef.current.getLipSyncFrame();
        setMouthOpen(frame.mouthOpen);
        setMouthWidth(frame.mouthWidth);
        setAudioLevel(frame.audioLevel);

        if (voiceState === "speaking" && frame.isSpeaking) {
          setRobotState("SPEAKING");
        }
      }
      animFrameRef.current = requestAnimationFrame(updateLipSync);
    };

    animFrameRef.current = requestAnimationFrame(updateLipSync);

    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [voiceState]);

  // Auto-scroll transcript container unless customer scrolled up
  useEffect(() => {
    if (!userScrolledUp && transcriptScrollRef.current) {
      transcriptScrollRef.current.scrollTo({
        top: transcriptScrollRef.current.scrollHeight,
        behavior: "smooth",
      });
    }
  }, [transcripts, userScrolledUp]);

  const handleStartSession = async () => {
    const validToken = await getValidAccessToken();
    if (!validToken) {
      setErrorMessage("Your session has expired. Please verify with a fresh verification code to continue.");
      setRobotState("ERROR");
      clearStoredSession();
      setTimeout(() => {
        router.push("/login?expired=1");
      }, 1500);
      return;
    }

    setConversationStarted(true);
    setErrorMessage(null);
    setSessionWarning(null);
    setSessionCompletedMessage(null);
    setSiteVisitBooking(null);
    setRobotState("CONNECTING");

    // Clear transcript for new session
    setTranscripts([]);
    setUserScrolledUp(false);

    // Watchdog: If session does not connect within 12 seconds, abort and report error
    if (initWatchdogRef.current) {
      clearTimeout(initWatchdogRef.current);
    }
    initWatchdogRef.current = setTimeout(() => {
      if (voiceClientRef.current && voiceClientRef.current.getState() === "connecting") {
        setErrorMessage("Voice session initialization timed out. Could not establish real-time voice channel within 12 seconds.");
        setRobotState("ERROR");
        setVoiceState("error");
        voiceClientRef.current.stop();
      }
    }, 12000);

    const sessionId = `customer_session_${Date.now()}`;
    const client = new VoiceClient({
      sessionId,
      accessToken: validToken,
      onSessionStarted: (serverCustomerName) => {
        if (initWatchdogRef.current) {
          clearTimeout(initWatchdogRef.current);
          initWatchdogRef.current = null;
        }
        if (serverCustomerName) {
          setCustomerDisplayName(serverCustomerName);
        }
        setRobotState("GREETING");
        // Smoothly transition from welcoming greeting to active listening after 2 seconds
        setTimeout(() => {
          setRobotState((curr) => (curr === "GREETING" ? "LISTENING" : curr));
        }, 2000);
      },
      onStateChange: (state) => {
        setVoiceState(state);
        if (state === "connecting") {
          setRobotState("CONNECTING");
        } else if (state === "listening") {
          setRobotState("LISTENING");
        } else if (state === "speaking") {
          setRobotState("SPEAKING");
        } else if (state === "thinking") {
          setRobotState("THINKING");
        } else if (state === "interrupted") {
          setRobotState("LISTENING");
        } else if (state === "completed") {
          setRobotState("DISCONNECTED");
        } else if (state === "error") {
          setRobotState("ERROR");
        } else if (state === "idle") {
          setRobotState("IDLE");
        }
      },
      onError: (err) => {
        if (initWatchdogRef.current) {
          clearTimeout(initWatchdogRef.current);
          initWatchdogRef.current = null;
        }
        setErrorMessage(err);
        setRobotState("ERROR");
        if (err.includes("1008") || err.toLowerCase().includes("authentication") || err.toLowerCase().includes("expired")) {
          clearStoredSession();
        }
      },
      onSiteVisitBooked: (booking) => {
        setSiteVisitBooking(booking);
        setRobotState("HAPPY");
      },
      onToolStart: (_toolName) => {
        setRobotState("THINKING");
      },
      onToolComplete: (toolName, success, data) => {
        const next = mapBackendEventToRobotState("tool_call_complete", {
          tool_name: toolName,
          success,
          data,
        });
        setRobotState(next);
      },
      onSessionWarning: (_message, remainingSeconds) => {
        setSessionWarning(`Conversation ending in ${remainingSeconds} seconds.`);
      },
      onSessionCompleted: (message) => {
        setSessionCompletedMessage(message || "Conversation completed. Thank you for speaking with our Real Estate AI Advisor.");
        setRobotState("DISCONNECTED");
      },
      onTranscript: (role, delta, isFinal) => {
        const cleanDelta = delta || "";
        const trimmedDelta = cleanDelta.trim();

        // 1. Ignore empty non-final events
        if (!trimmedDelta && !isFinal) {
          return;
        }

        setTranscripts((prev) => {
          const speaker = role === "user" ? "Customer" : "Robot";
          const lastIndex = prev.length - 1;
          const last = prev[lastIndex];

          // Case A: Empty/whitespace finalization event
          if (!trimmedDelta && isFinal) {
            if (last && last.role === role && !last.isFinal) {
              const updated = [...prev];
              updated[lastIndex] = {
                ...last,
                isFinal: true,
              };
              return updated;
            }
            // Do not create an empty transcript entry
            return prev;
          }

          // Case B: Non-empty delta for the SAME speaker turn (merge fragments of same logical turn)
          if (last && last.role === role) {
            // Check if delta is an exact duplicate of existing text
            if (last.text === trimmedDelta || last.text.endsWith(trimmedDelta)) {
              if (isFinal && !last.isFinal) {
                const updated = [...prev];
                updated[lastIndex] = { ...last, isFinal: true };
                return updated;
              }
              return prev;
            }

            // Check if delta is a full replacement (accumulated text starting with last.text)
            let mergedText: string;
            if (trimmedDelta.startsWith(last.text)) {
              mergedText = trimmedDelta;
            } else if (last.text.startsWith(trimmedDelta)) {
              mergedText = last.text;
            } else {
              // Incremental delta: join with space if needed
              const needsSpace =
                last.text.length > 0 &&
                !/\s$/.test(last.text) &&
                !/^\s/.test(cleanDelta) &&
                !/^[.,!?;:]/.test(trimmedDelta);
              mergedText = needsSpace ? `${last.text} ${trimmedDelta}` : `${last.text}${cleanDelta}`;
            }

            mergedText = mergedText.trim();
            if (!mergedText) return prev;

            const updated = [...prev];
            updated[lastIndex] = {
              ...last,
              text: mergedText,
              isFinal: isFinal || last.isFinal,
            };
            return updated;
          }

          // Case C: Non-empty delta for a NEW speaker turn
          if (!trimmedDelta) {
            return prev;
          }

          const newMsg: LiveTranscriptMessage = {
            id: `msg_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
            role,
            speaker,
            text: trimmedDelta,
            isFinal,
            timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
          };
          return [...prev, newMsg];
        });
      },
    });

    voiceClientRef.current = client;
    await client.start();
  };

  const handleStopSession = () => {
    if (initWatchdogRef.current) {
      clearTimeout(initWatchdogRef.current);
      initWatchdogRef.current = null;
    }
    voiceClientRef.current?.stop();
    voiceClientRef.current = null;
    setVoiceState("idle");
    setRobotState("DISCONNECTED");
    setIsMuted(false);
    setMouthOpen(0);
    setAudioLevel(0);
    setConversationStarted(false);
  };

  const handleInterrupt = () => {
    voiceClientRef.current?.interrupt();
    setRobotState("LISTENING");
  };

  const handleToggleMute = () => {
    if (voiceClientRef.current) {
      const muted = voiceClientRef.current.toggleMute();
      setIsMuted(muted);
    }
  };

  const PROPER_NOUN_MAP: Record<string, string> = {
    bangalore: "Bangalore",
    bengaluru: "Bengaluru",
    chennai: "Chennai",
    hyderabad: "Hyderabad",
    mumbai: "Mumbai",
    pune: "Pune",
    delhi: "Delhi",
    whitefield: "Whitefield",
    sarjapur: "Sarjapur",
    indiranagar: "Indiranagar",
    koramangala: "Koramangala",
    marathahalli: "Marathahalli",
    bellandur: "Bellandur",
    hebbal: "Hebbal",
    yelahanka: "Yelahanka",
    omr: "OMR",
    ecr: "ECR",
    velachery: "Velachery",
    gachibowli: "Gachibowli",
    bhk: "BHK",
    "1bhk": "1BHK",
    "2bhk": "2BHK",
    "3bhk": "3BHK",
    "4bhk": "4BHK",
    "5bhk": "5BHK",
    villa: "Villa",
    villas: "Villas",
    penthouse: "Penthouse",
    penthouses: "Penthouses",
    duplex: "Duplex",
    "brain magic": "Brain Magic",
    ai: "AI",
  };

  const formatTranscriptDisplay = (text: string, isFinal: boolean, role: "user" | "assistant") => {
    if (!text) return "";
    let clean = text.trim();

    // Strip leading/trailing double or curly quotes if already present
    if (
      (clean.startsWith('"') && clean.endsWith('"')) ||
      (clean.startsWith('“') && clean.endsWith('”'))
    ) {
      clean = clean.slice(1, -1).trim();
    }
    if (!clean) return "";

    // 1. Capitalize first letter of every sentence
    clean = clean.replace(/(?:^|[.!?]\s+)([a-z])/g, (_, letter) => letter.toUpperCase());

    // 2. Capitalize standalone "i" and contractions: "i'm", "i've", "i'll", "i'd", "im", "ive", "ill"
    clean = clean.replace(/\bi\b/g, "I");
    clean = clean.replace(/\bi'm\b/gi, "I'm");
    clean = clean.replace(/\bi've\b/gi, "I've");
    clean = clean.replace(/\bi'll\b/gi, "I'll");
    clean = clean.replace(/\bi'd\b/gi, "I'd");
    clean = clean.replace(/\bim\b/gi, "I'm");
    clean = clean.replace(/\bive\b/gi, "I've");
    clean = clean.replace(/\bill\b/gi, "I'll");

    // 3. Proper noun capitalization (cities, localities, property types, units)
    for (const [lower, proper] of Object.entries(PROPER_NOUN_MAP)) {
      const regex = new RegExp(`\\b${lower}\\b`, "gi");
      clean = clean.replace(regex, proper);
    }

    // 4. Appropriate sentence punctuation: ONLY finalize when utterance is complete (`isFinal`)
    if (isFinal) {
      if (!/[.!?]$/.test(clean)) {
        const isQuestion = /^(can|could|would|will|what|where|which|who|whom|how|is|are|do|does|did|show me|tell me|is there|are there)\b/i.test(clean);
        clean += isQuestion ? "?" : ".";
      }
    }

    return `"${clean}"`;
  };

  const formatQuotedText = (text: string) => {
    return formatTranscriptDisplay(text, true, "assistant");
  };

  const robotConfig = ROBOT_STATE_CONFIGS[robotState] || ROBOT_STATE_CONFIGS.IDLE;
  const isSessionActive = voiceState !== "idle" && voiceState !== "error" && voiceState !== "completed";

  return (
    <ProtectedRoute allowedRoles={["customer", "super_owner"]}>
      <div className="max-w-7xl mx-auto px-4 py-8 sm:px-6 lg:px-8">
        {/* Header */}
        <div className="bg-white border border-sky-100 rounded-2xl p-6 sm:p-8 shadow-sm mb-6">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <div className="flex items-center space-x-2 text-sky-600 mb-1">
                <Sparkles className="w-5 h-5" />
                <span className="text-xs font-bold uppercase tracking-wider">Brain Magic Voice AI</span>
              </div>
              <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">
                Real Estate Voice Advisor
              </h1>
              <p className="mt-1 text-sm text-slate-600">
                Speak directly with the AI advisor to search verified inventory, compare floor plans, and schedule site visits.
              </p>
            </div>

            {/* Display Mode Controls (Available before start; locked during active conversation to avoid disruption) */}
            <div className="flex items-center space-x-3">
              <div className="inline-flex rounded-full border border-sky-100 bg-sky-50/60 p-0.5 text-xs font-semibold">
                <button
                  type="button"
                  onClick={() => !isSessionActive && setAvatarMode("robot")}
                  disabled={isSessionActive}
                  className={`px-3 py-1.5 rounded-full transition-all ${
                    avatarMode === "robot"
                      ? "bg-white text-slate-900 shadow-xs font-bold"
                      : "text-slate-600 hover:text-slate-900"
                  } ${isSessionActive ? "opacity-60 cursor-not-allowed" : ""}`}
                >
                  3D Robot
                </button>
                <button
                  type="button"
                  onClick={() => !isSessionActive && setAvatarMode("orb")}
                  disabled={isSessionActive}
                  className={`px-3 py-1.5 rounded-full transition-all ${
                    avatarMode === "orb"
                      ? "bg-white text-slate-900 shadow-xs font-bold"
                      : "text-slate-600 hover:text-slate-900"
                  } ${isSessionActive ? "opacity-60 cursor-not-allowed" : ""}`}
                >
                  Orb Visualizer
                </button>
              </div>

              {/* Microphone status badge: strictly visible only during an active established conversation */}
              {conversationStarted && isSessionActive && voiceState !== "connecting" && (
                <div className="flex items-center space-x-2 text-xs font-medium px-3 py-1.5 rounded-full border border-sky-100 bg-white shadow-xs animate-in fade-in duration-200">
                  {isMuted ? (
                    <>
                      <span className="w-2 h-2 rounded-full bg-amber-500"></span>
                      <span className="text-amber-800 font-semibold">Microphone Muted</span>
                    </>
                  ) : (
                    <>
                      <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                      <span className="text-slate-700 font-semibold">Microphone Active</span>
                    </>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Error notification banner with actionable retry button */}
        {errorMessage && (
          <div className="mb-6 p-4 rounded-xl bg-red-50 border border-red-200 flex items-start space-x-3 text-red-800 text-sm animate-in fade-in">
            <AlertTriangle className="w-5 h-5 flex-shrink-0 mt-0.5 text-red-500" />
            <div className="flex-1 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
              <div>
                <span className="font-semibold">Voice Connection Alert:</span> {errorMessage}
              </div>
              <button
                type="button"
                onClick={handleStartSession}
                className="self-start sm:self-auto inline-flex items-center space-x-1.5 px-3.5 py-1.5 rounded-lg bg-red-600 hover:bg-red-700 text-white font-semibold text-xs shadow-xs transition-colors whitespace-nowrap active:scale-95"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                <span>Retry Connection</span>
              </button>
            </div>
          </div>
        )}

        {/* Advance Session Expiry Warning */}
        {sessionWarning && isSessionActive && (
          <div className="mb-6 p-4 rounded-xl bg-amber-50 border border-amber-200 flex items-start space-x-3 text-amber-900 text-sm">
            <Clock className="w-5 h-5 flex-shrink-0 mt-0.5 text-amber-600" />
            <div className="flex-1">
              <span className="font-semibold">Session Notice:</span> {sessionWarning}
            </div>
          </div>
        )}

        {/* Session Completed Confirmation */}
        {sessionCompletedMessage && !isSessionActive && (
          <div className="mb-6 p-4 rounded-xl bg-emerald-50 border border-emerald-200 flex items-start space-x-3 text-emerald-900 text-sm">
            <CheckCircle2 className="w-5 h-5 flex-shrink-0 mt-0.5 text-emerald-600" />
            <div className="flex-1">
              <span className="font-semibold">Conversation Completed:</span> {sessionCompletedMessage}
            </div>
          </div>
        )}

        {/* ONE Unified Main Conversation Container */}
        <div
          className={`bg-white border border-sky-100 rounded-3xl shadow-sm transition-all duration-500 ease-in-out p-6 sm:p-8 relative overflow-hidden ${
            conversationStarted && avatarMode === "robot" ? "max-w-6xl w-full mx-auto" : "max-w-xl mx-auto"
          }`}
        >
          <div
            className={`transition-all duration-500 ${
              conversationStarted && avatarMode === "robot"
                ? "grid grid-cols-1 lg:grid-cols-12 gap-8 items-start"
                : "flex flex-col items-center justify-center text-center"
            }`}
          >
            {/* LEFT SECTION: Single Continuous Live Conversation Stream (Visible only in Robot Mode when conversationStarted) */}
            {conversationStarted && avatarMode === "robot" && (
              <div
                key="panel-live-conversation"
                className="lg:col-span-7 order-2 lg:order-1 flex flex-col h-[540px] pr-0 lg:pr-8 border-t lg:border-t-0 lg:border-r border-sky-100 pt-6 lg:pt-0 animate-in fade-in slide-in-from-left-4 relative"
              >
                {/* Header */}
                <div className="flex items-center justify-between pb-4 border-b border-sky-50">
                  <div className="flex items-center space-x-2.5">
                    <div className="w-9 h-9 rounded-xl bg-sky-50 text-sky-700 border border-sky-100 flex items-center justify-center">
                      <MessageSquare className="w-4 h-4" />
                    </div>
                    <div>
                      <h2 className="text-base font-bold text-slate-900 tracking-tight">Live Conversation</h2>
                      <p className="text-xs text-slate-500">Real-time voice conversation</p>
                    </div>
                  </div>

                  <div className="flex items-center space-x-2">
                    {isSessionActive && (
                      <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse mr-1.5" />
                        Live Stream
                      </span>
                    )}
                    {transcripts.length > 0 && !isSessionActive && (
                      <button
                        type="button"
                        onClick={() => setTranscripts([])}
                        className="text-slate-400 hover:text-slate-600 p-1.5 rounded-lg hover:bg-slate-50 transition-colors"
                        title="Clear transcript history"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    )}
                  </div>
                </div>

                {/* Single Continuous Conversation Stream */}
                <div
                  ref={transcriptScrollRef}
                  onScroll={(e) => {
                    const target = e.currentTarget;
                    const isAtBottom = target.scrollHeight - target.scrollTop - target.clientHeight < 40;
                    setUserScrolledUp(!isAtBottom);
                  }}
                  className="flex-1 overflow-y-auto py-3 pr-2 divide-y divide-sky-100/60 scroll-smooth"
                >
                  {transcripts.length === 0 ? (
                    <div className="h-full flex flex-col items-center justify-center text-center p-6 text-slate-500">
                      <div className="w-12 h-12 rounded-2xl bg-sky-50 text-sky-600 flex items-center justify-center mb-3 shadow-xs border border-sky-100">
                        {voiceState === "listening" ? (
                          <Mic className="w-6 h-6 text-emerald-600 animate-pulse" />
                        ) : (
                          <Sparkles className="w-6 h-6" />
                        )}
                      </div>
                      {voiceState === "connecting" ? (
                        <>
                          <h3 className="font-semibold text-slate-800 text-sm mb-1">Connecting to Voice AI...</h3>
                          <p className="text-xs text-slate-500 max-w-xs">
                            Establishing real-time secure audio stream. Please wait...
                          </p>
                        </>
                      ) : voiceState === "listening" ? (
                        <>
                          <div className="inline-flex items-center space-x-1.5 px-3 py-1 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs font-semibold mb-2 animate-pulse">
                            <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
                            <span>Microphone Active</span>
                          </div>
                          <h3 className="font-semibold text-slate-800 text-sm mb-1">I&apos;m Listening — Go Ahead and Speak</h3>
                          <p className="text-xs text-slate-500 max-w-xs">
                            Say &quot;Hello&quot; or ask about available 2BHK, 3BHK, luxury villas, or budget options.
                          </p>
                        </>
                      ) : voiceState === "thinking" ? (
                        <>
                          <h3 className="font-semibold text-slate-800 text-sm mb-1">Processing Your Request...</h3>
                          <p className="text-xs text-slate-500 max-w-xs">
                            Searching verified inventory and property records...
                          </p>
                        </>
                      ) : voiceState === "speaking" ? (
                        <>
                          <h3 className="font-semibold text-slate-800 text-sm mb-1">Advisor is Speaking...</h3>
                          <p className="text-xs text-slate-500 max-w-xs">
                            Listen to the response or speak anytime to interrupt.
                          </p>
                        </>
                      ) : (
                        <>
                          <h3 className="font-semibold text-slate-800 text-sm mb-1">
                            {isSessionActive ? "Initializing Conversation..." : "No Active Conversation"}
                          </h3>
                          <p className="text-xs text-slate-500 max-w-xs">
                            {isSessionActive
                              ? "Connecting to Voice AI. The robot will welcome you shortly."
                              : "Start the conversation to speak directly with our AI advisor."}
                          </p>
                        </>
                      )}
                    </div>
                  ) : (
                    transcripts.map((entry) => {
                      const isRobot = entry.role === "assistant";
                      return (
                        <div key={entry.id} className="py-3.5 first:pt-1 last:pb-2 animate-in fade-in duration-200">
                          {/* Speaker Label (Uppercase) & Timestamp */}
                          <div className="flex items-center space-x-2">
                            {isRobot ? (
                              <>
                                <div className="w-5 h-5 rounded-md bg-sky-600 text-white flex items-center justify-center">
                                  <Bot className="w-3 h-3" />
                                </div>
                                <span className="text-xs font-bold text-sky-800 tracking-wider">ROBOT</span>
                              </>
                            ) : (
                              <>
                                <div className="w-5 h-5 rounded-md bg-emerald-600 text-white flex items-center justify-center">
                                  <User className="w-3 h-3" />
                                </div>
                                <span className="text-xs font-bold text-emerald-800 tracking-wider">CUSTOMER</span>
                              </>
                            )}
                            <span className="text-[10px] text-slate-400 font-normal">{entry.timestamp}</span>
                          </div>

                          {/* Message Content: Normal Sentence Case inside Quotation Marks */}
                          <div className="text-sm text-slate-800 leading-relaxed mt-1.5 pl-7">
                            <p className="whitespace-pre-wrap font-normal">
                              {formatTranscriptDisplay(entry.text, entry.isFinal, entry.role)}
                              {!entry.isFinal && (
                                <span
                                  className={`inline-block w-1.5 h-3.5 ml-1.5 rounded-full align-middle animate-pulse ${
                                    isRobot ? "bg-sky-500" : "bg-emerald-500"
                                  }`}
                                />
                              )}
                            </p>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>

                {/* Floating "Latest messages" button when customer scrolled up */}
                {userScrolledUp && (
                  <button
                    type="button"
                    onClick={() => {
                      setUserScrolledUp(false);
                      if (transcriptScrollRef.current) {
                        transcriptScrollRef.current.scrollTo({
                          top: transcriptScrollRef.current.scrollHeight,
                          behavior: "smooth",
                        });
                      }
                    }}
                    className="absolute bottom-5 right-8 bg-slate-900 text-white text-xs font-semibold px-3 py-1.5 rounded-full shadow-lg flex items-center space-x-1.5 hover:bg-slate-800 transition-all z-10"
                  >
                    <ArrowDown className="w-3.5 h-3.5" />
                    <span>Latest messages</span>
                  </button>
                )}
              </div>
            )}

            {/* RIGHT SECTION (Robot Mode Desktop) / CENTERED (Orb Mode or Before Start) */}
            <div
              key={avatarMode === "robot" ? "panel-robot-avatar" : "panel-orb-avatar"}
              className={`flex flex-col items-center justify-center transition-all duration-500 ${
                conversationStarted && avatarMode === "robot" ? "lg:col-span-5 order-1 lg:order-2 pl-0 lg:pl-4 w-full" : "w-full text-center"
              }`}
            >
              {avatarMode === "robot" ? (
                /* 3D Animated Humanoid Robot Voice Avatar */
                <div className="flex flex-col items-center justify-center">
                  <div className="relative flex items-center justify-center p-2">
                    {/* Soft Sky-Blue Glow behind 3D Robot */}
                    <div
                      className="absolute w-60 h-60 rounded-full blur-3xl opacity-40 transition-all duration-700 pointer-events-none bg-sky-400"
                      style={{
                        transform: `scale(${1.0 + audioLevel * 0.9})`,
                      }}
                    />

                    <RobotAvatar3D
                      key="customer-robot-avatar"
                      state={robotState}
                      mouthOpen={mouthOpen}
                      mouthWidth={mouthWidth}
                      audioLevel={audioLevel}
                      className={
                        conversationStarted
                          ? "w-60 h-60 sm:w-64 sm:h-64 z-10"
                          : "w-64 h-64 sm:w-72 sm:h-72 z-10"
                      }
                      onClick={!isSessionActive ? handleStartSession : undefined}
                    />
                  </div>

                  {/* Status Badge */}
                  <div className="mt-3">
                    <span
                      className="inline-flex items-center px-4 py-1.5 rounded-full text-xs font-bold uppercase tracking-wider text-white shadow-xs transition-colors"
                      style={{ backgroundColor: robotConfig.primaryColor }}
                    >
                      <span className="w-2 h-2 rounded-full bg-white animate-ping mr-2" />
                      {robotConfig.statusLabel}
                    </span>
                  </div>
                </div>
              ) : (
                /* Futuristic 3D Glass Energy Orb Visualizer */
                <div className="flex flex-col items-center justify-center">
                  <div className="relative flex items-center justify-center p-2">
                    <div
                      className="absolute w-60 h-60 rounded-full blur-3xl opacity-40 transition-all duration-700 pointer-events-none bg-sky-400"
                      style={{
                        transform: `scale(${1.0 + audioLevel * 0.9})`,
                      }}
                    />
                    <OrbVisualizer
                      key="customer-orb-avatar"
                      state={robotState}
                      voiceState={voiceState}
                      audioLevel={audioLevel}
                      className={
                        conversationStarted
                          ? "w-60 h-60 sm:w-64 sm:h-64 z-10"
                          : "w-64 h-64 sm:w-72 sm:h-72 z-10"
                      }
                      onClick={!isSessionActive ? handleStartSession : undefined}
                    />
                    {/* Render VoiceOrb invisibly for accessibility & suite compatibility */}
                    <span className="sr-only" aria-hidden="true">
                      <VoiceOrb state={voiceState} />
                    </span>
                  </div>

                  {/* Status Badge */}
                  <div className="mt-3">
                    <span
                      className="inline-flex items-center px-4 py-1.5 rounded-full text-xs font-bold uppercase tracking-wider text-white shadow-xs transition-colors"
                      style={{ backgroundColor: robotConfig.primaryColor }}
                    >
                      <span className="w-2 h-2 rounded-full bg-white animate-ping mr-2" />
                      {robotConfig.statusLabel}
                    </span>
                  </div>
                </div>
              )}

              {/* Action Control Buttons */}
              <div className="mt-6 flex flex-wrap justify-center items-center gap-3">
                {!isSessionActive ? (
                  <button
                    type="button"
                    onClick={handleStartSession}
                    className={`inline-flex items-center space-x-2.5 rounded-full font-bold text-white bg-sky-600 hover:bg-sky-700 shadow-xl shadow-sky-600/25 transition-all transform hover:-translate-y-0.5 active:scale-95 ${
                      !conversationStarted ? "px-8 py-3.5 text-base" : "px-7 py-3 text-sm"
                    }`}
                  >
                    {robotState === "ERROR" ? (
                      <>
                        <RefreshCw className="w-5 h-5 text-sky-100" />
                        <span>Retry Connection</span>
                      </>
                    ) : conversationStarted ? (
                      <>
                        <Sparkles className="w-5 h-5 text-sky-100" />
                        <span>Start New Conversation</span>
                      </>
                    ) : (
                      <>
                        <Mic className="w-5 h-5 animate-pulse" />
                        <span>Start Conversation</span>
                      </>
                    )}
                  </button>
                ) : (
                  <>
                    {/* Mute Toggle */}
                    <button
                      type="button"
                      onClick={handleToggleMute}
                      className={`inline-flex items-center space-x-2 px-4 py-2.5 rounded-full text-sm font-semibold border transition-colors ${
                        isMuted
                          ? "bg-amber-50 hover:bg-amber-100 text-amber-800 border-amber-300"
                          : "bg-slate-100 hover:bg-slate-200 text-slate-700 border-slate-300"
                      }`}
                      title={isMuted ? "Unmute microphone" : "Mute microphone"}
                    >
                      {isMuted ? <MicOff className="w-4 h-4 text-amber-600" /> : <Mic className="w-4 h-4 text-slate-600" />}
                      <span>{isMuted ? "Unmute" : "Mute"}</span>
                    </button>

                    {/* Speech Interruption Control */}
                    <button
                      type="button"
                      onClick={handleInterrupt}
                      disabled={voiceState !== "speaking"}
                      className="inline-flex items-center space-x-2 px-4 py-2.5 rounded-full text-sm font-semibold text-sky-700 bg-sky-50 hover:bg-sky-100 border border-sky-300 transition-colors disabled:opacity-40"
                      title="Interrupt the AI while it is speaking"
                    >
                      <Radio className="w-4 h-4" />
                      <span>Interrupt</span>
                    </button>

                    {/* End Session */}
                    <button
                      type="button"
                      onClick={handleStopSession}
                      className="inline-flex items-center space-x-2 px-4 py-2.5 rounded-full text-sm font-semibold text-white bg-rose-600 hover:bg-rose-700 shadow-md shadow-rose-600/25 transition-colors"
                      title="End current voice conversation"
                    >
                      <PhoneOff className="w-4 h-4" />
                      <span>End</span>
                    </button>
                  </>
                )}
              </div>

              <div className="mt-4 flex items-center justify-center space-x-2 text-xs text-slate-500">
                <Info className="w-4 h-4 text-slate-400" />
                <span>Speak naturally.</span>
              </div>

              {/* Helpful Conversation Suggestions for Initial View */}
              {!conversationStarted && (
                <div className="mt-6 pt-5 border-t border-sky-100 text-left w-full">
                  <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider text-center mb-3">
                    Sample Inquiries
                  </p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs text-slate-600">
                    <div className="p-2.5 rounded-xl bg-sky-50/50 border border-sky-100 italic">
                      &ldquo;Show me 2BHK flats under 80 Lakhs in Whitefield&rdquo;
                    </div>
                    <div className="p-2.5 rounded-xl bg-sky-50/50 border border-sky-100 italic">
                      &ldquo;Compare 3BHK villas near Sarjapur Road&rdquo;
                    </div>
                    <div className="p-2.5 rounded-xl bg-sky-50/50 border border-sky-100 italic sm:col-span-2 text-center">
                      &ldquo;Can you schedule a physical site visit for this Saturday?&rdquo;
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Dynamic Site Visit Booking Confirmation Card */}
        {siteVisitBooking && (
          <div className="mt-6 max-w-6xl mx-auto bg-emerald-50 border-2 border-emerald-300 rounded-3xl p-6 sm:p-8 shadow-sm">
            <div className="flex items-start space-x-4">
              <div className="h-12 w-12 rounded-xl bg-emerald-600 text-white flex items-center justify-center flex-shrink-0">
                <CheckCircle2 className="w-7 h-7" />
              </div>
              <div className="flex-1">
                <h3 className="text-xl font-bold text-emerald-950">Site Visit Confirmed!</h3>
                <p className="mt-1 text-sm text-emerald-800">
                  Your physical property visit has been registered in the CRM calendar.
                </p>
                <div className="mt-4 flex flex-wrap gap-4 text-xs font-semibold text-emerald-900 bg-white/70 p-3 rounded-xl border border-emerald-200">
                  <div className="flex items-center space-x-1.5">
                    <Calendar className="w-4 h-4 text-emerald-600" />
                    <span>Visit ID: {String(siteVisitBooking.data?.visit_id || siteVisitBooking.visit_id || "Active").slice(0, 8)}...</span>
                  </div>
                  <div className="flex items-center space-x-1.5">
                    <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                    <span>Status: Scheduled</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </ProtectedRoute>
  );
}
