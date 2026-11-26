/**
 * Real-time Voice AI WebSocket Client with Audio Lip Sync & Mute Controls.
 * Connects to /api/v1/ws/voice/{sessionId}, executes the mandatory auth handshake,
 * captures 24kHz PCM audio from microphone, and streams playback audio from Nova 2.5 Sonic.
 *
 * NOTE: As per Phase 0 architecture and Customer Portal requirements, transcripts and chat
 * text are NOT presented to the customer. All interaction occurs through voice and audio cues.
 */

import { AudioLipSyncEngine, LipSyncFrame } from "./audio-lip-sync";

export type VoiceState = "idle" | "connecting" | "listening" | "thinking" | "speaking" | "interrupted" | "completed" | "error";

export interface VoiceClientOptions {
  sessionId: string;
  accessToken: string;
  wsUrl?: string;
  onStateChange?: (state: VoiceState) => void;
  onError?: (error: string) => void;
  onSiteVisitBooked?: (bookingData: any) => void;
  onToolStart?: (toolName: string) => void;
  onToolComplete?: (toolName: string, success: boolean, data: any) => void;
  onSessionWarning?: (message: string, remainingSeconds: number) => void;
  onSessionCompleted?: (message: string) => void;
  onTranscript?: (role: "user" | "assistant", delta: string, isFinal: boolean) => void;
  onSessionStarted?: (customerName?: string, sessionId?: string) => void;
}

export class VoiceClient {
  private ws: WebSocket | null = null;
  private audioContext: AudioContext | null = null;
  private analyserNode: AnalyserNode | null = null;
  private lipSyncEngine: AudioLipSyncEngine = new AudioLipSyncEngine();
  private mediaStream: MediaStream | null = null;
  private processor: ScriptProcessorNode | null = null;
  private isConnected = false;
  private isMuted = false;
  private state: VoiceState = "idle";

  private audioQueue: AudioBuffer[] = [];
  private activeSources: AudioBufferSourceNode[] = [];
  private scheduledEndTime = 0;
  private playbackEndTimer: any = null;
  private initTimeoutTimer: any = null;
  private muteGainNode: GainNode | null = null;
  private isPlaying = false;
  private vocalBargeInFrames = 0;
  private playbackStartTime = 0;

  private sessionId: string;
  private accessToken: string;
  private wsUrl: string;
  private onStateChange?: (state: VoiceState) => void;
  private onError?: (error: string) => void;
  private onSiteVisitBooked?: (bookingData: any) => void;
  private onToolStart?: (toolName: string) => void;
  private onToolComplete?: (toolName: string, success: boolean, data: any) => void;
  private onSessionWarning?: (message: string, remainingSeconds: number) => void;
  private onSessionCompleted?: (message: string) => void;
  private onTranscript?: (role: "user" | "assistant", delta: string, isFinal: boolean) => void;
  private onSessionStarted?: (customerName?: string, sessionId?: string) => void;

  constructor(options: VoiceClientOptions) {
    this.sessionId = options.sessionId;
    this.accessToken = options.accessToken;
    this.wsUrl = options.wsUrl || process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/api/v1/ws/voice";
    this.onStateChange = options.onStateChange;
    this.onError = options.onError;
    this.onSiteVisitBooked = options.onSiteVisitBooked;
    this.onToolStart = options.onToolStart;
    this.onToolComplete = options.onToolComplete;
    this.onSessionWarning = options.onSessionWarning;
    this.onSessionCompleted = options.onSessionCompleted;
    this.onTranscript = options.onTranscript;
    this.onSessionStarted = options.onSessionStarted;
  }

  private setState(state: VoiceState) {
    this.state = state;
    this.onStateChange?.(state);
  }

  public getState(): VoiceState {
    return this.state;
  }

  public getIsMuted(): boolean {
    return this.isMuted;
  }

  public mute(): void {
    this.isMuted = true;
    if (this.mediaStream) {
      this.mediaStream.getAudioTracks().forEach((t) => {
        t.enabled = false;
      });
    }
  }

  public unmute(): void {
    this.isMuted = false;
    if (this.mediaStream) {
      this.mediaStream.getAudioTracks().forEach((t) => {
        t.enabled = true;
      });
    }
  }

  public toggleMute(): boolean {
    if (this.isMuted) {
      this.unmute();
    } else {
      this.mute();
    }
    return this.isMuted;
  }

  public getLipSyncFrame(): LipSyncFrame {
    return this.lipSyncEngine.update();
  }

  public async start(): Promise<void> {
    if (this.isConnected) return;
    this.setState("connecting");

    try {
      // 1. Request microphone permission early with flexible constraints
      if (typeof navigator !== "undefined" && navigator.mediaDevices) {
        let stream: MediaStream | null = null;
        try {
          stream = await navigator.mediaDevices.getUserMedia({
            audio: {
              channelCount: 1,
              sampleRate: { ideal: 24000 },
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true,
            },
          });
        } catch (initialErr: any) {
          // If browser driver rejects strict sample rate constraints, retry with standard audio
          if (initialErr?.name === "OverconstrainedError" || initialErr?.name === "TypeError") {
            stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          } else {
            throw initialErr;
          }
        }

        this.mediaStream = stream;

        if (this.isMuted) {
          this.mediaStream.getAudioTracks().forEach((t) => {
            t.enabled = false;
          });
        }
      }

      // Initialize and unlock Web Audio context directly within user click handler
      if (typeof window !== "undefined") {
        const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
        if (AudioCtx && !this.audioContext) {
          this.audioContext = new AudioCtx({ sampleRate: 24000 });
        }
        if (this.audioContext && this.audioContext.state === "suspended") {
          await this.audioContext.resume();
        }
      }
    } catch (err: any) {
      this.teardownAudio();
      this.setState("error");

      const errName = err?.name || "";
      let detailedMsg = "Microphone unavailable. Please verify your audio input settings and retry.";

      if (errName === "NotAllowedError" || errName === "PermissionDeniedError") {
        detailedMsg =
          "Microphone permission blocked. In Brave / Chrome, click the site settings / lock icon (🔒) on the left of your address bar, toggle Microphone to 'Allow', and click 'Retry Connection'.";
      } else if (errName === "NotFoundError" || errName === "DevicesNotFoundError") {
        detailedMsg =
          "No microphone found. Please connect or enable an audio input device (headset or microphone) and click 'Retry Connection'.";
      } else if (errName === "NotReadableError" || errName === "TrackStartError") {
        detailedMsg =
          "Microphone is busy or inaccessible. Please close other applications that may be using your audio device (e.g. Teams, Zoom, Discord) and click 'Retry Connection'.";
      } else if (errName === "OverconstrainedError") {
        detailedMsg =
          "Microphone hardware constraints could not be satisfied. Please check your default recording device settings.";
      } else if (errName === "SecurityError") {
        detailedMsg =
          "Microphone access requires a secure HTTPS context or localhost.";
      } else if (err?.message) {
        detailedMsg = `Microphone error (${errName || "Unknown"}): ${err.message}`;
      }

      this.onError?.(detailedMsg);
      return;
    }

    // 2. Start bounded session initialization timeout watchdog (10.0s)
    if (this.initTimeoutTimer) {
      clearTimeout(this.initTimeoutTimer);
    }
    this.initTimeoutTimer = setTimeout(() => {
      if (!this.isConnected) {
        this.setState("error");
        this.teardownAudio();
        if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
          try {
            this.ws.close(1000, "Initialization timed out");
          } catch (e) {
            // ignore
          }
        }
        this.onError?.("Voice session initialization timed out. Could not establish real-time voice channel within 10 seconds.");
      }
    }, 10000);

    // 3. Open WebSocket connection (strictly without query-string tokens)
    const targetUrl = `${this.wsUrl}/${this.sessionId}`;
    this.ws = new WebSocket(targetUrl);
    this.ws.binaryType = "arraybuffer";

    this.ws.onopen = () => {
      // MANDATORY: Send initial JSON authentication handshake
      this.ws?.send(
        JSON.stringify({
          type: "auth",
          token: this.accessToken,
        })
      );
    };

    this.ws.onmessage = async (event) => {
      // Binary PCM audio frame from backend
      if (event.data instanceof ArrayBuffer) {
        this.playAudioChunk(event.data);
        return;
      }

      // JSON Control frames
      try {
        const msg = JSON.parse(event.data);
        this.handleControlMessage(msg);
      } catch (err) {
        // Plain text or unparseable frame
      }
    };

    this.ws.onerror = (err) => {
      if (this.initTimeoutTimer) {
        clearTimeout(this.initTimeoutTimer);
        this.initTimeoutTimer = null;
      }
      this.teardownAudio();
      this.setState("error");
      this.onError?.(`Voice server unreachable: Could not connect to WebSocket at ${targetUrl}. Please ensure the backend server is running.`);
    };

    this.ws.onclose = (event) => {
      if (this.initTimeoutTimer) {
        clearTimeout(this.initTimeoutTimer);
        this.initTimeoutTimer = null;
      }
      this.isConnected = false;
      this.teardownAudio();
      if (event.code === 1008) {
        this.setState("error");
        this.onError?.(`Session rejected: ${event.reason || "Authentication token invalid or expired"}`);
      } else if (this.state === "error" || this.state === "completed") {
        // Retain existing terminal error/completed state
      } else if (event.code !== 1000) {
        this.setState("error");
        this.onError?.(`Voice connection closed unexpectedly (code: ${event.code}). Please click Retry Connection.`);
      } else {
        this.setState("idle");
      }
    };
  }

  private handleControlMessage(msg: any) {
    switch (msg.type) {
      case "session_started":
        if (this.initTimeoutTimer) {
          clearTimeout(this.initTimeoutTimer);
          this.initTimeoutTimer = null;
        }
        this.isConnected = true;
        this.setupAudioRecording();
        // Await incoming assistant greeting audio; fallback to listening if no audio within 3.5s
        this.onSessionStarted?.(msg.customer_name, msg.session_id);
        setTimeout(() => {
          if (this.isConnected && !this.isPlaying && this.state !== "speaking" && this.state !== "thinking") {
            this.setState("listening");
          }
        }, 3500);
        break;

      case "tool_call_start":
        this.setState("thinking");
        this.onToolStart?.(msg.tool_name);
        break;

      case "tool_call_complete":
        this.onToolComplete?.(msg.tool_name, msg.success, msg.data || msg);
        if (msg.tool_name === "book_site_visit" && msg.success) {
          this.onSiteVisitBooked?.(msg);
        }
        break;

      case "transcript":
        this.onTranscript?.(msg.role, msg.delta || "", Boolean(msg.is_final));
        if (msg.role === "assistant") {
          if (msg.is_final) {
            // End of assistant turn transcript
            if (!this.isPlaying && this.isConnected && this.state !== "completed") {
              this.setState("listening");
            }
          } else if (this.isPlaying) {
            this.setState("speaking");
          }
        } else if (msg.role === "user") {
          this.setState("thinking");
        }
        break;

      case "interrupted":
        this.stopAudioPlayback();
        this.setState("listening");
        break;

      case "session_warning":
        this.onSessionWarning?.(msg.message || "Conversation will conclude shortly.", msg.remaining_seconds || 30);
        break;

      case "session_completed":
        this.isConnected = false;
        this.setState("completed");
        this.teardownAudio();
        if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
          try {
            this.ws.close();
          } catch (e) {
            // ignore
          }
        }
        this.onSessionCompleted?.(msg.message || "Conversation completed.");
        break;

      case "error":
        this.isConnected = false;
        this.setState("error");
        this.teardownAudio();
        if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
          try {
            this.ws.close();
          } catch (e) {
            // ignore
          }
        }
        this.onError?.(msg.message || "Voice session error occurred");
        break;
    }
  }

  private setupAudioRecording() {
    if (!this.mediaStream) return;
    try {
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      if (!this.audioContext) {
        this.audioContext = new AudioCtx({ sampleRate: 24000 });
      }
      if (this.audioContext && this.audioContext.state === "suspended") {
        this.audioContext.resume();
      }

      const source = this.audioContext.createMediaStreamSource(this.mediaStream);
      this.processor = this.audioContext.createScriptProcessor(4096, 1, 1);
      let framesSentCount = 0;

      // Uninterrupted audio capture: continuously stream mic frames as long as connected and not muted.
      // Acoustic Echo Suppression: When the robot is speaking, prevent speaker audio from bleeding
      // into the microphone and triggering false Bedrock interruptions. Send silence frames to maintain stream.
      this.processor.onaudioprocess = (e) => {
        if (!this.isConnected || this.isMuted) return;

        const inputData = e.inputBuffer.getChannelData(0);
        const actualRate = e.inputBuffer.sampleRate || this.audioContext?.sampleRate || 24000;
        let channelData = inputData;

        // Sample rate matching: ensure transmitted PCM is strictly 24000 Hz matching backend expectation
        if (actualRate !== 24000 && actualRate > 0) {
          const ratio = 24000 / actualRate;
          const targetLength = Math.round(inputData.length * ratio);
          const resampled = new Float32Array(targetLength);
          for (let i = 0; i < targetLength; i++) {
            const srcIdx = i / ratio;
            const idx = Math.floor(srcIdx);
            const frac = srcIdx - idx;
            if (idx >= inputData.length - 1) {
              resampled[i] = inputData[inputData.length - 1];
            } else {
              resampled[i] = inputData[idx] * (1 - frac) + inputData[idx + 1] * frac;
            }
          }
          channelData = resampled;
        }

        if (this.isPlaying) {
          // Acoustic Echo Suppression & Natural Barge-In:
          let sumSquares = 0;
          for (let i = 0; i < channelData.length; i++) {
            sumSquares += channelData[i] * channelData[i];
          }
          const rms = Math.sqrt(sumSquares / channelData.length);

          // Grace period: during first 400ms of speech, the browser's acoustic echo cancellation filter
          // is adapting to speaker output; ignore transient echo spikes unless overwhelmingly loud (RMS > 0.20)
          const timeSincePlaybackStart = Date.now() - this.playbackStartTime;
          const isGracePeriod = timeSincePlaybackStart < 400;
          const bargeInThreshold = isGracePeriod ? 0.20 : 0.08;

          if (rms > bargeInThreshold) {
            this.vocalBargeInFrames++;
          } else {
            this.vocalBargeInFrames = 0;
          }

          // Require 2 consecutive frames (~340ms) of sustained vocal energy to confirm real customer barge-in
          if (this.vocalBargeInFrames >= 2) {
            console.log(`[VoiceClient] Natural customer barge-in confirmed (RMS=${rms.toFixed(3)}). Interrupting assistant playback.`);
            this.vocalBargeInFrames = 0;
            this.interrupt();
            // Allow this frame to fall through and be streamed to the backend as customer speech
          } else {
            // Send silence frames to maintain stream continuity without echo feedback
            const zeroPcm = new Int16Array(channelData.length);
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
              this.ws.send(zeroPcm.buffer);
            }
            return;
          }
        }

        // Convert Float32 to 16-bit Linear PCM at guaranteed 24000 Hz
        const pcm16 = new Int16Array(channelData.length);
        for (let i = 0; i < channelData.length; i++) {
          const s = Math.max(-1, Math.min(1, channelData[i]));
          pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }

        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(pcm16.buffer);
          framesSentCount++;
          if (framesSentCount <= 3 || framesSentCount % 50 === 0) {
            console.log(`[VoiceClient] Streaming mic frame #${framesSentCount} (${pcm16.byteLength} bytes at 24kHz)`);
          }
        }
      };

      source.connect(this.processor);
      // Connect to mute GainNode (gain=0) to keep processor active without feeding mic audio back into speakers!
      this.muteGainNode = this.audioContext.createGain();
      this.muteGainNode.gain.value = 0;
      this.processor.connect(this.muteGainNode);
      this.muteGainNode.connect(this.audioContext.destination);
    } catch (e) {
      console.error("Audio recording setup failure:", e);
    }
  }

  private playAudioChunk(arrayBuffer: ArrayBuffer) {
    if (!this.audioContext) {
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      this.audioContext = new AudioCtx({ sampleRate: 24000 });
    }
    if (this.audioContext && this.audioContext.state === "suspended") {
      this.audioContext.resume();
    }

    if (!this.analyserNode && this.audioContext) {
      this.analyserNode = this.lipSyncEngine.attachToContext(this.audioContext);
      this.analyserNode.connect(this.audioContext.destination);
    }

    try {
      // Decode 16-bit PCM buffer into Web Audio API AudioBuffer
      const int16Array = new Int16Array(arrayBuffer);
      if (int16Array.length === 0) return;

      const float32Array = new Float32Array(int16Array.length);
      for (let i = 0; i < int16Array.length; i++) {
        float32Array[i] = int16Array[i] / 32768.0;
      }

      const audioBuffer = this.audioContext.createBuffer(1, float32Array.length, 24000);
      audioBuffer.getChannelData(0).set(float32Array);

      // Web Audio timeline gapless scheduling for smooth, continuous, uninterrupted playback
      const currentTime = this.audioContext.currentTime;
      let startTime = this.scheduledEndTime;
      if (startTime < currentTime + 0.02) {
        startTime = currentTime + 0.04;
      }

      const source = this.audioContext.createBufferSource();
      source.buffer = audioBuffer;

      // Connect source to analyserNode (which outputs to audioContext.destination)
      if (this.analyserNode) {
        source.connect(this.analyserNode);
      } else {
        source.connect(this.audioContext.destination);
      }

      source.start(startTime);
      this.scheduledEndTime = startTime + audioBuffer.duration;
      this.activeSources.push(source);

      source.onended = () => {
        const idx = this.activeSources.indexOf(source);
        if (idx !== -1) {
          this.activeSources.splice(idx, 1);
        }
      };

      if (!this.isPlaying) {
        this.playbackStartTime = Date.now();
      }
      this.isPlaying = true;
      this.setState("speaking");

      if (this.playbackEndTimer) {
        clearTimeout(this.playbackEndTimer);
      }

      const remainingMs = Math.max(0, (this.scheduledEndTime - currentTime) * 1000);
      this.playbackEndTimer = setTimeout(() => {
        if (this.audioContext && this.audioContext.currentTime >= this.scheduledEndTime - 0.04) {
          this.isPlaying = false;
          this.vocalBargeInFrames = 0;
          this.lipSyncEngine.reset();
          if (this.isConnected && this.state !== "completed" && this.state !== "error") {
            this.setState("listening");
          }
        }
      }, remainingMs + 100);
    } catch (err) {
      console.error("Error decoding PCM audio frame:", err);
    }
  }

  private stopAudioPlayback() {
    if (this.playbackEndTimer) {
      clearTimeout(this.playbackEndTimer);
      this.playbackEndTimer = null;
    }
    for (const src of this.activeSources) {
      try {
        src.stop();
        src.disconnect();
      } catch (e) {
        // ignore already stopped
      }
    }
    this.activeSources = [];
    this.audioQueue = [];
    this.scheduledEndTime = 0;
    this.isPlaying = false;
    this.vocalBargeInFrames = 0;
    this.lipSyncEngine.reset();
  }

  public interrupt() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.stopAudioPlayback();
      this.ws.send(JSON.stringify({ type: "interrupt" }));
      this.setState("interrupted");
    }
  }

  public stop() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "stop" }));
      this.ws.close();
    }
    this.teardownAudio();
    this.setState("idle");
  }

  private teardownAudio() {
    if (this.initTimeoutTimer) {
      clearTimeout(this.initTimeoutTimer);
      this.initTimeoutTimer = null;
    }
    if (this.processor) {
      this.processor.disconnect();
      this.processor = null;
    }
    if (this.muteGainNode) {
      this.muteGainNode.disconnect();
      this.muteGainNode = null;
    }
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((t) => t.stop());
      this.mediaStream = null;
    }
    this.stopAudioPlayback();
    this.lipSyncEngine.disconnect();
    this.analyserNode = null;
    if (this.audioContext && this.audioContext.state !== "closed") {
      this.audioContext.close();
      this.audioContext = null;
    }
    this.isConnected = false;
  }
}
