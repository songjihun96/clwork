import { chromium } from "playwright-core";
const b = await chromium.launch({ channel: "msedge" });
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
await p.goto("https://udjschool.ggm.kr/quiz", { waitUntil: "networkidle" });
console.log((await p.innerText("main")).slice(0, 1500));
await p.goto("https://udjschool.ggm.kr/schools/25", { waitUntil: "networkidle" });
await p.waitForTimeout(1500);
console.log("-----\n" + (await p.innerText("main")).slice(0, 1500));
await b.close();
