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
    const camera = new THREE.PerspectiveCamera(40, width / height, 0.1, 50);
    camera.position.set(0, 0, 3.1);

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

    // 3. Dynamic Studio Lights
    const ambientLight = new THREE.AmbientLight(0xffffff, 1.0);
    scene.add(ambientLight);

    const cyanLight = new THREE.PointLight(0x00f5ff, 4.5, 6.0);
    cyanLight.position.set(0.8, 0.5, 0.8);
    scene.add(cyanLight);

    const amberLight = new THREE.PointLight(0xf59e0b, 4.0, 6.0);
    amberLight.position.set(-0.8, -0.4, 0.8);
    scene.add(amberLight);

    // Root Group
    const rootGroup = new THREE.Group();
    scene.add(rootGroup);

    // =========================================================================
    // 1. DENSE VOLUMETRIC ENERGY CORE (Solid, rich, vibrant base - eliminates "lean")
    // =========================================================================
    const coreGroup = new THREE.Group();
    rootGroup.add(coreGroup);

    // Hot White Inner Sun
    const innerSunGeo = new THREE.SphereGeometry(0.22, 32, 32);
    const innerSunMat = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 0.95,
    });
    const innerSunMesh = new THREE.Mesh(innerSunGeo, innerSunMat);
    coreGroup.add(innerSunMesh);

    // Rich Glowing Plasma Mantle
    const mantleGeo = new THREE.SphereGeometry(0.40, 32, 32);
    const mantleMat = new THREE.MeshBasicMaterial({
      color: 0x00f5ff,
      transparent: true,
      opacity: 0.55,
      blending: THREE.AdditiveBlending,
    });
    const mantleMesh = new THREE.Mesh(mantleGeo, mantleMat);
    coreGroup.add(mantleMesh);

    // Deep Amber/Cyan Volumetric Atmosphere
    const atmoGeo = new THREE.SphereGeometry(0.58, 32, 32);
    const atmoMat = new THREE.MeshBasicMaterial({
      color: 0x0284c7,
      transparent: true,
      opacity: 0.28,
      blending: THREE.AdditiveBlending,
    });
    const atmoMesh = new THREE.Mesh(atmoGeo, atmoMat);
    coreGroup.add(atmoMesh);

    // =========================================================================
    // 2. HORIZONTAL MUSICAL WAVEFORM EQUALIZER (Full-width dual-colored audio bars)
    // =========================================================================
    const waveGroup = new THREE.Group();
    rootGroup.add(waveGroup);

    const barCount = 96;
    const barVertices = new Float32Array(barCount * 2 * 3);
    const barColors = new Float32Array(barCount * 2 * 3);

    const colGoldenAmber = new THREE.Color(0xfbbf24);
    const colFieryOrange = new THREE.Color(0xf97316);
    const colNeonCyan = new THREE.Color(0x00f5ff);
    const colDeepAqua = new THREE.Color(0x0284c7);

    for (let i = 0; i < barCount; i++) {
      const norm = i / (barCount - 1); // 0 to 1
      const x = (norm - 0.5) * 1.68; // -0.84 to +0.84 across the sphere

      // Base point
      barVertices[i * 6] = x;
      barVertices[i * 6 + 1] = 0;
      barVertices[i * 6 + 2] = 0.08;

      // Peak point
      barVertices[i * 6 + 3] = x;
      barVertices[i * 6 + 4] = 0;
      barVertices[i * 6 + 5] = 0.08;

      // Color split: Amber/Gold on left, Neon Aqua/Cyan on right
      const c = new THREE.Color();
      if (norm < 0.48) {
        c.copy(colFieryOrange).lerp(colGoldenAmber, norm / 0.48);
      } else if (norm > 0.52) {
        c.copy(colNeonCyan).lerp(colDeepAqua, (norm - 0.52) / 0.48);
      } else {
        c.copy(colGoldenAmber).lerp(colNeonCyan, (norm - 0.48) / 0.04);
      }

      barColors[i * 6] = c.r;
      barColors[i * 6 + 1] = c.g;
      barColors[i * 6 + 2] = c.b;

      barColors[i * 6 + 3] = Math.min(1.0, c.r * 1.3);
      barColors[i * 6 + 4] = Math.min(1.0, c.g * 1.3);
      barColors[i * 6 + 5] = Math.min(1.0, c.b * 1.3);
    }

    const barGeo = new THREE.BufferGeometry();
    barGeo.setAttribute("position", new THREE.BufferAttribute(barVertices, 3));
    barGeo.setAttribute("color", new THREE.BufferAttribute(barColors, 3));

    const barMat = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.95,
      blending: THREE.AdditiveBlending,
      linewidth: 3,
    });
    const waveformLines = new THREE.LineSegments(barGeo, barMat);
    waveGroup.add(waveformLines);

    // Continuous Fluid Waveform Ribbon (Smooth surface contour)
    const ribbonPointCount = 120;
    const ribbonGeo = new THREE.BufferGeometry();
    const ribbonPositions = new Float32Array(ribbonPointCount * 3);
    for (let i = 0; i < ribbonPointCount; i++) {
      const norm = i / (ribbonPointCount - 1);
      ribbonPositions[i * 3] = (norm - 0.5) * 1.68;
      ribbonPositions[i * 3 + 1] = 0;
      ribbonPositions[i * 3 + 2] = 0.08;
    }
    ribbonGeo.setAttribute(
      "position",
      new THREE.BufferAttribute(ribbonPositions, 3)
    );
    const ribbonMat = new THREE.LineBasicMaterial({
      color: 0x38bdf8,
      transparent: true,
      opacity: 0.85,
      blending: THREE.AdditiveBlending,
    });
    const waveRibbon = new THREE.Line(ribbonGeo, ribbonMat);
    waveGroup.add(waveRibbon);

    // =========================================================================
    // 3. 360° CIRCULAR RADIAL EQUALIZER (Circular Spectrum Analyzer around Core)
    // =========================================================================
    const radialGroup = new THREE.Group();
    rootGroup.add(radialGroup);

    const radialBarCount = 72;
    const radialVertices = new Float32Array(radialBarCount * 2 * 3);
    const radialColors = new Float32Array(radialBarCount * 2 * 3);

    const baseRadius = 0.62;
    for (let i = 0; i < radialBarCount; i++) {
      const angle = (i / radialBarCount) * Math.PI * 2;
      const cosA = Math.cos(angle);
      const sinA = Math.sin(angle);

      // Inner point
      radialVertices[i * 6] = baseRadius * cosA;
      radialVertices[i * 6 + 1] = baseRadius * sinA;
      radialVertices[i * 6 + 2] = 0;

      // Outer point
      radialVertices[i * 6 + 3] = (baseRadius + 0.05) * cosA;
      radialVertices[i * 6 + 4] = (baseRadius + 0.05) * sinA;
      radialVertices[i * 6 + 5] = 0;

      // Circular rainbow spectrum: amber -> cyan -> violet
      const rColor = new THREE.Color();
      const fraction = i / radialBarCount;
      if (fraction < 0.5) {
        rColor.copy(colGoldenAmber).lerp(colNeonCyan, fraction / 0.5);
      } else {
        rColor.copy(colNeonCyan).lerp(new THREE.Color(0xa855f7), (fraction - 0.5) / 0.5);
      }

      radialColors[i * 6] = rColor.r;
      radialColors[i * 6 + 1] = rColor.g;
      radialColors[i * 6 + 2] = rColor.b;

      radialColors[i * 6 + 3] = rColor.r * 1.2;
      radialColors[i * 6 + 4] = rColor.g * 1.2;
      radialColors[i * 6 + 5] = rColor.b * 1.2;
    }

    const radialGeo = new THREE.BufferGeometry();
    radialGeo.setAttribute("position", new THREE.BufferAttribute(radialVertices, 3));
    radialGeo.setAttribute("color", new THREE.BufferAttribute(radialColors, 3));

    const radialMat = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.85,
      blending: THREE.AdditiveBlending,
    });
    const radialEqualizer = new THREE.LineSegments(radialGeo, radialMat);
    radialGroup.add(radialEqualizer);

    // =========================================================================
    // 4. DENSE MUSICAL DUST & SPARK EMBERS (3,000+ points filling the volume)
    // =========================================================================
    const particleCount = 2800;
    const pPositions = new Float32Array(particleCount * 3);
    const pColors = new Float32Array(particleCount * 3);
    const pAngles = new Float32Array(particleCount);
    const pRadii = new Float32Array(particleCount);
    const pSpeeds = new Float32Array(particleCount);
    const pFreqIdx = new Float32Array(particleCount);

    for (let i = 0; i < particleCount; i++) {
      const u = Math.random();
      const v = Math.random();
      const theta = u * 2.0 * Math.PI;
      const phi = Math.acos(2.0 * v - 1.0);
      const r = 0.30 + Math.pow(Math.random(), 0.6) * 0.62; // 0.30 to 0.92

      pRadii[i] = r;
      pAngles[i] = theta;
      pSpeeds[i] = (Math.random() * 0.5 + 0.25) * (Math.random() > 0.5 ? 1 : -1);
      pFreqIdx[i] = Math.floor(Math.random() * barCount);

      pPositions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      pPositions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      pPositions[i * 3 + 2] = r * Math.cos(phi);

      const pCol = new THREE.Color();
      const isAmberSide = pPositions[i * 3] < 0;
      if (isAmberSide) {
        pCol.copy(colGoldenAmber).lerp(colFieryOrange, Math.random() * 0.6);
      } else {
        pCol.copy(colNeonCyan).lerp(new THREE.Color(0x818cf8), Math.random() * 0.6);
      }

      pColors[i * 3] = pCol.r;
      pColors[i * 3 + 1] = pCol.g;
      pColors[i * 3 + 2] = pCol.b;
    }

    const pGeo = new THREE.BufferGeometry();
    pGeo.setAttribute("position", new THREE.BufferAttribute(pPositions, 3));
    pGeo.setAttribute("color", new THREE.BufferAttribute(pColors, 3));

    const pMat = new THREE.PointsMaterial({
      size: 0.026,
      vertexColors: true,
      transparent: true,
      opacity: 0.88,
      blending: THREE.AdditiveBlending,
    });
    const musicalDust = new THREE.Points(pGeo, pMat);
    rootGroup.add(musicalDust);

    // Musical Sparks / Explosive Embers (Active & pop with beats)
    const sparkCount = 110;
    const sparkPositions = new Float32Array(sparkCount * 3);
    const sparkColors = new Float32Array(sparkCount * 3);
    const sparkVelocities: THREE.Vector3[] = [];

    for (let i = 0; i < sparkCount; i++) {
      const angle = Math.random() * Math.PI * 2;
      const dist = 0.35 + Math.random() * 0.45;
      sparkPositions[i * 3] = dist * Math.cos(angle);
      sparkPositions[i * 3 + 1] = (Math.random() - 0.5) * 0.2;
      sparkPositions[i * 3 + 2] = dist * Math.sin(angle);

      const speed = 0.25 + Math.random() * 0.6;
      sparkVelocities.push(
        new THREE.Vector3(
          Math.cos(angle) * speed,
          (Math.random() - 0.5) * 0.4,
          Math.sin(angle) * speed
        )
      );

      const isAmber = Math.random() > 0.5;
      const sCol = isAmber ? colGoldenAmber : colNeonCyan;
      sparkColors[i * 3] = sCol.r;
      sparkColors[i * 3 + 1] = sCol.g;
      sparkColors[i * 3 + 2] = sCol.b;
    }

    const sparkGeo = new THREE.BufferGeometry();
    sparkGeo.setAttribute("position", new THREE.BufferAttribute(sparkPositions, 3));
    sparkGeo.setAttribute("color", new THREE.BufferAttribute(sparkColors, 3));

    const sparkMat = new THREE.PointsMaterial({
      size: 0.042,
      vertexColors: true,
      transparent: true,
      opacity: 0.95,
      blending: THREE.AdditiveBlending,
    });
    const sparkPoints = new THREE.Points(sparkGeo, sparkMat);
    rootGroup.add(sparkPoints);

    // =========================================================================
    // 5. CONCENTRIC EQUALIZER SOUNDWAVE RINGS (Pulsing Subwoofer Shockwaves)
    // =========================================================================
    const ring1Geo = new THREE.TorusGeometry(0.88, 0.024, 16, 64);
    const ring1Mat = new THREE.MeshBasicMaterial({
      color: 0x00f5ff,
      transparent: true,
      opacity: 0.70,
      blending: THREE.AdditiveBlending,
    });
    const ring1Mesh = new THREE.Mesh(ring1Geo, ring1Mat);
    ring1Mesh.rotation.x = Math.PI / 2.2;
    rootGroup.add(ring1Mesh);

    const ring2Geo = new THREE.TorusGeometry(0.92, 0.020, 16, 64);
    const ring2Mat = new THREE.MeshBasicMaterial({
      color: 0xf59e0b,
      transparent: true,
      opacity: 0.60,
      blending: THREE.AdditiveBlending,
    });
    const ring2Mesh = new THREE.Mesh(ring2Geo, ring2Mat);
    ring2Mesh.rotation.x = -Math.PI / 2.6;
    ring2Mesh.rotation.y = Math.PI / 5;
    rootGroup.add(ring2Mesh);

    // =========================================================================
    // 6. 60 FPS MUSICAL RENDER LOOP
    // =========================================================================
    let animationFrameId: number;
    const clock = new THREE.Clock();

    const animate = () => {
      animationFrameId = requestAnimationFrame(animate);
      const delta = clock.getDelta();
      const elapsed = clock.getElapsedTime();

      const currentState = stateRef.current;
      const currentVoice = voiceStateRef.current;
      const currentAudio = Math.min(1.0, Math.max(0.0, audioLevelRef.current));

      const isSpeaking = currentState === "SPEAKING" || currentVoice === "speaking";
      const isThinking = currentState === "THINKING" || currentVoice === "thinking";
      const isListening = currentState === "LISTENING" || currentVoice === "listening";

      const speedFactor = reducedMotion ? 0.2 : 1.0;

      // Base musical energy: even in Standby, keep an organic rhythmic musical idle
      const baseEnergy = isSpeaking
        ? 0.35 + currentAudio * 0.95
        : isThinking
        ? 0.28 + Math.sin(elapsed * 6.0) * 0.12
        : isListening
        ? 0.22 + Math.sin(elapsed * 4.0) * 0.08
        : 0.18 + Math.sin(elapsed * 2.5) * 0.06;

      // Gyroscopic 3D Rotation
      rootGroup.rotation.y += delta * 0.40 * speedFactor * (isSpeaking ? 1.4 : 1.0);
      rootGroup.rotation.x = Math.sin(elapsed * 0.6) * 0.10;

      ring1Mesh.rotation.z += delta * 0.8 * speedFactor;
      ring2Mesh.rotation.z -= delta * 0.6 * speedFactor;

      // 1. Core Pulsing & Breathing (Dense plasma volume)
      const corePulse = 1.0 + baseEnergy * 0.35 + Math.sin(elapsed * 8.0) * 0.04;
      innerSunMesh.scale.set(corePulse, corePulse, corePulse);
      mantleMesh.scale.set(corePulse * 1.08, corePulse * 1.08, corePulse * 1.08);
      atmoMesh.scale.set(corePulse * 1.15, corePulse * 1.15, corePulse * 1.15);

      cyanLight.intensity = 3.5 + baseEnergy * 4.0;
      amberLight.intensity = 3.0 + baseEnergy * 3.5;

      // 2. Horizontal Waveform Bars Modulation
      const barPos = barGeo.attributes.position as THREE.BufferAttribute;
      const bArr = barPos.array as Float32Array;
      const ribPos = ribbonGeo.attributes.position as THREE.BufferAttribute;
      const rArr = ribPos.array as Float32Array;

      for (let i = 0; i < barCount; i++) {
        const norm = i / (barCount - 1);
        const bellCurve = Math.sin(norm * Math.PI); // Highest in center

        // Complex musical harmonics
        const freq1 = Math.sin(norm * 24 + elapsed * 12) * 0.38;
        const freq2 = Math.cos(norm * 14 - elapsed * 9) * 0.32;
        const freq3 = Math.sin(norm * 38 + elapsed * 18) * 0.22;
        const totalHarmonics = Math.abs(freq1 + freq2 + freq3);

        const amp = (0.05 + totalHarmonics * baseEnergy * 1.25) * bellCurve;

        // Top peak
        bArr[i * 6 + 1] = amp;
        // Bottom peak (symmetric musical spectrum)
        bArr[i * 6 + 4] = -amp;
      }
      barPos.needsUpdate = true;

      // Update fluid wave ribbon
      for (let i = 0; i < ribbonPointCount; i++) {
        const norm = i / (ribbonPointCount - 1);
        const bellCurve = Math.sin(norm * Math.PI);
        const wave =
          Math.sin(norm * 18 + elapsed * 10) * 0.28 +
          Math.cos(norm * 32 - elapsed * 14) * 0.18;
        rArr[i * 3 + 1] = Math.abs(wave) * baseEnergy * 1.1 * bellCurve;
      }
      ribPos.needsUpdate = true;

      // 3. 360° Circular Radial Equalizer Modulation
      const radPos = radialGeo.attributes.position as THREE.BufferAttribute;
      const radArr = radPos.array as Float32Array;

      for (let i = 0; i < radialBarCount; i++) {
        const angle = (i / radialBarCount) * Math.PI * 2;
        const cosA = Math.cos(angle);
        const sinA = Math.sin(angle);

        // Radial frequency modulation (bass kick effect)
        const radFreq =
          Math.sin(angle * 8 + elapsed * 11) * 0.08 +
          Math.cos(angle * 4 - elapsed * 7) * 0.06;
        const ext = Math.max(0.02, (0.04 + radFreq + baseEnergy * 0.28));

        // Update outer point
        radArr[i * 6 + 3] = (baseRadius + ext) * cosA;
        radArr[i * 6 + 4] = (baseRadius + ext) * sinA;
      }
      radPos.needsUpdate = true;
      radialEqualizer.rotation.z += delta * 0.25 * speedFactor;

      // 4. Musical Dust Orbit & Frequency Reaction
      const dustPos = pGeo.attributes.position as THREE.BufferAttribute;
      const dArr = dustPos.array as Float32Array;

      for (let i = 0; i < particleCount; i++) {
        pAngles[i] += delta * pSpeeds[i] * speedFactor * (1.0 + baseEnergy * 0.8);
        const theta = pAngles[i];
        const r = pRadii[i] + Math.sin(elapsed * 3.0 + i) * (0.02 + baseEnergy * 0.04);

        const y = dArr[i * 3 + 1];
        const horizR = Math.sqrt(Math.max(0, r * r - y * y));
        dArr[i * 3] = horizR * Math.cos(theta);
        dArr[i * 3 + 2] = horizR * Math.sin(theta);
      }
      dustPos.needsUpdate = true;

      // 5. Dynamic Ember Sparks
      const sparkPos = sparkGeo.attributes.position as THREE.BufferAttribute;
      const sArr = sparkPos.array as Float32Array;

      for (let i = 0; i < sparkCount; i++) {
        sArr[i * 3] += sparkVelocities[i].x * delta * (1.0 + baseEnergy * 2.0);
        sArr[i * 3 + 1] += sparkVelocities[i].y * delta * (1.0 + baseEnergy * 2.0);
        sArr[i * 3 + 2] += sparkVelocities[i].z * delta * (1.0 + baseEnergy * 2.0);

        const dist = Math.sqrt(
          sArr[i * 3] ** 2 + sArr[i * 3 + 1] ** 2 + sArr[i * 3 + 2] ** 2
        );
        if (dist > 0.94) {
          const a = Math.random() * Math.PI * 2;
          sArr[i * 3] = 0.25 * Math.cos(a);
          sArr[i * 3 + 1] = (Math.random() - 0.5) * 0.15;
          sArr[i * 3 + 2] = 0.25 * Math.sin(a);
        }
      }
      sparkPos.needsUpdate = true;

      // 6. Ring Shockwave Expansion
      const waveScale = 1.0 + baseEnergy * 0.22 + Math.sin(elapsed * 4.0) * 0.04;
      ring1Mesh.scale.set(waveScale, waveScale, waveScale);
      ring2Mesh.scale.set(waveScale * 0.96, waveScale * 0.96, waveScale * 0.96);

      renderer.render(scene, camera);
    };

    animate();

    // 7. Responsive Resize Observer
    const handleResize = () => {
      if (!container) return;
      const w = container.clientWidth || 288;
      const h = container.clientHeight || 288;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };

    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(container);

    // 8. Safe Cleanup
    return () => {
      cancelAnimationFrame(animationFrameId);
      resizeObserver.disconnect();
      renderer.dispose();
      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
      scene.clear();
    };
  }, [hasWebGL, reducedMotion]);

  // Status checks for HUD
  const isSpeaking = state === "SPEAKING" || voiceState === "speaking";
  const isThinking = state === "THINKING" || voiceState === "thinking";
  const isListening = state === "LISTENING" || voiceState === "listening";

  return (
    <div
      onClick={onClick}
      className={`relative flex items-center justify-center cursor-pointer select-none overflow-hidden rounded-full p-2 transition-transform duration-300 hover:scale-[1.03] active:scale-[0.98] ${className}`}
      title="Next-Gen Musical 3D Glass Energy Orb Visualizer"
    >
      {/* ================================================================= */}
      {/* 1. DEEP COSMIC OBSIDIAN BACKDROP                                  */}
      {/* Ensures rich, dark optical glass with high-contrast bloom         */}
      {/* ================================================================= */}
      <div
        className="absolute inset-2 rounded-full pointer-events-none transition-all duration-700"
        style={{
          background: isSpeaking
            ? "radial-gradient(circle at 45% 35%, #221c38 0%, #120e24 45%, #05040f 100%)"
            : isThinking
            ? "radial-gradient(circle at 45% 35%, #161b40 0%, #0a1029 50%, #030514 100%)"
            : "radial-gradient(circle at 45% 35%, #0d1a3c 0%, #060e22 45%, #02040d 100%)",
          boxShadow: isSpeaking
            ? "0 0 40px rgba(245, 158, 11, 0.4), inset 0 0 35px rgba(2, 6, 23, 0.95)"
            : "0 0 35px rgba(56, 189, 248, 0.35), inset 0 0 35px rgba(2, 6, 23, 0.95)",
        }}
      />

      {/* ================================================================= */}
      {/* 2. THREE.JS 3D MUSICAL EQUALIZER & ENERGY CANVAS                  */}
      {/* ================================================================= */}
      <div
        ref={containerRef}
        className="relative z-10 w-full h-full flex items-center justify-center overflow-hidden"
        aria-label={`Musical 3D Glass Energy Orb. State: ${state}`}
      />

      {/* ================================================================= */}
      {/* 3. PHYSICAL 3D OPTICAL GLASS SPECULAR REFLECTION                  */}
      {/* ================================================================= */}
      <div
        className="absolute inset-2 rounded-full pointer-events-none z-20"
        style={{
          background:
            "radial-gradient(ellipse at 38% 14%, rgba(255, 255, 255, 0.80) 0%, rgba(255, 255, 255, 0.25) 24%, transparent 54%), radial-gradient(ellipse at 50% 88%, rgba(56, 189, 248, 0.35) 0%, transparent 48%)",
          boxShadow:
            "inset 0 0 28px rgba(2, 6, 23, 0.9), inset 0 2px 6px rgba(255, 255, 255, 0.55), inset 0 -4px 16px rgba(56, 189, 248, 0.4)",
        }}
      />

      {/* ================================================================= */}
      {/* 4. METALLIC CYBER CHROME BEZEL RING                               */}
      {/* ================================================================= */}
      <div
        className="absolute inset-2 rounded-full pointer-events-none z-20 border transition-all duration-500"
        style={{
          borderColor: isSpeaking
            ? "rgba(251, 191, 36, 0.6)"
            : isThinking
            ? "rgba(168, 85, 247, 0.55)"
            : "rgba(56, 189, 248, 0.5)",
          boxShadow: isSpeaking
            ? "0 0 30px rgba(245, 158, 11, 0.35)"
            : "0 0 25px rgba(56, 189, 248, 0.3)",
        }}
      />

      {/* ================================================================= */}
      {/* 5. SCI-FI AUDIO EQUALIZER HUD OVERLAY                             */}
      {/* ================================================================= */}
      <div className="absolute inset-5 pointer-events-none z-30 flex flex-col justify-between">
        {/* Top-Right HUD Tag */}
        <div className="flex justify-end pr-2 pt-1">
          {isSpeaking ? (
            <span className="font-mono text-[9px] sm:text-[10px] font-bold tracking-widest text-amber-300 drop-shadow-[0_0_8px_rgba(251,191,36,0.9)] animate-pulse">
              LIVE SPECTRUM
            </span>
          ) : isThinking ? (
            <span className="font-mono text-[9px] sm:text-[10px] font-bold tracking-widest text-purple-300 drop-shadow-[0_0_8px_rgba(168,85,247,0.9)] animate-pulse">
              ANALYZING...
            </span>
          ) : isListening ? (
            <span className="font-mono text-[9px] sm:text-[10px] font-bold tracking-widest text-emerald-300 drop-shadow-[0_0_8px_rgba(52,211,153,0.9)] animate-pulse">
              LISTENING...
            </span>
          ) : (
            <span className="font-mono text-[8px] sm:text-[9px] font-semibold tracking-wider text-sky-300/80 drop-shadow-[0_0_6px_rgba(56,189,248,0.6)]">
              MUSICAL SPECTRUM
            </span>
          )}
        </div>

        {/* Bottom HUD: Live Equalizer Level Meter */}
        <div className="flex justify-between items-end px-2 pb-1 font-mono text-[7px] sm:text-[8px] tracking-widest">
          <span className="text-sky-300/60 flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping inline-block" />
            24kHz PCM
          </span>

          <div className="flex items-center gap-0.5">
            <span className="h-2 w-0.5 bg-amber-400/80 inline-block animate-pulse" />
            <span className="h-3 w-0.5 bg-amber-300 inline-block animate-pulse" />
            <span className="h-4 w-0.5 bg-sky-400 inline-block animate-pulse" />
            <span className="h-3 w-0.5 bg-cyan-300 inline-block animate-pulse" />
            <span className="h-2 w-0.5 bg-cyan-400/80 inline-block animate-pulse" />
          </div>
        </div>
      </div>
    </div>
  );
}
