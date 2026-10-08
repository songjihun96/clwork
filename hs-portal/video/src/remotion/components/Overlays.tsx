import React from "react";
import { C, FONT } from "../theme";
import { ease, kf, prog, Rect } from "../lib";
import type { Mapper } from "./BrowserFrame";

/** 특정 영역 강조: 바깥은 살짝 어둡게, 테두리는 브랜드 색 */
export function Highlight({ m, frame, r, from, to, pad = 8, dim = 0.28, radius = 14 }: {
  m: Mapper; frame: number; r: Rect; from: number; to: number; pad?: number; dim?: number; radius?: number;
}) {
  const a = Math.min(prog(frame, from, 14), 1 - prog(frame, to - 10, 10, ease));
  if (a <= 0) return null;
  const q = m.rect({ x: r.x - pad, y: r.y - pad, w: r.w + pad * 2, h: r.h + pad * 2 });
  const grow = 1 + (1 - prog(frame, from, 18)) * 0.04;
  return (
    <div style={{
      position: "absolute", left: q.x, top: q.y, width: q.w, height: q.h, borderRadius: radius,
      border: `3px solid ${C.accent}`, opacity: a, transform: `scale(${grow})`,
      boxShadow: `0 0 0 9999px rgba(25, 18, 16, ${dim * a}), 0 0 0 6px rgba(181, 39, 1, 0.15)`,
      pointerEvents: "none",
    }} />
  );
}

export type CursorKey = { f: number; x: number; y: number; click?: boolean };

/** 마우스 커서. keys 의 좌표는 페이지 좌표(CSS px). click 이 있으면 그 프레임에 물결이 퍼진다. */
export function Cursor({ m, frame, keys, show = [0, 1e9] }: {
  m: Mapper; frame: number; keys: CursorKey[]; show?: [number, number];
}) {
  const a = Math.min(prog(frame, show[0], 10), 1 - prog(frame, show[1] - 8, 8, ease));
  if (a <= 0) return null;
  const x = kf(frame, keys.map((k) => [k.f, k.x]));
  const y = kf(frame, keys.map((k) => [k.f, k.y]));
  const p = m.pt(x, y);
  const clicks = keys.filter((k) => k.click);
  let press = 1;
  const ripples: React.ReactNode[] = [];
  for (const c of clicks) {
    const d = frame - c.f;
    if (d >= -4 && d <= 6) press = Math.min(press, 0.86);
    if (d >= 0 && d < 26) {
      const t = d / 26;
      const cp = m.pt(c.x, c.y);
      ripples.push(
        <div key={c.f} style={{
          position: "absolute", left: cp.x - 30, top: cp.y - 30, width: 60, height: 60, borderRadius: 30,
          border: `3px solid ${C.accent}`, opacity: (1 - t) * 0.9, transform: `scale(${0.3 + t * 1.1})`,
        }} />,
      );
    }
  }
  return (
    <>
      {ripples}
      <svg width="34" height="40" viewBox="0 0 34 40" style={{
        position: "absolute", left: p.x - 4, top: p.y - 2, opacity: a,
        transform: `scale(${press})`, transformOrigin: "4px 2px",
        filter: "drop-shadow(0 3px 5px rgba(0,0,0,0.3))",
      }}>
        <path d="M4 2 L4 31 L11.5 24 L16.5 36 L21.5 34 L16.5 22.5 L27 22.5 Z" fill="#111" stroke="#fff" strokeWidth="2.4" strokeLinejoin="round" />
      </svg>
    </>
  );
}

/** 입력창 위에 글자를 한 자씩 찍는 효과. r = 입력창 영역(CSS px) */
export function Typing({ m, frame, r, text, from, cps = 6, fontSize = 14, padX = 13 }: {
  m: Mapper; frame: number; r: Rect; text: string; from: number; cps?: number; fontSize?: number; padX?: number;
}) {
  if (frame < from) return null;
  const chars = Array.from(text);
  const n = Math.min(chars.length, Math.floor(((frame - from) / 60) * cps) + 1);
  const q = m.rect({ x: r.x + 2, y: r.y + 2, w: r.w - 4, h: r.h - 4 });
  const blink = Math.floor(frame / 18) % 2 === 0;
  return (
    <div style={{ position: "absolute", left: q.x, top: q.y, width: q.w, height: q.h, background: "#fff",
      borderRadius: 6 * m.scale, display: "flex", alignItems: "center", paddingLeft: (padX - 2) * m.scale,
      fontFamily: FONT, fontSize: fontSize * m.scale, color: C.ink, whiteSpace: "nowrap" }}>
      {chars.slice(0, n).join("")}
      <span style={{ display: "inline-block", width: 1.6 * m.scale, height: fontSize * 1.25 * m.scale,
        background: C.ink, marginLeft: 1.5 * m.scale, opacity: blink ? 1 : 0 }} />
    </div>
  );
}

/** "화면 예시 · 가상 데이터" 표시 */
export function SampleBadge({ frame, from = 0, text = "화면 예시 · 가상 데이터" }: { frame: number; from?: number; text?: string }) {
  const a = prog(frame, from, 14);
  return (
    <div style={{ position: "absolute", right: 18, top: 16, zIndex: 5, opacity: a,
      transform: `translateY(${(1 - a) * -8}px)`,
      background: "rgba(25,28,29,0.88)", color: "#fff", fontFamily: FONT, fontWeight: 700, fontSize: 19,
      padding: "9px 16px", borderRadius: 999, display: "flex", alignItems: "center", gap: 8,
      boxShadow: "0 6px 18px rgba(0,0,0,0.2)" }}>
      <span style={{ width: 9, height: 9, borderRadius: 5, background: "#ffb199" }} />
      {text}
    </div>
  );
}
