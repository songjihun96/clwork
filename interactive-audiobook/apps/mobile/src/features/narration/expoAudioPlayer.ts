import { createAudioPlayer, setAudioModeAsync, type AudioPlayer, type AudioStatus } from "expo-audio";

import type { NarrationPlayer, PlayerStatus } from "./types";

let audioModeConfigured = false;

async function configureAudioMode(): Promise<void> {
  if (audioModeConfigured) return;
  audioModeConfigured = true;
  // Foreground narration for now; background playback and lock-screen controls come in Phase 11.
  await setAudioModeAsync({ playsInSilentMode: true, interruptionMode: "doNotMix", shouldPlayInBackground: false });
}

export class ExpoAudioNarrationPlayer implements NarrationPlayer {
  private readonly player: AudioPlayer;

  constructor() {
    void configureAudioMode();
    this.player = createAudioPlayer(null, { updateInterval: 200 });
  }

  load(url: string): void {
    this.player.replace({ uri: url });
  }

  play(): void {
    this.player.play();
  }

  pause(): void {
    this.player.pause();
  }

  seekTo(positionMs: number): Promise<void> {
    return this.player.seekTo(positionMs / 1000);
  }

  setRate(rate: number): void {
    this.player.setPlaybackRate(rate);
  }

  onStatus(listener: (status: PlayerStatus) => void): () => void {
    const subscription = this.player.addListener("playbackStatusUpdate", (status: AudioStatus) => {
      listener({
        positionMs: Math.round(status.currentTime * 1000),
        durationMs: Math.round(status.duration * 1000),
        playing: status.playing,
        buffering: status.isBuffering,
        didJustFinish: status.didJustFinish,
        error: null,
      });
    });
    return () => subscription.remove();
  }

  release(): void {
    this.player.remove();
  }
}

export function createNarrationPlayer(): NarrationPlayer {
  return new ExpoAudioNarrationPlayer();
}
