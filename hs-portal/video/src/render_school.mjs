// 학교·교사용 기능 소개영상 렌더
//   node render_school.mjs                       → 5개 영상 모두
//   node render_school.mjs school_admin          → 일부만
//   node render_school.mjs --stills school_teacher_full   → 검수용 정지 화면만
//
// 결과 경로는 script/school_narration.json 의 versions.*.out (video/ 기준).
// 렌더 뒤 표준 yuv420p(BT.709) 재인코딩 + -16 LUFS + faststart (render.mjs 와 같은 방식).
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
const tls = JSON.parse(fs.readFileSync(path.join(here, "remotion/school_timeline.json"), "utf8"));
const todo = args.filter((a) => !a.startsWith("--"));
const versions = todo.length ? todo : Object.keys(tls);

console.log("bundling…");
const serveUrl = await bundle({ entryPoint: path.join(here, "remotion/index.ts"), publicDir: path.join(here, "public") });

for (const v of versions) {
  const id = `school-${v.replace(/_/g, "-")}`;
  const comp = await selectComposition({ serveUrl, id, inputProps: { version: v } });
  if (stills) {
    const dir = path.resolve(here, `review/${v}`);
    fs.mkdirSync(dir, { recursive: true });
    for (const s of tls[v].scenes) {
      for (const p of [0.08, 0.3, 0.55, 0.8, 0.95]) {
        const f = s.from + Math.round(s.frames * p);
        await renderStill({ composition: comp, serveUrl, frame: f, inputProps: { version: v },
          output: path.join(dir, `${String(f).padStart(6, "0")}_${s.id}.png`) });
      }
    }
    console.log("stills", v, "→", dir);
    continue;
  }
  const out = path.resolve(here, "..", tls[v].out);
  // 긴 영상은 2분 단위로 나눠 렌더한다. 끝에서 브라우저가 죽어도 다 된 구간은 남고,
  // 다시 실행하면 남은 구간만 렌더한다(.render_chunks/<버전>/chunk_N.done).
  const dir = path.resolve(here, `.render_chunks/${v}`);
  fs.mkdirSync(dir, { recursive: true });
  const total = comp.durationInFrames, CH = 60 * 120;
  const chunks = [];
  for (let a = 0; a < total; a += CH) chunks.push([a, Math.min(total, a + CH) - 1]);
  const t0 = Date.now();
  for (const [i, [a, b]] of chunks.entries()) {
    const file = path.join(dir, `chunk_${i}.mp4`), done = file + ".done";
    if (fs.existsSync(done)) { console.log(`${v} chunk ${i + 1}/${chunks.length} 이미 있음`); continue; }
    for (let attempt = 1; ; attempt++) {
      try {
        let last = -1;
        await renderMedia({
          composition: comp, serveUrl, codec: "h264", outputLocation: file, inputProps: { version: v },
          frameRange: [a, b], muted: true,
          crf: 10, pixelFormat: "yuv420p", imageFormat: "jpeg", jpegQuality: 95, x264Preset: "medium",
          concurrency: Math.max(2, Math.floor(os.cpus().length * 0.6)),
          onProgress: ({ progress }) => {
            const p = Math.floor(progress * 10);
            if (p !== last) { last = p; process.stdout.write(`${v} chunk ${i + 1}/${chunks.length} ${Math.round(progress * 100)}%  `); }
          },
        });
        fs.writeFileSync(done, "");
        console.log(`\n${v} chunk ${i + 1}/${chunks.length} ok`);
        break;
      } catch (e) {
        console.log(`\n${v} chunk ${i + 1} 실패(${attempt}회): ${e.message}`);
        if (attempt >= 3) throw e;
      }
    }
  }
  // 오디오는 화면을 찍지 않아 금방 끝난다
  const wav = path.join(dir, "audio.wav");
  await renderMedia({ composition: comp, serveUrl, codec: "wav", outputLocation: wav, inputProps: { version: v } });
  const list = path.join(dir, "list.txt");
  fs.writeFileSync(list, chunks.map((_, i) => `file 'chunk_${i}.mp4'`).join("\n"));
  console.log(`${v} rendered in ${Math.round((Date.now() - t0) / 1000)}s — 이어 붙이고 인코딩`);
  fs.mkdirSync(path.dirname(out), { recursive: true });
  execFileSync("ffmpeg", ["-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", list, "-i", wav,
    "-map", "0:v", "-map", "1:a",
    "-vf", "scale=in_range=full:out_range=tv:in_color_matrix=bt709:out_color_matrix=bt709,format=yuv420p",
    "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-profile:v", "high", "-level", "4.2",
    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
    "-r", "60", "-g", "120",
    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", "-c:a", "aac", "-b:a", "192k",
    "-movflags", "+faststart", out]);
  // 임시 구간 정리 — 실패해도(폴더가 열려 있는 등) 결과물에는 영향이 없다
  try { fs.rmSync(dir, { recursive: true, force: true }); } catch (e) { console.log("임시 폴더를 지우지 못했습니다:", dir, e.code); }
  console.log("→", out);
}
