"use client";

import React, { useEffect, useState, useRef } from "react";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { VoiceOrb } from "@/components/VoiceOrb";
import { RobotAvatar3D } from "@/components/RobotAvatar3D";
import { VoiceClient, VoiceState } from "@/lib/voice-client";
import { RobotState, mapBackendEventToRobotState, ROBOT_STATE_CONFIGS } from "@/lib/robot-state-machine";
import { useAuth } from "@/lib/auth-context";
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
  Eye,
} from "lucide-react";

export default function CustomerPortal() {
  const { session } = useAuth();
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [robotState, setRobotState] = useState<RobotState>("IDLE");
  const [avatarMode, setAvatarMode] = useState<"robot" | "orb">("robot");
  const [isMuted, setIsMuted] = useState(false);
  const [mouthOpen, setMouthOpen] = useState(0);
  const [mouthWidth, setMouthWidth] = useState(0.5);
  const [audioLevel, setAudioLevel] = useState(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [siteVisitBooking, setSiteVisitBooking] = useState<any | null>(null);
  const [micPermissionGranted, setMicPermissionGranted] = useState<boolean | null>(null);

  const voiceClientRef = useRef<VoiceClient | null>(null);
  const animFrameRef = useRef<number | null>(null);

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

  const handleStartSession = async () => {
    if (!session?.accessToken) return;

    setErrorMessage(null);
    setSiteVisitBooking(null);
    setRobotState("CONNECTING");

    const sessionId = `customer_session_${Date.now()}`;
    const client = new VoiceClient({
      sessionId,
      accessToken: session.accessToken,
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
        } else if (state === "error") {
          setRobotState("ERROR");
        } else if (state === "idle") {
          setRobotState("IDLE");
        }
      },
      onError: (err) => {
        setErrorMessage(err);
        setRobotState("ERROR");
      },
      onSiteVisitBooked: (booking) => {
        setSiteVisitBooking(booking);
        setRobotState("HAPPY");
      },
      onToolStart: (toolName) => {
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
    });

    voiceClientRef.current = client;
    await client.start();
  };

  const handleStopSession = () => {
    voiceClientRef.current?.stop();
    voiceClientRef.current = null;
    setVoiceState("idle");
    setRobotState("DISCONNECTED");
    setIsMuted(false);
    setMouthOpen(0);
    setAudioLevel(0);
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

  const robotConfig = ROBOT_STATE_CONFIGS[robotState] || ROBOT_STATE_CONFIGS.IDLE;

  return (
    <ProtectedRoute allowedRoles={["customer", "super_owner"]}>
      <div className="max-w-4xl mx-auto px-4 py-8 sm:px-6 lg:px-8">
        {/* Header */}
        <div className="bg-white border border-slate-200 rounded-2xl p-6 sm:p-8 shadow-sm mb-6">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <div className="flex items-center space-x-2 text-emerald-600 mb-1">
                <Sparkles className="w-5 h-5" />
                <span className="text-xs font-bold uppercase tracking-wider">Voice AI Assistant</span>
              </div>
              <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">
                Real Estate Voice Advisor
              </h1>
              <p className="mt-1 text-sm text-slate-600">
                Speak directly with the AI advisor to search properties, verify live availability, and schedule site visits.
              </p>
            </div>

            {/* Microphone & Display Mode Controls */}
            <div className="flex items-center space-x-3">
              {/* Avatar View Switcher */}
              <div className="inline-flex rounded-full border border-slate-200 bg-slate-100 p-0.5 text-xs font-semibold">
                <button
                  type="button"
                  onClick={() => setAvatarMode("robot")}
                  className={`px-3 py-1.5 rounded-full transition-all ${
                    avatarMode === "robot"
                      ? "bg-white text-slate-900 shadow-sm"
                      : "text-slate-600 hover:text-slate-900"
                  }`}
                >
                  3D Robot
                </button>
                <button
                  type="button"
                  onClick={() => setAvatarMode("orb")}
                  className={`px-3 py-1.5 rounded-full transition-all ${
                    avatarMode === "orb"
                      ? "bg-white text-slate-900 shadow-sm"
                      : "text-slate-600 hover:text-slate-900"
                  }`}
                >
                  Orb Visualizer
                </button>
              </div>

              {/* Microphone permission badge */}
              <div className="flex items-center space-x-2 text-xs font-medium px-3 py-1.5 rounded-full border bg-slate-50">
                {micPermissionGranted ? (
                  <>
                    <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
                    <span className="text-slate-700">Microphone Ready</span>
                  </>
                ) : micPermissionGranted === false ? (
                  <>
                    <span className="w-2 h-2 rounded-full bg-red-500"></span>
                    <span className="text-red-700">Microphone Blocked</span>
                  </>
                ) : (
                  <>
                    <span className="w-2 h-2 rounded-full bg-slate-400"></span>
                    <span className="text-slate-600">Microphone Inactive</span>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Error notification banner */}
        {errorMessage && (
          <div className="mb-6 p-4 rounded-xl bg-red-50 border border-red-200 flex items-start space-x-3 text-red-800 text-sm">
            <AlertTriangle className="w-5 h-5 flex-shrink-0 mt-0.5 text-red-500" />
            <div className="flex-1">
              <span className="font-semibold">Voice Connection Alert:</span> {errorMessage}
            </div>
          </div>
        )}

        {/* Central Voice AI Interface (VOICE-ONLY) */}
        <div className="bg-white border border-slate-200 rounded-3xl p-8 sm:p-12 shadow-sm text-center relative overflow-hidden mb-6">
          {avatarMode === "robot" ? (
            /* 3D Animated Robot Voice Avatar */
            <div className="flex flex-col items-center justify-center">
              {/* Outer Energy Halo */}
              <div className="relative flex items-center justify-center p-4">
                <div
                  className="absolute w-56 h-56 rounded-full blur-3xl opacity-35 transition-all duration-700 pointer-events-none"
                  style={{
                    backgroundColor: robotConfig.primaryColor,
                    transform: `scale(${1.0 + audioLevel * 0.9})`,
                  }}
                />

                <RobotAvatar3D
                  state={robotState}
                  mouthOpen={mouthOpen}
                  mouthWidth={mouthWidth}
                  audioLevel={audioLevel}
                  className="w-64 h-64 sm:w-72 sm:h-72 z-10"
                  onClick={voiceState === "idle" ? handleStartSession : undefined}
                />
              </div>

              {/* Status Badge */}
              <div className="mt-4">
                <span
                  className="inline-flex items-center px-4 py-1.5 rounded-full text-xs font-bold uppercase tracking-wider text-white shadow-sm transition-colors"
                  style={{ backgroundColor: robotConfig.primaryColor }}
                >
                  <span className="w-2 h-2 rounded-full bg-white animate-ping mr-2" />
                  {robotConfig.statusLabel}
                </span>
              </div>
            </div>
          ) : (
            /* Classic Voice Visualizer Orb */
            <VoiceOrb
              state={voiceState}
              onClick={voiceState === "idle" ? handleStartSession : undefined}
            />
          )}

          {/* Action Control Buttons (Voice-Only) */}
          <div className="mt-8 flex flex-wrap justify-center items-center gap-3">
            {voiceState === "idle" ? (
              <button
                type="button"
                onClick={handleStartSession}
                className="inline-flex items-center space-x-2 px-7 py-3.5 rounded-full text-sm font-bold text-white bg-emerald-600 hover:bg-emerald-700 shadow-lg shadow-emerald-600/25 transition-all transform active:scale-95"
              >
                <Mic className="w-5 h-5" />
                <span>Start Conversation</span>
              </button>
            ) : (
              <>
                {/* Mute Toggle */}
                <button
                  type="button"
                  onClick={handleToggleMute}
                  className={`inline-flex items-center space-x-2 px-5 py-2.5 rounded-full text-sm font-semibold border transition-colors ${
                    isMuted
                      ? "bg-amber-50 hover:bg-amber-100 text-amber-800 border-amber-300"
                      : "bg-slate-100 hover:bg-slate-200 text-slate-700 border-slate-300"
                  }`}
                  title={isMuted ? "Unmute microphone" : "Mute microphone"}
                >
                  {isMuted ? <MicOff className="w-4 h-4 text-amber-600" /> : <Mic className="w-4 h-4" />}
                  <span>{isMuted ? "Unmute" : "Mute"}</span>
                </button>

                {/* Speech Interruption Control */}
                <button
                  type="button"
                  onClick={handleInterrupt}
                  disabled={voiceState !== "speaking"}
                  className="inline-flex items-center space-x-2 px-5 py-2.5 rounded-full text-sm font-semibold text-sky-700 bg-sky-50 hover:bg-sky-100 border border-sky-300 transition-colors disabled:opacity-40"
                  title="Interrupt the AI while it is speaking"
                >
                  <Radio className="w-4 h-4" />
                  <span>Interrupt AI</span>
                </button>

                {/* End Session */}
                <button
                  type="button"
                  onClick={handleStopSession}
                  className="inline-flex items-center space-x-2 px-5 py-2.5 rounded-full text-sm font-semibold text-white bg-rose-600 hover:bg-rose-700 shadow-md shadow-rose-600/25 transition-colors"
                  title="End current voice conversation"
                >
                  <PhoneOff className="w-4 h-4" />
                  <span>End Session</span>
                </button>
              </>
            )}
          </div>

          <div className="mt-8 flex items-center justify-center space-x-2 text-xs text-slate-500">
            <Info className="w-4 h-4 text-slate-400" />
            <span>Voice-first audio stream (24kHz 16-bit linear PCM). Speak naturally into your microphone.</span>
          </div>
        </div>

        {/* Dynamic Site Visit Booking Confirmation Card */}
        {siteVisitBooking && (
          <div className="bg-emerald-50 border-2 border-emerald-300 rounded-2xl p-6 sm:p-8 shadow-sm">
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
