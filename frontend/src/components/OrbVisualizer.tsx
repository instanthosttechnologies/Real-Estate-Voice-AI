"use client";

import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { RobotState } from "@/lib/robot-state-machine";
import { VoiceState } from "@/lib/voice-client";

interface OrbVisualizerProps {
  state: RobotState;
  voiceState?: VoiceState;
  audioLevel?: number; // 0.0 to 1.0 real-time playback amplitude
  className?: string;
  onClick?: () => void;
}

/**
 * Premium Liquid Glass Energy Orb Visualizer
 *
 * Visual Characteristics:
 * - Solid luminous liquid glass sphere with authentic optical refraction (transmission & fresnel)
 * - White and icy sky-blue theme (#FFFFFF, #F0F9FF, #E0F2FE, #38BDF8, #0EA5E9)
 * - Concentric smooth circular energy rings
 * - Glowing central energy core with gentle internal floating particles
 * - Audio-reactive pulsation in speaking state driven by real-time PCM amplitude
 * - Smooth state transitions: Idle, Listening, Thinking (subtle blue-violet), Speaking
 * - Zero black background, zero orange/red artifacts, zero spiky equalizer bars
 */
export function OrbVisualizer({
  state,
  voiceState = "idle",
  audioLevel = 0,
  className = "w-64 h-64 sm:w-72 sm:h-72",
  onClick,
}: OrbVisualizerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [hasWebGL, setHasWebGL] = useState<boolean | null>(null);
  const [reducedMotion, setReducedMotion] = useState(false);

  // References to dynamic state for 60fps render loop
  const stateRef = useRef<RobotState>(state);
  stateRef.current = state;
  const voiceStateRef = useRef<VoiceState>(voiceState);
  voiceStateRef.current = voiceState;
  const audioLevelRef = useRef<number>(audioLevel);
  audioLevelRef.current = audioLevel;

  // WebGL detection & accessibility
  useEffect(() => {
    try {
      const canvas = document.createElement("canvas");
      const gl = !!(
        window.WebGLRenderingContext &&
        (canvas.getContext("webgl") || canvas.getContext("experimental-webgl"))
      );
      setHasWebGL(gl);
    } catch {
      setHasWebGL(false);
    }

    if (typeof window !== "undefined") {
      const media = window.matchMedia("(prefers-reduced-motion: reduce)");
      setReducedMotion(media.matches);
      const listener = (e: MediaQueryListEvent) => setReducedMotion(e.matches);
      media.addEventListener("change", listener);
      return () => media.removeEventListener("change", listener);
    }
  }, []);

  useEffect(() => {
    if (hasWebGL === false || !containerRef.current) return;

    const container = containerRef.current;
    const width = container.clientWidth || 288;
    const height = container.clientHeight || 288;

    // 1. Scene & Camera
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, width / height, 0.1, 50);
    camera.position.set(0, 0, 3.2);

    // 2. High-performance WebGL Renderer with Alpha & sRGB
    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: "high-performance",
    });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    container.appendChild(renderer.domElement);

    // 3. Studio Lighting: Ice-White & Sky-Blue Ambient/Point Lights
    const ambientLight = new THREE.AmbientLight(0xffffff, 1.2);
    scene.add(ambientLight);

    const cyanPoint = new THREE.PointLight(0x0ea5e9, 3.5, 8.0);
    cyanPoint.position.set(1.2, 0.8, 1.2);
    scene.add(cyanPoint);

    const skyPoint = new THREE.PointLight(0x38bdf8, 3.0, 8.0);
    skyPoint.position.set(-1.2, -0.6, 1.0);
    scene.add(skyPoint);

    const topWhiteRim = new THREE.DirectionalLight(0xffffff, 2.0);
    topWhiteRim.position.set(0, 2.5, 1.5);
    scene.add(topWhiteRim);

    // Root Group
    const rootGroup = new THREE.Group();
    scene.add(rootGroup);

    // =========================================================================
    // 1. GLOWING CENTRAL ENERGY CORE
    // =========================================================================
    const coreGroup = new THREE.Group();
    rootGroup.add(coreGroup);

    // Hot White Inner Sun
    const innerSunGeo = new THREE.SphereGeometry(0.24, 32, 32);
    const innerSunMat = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 0.98,
    });
    const innerSunMesh = new THREE.Mesh(innerSunGeo, innerSunMat);
    coreGroup.add(innerSunMesh);

    // Soft Cyan Luminous Mantle
    const mantleGeo = new THREE.SphereGeometry(0.42, 32, 32);
    const mantleMat = new THREE.MeshBasicMaterial({
      color: 0x0ea5e9,
      transparent: true,
      opacity: 0.55,
      blending: THREE.AdditiveBlending,
    });
    const mantleMesh = new THREE.Mesh(mantleGeo, mantleMat);
    coreGroup.add(mantleMesh);

    // Radiant Icy Atmosphere Halo
    const atmoGeo = new THREE.SphereGeometry(0.62, 32, 32);
    const atmoMat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      transparent: true,
      opacity: 0.30,
      blending: THREE.AdditiveBlending,
    });
    const atmoMesh = new THREE.Mesh(atmoGeo, atmoMat);
    coreGroup.add(atmoMesh);

    // =========================================================================
    // 2. GENTLE INTERNAL ENERGY PARTICLES
    // =========================================================================
    const particleCount = 54;
    const particlePositions = new Float32Array(particleCount * 3);
    const particleColors = new Float32Array(particleCount * 3);
    const particleBaseColors: THREE.Color[] = [];
    const particleVelocities: { x: number; y: number; z: number; speed: number }[] = [];

    const colWhite = new THREE.Color(0xffffff);
    const colSkyBlue = new THREE.Color(0x38bdf8);
    const colCyan = new THREE.Color(0x0ea5e9);
    const colBlueViolet = new THREE.Color(0x818cf8);

    for (let i = 0; i < particleCount; i++) {
      // Distribute particles inside sphere shell between radius 0.25 and 0.72
      const u = Math.random();
      const v = Math.random();
      const theta = u * 2.0 * Math.PI;
      const phi = Math.acos(2.0 * v - 1.0);
      const r = 0.25 + Math.random() * 0.46;

      const px = r * Math.sin(phi) * Math.cos(theta);
      const py = r * Math.sin(phi) * Math.sin(theta);
      const pz = r * Math.cos(phi);

      particlePositions[i * 3] = px;
      particlePositions[i * 3 + 1] = py;
      particlePositions[i * 3 + 2] = pz;

      const colChoice = Math.random();
      const chosenCol = new THREE.Color();
      if (colChoice < 0.35) {
        chosenCol.copy(colWhite);
      } else if (colChoice < 0.70) {
        chosenCol.copy(colSkyBlue);
      } else {
        chosenCol.copy(colCyan);
      }
      particleBaseColors.push(chosenCol.clone());

      particleColors[i * 3] = chosenCol.r;
      particleColors[i * 3 + 1] = chosenCol.g;
      particleColors[i * 3 + 2] = chosenCol.b;

      particleVelocities.push({
        x: (Math.random() - 0.5) * 0.08,
        y: (Math.random() - 0.5) * 0.08,
        z: (Math.random() - 0.5) * 0.08,
        speed: 0.4 + Math.random() * 0.6,
      });
    }

    const particleGeo = new THREE.BufferGeometry();
    particleGeo.setAttribute("position", new THREE.BufferAttribute(particlePositions, 3));
    particleGeo.setAttribute("color", new THREE.BufferAttribute(particleColors, 3));

    const particleMat = new THREE.PointsMaterial({
      size: 0.038,
      vertexColors: true,
      transparent: true,
      opacity: 0.90,
      blending: THREE.AdditiveBlending,
    });
    const particlePoints = new THREE.Points(particleGeo, particleMat);
    rootGroup.add(particlePoints);

    // =========================================================================
    // 3. SOLID LIQUID GLASS REFRACTIVE SPHERE
    // =========================================================================
    const glassGeo = new THREE.SphereGeometry(0.86, 64, 64);
    const glassMat = new THREE.MeshPhysicalMaterial({
      color: 0xffffff,
      transmission: 0.92,
      opacity: 0.98,
      transparent: true,
      roughness: 0.05,
      ior: 1.45,
      metalness: 0.02,
      clearcoat: 1.0,
      clearcoatRoughness: 0.04,
      sheen: 1.0,
      sheenColor: new THREE.Color(0x38bdf8),
      attenuationColor: new THREE.Color(0xe0f2fe),
      attenuationDistance: 1.1,
    });
    const glassSphere = new THREE.Mesh(glassGeo, glassMat);
    rootGroup.add(glassSphere);

    // =========================================================================
    // 4. SMOOTH CIRCULAR CONCENTRIC ENERGY RINGS
    // =========================================================================
    const ringGroup = new THREE.Group();
    rootGroup.add(ringGroup);

    // Primary Equatorial Energy Ring
    const ring1Geo = new THREE.TorusGeometry(1.06, 0.014, 16, 96);
    const ring1Mat = new THREE.MeshBasicMaterial({
      color: 0x0ea5e9,
      transparent: true,
      opacity: 0.75,
      blending: THREE.AdditiveBlending,
    });
    const ring1Mesh = new THREE.Mesh(ring1Geo, ring1Mat);
    ring1Mesh.rotation.x = Math.PI / 2.3;
    ringGroup.add(ring1Mesh);

    // Secondary Counter-Tilted Orbital Energy Ring
    const ring2Geo = new THREE.TorusGeometry(1.18, 0.010, 16, 96);
    const ring2Mat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      transparent: true,
      opacity: 0.55,
      blending: THREE.AdditiveBlending,
    });
    const ring2Mesh = new THREE.Mesh(ring2Geo, ring2Mat);
    ring2Mesh.rotation.x = -Math.PI / 2.6;
    ring2Mesh.rotation.y = Math.PI / 5;
    ringGroup.add(ring2Mesh);

    // =========================================================================
    // 5. 60 FPS LIQUID GLASS ANIMATION RENDER LOOP
    // =========================================================================
    let animationFrameId: number;
    const clock = new THREE.Clock();

    // Smooth lerping tracking values
    let smoothedAudio = 0;
    let thinkingColorProgress = 0;

    const animate = () => {
      animationFrameId = requestAnimationFrame(animate);
      const delta = clock.getDelta();
      const elapsed = clock.getElapsedTime();

      const currentState = stateRef.current;
      const currentVoice = voiceStateRef.current;
      const rawAudio = Math.min(1.0, Math.max(0.0, audioLevelRef.current));

      const isSpeaking = currentState === "SPEAKING" || currentVoice === "speaking";
      const isThinking = currentState === "THINKING" || currentVoice === "thinking";
      const isListening = currentState === "LISTENING" || currentVoice === "listening";

      const speed = reducedMotion ? 0.25 : 1.0;

      // Smooth audio attack and decay
      smoothedAudio += (rawAudio - smoothedAudio) * Math.min(1.0, delta * 14.0);

      // Smooth color transition for thinking state (accents of subtle blue-violet)
      const targetThinkingProgress = isThinking ? 1.0 : 0.0;
      thinkingColorProgress += (targetThinkingProgress - thinkingColorProgress) * Math.min(1.0, delta * 4.0);

      // 1. Organic Breathing & Pulsing
      let scaleTarget = 1.0;
      let coreTarget = 1.0;

      if (isSpeaking) {
        // Sphere pulses in proportion to actual assistant audio amplitude
        const audioPulse = smoothedAudio * 0.30;
        const fluidOsc = Math.sin(elapsed * 9.0) * (0.02 + smoothedAudio * 0.03);
        scaleTarget = 1.0 + audioPulse + fluidOsc;
        coreTarget = 1.0 + smoothedAudio * 0.45;
      } else if (isListening) {
        // Subtle inward pulsing & smooth sky-blue wave rhythm
        scaleTarget = 0.98 + Math.sin(elapsed * 2.8) * 0.03;
        coreTarget = 1.02 + Math.sin(elapsed * 2.8) * 0.04;
      } else if (isThinking) {
        // Gentle rotational rhythmic breathing
        scaleTarget = 0.99 + Math.sin(elapsed * 2.0) * 0.02;
        coreTarget = 1.0 + Math.sin(elapsed * 4.0) * 0.05;
      } else {
        // Idle: Gentle breathing motion & soft glow
        scaleTarget = 1.0 + Math.sin(elapsed * 1.5) * 0.022;
        coreTarget = 1.0 + Math.sin(elapsed * 1.5) * 0.03;
      }

      glassSphere.scale.set(scaleTarget, scaleTarget, scaleTarget);
      innerSunMesh.scale.set(coreTarget, coreTarget, coreTarget);
      mantleMesh.scale.set(coreTarget * 1.05, coreTarget * 1.05, coreTarget * 1.05);
      atmoMesh.scale.set(scaleTarget * 1.08, scaleTarget * 1.08, scaleTarget * 1.08);

      // 2. Light Intensities & Color Tuning
      const baseLuminance = isSpeaking ? 1.0 + smoothedAudio * 0.8 : 1.0;
      cyanPoint.intensity = 3.2 * baseLuminance;
      skyPoint.intensity = 2.8 * baseLuminance;

      if (thinkingColorProgress > 0.01) {
        const blendedCyan = colCyan.clone().lerp(colBlueViolet, thinkingColorProgress * 0.7);
        mantleMat.color.copy(blendedCyan);
        cyanPoint.color.copy(blendedCyan);
        glassMat.sheenColor.copy(colSkyBlue.clone().lerp(colBlueViolet, thinkingColorProgress * 0.5));
      } else {
        mantleMat.color.copy(colCyan);
        cyanPoint.color.copy(colCyan);
        glassMat.sheenColor.copy(colSkyBlue);
      }

      // 3. Energy Rings Dynamics
      const ringSpeed = (isSpeaking ? 1.4 : isThinking ? 1.2 : 0.8) * speed;
      ring1Mesh.rotation.z += delta * 0.75 * ringSpeed;
      ring2Mesh.rotation.z -= delta * 0.60 * ringSpeed;

      if (isSpeaking) {
        // Soft expanding cyan energy rings
        const ringScale = 1.0 + smoothedAudio * 0.18 + Math.sin(elapsed * 6.0) * 0.02;
        ring1Mesh.scale.set(ringScale, ringScale, ringScale);
        ring2Mesh.scale.set(ringScale * 1.04, ringScale * 1.04, ringScale * 1.04);
        ring1Mat.opacity = Math.min(0.95, 0.70 + smoothedAudio * 0.25);
        ring2Mat.opacity = Math.min(0.85, 0.50 + smoothedAudio * 0.25);
      } else if (isListening) {
        // Smooth sky-blue wave ripples in rings
        const ripple = Math.sin(elapsed * 3.5) * 0.04;
        ring1Mesh.scale.set(1.0 + ripple, 1.0 + ripple, 1.0 + ripple);
        ring2Mesh.scale.set(1.0 - ripple * 0.5, 1.0 - ripple * 0.5, 1.0 - ripple * 0.5);
        ring1Mat.opacity = 0.72 + ripple * 2.0;
        ring2Mat.opacity = 0.55 + ripple * 1.5;
      } else {
        ring1Mesh.scale.set(1.0, 1.0, 1.0);
        ring2Mesh.scale.set(1.0, 1.0, 1.0);
        ring1Mat.opacity = 0.70;
        ring2Mat.opacity = 0.50;
      }

      // 4. Internal Particles: Gentle Drift & Thinking Rotation
      const pPos = particleGeo.attributes.position as THREE.BufferAttribute;
      const pArr = pPos.array as Float32Array;
      const pCol = particleGeo.attributes.color as THREE.BufferAttribute;
      const cArr = pCol.array as Float32Array;

      const particleSpeed = (isThinking ? 1.5 : isSpeaking ? 1.2 : 0.6) * speed;
      const rotAngle = delta * 0.3 * particleSpeed;
      const cosR = Math.cos(rotAngle);
      const sinR = Math.sin(rotAngle);

      for (let i = 0; i < particleCount; i++) {
        let x = pArr[i * 3];
        let y = pArr[i * 3 + 1];
        let z = pArr[i * 3 + 2];

        // Rotation around Y/Z axis (especially graceful in thinking state)
        const rx = x * cosR - z * sinR;
        const rz = x * sinR + z * cosR;
        x = rx;
        z = rz;

        // Subtle fluid vertical drift
        y += Math.sin(elapsed * 1.8 + i) * 0.0006 * particleSpeed;

        pArr[i * 3] = x;
        pArr[i * 3 + 1] = y;
        pArr[i * 3 + 2] = z;

        // Color interpolation for thinking state
        if (thinkingColorProgress > 0.01) {
          const baseC = particleBaseColors[i];
          const currC = baseC.clone().lerp(colBlueViolet, thinkingColorProgress * 0.75);
          cArr[i * 3] = currC.r;
          cArr[i * 3 + 1] = currC.g;
          cArr[i * 3 + 2] = currC.b;
        } else {
          const baseC = particleBaseColors[i];
          cArr[i * 3] = baseC.r;
          cArr[i * 3 + 1] = baseC.g;
          cArr[i * 3 + 2] = baseC.b;
        }
      }
      pPos.needsUpdate = true;
      if (thinkingColorProgress > 0.01 || thinkingColorProgress === 0) {
        pCol.needsUpdate = true;
      }

      // 5. Gentle Gyroscopic Rotation of Root
      rootGroup.rotation.y += delta * 0.25 * speed;
      rootGroup.rotation.x = Math.sin(elapsed * 0.8) * 0.08;

      renderer.render(scene, camera);
    };

    animate();

    // Resize Handler
    const handleResize = () => {
      if (!containerRef.current) return;
      const w = containerRef.current.clientWidth || 288;
      const h = containerRef.current.clientHeight || 288;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    window.addEventListener("resize", handleResize);

    // Cleanup on unmount
    return () => {
      window.removeEventListener("resize", handleResize);
      cancelAnimationFrame(animationFrameId);

      renderer.dispose();
      innerSunGeo.dispose();
      innerSunMat.dispose();
      mantleGeo.dispose();
      mantleMat.dispose();
      atmoGeo.dispose();
      atmoMat.dispose();
      particleGeo.dispose();
      particleMat.dispose();
      glassGeo.dispose();
      glassMat.dispose();
      ring1Geo.dispose();
      ring1Mat.dispose();
      ring2Geo.dispose();
      ring2Mat.dispose();

      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
    };
  }, [hasWebGL, reducedMotion]);

  const isSpeaking = voiceState === "speaking" || state === "SPEAKING";
  const isListening = voiceState === "listening" || state === "LISTENING";
  const isThinking = voiceState === "thinking" || state === "THINKING";

  return (
    <div
      className={`relative rounded-full flex items-center justify-center select-none transition-transform duration-500 ${
        onClick ? "cursor-pointer hover:scale-[1.03]" : ""
      } ${className}`}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      aria-label={`Liquid Glass Energy Orb. State: ${voiceState}`}
    >
      {/* ================================================================= */}
      {/* 1. SOFT AMBIENT LIGHT AURA (No black background, pure light glow) */}
      {/* ================================================================= */}
      <div
        className="absolute inset-0 rounded-full pointer-events-none transition-all duration-700"
        style={{
          background: isSpeaking
            ? "radial-gradient(circle, rgba(14, 165, 233, 0.25) 0%, rgba(56, 189, 248, 0.12) 50%, transparent 72%)"
            : isThinking
            ? "radial-gradient(circle, rgba(129, 140, 248, 0.22) 0%, rgba(56, 189, 248, 0.10) 50%, transparent 72%)"
            : isListening
            ? "radial-gradient(circle, rgba(56, 189, 248, 0.24) 0%, rgba(224, 242, 254, 0.15) 50%, transparent 72%)"
            : "radial-gradient(circle, rgba(224, 242, 254, 0.30) 0%, rgba(56, 189, 248, 0.10) 55%, transparent 72%)",
          filter: "blur(18px)",
          transform: `scale(${1.0 + (isSpeaking ? audioLevel * 0.25 : 0)})`,
        }}
      />

      {/* ================================================================= */}
      {/* 2. THREE.JS 3D LIQUID GLASS ENERGY ORB CANVAS                    */}
      {/* ================================================================= */}
      {hasWebGL !== false ? (
        <div
          ref={containerRef}
          className="relative z-10 w-full h-full flex items-center justify-center overflow-hidden"
          aria-label={`Liquid Glass Energy Orb 3D canvas`}
        />
      ) : (
        /* Accessible Fallback when WebGL is unavailable */
        <div className="relative z-10 w-full h-full flex items-center justify-center">
          <div
            className="w-44 h-44 rounded-full border border-sky-200/60 shadow-lg animate-pulse"
            style={{
              background:
                "radial-gradient(circle at 35% 30%, #ffffff 0%, #e0f2fe 35%, #38bdf8 70%, #0ea5e9 100%)",
              boxShadow: "0 0 32px rgba(56, 189, 248, 0.4), inset 0 2px 8px #ffffff",
            }}
          />
        </div>
      )}

      {/* ================================================================= */}
      {/* 3. OPTICAL LIQUID GLASS CURVED SPECULAR HIGHLIGHT                 */}
      {/* ================================================================= */}
      <div
        className="absolute inset-2.5 rounded-full pointer-events-none z-20 transition-opacity duration-500"
        style={{
          background:
            "radial-gradient(ellipse at 32% 16%, rgba(255, 255, 255, 0.85) 0%, rgba(255, 255, 255, 0.30) 22%, transparent 52%), radial-gradient(ellipse at 50% 86%, rgba(56, 189, 248, 0.25) 0%, transparent 50%)",
          boxShadow:
            "inset 0 1px 4px rgba(255, 255, 255, 0.75), inset 0 -3px 12px rgba(56, 189, 248, 0.25)",
        }}
      />

      {/* ================================================================= */}
      {/* 4. SUBTLE TRANSLUCENT RIM BORDER                                  */}
      {/* ================================================================= */}
      <div
        className="absolute inset-2 rounded-full pointer-events-none z-20 border border-sky-300/40 transition-colors duration-500"
        style={{
          borderColor: isThinking
            ? "rgba(129, 140, 248, 0.45)"
            : isSpeaking
            ? "rgba(14, 165, 233, 0.55)"
            : "rgba(56, 189, 248, 0.35)",
        }}
      />
    </div>
  );
}
