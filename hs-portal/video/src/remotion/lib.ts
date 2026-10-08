import { continueRender, delayRender, Easing, interpolate, staticFile } from "remotion";
import rectsJson from "./rects.json";
import timelineJson from "./timeline.json";

export type Rect = { x: number; y: number; w: number; h: number };
export const RECTS = (rectsJson as any).rects as Record<string, Record<string, Rect>>;
export const META = (rectsJson as any).meta as Record<string, any>;

export type Line = { text: string; src: string; dur: number; at: number; frames: number };
export type SceneT = { id: string; lines: Line[]; from: number; frames: number };
export type TimelineT = { version: string; fps: number; frames: number; scenes: SceneT[] };
export const TIMELINES = timelineJson as unknown as Record<string, TimelineT>;

// ── 글꼴: 사이트와 같은 Pretendard 를 렌더 전에 반드시 불러 둔다 ──
let fontPromise: Promise<void> | null = null;
export function ensureFont() {
  if (typeof document === "undefined" || fontPromise) return;
  const handle = delayRender("Pretendard");
  const face = new FontFace("Pretendard", `url(${staticFile("fonts/PretendardVariable.woff2")}) format("woff2")`, {
    weight: "45 920",
  });
  fontPromise = face.load().then((f) => {
    (document.fonts as any).add(f);
    continueRender(handle);
  }).catch((e) => {
    console.error(e);
    continueRender(handle);
  });
}

export const ease = Easing.bezier(0.45, 0, 0.2, 1);
export const easeOut = Easing.bezier(0.16, 1, 0.3, 1);

/** 키프레임 보간: keys = [[frame, value], ...] */
export function kf(frame: number, keys: [number, number][], e = ease) {
  if (keys.length === 1) return keys[0][1];
  // 같은 프레임에 키가 겹치면(짧은 버전에서 생길 수 있다) 아주 조금씩 밀어 순증가로 만든다
  const xs: number[] = [];
  for (const [f] of keys) xs.push(xs.length && f <= xs[xs.length - 1] ? xs[xs.length - 1] + 0.001 : f);
  return interpolate(frame, xs, keys.map((k) => k[1]), {
    easing: e,
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
}

/** 0→1 진행값 (start 부터 len 프레임 동안) */
export function prog(frame: number, start: number, len: number, e = easeOut) {
  return interpolate(frame, [start, start + len], [0, 1], {
    easing: e,
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
}

/** 장면 시작/끝 페이드 */
export function sceneFade(frame: number, dur: number, inLen = 14, outLen = 12) {
  return Math.min(prog(frame, 0, inLen), 1 - prog(frame, dur - outLen, outLen, ease));
}

export const shot = (name: string) => staticFile(`shots/${name}.png`);
