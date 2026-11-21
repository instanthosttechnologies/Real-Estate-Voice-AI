"use client";

import React from "react";
import { VoiceState } from "@/lib/voice-client";
import { RobotState } from "@/lib/robot-state-machine";
import { OrbVisualizer } from "./OrbVisualizer";

interface VoiceOrbProps {
  state: VoiceState;
  audioLevel?: number;
  onClick?: () => void;
  className?: string;
}

const VOICE_TO_ROBOT_STATE: Record<VoiceState, RobotState> = {
  idle: "IDLE",
  connecting: "CONNECTING",
  listening: "LISTENING",
  thinking: "THINKING",
  speaking: "SPEAKING",
  interrupted: "LISTENING",
  completed: "HAPPY",
  error: "ERROR",
};

export function VoiceOrb({
  state,
  audioLevel = 0,
  onClick,
  className = "w-60 h-60 sm:w-64 sm:h-64",
}: VoiceOrbProps) {
  const mappedRobotState = VOICE_TO_ROBOT_STATE[state] || "IDLE";

  return (
    <OrbVisualizer
      state={mappedRobotState}
      voiceState={state}
      audioLevel={audioLevel}
      onClick={onClick}
      className={className}
    />
  );
}
