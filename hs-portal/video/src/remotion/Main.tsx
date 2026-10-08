import React from "react";
import { AbsoluteFill, Audio, interpolate, Sequence, staticFile } from "remotion";
import { Background } from "./components/UI";
import { ensureFont, TIMELINES } from "./lib";
import { FEATURE_IDS, SCENES } from "./scenes/Scenes";

ensureFont();

export const BGM_BASE = 0.2;   // 나레이션이 없을 때
export const BGM_DUCK = 0.075; // 나레이션 중

export const Main: React.FC<{ version: string }> = ({ version }) => {
  const tl = TIMELINES[version];
  const features = tl.scenes.filter((s) => FEATURE_IDS.includes(s.id));
  const speech = tl.scenes.flatMap((s) => s.lines.map((l) => [s.from + l.at, s.from + l.at + l.frames] as const));

  // 나레이션 구간마다 BGM 을 부드럽게 낮춘다(앞뒤 0.25초 램프)
  const bgmVolume = (f: number) => {
    const ramp = 15;
    let duck = 0;
    for (const [a, b] of speech) {
      const v = interpolate(f, [a - ramp, a, b, b + ramp], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
      duck = Math.max(duck, v);
    }
    return BGM_BASE + (BGM_DUCK - BGM_BASE) * duck;
  };

  return (
    <AbsoluteFill style={{ background: "#fbf6f4" }}>
      <Background />
      {tl.scenes.map((s) => {
        const Comp = SCENES[s.id];
        const fi = features.findIndex((x) => x === s);
        const index = fi >= 0 ? String(fi + 1).padStart(2, "0") : undefined;
        return (
          <Sequence key={s.id} from={s.from} durationInFrames={s.frames} name={s.id}>
            <Comp scene={s} index={index} />
          </Sequence>
        );
      })}
      {tl.scenes.flatMap((s) =>
        s.lines.map((l, i) => (
          <Sequence key={`${s.id}-${i}`} from={s.from + l.at} durationInFrames={l.frames + 6} name={`vo:${s.id}:${i}`}>
            <Audio src={staticFile(l.src)} volume={1} />
          </Sequence>
        )),
      )}
      <Audio src={staticFile(`audio/bgm_${version}.wav`)} volume={bgmVolume} />
    </AbsoluteFill>
  );
};
