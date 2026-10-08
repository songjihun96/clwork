// 실제 UDJ(https://udjschool.ggm.kr) 화면을 캡처한다.
//
// - 뷰포트 1440×900, deviceScaleFactor 2 → 2880px 폭 PNG (영상에서 확대해도 선명)
// - 운영 통계를 건드리지 않도록 조회수·방문자 집계 POST 는 가로채서 막는다.
// - 화면 우하단 "오프라인 직업계고설명회 신청" 플로팅 버튼(외부 링크)은 숨긴다.
// - 취업/진학 정보 화면은 학교가 넣은 임의 데이터라 "가상 데이터 예시"로 쓴다.
//   학교명을 "예시고등학교"로 바꿔 캡처한다.
// - 각 장면에서 강조할 요소의 좌표(CSS px)를 rects.json 에 함께 남긴다.
//
// 실행: npm run capture   (Edge 채널 사용 — 별도 브라우저 다운로드 없음)
import { chromium } from "playwright-core";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const BASE = "https://udjschool.ggm.kr";
const here = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(here, "../../assets/screenshots");
const PUBLIC = path.resolve(here, "../public/shots");
fs.mkdirSync(OUT, { recursive: true });
fs.mkdirSync(PUBLIC, { recursive: true });

const VW = 1440, VH = 900, DSF = 2;
const rects = {};

const browser = await chromium.launch({ channel: "msedge" });
const ctx = await browser.newContext({
  viewport: { width: VW, height: VH },
  deviceScaleFactor: DSF,
  locale: "ko-KR",
  colorScheme: "light",
});

// 통계 집계 요청 차단 (학교 조회수, 방문자 수).
// 방문 집계 POST 가 실패하면 화면은 GET /api/visit-stats 로 실제 숫자를 다시 받아 그린다.
await ctx.route(/\/api\/visit$/, (route) =>
  route.request().method() === "POST"
    ? route.fulfill({ status: 503, contentType: "application/json", body: "{}" })
    : route.continue());
await ctx.route(/\/api\/schools\/\d+\/view$/, (route) =>
  route.request().method() === "POST"
    ? route.fulfill({ status: 200, contentType: "application/json", body: '{"ok":true}' })
    : route.continue());

const page = await ctx.newPage();

const CLEAN_CSS = `
  .fab { display: none !important; }
  html { scroll-behavior: auto !important; }
  /* 홈 슬라이드가 전환 도중에 찍혀 두 장이 겹쳐 보이지 않게 전환 효과를 끈다 */
  *, *::before, *::after { transition: none !important; animation-duration: 0s !important; }
  *, *::before, *::after { caret-color: transparent !important; }
`;

async function settle(p = page, extra = 600) {
  await p.waitForLoadState("networkidle").catch(() => {});
  await p.addStyleTag({ content: CLEAN_CSS });
  await p.evaluate(async () => {
    await document.fonts.ready;
    // 아이콘 글꼴(Material Symbols)이 늦게 오면 "search" 같은 글자가 그대로 찍힌다.
    for (let i = 0; i < 40; i++) {
      if (document.fonts.check('20px "Material Symbols Outlined"')) break;
      await new Promise((r) => setTimeout(r, 150));
    }
  });
  // 이미지 로딩 대기
  await p.evaluate(async () => {
    const imgs = [...document.images].filter((i) => !i.complete);
    await Promise.all(imgs.map((i) => new Promise((r) => { i.onload = i.onerror = r; setTimeout(r, 4000); })));
  });
  await p.waitForTimeout(extra);
}

async function noLoading(p = page) {
  await p.waitForFunction(() => !document.querySelector("main")?.innerText.includes("불러오는 중"), null, { timeout: 20000 }).catch(() => {});
}

async function rectOf(sel, p = page) {
  const r = await p.locator(sel).first().evaluate((el) => {
    const b = el.getBoundingClientRect();
    return { x: b.left + window.scrollX, y: b.top + window.scrollY, w: b.width, h: b.height };
  });
  return r;
}

async function shot(name, { full = false, clip } = {}) {
  const file = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: file, fullPage: full, clip });
  fs.copyFileSync(file, path.join(PUBLIC, `${name}.png`));
  const dims = await page.evaluate(() => ({ w: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight }));
  console.log("saved", name, full ? `full ${dims.w}x${dims.h}` : "viewport");
  return dims;
}

const meta = {};

// ───────── 1. 홈 ─────────
await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
await settle(page, 1500);
await shot("home_viewport");
rects.home = {
  hero_title: await rectOf("h1"),
  hero_search: await rectOf("form input.input"),
  hero_quiz_btn: await rectOf("text=진로 테스트 →"),
};
meta.home_full = await shot("home_full", { full: true });
rects.home.stats = await rectOf(".stat-icon-grid");
rects.home.categories = await rectOf("text=계열별로 찾기");
rects.home.news = await rectOf("text=학교 소식");
rects.home.popular = await rectOf("text=인기 특성화고 · 마이스터고");

// ───────── 2. 학교 검색 ─────────
await page.goto(BASE + "/search", { waitUntil: "domcontentloaded" });
await noLoading();
await settle();
await shot("search_top");
rects.search = {
  name: await rectOf("#f-name"),
  region: await rectOf("#f-region"),
  sigungu: await rectOf("#f-sigungu"),
  category: await rectOf("#f-cat"),
  dept: await rectOf("#f-dept"),
  coed: await rectOf("#f-coed"),
  submit: await rectOf(".filter-actions button[type=submit]"),
  form: await rectOf("form.searchbar"),
};

// 검색어 입력 → 결과
await page.fill("#f-name", "공업");
await page.selectOption("#f-region", "경기");
await page.waitForTimeout(500);
await shot("search_typed");
await page.click(".filter-actions button[type=submit]");
await noLoading();
await settle();
await page.evaluate(() => window.scrollTo(0, 0));
await page.waitForTimeout(300);
meta.search_result_full = await shot("search_result_full", { full: true });
rects.search.result_label = await rectOf("text=/검색 결과 [0-9,]+개/");
rects.search.first_card = await rectOf(".card-wrap");
rects.search.card_list = await rectOf(".card-list");
meta.search_result_total = await page.locator("text=/검색 결과 [0-9,]+개/").first().innerText();

// 학과 계열로 찾기 (IT·소프트웨어)
await page.goto(BASE + "/search", { waitUntil: "domcontentloaded" });
await noLoading();
await settle();
await page.selectOption("#f-dept", { label: "IT·소프트웨어" });
await page.waitForTimeout(300);
await shot("search_dept_select");
await page.click(".filter-actions button[type=submit]");
await noLoading();
await settle();
meta.search_dept_full = await shot("search_dept_full", { full: true });
rects.search.dept_result_label = await rectOf("text=/검색 결과 [0-9,]+개/");
rects.search.dept_card_list = await rectOf(".card-list");
meta.search_dept_total = await page.locator("text=/검색 결과 [0-9,]+개/").first().innerText();

// 비교 담기 3곳 → 비교 트레이
const cmpBtns = page.locator(".compare-btn");
for (let i = 0; i < 3; i++) { await cmpBtns.nth(i).click(); await page.waitForTimeout(250); }
await page.evaluate(() => window.scrollTo(0, 380));
await settle(page, 500);
await shot("search_compare_tray");
rects.search.compare_btn = await rectOf(".compare-btn");
// 비교하기 버튼이 있으면 눌러서 비교 화면까지
const cmpOpen = page.locator("button", { hasText: /나란히 비교|비교하기|비교 보기/ }).first();
if (await cmpOpen.count()) {
  await cmpOpen.click();
  await page.waitForTimeout(1500);
  await settle(page, 500);
  await shot("search_compare_modal");
}

// 지도 보기
await page.goto(BASE + "/search", { waitUntil: "domcontentloaded" });
await noLoading();
await settle();
await page.selectOption("#f-region", "서울");
await page.click(".filter-actions button[type=submit]");
await noLoading();
await page.click("button:has-text('지도')");
await page.waitForSelector(".leaflet-container", { timeout: 20000 });
await page.waitForTimeout(3500);
await settle(page, 1500);
const mapBox = await rectOf(".leaflet-container");
await page.evaluate((y) => window.scrollTo(0, Math.max(0, y - 140)), mapBox.y);
await page.waitForTimeout(800);
await shot("search_map");
rects.search.map = mapBox;

// ───────── 3. 학교 상세 ─────────
for (const [id, key] of [[25, "school_25"], [262, "school_262"]]) {
  await page.goto(`${BASE}/schools/${id}`, { waitUntil: "domcontentloaded" });
  await noLoading();
  await settle(page, 1500);
  await shot(`${key}_viewport`);
  meta[`${key}_full`] = await shot(`${key}_full`, { full: true });
  const r = {};
  for (const [k, txt] of [["basic", "기본 정보"], ["depts", "개설 학과"], ["inquiry", "학교에 문의하기"],
    ["contact", "위치 및 연락처"], ["admission", "취업/진학 정보"], ["videos", "학교 소개 영상"], ["news", "특성화고신문 기사"]]) {
    const loc = page.locator(`text="${txt}"`).first();
    if (await loc.count()) {
      // 제목이 든 카드(가장 가까운 큰 상자)를 잡는다
      r[k] = await loc.evaluate((el) => {
        let n = el;
        for (let i = 0; i < 6 && n.parentElement; i++) {
          n = n.parentElement;
          const b = n.getBoundingClientRect();
          if (b.width > 300 && b.height > 80) break;
        }
        const b = n.getBoundingClientRect();
        return { x: b.left + window.scrollX, y: b.top + window.scrollY, w: b.width, h: b.height };
      });
    }
  }
  rects[key] = r;
}

// ───────── 4. 취업/진학 정보 (가상 데이터 예시) ─────────
await page.goto(`${BASE}/schools/262/admission`, { waitUntil: "domcontentloaded" });
await noLoading();
await settle(page, 2000);
await page.evaluate(() => {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const n of nodes) {
    if (n.nodeValue.includes("근명")) n.nodeValue = n.nodeValue.replace(/근명(여자정보)?고등학교/g, "예시고등학교");
  }
  document.title = "예시고등학교 취업/진학 정보";
});
await page.waitForTimeout(300);
await shot("admission_viewport");
meta.admission_full = await shot("admission_full", { full: true });
rects.admission = {};
for (const [k, txt] of [["tabs", "주요 취업처"], ["career", "졸업 후 진로"], ["univ", "주요 진학 대학"], ["employ", "취업 현황"], ["fields", "취업 분야"]]) {
  const loc = page.locator(`text="${txt}"`).first();
  if (await loc.count()) {
    rects.admission[k] = await loc.evaluate((el) => {
      let n = el;
      for (let i = 0; i < 5 && n.parentElement; i++) {
        n = n.parentElement;
        const b = n.getBoundingClientRect();
        if (b.width > 300 && b.height > 120) break;
      }
      const b = n.getBoundingClientRect();
      return { x: b.left + window.scrollX, y: b.top + window.scrollY, w: b.width, h: b.height };
    });
  }
}

// ───────── 5. 진로 테스트 ─────────
await page.goto(`${BASE}/quiz`, { waitUntil: "domcontentloaded" });
await noLoading();
await settle(page, 800);
await shot("quiz_intro");
rects.quiz = { start: await rectOf("button:has-text('테스트 시작하기')") };
meta.quiz_intro_full = await shot("quiz_intro_full", { full: true });

await page.click("button:has-text('테스트 시작하기')");
await page.waitForTimeout(800);

// IT·소프트웨어 쪽으로 기우는 응답 (역문항은 반대로). 응답 편차를 둬서 신뢰도 경고가 안 뜨게 한다.
const IT = /컴퓨터|프로그램|코딩|앱|소프트웨어|데이터|디지털|게임|인터넷|기기|전자|로봇|웹|AI|인공지능/;
const NEG = /지루|끌리지 않|싫|않는다|어렵|부담/;
let qi = 0;
for (; qi < 60; qi++) {
  const label = await page.locator("span.label", { hasText: /\d+ \/ \d+/ }).first().innerText().catch(() => "");
  const m = label.match(/(\d+) \/ (\d+)/);
  if (!m) break;
  const [cur, total] = [Number(m[1]), Number(m[2])];
  const q = await page.locator("h2").first().innerText();
  let v;
  if (IT.test(q)) v = NEG.test(q) ? 1 : 5;
  else v = NEG.test(q) ? 3 : [2, 3, 2, 4, 3][cur % 5];
  if (cur === 7) {
    // 문항 화면 하나는 선택 직전 모습으로 남긴다
    await settle(page, 300);
    await shot("quiz_question");
    rects.quiz.question = await rectOf("h2");
  }
  const opts = page.locator("main button").filter({ hasText: /그렇|보통/ });
  const labels = ["전혀 그렇지 않다", "그렇지 않은 편이다", "보통이다", "그런 편이다", "매우 그렇다"];
  await page.locator("main button", { hasText: labels[v - 1] }).first().click();
  await page.waitForTimeout(cur === total ? 2500 : 350);
  if (cur === total) break;
}
await page.waitForFunction(() => /추천/.test(document.querySelector("main")?.innerText || ""), null, { timeout: 30000 }).catch(() => {});
await settle(page, 2500);
await page.evaluate(() => window.scrollTo(0, 0));
await page.waitForTimeout(400);
await shot("quiz_result_viewport");
meta.quiz_result_full = await shot("quiz_result_full", { full: true });
meta.quiz_result_text = (await page.locator("main").innerText()).slice(0, 2500);

// ───────── 6. 회원가입(사용자 구분) · 학교 계정 신청 · 학교 일정 ─────────
await page.goto(`${BASE}/signup`, { waitUntil: "domcontentloaded" });
await settle(page, 800);
await shot("signup");
meta.signup_text = (await page.locator("main").innerText()).slice(0, 1200);
await page.goto(`${BASE}/school-account-request`, { waitUntil: "domcontentloaded" });
await settle(page, 800);
await shot("school_account_request");
meta.school_req_text = (await page.locator("main").innerText()).slice(0, 1200);
await page.goto(`${BASE}/events`, { waitUntil: "domcontentloaded" });
await noLoading();
await settle(page, 800);
await shot("events");

fs.writeFileSync(path.join(OUT, "rects.json"), JSON.stringify({ viewport: { w: VW, h: VH, dsf: DSF }, rects, meta }, null, 2));
fs.copyFileSync(path.join(OUT, "rects.json"), path.resolve(here, "../remotion/rects.json"));
console.log("done");
await browser.close();
