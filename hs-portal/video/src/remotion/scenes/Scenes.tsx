import React from "react";
import { AbsoluteFill, Img, useCurrentFrame } from "remotion";
import { C, FONT, SITE } from "../theme";
import { ease, easeOut, kf, prog, RECTS, Rect, sceneFade, SceneT, shot } from "../lib";
import { BrowserFrame, Layer } from "../components/BrowserFrame";
import { Cursor, Highlight, SampleBadge, Typing } from "../components/Overlays";
import { BrandLockup, BrandMark, FeatureText, lineAt, Subtitles } from "../components/UI";
import { Icon } from "../components/Icons";

export type SceneProps = { scene: SceneT; index?: string; compact?: boolean };

// 기능 장면 공통 배치 (1920×1080)
const FX = 640, FY = 150, FW = 1180;
const URL = (p = "") => `${SITE}${p}`;

/** 기능 장면 공통 틀: 왼쪽 위 브랜드 + 장면 페이드 + 자막 */
const Shell: React.FC<{ scene: SceneT; children: React.ReactNode; hideSubs?: number[] }> = ({ scene, children, hideSubs }) => {
  const frame = useCurrentFrame();
  const a = sceneFade(frame, scene.frames);
  return (
    <AbsoluteFill style={{ opacity: a }}>
      <div style={{ position: "absolute", left: 110, top: 62 }}><BrandLockup size={30} /></div>
      {children}
      <Subtitles scene={scene} hide={hideSubs} />
    </AbsoluteFill>
  );
};

/** 브라우저 창이 아래에서 떠오르는 등장 */
const rise = (frame: number) => {
  const p = prog(frame, 0, 26);
  return { transform: `translateY(${(1 - p) * 60}px) scale(${0.97 + p * 0.03})`, transformOrigin: "50% 100%" } as React.CSSProperties;
};

/* ───────────────────────── 01. 소개 ───────────────────────── */
export const IntroScene: React.FC<SceneProps> = ({ scene }) => {
  const frame = useCurrentFrame();
  const D = scene.frames;
  const b0 = lineAt(scene, 1, Math.round(D * 0.62));      // 두 번째 문장(설명)이 시작될 때 화면 전환
  const hasB = scene.lines.length > 1;
  const mark = prog(frame, 2, 24);
  const t1 = prog(frame, 10, 24);
  const t2 = prog(frame, 22, 24);
  const up = hasB ? prog(frame, b0 - 6, 34, ease) : 0;
  const out = 1 - prog(frame, D - 12, 12, ease);
  const blockY = 330 - up * 230;
  const blockS = 1 - up * 0.3;
  return (
    <AbsoluteFill style={{ opacity: out }}>
      <div style={{ position: "absolute", left: 0, right: 0, top: blockY, display: "flex", flexDirection: "column",
        alignItems: "center", transform: `scale(${blockS})`, transformOrigin: "50% 0%", fontFamily: FONT }}>
        <div style={{ opacity: mark, transform: `scale(${0.6 + mark * 0.4})` }}><BrandMark size={118} /></div>
        <div style={{ opacity: t1, transform: `translateY(${(1 - t1) * 24}px)`, marginTop: 34, fontSize: 104,
          fontWeight: 850, letterSpacing: -3, color: C.ink, lineHeight: 1 }}>
          우리동네 <span style={{ color: C.accent }}>직업계고</span>
        </div>
        <div style={{ opacity: t2, transform: `translateY(${(1 - t2) * 18}px)`, marginTop: 30, display: "flex", alignItems: "center", gap: 18 }}>
          <span style={{ fontSize: 40, fontWeight: 800, color: "#fff", background: C.accent, padding: "6px 22px",
            borderRadius: 14, letterSpacing: 4 }}>UDJ</span>
          <span style={{ fontSize: 40, fontWeight: 650, color: C.steel }}>직업계고 정보 포털</span>
        </div>
      </div>
      {hasB && (
        <div style={{ opacity: prog(frame, b0 + 4, 20) }}>
          <BrowserFrame x={(1920 - 1300) / 2} y={kf(frame, [[b0, 1000], [b0 + 40, 470]], easeOut)} w={1300}
            layers={[{ name: "home_viewport", h: 900, url: URL("/"), start: 0,
              cam: [{ f: b0, y: 450, z: 1 }, { f: D, y: 470, z: 1.06 }] }]} />
        </div>
      )}
      <Subtitles scene={scene} hide={[0]} />
    </AbsoluteFill>
  );
};

/* ───────────────────────── 홈 ───────────────────────── */
export const HomeScene: React.FC<SceneProps> = ({ scene, index }) => {
  const frame = useCurrentFrame();
  const D = scene.frames;
  const R = RECTS.home;
  const t = (p: number) => Math.round(D * p);
  const phase = frame < t(0.3) ? 0 : frame < t(0.58) ? 1 : frame < t(0.78) ? 2 : 3;
  return (
    <Shell scene={scene}>
      <FeatureText index={index} icon="home" title="홈" desc="전국 직업계고 현황을 한눈에"
        chips={["전국 학교 현황", "많이 찾아본 학교", "계열별 찾기", "학교 소식"]}
        chipActive={(i) => i === phase}
        note="수록 학교 수 575개교 · 17개 시·도 (2026년 10월 기준)" />
      <div style={rise(frame)}>
        <BrowserFrame x={FX} y={FY} w={FW} layers={[{
          name: "home_full", h: 2764, url: URL("/"), start: 0,
          cam: [
            { f: 0, y: 450, z: 1 }, { f: t(0.12), y: 450, z: 1 },
            { f: t(0.24), y: 690, z: 1.12 }, { f: t(0.34), y: 700, z: 1.12 },
            { f: t(0.5), y: 1170, z: 1.0 }, { f: t(0.6), y: 1180, z: 1.0 },
            { f: t(0.74), y: 1560, z: 1.25, x: 560 }, { f: t(0.8), y: 1560, z: 1.25, x: 560 },
            { f: t(0.94), y: 2000, z: 1.0 }, { f: D, y: 2010, z: 1.0 },
          ],
          overlay: (m, f) => (
            <>
              <Highlight m={m} frame={f} r={R.stats} from={t(0.22)} to={t(0.4)} />
              <Highlight m={m} frame={f} r={{ x: 120, y: 1500, w: 520, h: 90 }} from={t(0.7)} to={t(0.84)} />
            </>
          ),
        }]} />
      </div>
    </Shell>
  );
};

/* ───────────────────────── 학교 검색 ───────────────────────── */
export const SearchScene: React.FC<SceneProps> = ({ scene, index }) => {
  const frame = useCurrentFrame();
  const D = scene.frames;
  const S = RECTS.search;
  const twoLines = scene.lines.length > 1;
  const L0 = lineAt(scene, 0, 20);
  const L0end = L0 + (scene.lines[0]?.frames ?? D * 0.6);
  // 첫 문장 동안 필터를 차례로 강조: 지역 → 학교 계열 → 학과 계열 → 남녀공학
  const filt: Rect[] = [
    { x: S.region.x, y: S.region.y - 26, w: S.sigungu.x + S.sigungu.w - S.region.x, h: S.region.h + 26 },
    { ...S.category, y: S.category.y - 26, h: S.category.h + 26 },
    { ...S.dept, y: S.dept.y - 26, h: S.dept.h + 26 },
    { ...S.coed, y: S.coed.y - 26, h: S.coed.h + 26 },
  ];
  const span = (L0end - L0 - 10) / filt.length;
  const fStart = (i: number) => Math.round(L0 + 6 + i * span);
  const active = filt.findIndex((_, i) => frame >= fStart(i) && frame < fStart(i) + span);
  const formCam = { x: 720, y: 368, z: 1.2 };

  let layers: Layer[];
  let chipOn: (i: number) => boolean;
  if (twoLines) {
    // 두 번째 문장: 이름 입력 → 검색 → 결과
    const L1 = lineAt(scene, 1);
    const clickName = L1 + 8, typeAt = L1 + 16, typedLayer = L1 + 44, clickGo = L1 + 60, resAt = L1 + 70;
    chipOn = (i) => (i < 4 ? i === active : frame >= L1);
    layers = [
      { name: "search_top", h: 900, url: URL("/search"), start: 0,
        cam: [{ f: 0, y: 450, z: 1 }, { f: L0, y: 450, z: 1 }, { f: L0 + 26, ...formCam }],
        overlay: (m, f) => (
          <>
            {filt.map((r, i) => <Highlight key={i} m={m} frame={f} r={r} from={fStart(i)} to={fStart(i) + span} pad={6} />)}
            <Typing m={m} frame={f} r={S.name} text="공업" from={typeAt} cps={5} />
            <Cursor m={m} frame={f} show={[L1 - 14, D]} keys={[
              { f: L1 - 14, x: 700, y: 520 }, { f: clickName, x: S.name.x + 60, y: S.name.y + 20, click: true },
            ]} />
          </>
        ) },
      { name: "search_typed", h: 900, url: URL("/search"), start: typedLayer, fade: 8,
        cam: [{ f: 0, ...formCam }],
        overlay: (m, f) => (
          <>
            <Highlight m={m} frame={f} r={{ x: S.name.x, y: S.name.y - 26, w: S.region.x + S.region.w - S.name.x, h: S.name.h + 26 }} from={typedLayer} to={clickGo + 6} pad={6} />
            <Cursor m={m} frame={f} keys={[
              { f: typedLayer, x: S.name.x + 60, y: S.name.y + 20 },
              { f: clickGo, x: S.submit.x + 46, y: S.submit.y + 19, click: true },
            ]} />
          </>
        ) },
      { name: "search_result_full", h: 1547, url: URL("/search?name=공업&region=경기"), start: resAt,
        cam: [{ f: resAt, ...formCam }, { f: resAt + 40, y: 760, z: 1.02 }, { f: D, y: 800, z: 1.02 }],
        overlay: (m, f) => (
          <>
            <Highlight m={m} frame={f} r={{ x: S.result_label.x - 4, y: S.result_label.y - 6, w: 100, h: 26 }} from={resAt + 34} to={D} pad={6} radius={10} dim={0} />
          </>
        ) },
    ];
  } else {
    // 한 문장 버전: 학과 계열(IT·소프트웨어) 선택 → 검색 → 결과
    const sel = Math.round(L0 + (L0end - L0) * 0.55), go = sel + 26, res = go + 10;
    chipOn = (i) => (frame >= sel ? i === 2 : i === active);
    layers = [
      { name: "search_top", h: 900, url: URL("/search"), start: 0,
        cam: [{ f: 0, y: 450, z: 1 }, { f: 18, ...formCam }],
        overlay: (m, f) => <>{filt.map((r, i) => <Highlight key={i} m={m} frame={f} r={r} from={fStart(i) - 8} to={Math.min(fStart(i) + span, sel)} pad={6} />)}</> },
      { name: "search_dept_select", h: 900, url: URL("/search"), start: sel, fade: 8,
        cam: [{ f: 0, ...formCam }],
        overlay: (m, f) => (
          <>
            <Highlight m={m} frame={f} r={filt[2]} from={sel} to={go + 4} pad={6} />
            <Cursor m={m} frame={f} keys={[
              { f: sel, x: S.dept.x + 90, y: S.dept.y + 19 }, { f: go, x: S.submit.x + 46, y: S.submit.y + 19, click: true },
            ]} />
          </>
        ) },
      { name: "search_dept_full", h: 2651, url: URL("/search?dept_field=it"), start: res,
        cam: [{ f: res, ...formCam }, { f: res + 36, y: 740, z: 1.0 }, { f: D, y: 830, z: 1.0 }] },
    ];
  }
  return (
    <Shell scene={scene}>
      <FeatureText index={index} icon="search" title="학교 검색" desc="조건을 골라 전국 직업계고를 찾아요"
        chips={["지역", "학교 계열", "학과 계열", "남녀공학", ...(twoLines ? ["학교 이름"] : [])]} chipActive={chipOn} />
      <div style={rise(frame)}><BrowserFrame x={FX} y={FY} w={FW} layers={layers} /></div>
    </Shell>
  );
};

/* ───────────────────────── 지도 ───────────────────────── */
export const MapScene: React.FC<SceneProps> = ({ scene, index }) => {
  const frame = useCurrentFrame();
  const D = scene.frames;
  // 지도 캡처는 화면을 392px 내려 찍었다 → 지도 상자 위치(화면 좌표)
  const map = { ...RECTS.search.map, y: RECTS.search.map.y - 392 };
  const c = { x: map.x + map.w / 2, y: map.y + map.h / 2 };
  return (
    <Shell scene={scene}>
      <FeatureText index={index} icon="map" title="지도 보기" desc="검색한 학교를 지도에서 확인해요"
        chips={["검색 결과 그대로", "서울 72개교 예시"]} chipActive={(i) => i === 0} />
      <div style={rise(frame)}>
        <BrowserFrame x={FX} y={FY} w={FW} layers={[{
          name: "search_map", h: 900, url: URL("/search?region=서울"), start: 0,
          cam: [{ f: 0, y: 450, z: 1 }, { f: Math.round(D * 0.18), y: 450, z: 1 },
            { f: Math.round(D * 0.55), x: c.x + 40, y: c.y - 20, z: 1.5 }, { f: D, x: c.x + 70, y: c.y - 30, z: 1.62 }],
          overlay: (m, f) => (
            <>
              <Highlight m={m} frame={f} r={{ x: 118, y: 80, w: 100, h: 20 }} from={Math.round(D * 0.06)} to={Math.round(D * 0.4)} pad={6} radius={10} dim={0} />
              <Cursor m={m} frame={f} show={[Math.round(D * 0.35), D]} keys={[
                { f: Math.round(D * 0.35), x: c.x - 160, y: c.y + 120 },
                { f: Math.round(D * 0.7), x: c.x + 30, y: c.y - 40 },
                { f: D, x: c.x + 60, y: c.y - 70 },
              ]} />
            </>
          ),
        }]} />
      </div>
    </Shell>
  );
};

/* ───────────────────────── 학교 정보 ───────────────────────── */
export const SchoolScene: React.FC<SceneProps> = ({ scene, index }) => {
  const frame = useCurrentFrame();
  const D = scene.frames;
  const A = RECTS.school_25;
  const B = RECTS.school_262;
  const L1 = scene.lines.length > 1 ? lineAt(scene, 1) : D;   // 한 문장 버전은 문의 화면으로 넘어가지 않는다
  const t = (p: number) => Math.round(L1 * p);
  const phase = frame < t(0.25) ? -1 : frame < t(0.48) ? 0 : frame < t(0.72) ? 1 : frame < L1 ? 2 : 3;
  const depts = { ...A.depts, h: 150 };
  const contact = { ...A.contact, h: 290 };
  return (
    <Shell scene={scene}>
      <FeatureText index={index} icon="school" title="학교 정보" desc="학교마다 상세 페이지가 있어요"
        chips={["기본 정보", "개설 학과", "위치·연락처", ...(L1 < D ? ["학교에 문의"] : [])]} chipActive={(i) => i === phase} />
      <div style={rise(frame)}>
        <BrowserFrame x={FX} y={FY} w={FW} layers={[
          { name: "school_25_full", h: 1858, url: URL("/schools/25"), start: 0,
            cam: [{ f: 0, y: 450, z: 1 }, { f: t(0.2), y: 470, z: 1 },
              { f: t(0.34), x: 600, y: 700, z: 1.32 }, { f: t(0.5), x: 600, y: 720, z: 1.32 },
              { f: t(0.62), x: 900, y: 730, z: 1.25 }, { f: L1, x: 900, y: 730, z: 1.25 }],
            overlay: (m, f) => (
              <>
                <Highlight m={m} frame={f} r={{ ...A.basic, h: 125 }} from={t(0.26)} to={t(0.5)} />
                <Highlight m={m} frame={f} r={depts} from={t(0.36)} to={t(0.62)} />
                <Highlight m={m} frame={f} r={contact} from={t(0.62)} to={L1 + 4} />
              </>
            ) },
          ...(L1 >= D ? [] : [{ name: "school_262_full", h: 2900, url: URL("/schools/262"), start: L1,
            cam: [{ f: L1, x: 640, y: B.inquiry.y + 230, z: 1.22 }, { f: D, x: 640, y: B.inquiry.y + 260, z: 1.26 }],
            overlay: (m, f) => (
              <>
                <Highlight m={m} frame={f} r={{ ...B.inquiry, h: 525 }} from={L1 + 10} to={D} />
                <Cursor m={m} frame={f} show={[L1 + 16, D]} keys={[
                  { f: L1 + 16, x: 700, y: B.inquiry.y + 420 }, { f: D, x: 520, y: B.inquiry.y + 330 },
                ]} />
              </>
            ) } as Layer]),
        ]} />
      </div>
    </Shell>
  );
};

/* ───────────────────────── 학교 비교 ───────────────────────── */
export const CompareScene: React.FC<SceneProps> = ({ scene, index }) => {
  const frame = useCurrentFrame();
  const D = scene.frames;
  const click = Math.round(D * 0.36), modal = click + 12;
  return (
    <Shell scene={scene}>
      <FeatureText index={index} icon="compare" title="학교 비교" desc="관심 학교를 담아 나란히 비교해요"
        chips={["최대 3곳", "계열·지역·학과", "설립·연락처"]} chipActive={(i) => (frame < modal ? i === 0 : i > 0)} />
      <div style={rise(frame)}>
        <BrowserFrame x={FX} y={FY} w={FW} layers={[
          { name: "search_compare_tray", h: 900, url: URL("/search"), start: 0,
            cam: [{ f: 0, y: 450, z: 1 }, { f: Math.round(D * 0.12), y: 450, z: 1 }, { f: click - 4, x: 900, y: 700, z: 1.35 }],
            overlay: (m, f) => (
              <>
                <Highlight m={m} frame={f} r={{ x: 112, y: 850, w: 1220, h: 44 }} from={Math.round(D * 0.1)} to={click + 6} pad={4} radius={10} />
                <Cursor m={m} frame={f} show={[Math.round(D * 0.12), D]} keys={[
                  { f: Math.round(D * 0.12), x: 900, y: 600 }, { f: click, x: 1208, y: 871, click: true },
                ]} />
              </>
            ) },
          { name: "search_compare_modal", h: 900, url: URL("/search"), start: modal,
            cam: [{ f: modal, y: 450, z: 1 }, { f: modal + 30, x: 720, y: 470, z: 1.18 }, { f: D, x: 720, y: 500, z: 1.2 }] },
        ]} />
      </div>
    </Shell>
  );
};

/* ───────────────────────── 취업·진학 정보 (가상 데이터 예시) ───────────────────────── */
export const AdmissionScene: React.FC<SceneProps> = ({ scene, index }) => {
  const frame = useCurrentFrame();
  const D = scene.frames;
  const t = (p: number) => Math.round(D * p);
  const phase = frame < t(0.45) ? 0 : frame < t(0.7) ? 1 : 2;
  return (
    <Shell scene={scene}>
      <FeatureText index={index} icon="chart" title="취업·진학 정보" desc="학교가 직접 입력해 공개한 졸업생 진로 자료"
        chips={["졸업 후 진로", "진학 현황", "취업 분야"]} chipActive={(i) => i === phase}
        note="※ 학교가 공개한 경우에만 볼 수 있습니다. 영상 속 수치와 학교명은 가상 데이터 예시입니다." />
      <div style={rise(frame)}>
        <BrowserFrame x={FX} y={FY} w={FW} badge={<SampleBadge frame={frame} from={4} />} layers={[{
          name: "admission_full", h: 2725, url: URL("/schools/…/admission"), start: 0,
          cam: [{ f: 0, y: 450, z: 1 }, { f: t(0.15), y: 450, z: 1 },
            { f: t(0.32), y: 640, z: 1.18 }, { f: t(0.55), y: 660, z: 1.18 },
            { f: t(0.78), y: 1900, z: 1.12 }, { f: D, y: 1930, z: 1.12 }],
          overlay: (m, f) => (
            <>
              <Highlight m={m} frame={f} r={{ x: 120, y: 548, w: 1200, h: 228 }} from={t(0.3)} to={t(0.6)} />
              <Highlight m={m} frame={f} r={{ x: 120, y: 1810, w: 1200, h: 225 }} from={t(0.78)} to={D} />
            </>
          ),
        }]} />
      </div>
    </Shell>
  );
};

/* ───────────────────────── 진로 테스트 ───────────────────────── */
export const QuizScene: React.FC<SceneProps> = ({ scene, index }) => {
  const frame = useCurrentFrame();
  const D = scene.frames;
  const Q = RECTS.quiz;
  const two = scene.lines.length > 1;
  const L1 = two ? lineAt(scene, 1) : Math.round(D * 0.42);
  const startClick = Math.round(L1 * 0.55), qAt = startClick + 10, ans = Math.min(L1 - 6, qAt + 34);
  const resAt = L1 + 4;
  const R = D - resAt;
  const r = (p: number) => resAt + Math.round(R * p);
  const phase = frame < resAt ? 0 : frame < r(0.45) ? 1 : frame < r(0.76) ? 2 : 3;
  return (
    <Shell scene={scene}>
      <FeatureText index={index} icon="compass" title="진로 테스트" desc="나에게 맞는 학과와 학교를 추천받아요"
        chips={["36개 문항", "관심 분야", "추천 학과 TOP 3", "통학 가능한 학교"]} chipActive={(i) => i === phase} />
      <div style={rise(frame)}>
        <BrowserFrame x={FX} y={FY} w={FW} layers={[
          { name: "quiz_intro_full", h: 1304, url: URL("/quiz"), start: 0,
            cam: [{ f: 0, y: 450, z: 1 }, { f: Math.round(startClick * 0.4), y: 450, z: 1 }, { f: startClick - 4, y: 760, z: 1.18 }],
            overlay: (m, f) => (
              <Cursor m={m} frame={f} show={[Math.round(startClick * 0.4), D]} keys={[
                { f: Math.round(startClick * 0.4), x: 1000, y: 640 }, { f: startClick, x: Q.start.x + Q.start.w / 2, y: Q.start.y + 21, click: true },
              ]} />
            ) },
          { name: "quiz_question", h: 900, url: URL("/quiz"), start: qAt, fade: 8,
            cam: [{ f: qAt, x: 720, y: 270, z: 1.45 }, { f: L1, x: 720, y: 270, z: 1.5 }],
            overlay: (m, f) => (
              <Cursor m={m} frame={f} keys={[{ f: qAt, x: 720, y: 400 }, { f: ans, x: 866, y: 306, click: true }]} />
            ) },
          { name: "quiz_result_full", h: 4182, url: URL("/quiz"), start: resAt,
            cam: [{ f: resAt, y: 330, z: 1.32 }, { f: r(0.38), y: 360, z: 1.32 },
              { f: r(0.5), y: 1310, z: 1.25 }, { f: r(0.7), y: 1330, z: 1.25 },
              { f: r(0.86), y: 2080, z: 1.0 }, { f: D, y: 2120, z: 1.0 }],
            overlay: (m, f) => (
              <>
                <Highlight m={m} frame={f} r={{ x: 362, y: 312, w: 716, h: 200 }} from={r(0.06)} to={r(0.4)} />
                <Highlight m={m} frame={f} r={{ x: 380, y: 1085, w: 680, h: 485 }} from={r(0.5)} to={r(0.74)} />
              </>
            ) },
        ]} />
      </div>
    </Shell>
  );
};

/* ───────────────────────── 기능 정리 ───────────────────────── */
const RECAP = [
  { icon: "search", label: "학교 검색", img: "search_result_full", crop: { x: 120, y: 280, w: 1200, h: 760 } },
  { icon: "map", label: "지도 보기", img: "search_map", crop: { x: 300, y: 160, w: 860, h: 540 } },
  { icon: "school", label: "학교 정보", img: "school_25_full", crop: { x: 120, y: 80, w: 1200, h: 760 } },
  { icon: "compare", label: "학교 비교", img: "search_compare_modal", crop: { x: 280, y: 60, w: 880, h: 560 } },
  { icon: "compass", label: "진로 테스트", img: "quiz_result_full", crop: { x: 360, y: 90, w: 720, h: 460 } },
];
const PAGE_H: Record<string, number> = { search_result_full: 1547, search_map: 900, school_25_full: 1858, search_compare_modal: 900, quiz_result_full: 4182 };

const Thumb: React.FC<{ img: string; crop: Rect; w: number; h: number; fit?: "cover" | "contain" }> = ({ img, crop, w, h, fit = "cover" }) => {
  const s = fit === "cover" ? Math.max(w / crop.w, h / crop.h) : Math.min(w / crop.w, h / crop.h);
  return (
    <div style={{ width: w, height: h, overflow: "hidden", position: "relative", background: C.bg }}>
      <Img src={shot(img)} style={{ position: "absolute", width: 1440 * s, height: PAGE_H[img] * s,
        left: -crop.x * s - (crop.w * s - w) / 2, top: -crop.y * s - (crop.h * s - h) / 2 }} />
    </div>
  );
};

export const RecapScene: React.FC<SceneProps> = ({ scene }) => {
  const frame = useCurrentFrame();
  const D = scene.frames;
  const l = scene.lines[0];
  const span = l ? l.frames : D * 0.7;
  const at = (i: number) => Math.round((l?.at ?? 10) + (span * i) / RECAP.length) - 6;
  const cw = 318, gap = 26, total = RECAP.length * cw + (RECAP.length - 1) * gap;
  return (
    <AbsoluteFill style={{ opacity: sceneFade(frame, D) }}>
      <div style={{ position: "absolute", left: 110, top: 62 }}><BrandLockup size={30} /></div>
      <div style={{ position: "absolute", top: 190, left: 0, right: 0, textAlign: "center", fontFamily: FONT,
        opacity: prog(frame, 2, 20) }}>
        <div style={{ fontSize: 26, fontWeight: 700, color: C.accent, letterSpacing: 2 }}>UDJ 주요 기능</div>
        <div style={{ fontSize: 58, fontWeight: 800, color: C.ink, letterSpacing: -1.5, marginTop: 10 }}>학교 찾기부터 진로 탐색까지</div>
      </div>
      <div style={{ position: "absolute", top: 400, left: (1920 - total) / 2, display: "flex", gap }}>
        {RECAP.map((c, i) => {
          const a = prog(frame, at(i), 18);
          return (
            <div key={c.label} style={{ width: cw, opacity: a, transform: `translateY(${(1 - a) * 40}px)`,
              background: C.surface, borderRadius: 22, overflow: "hidden", border: `1px solid ${C.lineSoft}`,
              boxShadow: "0 18px 40px rgba(60,20,10,0.10)", fontFamily: FONT }}>
              <Thumb img={c.img} crop={c.crop} w={cw} h={210} />
              <div style={{ padding: "22px 22px 26px", display: "flex", alignItems: "center", gap: 14 }}>
                <div style={{ width: 52, height: 52, borderRadius: 15, background: C.accentSoft, display: "grid", placeItems: "center" }}>
                  <Icon name={c.icon} size={30} color={C.accent} />
                </div>
                <span style={{ fontSize: 30, fontWeight: 800, color: C.ink, letterSpacing: -0.5 }}>{c.label}</span>
              </div>
            </div>
          );
        })}
      </div>
      <Subtitles scene={scene} />
    </AbsoluteFill>
  );
};

/* ───────────────────────── 이용 대상 ───────────────────────── */
const UserCard: React.FC<{ icon: string; who: string; lead: string; items: string[]; img: string; crop: Rect; a: number; note?: string; w: number }> = ({
  icon, who, lead, items, img, crop, a, note, w,
}) => (
  <div style={{ width: w, opacity: a, transform: `translateY(${(1 - a) * 40}px)`, background: C.surface, borderRadius: 26,
    overflow: "hidden", border: `1px solid ${C.lineSoft}`, boxShadow: "0 20px 50px rgba(60,20,10,0.10)", fontFamily: FONT }}>
    <div style={{ padding: "36px 40px 28px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
        <div style={{ width: 72, height: 72, borderRadius: 20, background: C.accentSoft, display: "grid", placeItems: "center" }}>
          <Icon name={icon} size={42} color={C.accent} />
        </div>
        <div>
          <div style={{ fontSize: 46, fontWeight: 850, color: C.ink, letterSpacing: -1 }}>{who}</div>
          <div style={{ fontSize: 24, color: C.steel, fontWeight: 600, marginTop: 2 }}>{lead}</div>
        </div>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 26 }}>
        {items.map((it) => (
          <span key={it} style={{ fontSize: 22, fontWeight: 650, padding: "9px 16px", borderRadius: 999, border: `1.5px solid ${C.line}`, color: C.ink }}>{it}</span>
        ))}
      </div>
      {note && <div style={{ fontSize: 19, color: C.muted, marginTop: 18 }}>{note}</div>}
    </div>
    <div style={{ borderTop: `1px solid ${C.lineSoft}` }}>
      <Thumb img={img} crop={crop} w={w} h={330} fit="contain" />
    </div>
  </div>
);
PAGE_H.signup = 900;
PAGE_H.school_account_request = 900;

export const UsersScene: React.FC<SceneProps> = ({ scene }) => {
  const frame = useCurrentFrame();
  const D = scene.frames;
  const two = scene.lines.length > 1;
  const L1 = two ? lineAt(scene, 1) : D;
  const w = two ? 760 : 900;
  return (
    <AbsoluteFill style={{ opacity: sceneFade(frame, D) }}>
      <div style={{ position: "absolute", left: 110, top: 62 }}><BrandLockup size={30} /></div>
      <div style={{ position: "absolute", top: 150, left: 0, right: 0, textAlign: "center", fontFamily: FONT, opacity: prog(frame, 2, 20) }}>
        <div style={{ fontSize: 26, fontWeight: 700, color: C.accent, letterSpacing: 2 }}>누가 이용하나요?</div>
      </div>
      <div style={{ position: "absolute", top: 225, left: 0, right: 0, display: "flex", justifyContent: "center", gap: 40 }}>
        <UserCard w={w} a={prog(frame, 8, 22)} icon="family" who="학생 · 학부모" lead="직업계고 진학을 고민할 때"
          items={["학교 검색·비교", "진로 테스트", "학교에 문의"]} note="학교 검색과 진로 테스트는 로그인 없이 이용할 수 있어요."
          img="signup" crop={{ x: 500, y: 100, w: 500, h: 330 }} />
        {two && (
          <UserCard w={w} a={prog(frame, L1 - 4, 22)} icon="building" who="학교" lead="학교 계정으로 직접 소개"
            items={["학교 정보·학과·사진", "학교 일정", "문의 답변"]} note="학교 계정은 신청 후 담당자 확인을 거쳐 발급돼요."
            img="school_account_request" crop={{ x: 440, y: 100, w: 600, h: 330 }} />
        )}
      </div>
      <Subtitles scene={scene} />
    </AbsoluteFill>
  );
};

/* ───────────────────────── 엔딩 ───────────────────────── */
export const OutroScene: React.FC<SceneProps> = ({ scene }) => {
  const frame = useCurrentFrame();
  const D = scene.frames;
  const a = prog(frame, 0, 20);
  const b = prog(frame, 12, 22);
  const c = prog(frame, 26, 22);
  const end = 1 - prog(frame, D - 8, 8, ease);
  const fr = prog(frame, 18, 40);
  return (
    <AbsoluteFill style={{ opacity: Math.min(a, end), fontFamily: FONT }}>
      <div style={{ position: "absolute", top: 120, left: 0, right: 0, display: "flex", flexDirection: "column", alignItems: "center" }}>
        <div style={{ fontSize: 40, fontWeight: 650, color: C.steel, opacity: a, transform: `translateY(${(1 - a) * 14}px)` }}>
          직업계고에 필요한 정보를 더 쉽고 편리하게
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 26, marginTop: 34, opacity: b, transform: `translateY(${(1 - b) * 18}px)` }}>
          <BrandMark size={92} />
          <span style={{ fontSize: 88, fontWeight: 850, letterSpacing: -2.5, color: C.ink }}>
            우리동네 <span style={{ color: C.accent }}>직업계고</span>
          </span>
          <span style={{ fontSize: 44, fontWeight: 800, color: "#fff", background: C.accent, padding: "4px 20px", borderRadius: 14, letterSpacing: 4 }}>UDJ</span>
        </div>
        <div style={{ marginTop: 36, opacity: c, transform: `scale(${0.94 + c * 0.06})`, display: "flex", alignItems: "center", gap: 14,
          background: C.ink, color: "#fff", padding: "16px 34px", borderRadius: 999, fontSize: 40, fontWeight: 700, letterSpacing: 0.5 }}>
          <Icon name="link" size={34} color="#ffb199" stroke={2.2} />
          https://{SITE}/
        </div>
      </div>
      <div style={{ opacity: fr }}>
        <BrowserFrame x={(1920 - 1240) / 2} y={kf(frame, [[18, 900], [60, 560]], easeOut)} w={1240}
          layers={[{ name: "home_viewport", h: 900, url: URL("/"), start: 0, cam: [{ f: 0, y: 450, z: 1 }] }]} />
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 260,
        background: `linear-gradient(180deg, rgba(251,246,244,0) 0%, ${C.bgWarm} 85%)` }} />
    </AbsoluteFill>
  );
};

/* ───────────────────────── 15초 몽타주 ───────────────────────── */
export const MontageScene: React.FC<SceneProps> = ({ scene }) => {
  const frame = useCurrentFrame();
  const D = scene.frames;
  const n = 3, seg = Math.floor(D / n);
  const items = [
    { label: "학교 검색", icon: "search", layer: { name: "search_result_full", h: 1547, url: URL("/search"), cam: [{ f: 0, y: 450, z: 1 }, { f: seg, y: 700, z: 1.04 }] } },
    { label: "학교 정보", icon: "school", layer: { name: "school_25_full", h: 1858, url: URL("/schools/25"), cam: [{ f: seg, y: 450, z: 1 }, { f: seg * 2, x: 620, y: 720, z: 1.25 }] } },
    { label: "진로 테스트", icon: "compass", layer: { name: "quiz_result_full", h: 4182, url: URL("/quiz"), cam: [{ f: seg * 2, y: 300, z: 1.32 }, { f: D, y: 400, z: 1.32 }] } },
  ];
  const cur = Math.min(n - 1, Math.floor(frame / seg));
  const layers: Layer[] = items.map((it, i) => ({ ...it.layer, start: i * seg, fade: 8 }));
  const la = prog(frame, cur * seg, 12);
  return (
    <AbsoluteFill style={{ opacity: sceneFade(frame, D, 8, 8) }}>
      <div style={{ position: "absolute", left: 110, top: 62 }}><BrandLockup size={30} /></div>
      <div style={{ position: "absolute", left: 110, top: 300, fontFamily: FONT }}>
        {items.map((it, i) => (
          <div key={it.label} style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 26,
            opacity: i <= cur ? (i === cur ? 1 : 0.35) : 0.12 }}>
            <div style={{ width: 62, height: 62, borderRadius: 18, background: i === cur ? C.accent : C.accentSoft, display: "grid", placeItems: "center" }}>
              <Icon name={it.icon} size={34} color={i === cur ? "#fff" : C.accent} />
            </div>
            <span style={{ fontSize: 50, fontWeight: 800, color: C.ink, letterSpacing: -1,
              transform: i === cur ? `translateX(${(1 - la) * 12}px)` : undefined }}>{it.label}</span>
          </div>
        ))}
      </div>
      <BrowserFrame x={FX} y={FY} w={FW} layers={layers} />
      <Subtitles scene={scene} />
    </AbsoluteFill>
  );
};

export const SCENES: Record<string, React.FC<SceneProps>> = {
  intro: IntroScene, home: HomeScene, search: SearchScene, map: MapScene, school: SchoolScene,
  compare: CompareScene, admission: AdmissionScene, quiz: QuizScene, recap: RecapScene,
  users: UsersScene, outro: OutroScene, montage: MontageScene,
};
export const FEATURE_IDS = ["home", "search", "map", "school", "compare", "admission", "quiz"];
