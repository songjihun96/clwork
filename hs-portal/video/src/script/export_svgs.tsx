// 영상에 쓴 아이콘·로고를 SVG 파일로 내보낸다: npx esbuild script/export_svgs.tsx --bundle --platform=node --outfile=script/.export.cjs && node script/.export.cjs
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import fs from "node:fs";
import path from "node:path";
import { Icon, ICON_NAMES } from "../remotion/components/Icons";

const root = path.resolve(__dirname, "../..");
const icons = path.join(root, "assets/icons");
const logos = path.join(root, "assets/logos");
fs.mkdirSync(icons, { recursive: true });
fs.mkdirSync(logos, { recursive: true });
for (const n of ICON_NAMES) {
  const svg = renderToStaticMarkup(<Icon name={n} size={48} color="#b52701" />).replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"');
  fs.writeFileSync(path.join(icons, `${n}.svg`), svg);
}
const FONT = "Pretendard, 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif";
fs.writeFileSync(path.join(logos, "udj_mark.svg"),
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 64" width="240" height="128"><rect width="120" height="64" rx="19" fill="#191c1d"/><text x="60" y="42" text-anchor="middle" font-family="${FONT}" font-size="28" font-weight="800" letter-spacing="2.5" fill="#fff">ㅇㅈ</text></svg>`);
fs.writeFileSync(path.join(logos, "udj_lockup.svg"),
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 100" width="760" height="100"><rect x="0" y="18" width="110" height="64" rx="19" fill="#191c1d"/><text x="55" y="60" text-anchor="middle" font-family="${FONT}" font-size="28" font-weight="800" letter-spacing="2.5" fill="#fff">ㅇㅈ</text><text x="136" y="68" font-family="${FONT}" font-size="50" font-weight="800" fill="#191c1d">우리동네 <tspan fill="#b52701">직업계고</tspan></text><rect x="616" y="24" width="132" height="52" rx="14" fill="#b52701"/><text x="682" y="61" text-anchor="middle" font-family="${FONT}" font-size="30" font-weight="800" letter-spacing="4" fill="#fff">UDJ</text></svg>`);
fs.copyFileSync(path.resolve(root, "../frontend/public/favicon.svg"), path.join(logos, "favicon.svg"));
console.log("icons", ICON_NAMES.length, "→", icons);
