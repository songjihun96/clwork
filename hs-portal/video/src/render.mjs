// 렌더링 스크립트
//   node render.mjs                 → 90s 60s 30s 15s 모두 렌더
//   node render.mjs 90s 30s         → 일부만
//   node render.mjs --stills 90s    → 검수용 정지 화면(장면마다 몇 장)만 뽑기
//
// 결과: ../main/udj_intro_90s.mp4, ../main/udj_intro_60s.mp4,
//       ../shorts/udj_intro_30s.mp4, ../shorts/udj_intro_15s.mp4
// 렌더 후 ffmpeg 로
//  - 영상: 표준 yuv420p(BT.709, 제한 범위)로 최종 인코딩 (Remotion 중간본은 JPEG 프레임이라 yuvj420p 로 나온다)
//  - 음량: -16 LUFS(온라인 영상 권장값)
//  - faststart(웹에서 바로 재생)
import { bundle } from "@remotion/bundler";
import { renderMedia, renderStill, selectComposition } from "@remotion/renderer";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const stills = args.includes("--stills");
const versions = args.filter((a) => !a.startsWith("--"));
const timeline = JSON.parse(fs.readFileSync(path.join(here, "remotion/timeline.json"), "utf8"));
const todo = versions.length ? versions : Object.keys(timeline);

const OUT = {
  "90s": path.resolve(here, "../main/udj_intro_90s.mp4"),
  "60s": path.resolve(here, "../main/udj_intro_60s.mp4"),
  "30s": path.resolve(here, "../shorts/udj_intro_30s.mp4"),
  "15s": path.resolve(here, "../shorts/udj_intro_15s.mp4"),
};

console.log("bundling…");
const serveUrl = await bundle({ entryPoint: path.join(here, "remotion/index.ts"), publicDir: path.join(here, "public") });

for (const v of todo) {
  const comp = await selectComposition({ serveUrl, id: `udj-${v}`, inputProps: { version: v } });
  if (stills) {
    const dir = path.resolve(here, `review/${v}`);
    fs.mkdirSync(dir, { recursive: true });
    for (const s of timeline[v].scenes) {
      const picks = [0.12, 0.35, 0.6, 0.85].map((p) => s.from + Math.round(s.frames * p));
      for (const f of picks) {
        const out = path.join(dir, `${String(f).padStart(5, "0")}_${s.id}.png`);
        await renderStill({ composition: comp, serveUrl, output: out, frame: f, inputProps: { version: v } });
      }
    }
    console.log("stills", v, "→", dir);
    continue;
  }
  const raw = path.join(os.tmpdir(), `udj_${v}_raw.mp4`);
  let last = -1;
  const t0 = Date.now();
  await renderMedia({
    composition: comp, serveUrl, codec: "h264", outputLocation: raw, inputProps: { version: v },
    crf: 10, pixelFormat: "yuv420p", imageFormat: "jpeg", jpegQuality: 95, audioBitrate: "192k", x264Preset: "medium",
    concurrency: Math.max(2, Math.floor(os.cpus().length * 0.75)),
    onProgress: ({ progress }) => {
      const p = Math.floor(progress * 20);
      if (p !== last) { last = p; process.stdout.write(`\r${v} ${Math.round(progress * 100)}%  `); }
    },
  });
  console.log(`\n${v} rendered in ${Math.round((Date.now() - t0) / 1000)}s`);
  fs.mkdirSync(path.dirname(OUT[v]), { recursive: true });
  execFileSync("ffmpeg", ["-loglevel", "error", "-y", "-i", raw,
    "-vf", "scale=in_range=full:out_range=tv:in_color_matrix=bt709:out_color_matrix=bt709,format=yuv420p",
    "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-profile:v", "high", "-level", "4.2",
    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
    "-r", "60", "-g", "120",
    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", "-c:a", "aac", "-b:a", "192k",
    "-movflags", "+faststart", OUT[v]]);
  fs.unlinkSync(raw);
  console.log("→", OUT[v]);
}
