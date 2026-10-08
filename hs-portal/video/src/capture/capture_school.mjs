// 학교·교사용 영상 캡처 — 로컬 테스트 환경(video/school-demo)에서 실제로 조작하며 찍는다.
//
//   1) udj-demo-backend(8800) · udj-demo-frontend(5190) 를 띄운다 (.claude/launch.json)
//   2) node capture/capture_school.mjs
//
// - 시작할 때 테스트 DB 를 새로 만든다(seed_demo.py). 모든 학교·사람·숫자는 가상이다.
// - 비밀번호는 data/demo_accounts.json 에서만 읽고 화면에는 마스킹된 채로만 나온다.
// - 운영 사이트(udjschool.ggm.kr)에는 접속하지 않는다.
import { chromium } from "playwright-core";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const DEMO = path.resolve(here, "../../school-demo");
const OUT = path.resolve(here, "../../assets/screenshots/school");
const PUB = path.resolve(here, "../public/shots");
const B = "http://127.0.0.1:5190";
fs.mkdirSync(OUT, { recursive: true });

// 0. 테스트 DB 초기화
execFileSync(path.join(DEMO, ".venv/Scripts/python.exe"), [path.join(DEMO, "seed_demo.py")], { stdio: "inherit" });
const ACC = JSON.parse(fs.readFileSync(path.join(DEMO, "data/demo_accounts.json"), "utf8")).accounts;
const sql = (q) => execFileSync(path.join(DEMO, ".venv/Scripts/python.exe"),
  ["-c", `import sqlite3;c=sqlite3.connect(r"${path.join(DEMO, "data/demo.db")}");c.execute("""${q}""");c.commit()`]);

const browser = await chromium.launch({ channel: "msedge" });
const CLEAN = `.fab{display:none!important} *,*::before,*::after{transition:none!important;animation-duration:0s!important;caret-color:transparent!important}`;
const META = { shots: {}, rects: {} };

async function newPage() {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, locale: "ko-KR" });
  const p = await ctx.newPage();
  p.on("pageerror", (e) => console.log("pageerror:", e.message));
  return p;
}
async function settle(p, ms = 700) {
  await p.waitForLoadState("networkidle").catch(() => {});
  await p.addStyleTag({ content: CLEAN }).catch(() => {});
  await p.evaluate(async () => {
    await document.fonts.ready;
    for (let i = 0; i < 40 && !document.fonts.check('20px "Material Symbols Outlined"'); i++) await new Promise((r) => setTimeout(r, 150));
  });
  await p.waitForFunction(() => !/불러오는 중/.test(document.querySelector("main")?.innerText || ""), null, { timeout: 15000 }).catch(() => {});
  await p.waitForTimeout(ms);
}
async function go(p, url, ms) { await p.goto(B + url, { waitUntil: "domcontentloaded" }); await settle(p, ms); }
async function shot(p, name, full = false) {
  const file = path.join(OUT, `${name}.png`);
  let h = 900;
  if (full) {
    // fullPage 캡처는 찍는 순간 창 크기를 바꿔 그래프(recharts)가 다시 그려지다 찍힌다.
    // 창 높이를 먼저 페이지 높이로 맞추고 그래프가 다 그려진 뒤 찍는다.
    h = await p.evaluate(() => document.documentElement.scrollHeight);
    await p.setViewportSize({ width: 1440, height: h });
    await p.waitForTimeout(1800);
    await p.screenshot({ path: file });
    await p.setViewportSize({ width: 1440, height: 900 });
    await p.waitForTimeout(300);
  } else {
    await p.evaluate(() => window.scrollTo(0, 0));
    await p.screenshot({ path: file });
  }
  fs.copyFileSync(file, path.join(PUB, `s_${name}.png`));
  META.shots[name] = { h, url: new URL(p.url()).pathname };
  console.log("shot", name, h);
}
async function rect(p, key, loc) {
  const l = typeof loc === "string" ? p.locator(loc).first() : loc.first();
  if (!(await l.count())) { console.log("  (no rect)", key); return; }
  META.rects[key] = await l.evaluate((el) => {
    const b = el.getBoundingClientRect();
    return { x: Math.round(b.left + scrollX), y: Math.round(b.top + scrollY), w: Math.round(b.width), h: Math.round(b.height) };
  });
}
const field = (p, label) => p.locator(".field", { has: p.locator(`label:text-is("${label}")`) }).locator("input, textarea, select").first();
const panel = (p, title) => p.locator(".panel", { has: p.locator(`h3:text-is("${title}")`) });
const tab = (p, name) => p.locator(".tabs button", { hasText: name }).first();

// ───────── 1. 학교 계정 신청 (비로그인) ─────────
let p = await newPage();
await go(p, "/schools/1");
await shot(p, "pub_school_before", true);
await rect(p, "pub_before.inquiry", "#inquiry");

await go(p, "/school-account-request");
await shot(p, "req_empty");
await rect(p, "req.search", "#sq");
await p.fill("#sq", "예시미래");
await p.waitForTimeout(1200);
await shot(p, "req_search");
await rect(p, "req.result", p.locator("button", { hasText: "예시미래산업고등학교" }));
await p.locator("button", { hasText: "예시미래산업고등학교" }).first().click();
await p.fill("#mname", "진로부 담당");
await p.fill("#mpos", "진로진학부장");
await p.fill("#mphone", "010-0000-0000");
await p.fill("#memail", "jinro.request@example.com");
await p.fill("#sphone", "031-000-0000");
await p.fill("#ctime", "평일 오후 2~4시");
await p.locator("input[type=checkbox]").last().check();
await settle(p, 300);
await shot(p, "req_filled", true);
for (const id of ["mname", "mphone", "memail"]) await rect(p, `req.${id}`, `#${id}`);
await rect(p, "req.submit", p.locator("button", { hasText: "신청하기" }));
await p.locator("button", { hasText: "신청하기" }).first().click();
await settle(p, 1200);
await shot(p, "req_done");

// ───────── 2. 첫 로그인 ─────────
await go(p, "/login");
await shot(p, "login_empty");
await rect(p, "login.email", "#email");
await rect(p, "login.pw", "#pw");
await rect(p, "login.btn", "form button.btn-signal");
await p.fill("#email", ACC.school.email);
await p.fill("#pw", ACC.school.password);
await shot(p, "login_filled");
await p.click("form button.btn-signal");
await p.waitForTimeout(2500);
await settle(p, 2500);
await shot(p, "ms_first");
await rect(p, "ms.banner", p.locator("text=임시 비밀번호로 로그인했습니다").locator(".."));
await rect(p, "ms.banner_btn", p.locator("a", { hasText: "비밀번호 바꾸기" }));
await rect(p, "ms.dday", ".plan-dday");
await go(p, "/account/password");
await shot(p, "pw_change");

// 비밀번호를 바꾼 것으로 처리(문자 인증은 테스트 환경에서 할 수 없어 DB 에서 표시만 끈다)
sql("UPDATE users SET must_change_password=0 WHERE role='school'");
await p.reload(); await go(p, "/my-school", 1200);
await p.waitForTimeout(2500);   // 조회수 그래프(recharts) 막대가 다 자란 뒤 찍는다

// ───────── 3. 학교 관리 화면 ─────────
await shot(p, "ms_stats", true);
await rect(p, "ms.tabs", ".tabs");
for (let i = 0; i < 6; i++) await rect(p, `ms.tab${i}`, p.locator(".tabs button").nth(i));
await rect(p, "ms.dday2", ".plan-dday");
await rect(p, "ms.stat_cards", p.locator(".stat-icon-grid, .stat-grid").first());
await rect(p, "ms.chart", panel(p, "최근 14일 조회수"));

await tab(p, "학교 정보").click(); await settle(p);
await shot(p, "ms_profile_empty", true);
await rect(p, "pf.search_panel", panel(p, "검색 결과에 보이는 정보"));
await rect(p, "pf.detail_panel", panel(p, "상세 페이지에만 보이는 정보"));
await field(p, "한 줄 소개").fill("반도체·전기 현장을 직접 다뤄 보는 실무형 특성화고");
await field(p, "기숙사 운영").selectOption({ label: "운영하지 않음" });
await field(p, "학생 수").fill("540");
await field(p, "취업률 (%)").fill("40.7");
await field(p, "학교 소개").fill("예시미래산업고등학교는 반도체·전기·소프트웨어·디자인 4개 학과를 운영하는 가상의 특성화고입니다.\n1학년부터 학과별 실습실에서 기초 실습을 하고, 3학년에는 현장실습과 취업·진학 준비를 병행합니다.");
await field(p, "실습 시설").fill("반도체 공정 실습실, 스마트전기 제어 실습실, AI 소프트웨어 실습실, 영상·디자인 스튜디오 (가상)");
await settle(p, 300);
await shot(p, "ms_profile_filled", true);
for (const [k, l] of [["slogan", "한 줄 소개"], ["dorm", "기숙사 운영"], ["count", "학생 수"], ["depts", "개설 학과 (한 줄에 하나씩)"], ["intro", "학교 소개"], ["facil", "실습 시설"], ["video", "학교 소개 영상 (유튜브, 최대 4개)"]])
  await rect(p, `pf.${k}`, p.locator(".field", { has: p.locator(`label:text-is("${l}")`) }));
await rect(p, "pf.save", p.locator("button", { hasText: "변경사항 저장" }));
await p.locator("button", { hasText: "변경사항 저장" }).first().click();
await settle(p, 1000);
await shot(p, "ms_profile_saved");

const anon = await newPage();
await go(anon, "/schools/1", 1200);
await shot(anon, "pub_school_after", true);
await rect(anon, "pub.hero", anon.locator("text=반도체·전기 현장을 직접 다뤄 보는").locator(".."));
await rect(anon, "pub.basic", panel(anon, "기본 정보"));
await rect(anon, "pub.depts", panel(anon, "개설 학과"));
await rect(anon, "pub.intro", panel(anon, "학교 소개"));
await rect(anon, "pub.facil", panel(anon, "실습 시설"));
await rect(anon, "pub.events", panel(anon, "학교 설명회"));
await rect(anon, "pub.admission", panel(anon, "취업/진학 정보"));
await rect(anon, "pub.inquiry", "#inquiry");

// ───────── 4. 문의 — 학부모가 남기고 학교가 답한다 ─────────
const inq = anon.locator("#inquiry");
await inq.locator("input.input").nth(0).fill("최가상");
await inq.locator("input.input").nth(1).fill("010-0000-0000");
await inq.locator("input[type=email]").fill("parent2@example.com");
await inq.locator("textarea").fill("학부모와 함께 학교 견학을 할 수 있는 날이 있을까요?");
await inq.locator("input[type=checkbox]").check();
await settle(anon, 300);
await shot(anon, "pub_inquiry_filled", true);
await rect(anon, "pubq.form", "#inquiry");
await rect(anon, "pubq.submit", inq.locator("button", { hasText: "문의 남기기" }));
await inq.locator("button", { hasText: "문의 남기기" }).click();
await settle(anon, 1200);
await shot(anon, "pub_inquiry_done", true);
await rect(anon, "pubq.done", "#inquiry");

await p.reload(); await settle(p, 1000);
await tab(p, "문의 관리").click(); await settle(p);
await shot(p, "ms_inq_list", true);
await rect(p, "iq.notify", panel(p, "새 문의 알림 받기"));
// 순서는 날짜에 따라 바뀌므로, 방금 남긴 학부모 문의(최가상)를 이름으로 찾는다
const firstQ = p.locator(".panel", { has: p.locator("textarea") }).filter({ hasText: "최가상" }).first();
await rect(p, "iq.first", firstQ);
await rect(p, "iq.first_text", firstQ.locator("textarea"));
await rect(p, "iq.first_send", firstQ.locator("button", { hasText: "답변 저장" }));
await rect(p, "iq.first_attach", firstQ.locator("label", { hasText: "파일 첨부" }));
await firstQ.locator("textarea").fill("안녕하세요, 예시미래산업고등학교 진로부입니다.\n11월 7일(토) 오전 10시에 학부모와 함께하는 학교 견학의 날을 운영합니다. 학교 페이지의 학교 설명회 일정을 확인해 주세요.");
await settle(p, 300);
await shot(p, "ms_inq_typed", true);
await firstQ.locator("button", { hasText: "답변 저장" }).click();
await settle(p, 1500);
await shot(p, "ms_inq_sent", true);
await rect(p, "iq.msg", p.locator(".notice-ok, .notice-success").first());
await rect(p, "iq.sent_item", p.locator(".panel", { hasText: "최가상" }).first());
await panel(p, "새 문의 알림 받기").locator("input").fill("jinro.notice@example.com");
await settle(p, 200);
await shot(p, "ms_inq_notify");
await rect(p, "iq.notify_v", panel(p, "새 문의 알림 받기"));

// ───────── 5. 학교 일정 등록 ─────────
await tab(p, "학교일정등록").click(); await settle(p);
await shot(p, "ms_events_empty", true);
await rect(p, "ev.form", panel(p, "일정 추가"));
await field(p, "일정 종류").selectOption({ label: "학교 설명회" }).catch(() => {});
await field(p, "일정 이름").fill("학부모와 함께하는 학교 견학의 날");
await field(p, "시작일").fill("2026-11-07");
await field(p, "시작 시각 (선택)").fill("10:00");
await field(p, "종료 시각 (선택)").fill("12:00");
await field(p, "장소 (선택)").fill("실습동 1층 로비 (가상)");
await field(p, "설명 (선택)").fill("실습실을 둘러보고 학과별 상담을 받을 수 있습니다.");
await settle(p, 300);
await shot(p, "ms_events_filled", true);
for (const [k, l] of [["kind", "일정 종류"], ["title", "일정 이름"], ["date", "시작일"], ["time", "시작 시각 (선택)"], ["place", "장소 (선택)"]])
  await rect(p, `ev.${k}`, p.locator(".field", { has: p.locator(`label:text-is("${l}")`) }));
await rect(p, "ev.add", panel(p, "일정 추가").locator("button", { hasText: "일정 추가" }));
await panel(p, "일정 추가").locator("button", { hasText: "일정 추가" }).click();
await settle(p, 1200);
await shot(p, "ms_events_added", true);
await rect(p, "ev.list", p.locator(".panel", { has: p.locator("h3", { hasText: "등록된 일정" }) }));

await go(anon, "/events", 1200);
await shot(anon, "pub_events", true);
await rect(anon, "pev.first", anon.locator("text=학부모와 함께하는 학교 견학의 날"));
await go(anon, "/schools/1", 1000);
await shot(anon, "pub_school_events", true);
await rect(anon, "pub2.events", panel(anon, "학교 설명회"));

// ───────── 6. 취업/진학 정보 ─────────
await tab(p, "취업/진학 정보").click(); await settle(p, 1200);
await shot(p, "adm_stats", true);
await rect(p, "adm.summary", p.locator(".panel").first());
await rect(p, "adm.subtabs", p.locator("button", { hasText: "졸업생 기본 통계" }).locator(".."));
await rect(p, "adm.form", p.locator(".panel", { hasText: "졸업생 기본 통계" }).last());
for (const [k, t] of [["univ", "주요대학 진학 데이터"], ["emp", "취업 데이터"], ["employers", "주요 취업처"], ["excel", "Excel 일괄 업로드"], ["vis", "공개 설정"]]) {
  await p.locator("button", { hasText: t }).first().click();
  await settle(p, 900);
  await shot(p, `adm_${k}`, true);
  await rect(p, `adm.${k}_panel`, p.locator(".panel").nth(1));
}
await go(anon, "/schools/1/admission", 1500);
await shot(anon, "pub_admission", true);

// ───────── 7. 노출 플랜 ─────────
await tab(p, "노출 플랜").click(); await settle(p, 1000);
await shot(p, "ms_plan", true);
await rect(p, "plan.current", panel(p, "현재 사용 중인 기능"));
await rect(p, "plan.apply", panel(p, "플랜 신청"));
await rect(p, "plan.orders", panel(p, "신청 내역"));

// ───────── 8. 학생 계정 ─────────
const st = await newPage();
await go(st, "/login");
await st.fill("#email", ACC.student.email);
await st.fill("#pw", ACC.student.password);
await st.click("form button.btn-signal");
await st.waitForTimeout(2500);
await go(st, "/favorites", 1200);
await shot(st, "stu_fav", true);
await rect(st, "fav.first", st.locator("text=반도체장비과 · 10월 설명회").locator("xpath=ancestor::*[contains(@class,'panel') or contains(@class,'card')][1]"));
await st.locator("button", { hasText: "학교 일정" }).first().click();
await settle(st, 900);
await shot(st, "stu_fav_events", true);
await go(st, "/schools/1", 1000);
await shot(st, "stu_school", true);

fs.writeFileSync(path.join(OUT, "meta.json"), JSON.stringify(META, null, 2));
fs.copyFileSync(path.join(OUT, "meta.json"), path.resolve(here, "../remotion/school_meta.json"));
await browser.close();
console.log("done", Object.keys(META.shots).length, "shots");
