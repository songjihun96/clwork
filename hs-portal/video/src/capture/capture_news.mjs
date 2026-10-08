// 특성화고신문 기사가 붙은 학교 페이지(운영 사이트, 비로그인) 캡처 — 학교·교사용 영상의 '보도자료' 장면용.
//   node capture/capture_news.mjs 343 255
// 조회수·방문자 집계 POST 는 막는다. 결과: assets/screenshots/news_<id>_full.png (+ public/shots 사본), news_meta.json
import { chromium } from "playwright-core";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(here, "../../assets/screenshots");
const PUB = path.resolve(here, "../public/shots");
const ids = process.argv.slice(2);
const b = await chromium.launch({ channel: "msedge" });
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, locale: "ko-KR" });
await ctx.route(/\/api\/visit$/, (r) => r.request().method() === "POST" ? r.fulfill({ status: 503, body: "{}" }) : r.continue());
await ctx.route(/\/api\/schools\/\d+\/view$/, (r) => r.request().method() === "POST" ? r.fulfill({ status: 200, body: '{"ok":true}' }) : r.continue());
const p = await ctx.newPage();
const meta = fs.existsSync(path.join(here, "../remotion/news_meta.json")) ? JSON.parse(fs.readFileSync(path.join(here, "../remotion/news_meta.json"), "utf8")) : {};
for (const id of ids) {
  await p.goto(`https://udjschool.ggm.kr/schools/${id}`, { waitUntil: "networkidle" });
  await p.addStyleTag({ content: ".fab{display:none!important} *{transition:none!important}" });
  await p.evaluate(async () => { await document.fonts.ready; });
  await p.waitForTimeout(1500);
  const h = await p.evaluate(() => document.documentElement.scrollHeight);
  await p.setViewportSize({ width: 1440, height: h });
  await p.waitForTimeout(1500);
  const file = path.join(OUT, `news_${id}_full.png`);
  await p.screenshot({ path: file });
  fs.copyFileSync(file, path.join(PUB, `news_${id}_full.png`));
  const news = await p.locator(".panel", { has: p.locator("h3", { hasText: "특성화고신문 기사" }) }).first()
    .evaluate((el) => { const r = el.getBoundingClientRect(); return { x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height }; });
  meta[id] = { h, news, name: await p.locator("h1").first().innerText().catch(() => "") };
  await p.setViewportSize({ width: 1440, height: 900 });
  console.log(id, meta[id]);
}
fs.writeFileSync(path.join(here, "../remotion/news_meta.json"), JSON.stringify(meta, null, 2));
await b.close();
