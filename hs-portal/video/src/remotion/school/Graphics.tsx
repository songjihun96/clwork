import React from "react";
import { AbsoluteFill, Img, useCurrentFrame } from "remotion";
import { C, FONT, SITE } from "../theme";
import { ease, prog, sceneFade, SceneT, shot } from "../lib";
import { BrandLockup, BrandMark, Subtitles } from "../components/UI";
import { Icon } from "../components/Icons";
import { timing } from "./Demo";

const sub = (scene: SceneT, bar?: boolean, hide: number[] = []) =>
  <Subtitles scene={scene} hide={hide} bottom={bar ? 62 : 40} fontSize={33} maxWidth={1600} />;

/** 실제 화면 조각(캡처 일부를 잘라 보여 준다) */
const Crop: React.FC<{ img: string; x: number; y: number; w: number; h: number; W: number; H: number; pageH?: number }> = ({ img, x, y, w, h, W, H, pageH = 900 }) => {
  const s = Math.max(W / w, H / h);
  return (
    <div style={{ width: W, height: H, overflow: "hidden", position: "relative", background: C.bg, borderRadius: 10 }}>
      <Img src={shot(img)} style={{ position: "absolute", width: 1440 * s, height: pageH * s, left: -x * s - (w * s - W) / 2, top: -y * s - (h * s - H) / 2 }} />
    </div>
  );
};

const Card: React.FC<{ a: number; w: number; icon: string; title: string; body?: string; children?: React.ReactNode; active?: boolean }> = ({ a, w, icon, title, body, children, active }) => (
  <div style={{ width: w, opacity: a, transform: `translateY(${(1 - a) * 30}px)`, background: C.surface, borderRadius: 22, overflow: "hidden",
    border: `${active ? 2.5 : 1}px solid ${active ? C.accent : C.lineSoft}`, boxShadow: "0 16px 40px rgba(60,20,10,0.10)", fontFamily: FONT }}>
    {children}
    <div style={{ padding: "20px 24px 24px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ width: 48, height: 48, borderRadius: 14, background: C.accentSoft, display: "grid", placeItems: "center" }}>
          <Icon name={icon} size={28} color={C.accent} />
        </div>
        <span style={{ fontSize: 30, fontWeight: 850, color: C.ink, letterSpacing: -0.6 }}>{title}</span>
      </div>
      {body && <div style={{ marginTop: 12, fontSize: 21, color: C.steel, lineHeight: 1.5, wordBreak: "keep-all" }}>{body}</div>}
    </div>
  </div>
);

/* ── 01 서비스 소개 ── */
export const IntroScene: React.FC<{ scene: SceneT; bar?: boolean }> = ({ scene, bar }) => {
  const f = useCurrentFrame();
  const { L, D } = timing(scene);
  const up = prog(f, L(1) - 10, 30, ease);
  const logoA = prog(f, 2, 24);
  return (
    <AbsoluteFill style={{ opacity: sceneFade(f, D), fontFamily: FONT }}>
      <div style={{ position: "absolute", left: 0, right: 0, top: 300 - up * 210, display: "flex", flexDirection: "column", alignItems: "center",
        transform: `scale(${1 - up * 0.28})`, transformOrigin: "50% 0%" }}>
        <div style={{ opacity: logoA, transform: `scale(${0.7 + logoA * 0.3})` }}><BrandMark size={104} /></div>
        <div style={{ opacity: prog(f, 10, 24), marginTop: 28, fontSize: 92, fontWeight: 850, letterSpacing: -3, color: C.ink }}>
          우리동네 <span style={{ color: C.accent }}>직업계고</span>
        </div>
        <div style={{ opacity: prog(f, 22, 24), marginTop: 22, display: "flex", alignItems: "center", gap: 16 }}>
          <span style={{ fontSize: 36, fontWeight: 700, color: C.steel }}>학교·교사용 기능 안내</span>
        </div>
      </div>
      <div style={{ position: "absolute", top: 430, left: 0, right: 0, display: "flex", justifyContent: "center", gap: 40 }}>
        <Card a={prog(f, L(1) + 4, 22)} w={760} icon="family" title="학생·학부모" body="전국 직업계고를 찾고 비교하고, 학교에 문의합니다.">
          <Crop img="search_result_full" x={120} y={280} w={1200} h={560} W={760} H={300} pageH={1547} />
        </Card>
        <Card a={prog(f, L(1) + 40, 22)} w={760} icon="building" title="학교" body="학교 계정으로 학교 정보를 직접 소개하고 관리합니다.">
          <Crop img="s_ms_stats" x={120} y={40} w={1200} h={560} W={760} H={300} pageH={1069} />
        </Card>
      </div>
      {f >= L(3) - 6 && (
        <div style={{ position: "absolute", top: 352, left: 0, right: 0, display: "flex", justifyContent: "center", opacity: prog(f, L(3) - 6, 14) }}>
          <div style={{ background: "rgba(25,28,29,0.9)", color: "#fff", padding: "10px 24px", borderRadius: 999, fontSize: 24, fontWeight: 700 }}>
            화면 속 학교·인물·숫자는 시연용 가상 데이터입니다
          </div>
        </div>
      )}
      {sub(scene, bar)}
    </AbsoluteFill>
  );
};

/* ── 챕터 영상 앞머리 카드 ── */
export const TitleCard: React.FC<{ scene: SceneT; bar?: boolean }> = ({ scene, bar }) => {
  const f = useCurrentFrame();
  const a = prog(f, 2, 22), b = prog(f, 12, 22);
  return (
    <AbsoluteFill style={{ opacity: sceneFade(f, scene.frames), fontFamily: FONT, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ textAlign: "center", marginTop: -60 }}>
        <div style={{ opacity: a, display: "flex", justifyContent: "center" }}><BrandLockup size={40} /></div>
        <div style={{ opacity: b, transform: `translateY(${(1 - b) * 20}px)`, marginTop: 40, fontSize: 84, fontWeight: 850, color: C.ink, letterSpacing: -2.5 }}>
          {(scene as any).card}
        </div>
        <div style={{ opacity: b, marginTop: 18, fontSize: 28, color: C.steel, fontWeight: 600 }}>학교·교사용 기능 안내 · {SITE}</div>
      </div>
      {sub(scene, bar)}
    </AbsoluteFill>
  );
};

/* ── 04 담당 선생님 업무 개요 ── */
export const TasksScene: React.FC<{ scene: SceneT; bar?: boolean }> = ({ scene, bar }) => {
  const f = useCurrentFrame();
  const { L, D } = timing(scene);
  const items = [
    { icon: "mail", title: "문의 관리", body: "학교 페이지로 들어온 문의에 답변", img: "s_ms_inq_list", y: 870, h: 2228 },
    { icon: "home", title: "학교일정등록", body: "설명회·참가 행사 일정 등록", img: "s_ms_events_added", y: 980, h: 1594 },
    { icon: "chart", title: "취업/진학 정보", body: "졸업생 진로 자료 입력·공개", img: "s_adm_stats", y: 250, h: 1344 },
  ];
  return (
    <AbsoluteFill style={{ opacity: sceneFade(f, D), fontFamily: FONT }}>
      <div style={{ position: "absolute", left: 80, top: 46 }}><BrandLockup size={28} /></div>
      <div style={{ position: "absolute", top: 140, left: 0, right: 0, textAlign: "center", opacity: prog(f, 2, 20) }}>
        <div style={{ fontSize: 22, fontWeight: 800, color: C.accent, letterSpacing: 1 }}>04 담당 선생님 업무</div>
        <div style={{ fontSize: 58, fontWeight: 850, color: C.ink, letterSpacing: -1.5, marginTop: 10 }}>학교 계정으로 처리하는 일</div>
        <div style={{ fontSize: 24, color: C.steel, marginTop: 10 }}>선생님 개인 계정이 아니라, 학교 대표 계정 하나로 로그인해 처리합니다</div>
      </div>
      <div style={{ position: "absolute", top: 380, left: 0, right: 0, display: "flex", justifyContent: "center", gap: 34 }}>
        {items.map((it, i) => (
          <Card key={it.title} a={prog(f, 24 + i * 18, 20)} w={520} icon={it.icon} title={it.title} body={it.body}>
            <Crop img={it.img} x={120} y={it.y} w={1200} h={520} W={520} H={250} pageH={it.h} />
          </Card>
        ))}
      </div>
      {sub(scene, bar)}
    </AbsoluteFill>
  );
};

/* ── 06 학교와 학생의 연결 ── */
const Node: React.FC<{ a: number; on: boolean; icon: string; text: string; side: "l" | "r" }> = ({ a, on, icon, text, side }) => (
  <div style={{ opacity: a, display: "flex", alignItems: "center", gap: 14, height: 86, padding: "0 22px", borderRadius: 18,
    background: on ? C.surface : "rgba(255,255,255,0.6)", border: `2px solid ${on ? C.accent : C.lineSoft}`,
    boxShadow: on ? "0 10px 26px rgba(181,39,1,0.14)" : "none", flexDirection: side === "l" ? "row" : "row" }}>
    <div style={{ width: 48, height: 48, borderRadius: 14, background: on ? C.accent : C.accentSoft, display: "grid", placeItems: "center", flexShrink: 0 }}>
      <Icon name={icon} size={28} color={on ? "#fff" : C.accent} />
    </div>
    <span style={{ fontSize: 25, fontWeight: on ? 800 : 650, color: on ? C.ink : C.steel, wordBreak: "keep-all", lineHeight: 1.3 }}>{text}</span>
  </div>
);

export const ConnectScene: React.FC<{ scene: SceneT; bar?: boolean }> = ({ scene, bar }) => {
  const f = useCurrentFrame();
  const { L, D } = timing(scene);
  const rows = [
    { l: ["school", "학교 정보"], r: ["search", "검색 결과 · 학교 페이지"], at: L(1) },
    { l: ["home", "학교 일정"], r: ["home", "일정 모아보기 · 즐겨찾기 D-day"], at: L(1) + 70 },
    { l: ["chart", "취업/진학 정보"], r: ["chart", "취업/진학 공개 페이지"], at: L(1) + 140 },
    { l: ["mail", "문의 답변"], r: ["mail", "학생·학부모 문의 (이메일로 답변)"], at: L(2), both: true },
    { l: ["chart", "학교 통계"], r: ["user", "학교 페이지 조회 · 즐겨찾기"], at: L(3), back: true },
  ];
  const cur = rows.reduce((acc, r, i) => (f >= r.at ? i : acc), -1);
  return (
    <AbsoluteFill style={{ opacity: sceneFade(f, D), fontFamily: FONT }}>
      <div style={{ position: "absolute", left: 80, top: 46 }}><BrandLockup size={28} /></div>
      <div style={{ position: "absolute", top: 116, left: 0, right: 0, textAlign: "center", opacity: prog(f, 2, 20) }}>
        <div style={{ fontSize: 22, fontWeight: 800, color: C.accent, letterSpacing: 1 }}>06 학교와 학생의 연결</div>
        <div style={{ fontSize: 52, fontWeight: 850, color: C.ink, letterSpacing: -1.5, marginTop: 8 }}>학교 계정에서 입력한 정보가 닿는 곳</div>
      </div>
      <div style={{ position: "absolute", top: 262, left: 230, width: 560, textAlign: "center", fontSize: 24, fontWeight: 800, color: C.accent }}>학교 계정 (학교 관리 화면)</div>
      <div style={{ position: "absolute", top: 262, right: 230, width: 620, textAlign: "center", fontSize: 24, fontWeight: 800, color: C.accent }}>학생·학부모가 보는 화면</div>
      {rows.map((r, i) => {
        const a = Math.max(0.28, prog(f, r.at - 8, 18));   // 처음부터 흐리게 전체 구조를 보여 준다
        const on = i === cur;
        const top = 310 + i * 104;
        const arrowA = prog(f, r.at + 6, 22);
        return (
          <React.Fragment key={i}>
            <div style={{ position: "absolute", top, left: 230, width: 560 }}><Node a={a} on={on} icon={r.l[0]} text={r.l[1]} side="l" /></div>
            <div style={{ position: "absolute", top, right: 230, width: 620 }}><Node a={a} on={on} icon={r.r[0]} text={r.r[1]} side="r" /></div>
            {/* 왼쪽 상자 끝(790) ~ 오른쪽 상자 시작(1070) 사이 가운데, 양쪽 30px 여백 */}
            <svg style={{ position: "absolute", top: top + 29, left: 820, opacity: a }} width="220" height="28" viewBox="0 0 220 28">
              {(() => {
                const c = on ? C.accent : "#d9b4aa";
                const back = r.back || r.both;
                // 화살표가 가리키는 쪽으로 자라게 그린다
                const x1 = back && !r.both ? 214 - 206 * arrowA : 6, x2 = back && !r.both ? 214 : 6 + 208 * arrowA;
                return (<>
                  <line x1={x1} y1="14" x2={x2} y2="14" stroke={c} strokeWidth="4" strokeLinecap="round" />
                  {!r.back && arrowA > 0.95 && <path d="M200 5 L214 14 L200 23" fill="none" stroke={c} strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />}
                  {back && arrowA > 0.95 && <path d="M20 5 L6 14 L20 23" fill="none" stroke={c} strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />}
                </>);
              })()}
            </svg>
          </React.Fragment>
        );
      })}
      {f >= L(4) - 6 && (
        <div style={{ position: "absolute", top: 838, left: 0, right: 0, display: "flex", justifyContent: "center", opacity: prog(f, L(4) - 6, 16) }}>
          <div style={{ background: C.ink, color: "#fff", borderRadius: 16, padding: "14px 28px", fontSize: 26, fontWeight: 700 }}>
            학교 계정 = 학교를 소개하고 문의에 답하는 계정 <span style={{ color: "#ffb199" }}>(학생 개인 관리 기능 없음)</span>
          </div>
        </div>
      )}
      {sub(scene, bar)}
    </AbsoluteFill>
  );
};

/* ── 07 도입 후 운영 흐름 ── */
export const FlowScene: React.FC<{ scene: SceneT; bar?: boolean }> = ({ scene, bar }) => {
  const f = useCurrentFrame();
  const { L, D } = timing(scene);
  const steps = [
    { icon: "building", t: "학교 계정 신청", d: "학교 찾기·담당자 정보", at: L(1) },
    { icon: "mail", t: "확인 전화·계정 발급", d: "운영진 확인 후 메일 안내", at: L(1) + 55 },
    { icon: "user", t: "첫 로그인", d: "임시 비밀번호 변경", at: L(1) + 110 },
    { icon: "school", t: "학교 정보 입력", d: "학교 페이지 채우기", at: L(2) },
    { icon: "chart", t: "플랜 선택·공개", d: "일정·취업/진학 정보", at: L(2) + 80 },
    { icon: "compare", t: "운영", d: "문의 답변·통계 확인·자료 갱신", at: L(3) },
  ];
  const cur = steps.reduce((acc, s, i) => (f >= s.at ? i : acc), -1);
  const W = 262, G = 22, total = steps.length * W + (steps.length - 1) * G, x0 = (1920 - total) / 2;
  return (
    <AbsoluteFill style={{ opacity: sceneFade(f, D), fontFamily: FONT }}>
      <div style={{ position: "absolute", left: 80, top: 46 }}><BrandLockup size={28} /></div>
      <div style={{ position: "absolute", top: 170, left: 0, right: 0, textAlign: "center", opacity: prog(f, 2, 20) }}>
        <div style={{ fontSize: 22, fontWeight: 800, color: C.accent, letterSpacing: 1 }}>07 도입 후 운영 흐름</div>
        <div style={{ fontSize: 58, fontWeight: 850, color: C.ink, letterSpacing: -1.5, marginTop: 10 }}>학교에서 우리동네 직업계고를 운영하는 순서</div>
      </div>
      {steps.map((s, i) => {
        const a = prog(f, s.at - 8, 18), on = i === cur, done = i < cur;
        return (
          <div key={s.t} style={{ position: "absolute", top: 400, left: x0 + i * (W + G), width: W, opacity: Math.max(0.25, a),
            transform: `translateY(${(1 - a) * 20}px)` }}>
            <div style={{ height: 300, borderRadius: 22, padding: "26px 22px", background: on ? C.surface : done ? "rgba(255,255,255,0.85)" : "rgba(255,255,255,0.55)",
              border: `2px solid ${on ? C.accent : C.lineSoft}`, boxShadow: on ? "0 14px 34px rgba(181,39,1,0.15)" : "none" }}>
              <div style={{ fontSize: 22, fontWeight: 800, color: on || done ? C.accent : C.muted }}>STEP {i + 1}</div>
              <div style={{ width: 62, height: 62, borderRadius: 18, margin: "18px 0", background: on ? C.accent : C.accentSoft, display: "grid", placeItems: "center" }}>
                <Icon name={s.icon} size={34} color={on ? "#fff" : C.accent} />
              </div>
              <div style={{ fontSize: 28, fontWeight: 850, color: C.ink, letterSpacing: -0.6, lineHeight: 1.25, wordBreak: "keep-all" }}>{s.t}</div>
              <div style={{ fontSize: 20, color: C.steel, marginTop: 10, lineHeight: 1.45, wordBreak: "keep-all" }}>{s.d}</div>
            </div>
            {i < steps.length - 1 && (
              <div style={{ position: "absolute", top: 136, right: -G + 2, width: G - 4, height: 28, display: "grid", placeItems: "center", color: done ? C.accent : "#d9b4aa", fontSize: 26, fontWeight: 900 }}>›</div>
            )}
          </div>
        );
      })}
      {f >= L(3) && (
        <div style={{ position: "absolute", top: 740, left: x0 + 5 * (W + G) - 40, width: W + 80, textAlign: "center", fontSize: 22, color: C.accent, fontWeight: 800, opacity: prog(f, L(3) + 20, 16) }}>
          ↻ 학기마다 반복
        </div>
      )}
      {sub(scene, bar)}
    </AbsoluteFill>
  );
};

/* ── 08 마무리 ── */
export const OutroScene: React.FC<{ scene: SceneT; bar?: boolean }> = ({ scene, bar }) => {
  const f = useCurrentFrame();
  const D = scene.frames;
  const a = prog(f, 0, 20), b = prog(f, 12, 22), c = prog(f, 26, 22);
  return (
    <AbsoluteFill style={{ opacity: Math.min(a, 1 - prog(f, D - 10, 10, ease)), fontFamily: FONT }}>
      <div style={{ position: "absolute", top: 230, left: 0, right: 0, display: "flex", flexDirection: "column", alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 26, opacity: b, transform: `translateY(${(1 - b) * 18}px)` }}>
          <BrandMark size={96} />
          <span style={{ fontSize: 92, fontWeight: 850, letterSpacing: -2.5, color: C.ink }}>우리동네 <span style={{ color: C.accent }}>직업계고</span></span>
        </div>
        <div style={{ marginTop: 34, fontSize: 38, fontWeight: 650, color: C.steel, opacity: b }}>
          학교를 알리고, 학생·학부모의 질문에 답하는 직업계고 정보 포털
        </div>
        <div style={{ marginTop: 56, opacity: c, transform: `scale(${0.94 + c * 0.06})`, display: "flex", flexDirection: "column", alignItems: "center", gap: 18 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14, background: C.ink, color: "#fff", padding: "16px 36px", borderRadius: 999, fontSize: 42, fontWeight: 700 }}>
            <Icon name="link" size={36} color="#ffb199" stroke={2.2} /> https://{SITE}/
          </div>
          <div style={{ fontSize: 26, color: C.steel, fontWeight: 600 }}>학교 계정 신청 · {SITE}/school-account-request</div>
        </div>
      </div>
      {sub(scene, bar, [0])}
    </AbsoluteFill>
  );
};
