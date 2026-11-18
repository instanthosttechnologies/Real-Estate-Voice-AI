"use client";

import React from "react";
import { Mic, Loader2, Volume2, MicOff, AlertCircle } from "lucide-react";
import { VoiceState } from "@/lib/voice-client";

interface VoiceOrbProps {
  state: VoiceState;
  onClick?: () => void;
}

export function VoiceOrb({ state, onClick }: VoiceOrbProps) {
  const getOrbConfig = () => {
    switch (state) {
      case "connecting":
        return {
          bg: "bg-amber-500",
          ring: "ring-amber-200",
          icon: <Loader2 className="w-12 h-12 text-white animate-spin" />,
          label: "Connecting to Nova 2.5 Sonic...",
          badge: "bg-amber-100 text-amber-800 border-amber-300",
        };
      case "listening":
        return {
          bg: "bg-emerald-600 animate-pulse",
          ring: "ring-emerald-200 animate-ping",
          icon: <Mic className="w-12 h-12 text-white" />,
          label: "Listening to your voice...",
          badge: "bg-emerald-100 text-emerald-800 border-emerald-300",
        };
      case "thinking":
        return {
          bg: "bg-indigo-600 animate-pulse",
          ring: "ring-indigo-200",
          icon: <Loader2 className="w-12 h-12 text-white animate-spin" />,
          label: "Searching properties & verifying availability...",
          badge: "bg-indigo-100 text-indigo-800 border-indigo-300",
        };
      case "speaking":
        return {
          bg: "bg-blue-600 animate-pulse",
          ring: "ring-blue-300",
          icon: <Volume2 className="w-12 h-12 text-white" />,
          label: "Voice AI Speaking...",
          badge: "bg-blue-100 text-blue-800 border-blue-300",
        };
      case "interrupted":
        return {
          bg: "bg-amber-600",
          ring: "ring-amber-200",
          icon: <MicOff className="w-12 h-12 text-white" />,
          label: "Interrupted",
          badge: "bg-amber-100 text-amber-800 border-amber-300",
        };
      case "error":
        return {
          bg: "bg-rose-600",
          ring: "ring-rose-200",
          icon: <AlertCircle className="w-12 h-12 text-white" />,
          label: "Connection Disrupted",
          badge: "bg-rose-100 text-rose-800 border-rose-300",
        };
      case "idle":
      default:
        return {
          bg: "bg-slate-700 hover:bg-emerald-600 transition-colors",
          ring: "ring-slate-200",
          icon: <Mic className="w-12 h-12 text-white" />,
          label: "Click to start speaking",
          badge: "bg-slate-100 text-slate-700 border-slate-300",
        };
    }
  };

  const config = getOrbConfig();

  return (
    <div className="flex flex-col items-center justify-center p-8">
      {/* Outer pulsating ring */}
      <div className="relative flex items-center justify-center">
        {state === "listening" && (
          <div className="absolute w-48 h-48 rounded-full bg-emerald-400 opacity-25 animate-ping"></div>
        )}
        {state === "speaking" && (
          <div className="absolute w-44 h-44 rounded-full bg-blue-400 opacity-30 animate-pulse"></div>
        )}

        {/* Central interactive voice button / orb */}
        <button
          type="button"
          onClick={onClick}
          className={`relative z-10 w-36 h-36 rounded-full flex items-center justify-center shadow-xl transition-all duration-300 transform active:scale-95 ${config.bg} focus:outline-none focus:ring-4 ${config.ring}`}
        >
          {config.icon}
        </button>
      </div>

      {/* State label badge */}
      <div className="mt-8 text-center">
        <span className={`inline-flex items-center px-4 py-1.5 rounded-full text-xs font-semibold border ${config.badge}`}>
          {state.toUpperCase()}
        </span>
        <p className="mt-3 text-base font-medium text-slate-700">{config.label}</p>
      </div>
    </div>
  );
}
