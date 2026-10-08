import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { C, FONT } from "../theme";
import { ease, prog, SceneT } from "../lib";
import { Icon } from "./Icons";

/** 배경: 사이트 배경색 + 아주 옅은 브랜드 색 번짐 */
export const Background: React.FC = () => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const drift = Math.sin(frame / 240) * 30;
  return (
    <AbsoluteFill style={{ background: C.bgWarm }}>
      <div style={{ position: "absolute", width: width * 0.7, height: width * 0.7, borderRadius: "50%",
        right: -width * 0.22 + drift, top: -width * 0.32,
        background: "radial-gradient(circle, rgba(255,218,210,0.85) 0%, rgba(255,218,210,0) 65%)" }} />
      <div style={{ position: "absolute", width: width * 0.6, height: width * 0.6, borderRadius: "50%",
        left: -width * 0.25 - drift, bottom: -width * 0.36,
        background: "radial-gradient(circle, rgba(255,219,202,0.7) 0%, rgba(255,219,202,0) 65%)" }} />
      <div style={{ position: "absolute", inset: 0,
        backgroundImage: `radial-gradient(rgba(181,39,1,0.07) 1.2px, transparent 1.2px)`,
        backgroundSize: "28px 28px", opacity: 0.6, maskImage: "linear-gradient(180deg, #000, transparent 70%)" }} />
      <div style={{ position: "absolute", left: 0, right: 0, height: height }} />
    </AbsoluteFill>
  );
};

/** 사이트 헤더의 "ㅇㅈ" 마크 */
export const BrandMark: React.FC<{ size?: number }> = ({ size = 26 }) => (
  <span style={{ height: size, padding: `0 ${size * 0.36}px`, background: C.ink, color: "#fff",
    display: "inline-grid", placeItems: "center", borderRadius: size * 0.3, fontFamily: FONT,
    fontSize: size * 0.44, fontWeight: 800, letterSpacing: size * 0.04 }}>ㅇㅈ</span>
);

export const BrandLockup: React.FC<{ size?: number; color?: string }> = ({ size = 30, color = C.ink }) => (
  <div style={{ display: "flex", alignItems: "center", gap: size * 0.4, fontFamily: FONT, color }}>
    <BrandMark size={size} />
    <span style={{ fontSize: size * 0.72, fontWeight: 800, letterSpacing: -0.3 }}>우리동네 직업계고</span>
  </div>
);

/** 기능 장면 왼쪽 설명 영역 */
export const FeatureText: React.FC<{
  index?: string; icon: string; title: string; desc: string; chips?: string[]; x?: number; y?: number; w?: number;
  chipActive?: (i: number) => boolean; note?: string;
}> = ({ index, icon, title, desc, chips = [], x = 110, y = 300, w = 470, chipActive, note }) => {
  const frame = useCurrentFrame();
  const a = prog(frame, 4, 22);
  const b = prog(frame, 12, 22);
  return (
    <div style={{ position: "absolute", left: x, top: y, width: w, fontFamily: FONT }}>
      <div style={{ opacity: a, transform: `translateY(${(1 - a) * 18}px)`, display: "flex", alignItems: "center", gap: 14, marginBottom: 22 }}>
        <div style={{ width: 62, height: 62, borderRadius: 18, background: C.accentSoft, display: "grid", placeItems: "center" }}>
          <Icon name={icon} size={34} color={C.accent} />
        </div>
        {index && <span style={{ fontSize: 20, fontWeight: 700, color: C.accent, letterSpacing: 1 }}>{index}</span>}
      </div>
      <div style={{ opacity: a, transform: `translateY(${(1 - a) * 22}px)`, fontSize: 64, fontWeight: 800,
        color: C.ink, letterSpacing: -1.5, lineHeight: 1.15 }}>{title}</div>
      <div style={{ opacity: b, transform: `translateY(${(1 - b) * 16}px)`, fontSize: 28, fontWeight: 500,
        color: C.steel, marginTop: 18, lineHeight: 1.5, wordBreak: "keep-all" }}>{desc}</div>
      {chips.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 28 }}>
          {chips.map((c, i) => {
            const ca = prog(frame, 22 + i * 5, 16);
            const on = chipActive?.(i) ?? false;
            return (
              <span key={c} style={{ opacity: ca, transform: `translateY(${(1 - ca) * 10}px)`,
                fontSize: 21, fontWeight: 600, padding: "9px 16px", borderRadius: 999,
                background: on ? C.accent : C.surface, color: on ? "#fff" : C.ink,
                border: `1.5px solid ${on ? C.accent : C.line}` }}>{c}</span>
            );
          })}
        </div>
      )}
      {note && (
        <div style={{ opacity: prog(frame, 30, 18), marginTop: 26, fontSize: 18, color: C.muted, lineHeight: 1.5 }}>{note}</div>
      )}
    </div>
  );
};

/** 자막: 나레이션 문장과 같은 글을 그 문장이 들리는 동안 보여 준다 */
export const Subtitles: React.FC<{ scene: SceneT; hide?: number[]; bottom?: number; maxWidth?: number; fontSize?: number }> = ({
  scene, hide = [], bottom = 46, maxWidth = 1500, fontSize = 36,
}) => {
  const frame = useCurrentFrame();
  const idx = scene.lines.findIndex((l) => frame >= l.at - 4 && frame < l.at + l.frames + 10);
  if (idx < 0 || hide.includes(idx)) return null;
  const l = scene.lines[idx];
  const a = Math.min(prog(frame, l.at - 4, 8), 1 - prog(frame, l.at + l.frames + 2, 8, ease));
  return (
    <div style={{ position: "absolute", left: 0, right: 0, bottom, display: "flex", justifyContent: "center", opacity: a }}>
      <div style={{ maxWidth, background: "rgba(25, 28, 29, 0.86)", color: "#fff", fontFamily: FONT,
        fontSize, fontWeight: 600, lineHeight: 1.42, padding: "12px 30px", borderRadius: 14,
        textAlign: "center", wordBreak: "keep-all", letterSpacing: -0.2 }}>
        {l.text}
      </div>
    </div>
  );
};

/** 문장 i 가 시작되는 프레임(없으면 대체값) */
export const lineAt = (scene: SceneT, i: number, fallback = 0) => scene.lines[i]?.at ?? fallback;
