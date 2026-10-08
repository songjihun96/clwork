// 학교·교사용 영상의 기능 시연 장면 정의.
// 좌표는 모두 캡처 화면의 CSS px(가로 1440). R("...") 은 capture_school.mjs 가 기록한 실제 요소 위치다.
import React from "react";
import { Cursor, Highlight, Typing } from "../components/Overlays";
import type { Rect, SceneT } from "../lib";
import { R, Spec, timing } from "./Demo";

const Z = (x: number, y: number, z: number) => ({ x, y, z });
const span = (a: Rect, b: Rect): Rect => ({ x: Math.min(a.x, b.x), y: Math.min(a.y, b.y),
  w: Math.max(a.x + a.w, b.x + b.w) - Math.min(a.x, b.x), h: Math.max(a.y + a.h, b.y + b.h) - Math.min(a.y, b.y) });
const mid = (r: Rect) => ({ x: r.x + r.w / 2, y: r.y + r.h / 2 });
const field = (r: Rect): Rect => ({ x: r.x, y: r.y + r.h - 38, w: r.w, h: 38 }); // label 아래 입력칸

type SpecFn = (s: SceneT) => Spec;

/* ───────── 02 학교 계정 시작하기 ───────── */
const request: SpecFn = (s) => {
  const { L, E, D } = timing(s);
  const typeAt = L(1) + 14, pick = L(1) + 62, filled = pick + 12, submit = Math.max(filled + 70, E(1) - 4), done = submit + 10;
  const q = R("req.search"), res = R("req.result"), sub = R("req.submit");
  const info = span(R("req.mname"), R("req.memail"));
  return {
    chapter: "02 학교 계정 시작하기", icon: "building", title: "학교 계정 신청",
    desc: "학교 계정은 직접 가입하지 않고, 신청을 받아 발급합니다.",
    steps: [
      { label: "학교 계정 신청 화면 열기", at: 0 },
      { label: "학교 찾기", at: L(1) },
      { label: "담당자 이름·연락처·이메일 입력", at: filled },
      { label: "신청하기", at: submit - 20 },
      { label: "운영진 확인 전화 → 계정 발급·메일 안내", at: L(2) },
    ],
    use: "신청한 학교의 대표 계정이 만들어지고, 아이디와 임시 비밀번호가 담당자 이메일로 전달됩니다.",
    layers: [
      { shot: "req_empty", start: 0, cam: [{ f: 0, y: 450, z: 1 }, { f: L(0) + 30, ...Z(720, 380, 1.3) }],
        overlay: (m, f) => (<>
          <Typing m={m} frame={f} r={q} text="예시미래" from={typeAt} cps={5} />
          <Cursor m={m} frame={f} show={[L(1) - 20, pick + 4]} keys={[{ f: L(1) - 20, x: 900, y: 600 }, { f: L(1) + 6, x: q.x + 80, y: q.y + 19, click: true }]} />
        </>) },
      { shot: "req_search", start: typeAt + 30, fade: 6, cam: [{ f: 0, ...Z(720, 380, 1.3) }],
        overlay: (m, f) => (<>
          <Highlight m={m} frame={f} r={res} from={typeAt + 34} to={pick + 6} pad={4} dim={0.12} />
          <Cursor m={m} frame={f} keys={[{ f: typeAt + 30, x: q.x + 80, y: q.y + 19 }, { f: pick, x: res.x + 120, y: res.y + 22, click: true }]} />
        </>) },
      { shot: "req_filled", start: filled, fade: 8,
        cam: [{ f: filled, ...Z(720, 380, 1.3) }, { f: filled + 40, ...Z(720, 520, 1.2) }, { f: submit - 30, ...Z(720, 520, 1.2) }, { f: submit - 8, ...Z(720, 700, 1.2) }],
        overlay: (m, f) => (<>
          <Highlight m={m} frame={f} r={info} from={filled + 20} to={submit - 24} pad={8} dim={0.15} />
          <Cursor m={m} frame={f} show={[submit - 40, done]} keys={[{ f: submit - 40, x: 900, y: 600 }, { f: submit, ...mid(sub), click: true }]} />
        </>) },
      { shot: "req_done", start: done, cam: [{ f: done, ...Z(720, 330, 1.35) }, { f: D, ...Z(720, 330, 1.4) }],
        overlay: (m, f) => <Highlight m={m} frame={f} r={{ x: 460, y: 186, w: 520, h: 70 }} from={L(2)} to={D} pad={8} dim={0.18} /> },
    ],
  };
};

const firstlogin: SpecFn = (s) => {
  const { L, E, D } = timing(s);
  const em = R("login.email"), pw = R("login.pw"), btn = R("login.btn");
  const t0 = L(0) + 6, pwAt = t0 + 100, filled = pwAt + 50, click = filled + 14, ms = click + 12;
  const bannerBtn = R("ms.banner_btn"), toPw = Math.max(L(1) + 60, ms + 40);
  return {
    chapter: "02 학교 계정 시작하기", icon: "user", title: "첫 로그인",
    desc: "안내받은 이메일과 임시 비밀번호로 로그인합니다.",
    steps: [
      { label: "이메일·임시 비밀번호 입력", at: 0 },
      { label: "학교 관리 화면으로 이동", at: ms },
      { label: "새 비밀번호로 변경", at: L(1) },
    ],
    use: "임시 비밀번호는 전화·메일로 전달된 값이라, 첫 로그인 때 바꾸도록 안내합니다.",
    layers: [
      { shot: "login_empty", start: 0, cam: [{ f: 0, ...Z(720, 300, 1.45) }],
        overlay: (m, f) => (<>
          <Typing m={m} frame={f} r={em} text="jinro.demo@example.com" from={t0} cps={14} />
          <Typing m={m} frame={f} r={pw} text={"••••••••••••••"} from={pwAt} cps={16} />
          <Cursor m={m} frame={f} keys={[{ f: 0, x: 900, y: 420 }, { f: t0 - 4, x: em.x + 100, y: em.y + 19, click: true }, { f: pwAt - 4, x: pw.x + 100, y: pw.y + 19, click: true }]} />
        </>) },
      { shot: "login_filled", start: filled, fade: 4, cam: [{ f: 0, ...Z(720, 300, 1.45) }],
        overlay: (m, f) => <Cursor m={m} frame={f} keys={[{ f: filled, x: pw.x + 100, y: pw.y + 19 }, { f: click, ...mid(btn), click: true }]} /> },
      { shot: "ms_first", start: ms, cam: [{ f: ms, y: 450, z: 1 }, { f: L(1), y: 450, z: 1 }, { f: L(1) + 30, ...Z(900, 220, 1.35) }],
        overlay: (m, f) => (<>
          <Highlight m={m} frame={f} r={R("ms.banner")} from={L(1)} to={toPw} pad={6} dim={0.15} />
          <Cursor m={m} frame={f} show={[L(1) + 20, toPw + 4]} keys={[{ f: L(1) + 20, x: 900, y: 400 }, { f: toPw - 6, ...mid(bannerBtn), click: true }]} />
        </>) },
      { shot: "pw_change", start: toPw, cam: [{ f: toPw, ...Z(720, 330, 1.3) }, { f: D, ...Z(720, 340, 1.32) }] },
    ],
  };
};

/* ───────── 03 학교 관리 화면 ───────── */
const TABS = ["통계", "학교 정보", "문의 관리", "학교일정등록", "취업/진학 정보", "노출 플랜"];
const overview: SpecFn = (s) => {
  const { L, E, D } = timing(s);
  const per = (E(0) - L(0)) / 6;
  const at = (i: number) => Math.round(L(0) + i * per);
  return {
    chapter: "03 학교 관리 화면", icon: "school", title: "학교 관리 화면",
    desc: "학교 계정으로 로그인하면 여섯 개 탭으로 학교를 관리합니다.",
    steps: TABS.map((t, i) => ({ label: t, at: at(i) })),
    use: "상단의 'D-' 표시로 이용 중인 플랜이 언제 끝나는지 바로 볼 수 있습니다.",
    layers: [{ shot: "ms_stats", start: 0, cam: [{ f: 0, y: 450, z: 1 }, { f: L(0), ...Z(560, 260, 1.45) }, { f: E(0), ...Z(560, 260, 1.45) }, { f: L(1), ...Z(500, 160, 1.5) }],
      overlay: (m, f) => (<>
        {TABS.map((_, i) => <Highlight key={i} m={m} frame={f} r={R(`ms.tab${i}`)} from={at(i)} to={at(i + 1) + 4} pad={4} dim={0.12} radius={8} />)}
        <Highlight m={m} frame={f} r={R("ms.dday2")} from={L(1)} to={D} pad={6} dim={0.15} radius={999} />
      </>) }],
  };
};

const profile: SpecFn = (s) => {
  const { L, E, D } = timing(s);
  const save = R("pf.save"), saveAt = L(3) + 24, savedAt = saveAt + 10, pubAt = savedAt + 80;
  return {
    chapter: "03 학교 관리 화면", icon: "school", title: "학교 정보",
    desc: "학교가 직접 소개할 내용을 입력하면 학교 페이지에 반영됩니다.",
    steps: [
      { label: "학교 정보 탭 열기", at: 0 },
      { label: "한 줄 소개·대표 이미지·기숙사", at: L(1) },
      { label: "개설 학과·학교 소개·실습 시설·소개 영상", at: L(2) },
      { label: "변경사항 저장", at: L(3) },
      { label: "학교 페이지에서 확인", at: pubAt },
    ],
    use: "학교 이름·주소·계열은 나이스(NEIS) 값이라 바꿀 수 없고, 틀린 곳은 포털 관리자에게 알립니다.",
    layers: [
      { shot: "ms_profile_empty", start: 0, cam: [{ f: 0, y: 450, z: 1 }, { f: L(0) + 20, ...Z(720, 420, 1.1) }],
        overlay: (m, f) => <Highlight m={m} frame={f} r={{ x: 120, y: 258, w: 1200, h: 40 }} from={L(0) + 20} to={L(1)} pad={4} dim={0.15} radius={10} /> },
      { shot: "ms_profile_filled", start: L(1), fade: 14,
        cam: [{ f: L(1), ...Z(720, 440, 1.15) }, { f: L(2), ...Z(720, 440, 1.15) }, { f: L(2) + 40, ...Z(720, 950, 1.1) }, { f: L(3) - 10, ...Z(720, 1180, 1.1) }, { f: L(3) + 10, ...Z(720, 1250, 1.1) }],
        overlay: (m, f) => (<>
          <Highlight m={m} frame={f} r={R("pf.slogan")} from={L(1) + 10} to={L(1) + 90} dim={0.15} />
          <Highlight m={m} frame={f} r={span(R("pf.dorm"), { x: 120, y: 450, w: 400, h: 30 })} from={L(1) + 80} to={L(2)} dim={0.15} />
          <Highlight m={m} frame={f} r={R("pf.depts")} from={L(2) + 40} to={L(2) + 100} dim={0.15} />
          <Highlight m={m} frame={f} r={span(R("pf.intro"), R("pf.facil"))} from={L(2) + 90} to={L(2) + 170} dim={0.15} />
          <Highlight m={m} frame={f} r={R("pf.video")} from={L(2) + 160} to={L(3)} dim={0.15} />
          <Cursor m={m} frame={f} show={[L(3) - 6, savedAt]} keys={[{ f: L(3) - 6, x: 700, y: 1300 }, { f: saveAt, ...mid(save), click: true }]} />
        </>) },
      { shot: "ms_profile_saved", start: savedAt, cam: [{ f: 0, ...Z(720, 420, 1.25) }],
        overlay: (m, f) => <Highlight m={m} frame={f} r={{ x: 460, y: 375, w: 520, h: 145 }} from={savedAt + 8} to={pubAt} pad={6} dim={0} /> },
      { shot: "pub_school_after", start: pubAt, cam: [{ f: pubAt, ...Z(720, 420, 1.05) }, { f: pubAt + 50, ...Z(720, 420, 1.05) }, { f: D - 30, ...Z(600, 980, 1.15) }],
        overlay: (m, f) => (<>
          <Highlight m={m} frame={f} r={R("pub.hero")} from={pubAt + 10} to={pubAt + 60} dim={0.15} />
          <Highlight m={m} frame={f} r={span(R("pub.intro"), R("pub.facil"))} from={pubAt + 70} to={D} dim={0.15} />
        </>) },
    ],
  };
};

const stats: SpecFn = (s) => {
  const { L, D } = timing(s);
  return {
    chapter: "03 학교 관리 화면", icon: "chart", title: "통계",
    desc: "학교 페이지가 얼마나 조회되고 즐겨찾기되는지 확인합니다.",
    steps: [{ label: "누적 조회수·즐겨찾기·노출 순서", at: L(0) }, { label: "최근 14일 일별 조회수", at: L(1) }],
    use: "학교 정보를 갱신하거나 일정을 등록한 뒤 조회 추이를 살펴볼 수 있습니다.",
    layers: [{ shot: "ms_stats", start: 0, cam: [{ f: 0, y: 450, z: 1 }, { f: L(0) + 20, ...Z(720, 300, 1.2) }, { f: L(1), ...Z(720, 300, 1.2) }, { f: L(1) + 30, ...Z(720, 540, 1.12) }],
      overlay: (m, f) => (<>
        <Highlight m={m} frame={f} r={R("ms.stat_cards")} from={L(0) + 10} to={L(1) + 6} dim={0.15} />
        <Highlight m={m} frame={f} r={R("ms.chart")} from={L(1) + 20} to={D} dim={0.12} />
      </>) }],
  };
};

const plan: SpecFn = (s) => {
  const { L, D } = timing(s);
  // 플랜 카드 4장: '현재 플랜' 상자 아래 ~ '플랜 신청' 위 (2026-10-03 재캡처 기준)
  const apply = R("plan.apply"), orders = R("plan.orders");
  const cards = { x: 120, y: apply.y - 335, w: 1200, h: 318 };
  const lowY = Math.round((apply.y + orders.y + orders.h) / 2);
  return {
    chapter: "03 학교 관리 화면", icon: "chart", title: "노출 플랜",
    desc: "사용 중인 기능과 플랜별 혜택을 확인하고 플랜을 신청합니다.",
    steps: [
      { label: "현재 사용 중인 기능 확인", at: L(0) },
      { label: "플랜별 혜택 비교", at: L(1) },
      { label: "플랜 신청 → 입금 → 관리자 승인", at: L(2) },
      { label: "견적서·계약서·명세서 확인", at: L(2) + 120 },
    ],
    use: "가격과 혜택은 운영 사이트 공개 값과 같습니다(2026년 10월 기준).",
    layers: [{ shot: "ms_plan", start: 0,
      cam: [{ f: 0, y: 450, z: 1 }, { f: L(0) + 20, ...Z(720, 380, 1.12) }, { f: L(1), ...Z(720, 380, 1.12) }, { f: L(1) + 30, ...Z(720, cards.y + cards.h / 2, 1.05) }, { f: L(2), ...Z(720, cards.y + cards.h / 2, 1.05) }, { f: L(2) + 35, ...Z(720, lowY, 1.05) }],
      overlay: (m, f) => (<>
        <Highlight m={m} frame={f} r={R("plan.current")} from={L(0) + 10} to={L(1) + 6} dim={0.15} />
        <Highlight m={m} frame={f} r={cards} from={L(1) + 30} to={L(2) + 6} dim={0.12} />
        <Highlight m={m} frame={f} r={R("plan.apply")} from={L(2) + 30} to={L(2) + 120} dim={0.12} />
        <Highlight m={m} frame={f} r={R("plan.orders")} from={L(2) + 120} to={D} dim={0.12} />
      </>) }],
  };
};

/* ───────── 04 담당 선생님 업무 ───────── */
const inquiry: SpecFn = (s) => {
  const { L, E, D } = timing(s);
  const sub = R("pubq.submit"), subAt = Math.max(L(0) + 90, E(0) - 6), done = subAt + 10;
  const send = R("iq.first_send"), sendAt = L(2) + 110, sent = sendAt + 10;
  return {
    chapter: "04 담당 선생님 업무", icon: "mail", title: "문의 관리",
    desc: "학교 페이지로 들어온 문의에 답하면 문의자 이메일로 발송됩니다.",
    steps: [
      { label: "학생·학부모가 학교 페이지에서 문의", at: 0 },
      { label: "문의 관리 탭에서 확인", at: L(1) },
      { label: "답변 입력 → 저장 및 발송", at: L(2) },
      { label: "새 문의 알림 메일 받기", at: L(3) },
      { label: "처리 끝난 문의 삭제(1년 뒤 자동 파기)", at: L(4) },
    ],
    use: "로그인은 학교 대표 계정으로 하고, 알림 메일은 담당 선생님 주소로 받을 수 있습니다.",
    layers: [
      { shot: "pub_inquiry_filled", start: 0, cam: [{ f: 0, ...Z(560, 1790, 1.2) }],
        overlay: (m, f) => (<>
          <Highlight m={m} frame={f} r={R("pubq.form")} from={8} to={subAt} dim={0.12} />
          <Cursor m={m} frame={f} show={[subAt - 34, done]} keys={[{ f: subAt - 34, x: 700, y: 1900 }, { f: subAt, ...mid(sub), click: true }]} />
        </>) },
      { shot: "pub_inquiry_done", start: done, cam: [{ f: done, ...Z(600, 1500, 1.15) }] },
      { shot: "ms_inq_list", start: L(1), fade: 14, cam: [{ f: L(1), ...Z(720, R("iq.first").y + 120, 1.05) }],
        overlay: (m, f) => <Highlight m={m} frame={f} r={R("iq.first")} from={L(1) + 14} to={L(2)} dim={0.15} /> },
      { shot: "ms_inq_typed", start: L(2), fade: 10, cam: [{ f: L(2), ...Z(720, R("iq.first_text").y + 40, 1.2) }],
        overlay: (m, f) => (<>
          <Highlight m={m} frame={f} r={R("iq.first_text")} from={L(2) + 8} to={L(2) + 70} dim={0.15} />
          <Highlight m={m} frame={f} r={R("iq.first_attach")} from={L(2) + 70} to={sendAt - 6} dim={0.15} radius={8} />
          <Cursor m={m} frame={f} show={[L(2) + 60, sent]} keys={[{ f: L(2) + 60, x: 700, y: 1060 }, { f: L(2) + 80, ...mid(R("iq.first_attach")) }, { f: sendAt, ...mid(send), click: true }]} />
        </>) },
      { shot: "ms_inq_sent", start: sent, cam: [{ f: sent, ...Z(720, R("iq.sent_item").y + 110, 1.2) }],
        overlay: (m, f) => <Highlight m={m} frame={f} r={R("iq.sent_item")} from={sent + 10} to={L(3)} dim={0.15} /> },
      { shot: "ms_inq_notify", start: L(3), fade: 12, cam: [{ f: L(3), ...Z(720, 360, 1.15) }, { f: L(4), ...Z(720, 360, 1.15) }, { f: L(4) + 30, ...Z(720, 300, 1.15) }],
        overlay: (m, f) => (<>
          <Highlight m={m} frame={f} r={R("iq.notify_v")} from={L(3) + 10} to={L(4)} dim={0.15} />
          <Highlight m={m} frame={f} r={{ x: 120, y: 258, w: 1200, h: 40 }} from={L(4) + 20} to={D} pad={4} dim={0.15} radius={10} />
        </>) },
    ],
  };
};

const events: SpecFn = (s) => {
  const { L, E, D } = timing(s);
  const add = R("ev.add"), addAt = E(1) + 14, added = addAt + 10;
  const seg = (D - L(2)) / 3;
  const a = L(2), b = Math.round(L(2) + seg), c = Math.round(L(2) + seg * 2);
  const fields = [R("ev.kind"), R("ev.title"), R("ev.date"), R("ev.time"), R("ev.place")];
  const per = Math.max(20, (addAt - L(1) - 30) / fields.length);
  return {
    chapter: "04 담당 선생님 업무", icon: "home", title: "학교일정등록",
    desc: "학교 설명회와 참가 행사 일정을 등록합니다.",
    steps: [
      { label: "일정 종류 선택 (설명회·참가 행사)", at: 0 },
      { label: "이름·날짜·시간·장소 입력", at: L(1) },
      { label: "일정 추가", at: addAt - 10 },
      { label: "일정 모아보기·학교 페이지·즐겨찾기에 D-day", at: L(2) },
    ],
    use: "일정 등록은 베이직 플랜부터 쓸 수 있는 플랜 혜택입니다.",
    layers: [
      { shot: "ms_events_empty", start: 0, cam: [{ f: 0, y: 450, z: 1 }, { f: L(0) + 20, ...Z(720, 560, 1.1) }],
        overlay: (m, f) => <Highlight m={m} frame={f} r={R("ev.form")} from={L(0) + 20} to={L(1)} dim={0.12} /> },
      { shot: "ms_events_filled", start: L(1), fade: 12, cam: [{ f: L(1), ...Z(720, 560, 1.1) }, { f: addAt - 20, ...Z(720, 640, 1.1) }],
        overlay: (m, f) => (<>
          {fields.map((r, i) => <Highlight key={i} m={m} frame={f} r={r} from={Math.round(L(1) + 10 + i * per)} to={Math.round(L(1) + 10 + (i + 1) * per + 4)} dim={0.12} />)}
          <Cursor m={m} frame={f} show={[addAt - 30, added]} keys={[{ f: addAt - 30, x: 700, y: 760 }, { f: addAt, ...mid(add), click: true }]} />
        </>) },
      { shot: "ms_events_added", start: added, cam: [{ f: added, ...Z(720, 1080, 1.15) }],
        overlay: (m, f) => <Highlight m={m} frame={f} r={R("ev.list")} from={added + 10} to={a} dim={0.15} /> },
      { shot: "pub_events", start: a, fade: 12, url: "udjschool.ggm.kr/events", cam: [{ f: a, ...Z(720, 470, 1.1) }],
        overlay: (m, f) => <Highlight m={m} frame={f} r={{ x: 120, y: 520, w: 1200, h: 280 }} from={a + 10} to={b} dim={0.12} /> },
      { shot: "pub_school_events", start: b, fade: 12, cam: [{ f: b, ...Z(600, 1420, 1.25) }],
        overlay: (m, f) => <Highlight m={m} frame={f} r={R("pub2.events")} from={b + 10} to={c} dim={0.15} /> },
      { shot: "stu_fav_events", start: c, fade: 12, cam: [{ f: c, ...Z(720, 300, 1.3) }],
        overlay: (m, f) => <Highlight m={m} frame={f} r={{ x: 120, y: 205, w: 1200, h: 90 }} from={c + 10} to={D} dim={0.12} /> },
    ],
  };
};

const ADM_TABS = ["adm_stats", "adm_univ", "adm_emp", "adm_employers"];
const admission: SpecFn = (s) => {
  const { L, E, D } = timing(s);
  const per = (L(2) - L(1)) / 3;
  const sub = R("adm.subtabs");
  const pubAt = L(3) + 90;
  return {
    chapter: "04 담당 선생님 업무", icon: "chart", title: "취업/진학 정보",
    desc: "졸업 연도별 진로 자료를 입력하고 공개 범위를 정합니다.",
    steps: [
      { label: "졸업생 기본 통계 (진학·취업 인원)", at: 0 },
      { label: "대학·학과별 진학, 취업 분야, 주요 취업처", at: L(1) },
      { label: "Excel 일괄 업로드", at: L(2) },
      { label: "공개 설정 → 공개 페이지", at: L(3) },
    ],
    use: "취업/진학 정보 공개 페이지는 플래티넘 플랜 혜택입니다. 입력하지 않은 값은 추정하지 않고 비워 둡니다.",
    layers: [
      { shot: "adm_stats", start: 0, cam: [{ f: 0, y: 450, z: 1 }, { f: L(0) + 20, ...Z(720, 560, 1.05) }],
        overlay: (m, f) => (<>
          <Highlight m={m} frame={f} r={R("adm.summary")} from={L(0) + 10} to={L(0) + 90} dim={0.12} />
          <Highlight m={m} frame={f} r={R("adm.form")} from={L(0) + 90} to={L(1)} dim={0.12} />
        </>) },
      ...ADM_TABS.slice(1).map((shot, i) => ({ shot, start: Math.round(L(1) + i * per), fade: 10,
        cam: [{ f: 0, ...Z(720, 760, 1.05) }],
        overlay: (m: any, f: number) => <Highlight m={m} frame={f} r={R(`adm.${shot.replace("adm_", "")}_panel`)} from={Math.round(L(1) + i * per) + 8} to={Math.round(L(1) + (i + 1) * per)} dim={0.12} /> })),
      { shot: "adm_excel", start: L(2), fade: 10, cam: [{ f: 0, ...Z(720, 700, 1.1) }],
        overlay: (m, f) => <Highlight m={m} frame={f} r={R("adm.excel_panel")} from={L(2) + 8} to={L(3)} dim={0.12} /> },
      { shot: "adm_vis", start: L(3), fade: 10, cam: [{ f: 0, ...Z(720, 720, 1.15) }],
        overlay: (m, f) => <Highlight m={m} frame={f} r={R("adm.vis_panel")} from={L(3) + 8} to={pubAt} dim={0.12} /> },
      { shot: "pub_admission", start: pubAt, fade: 12, cam: [{ f: pubAt, y: 450, z: 1 }, { f: D, y: 1150, z: 1 }] },
    ],
  };
};

/* ───────── 04 특성화고신문 보도자료 ───────── */
// 운영 사이트 공개 화면: 영서고(343) 학교 페이지의 '특성화고신문 기사', 홈 하단 연락처.
// 학생 이름·얼굴이 없는 기관 소식 기사만 있는 학교를 골랐다.
const NEWS = { x: 148, y: 903, w: 792, h: 270 };          // news_meta.json(343).news
const CONTACT = { x: 116, y: 2622, w: 216, h: 26 };       // home_full 하단 '070-7867-7970 · news@sinmoon.net'
const press: SpecFn = (s) => {
  const { L, D } = timing(s);
  return {
    chapter: "04 담당 선생님 업무", icon: "link", title: "특성화고신문 보도자료",
    desc: "특성화고신문에 실린 학교 기사가 학교 페이지에 함께 표시됩니다.",
    steps: [
      { label: "특성화고신문에 보도자료 게재", at: 0 },
      { label: "기사 제목의 학교 이름으로 자동 연결", at: L(0) + 60 },
      { label: "학교 페이지 '특성화고신문 기사'에 표시", at: L(0) + 150 },
      { label: "게재 권한 문의: 사이트 하단 전화·이메일", at: L(1) },
    ],
    use: "문의: 070-7867-7970 · news@sinmoon.net (사이트 하단 표기)",
    layers: [
      { shot: "news_343_full", prod: true, url: "udjschool.ggm.kr/schools/343", start: 0,
        cam: [{ f: 0, y: 450, z: 1 }, { f: L(0) + 30, ...Z(560, NEWS.y + NEWS.h / 2, 1.25) }],
        overlay: (m, f) => <Highlight m={m} frame={f} r={NEWS} from={L(0) + 30} to={L(1) + 4} dim={0.15} /> },
      { shot: "home_full", prod: true, url: "udjschool.ggm.kr/", start: L(1), fade: 14,
        cam: [{ f: L(1), ...Z(440, 2620, 1.7) }, { f: D, ...Z(420, 2630, 1.85) }],
        overlay: (m, f) => <Highlight m={m} frame={f} r={CONTACT} from={L(1) + 20} to={D} pad={3} dim={0.15} radius={6} /> },
    ],
  };
};

/* ───────── 05 학생 서비스 ───────── */
const student: SpecFn = (s) => {
  const { L, D } = timing(s);
  return {
    chapter: "05 학생 서비스", icon: "family", title: "학생 서비스",
    desc: "학생에게 우리동네 직업계고를 안내할 때 보여 줄 수 있는 기능입니다.",
    steps: [
      { label: "학교 검색·지도", at: L(1) },
      { label: "학교 페이지·문의", at: L(2) },
      { label: "학교 일정 모아보기", at: L(3) },
      { label: "학교 비교 (최대 3곳)", at: L(4) },
      { label: "진로 테스트", at: L(5) },
      { label: "회원가입 → 즐겨찾기·메모·D-day", at: L(6) },
    ],
    use: "학교 검색과 진로 테스트는 로그인 없이 이용할 수 있습니다.",
    layers: [
      { shot: "home_viewport", prod: true, url: "udjschool.ggm.kr/", start: 0, cam: [{ f: 0, y: 450, z: 1 }] },
      { shot: "search_result_full", prod: true, url: "udjschool.ggm.kr/search", start: L(1), fade: 12, cam: [{ f: L(1), ...Z(720, 420, 1.1) }, { f: L(1) + 120, ...Z(720, 700, 1.05) }] },
      { shot: "search_map", prod: true, url: "udjschool.ggm.kr/search", start: L(1) + 150, fade: 12, cam: [{ f: L(1) + 150, y: 450, z: 1 }, { f: L(2), ...Z(760, 420, 1.3) }] },
      { shot: "stu_school", start: L(2), fade: 12, cam: [{ f: L(2), ...Z(600, 760, 1.1) }, { f: L(3) - 10, ...Z(600, 1500, 1.1) }] },
      { shot: "pub_events", start: L(3), fade: 12, url: "udjschool.ggm.kr/events", cam: [{ f: L(3), ...Z(720, 470, 1.1) }] },
      { shot: "search_compare_modal", prod: true, url: "udjschool.ggm.kr/search", start: L(4), fade: 12, cam: [{ f: L(4), ...Z(720, 470, 1.18) }] },
      { shot: "quiz_result_full", prod: true, url: "udjschool.ggm.kr/quiz", start: L(5), fade: 12, cam: [{ f: L(5), ...Z(720, 330, 1.3) }, { f: L(6) - 10, ...Z(720, 1250, 1.2) }] },
      { shot: "signup", prod: true, url: "udjschool.ggm.kr/signup", start: L(6), fade: 12, cam: [{ f: L(6), ...Z(720, 520, 1.25) }],
        overlay: (m, f) => <Highlight m={m} frame={f} r={{ x: 515, y: 560, w: 410, h: 150 }} from={L(6) + 20} to={L(7)} dim={0.15} /> },
      { shot: "stu_fav", start: L(7), fade: 12, cam: [{ f: L(7), ...Z(720, 440, 1.15) }],
        overlay: (m, f) => <Highlight m={m} frame={f} r={{ ...R("fav.first"), h: R("fav.first").h + 60 }} from={L(7) + 10} to={L(7) + 140} dim={0.12} /> },
      { shot: "stu_fav_events", start: L(7) + 150, fade: 12, cam: [{ f: 0, ...Z(720, 300, 1.3) }] },
      { shot: "home_viewport", prod: true, url: "udjschool.ggm.kr/", start: L(8), fade: 12, cam: [{ f: L(8), y: 450, z: 1 }, { f: D, y: 470, z: 1.04 }] },
    ],
  };
};

export const SPECS: Record<string, SpecFn> = { request, firstlogin, overview, profile, stats, plan, inquiry, events, admission, press, student };
