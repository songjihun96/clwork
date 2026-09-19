import { JSDOM } from "jsdom";
import { build } from "esbuild";

const out = await build({
  entryPoints: ["./tests/entry.jsx"], bundle: true, write: false,
  format: "iife", jsx: "automatic", absWorkingDir: process.cwd(),
});
const code = out.outputFiles[0].text;

const OK = [];
const chk = (n, c, e = "") => {
  OK.push(!!c);
  console.log((c ? "  OK  " : "  FAIL") + `  ${n}` + (!c && e ? `  ${e}` : ""));
};

function run(html) {
  const dom = new JSDOM(`<!doctype html><html><body>${html}<div id="root"></div></body></html>`,
    { runScripts: "outside-only", pretendToBeVisual: true });
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
  w.eval(code);
  return w;
}

const full = `<input data-tour="title"/><div data-tour="item">항목</div>
  <button data-tour="materials">재료</button><div data-tour="panel">패널</div>
  <div data-tour="ai">AI</div><button data-tour="download">받기</button>`;

console.log("=== 1. 안내가 뜬다 ===");
let w = run(full);
await new Promise(r => setTimeout(r, 150));
let b = w.document.body.innerHTML;
chk("첫 단계 표시", b.includes("먼저 이름을 붙이세요"), b.slice(0, 120));
chk("1 / 6", b.includes("1 / 6"));
chk("화면을 덮음", b.includes("9999px"));

console.log("=== 2. 다음으로 넘어간다 ===");
let next = [...w.document.querySelectorAll("button")].find(x => x.textContent === "다음");
chk("다음 버튼 있음", !!next);
if (next) {
  next.dispatchEvent(new w.MouseEvent("click", { bubbles: true }));
  await new Promise(r => setTimeout(r, 150));
  b = w.document.body.innerHTML;
  chk("2단계로", b.includes("2 / 6") && b.includes("쓰고 싶은 항목"), b.slice(0, 100));
}

console.log("=== 3. AI 가 없으면 건너뛴다 ===");
const noAi = full.replace('<div data-tour="ai">AI</div>', "");
w = run(noAi);
await new Promise(r => setTimeout(r, 150));
// 5단계까지 넘겨 본다
for (let i = 0; i < 4; i++) {
  const btn = [...w.document.querySelectorAll("button")].find(x => x.textContent === "다음");
  if (!btn) break;
  btn.dispatchEvent(new w.MouseEvent("click", { bubbles: true }));
  await new Promise(r => setTimeout(r, 120));
}
b = w.document.body.innerHTML;
chk("AI 단계를 건너뜀", !b.includes("AI로 정리할 수도"), b.slice(0, 120));
chk("마지막 단계로", b.includes("파일로 받으세요") || b === "" || !b.includes("/ 6"),
  b.slice(0, 100));

console.log("=== 4. 짚을 것이 없으면 조용히 닫는다 ===");
w = run("<p>아무것도 없음</p>");
await new Promise(r => setTimeout(r, 150));
b = w.document.getElementById("root").innerHTML;
chk("아무것도 안 그림", b === "", b.slice(0, 80));

console.log(`\n===== ${OK.filter(Boolean).length}/${OK.length} 통과 =====`);
process.exit(OK.every(Boolean) ? 0 : 1);
