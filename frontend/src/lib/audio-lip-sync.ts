/**
 * Audio-Driven Lip Synchronization Engine.
 * 
 * Analyzes live streamed AI audio output from Nova 2.5 Sonic using the Web Audio API AnalyserNode.
 * Computes smoothed mouth opening (0.0 to 1.0) and vowel formant width for avatar mouth animation.
 * 
 * NOTE: As per technical disclosure guidelines, this utilizes real-time audio energy and
 * vocal tract frequency band analysis (200Hz - 3500Hz) rather than pre-rendered phoneme/viseme tracks.
 */

export interface LipSyncFrame {
  mouthOpen: number; // 0.0 (closed) to 1.0 (fully open)
  mouthWidth: number; // 0.0 (narrow/rounded 'O') to 1.0 (wide smile 'A'/'E')
  audioLevel: number; // RMS volume level (0.0 to 1.0)
  isSpeaking: boolean;
}

export class AudioLipSyncEngine {
  private audioContext: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private freqData: Uint8Array | null = null;
  private timeData: Uint8Array | null = null;

  // Smoothing state
  private currentMouthOpen = 0;
  private currentMouthWidth = 0.5;
  private currentLevel = 0;
  private isSpeaking = false;

  private smoothingAttack = 0.65; // Quick response to new syllables
  private smoothingDecay = 0.15; // Smooth release

  /**
   * Attaches the analyzer to an active AudioContext and returns an AnalyserNode
   * that should be inserted between the audio buffer source and destination.
   */
  public attachToContext(context: AudioContext): AnalyserNode {
    this.audioContext = context;
    this.analyser = context.createAnalyser();
    this.analyser.fftSize = 512;
    this.analyser.smoothingTimeConstant = 0.4;

    this.freqData = new Uint8Array(this.analyser.frequencyBinCount);
    this.timeData = new Uint8Array(this.analyser.fftSize);

    return this.analyser;
  }

  /**
   * Call once per render frame (e.g. in requestAnimationFrame) to sample current audio physics.
   */
  public update(): LipSyncFrame {
    if (!this.analyser || !this.audioContext || this.audioContext.state !== "running" || !this.freqData || !this.timeData) {
      this.decayToRest();
      return this.getFrame();
    }

    // Sample current frequency spectrum and waveform
    this.analyser.getByteFrequencyData(this.freqData as any);
    this.analyser.getByteTimeDomainData(this.timeData as any);

    // 1. Calculate RMS volume from time domain waveform
    let sumSquares = 0;
    for (let i = 0; i < this.timeData.length; i++) {
      const normalized = (this.timeData[i] - 128) / 128.0;
      sumSquares += normalized * normalized;
    }
    const rms = Math.sqrt(sumSquares / this.timeData.length);
    const audioLevel = Math.min(1.0, rms * 3.5);

    // 2. Vocal tract band analysis (~200Hz to ~3500Hz)
    // Sample rate = 24000Hz (standard Nova 2.5 Sonic PCM output)
    // Bin width = (SampleRate / 2) / frequencyBinCount = 12000 / 256 ~= 46.875 Hz per bin
    const sampleRate = this.audioContext.sampleRate || 24000;
    const binWidth = (sampleRate / 2) / this.freqData.length;

    const minBin = Math.max(1, Math.floor(200 / binWidth));
    const maxBin = Math.min(this.freqData.length - 1, Math.ceil(3500 / binWidth));

    let vocalEnergy = 0;
    let lowEnergy = 0;
    let highEnergy = 0;
    let count = 0;

    for (let bin = minBin; bin <= maxBin; bin++) {
      const val = this.freqData[bin] / 255.0;
      vocalEnergy += val;
      if (bin < (minBin + maxBin) / 2) {
        lowEnergy += val;
      } else {
        highEnergy += val;
      }
      count++;
    }

    const avgVocalEnergy = count > 0 ? vocalEnergy / count : 0;
    const isAudioActive = audioLevel > 0.03 && avgVocalEnergy > 0.04;

    this.isSpeaking = isAudioActive;

    if (!isAudioActive) {
      this.decayToRest();
      return this.getFrame();
    }

    // Target mouth opening driven by vocal energy boosted by audioLevel
    const targetMouthOpen = Math.min(1.0, Math.pow(avgVocalEnergy * 1.8, 1.2));

    // Formant ratio for width (high frequency sibilants/vowels 'E'/'I' vs low 'O'/'U')
    const totalEnergy = lowEnergy + highEnergy;
    const targetWidth = totalEnergy > 0 ? Math.min(1.0, Math.max(0.2, (highEnergy / totalEnergy) * 1.5)) : 0.5;

    // Apply asymmetric smoothing: fast attack on onset, natural decay on pauses
    if (targetMouthOpen > this.currentMouthOpen) {
      this.currentMouthOpen += (targetMouthOpen - this.currentMouthOpen) * this.smoothingAttack;
    } else {
      this.currentMouthOpen += (targetMouthOpen - this.currentMouthOpen) * this.smoothingDecay;
    }

    this.currentMouthWidth += (targetWidth - this.currentMouthWidth) * 0.2;
    this.currentLevel = audioLevel;

    return this.getFrame();
  }

  private decayToRest() {
    this.currentMouthOpen *= 0.7;
    if (this.currentMouthOpen < 0.01) this.currentMouthOpen = 0;
    this.currentLevel *= 0.7;
    if (this.currentLevel < 0.01) this.currentLevel = 0;
    this.currentMouthWidth += (0.5 - this.currentMouthWidth) * 0.1;
    this.isSpeaking = false;
  }

  public reset() {
    this.currentMouthOpen = 0;
    this.currentMouthWidth = 0.5;
    this.currentLevel = 0;
    this.isSpeaking = false;
  }

  public getFrame(): LipSyncFrame {
    return {
      mouthOpen: Math.max(0, Math.min(1, this.currentMouthOpen)),
      mouthWidth: Math.max(0, Math.min(1, this.currentMouthWidth)),
      audioLevel: Math.max(0, Math.min(1, this.currentLevel)),
      isSpeaking: this.isSpeaking,
    };
  }

  public disconnect() {
    this.reset();
    if (this.analyser) {
      this.analyser.disconnect();
      this.analyser = null;
    }
    this.audioContext = null;
    this.freqData = null;
    this.timeData = null;
  }
}
