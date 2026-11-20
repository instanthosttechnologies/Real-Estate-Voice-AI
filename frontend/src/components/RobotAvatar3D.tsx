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

  // Arm & Joint references for natural conversational gestures
  const leftShoulderRef = useRef<THREE.Group | null>(null);
  const leftElbowRef = useRef<THREE.Group | null>(null);
  const rightShoulderRef = useRef<THREE.Group | null>(null);
  const rightElbowRef = useRef<THREE.Group | null>(null);

  // Keep state & audio values updated in animation loop
  const stateRef = useRef<RobotState>(state);
  stateRef.current = state;
  const mouthOpenRef = useRef<number>(mouthOpen);
  mouthOpenRef.current = mouthOpen;
  const mouthWidthRef = useRef<number>(mouthWidth);
  mouthWidthRef.current = mouthWidth;
  const audioLevelRef = useRef<number>(audioLevel);
  audioLevelRef.current = audioLevel;

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

    // 1. Scene & Camera (Positioned to frame full head, neck, torso, and expressive arms)
    const scene = new THREE.Scene();
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(38, width / height, 0.1, 100);
    camera.position.set(0, 0.15, 3.8);

    // 2. Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    rendererRef.current = renderer;
    container.appendChild(renderer.domElement);

    // 3. Lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 1.3);
    scene.add(ambientLight);

    const keyLight = new THREE.DirectionalLight(0xffffff, 2.2);
    keyLight.position.set(2.5, 4.0, 3.5);
    scene.add(keyLight);

    const rimLight = new THREE.DirectionalLight(0x38bdf8, 1.6);
    rimLight.position.set(-3.0, -1.5, -2.5);
    scene.add(rimLight);

    const pointLight = new THREE.PointLight(0x0ea5e9, 2.8, 6.0);
    pointLight.position.set(0, 0.2, 1.4);
    scene.add(pointLight);
    pointLightRef.current = pointLight;

    // 4. Materials (High-tech friendly robot polymer, metallic accents, and dynamic glow)
    const whiteChassisMat = new THREE.MeshStandardMaterial({
      color: 0xf8fafc,
      roughness: 0.22,
      metalness: 0.2,
    });

    const slateJointMat = new THREE.MeshStandardMaterial({
      color: 0x334155,
      roughness: 0.45,
      metalness: 0.65,
    });

    const visorMat = new THREE.MeshStandardMaterial({
      color: 0x030712,
      roughness: 0.08,
      metalness: 0.9,
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

    // 5. Construct 3D Procedural Robot Hierarchy (Full Head, Neck, Torso, Arms & Joints)
    const robotGroup = new THREE.Group();
    scene.add(robotGroup);
    robotGroupRef.current = robotGroup;

    // --- Torso / Upper Body Chassis ---
    const torsoGroup = new THREE.Group();
    torsoGroup.position.set(0, -0.1, 0);
    robotGroup.add(torsoGroup);

    // Torso Shell
    const bodyGeo = new THREE.CylinderGeometry(0.36, 0.46, 0.68, 32);
    const bodyMesh = new THREE.Mesh(bodyGeo, whiteChassisMat);
    bodyMesh.position.y = -0.32;
    torsoGroup.add(bodyMesh);

    // Shoulder Collar / Armor Arch
    const collarGeo = new THREE.CylinderGeometry(0.50, 0.44, 0.12, 32);
    const collarMesh = new THREE.Mesh(collarGeo, slateJointMat);
    collarMesh.position.y = -0.02;
    torsoGroup.add(collarMesh);

    // Chest glowing indicator
    const chestLightGeo = new THREE.CylinderGeometry(0.09, 0.09, 0.04, 24);
    const chestLight = new THREE.Mesh(chestLightGeo, chestLightMat);
    chestLight.rotation.x = Math.PI / 2;
    chestLight.position.set(0, -0.26, 0.42);
    torsoGroup.add(chestLight);
    chestLightRef.current = chestLight;

    // Hover Energy Thruster Ring
    const hoverRingGeo = new THREE.TorusGeometry(0.40, 0.035, 16, 32);
    const hoverRing = new THREE.Mesh(hoverRingGeo, hoverRingMat);
    hoverRing.rotation.x = Math.PI / 2;
    hoverRing.position.set(0, -0.72, 0);
    torsoGroup.add(hoverRing);
    hoverRingRef.current = hoverRing;

    // Neck joint
    const neckGeo = new THREE.CylinderGeometry(0.11, 0.11, 0.16, 16);
    const neckMesh = new THREE.Mesh(neckGeo, slateJointMat);
    neckMesh.position.y = 0.08;
    torsoGroup.add(neckMesh);

    // --- Head Group ---
    const headGroup = new THREE.Group();
    headGroup.position.set(0, 0.42, 0);
    torsoGroup.add(headGroup);
    headGroupRef.current = headGroup;

    // Head Shell (Rounded Aerodynamic Head)
    const headGeo = new THREE.SphereGeometry(0.56, 32, 24);
    headGeo.scale(1.15, 0.96, 0.96);
    const headMesh = new THREE.Mesh(headGeo, whiteChassisMat);
    headGroup.add(headMesh);

    // Dark Visor Face Screen
    const visorGeo = new THREE.SphereGeometry(0.52, 32, 24, 0, Math.PI * 2, 0, Math.PI * 0.55);
    visorGeo.scale(1.08, 0.88, 0.98);
    const visorMesh = new THREE.Mesh(visorGeo, visorMat);
    visorMesh.position.set(0, -0.02, 0.04);
    headGroup.add(visorMesh);

    // Left Digital Eye
    const eyeGeo = new THREE.CapsuleGeometry(0.065, 0.07, 8, 16);
    const leftEye = new THREE.Mesh(eyeGeo, eyeMat);
    leftEye.position.set(-0.24, 0.04, 0.49);
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
    leftEar.position.set(-0.64, 0.02, 0);
    headGroup.add(leftEar);

    const rightEar = new THREE.Mesh(earGeo, slateJointMat);
    rightEar.rotation.z = Math.PI / 2;
    rightEar.position.set(0.64, 0.02, 0);
    headGroup.add(rightEar);

    // Antenna & Glowing Signal Sphere
    const antennaStemGeo = new THREE.CylinderGeometry(0.02, 0.025, 0.32, 12);
    const antennaStem = new THREE.Mesh(antennaStemGeo, slateJointMat);
    antennaStem.position.set(0, 0.64, 0);
    headGroup.add(antennaStem);

    const antennaTipGeo = new THREE.SphereGeometry(0.065, 16, 16);
    const antennaTip = new THREE.Mesh(antennaTipGeo, antennaMat);
    antennaTip.position.set(0, 0.82, 0);
    headGroup.add(antennaTip);
    antennaTipRef.current = antennaTip;

    // --- Left Arm & Joints Hierarchy ---
    const leftShoulderGroup = new THREE.Group();
    leftShoulderGroup.position.set(-0.52, -0.06, 0);
    torsoGroup.add(leftShoulderGroup);
    leftShoulderRef.current = leftShoulderGroup;

    const leftShoulderJoint = new THREE.Mesh(new THREE.SphereGeometry(0.085, 16, 16), slateJointMat);
    leftShoulderGroup.add(leftShoulderJoint);

    const leftUpperArmGeo = new THREE.CapsuleGeometry(0.06, 0.22, 8, 16);
    const leftUpperArmMesh = new THREE.Mesh(leftUpperArmGeo, whiteChassisMat);
    leftUpperArmMesh.position.set(0, -0.15, 0);
    leftShoulderGroup.add(leftUpperArmMesh);

    const leftElbowGroup = new THREE.Group();
    leftElbowGroup.position.set(0, -0.30, 0);
    leftShoulderGroup.add(leftElbowGroup);
    leftElbowRef.current = leftElbowGroup;

    const leftElbowJoint = new THREE.Mesh(new THREE.SphereGeometry(0.065, 16, 16), slateJointMat);
    leftElbowGroup.add(leftElbowJoint);

    const leftForearmGeo = new THREE.CapsuleGeometry(0.05, 0.20, 8, 16);
    const leftForearmMesh = new THREE.Mesh(leftForearmGeo, whiteChassisMat);
    leftForearmMesh.position.set(0, -0.14, 0);
    leftElbowGroup.add(leftForearmMesh);

    const leftHandMesh = new THREE.Mesh(new THREE.SphereGeometry(0.055, 16, 16), slateJointMat);
    leftHandMesh.scale.set(1.0, 0.8, 1.3);
    leftHandMesh.position.set(0, -0.27, 0);
    leftElbowGroup.add(leftHandMesh);

    // --- Right Arm & Joints Hierarchy ---
    const rightShoulderGroup = new THREE.Group();
    rightShoulderGroup.position.set(0.52, -0.06, 0);
    torsoGroup.add(rightShoulderGroup);
    rightShoulderRef.current = rightShoulderGroup;

    const rightShoulderJoint = new THREE.Mesh(new THREE.SphereGeometry(0.085, 16, 16), slateJointMat);
    rightShoulderGroup.add(rightShoulderJoint);

    const rightUpperArmGeo = new THREE.CapsuleGeometry(0.06, 0.22, 8, 16);
    const rightUpperArmMesh = new THREE.Mesh(rightUpperArmGeo, whiteChassisMat);
    rightUpperArmMesh.position.set(0, -0.15, 0);
    rightShoulderGroup.add(rightUpperArmMesh);

    const rightElbowGroup = new THREE.Group();
    rightElbowGroup.position.set(0, -0.30, 0);
    rightShoulderGroup.add(rightElbowGroup);
    rightElbowRef.current = rightElbowGroup;

    const rightElbowJoint = new THREE.Mesh(new THREE.SphereGeometry(0.065, 16, 16), slateJointMat);
    rightElbowGroup.add(rightElbowJoint);

    const rightForearmGeo = new THREE.CapsuleGeometry(0.05, 0.20, 8, 16);
    const rightForearmMesh = new THREE.Mesh(rightForearmGeo, whiteChassisMat);
    rightForearmMesh.position.set(0, -0.14, 0);
    rightElbowGroup.add(rightForearmMesh);

    const rightHandMesh = new THREE.Mesh(new THREE.SphereGeometry(0.055, 16, 16), slateJointMat);
    rightHandMesh.scale.set(1.0, 0.8, 1.3);
    rightHandMesh.position.set(0, -0.27, 0);
    rightElbowGroup.add(rightHandMesh);

    // 6. Interactive Cursor Tracking Listener
    const handleMouseMove = (event: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      const x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      const y = -(((event.clientY - rect.top) / rect.height) * 2 - 1);
      targetLookX.current = Math.max(-0.4, Math.min(0.4, x * 0.4));
      targetLookY.current = Math.max(-0.3, Math.min(0.3, y * 0.3));
    };

    window.addEventListener("mousemove", handleMouseMove);

    // 7. Expressive Multi-State Animation Loop
    let animationFrameId: number;
    let clock = new THREE.Clock();
    let blinkTimer = 0;
    let nextBlinkTime = 3.5;
    let isBlinking = false;

    const animate = () => {
      animationFrameId = requestAnimationFrame(animate);
      const delta = clock.getDelta();
      const elapsed = clock.getElapsedTime();

      const currentState = stateRef.current;
      const cfg = ROBOT_STATE_CONFIGS[currentState] || ROBOT_STATE_CONFIGS.IDLE;
      const themeColor = new THREE.Color(cfg.primaryColor);

      // Smooth color blending across LED emissives
      eyeMat.color.lerp(themeColor, 0.1);
      mouthMat.color.lerp(themeColor, 0.1);
      antennaMat.color.lerp(themeColor, 0.1);
      chestLightMat.color.lerp(themeColor, 0.1);
      hoverRingMat.color.lerp(themeColor, 0.1);
      pointLight.color.lerp(themeColor, 0.1);

      // Antenna pulsing glow based on state
      const pulse = 1.0 + Math.sin(elapsed * cfg.antennaPulseSpeed * 4) * 0.35;
      antennaTip.scale.set(pulse, pulse, pulse);

      // Floating / Breathing dynamics (subtly damped if reduced motion is requested)
      const floatAmp = reducedMotion ? 0.01 : cfg.breathingAmplitude;
      const floatSpeed = reducedMotion ? 0.5 : cfg.floatingSpeed;
      if (robotGroupRef.current) {
        robotGroupRef.current.position.y = Math.sin(elapsed * floatSpeed * 2.5) * floatAmp;
        hoverRing.rotation.z += 0.015;
      }

      // Smooth Cursor Head Tracking
      currentLookX.current += (targetLookX.current - currentLookX.current) * 0.08;
      currentLookY.current += (targetLookY.current - currentLookY.current) * 0.08;

      let targetPitch = cfg.headTiltX + (reducedMotion ? 0 : -currentLookY.current);
      let targetYaw = cfg.headTiltY + (reducedMotion ? 0 : currentLookX.current);
      let targetRoll = cfg.headTiltZ;

      // Expressive State-Specific Arm & Body Poses
      let targetLeftShoulderX = 0.1;
      let targetLeftShoulderY = 0.0;
      let targetLeftShoulderZ = 0.18;
      let targetLeftElbowX = -0.25;

      let targetRightShoulderX = 0.1;
      let targetRightShoulderY = 0.0;
      let targetRightShoulderZ = -0.18;
      let targetRightElbowX = -0.25;

      const currentAudio = audioLevelRef.current;

      if (currentState === "IDLE") {
        // Natural breathing and resting arm sway
        targetLeftShoulderX = 0.08 + Math.sin(elapsed * 1.5) * 0.03;
        targetLeftShoulderZ = 0.18;
        targetLeftElbowX = -0.25 + Math.sin(elapsed * 1.5) * 0.02;

        targetRightShoulderX = 0.08 + Math.sin(elapsed * 1.5) * 0.03;
        targetRightShoulderZ = -0.18;
        targetRightElbowX = -0.25 + Math.sin(elapsed * 1.5) * 0.02;
      } else if (currentState === "LISTENING") {
        // Attentive posture: arms held forward, receptive focus, gentle natural nods
        targetLeftShoulderX = -0.32;
        targetLeftShoulderY = 0.12;
        targetLeftShoulderZ = 0.22;
        targetLeftElbowX = -0.65;

        targetRightShoulderX = -0.32;
        targetRightShoulderY = -0.12;
        targetRightShoulderZ = -0.22;
        targetRightElbowX = -0.65;

        // Occasional gentle affirmative nod cycle (every ~5 seconds)
        const nodCycle = (elapsed * 0.6) % 5.0;
        if (nodCycle < 0.7) {
          targetPitch += Math.sin((nodCycle * Math.PI) / 0.7) * 0.06;
        }
      } else if (currentState === "THINKING") {
        // Contemplative pose: right hand raised towards chin/chest, thoughtful eye drift
        targetLeftShoulderX = -0.2;
        targetLeftShoulderZ = 0.2;
        targetLeftElbowX = -0.5;

        targetRightShoulderX = -0.88;
        targetRightShoulderY = -0.32;
        targetRightShoulderZ = -0.25;
        targetRightElbowX = -1.35;

        targetPitch = -0.16; // Head tilted upward in reflection
        targetYaw = 0.12;
      } else if (currentState === "SPEAKING") {
        // Audio-driven speech cadence & natural conversational gesturing
        const speechEnergy = Math.min(1.0, currentAudio * 2.8 + 0.3);

        targetLeftShoulderX = -0.40 + Math.sin(elapsed * 3.5) * 0.14 * speechEnergy;
        targetLeftShoulderZ = 0.30 + Math.sin(elapsed * 2.8) * 0.08;
        targetLeftElbowX = -0.65 + Math.sin(elapsed * 4.0) * 0.12;

        targetRightShoulderX = -0.45 + Math.cos(elapsed * 3.2) * 0.16 * speechEnergy;
        targetRightShoulderZ = -0.30 + Math.cos(elapsed * 2.5) * 0.08;
        targetRightElbowX = -0.70 + Math.cos(elapsed * 3.6) * 0.12;

        // Head cadence tied to speech rhythm
        targetPitch += Math.sin(elapsed * 7.5) * 0.04 * speechEnergy;
        targetYaw += Math.sin(elapsed * 3.2) * 0.03;
      } else if (currentState === "HAPPY" || currentState === "GREETING") {
        // Cheerful open greeting / successful site visit booking celebration
        targetLeftShoulderX = -0.55;
        targetLeftShoulderY = 0.20;
        targetLeftShoulderZ = 0.55;
        targetLeftElbowX = -0.85;

        targetRightShoulderX = -0.55;
        targetRightShoulderY = -0.20;
        targetRightShoulderZ = -0.55;
        targetRightElbowX = -0.85;

        targetPitch += Math.sin(elapsed * 4.0) * 0.05; // Joyful bounce
      } else if (currentState === "CONFUSED") {
        // Puzzled / clarification posture: one hand raised with open palm, head side tilt
        targetLeftShoulderX = 0.05;
        targetLeftShoulderZ = 0.18;
        targetLeftElbowX = -0.25;

        targetRightShoulderX = -0.70;
        targetRightShoulderY = -0.25;
        targetRightShoulderZ = -0.40;
        targetRightElbowX = -1.0;

        targetRoll = 0.22; // Side head tilt
      } else if (currentState === "ERROR") {
        // Friendly recovery posture without erratic movements
        targetLeftShoulderX = -0.15;
        targetLeftShoulderZ = 0.15;
        targetLeftElbowX = -0.4;

        targetRightShoulderX = -0.15;
        targetRightShoulderZ = -0.15;
        targetRightElbowX = -0.4;

        targetPitch = 0.12; // Slight humble bow
      } else if (currentState === "DISCONNECTED") {
        // Sleeping / restful pose: head lowered, arms relaxed
        targetLeftShoulderX = 0.05;
        targetLeftShoulderZ = 0.10;
        targetLeftElbowX = -0.10;

        targetRightShoulderX = 0.05;
        targetRightShoulderZ = -0.10;
        targetRightElbowX = -0.10;

        targetPitch = 0.20;
      }

      // Smooth Animation Blending (Lerp) for head and joints (Zero abrupt snaps)
      const lerpSpeed = reducedMotion ? 0.05 : 0.10;

      if (headGroupRef.current) {
        headGroupRef.current.rotation.x += (targetPitch - headGroupRef.current.rotation.x) * lerpSpeed;
        headGroupRef.current.rotation.y += (targetYaw - headGroupRef.current.rotation.y) * lerpSpeed;
        headGroupRef.current.rotation.z += (targetRoll - headGroupRef.current.rotation.z) * lerpSpeed;
      }

      if (leftShoulderRef.current && leftElbowRef.current) {
        leftShoulderRef.current.rotation.x += (targetLeftShoulderX - leftShoulderRef.current.rotation.x) * lerpSpeed;
        leftShoulderRef.current.rotation.y += (targetLeftShoulderY - leftShoulderRef.current.rotation.y) * lerpSpeed;
        leftShoulderRef.current.rotation.z += (targetLeftShoulderZ - leftShoulderRef.current.rotation.z) * lerpSpeed;
        leftElbowRef.current.rotation.x += (targetLeftElbowX - leftElbowRef.current.rotation.x) * lerpSpeed;
      }

      if (rightShoulderRef.current && rightElbowRef.current) {
        rightShoulderRef.current.rotation.x += (targetRightShoulderX - rightShoulderRef.current.rotation.x) * lerpSpeed;
        rightShoulderRef.current.rotation.y += (targetRightShoulderY - rightShoulderRef.current.rotation.y) * lerpSpeed;
        rightShoulderRef.current.rotation.z += (targetRightShoulderZ - rightShoulderRef.current.rotation.z) * lerpSpeed;
        rightElbowRef.current.rotation.x += (targetRightElbowX - rightElbowRef.current.rotation.x) * lerpSpeed;
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
        eyeScaleY = 0.40;
        eyeScaleX = 1.25;
        eyeRotZ = 0.15; // Inverted curved angle
      } else if (cfg.eyeShape === "confused") {
        eyeScaleY = 0.70;
      }

      if (leftEyeRef.current && rightEyeRef.current) {
        leftEyeRef.current.scale.set(eyeScaleX, eyeScaleY, 1.0);
        leftEyeRef.current.rotation.z = eyeRotZ;

        // Asymmetrical puzzled eye if CONFUSED
        const rightScale = cfg.eyeShape === "confused" ? 1.3 : eyeScaleX;
        rightEyeRef.current.scale.set(rightScale, cfg.eyeShape === "confused" ? 1.3 : eyeScaleY, 1.0);
        rightEyeRef.current.rotation.z = -eyeRotZ;
      }

      // Real-Time Lip Synchronization (Mouth open & width driven by playback audio)
      if (mouthMeshRef.current) {
        if (currentState === "SPEAKING") {
          // Strictly proportional to real playback audio energy: stops immediately when audio stops
          const currentMouthOpen = mouthOpenRef.current;
          const currentMouthWidth = mouthWidthRef.current;
          const openScale = Math.max(0.18, currentMouthOpen * 3.4);
          const widthScale = Math.max(0.65, 0.75 + currentMouthWidth * 0.6);
          mouthMeshRef.current.scale.set(widthScale, openScale, 1.0);
        } else if (currentState === "HAPPY" || currentState === "GREETING") {
          mouthMeshRef.current.scale.set(1.25, 0.35, 1.0); // Gentle friendly smile
        } else {
          mouthMeshRef.current.scale.set(0.80, 0.20, 1.0); // Neutral resting mouth
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
