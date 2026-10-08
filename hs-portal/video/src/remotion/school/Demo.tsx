import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { C, FONT } from "../theme";
import { ease, prog, Rect, sceneFade, SceneT } from "../lib";
import { BrowserFrame, Layer } from "../components/BrowserFrame";
import { BrandLockup, Subtitles } from "../components/UI";
import { Icon } from "../components/Icons";
import metaJson from "../school_meta.json";

// ── 캡처 정보 ─────────────────────────────────────────────
const META = metaJson as { shots: Record<string, { h: number; url: string }>; rects: Record<string, Rect> };
/** 로컬 테스트 환경 캡처 좌표(CSS px) */
export const R = (k: string): Rect => META.rects[k] ?? { x: 0, y: 0, w: 0, h: 0 };
/** 운영 사이트(공개 화면) 캡처의 페이지 높이 — 학생 홍보영상에서 찍은 것 */
const PROD_H: Record<string, number> = {
  home_viewport: 900, search_result_full: 1547, search_map: 900, search_compare_modal: 900,
  quiz_result_full: 4182, quiz_intro_full: 1304, signup: 900, search_dept_full: 2651,
  home_full: 2808, news_343_full: 2126,   // 보도자료 장면(특성화고신문 기사·사이트 하단 연락처)
};

export type DemoLayer = Omit<Layer, "name" | "h" | "url"> & { shot: string; prod?: boolean; url?: string };

/** 테스트 환경 캡처는 s_ 접두어, 운영 캡처는 그대로 */
export function toLayer(l: DemoLayer): Layer & { prod?: boolean } {
  if (l.prod) {
    return { ...l, name: l.shot, h: PROD_H[l.shot] ?? 900, url: l.url ?? "udjschool.ggm.kr", prod: true };
  }
  const m = META.shots[l.shot];
  if (!m) throw new Error("unknown shot " + l.shot);
  return { ...l, name: "s_" + l.shot, h: m.h, url: l.url ?? `udjschool.ggm.kr${m.url}` };
}

// ── 배치(1920×1080) ───────────────────────────────────────
export const FR = { x: 600, y: 92, w: 1250 };

export type Step = { label: string; at: number };
export type Spec = {
  chapter: string;            // "04 담당 선생님 업무"
  icon: string;
  title: string;              // [기능명]
  desc: string;               // 한 문장 설명
  steps?: Step[];             // 사용 방법 (at 프레임부터 강조)
  use?: string;               // 활용 목적
  layers: DemoLayer[];
};

const SidePanel: React.FC<{ spec: Spec }> = ({ spec }) => {
  const f = useCurrentFrame();
  const a = prog(f, 4, 22);
  const b = prog(f, 12, 22);
  const steps = spec.steps ?? [];
  const cur = steps.reduce((acc, s, i) => (f >= s.at ? i : acc), -1);
  return (
    <div style={{ position: "absolute", left: 80, top: 150, width: 470, fontFamily: FONT }}>
      <div style={{ opacity: a, display: "flex", alignItems: "center", gap: 12, marginBottom: 18 }}>
        <div style={{ width: 52, height: 52, borderRadius: 15, background: C.accentSoft, display: "grid", placeItems: "center" }}>
          <Icon name={spec.icon} size={30} color={C.accent} />
        </div>
        <span style={{ fontSize: 19, fontWeight: 700, color: C.accent, letterSpacing: 0.5 }}>{spec.chapter}</span>
      </div>
      <div style={{ opacity: a, transform: `translateY(${(1 - a) * 18}px)`, fontSize: 54, fontWeight: 850, color: C.ink,
        letterSpacing: -1.5, lineHeight: 1.15 }}>{spec.title}</div>
      <div style={{ opacity: b, fontSize: 24, fontWeight: 500, color: C.steel, marginTop: 14, lineHeight: 1.5, wordBreak: "keep-all" }}>
        {spec.desc}
      </div>
      {steps.length > 0 && (
        <div style={{ marginTop: 30, display: "grid", gap: 10 }}>
          <div style={{ fontSize: 16, fontWeight: 700, color: C.muted, letterSpacing: 1 }}>사용 방법</div>
          {steps.map((s, i) => {
            const on = i === cur, done = i < cur;
            const sa = prog(f, 20 + i * 4, 14);
            return (
              <div key={s.label} style={{ opacity: sa, display: "flex", alignItems: "center", gap: 12,
                padding: "10px 14px", borderRadius: 12, transition: "none",
                background: on ? C.surface : "transparent", border: `1.5px solid ${on ? C.accent : "transparent"}`,
                boxShadow: on ? "0 6px 18px rgba(181,39,1,0.10)" : "none" }}>
                <span style={{ width: 28, height: 28, borderRadius: 14, flexShrink: 0, display: "grid", placeItems: "center",
                  fontSize: 15, fontWeight: 800, color: on || done ? "#fff" : C.muted,
                  background: on ? C.accent : done ? "#d98a74" : "#efe6e3" }}>{i + 1}</span>
                <span style={{ fontSize: 21, fontWeight: on ? 750 : 550, color: on ? C.ink : done ? C.steel : C.muted,
                  wordBreak: "keep-all", lineHeight: 1.35 }}>{s.label}</span>
              </div>
            );
          })}
        </div>
      )}
      {spec.use && (
        <div style={{ opacity: prog(f, 40, 20), marginTop: 26, padding: "14px 18px", borderRadius: 14,
          background: "rgba(255,218,210,0.55)", borderLeft: `4px solid ${C.accent}` }}>
          <div style={{ fontSize: 15, fontWeight: 800, color: C.accent, marginBottom: 4, letterSpacing: 1 }}>활용</div>
          <div style={{ fontSize: 19, color: C.ink, lineHeight: 1.5, wordBreak: "keep-all" }}>{spec.use}</div>
        </div>
      )}
    </div>
  );
};

/** 화면 출처 배지: 테스트 환경(가상 데이터) / 실제 서비스 공개 화면 */
const SourceBadge: React.FC<{ prod: boolean }> = ({ prod }) => (
  <div style={{ position: "absolute", right: 16, top: 14, zIndex: 6, display: "flex", alignItems: "center", gap: 8,
    background: prod ? "rgba(255,255,255,0.94)" : "rgba(25,28,29,0.86)", color: prod ? C.ink : "#fff",
    border: prod ? `1px solid ${C.line}` : "none", fontFamily: FONT, fontWeight: 700, fontSize: 16,
    padding: "7px 14px", borderRadius: 999, boxShadow: "0 4px 14px rgba(0,0,0,0.15)" }}>
    <span style={{ width: 8, height: 8, borderRadius: 4, background: prod ? "#2f7d5c" : "#ffb199" }} />
    {prod ? "실제 서비스 공개 화면" : "시연용 테스트 환경 · 가상 데이터"}
  </div>
);

export const DemoScene: React.FC<{ scene: SceneT; spec: Spec; chapterBar?: boolean }> = ({ scene, spec, chapterBar }) => {
  const f = useCurrentFrame();
  const layers = spec.layers.map(toLayer);
  const top = [...layers].reverse().find((l) => f >= l.start) ?? layers[0];
  const rise = prog(f, 0, 26);
  return (
    <AbsoluteFill style={{ opacity: sceneFade(f, scene.frames) }}>
      <div style={{ position: "absolute", left: 80, top: 46 }}><BrandLockup size={28} /></div>
      <SidePanel spec={spec} />
      <div style={{ transform: `translateY(${(1 - rise) * 50}px)`, opacity: rise }}>
        <BrowserFrame x={FR.x} y={FR.y} w={FR.w} layers={layers} badge={<SourceBadge prod={!!top.prod} />} />
      </div>
      <Subtitles scene={scene} bottom={chapterBar ? 62 : 40} fontSize={33} maxWidth={1600} />
    </AbsoluteFill>
  );
};

// ── 챕터 바 (통합본 하단) ─────────────────────────────────
export const ChapterBar: React.FC<{ chapters: Record<string, string>; current: string; progress: number }> = ({ chapters, current, progress }) => {
  const keys = Object.keys(chapters);
  return (
    <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 44, background: "rgba(25,28,29,0.92)",
      display: "flex", alignItems: "stretch", fontFamily: FONT }}>
      {keys.map((k, i) => {
        const on = k === current;
        const done = keys.indexOf(current) > i;
        return (
          <div key={k} style={{ flex: 1, position: "relative", display: "flex", alignItems: "center", justifyContent: "center",
            gap: 8, color: on ? "#fff" : done ? "rgba(255,255,255,0.6)" : "rgba(255,255,255,0.38)",
            fontSize: 17, fontWeight: on ? 800 : 600, borderRight: i < keys.length - 1 ? "1px solid rgba(255,255,255,0.08)" : "none",
            background: on ? "rgba(181,39,1,0.55)" : "transparent" }}>
            <span style={{ fontSize: 14, opacity: 0.85 }}>{String(i + 1).padStart(2, "0")}</span>
            {chapters[k]}
            {on && <div style={{ position: "absolute", left: 0, bottom: 0, height: 4, width: `${progress * 100}%`, background: "#ffb199" }} />}
          </div>
        );
      })}
    </div>
  );
};

/** 줄 번호로 시간 찾기 */
export function timing(scene: SceneT) {
  const L = (i: number) => scene.lines[Math.min(i, scene.lines.length - 1)]?.at ?? 0;
  const E = (i: number) => {
    const l = scene.lines[Math.min(i, scene.lines.length - 1)];
    return l ? l.at + l.frames : 0;
  };
  return { L, E, D: scene.frames };
}

export const fadeOut = (f: number, at: number) => 1 - prog(f, at, 10, ease);
