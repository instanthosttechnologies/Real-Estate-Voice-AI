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
  const mouthWaveMeshRef = useRef<THREE.Line | null>(null);
  const mouthWaveGeoRef = useRef<THREE.BufferGeometry | null>(null);
  const chestLightRef = useRef<THREE.Mesh | null>(null);
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
    const width = container.clientWidth || 256;
    const height = container.clientHeight || 256;

    // 1. Scene & Camera
    const scene = new THREE.Scene();
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(40, width / height, 0.1, 100);
    camera.position.set(0, 0.15, 3.5);

    // 2. High-performance WebGL Renderer with Alpha & sRGB
    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: "high-performance",
    });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.1;
    rendererRef.current = renderer;
    container.appendChild(renderer.domElement);

    // 3. Three-Point Studio Lighting (Key, Sky-Blue Rim, and Soft Fill)
    const ambientLight = new THREE.AmbientLight(0xffffff, 1.1);
    scene.add(ambientLight);

    const keyLight = new THREE.DirectionalLight(0xffffff, 2.4);
    keyLight.position.set(2.0, 3.0, 3.0);
    scene.add(keyLight);

    const rimLight = new THREE.DirectionalLight(0x38bdf8, 3.0);
    rimLight.position.set(-2.5, 2.0, -2.0);
    scene.add(rimLight);

    const fillLight = new THREE.DirectionalLight(0x94a3b8, 1.2);
    fillLight.position.set(0, -2.0, 2.0);
    scene.add(fillLight);

    const pointLight = new THREE.PointLight(0x00f5ff, 3.5, 6.0);
    pointLight.position.set(0, 0.3, 1.2);
    scene.add(pointLight);
    pointLightRef.current = pointLight;

    // 4. Materials (High-grade ceramic white, metallic sky-blue helmet, titanium joints)
    const whiteChassisMat = new THREE.MeshStandardMaterial({
      color: 0xf8fafc,
      roughness: 0.20,
      metalness: 0.15,
    });

    const skyBlueHelmetMat = new THREE.MeshStandardMaterial({
      color: 0x0284c7,
      roughness: 0.18,
      metalness: 0.55,
    });

    const slateJointMat = new THREE.MeshStandardMaterial({
      color: 0x334155,
      roughness: 0.40,
      metalness: 0.70,
    });

    const cyanEmissiveMat = new THREE.MeshBasicMaterial({
      color: 0x00f5ff,
      transparent: true,
      opacity: 0.95,
    });

    const deepBlueEyeMat = new THREE.MeshBasicMaterial({
      color: 0x0369a1,
    });

    const mouthMat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      transparent: true,
      opacity: 0.95,
    });

    const chestCoreMat = new THREE.MeshBasicMaterial({
      color: 0x00f5ff,
      transparent: true,
      opacity: 0.95,
    });

    // 5. Construct Proportional Humanoid Hierarchy
    const robotGroup = new THREE.Group();
    scene.add(robotGroup);
    robotGroupRef.current = robotGroup;

    // --- Torso / Athletic Upper Body Chassis ---
    const torsoGroup = new THREE.Group();
    torsoGroup.position.set(0, -0.22, 0);
    robotGroup.add(torsoGroup);

    // Broad Humanoid Chest & Abdomen Shell
    const bodyGeo = new THREE.CylinderGeometry(0.38, 0.32, 0.68, 32);
    const bodyMesh = new THREE.Mesh(bodyGeo, whiteChassisMat);
    bodyMesh.position.y = -0.28;
    torsoGroup.add(bodyMesh);

    // Blue Clavicle Armor / Shoulder Yoke
    const collarGeo = new THREE.CylinderGeometry(0.48, 0.42, 0.14, 32);
    const collarMesh = new THREE.Mesh(collarGeo, skyBlueHelmetMat);
    collarMesh.position.y = 0.04;
    torsoGroup.add(collarMesh);

    // Chest Glowing Cyan Reactor Core
    const chestLightGeo = new THREE.CylinderGeometry(0.08, 0.08, 0.04, 24);
    const chestLight = new THREE.Mesh(chestLightGeo, chestCoreMat);
    chestLight.rotation.x = Math.PI / 2;
    chestLight.position.set(0, -0.20, 0.36);
    torsoGroup.add(chestLight);
    chestLightRef.current = chestLight;

    // Glowing Chest Ring Trim
    const chestRingGeo = new THREE.TorusGeometry(0.10, 0.015, 16, 32);
    const chestRing = new THREE.Mesh(chestRingGeo, cyanEmissiveMat);
    chestRing.position.set(0, -0.20, 0.37);
    torsoGroup.add(chestRing);

    // Articulated Cervical Vertebrae Neck Joint
    const neckGeo = new THREE.CylinderGeometry(0.13, 0.15, 0.22, 24);
    const neckMesh = new THREE.Mesh(neckGeo, slateJointMat);
    neckMesh.position.y = 0.18;
    torsoGroup.add(neckMesh);

    // Hydraulic Neck Pistons
    const pistonGeo = new THREE.CylinderGeometry(0.025, 0.025, 0.18, 12);
    const leftPiston = new THREE.Mesh(pistonGeo, slateJointMat);
    leftPiston.position.set(-0.11, 0.18, 0.04);
    torsoGroup.add(leftPiston);

    const rightPiston = new THREE.Mesh(pistonGeo, slateJointMat);
    rightPiston.position.set(0.11, 0.18, 0.04);
    torsoGroup.add(rightPiston);

    // =========================================================================
    // HEAD GROUP (Proportional Humanoid Head with Metallic Sky-Blue Helmet)
    // =========================================================================
    const headGroup = new THREE.Group();
    headGroup.position.set(0, 0.52, 0);
    torsoGroup.add(headGroup);
    headGroupRef.current = headGroup;

    // Outer Sky-Blue Cranial Helmet (Covers top, back and sides of head)
    const helmetGeo = new THREE.SphereGeometry(0.48, 32, 28);
    helmetGeo.scale(1.05, 1.08, 1.02);
    const helmetMesh = new THREE.Mesh(helmetGeo, skyBlueHelmetMat);
    headGroup.add(helmetMesh);

    // Sculpted Ceramic White Face Mask & Jawline (Front humanoid faceplate)
    const faceGeo = new THREE.SphereGeometry(0.44, 32, 24, 0, Math.PI * 2, 0, Math.PI * 0.52);
    faceGeo.scale(0.96, 1.02, 0.98);
    const faceMesh = new THREE.Mesh(faceGeo, whiteChassisMat);
    faceMesh.position.set(0, -0.04, 0.07);
    headGroup.add(faceMesh);

    // Chin & Jaw Contouring
    const jawGeo = new THREE.BoxGeometry(0.24, 0.16, 0.24);
    const jawMesh = new THREE.Mesh(jawGeo, whiteChassisMat);
    jawMesh.position.set(0, -0.38, 0.22);
    headGroup.add(jawMesh);

    // Left & Right Streamlined Ear Sensor Pods
    const earGeo = new THREE.CylinderGeometry(0.11, 0.11, 0.07, 24);
    const leftEar = new THREE.Mesh(earGeo, skyBlueHelmetMat);
    leftEar.rotation.z = Math.PI / 2;
    leftEar.position.set(-0.52, -0.02, 0);
    headGroup.add(leftEar);

    const leftEarRing = new THREE.Mesh(new THREE.TorusGeometry(0.08, 0.015, 16, 24), cyanEmissiveMat);
    leftEarRing.rotation.y = Math.PI / 2;
    leftEarRing.position.set(-0.55, -0.02, 0);
    headGroup.add(leftEarRing);

    const rightEar = new THREE.Mesh(earGeo, skyBlueHelmetMat);
    rightEar.rotation.z = Math.PI / 2;
    rightEar.position.set(0.52, -0.02, 0);
    headGroup.add(rightEar);

    const rightEarRing = new THREE.Mesh(new THREE.TorusGeometry(0.08, 0.015, 16, 24), cyanEmissiveMat);
    rightEarRing.rotation.y = Math.PI / 2;
    rightEarRing.position.set(0.55, -0.02, 0);
    headGroup.add(rightEarRing);

    // =========================================================================
    // EXPRESSIVE CONCENTRIC CIRCULAR BLUE EYES (Matching Reference GIF)
    // =========================================================================
    const eyeOuterRingGeo = new THREE.TorusGeometry(0.09, 0.022, 16, 32);
    const eyePupilGeo = new THREE.SphereGeometry(0.065, 24, 24);

    // Left Eye (Concentric outer cyan ring + deep blue inner pupil)
    const leftEyeGroup = new THREE.Group();
    leftEyeGroup.position.set(-0.20, 0.04, 0.44);
    headGroup.add(leftEyeGroup);

    const leftEyeRing = new THREE.Mesh(eyeOuterRingGeo, cyanEmissiveMat);
    leftEyeGroup.add(leftEyeRing);

    const leftEyePupil = new THREE.Mesh(eyePupilGeo, deepBlueEyeMat);
    leftEyePupil.position.z = -0.01;
    leftEyeGroup.add(leftEyePupil);
    leftEyeRef.current = leftEyePupil;

    // Right Eye
    const rightEyeGroup = new THREE.Group();
    rightEyeGroup.position.set(0.20, 0.04, 0.44);
    headGroup.add(rightEyeGroup);

    const rightEyeRing = new THREE.Mesh(eyeOuterRingGeo, cyanEmissiveMat);
    rightEyeGroup.add(rightEyeRing);

    const rightEyePupil = new THREE.Mesh(eyePupilGeo, deepBlueEyeMat);
    rightEyePupil.position.z = -0.01;
    rightEyeGroup.add(rightEyePupil);
    rightEyeRef.current = rightEyePupil;

    // Friendly Curved Sky-Blue Eyebrows
    const browGeo = new THREE.BoxGeometry(0.16, 0.025, 0.03);
    const leftBrow = new THREE.Mesh(browGeo, skyBlueHelmetMat);
    leftBrow.position.set(-0.20, 0.17, 0.45);
    leftBrow.rotation.z = 0.08;
    headGroup.add(leftBrow);

    const rightBrow = new THREE.Mesh(browGeo, skyBlueHelmetMat);
    rightBrow.position.set(0.20, 0.17, 0.45);
    rightBrow.rotation.z = -0.08;
    headGroup.add(rightBrow);

    // =========================================================================
    // ILLUMINATED SMILING MOUTH & OSCILLATING CYAN SOUNDWAVE OVERLAY
    // =========================================================================
    const mouthGeo = new THREE.CapsuleGeometry(0.028, 0.20, 8, 16);
    mouthGeo.rotateZ(Math.PI / 2);
    const mouthMesh = new THREE.Mesh(mouthGeo, mouthMat);
    mouthMesh.position.set(0, -0.21, 0.45);
    headGroup.add(mouthMesh);
    mouthMeshRef.current = mouthMesh;

    // Oscillating Digital Soundwave across mouth (Matching Reference GIF)
    const wavePointCount = 36;
    const wavePositions = new Float32Array(wavePointCount * 3);
    for (let i = 0; i < wavePointCount; i++) {
      const norm = i / (wavePointCount - 1);
      wavePositions[i * 3] = (norm - 0.5) * 0.46; // span across mouth
      wavePositions[i * 3 + 1] = 0;
      wavePositions[i * 3 + 2] = 0.47;
    }
    const mouthWaveGeo = new THREE.BufferGeometry();
    mouthWaveGeo.setAttribute("position", new THREE.BufferAttribute(wavePositions, 3));
    mouthWaveGeoRef.current = mouthWaveGeo;

    const mouthWaveMat = new THREE.LineBasicMaterial({
      color: 0x00f5ff,
      transparent: true,
      opacity: 0.90,
      linewidth: 2,
    });
    const mouthWaveMesh = new THREE.Line(mouthWaveGeo, mouthWaveMat);
    mouthWaveMesh.position.set(0, -0.21, 0);
    headGroup.add(mouthWaveMesh);
    mouthWaveMeshRef.current = mouthWaveMesh;

    // =========================================================================
    // ARTICULATED HUMAN DUAL ARMS & BALL-AND-SOCKET JOINTS
    // =========================================================================
    const leftUpperArmGeo = new THREE.CapsuleGeometry(0.065, 0.24, 8, 16);
    const leftForearmGeo = new THREE.CapsuleGeometry(0.055, 0.22, 8, 16);

    // --- Left Arm ---
    const leftShoulderGroup = new THREE.Group();
    leftShoulderGroup.position.set(-0.56, 0.02, 0);
    torsoGroup.add(leftShoulderGroup);
    leftShoulderRef.current = leftShoulderGroup;

    // Blue Shoulder Cap
    const leftShoulderCap = new THREE.Mesh(new THREE.SphereGeometry(0.11, 16, 16), skyBlueHelmetMat);
    leftShoulderGroup.add(leftShoulderCap);

    const leftShoulderRing = new THREE.Mesh(new THREE.TorusGeometry(0.09, 0.015, 16, 24), cyanEmissiveMat);
    leftShoulderGroup.add(leftShoulderRing);

    const leftUpperArmMesh = new THREE.Mesh(leftUpperArmGeo, whiteChassisMat);
    leftUpperArmMesh.position.set(0, -0.16, 0);
    leftShoulderGroup.add(leftUpperArmMesh);

    const leftElbowGroup = new THREE.Group();
    leftElbowGroup.position.set(0, -0.32, 0);
    leftShoulderGroup.add(leftElbowGroup);
    leftElbowRef.current = leftElbowGroup;

    const leftElbowJoint = new THREE.Mesh(new THREE.SphereGeometry(0.065, 16, 16), slateJointMat);
    leftElbowGroup.add(leftElbowJoint);

    const leftForearmMesh = new THREE.Mesh(leftForearmGeo, whiteChassisMat);
    leftForearmMesh.position.set(0, -0.15, 0);
    leftElbowGroup.add(leftForearmMesh);

    const leftHandMesh = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.09, 0.04), slateJointMat);
    leftHandMesh.position.set(0, -0.28, 0);
    leftElbowGroup.add(leftHandMesh);

    // --- Right Arm ---
    const rightShoulderGroup = new THREE.Group();
    rightShoulderGroup.position.set(0.56, 0.02, 0);
    torsoGroup.add(rightShoulderGroup);
    rightShoulderRef.current = rightShoulderGroup;

    const rightShoulderCap = new THREE.Mesh(new THREE.SphereGeometry(0.11, 16, 16), skyBlueHelmetMat);
    rightShoulderGroup.add(rightShoulderCap);

    const rightShoulderRing = new THREE.Mesh(new THREE.TorusGeometry(0.09, 0.015, 16, 24), cyanEmissiveMat);
    rightShoulderGroup.add(rightShoulderRing);

    const rightUpperArmMesh = new THREE.Mesh(leftUpperArmGeo, whiteChassisMat);
    rightUpperArmMesh.position.set(0, -0.16, 0);
    rightShoulderGroup.add(rightUpperArmMesh);

    const rightElbowGroup = new THREE.Group();
    rightElbowGroup.position.set(0, -0.32, 0);
    rightShoulderGroup.add(rightElbowGroup);
    rightElbowRef.current = rightElbowGroup;

    const rightElbowJoint = new THREE.Mesh(new THREE.SphereGeometry(0.065, 16, 16), slateJointMat);
    rightElbowGroup.add(rightElbowJoint);

    const rightForearmMesh = new THREE.Mesh(leftForearmGeo, whiteChassisMat);
    rightForearmMesh.position.set(0, -0.15, 0);
    rightElbowGroup.add(rightForearmMesh);

    const rightHandMesh = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.09, 0.04), slateJointMat);
    rightHandMesh.position.set(0, -0.28, 0);
    rightElbowGroup.add(rightHandMesh);

    // 6. Interactive Cursor Tracking Listener
    const handleMouseMove = (event: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      const x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      const y = -(((event.clientY - rect.top) / height) * 2 - 1);
      targetLookX.current = Math.max(-0.6, Math.min(0.6, x * 0.35));
      targetLookY.current = Math.max(-0.4, Math.min(0.4, y * 0.25));
    };

    window.addEventListener("mousemove", handleMouseMove);

    // 7. 60 FPS Render & Animation Loop
    let animationFrameId: number;
    const clock = new THREE.Clock();

    const animate = () => {
      animationFrameId = requestAnimationFrame(animate);
      const delta = clock.getDelta();
      const elapsed = clock.getElapsedTime();

      const currentState = stateRef.current;
      const currentAudio = Math.min(1.0, Math.max(0.0, audioLevelRef.current));
      const config = ROBOT_STATE_CONFIGS[currentState] || ROBOT_STATE_CONFIGS.IDLE;

      const lerpSpeed = reducedMotion ? 0.05 : 0.12;

      // Cursor tracking with lerp
      currentLookX.current += (targetLookX.current - currentLookX.current) * lerpSpeed;
      currentLookY.current += (targetLookY.current - currentLookY.current) * lerpSpeed;

      // Base relaxed breathing motion
      const breathing = Math.sin(elapsed * 2.2) * 0.02;
      torsoGroup.position.y = -0.22 + breathing;

      // Head rotations
      let targetPitch = config.headTiltX + currentLookY.current * 0.5;
      let targetYaw = config.headTiltY + currentLookX.current * 0.7;
      let targetRoll = config.headTiltZ;

      // Arm pose targets
      let targetLeftShoulderX = 0;
      let targetLeftShoulderY = 0;
      let targetLeftShoulderZ = 0.12;
      let targetLeftElbowX = -0.22;

      let targetRightShoulderX = 0;
      let targetRightShoulderY = 0;
      let targetRightShoulderZ = -0.12;
      let targetRightElbowX = -0.22;

      // =======================================================================
      // STATE-SPECIFIC POSING & CONVERSATIONAL GESTURING
      // =======================================================================
      if (currentState === "IDLE") {
        targetPitch = config.headTiltX + currentLookY.current * 0.5;
        targetYaw = config.headTiltY + currentLookX.current * 0.7;
        targetLeftShoulderZ = 0.12;
        targetRightShoulderZ = -0.12;
      } else if (currentState === "LISTENING") {
        targetPitch = 0.08 + Math.sin(elapsed * 1.5) * 0.02; // Attentive nod
        targetLeftShoulderZ = 0.18;
        targetRightShoulderZ = -0.18;
      } else if (currentState === "THINKING") {
        targetPitch = -0.14; // Reflective upward gaze
        targetYaw = 0.12;
        targetRightShoulderX = -0.75;
        targetRightShoulderY = -0.30;
        targetRightElbowX = -1.25; // Hand raised thoughtfully toward chin
      } else if (currentState === "SPEAKING") {
        const speechCadence = Math.min(1.0, currentAudio * 2.5 + 0.35);

        // Conversational natural arm gesturing
        targetLeftShoulderX = -0.45 + Math.sin(elapsed * 3.8) * 0.18 * speechCadence;
        targetLeftShoulderZ = 0.28 + Math.sin(elapsed * 2.4) * 0.10;
        targetLeftElbowX = -0.65 + Math.sin(elapsed * 4.2) * 0.14;

        targetRightShoulderX = -0.50 + Math.cos(elapsed * 3.4) * 0.20 * speechCadence;
        targetRightShoulderZ = -0.28 + Math.cos(elapsed * 2.6) * 0.10;
        targetRightElbowX = -0.70 + Math.cos(elapsed * 3.8) * 0.14;

        // Head rhythm tied to speech
        targetPitch += Math.sin(elapsed * 6.5) * 0.04 * speechCadence;
        targetYaw += Math.sin(elapsed * 3.0) * 0.03;
      } else if (currentState === "HAPPY" || currentState === "GREETING") {
        // Welcoming greeting wave
        targetRightShoulderX = -0.85;
        targetRightShoulderZ = -0.40;
        targetRightElbowX = -1.10 + Math.sin(elapsed * 6.0) * 0.30; // Hand wave
        targetPitch += Math.sin(elapsed * 3.5) * 0.04;
      } else if (currentState === "CONFUSED") {
        targetRoll = 0.18; // Inquisitive head tilt
        targetRightShoulderX = -0.60;
        targetRightElbowX = -0.80;
      } else if (currentState === "ERROR") {
        targetPitch = 0.15; // Dejected head drop
        targetLeftShoulderX = 0.20;
        targetRightShoulderX = 0.20;
      } else if (currentState === "DISCONNECTED") {
        targetPitch = 0.25; // Powered off posture
        targetLeftShoulderX = 0.10;
        targetRightShoulderX = 0.10;
      }

      // Smooth lerp transforms
      headGroup.rotation.x += (targetPitch - headGroup.rotation.x) * lerpSpeed;
      headGroup.rotation.y += (targetYaw - headGroup.rotation.y) * lerpSpeed;
      headGroup.rotation.z += (targetRoll - headGroup.rotation.z) * lerpSpeed;

      leftShoulderGroup.rotation.x += (targetLeftShoulderX - leftShoulderGroup.rotation.x) * lerpSpeed;
      leftShoulderGroup.rotation.y += (targetLeftShoulderY - leftShoulderGroup.rotation.y) * lerpSpeed;
      leftShoulderGroup.rotation.z += (targetLeftShoulderZ - leftShoulderGroup.rotation.z) * lerpSpeed;
      leftElbowGroup.rotation.x += (targetLeftElbowX - leftElbowGroup.rotation.x) * lerpSpeed;

      rightShoulderGroup.rotation.x += (targetRightShoulderX - rightShoulderGroup.rotation.x) * lerpSpeed;
      rightShoulderGroup.rotation.y += (targetRightShoulderY - rightShoulderGroup.rotation.y) * lerpSpeed;
      rightShoulderGroup.rotation.z += (targetRightShoulderZ - rightShoulderGroup.rotation.z) * lerpSpeed;
      rightElbowGroup.rotation.x += (targetRightElbowX - rightElbowGroup.rotation.x) * lerpSpeed;

      // =======================================================================
      // MOUTH & OSCILLATING DIGITAL SOUNDWAVE ANIMATION
      // =======================================================================
      if (mouthMeshRef.current) {
        if (currentState === "SPEAKING") {
          const currentMouthOpen = mouthOpenRef.current;
          const currentMouthWidth = mouthWidthRef.current;
          const openScale = Math.max(0.25, currentMouthOpen * 3.2);
          const widthScale = Math.max(0.70, 0.75 + currentMouthWidth * 0.6);
          mouthMeshRef.current.scale.set(widthScale, openScale, 1.0);
        } else if (currentState === "HAPPY" || currentState === "GREETING") {
          mouthMeshRef.current.scale.set(1.25, 0.40, 1.0); // Gentle smile
        } else {
          mouthMeshRef.current.scale.set(0.80, 0.20, 1.0); // neutral resting mouth
        }
      }

      // Digital Soundwave overlay oscillation (Active during speech)
      if (mouthWaveMeshRef.current && mouthWaveGeoRef.current) {
        if (currentState === "SPEAKING") {
          mouthWaveMeshRef.current.visible = true;
          const pos = mouthWaveGeoRef.current.attributes.position as THREE.BufferAttribute;
          const pArr = pos.array as Float32Array;

          for (let i = 0; i < wavePointCount; i++) {
            const norm = i / (wavePointCount - 1);
            const bell = Math.sin(norm * Math.PI);
            const freq =
              Math.sin(norm * 18 + elapsed * 16) * 0.035 +
              Math.sin(norm * 32 - elapsed * 12) * 0.025;
            pArr[i * 3 + 1] = freq * (0.3 + currentAudio * 2.2) * bell;
          }
          pos.needsUpdate = true;
        } else {
          // Flat subtle glowing smile line in non-speaking states
          mouthWaveMeshRef.current.visible = true;
          const pos = mouthWaveGeoRef.current.attributes.position as THREE.BufferAttribute;
          const pArr = pos.array as Float32Array;
          for (let i = 0; i < wavePointCount; i++) {
            pArr[i * 3 + 1] = 0;
          }
          pos.needsUpdate = true;
        }
      }

      // State eye glow scaling
      const eyeEnergy = currentState === "SPEAKING" ? 1.0 + currentAudio * 0.5 : 1.0;
      leftEyeGroup.scale.set(eyeEnergy, eyeEnergy, 1.0);
      rightEyeGroup.scale.set(eyeEnergy, eyeEnergy, 1.0);

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

    // 9. Cleanup
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
      aria-label={`Interactive 3D Voice AI Humanoid Robot Assistant. Current state: ${state}`}
    />
  );
}
