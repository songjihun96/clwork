import React from "react";
import { AbsoluteFill, Audio, interpolate, Sequence, staticFile, useCurrentFrame } from "remotion";
import { Background } from "../components/UI";
import { ensureFont, SceneT } from "../lib";
import timelineJson from "../school_timeline.json";
import { ChapterBar, DemoScene } from "./Demo";
import { ConnectScene, FlowScene, IntroScene, OutroScene, TasksScene, TitleCard } from "./Graphics";
import { SPECS } from "./specs";

ensureFont();

type TL = { version: string; fps: number; frames: number; chapterBar: boolean; out: string;
  chapters: Record<string, string>; scenes: (SceneT & { chapter: string; card?: string })[] };
export const SCHOOL_TIMELINES = timelineJson as unknown as Record<string, TL>;

const GRAPHIC: Record<string, React.FC<{ scene: SceneT; bar?: boolean }>> = {
  intro: IntroScene, tasks: TasksScene, connect: ConnectScene, flow: FlowScene, outro: OutroScene,
};

const Bar: React.FC<{ tl: TL }> = ({ tl }) => {
  const f = useCurrentFrame();
  const s = tl.scenes.find((x) => f >= x.from && f < x.from + x.frames) ?? tl.scenes[tl.scenes.length - 1];
  const same = tl.scenes.filter((x) => x.chapter === s.chapter);
  const a = same[0].from, b = same[same.length - 1].from + same[same.length - 1].frames;
  return <ChapterBar chapters={tl.chapters} current={s.chapter} progress={(f - a) / (b - a)} />;
};

export const SchoolMain: React.FC<{ version: string }> = ({ version }) => {
  const tl = SCHOOL_TIMELINES[version];
  const speech = tl.scenes.flatMap((s) => s.lines.map((l) => [s.from + l.at, s.from + l.at + l.frames] as const));
  const bgm = (f: number) => {
    let d = 0;
    for (const [a, b] of speech) d = Math.max(d, interpolate(f, [a - 15, a, b, b + 15], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }));
    return 0.13 + (0.045 - 0.13) * d;   // 시연 영상이라 학생 홍보영상보다 작게
  };
  return (
    <AbsoluteFill style={{ background: "#fbf6f4" }}>
      <Background />
      {tl.scenes.map((s) => {
        let el: React.ReactNode;
        if (s.card) el = <TitleCard scene={s} bar={tl.chapterBar} />;
        else if (GRAPHIC[s.id]) { const G = GRAPHIC[s.id]; el = <G scene={s} bar={tl.chapterBar} />; }
        else el = <DemoScene scene={s} spec={SPECS[s.id](s)} chapterBar={tl.chapterBar} />;
        return <Sequence key={s.id} from={s.from} durationInFrames={s.frames} name={s.id}>{el}</Sequence>;
      })}
      {tl.scenes.flatMap((s) => s.lines.map((l, i) => (
        <Sequence key={`${s.id}-${i}`} from={s.from + l.at} durationInFrames={l.frames + 6} name={`vo:${s.id}:${i}`}>
          <Audio src={staticFile(l.src)} />
        </Sequence>
      )))}
      <Audio src={staticFile(`audio/bgm_school_${version}.wav`)} volume={bgm} />
      {tl.chapterBar && <Bar tl={tl} />}
    </AbsoluteFill>
  );
};
