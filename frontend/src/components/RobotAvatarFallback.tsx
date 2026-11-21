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

  // Determine arm transform angles based on expressive state
  let leftArmRotate = 0;
  let rightArmRotate = 0;
  let leftHandY = 0;
  let rightHandY = 0;

  if (state === "THINKING") {
    rightArmRotate = -45; // Right hand raised near chin
    rightHandY = -15;
    leftArmRotate = 10;
  } else if (state === "SPEAKING") {
    leftArmRotate = Math.sin(Date.now() / 250) * 12 + 10;
    rightArmRotate = Math.cos(Date.now() / 250) * 14 - 10;
  } else if (state === "HAPPY" || state === "GREETING") {
    leftArmRotate = -28; // Arms raised in celebration / welcome
    rightArmRotate = 28;
    leftHandY = -10;
    rightHandY = -10;
  } else if (state === "CONFUSED") {
    rightArmRotate = -35;
    leftArmRotate = 5;
  } else if (state === "LISTENING") {
    leftArmRotate = 15;
    rightArmRotate = -15;
  }

  return (
    <div className={`relative flex items-center justify-center select-none ${className}`}>
      {/* Background radial glow */}
      <div
        className="absolute inset-0 rounded-full blur-2xl transition-all duration-700 opacity-60"
        style={{ backgroundColor: config.primaryColor }}
      />

      {/* SVG Robot Avatar with Head, Torso, Mouth, Eyes and Expressive Arms */}
      <svg
        viewBox="0 0 240 240"
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
        <ellipse cx="120" cy="225" rx="38" ry="6" fill="rgba(15, 23, 42, 0.25)" />
        <ellipse
          cx="120"
          cy="215"
          rx="20"
          ry="5"
          fill={config.primaryColor}
          opacity="0.8"
          filter="url(#glow)"
        />

        {/* Left Arm & Shoulder Joint */}
        <g style={{ transformOrigin: "85px 150px", transform: `rotate(${leftArmRotate}deg)` }}>
          <circle cx="85" cy="150" r="7" fill="#64748b" />
          <path d="M 85 150 L 60 178 L 52 195" fill="none" stroke="url(#bodyGrad)" strokeWidth="10" strokeLinecap="round" />
          <circle cx="52" cy={195 + leftHandY} r="6" fill="#475569" />
        </g>

        {/* Right Arm & Shoulder Joint */}
        <g style={{ transformOrigin: "155px 150px", transform: `rotate(${rightArmRotate}deg)` }}>
          <circle cx="155" cy="150" r="7" fill="#64748b" />
          <path d="M 155 150 L 180 178 L 188 195" fill="none" stroke="url(#bodyGrad)" strokeWidth="10" strokeLinecap="round" />
          <circle cx="188" cy={195 + rightHandY} r="6" fill="#475569" />
        </g>

        {/* Robot Body / Torso Chassis */}
        <path
          d="M 85 140 Q 120 130 155 140 L 145 200 Q 120 208 95 200 Z"
          fill="url(#bodyGrad)"
          stroke="#94a3b8"
          strokeWidth="2"
        />

        {/* Chest Status Light / Real Estate Badge */}
        <circle
          cx="120"
          cy="168"
          r="9"
          fill={config.primaryColor}
          filter="url(#glow)"
          className={state === "THINKING" || state === "LISTENING" ? "animate-pulse" : ""}
        />

        {/* Neck Pivot */}
        <rect x="112" y="125" width="16" height="15" rx="3" fill="#64748b" />

        {/* Proportional Humanoid Sky-Blue Cranial Helmet */}
        <ellipse
          cx="120"
          cy="75"
          rx="58"
          ry="50"
          fill="#0284c7"
          stroke="#0369a1"
          strokeWidth="2.5"
        />

        {/* Sculpted Ceramic White Face Mask & Jawline */}
        <path
          d="M 75 70 C 75 48, 165 48, 165 70 C 165 102, 148 122, 120 125 C 92 122, 75 102, 75 70 Z"
          fill="url(#bodyGrad)"
          stroke="#cbd5e1"
          strokeWidth="2"
        />

        {/* Left & Right Streamlined Ear Sensor Rings */}
        <rect x="56" y="66" width="7" height="22" rx="3.5" fill="#0284c7" />
        <circle cx="59.5" cy="77" r="4" fill="#00f5ff" filter="url(#glow)" />

        <rect x="177" y="66" width="7" height="22" rx="3.5" fill="#0284c7" />
        <circle cx="180.5" cy="77" r="4" fill="#00f5ff" filter="url(#glow)" />

        {/* Sky-Blue Eyebrows */}
        <line x1="86" y1="62" x2="104" y2="60" stroke="#0284c7" strokeWidth="2.5" strokeLinecap="round" />
        <line x1="136" y1="60" x2="154" y2="62" stroke="#0284c7" strokeWidth="2.5" strokeLinecap="round" />

        {/* Left Concentric Eye */}
        {eyeShape === "blink" || eyeShape === "closed" ? (
          <line
            x1="86"
            y1="75"
            x2="104"
            y2="75"
            stroke="#00f5ff"
            strokeWidth="3.5"
            strokeLinecap="round"
            filter="url(#glow)"
          />
        ) : eyeShape === "happy" ? (
          <path
            d="M 86 78 Q 95 65 104 78"
            fill="none"
            stroke="#00f5ff"
            strokeWidth="3.5"
            strokeLinecap="round"
            filter="url(#glow)"
          />
        ) : (
          <g>
            <circle cx="95" cy="74" r="10" fill="#00f5ff" filter="url(#glow)" />
            <circle cx="95" cy="74" r="6" fill="#0284c7" />
            <circle cx="97" cy="72" r="2" fill="#ffffff" />
          </g>
        )}

        {/* Right Concentric Eye */}
        {eyeShape === "blink" || eyeShape === "closed" ? (
          <line
            x1="136"
            y1="75"
            x2="154"
            y2="75"
            stroke="#00f5ff"
            strokeWidth="3.5"
            strokeLinecap="round"
            filter="url(#glow)"
          />
        ) : eyeShape === "happy" ? (
          <path
            d="M 136 78 Q 145 65 154 78"
            fill="none"
            stroke="#00f5ff"
            strokeWidth="3.5"
            strokeLinecap="round"
            filter="url(#glow)"
          />
        ) : (
          <g>
            <circle cx="145" cy="74" r="10" fill="#00f5ff" filter="url(#glow)" />
            <circle cx="145" cy="74" r="6" fill="#0284c7" />
            <circle cx="147" cy="72" r="2" fill="#ffffff" />
          </g>
        )}
        {/* Animated Mouth (Mouth height & width responsive to lip-sync) */}
        {state === "HAPPY" || state === "GREETING" ? (
          <path
            d="M 108 100 Q 120 110 132 100"
            fill="none"
            stroke={config.primaryColor}
            strokeWidth="3"
            strokeLinecap="round"
            filter="url(#glow)"
          />
        ) : (
          <rect
            x={120 - mouthW / 2}
            y={102 - mouthHeight / 2}
            width={mouthW}
            height={mouthHeight}
            rx={Math.min(mouthHeight / 2, 4)}
            fill={config.primaryColor}
            filter="url(#glow)"
          />
        )}
      </svg>
    </div>
  );
}
