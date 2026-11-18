"use client";

import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { RobotState, ROBOT_STATE_CONFIGS } from "@/lib/robot-state-machine";
import { RobotAvatarFallback } from "./RobotAvatarFallback";

interface RobotAvatar3DProps {
  state: RobotState;
  mouthOpen?: number; // 0.0 to 1.0
  mouthWidth?: number; // 0.0 to 1.0
  audioLevel?: number;
  className?: string;
  onClick?: () => void;
}

export function RobotAvatar3D({
  state,
  mouthOpen = 0,
  mouthWidth = 0.5,
  audioLevel = 0,
  className = "w-64 h-64",
  onClick,
}: RobotAvatar3DProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [hasWebGL, setHasWebGL] = useState<boolean | null>(null);
  const [reducedMotion, setReducedMotion] = useState(false);

  // References to animated 3D sub-objects
  const sceneRef = useRef<THREE.Scene | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const robotGroupRef = useRef<THREE.Group | null>(null);
  const headGroupRef = useRef<THREE.Group | null>(null);
  const leftEyeRef = useRef<THREE.Mesh | null>(null);
  const rightEyeRef = useRef<THREE.Mesh | null>(null);
  const mouthMeshRef = useRef<THREE.Mesh | null>(null);
  const antennaTipRef = useRef<THREE.Mesh | null>(null);
  const chestLightRef = useRef<THREE.Mesh | null>(null);
  const hoverRingRef = useRef<THREE.Mesh | null>(null);
  const pointLightRef = useRef<THREE.PointLight | null>(null);

  // Keep state & audio values updated in animation loop
  const stateRef = useRef<RobotState>(state);
  stateRef.current = state;
  const mouthOpenRef = useRef<number>(mouthOpen);
  mouthOpenRef.current = mouthOpen;
  const mouthWidthRef = useRef<number>(mouthWidth);
  mouthWidthRef.current = mouthWidth;

  // Mouse look tracking
  const targetLookX = useRef(0);
  const targetLookY = useRef(0);
  const currentLookX = useRef(0);
  const currentLookY = useRef(0);

  // WebGL availability and motion preference checks
  useEffect(() => {
    try {
      const canvas = document.createElement("canvas");
      const gl = !!(
        window.WebGLRenderingContext &&
        (canvas.getContext("webgl") || canvas.getContext("experimental-webgl"))
      );
      setHasWebGL(gl);
    } catch (e) {
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

  // Initialize Three.js 3D Robot Scene
  useEffect(() => {
    if (hasWebGL === false || !containerRef.current) return;

    const container = containerRef.current;
    const width = container.clientWidth || 256;
    const height = container.clientHeight || 256;

    // 1. Scene & Camera
    const scene = new THREE.Scene();
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(36, width / height, 0.1, 100);
    camera.position.set(0, 0.3, 3.8);

    // 2. Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    rendererRef.current = renderer;
    container.appendChild(renderer.domElement);

    // 3. Lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 1.2);
    scene.add(ambientLight);

    const keyLight = new THREE.DirectionalLight(0xffffff, 2.0);
    keyLight.position.set(2, 4, 3);
    scene.add(keyLight);

    const rimLight = new THREE.DirectionalLight(0x38bdf8, 1.5);
    rimLight.position.set(-3, -2, -2);
    scene.add(rimLight);

    const pointLight = new THREE.PointLight(0x0ea5e9, 2.5, 6);
    pointLight.position.set(0, 0.2, 1.2);
    scene.add(pointLight);
    pointLightRef.current = pointLight;

    // 4. Materials
    const whiteChassisMat = new THREE.MeshStandardMaterial({
      color: 0xf1f5f9,
      roughness: 0.25,
      metalness: 0.15,
    });

    const slateJointMat = new THREE.MeshStandardMaterial({
      color: 0x475569,
      roughness: 0.5,
      metalness: 0.6,
    });

    const visorMat = new THREE.MeshStandardMaterial({
      color: 0x090d16,
      roughness: 0.1,
      metalness: 0.85,
    });

    const glowColor = new THREE.Color(ROBOT_STATE_CONFIGS[stateRef.current].primaryColor);
    const eyeMat = new THREE.MeshBasicMaterial({ color: glowColor });
    const mouthMat = new THREE.MeshBasicMaterial({ color: glowColor });
    const antennaMat = new THREE.MeshBasicMaterial({ color: glowColor });
    const chestLightMat = new THREE.MeshBasicMaterial({ color: glowColor });
    const hoverRingMat = new THREE.MeshBasicMaterial({
      color: glowColor,
      transparent: true,
      opacity: 0.65,
    });

    // 5. Construct 3D Procedural Robot Hierarchy
    const robotGroup = new THREE.Group();
    scene.add(robotGroup);
    robotGroupRef.current = robotGroup;

    // --- Body Chassis ---
    const bodyGeo = new THREE.CylinderGeometry(0.38, 0.48, 0.7, 32);
    const bodyMesh = new THREE.Mesh(bodyGeo, whiteChassisMat);
    bodyMesh.position.y = -0.4;
    robotGroup.add(bodyMesh);

    // Chest glowing indicator
    const chestLightGeo = new THREE.CylinderGeometry(0.09, 0.09, 0.04, 24);
    const chestLight = new THREE.Mesh(chestLightGeo, chestLightMat);
    chestLight.rotation.x = Math.PI / 2;
    chestLight.position.set(0, -0.32, 0.44);
    robotGroup.add(chestLight);
    chestLightRef.current = chestLight;

    // Hover Energy Thruster Ring
    const hoverRingGeo = new THREE.TorusGeometry(0.42, 0.04, 16, 32);
    const hoverRing = new THREE.Mesh(hoverRingGeo, hoverRingMat);
    hoverRing.rotation.x = Math.PI / 2;
    hoverRing.position.set(0, -0.8, 0);
    robotGroup.add(hoverRing);
    hoverRingRef.current = hoverRing;

    // Neck joint
    const neckGeo = new THREE.CylinderGeometry(0.12, 0.12, 0.18, 16);
    const neckMesh = new THREE.Mesh(neckGeo, slateJointMat);
    neckMesh.position.y = 0.02;
    robotGroup.add(neckMesh);

    // --- Head Group ---
    const headGroup = new THREE.Group();
    headGroup.position.set(0, 0.35, 0);
    robotGroup.add(headGroup);
    headGroupRef.current = headGroup;

    // Head Shell (Rounded Box / Beveled Capsule)
    const headGeo = new THREE.SphereGeometry(0.55, 32, 24);
    headGeo.scale(1.15, 0.95, 0.95);
    const headMesh = new THREE.Mesh(headGeo, whiteChassisMat);
    headGroup.add(headMesh);

    // Dark Visor Face Screen
    const visorGeo = new THREE.SphereGeometry(0.51, 32, 24, 0, Math.PI * 2, 0, Math.PI * 0.55);
    visorGeo.scale(1.08, 0.88, 0.98);
    const visorMesh = new THREE.Mesh(visorGeo, visorMat);
    visorMesh.position.set(0, -0.02, 0.04);
    headGroup.add(visorMesh);

    // Left Digital Eye
    const eyeGeo = new THREE.CapsuleGeometry(0.065, 0.07, 8, 16);
    const leftEye = new THREE.Mesh(eyeGeo, eyeMat);
    leftEye.position.set(-0.24, 0.04, 0.49);
    leftEye.rotation.z = 0;
    headGroup.add(leftEye);
    leftEyeRef.current = leftEye;

    // Right Digital Eye
    const rightEye = new THREE.Mesh(eyeGeo, eyeMat);
    rightEye.position.set(0.24, 0.04, 0.49);
    headGroup.add(rightEye);
    rightEyeRef.current = rightEye;

    // Real-Time Lip Sync Mouth
    const mouthGeo = new THREE.CapsuleGeometry(0.035, 0.22, 8, 16);
    mouthGeo.rotateZ(Math.PI / 2);
    const mouthMesh = new THREE.Mesh(mouthGeo, mouthMat);
    mouthMesh.position.set(0, -0.22, 0.48);
    headGroup.add(mouthMesh);
    mouthMeshRef.current = mouthMesh;

    // Left & Right Ear Sensor Pods
    const earGeo = new THREE.CylinderGeometry(0.12, 0.12, 0.08, 16);
    const leftEar = new THREE.Mesh(earGeo, slateJointMat);
    leftEar.rotation.z = Math.PI / 2;
    leftEar.position.set(-0.62, 0.02, 0);
    headGroup.add(leftEar);

    const rightEar = new THREE.Mesh(earGeo, slateJointMat);
    rightEar.rotation.z = Math.PI / 2;
    rightEar.position.set(0.62, 0.02, 0);
    headGroup.add(rightEar);

    // Antenna & Glowing Signal Sphere
    const antennaStemGeo = new THREE.CylinderGeometry(0.02, 0.025, 0.32, 12);
    const antennaStem = new THREE.Mesh(antennaStemGeo, slateJointMat);
    antennaStem.position.set(0, 0.62, 0);
    headGroup.add(antennaStem);

    const antennaTipGeo = new THREE.SphereGeometry(0.06, 16, 16);
    const antennaTip = new THREE.Mesh(antennaTipGeo, antennaMat);
    antennaTip.position.set(0, 0.8, 0);
    headGroup.add(antennaTip);
    antennaTipRef.current = antennaTip;

    // 6. Mouse Interaction Listener
    const handleMouseMove = (event: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      const x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      const y = -(((event.clientY - rect.top) / rect.height) * 2 - 1);
      targetLookX.current = Math.max(-0.4, Math.min(0.4, x * 0.4));
      targetLookY.current = Math.max(-0.3, Math.min(0.3, y * 0.3));
    };

    window.addEventListener("mousemove", handleMouseMove);

    // 7. Animation Loop
    let animationFrameId: number;
    let clock = new THREE.Clock();
    let blinkTimer = 0;
    let nextBlinkTime = 3.5;
    let isBlinking = false;

    const animate = () => {
      animationFrameId = requestAnimationFrame(animate);
      const delta = clock.getDelta();
      const elapsed = clock.getElapsedTime();

      const cfg = ROBOT_STATE_CONFIGS[stateRef.current] || ROBOT_STATE_CONFIGS.IDLE;
      const themeColor = new THREE.Color(cfg.primaryColor);

      // Update dynamic emission colors across materials
      eyeMat.color.lerp(themeColor, 0.1);
      mouthMat.color.lerp(themeColor, 0.1);
      antennaMat.color.lerp(themeColor, 0.1);
      chestLightMat.color.lerp(themeColor, 0.1);
      hoverRingMat.color.lerp(themeColor, 0.1);
      pointLight.color.lerp(themeColor, 0.1);

      // Antenna pulsing glow based on state
      const pulse = 1.0 + Math.sin(elapsed * cfg.antennaPulseSpeed * 4) * 0.35;
      antennaTip.scale.set(pulse, pulse, pulse);

      // Floating / Breathing dynamics (damped if reduced motion requested)
      const floatAmp = reducedMotion ? 0.01 : cfg.breathingAmplitude;
      const floatSpeed = reducedMotion ? 0.5 : cfg.floatingSpeed;
      if (robotGroupRef.current) {
        robotGroupRef.current.position.y = Math.sin(elapsed * floatSpeed * 2.5) * floatAmp;
        hoverRing.rotation.z += 0.015;
      }

      // Smooth Head Tracking & State Reactions
      currentLookX.current += (targetLookX.current - currentLookX.current) * 0.08;
      currentLookY.current += (targetLookY.current - currentLookY.current) * 0.08;

      if (headGroupRef.current) {
        // Target tilts from state machine (e.g. thinking looks up, confused tilts sideways)
        const targetPitch = cfg.headTiltX + (reducedMotion ? 0 : -currentLookY.current);
        const targetYaw = cfg.headTiltY + (reducedMotion ? 0 : currentLookX.current);
        const targetRoll = cfg.headTiltZ;

        headGroupRef.current.rotation.x += (targetPitch - headGroupRef.current.rotation.x) * 0.1;
        headGroupRef.current.rotation.y += (targetYaw - headGroupRef.current.rotation.y) * 0.1;
        headGroupRef.current.rotation.z += (targetRoll - headGroupRef.current.rotation.z) * 0.1;
      }

      // Procedural Blinking
      blinkTimer += delta;
      if (blinkTimer > nextBlinkTime) {
        isBlinking = true;
        if (blinkTimer > nextBlinkTime + 0.14) {
          isBlinking = false;
          blinkTimer = 0;
          nextBlinkTime = 3.0 + Math.random() * 4.0;
        }
      }

      // Eye Shape morphing based on state & blinking
      let eyeScaleY = 1.0;
      let eyeScaleX = 1.0;
      let eyeRotZ = 0;

      if (isBlinking || cfg.eyeShape === "blink" || cfg.eyeShape === "closed") {
        eyeScaleY = 0.12; // Flat blink slit
      } else if (cfg.eyeShape === "happy") {
        eyeScaleY = 0.4;
        eyeScaleX = 1.25;
        eyeRotZ = 0.15; // Inverted curved angle
      } else if (cfg.eyeShape === "confused") {
        eyeScaleY = 0.7;
      }

      if (leftEyeRef.current && rightEyeRef.current) {
        leftEyeRef.current.scale.set(eyeScaleX, eyeScaleY, 1.0);
        leftEyeRef.current.rotation.z = eyeRotZ;

        // Asymmetrical puzzled eye if CONFUSED
        const rightScale = cfg.eyeShape === "confused" ? 1.3 : eyeScaleX;
        rightEyeRef.current.scale.set(rightScale, cfg.eyeShape === "confused" ? 1.3 : eyeScaleY, 1.0);
        rightEyeRef.current.rotation.z = -eyeRotZ;
      }

      // Real-Time Lip Synchronization (Mouth open & width)
      if (mouthMeshRef.current) {
        if (stateRef.current === "SPEAKING") {
          const openScale = Math.max(0.2, mouthOpenRef.current * 3.2);
          const widthScale = Math.max(0.6, 0.7 + mouthWidthRef.current * 0.6);
          mouthMeshRef.current.scale.set(widthScale, openScale, 1.0);
        } else if (stateRef.current === "HAPPY" || stateRef.current === "GREETING") {
          mouthMeshRef.current.scale.set(1.2, 0.35, 1.0); // Gentle smile
        } else {
          mouthMeshRef.current.scale.set(0.8, 0.2, 1.0); // Neutral resting mouth
        }
      }

      renderer.render(scene, camera);
    };

    animate();

    // 8. Handle Window / Container Resize
    const handleResize = () => {
      if (!container) return;
      const w = container.clientWidth || 256;
      const h = container.clientHeight || 256;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };

    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(container);

    // 9. Teardown Cleanup
    return () => {
      cancelAnimationFrame(animationFrameId);
      window.removeEventListener("mousemove", handleMouseMove);
      resizeObserver.disconnect();
      renderer.dispose();
      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
      scene.clear();
    };
  }, [hasWebGL, reducedMotion]);

  // Fallback to high-fidelity SVG/Canvas avatar if WebGL unsupported
  if (hasWebGL === false) {
    return (
      <RobotAvatarFallback
        state={state}
        mouthOpen={mouthOpen}
        mouthWidth={mouthWidth}
        audioLevel={audioLevel}
        className={className}
      />
    );
  }

  return (
    <div
      ref={containerRef}
      onClick={onClick}
      className={`relative flex items-center justify-center cursor-pointer select-none overflow-hidden ${className}`}
      aria-label={`Interactive 3D Voice AI Robot Assistant. Current state: ${state}`}
    />
  );
}
