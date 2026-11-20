"use client";

import React, { useEffect, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { clearStoredSession, getValidAccessToken } from "@/lib/api";
import { VoiceClient, VoiceState } from "@/lib/voice-client";
import { RobotState, mapBackendEventToRobotState, ROBOT_STATE_CONFIGS } from "@/lib/robot-state-machine";
import { RobotAvatar3D } from "./RobotAvatar3D";
import {
  Mic,
  MicOff,
  PhoneOff,
  Radio,
  Minimize2,
  X,
  Volume2,
  Calendar,
  CheckCircle2,
  AlertCircle,
  Sparkles,
} from "lucide-react";

interface RobotVoiceWidgetProps {
  initialOpen?: boolean;
}

export function RobotVoiceWidget({ initialOpen = false }: RobotVoiceWidgetProps) {
  const router = useRouter();
  const { session } = useAuth();
  const [isOpen, setIsOpen] = useState(initialOpen);
  const [robotState, setRobotState] = useState<RobotState>("IDLE");
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [isMuted, setIsMuted] = useState(false);
  const [mouthOpen, setMouthOpen] = useState(0);
  const [mouthWidth, setMouthWidth] = useState(0.5);
  const [audioLevel, setAudioLevel] = useState(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [siteVisitBooking, setSiteVisitBooking] = useState<any | null>(null);
  const [hasMicPermission, setHasMicPermission] = useState<boolean | null>(null);

  const voiceClientRef = useRef<VoiceClient | null>(null);
  const animFrameRef = useRef<number | null>(null);

  // Check microphone hardware availability without opening stream
  useEffect(() => {
    if (typeof navigator !== "undefined" && navigator.mediaDevices) {
      navigator.mediaDevices
        .enumerateDevices()
        .then((devices) => {
          const hasAudioInput = devices.some((d) => d.kind === "audioinput");
          setHasMicPermission(hasAudioInput);
        })
        .catch(() => setHasMicPermission(false));
    }

    return () => {
      handleEndSession();
    };
  }, []);

  // Real-time lip-sync sampling loop when speaking
  useEffect(() => {
    const sampleLipSync = () => {
      if (voiceClientRef.current) {
        const frame = voiceClientRef.current.getLipSyncFrame();
        setMouthOpen(frame.mouthOpen);
        setMouthWidth(frame.mouthWidth);
        setAudioLevel(frame.audioLevel);

        // Update robot state automatically based on live audio activity
        if (voiceState === "speaking" && frame.isSpeaking) {
          setRobotState("SPEAKING");
        }
      }
      animFrameRef.current = requestAnimationFrame(sampleLipSync);
    };

    animFrameRef.current = requestAnimationFrame(sampleLipSync);

    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [voiceState]);

  // Start voice session (ONLY upon deliberate user click)
  const handleStartSession = useCallback(async () => {
    const validToken = await getValidAccessToken();
    if (!validToken) {
      setErrorMessage("Your session has expired or requires verification. Please log in to speak with the Voice AI.");
      setRobotState("ERROR");
      return;
    }

    setErrorMessage(null);
    setSiteVisitBooking(null);
    setRobotState("CONNECTING");

    const sessionId = `customer_session_${Date.now()}`;
    const client = new VoiceClient({
      sessionId,
      accessToken: validToken,
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
          setRobotState("HAPPY");
        } else if (state === "error") {
          setRobotState("ERROR");
        } else if (state === "idle") {
          setRobotState("IDLE");
        }
      },
      onError: (err) => {
        setErrorMessage(err);
        setRobotState("ERROR");
        if (err.includes("1008") || err.toLowerCase().includes("authentication") || err.toLowerCase().includes("expired")) {
          clearStoredSession();
        }
      },
      onSessionCompleted: () => {
        setRobotState("HAPPY");
      },
      onSiteVisitBooked: (booking) => {
        setSiteVisitBooking(booking);
        setRobotState("HAPPY");
      },
      onToolStart: (toolName) => {
        setRobotState("THINKING");
      },
      onToolComplete: (toolName, success, data) => {
        const nextState = mapBackendEventToRobotState("tool_call_complete", {
          tool_name: toolName,
          success,
          data,
        });
        setRobotState(nextState);
      },
    });

    voiceClientRef.current = client;
    await client.start();
  }, [session]);

  const handleEndSession = useCallback(() => {
    if (voiceClientRef.current) {
      voiceClientRef.current.stop();
      voiceClientRef.current = null;
    }
    setVoiceState("idle");
    setRobotState("DISCONNECTED");
    setIsMuted(false);
    setMouthOpen(0);
    setAudioLevel(0);
  }, []);

  const handleToggleMute = () => {
    if (voiceClientRef.current) {
      const muted = voiceClientRef.current.toggleMute();
      setIsMuted(muted);
    }
  };

  const handleInterrupt = () => {
    if (voiceClientRef.current) {
      voiceClientRef.current.interrupt();
      setRobotState("LISTENING");
    }
  };

  const cfg = ROBOT_STATE_CONFIGS[robotState] || ROBOT_STATE_CONFIGS.IDLE;
  const isSessionActive = voiceState !== "idle" && voiceState !== "error";

  return (
    <div className="fixed bottom-4 right-4 sm:bottom-6 sm:right-6 z-50 select-none">
      {/* ------------------------------------------------------------- */}
      {/* 1. FLOATING MINIMIZED ROBOT BUTTON (When widget is closed)     */}
      {/* ------------------------------------------------------------- */}
      {!isOpen && (
        <div className="relative group">
          {/* Subtle Ambient Pulse Ring */}
          <div
            className="absolute -inset-1.5 rounded-full blur-md opacity-70 group-hover:opacity-100 transition-opacity animate-pulse"
            style={{ backgroundColor: cfg.primaryColor }}
          />

          <button
            type="button"
            onClick={() => setIsOpen(true)}
            className="relative flex items-center space-x-3 bg-white hover:bg-slate-50 border border-slate-200/80 rounded-full pl-2 pr-5 py-2 shadow-2xl transition-all duration-300 transform group-hover:scale-105 active:scale-95 focus:outline-none focus:ring-4 focus:ring-sky-200"
            aria-label="Open Real Estate Voice AI Assistant"
          >
            {/* 3D Robot Head Thumbnail */}
            <div className="w-12 h-12 rounded-full bg-sky-50 flex items-center justify-center overflow-hidden border-2 border-sky-100 shadow-inner">
              <RobotAvatar3D
                state={robotState}
                mouthOpen={mouthOpen}
                className="w-16 h-16 pointer-events-none transform -translate-y-0.5"
              />
            </div>

            {/* Label and Live Status Pill */}
            <div className="flex flex-col text-left">
              <span className="text-xs font-bold text-slate-900 tracking-tight flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5 text-sky-500" />
                Voice Assistance
              </span>
              <span className="text-[10px] font-semibold text-emerald-600 flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-ping" />
                {cfg.statusLabel}
              </span>
            </div>
          </button>
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* 2. EXPANDED VOICE-ONLY CONVERSATION PANEL                     */}
      {/* ------------------------------------------------------------- */}
      {isOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Real Estate Voice AI Conversation Panel"
          className="w-[340px] sm:w-[390px] bg-white/95 backdrop-blur-xl border border-sky-100 rounded-3xl shadow-2xl overflow-hidden flex flex-col transition-all duration-300 transform animate-in fade-in zoom-in-95"
        >
          {/* Header Bar */}
          <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-100 bg-slate-50/70">
            <div className="flex items-center space-x-2.5">
              <span
                className="w-2.5 h-2.5 rounded-full animate-pulse transition-colors"
                style={{ backgroundColor: cfg.primaryColor }}
              />
              <span className="text-xs font-extrabold uppercase tracking-wider text-slate-800">
                {cfg.statusLabel}
              </span>
            </div>

            <div className="flex items-center space-x-1">
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                className="p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-200/60 rounded-full transition-colors"
                title="Minimize conversation"
                aria-label="Minimize"
              >
                <Minimize2 className="w-4 h-4" />
              </button>
              <button
                type="button"
                onClick={() => {
                  handleEndSession();
                  setIsOpen(false);
                }}
                className="p-1.5 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-full transition-colors"
                title="End session and close"
                aria-label="Close"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Central 3D Robot Viewport */}
          <div className="relative flex flex-col items-center justify-center pt-4 pb-2 px-6 bg-gradient-to-b from-slate-900 to-slate-950 overflow-hidden">
            {/* Dynamic Halo Glow behind Robot */}
            <div
              className="absolute w-44 h-44 rounded-full blur-3xl opacity-40 transition-all duration-700 pointer-events-none"
              style={{
                backgroundColor: cfg.primaryColor,
                transform: `scale(${1.0 + audioLevel * 0.8})`,
              }}
            />

            {/* 3D Robot Avatar Component */}
            <RobotAvatar3D
              state={robotState}
              mouthOpen={mouthOpen}
              mouthWidth={mouthWidth}
              audioLevel={audioLevel}
              className="w-56 h-56 z-10"
            />

            {/* Active Voice Energy Ring */}
            <div className="relative w-full flex items-center justify-center mt-1 mb-2 z-10">
              {robotState === "SPEAKING" && (
                <div className="flex items-center space-x-1.5 text-sky-400 text-xs font-semibold">
                  <Volume2 className="w-4 h-4 animate-bounce" />
                  <span>AI Speaking</span>
                </div>
              )}
              {robotState === "LISTENING" && (
                <div className="flex items-center space-x-1.5 text-emerald-400 text-xs font-semibold">
                  <Radio className="w-4 h-4 animate-pulse" />
                  <span>Listening to you...</span>
                </div>
              )}
              {robotState === "THINKING" && (
                <div className="flex items-center space-x-1.5 text-indigo-400 text-xs font-semibold animate-pulse">
                  <Sparkles className="w-4 h-4" />
                  <span>Searching Genuine Inventory...</span>
                </div>
              )}
              {robotState === "IDLE" && (
                <span className="text-slate-400 text-xs">Voice-First Real Estate Assistant</span>
              )}
            </div>
          </div>

          {/* Site Visit Booking Confirmation Card (NO Chat History, verified data only) */}
          {siteVisitBooking && (
            <div className="mx-4 mt-3 p-3.5 bg-emerald-50 border border-emerald-200 rounded-2xl flex items-start space-x-3 shadow-sm animate-in fade-in slide-in-from-top-2">
              <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0 mt-0.5" />
              <div className="text-xs">
                <p className="font-bold text-emerald-950">Site Visit Confirmed!</p>
                <p className="text-emerald-800 mt-0.5">
                  Your physical property visit has been registered in the CRM calendar.
                </p>
                <div className="flex items-center space-x-1 text-emerald-700 font-medium mt-1">
                  <Calendar className="w-3.5 h-3.5" />
                  <span>Visit ID: {String(siteVisitBooking.data?.visit_id || siteVisitBooking.visit_id || "Active").slice(0, 8)}...</span>
                </div>
              </div>
            </div>
          )}

          {/* Error Banner */}
          {errorMessage && (
            <div className="mx-4 mt-3 p-3 bg-rose-50 border border-rose-200 rounded-2xl flex flex-col space-y-1.5 text-rose-800 text-xs shadow-sm">
              <div className="flex items-center space-x-2.5">
                <AlertCircle className="w-4 h-4 shrink-0 text-rose-600" />
                <span className="flex-1">{errorMessage}</span>
              </div>
              {!session?.accessToken && (
                <button
                  type="button"
                  onClick={() => {
                    setIsOpen(false);
                    router.push("/login");
                  }}
                  className="text-left font-bold text-rose-900 hover:underline pt-0.5 ml-6"
                >
                  Go to Login page &rarr;
                </button>
              )}
            </div>
          )}

          {/* Interactive Voice Controls (VOICE-ONLY: Zero text chat) */}
          <div className="p-5 flex flex-col space-y-3 bg-white">
            {!isSessionActive ? (
              !session?.accessToken ? (
                <button
                  type="button"
                  onClick={() => {
                    setIsOpen(false);
                    router.push("/login");
                  }}
                  className="w-full flex items-center justify-center space-x-2 py-3.5 px-4 bg-sky-600 hover:bg-sky-700 text-white font-bold rounded-2xl shadow-lg shadow-sky-600/25 transition-all transform active:scale-95 focus:outline-none focus:ring-4 focus:ring-sky-200"
                >
                  <Sparkles className="w-5 h-5" />
                  <span>Log In to Speak with AI</span>
                </button>
              ) : (
                // Start Button (Microphone is never activated until user clicks here)
                <button
                  type="button"
                  onClick={handleStartSession}
                  className="w-full flex items-center justify-center space-x-2 py-3.5 px-4 bg-sky-600 hover:bg-sky-700 text-white font-bold rounded-2xl shadow-lg shadow-sky-600/25 transition-all transform active:scale-95 focus:outline-none focus:ring-4 focus:ring-sky-200"
                >
                  <Mic className="w-5 h-5" />
                  <span>{voiceState === "error" ? "Retry Voice Conversation" : "Start Voice Conversation"}</span>
                </button>
              )
            ) : (
              // Active Conversation Controls
              <div className="flex items-center justify-between gap-2.5">
                {/* Mute / Unmute Button */}
                <button
                  type="button"
                  onClick={handleToggleMute}
                  className={`flex-1 flex items-center justify-center space-x-1.5 py-3 px-3 rounded-2xl font-semibold text-xs border transition-all ${
                    isMuted
                      ? "bg-amber-50 border-amber-300 text-amber-800 hover:bg-amber-100"
                      : "bg-slate-100 border-slate-200 text-slate-700 hover:bg-slate-200"
                  }`}
                  title={isMuted ? "Unmute microphone" : "Mute microphone"}
                  aria-label={isMuted ? "Unmute microphone" : "Mute microphone"}
                >
                  {isMuted ? <MicOff className="w-4 h-4 text-amber-600" /> : <Mic className="w-4 h-4" />}
                  <span>{isMuted ? "Unmute" : "Mute"}</span>
                </button>

                {/* Speech Interruption Control */}
                <button
                  type="button"
                  onClick={handleInterrupt}
                  className="flex-1 flex items-center justify-center space-x-1.5 py-3 px-3 bg-slate-100 hover:bg-slate-200 border border-slate-200 rounded-2xl font-semibold text-xs text-slate-700 transition-all"
                  title="Interrupt AI speaking"
                  aria-label="Interrupt AI speaking"
                >
                  <Radio className="w-4 h-4 text-sky-600" />
                  <span>Interrupt</span>
                </button>

                {/* End Conversation Button */}
                <button
                  type="button"
                  onClick={handleEndSession}
                  className="flex-1 flex items-center justify-center space-x-1.5 py-3 px-3 bg-rose-600 hover:bg-rose-700 text-white rounded-2xl font-semibold text-xs shadow-md shadow-rose-600/25 transition-all"
                  title="End conversation"
                  aria-label="End conversation"
                >
                  <PhoneOff className="w-4 h-4" />
                  <span>End</span>
                </button>
              </div>
            )}

            {/* Privacy & Compliance Assurance Notice */}
            <p className="text-[10px] text-center text-slate-400 font-medium pt-1">
              Voice Assistance • Real-time property advisor
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
