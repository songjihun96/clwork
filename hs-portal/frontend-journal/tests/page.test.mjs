/** 자소서 편집 화면 전체가 실제로 그려지는지 본다.
 *
 *  Tour 만 따로 시험했더니, 정작 화면에 그리는 코드가 빠진 것을
 *  못 잡았다. 부품이 아니라 페이지째로 본다.
 */
import { JSDOM } from "jsdom";
import { build } from "esbuild";

const OK = [];
const chk = (n, c, e = "") => {
  OK.push(!!c);
  console.log((c ? "  OK  " : "  FAIL") + `  ${n}` + (!c && e ? `  ${e}` : ""));
};

const out = await build({
  entryPoints: ["./tests/page-entry.jsx"], bundle: true, write: false,
  format: "iife", jsx: "automatic", absWorkingDir: process.cwd(),
  define: { "process.env.NODE_ENV": '"production"' },
});

const dom = new JSDOM(`<!doctype html><html><body><div id="root"></div></body></html>`,
  { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
const w = dom.window;
w.scrollTo = () => {};
w.Element.prototype.scrollIntoView = () => {};
w.Element.prototype.getBoundingClientRect = function () {
  return { top: 100, left: 50, width: 200, height: 40,
           right: 250, bottom: 140, x: 50, y: 100 };
};
global.window = w; global.document = w.document;
try { global.localStorage = w.localStorage; } catch {}
Object.defineProperty(global, "navigator", { value: w.navigator, configurable: true });

// 서버를 부르지 않게 막는다. 화면이 그려지는지만 본다.
w.fetch = async () => ({
  ok: true, status: 200, headers: { get: () => "" },
  json: async () => ({
    resume_templates: [{ key: "strength", label: "자신의 강점을 강화시키고 약점을 관리했던 경험" },
                       { key: "teamwork", label: "팀 활동에서 본인의 역할을 책임감 있게 수행했던 경험" }],
    legacy_templates: [], pdf_available: true,
    // AI 는 켜져 있고 아직 동의 전인 상태로 본다.
    available: true, consented: false, topics: [],
  }),
});
global.fetch = w.fetch;

w.eval(out.outputFiles[0].text);
await new Promise(r => setTimeout(r, 400));

let html = w.document.body.innerHTML;
console.log("=== 1. 화면이 그려진다 ===");
chk("항목이 보임", html.includes("자신의 강점"), html.slice(0, 150));
chk("처음이신가요 버튼", html.includes("처음이신가요"));

console.log("=== 2. 버튼을 누르면 안내가 뜬다 ===");
const btn = [...w.document.querySelectorAll("button")]
  .find(x => x.textContent.includes("처음이신가요"));
chk("버튼 찾음", !!btn);
if (btn) {
  btn.dispatchEvent(new w.MouseEvent("click", { bubbles: true }));
  await new Promise(r => setTimeout(r, 400));
  html = w.document.body.innerHTML;
  chk("안내가 뜸", html.includes("먼저 이름을 붙이세요"), "버튼은 있는데 안내가 안 뜸");
  chk("단계 표시", html.includes("1 / 6"));
  chk("화면을 덮음", html.includes("9999px"));
}

console.log("=== 3. 재료와 AI 가 한 상자에 있다 ===");
// 예전에는 상자가 따로여서, 아무것도 안 골랐는데 빈 AI 상자가
// 자리를 차지했다. 이제는 재료 아래에 이어 붙는다.
const panel = w.document.querySelector("[data-tour='panel']");
chk("재료 상자 있음", !!panel);
if (panel) {
  const ai = panel.querySelector("[data-tour='ai']");
  chk("AI 가 그 안에 있음", !!ai, "AI 가 상자 밖에 있음");
  chk("동의 안내 보임",
    panel.innerHTML.includes("AI로 경험을 정리할 수도"),
    panel.innerHTML.slice(0, 150));
}

console.log("=== 4. 재료가 없어도 AI 가 보인다 ===");
// 지원동기·포부 같은 항목은 일지에 단서가 거의 없어 재료가 안 나온다.
// 그때 AI 안내까지 함께 묻히면 학생은 기능이 있는 줄도 모른다.
{
  const p2 = w.document.querySelector("[data-tour='panel']");
  const empty = p2 && (p2.innerHTML.includes("훑었지만")
    || p2.innerHTML.includes("아직 쓴 일지가 없습니다"));
  chk("재료가 비어 있는 상태", !!empty, "이 검사는 재료 없음 상태를 전제한다");
  chk("그래도 AI 가 보임", !!p2?.querySelector("[data-tour='ai']"),
    "재료가 없으면 AI 도 안 보임");
}

console.log(`\n===== ${OK.filter(Boolean).length}/${OK.length} 통과 =====`);
process.exit(OK.every(Boolean) ? 0 : 1);
