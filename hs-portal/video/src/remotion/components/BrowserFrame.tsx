import React from "react";
import { Img, useCurrentFrame } from "remotion";
import { C, FONT } from "../theme";
import { kf, prog, Rect, shot } from "../lib";

/** 카메라 키프레임. f=장면 내 프레임, x/y=화면 중심이 올 페이지 좌표(CSS px), z=확대 배율(1=가로 맞춤) */
export type CamKey = { f: number; x?: number; y: number; z?: number };

export type Mapper = {
  /** 페이지 좌표(CSS px) → 콘텐츠 영역 좌표(px) */
  pt: (x: number, y: number) => { x: number; y: number };
  rect: (r: Rect) => Rect;
  scale: number;
};

export type Layer = {
  name: string;          // 캡처 파일 이름
  h: number;             // 페이지 높이(CSS px). 뷰포트 캡처는 900
  url: string;           // 주소창에 보일 실제 URL
  start: number;         // 이 레이어가 나타나는 프레임
  fade?: number;
  cam: CamKey[];
  overlay?: (m: Mapper, frame: number) => React.ReactNode;
};

const PAGE_W = 1440;
const VIEW_H = 900;
const BAR = 46;

export function useCam(cam: CamKey[], frame: number, cw: number, ch: number, pageH: number): Mapper {
  const z = kf(frame, cam.map((k) => [k.f, k.z ?? 1]));
  const s = (cw / PAGE_W) * z;
  const vw = cw / s;
  const vh = ch / s;
  let cx = kf(frame, cam.map((k) => [k.f, k.x ?? PAGE_W / 2]));
  let cy = kf(frame, cam.map((k) => [k.f, k.y]));
  // 페이지 밖이 보이지 않게 가둔다
  cx = Math.min(Math.max(cx, vw / 2), PAGE_W - vw / 2);
  cy = pageH >= vh ? Math.min(Math.max(cy, vh / 2), pageH - vh / 2) : pageH / 2;
  const ox = cw / 2 - cx * s;
  const oy = ch / 2 - cy * s;
  return {
    pt: (x, y) => ({ x: ox + x * s, y: oy + y * s }),
    rect: (r) => ({ x: ox + r.x * s, y: oy + r.y * s, w: r.w * s, h: r.h * s }),
    scale: s,
  };
}

function LayerView({ layer, frame, cw, ch }: { layer: Layer; frame: number; cw: number; ch: number }) {
  const m = useCam(layer.cam, frame, cw, ch, layer.h);
  const o = prog(frame, layer.start, layer.fade ?? 12);
  const tl = m.pt(0, 0);
  return (
    <div style={{ position: "absolute", inset: 0, opacity: o, overflow: "hidden", background: C.bg }}>
      <Img
        src={shot(layer.name)}
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          width: PAGE_W,
          height: layer.h,
          transformOrigin: "0 0",
          transform: `translate(${tl.x}px, ${tl.y}px) scale(${m.scale})`,
          imageRendering: "auto",
        }}
      />
      {layer.overlay?.(m, frame)}
    </div>
  );
}

export const BrowserFrame: React.FC<{
  x: number;
  y: number;
  w: number;
  layers: Layer[];
  badge?: React.ReactNode;
  style?: React.CSSProperties;
}> = ({ x, y, w, layers, badge, style }) => {
  const frame = useCurrentFrame();
  const ch = Math.round((w * VIEW_H) / PAGE_W);
  // 지금 보여 줄 레이어들(시작한 것만, 마지막 두 개면 충분)
  const live = layers.filter((l) => frame >= l.start - 1).slice(-2);
  const top = live[live.length - 1] ?? layers[0];
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: w,
        height: ch + BAR,
        borderRadius: 18,
        background: C.surface,
        boxShadow: "0 30px 80px rgba(60, 20, 10, 0.16), 0 6px 18px rgba(0,0,0,0.06)",
        border: `1px solid ${C.lineSoft}`,
        overflow: "hidden",
        ...style,
      }}
    >
      <div style={{ height: BAR, display: "flex", alignItems: "center", gap: 14, padding: "0 18px",
        borderBottom: `1px solid ${C.lineSoft}`, background: "#fdfbfa" }}>
        <div style={{ display: "flex", gap: 8 }}>
          {["#ff6159", "#ffbd2e", "#28c941"].map((c) => (
            <span key={c} style={{ width: 12, height: 12, borderRadius: 6, background: c, opacity: 0.85 }} />
          ))}
        </div>
        <div style={{ flex: 1, display: "flex", justifyContent: "center" }}>
          <div style={{ minWidth: 380, maxWidth: "70%", height: 28, borderRadius: 14, background: C.raised,
            display: "flex", alignItems: "center", justifyContent: "center", gap: 8, padding: "0 18px",
            fontFamily: FONT, fontSize: 15, color: C.steel, letterSpacing: 0.1 }}>
            <svg width="12" height="14" viewBox="0 0 12 14"><path d="M2 6V4a4 4 0 1 1 8 0v2h.5A1.5 1.5 0 0 1 12 7.5v5A1.5 1.5 0 0 1 10.5 14h-9A1.5 1.5 0 0 1 0 12.5v-5A1.5 1.5 0 0 1 1.5 6H2Zm1.5 0h5V4a2.5 2.5 0 0 0-5 0v2Z" fill={C.muted} /></svg>
            {top.url}
          </div>
        </div>
        <div style={{ width: 60 }} />
      </div>
      <div style={{ position: "absolute", left: 0, top: BAR, width: w, height: ch, overflow: "hidden" }}>
        {live.map((l) => (
          <LayerView key={l.name + l.start} layer={l} frame={frame} cw={w} ch={ch} />
        ))}
        {badge}
      </div>
    </div>
  );
};

export const frameHeight = (w: number) => Math.round((w * VIEW_H) / PAGE_W) + BAR;
