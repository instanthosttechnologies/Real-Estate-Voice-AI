"use client";

import React, { useEffect, useState } from "react";
import { RobotState, ROBOT_STATE_CONFIGS } from "@/lib/robot-state-machine";

interface RobotAvatarFallbackProps {
  state: RobotState;
  mouthOpen?: number; // 0.0 to 1.0
  mouthWidth?: number; // 0.0 to 1.0
  audioLevel?: number;
  className?: string;
}

export function RobotAvatarFallback({
  state,
  mouthOpen = 0,
  mouthWidth = 0.5,
  audioLevel = 0,
  className = "w-48 h-48",
}: RobotAvatarFallbackProps) {
  const [blink, setBlink] = useState(false);
  const config = ROBOT_STATE_CONFIGS[state] || ROBOT_STATE_CONFIGS.IDLE;

  // Natural blinking interval
  useEffect(() => {
    if (state === "DISCONNECTED") return;
    const interval = setInterval(() => {
      setBlink(true);
      setTimeout(() => setBlink(false), 160);
    }, 3800 + Math.random() * 2000);

    return () => clearInterval(interval);
  }, [state]);

  const eyeShape = blink ? "blink" : config.eyeShape;
  const mouthHeight = Math.max(4, Math.round(mouthOpen * 22));
  const mouthW = Math.max(16, Math.round(18 + mouthWidth * 16));

  return (
    <div className={`relative flex items-center justify-center select-none ${className}`}>
      {/* Background radial glow */}
      <div
        className="absolute inset-0 rounded-full blur-2xl transition-all duration-700 opacity-60"
        style={{ backgroundColor: config.primaryColor }}
      />

      {/* SVG Robot Avatar */}
      <svg
        viewBox="0 0 200 220"
        className="w-full h-full drop-shadow-xl z-10 transition-transform duration-500"
        style={{
          transform: `rotate(${config.headTiltZ * 40}deg) translateY(${state === "HAPPY" ? "-6px" : "0px"})`,
        }}
      >
        <defs>
          <linearGradient id="bodyGrad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#f8fafc" />
            <stop offset="60%" stopColor="#e2e8f0" />
            <stop offset="100%" stopColor="#cbd5e1" />
          </linearGradient>
          <linearGradient id="visorGrad" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="#0f172a" />
            <stop offset="100%" stopColor="#1e293b" />
          </linearGradient>
          <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>

        {/* Floating Thruster Base / Shadow */}
        <ellipse cx="100" cy="205" rx="35" ry="6" fill="rgba(15, 23, 42, 0.25)" />
        <ellipse
          cx="100"
          cy="195"
          rx="18"
          ry="5"
          fill={config.primaryColor}
          opacity="0.8"
          filter="url(#glow)"
        />

        {/* Robot Body / Chassis */}
        <path
          d="M 65 140 Q 100 130 135 140 L 125 185 Q 100 192 75 185 Z"
          fill="url(#bodyGrad)"
          stroke="#94a3b8"
          strokeWidth="2"
        />

        {/* Chest Status Light / Real Estate Badge */}
        <circle
          cx="100"
          cy="162"
          r="8"
          fill={config.primaryColor}
          filter="url(#glow)"
          className={state === "THINKING" || state === "LISTENING" ? "animate-pulse" : ""}
        />

        {/* Neck Pivot */}
        <rect x="92" y="125" width="16" height="15" rx="3" fill="#64748b" />

        {/* Antenna */}
        <line x1="100" y1="35" x2="100" y2="15" stroke="#94a3b8" strokeWidth="3" strokeLinecap="round" />
        <circle
          cx="100"
          cy="12"
          r="6"
          fill={config.primaryColor}
          filter="url(#glow)"
          className={state === "THINKING" ? "animate-ping" : ""}
        />

        {/* Left & Right Ear Sensor Rings */}
        <rect x="34" y="68" width="8" height="24" rx="4" fill="#64748b" />
        <circle
          cx="38"
          cy="80"
          r="4"
          fill={config.primaryColor}
          filter="url(#glow)"
        />

        <rect x="158" y="68" width="8" height="24" rx="4" fill="#64748b" />
        <circle
          cx="162"
          cy="80"
          r="4"
          fill={config.primaryColor}
          filter="url(#glow)"
        />

        {/* Robot Head Outer Shell */}
        <rect
          x="42"
          y="35"
          width="116"
          height="92"
          rx="28"
          fill="url(#bodyGrad)"
          stroke="#94a3b8"
          strokeWidth="2.5"
        />

        {/* Visor Screen Face */}
        <rect
          x="54"
          y="47"
          width="92"
          height="68"
          rx="18"
          fill="url(#visorGrad)"
        />

        {/* Digital Eyes */}
        {eyeShape === "blink" || eyeShape === "closed" ? (
          // Blinking / Sleeping line eyes
          <g stroke={config.primaryColor} strokeWidth="3" strokeLinecap="round" filter="url(#glow)">
            <line x1="68" y1="74" x2="86" y2="74" />
            <line x1="114" y1="74" x2="132" y2="74" />
          </g>
        ) : eyeShape === "happy" ? (
          // Happy smiling eyes (^_^)
          <g stroke={config.primaryColor} strokeWidth="3.5" strokeLinecap="round" fill="none" filter="url(#glow)">
            <path d="M 68 76 Q 77 66 86 76" />
            <path d="M 114 76 Q 123 66 132 76" />
          </g>
        ) : eyeShape === "confused" ? (
          // Questioning / Confused eyes (o_O)
          <g fill={config.primaryColor} filter="url(#glow)">
            <circle cx="77" cy="74" r="5" />
            <circle cx="123" cy="72" r="8" />
          </g>
        ) : eyeShape === "focused" ? (
          // Focused / Listening eyes (larger glowing dots)
          <g fill={config.primaryColor} filter="url(#glow)">
            <circle cx="77" cy="74" r="7.5" />
            <circle cx="123" cy="74" r="7.5" />
            <circle cx="79" cy="72" r="2.5" fill="#ffffff" />
            <circle cx="125" cy="72" r="2.5" fill="#ffffff" />
          </g>
        ) : (
          // Normal rounded eyes
          <g fill={config.primaryColor} filter="url(#glow)">
            <ellipse cx="77" cy="74" rx="7" ry="8" />
            <ellipse cx="123" cy="74" rx="7" ry="8" />
            <circle cx="79" cy="72" r="2" fill="#ffffff" />
            <circle cx="125" cy="72" r="2" fill="#ffffff" />
          </g>
        )}

        {/* Dynamic Mouth (Audio-Driven Lip Sync) */}
        {state === "SPEAKING" && mouthOpen > 0.05 ? (
          <rect
            x={100 - mouthW / 2}
            y={98 - mouthHeight / 2}
            width={mouthW}
            height={mouthHeight}
            rx={mouthHeight / 2}
            fill={config.primaryColor}
            filter="url(#glow)"
          />
        ) : state === "HAPPY" || state === "GREETING" ? (
          // Gentle smiling mouth
          <path
            d="M 88 97 Q 100 104 112 97"
            stroke={config.primaryColor}
            strokeWidth="3"
            strokeLinecap="round"
            fill="none"
            filter="url(#glow)"
          />
        ) : (
          // Neutral resting mouth
          <line
            x1="92"
            y1="98"
            x2="108"
            y2="98"
            stroke={config.primaryColor}
            strokeWidth="2.5"
            strokeLinecap="round"
            opacity="0.75"
          />
        )}
      </svg>
    </div>
  );
}
