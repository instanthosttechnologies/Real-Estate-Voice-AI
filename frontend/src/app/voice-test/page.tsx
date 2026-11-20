"use client";

import React, { useEffect, useState, useRef } from "react";
import { VoiceOrb } from "@/components/VoiceOrb";
import { RobotAvatar3D } from "@/components/RobotAvatar3D";
import { VoiceClient, VoiceState } from "@/lib/voice-client";
import {
  RobotState,
  mapBackendEventToRobotState,
  ROBOT_STATE_CONFIGS,
} from "@/lib/robot-state-machine";
import { createLocalTestSession } from "@/lib/api";
import {
  Mic,
  MicOff,
  PhoneOff,
  Sparkles,
  Radio,
  Eye,
  AlertTriangle,
  CheckCircle2,
  Database,
  ShieldAlert,
  Volume2,
  RotateCcw,
} from "lucide-react";

export default function LocalVoiceTestPage() {
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
  const [datasetName, setDatasetName] = useState<string>("Unified_AI_Dataset (166 verified records)");
  const [driverMode, setDriverMode] = useState<"MOCK" | "LIVE">("MOCK");
  const [driverMessage, setDriverMessage] = useState<string | null>(
    "Mock mode — real speech is disabled. Enable live Bedrock Nova Sonic testing to hear real spoken English."
  );
  const [modelId, setModelId] = useState<string>("amazon.nova-2-5-sonic");
  const [awsRegion, setAwsRegion] = useState<string>("ap-northeast-1");
  const [isStarting, setIsStarting] = useState(false);
  const [isProduction, setIsProduction] = useState(false);

  const voiceClientRef = useRef<VoiceClient | null>(null);
  const animFrameRef = useRef<number | null>(null);

  // Production check
  useEffect(() => {
    if (process.env.NODE_ENV === "production") {
      setIsProduction(true);
    }
  }, []);

  // Teardown on unmount
  useEffect(() => {
    return () => {
      handleStopSession();
    };
  }, []);

  // Real-time lip-sync sampling loop when active
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
    setIsStarting(true);
    setErrorMessage(null);
    setSessionWarning(null);
    setSessionCompletedMessage(null);
    setRobotState("CONNECTING");

    try {
      // 1. Authorize local loopback test session from backend
      const testSession = await createLocalTestSession();
      setDatasetName(testSession.dataset_name);
      if (testSession.driver_mode) setDriverMode(testSession.driver_mode);
      if (testSession.driver_message) setDriverMessage(testSession.driver_message);
      if (testSession.model_id) setModelId(testSession.model_id);
      if (testSession.aws_region) setAwsRegion(testSession.aws_region);

      // 2. Initialize VoiceClient with temporary server-authorized token
      const client = new VoiceClient({
        sessionId: testSession.session_id,
        accessToken: testSession.token,
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
        },
        onSessionWarning: (message, remainingSeconds) => {
          setSessionWarning(`Notice: Conversation will complete in ${remainingSeconds} seconds.`);
        },
        onSessionCompleted: (message) => {
          setSessionWarning(null);
          setSessionCompletedMessage(message);
          setRobotState("HAPPY");
        },
        onSiteVisitBooked: () => {
          setRobotState("HAPPY");
        },
        onToolStart: () => {
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
    } catch (err: any) {
      const msg = err.message || "Failed to start local test session.";
      setErrorMessage(msg);
      setRobotState("ERROR");
      setVoiceState("error");
    } finally {
      setIsStarting(false);
    }
  };

  const handleStopSession = () => {
    if (voiceClientRef.current) {
      voiceClientRef.current.stop();
      voiceClientRef.current = null;
    }
    setVoiceState("idle");
    setRobotState("IDLE");
    setIsMuted(false);
    setMouthOpen(0);
    setAudioLevel(0);
  };

  const handleToggleMute = () => {
    if (!voiceClientRef.current) return;
    const nextMuted = !isMuted;
    if (nextMuted) {
      voiceClientRef.current.mute();
    } else {
      voiceClientRef.current.unmute();
    }
    setIsMuted(nextMuted);
  };

  if (isProduction) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center p-6 text-white">
        <div className="max-w-md bg-slate-800 border border-rose-500/30 rounded-2xl p-6 text-center">
          <ShieldAlert className="w-12 h-12 text-rose-500 mx-auto mb-4" />
          <h1 className="text-xl font-bold text-rose-400">Local Test Mode Forbidden</h1>
          <p className="text-sm text-slate-300 mt-2">
            The customer-free voice testing route is strictly prohibited in production environments.
          </p>
        </div>
      </div>
    );
  }

  const isSessionActive = voiceState !== "idle" && voiceState !== "error" && voiceState !== "completed";
  const cfg = ROBOT_STATE_CONFIGS[robotState];

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950 text-slate-100 flex flex-col items-center justify-start p-4 sm:p-6">
      {/* Top Warning Banner with Driver Status */}
      <div className="w-full max-w-4xl bg-slate-900/90 border border-slate-800 rounded-2xl p-4 mb-6 backdrop-blur-md shadow-xl">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
          <div className="flex items-center space-x-3">
            <span className="flex h-3 w-3 relative">
              <span
                className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
                  driverMode === "LIVE" ? "bg-emerald-400" : "bg-amber-400"
                }`}
              ></span>
              <span
                className={`relative inline-flex rounded-full h-3 w-3 ${
                  driverMode === "LIVE" ? "bg-emerald-500" : "bg-amber-500"
                }`}
              ></span>
            </span>
            <div>
              <span className="text-xs font-black tracking-widest uppercase text-amber-400 bg-amber-500/20 px-2 py-0.5 rounded-full mr-2">
                LOCAL TEST MODE
              </span>
              <span className="text-sm font-semibold text-slate-200">
                Customer-Free Voice Sandbox
              </span>
            </div>
          </div>

          <div className="flex items-center flex-wrap gap-2 text-xs">
            {driverMode === "LIVE" ? (
              <span className="px-3 py-1 rounded-full font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 flex items-center space-x-1.5">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                <span>DRIVER: LIVE NOVA SONIC ({awsRegion})</span>
              </span>
            ) : (
              <span className="px-3 py-1 rounded-full font-bold bg-amber-500/20 text-amber-300 border border-amber-500/40 flex items-center space-x-1.5">
                <span className="w-2 h-2 rounded-full bg-amber-400"></span>
                <span>DRIVER: MOCK MODE (Real speech disabled — zero cloud cost)</span>
              </span>
            )}
            <div className="flex items-center space-x-1.5 text-slate-400 bg-slate-800/80 px-2.5 py-1 rounded-full border border-slate-700/60">
              <Database className="w-3.5 h-3.5 text-emerald-400" />
              <span>{datasetName}</span>
            </div>
          </div>
        </div>

        {/* Notice banner for mock or live */}
        {driverMode === "MOCK" && (
          <div className="mt-3 pt-3 border-t border-slate-800/80 text-xs text-amber-300/90 flex items-center space-x-2">
            <Volume2 className="w-4 h-4 text-amber-400 shrink-0" />
            <span>Mock mode — real speech is disabled. Enable live Bedrock Nova Sonic testing to hear real spoken English.</span>
          </div>
        )}
        {driverMode === "LIVE" && (
          <div className="mt-3 pt-3 border-t border-slate-800/80 text-xs text-emerald-300/90 flex items-center space-x-2">
            <Sparkles className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>Live Nova Sonic voice active ({modelId} via AWS Bedrock in {awsRegion}). Microphone audio streams directly to Bedrock.</span>
          </div>
        )}
      </div>

      {/* Main Sandbox Card */}
      <div className="w-full max-w-4xl bg-slate-900/80 border border-slate-800 rounded-3xl shadow-2xl overflow-hidden backdrop-blur-xl flex flex-col md:flex-row">
        {/* Left Column: Visualizer Viewport */}
        <div className="flex-1 flex flex-col items-center justify-center p-6 sm:p-8 bg-gradient-to-b from-slate-900/50 to-slate-950/80 relative">
          {/* Avatar Switcher */}
          <div className="absolute top-4 left-4 z-20 flex bg-slate-800/80 border border-slate-700/60 rounded-xl p-0.5">
            <button
              type="button"
              onClick={() => setAvatarMode("robot")}
              className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-all flex items-center space-x-1.5 ${
                avatarMode === "robot"
                  ? "bg-emerald-600 text-white shadow-md"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              <Eye className="w-3.5 h-3.5" />
              <span>3D Robot</span>
            </button>
            <button
              type="button"
              onClick={() => setAvatarMode("orb")}
              className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-all flex items-center space-x-1.5 ${
                avatarMode === "orb"
                  ? "bg-emerald-600 text-white shadow-md"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              <Radio className="w-3.5 h-3.5" />
              <span>Orb Visualizer</span>
            </button>
          </div>

          {/* Halo Glow */}
          <div
            className="absolute w-64 h-64 rounded-full blur-3xl opacity-30 transition-all duration-700 pointer-events-none"
            style={{
              backgroundColor: cfg.primaryColor,
              transform: `scale(${1.0 + audioLevel * 1.0})`,
            }}
          />

          {/* Visualizer Display */}
          <div className="w-72 h-72 sm:w-80 sm:h-80 flex items-center justify-center relative z-10 my-4">
            {avatarMode === "robot" ? (
              <RobotAvatar3D
                state={robotState}
                mouthOpen={mouthOpen}
                mouthWidth={mouthWidth}
                audioLevel={audioLevel}
                className="w-full h-full"
              />
            ) : (
              <VoiceOrb state={voiceState} />
            )}
          </div>

          {/* Status Label */}
          <div className="flex items-center space-x-2 mt-2 px-4 py-1.5 rounded-full bg-slate-800/80 border border-slate-700/50">
            <span
              className="w-2.5 h-2.5 rounded-full animate-pulse"
              style={{ backgroundColor: cfg.primaryColor }}
            />
            <span className="text-xs font-extrabold uppercase tracking-wider text-slate-200">
              {cfg.statusLabel}
            </span>
          </div>
        </div>

        {/* Right Column: Interactive Voice Controls & Environment Info */}
        <div className="w-full md:w-96 p-6 sm:p-8 flex flex-col justify-between border-t md:border-t-0 md:border-l border-slate-800 bg-slate-900/40">
          <div>
            <h2 className="text-lg font-bold text-white flex items-center space-x-2">
              <Sparkles className="w-5 h-5 text-emerald-400" />
              <span>Direct Voice Testing</span>
            </h2>
            <p className="text-xs text-slate-400 mt-1">
              Zero-registration loopback interface. Voice input triggers database queries against verified real estate inventory.
            </p>

            {/* Advance Warning Notice */}
            {sessionWarning && (
              <div className="mt-4 p-3 bg-amber-500/10 border border-amber-500/30 rounded-2xl flex items-start space-x-2.5 text-xs text-amber-300 animate-pulse">
                <Volume2 className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                <div className="flex-1">
                  <p className="font-semibold text-amber-200">Session Warning</p>
                  <p className="mt-0.5">{sessionWarning}</p>
                </div>
              </div>
            )}

            {/* Session Completed Friendly State */}
            {sessionCompletedMessage && (
              <div className="mt-4 p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-2xl flex items-start space-x-2.5 text-xs text-emerald-300">
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                <div className="flex-1">
                  <p className="font-semibold text-emerald-200">Conversation Completed</p>
                  <p className="mt-0.5">{sessionCompletedMessage}</p>
                </div>
              </div>
            )}

            {/* Error Notification (Only genuine errors) */}
            {errorMessage && (
              <div className="mt-4 p-3 bg-rose-500/10 border border-rose-500/30 rounded-2xl flex items-start space-x-2.5 text-xs text-rose-300">
                <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                <div className="flex-1">
                  <p className="font-semibold text-rose-200">Session Error</p>
                  <p className="mt-0.5">{errorMessage}</p>
                </div>
              </div>
            )}

            {/* Environment Security Rules Checklist */}
            <div className="mt-5 space-y-2.5 text-xs text-slate-300">
              <div className="flex items-center space-x-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                <span>Zero Customer Auth / No OTP required</span>
              </div>
              <div className="flex items-center space-x-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                <span>Loopback restricted (127.0.0.1 / ::1 only)</span>
              </div>
              <div className="flex items-center space-x-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                <span>Dry-run database protection enabled</span>
              </div>
              <div className="flex items-center space-x-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                <span>Continuous 10-min voice conversation with auto-renewal</span>
              </div>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="mt-8 space-y-3">
            {!isSessionActive ? (
              <button
                type="button"
                onClick={handleStartSession}
                disabled={isStarting}
                className="w-full flex items-center justify-center space-x-2 py-4 px-4 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-2xl shadow-lg shadow-emerald-600/30 transition-all transform active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-4 focus:ring-emerald-500/30"
              >
                {voiceState === "completed" ? (
                  <>
                    <Sparkles className="w-5 h-5 text-emerald-200" />
                    <span>Start New Conversation</span>
                  </>
                ) : voiceState === "error" ? (
                  <>
                    <RotateCcw className="w-5 h-5 animate-spin-reverse" />
                    <span>Retry Conversation</span>
                  </>
                ) : (
                  <>
                    <Mic className="w-5 h-5" />
                    <span>{isStarting ? "Authorizing..." : "Start Conversation"}</span>
                  </>
                )}
              </button>
            ) : (
              <div className="space-y-3">
                <div className="flex space-x-2">
                  <button
                    type="button"
                    onClick={handleToggleMute}
                    className={`flex-1 flex items-center justify-center space-x-2 py-3 px-4 rounded-xl font-bold text-xs border transition-all ${
                      isMuted
                        ? "bg-amber-500/20 border-amber-500/40 text-amber-300 hover:bg-amber-500/30"
                        : "bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700"
                    }`}
                  >
                    {isMuted ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
                    <span>{isMuted ? "Unmute Mic" : "Mute Mic"}</span>
                  </button>

                  <button
                    type="button"
                    onClick={handleStopSession}
                    className="flex-1 flex items-center justify-center space-x-2 py-3 px-4 bg-rose-600 hover:bg-rose-500 text-white font-bold text-xs rounded-xl shadow-lg shadow-rose-600/20 transition-all transform active:scale-95"
                  >
                    <PhoneOff className="w-4 h-4" />
                    <span>End Session</span>
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
