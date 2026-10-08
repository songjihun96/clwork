"""학교·교사용 영상: 세그먼트별 나레이션 음성 → 버전별 타임라인(school_timeline.json) + SRT.

    python script/build_school_audio.py            # TTS 생성 + 타이밍
    python script/build_school_audio.py --no-tts   # 기존 WAV(예: 성우 녹음) 길이로 타이밍만 다시

세그먼트 음성은 한 번만 만들고, 통합본과 챕터 영상이 같은 파일을 나눠 쓴다.
"""
import asyncio
import json
import sys
from pathlib import Path

from build_audio import FPS, probe, srt_time, tts  # 같은 TTS·무음 제거 방식

SRC = Path(__file__).resolve().parents[1]
VIDEO = SRC.parent
NARR = json.loads((SRC / "script/school_narration.json").read_text(encoding="utf-8"))
NO_TTS = "--no-tts" in sys.argv

# 제품 시연이라 학생 홍보영상보다 여유 있게 둔다
LEAD, GAP, TAIL = 0.5, 0.45, 0.7
MIN_SEC = {"outro": 7.0, "card_admin": 4.5, "card_teacher": 4.5, "card_student": 4.5}


async def build_segments():
    voice, rate = NARR["voice"], NARR["rate"]
    segs = {}
    for sid, seg in NARR["segments"].items():
        lines = []
        for i, ln in enumerate(seg["lines"]):
            rel = f"audio/school/{sid}_{i}.wav"
            out = SRC / "public" / rel
            if not (NO_TTS and out.exists()):
                await tts(ln.get("tts", ln["text"]), out, voice, rate)
            lines.append({"text": ln["text"], "src": rel, "dur": round(probe(out), 3)})
        # hold: 화면 시연(입력·클릭)을 보여 줄 여유 시간. 문장 뒤마다 고르게 나눠 넣는다.
        gap = GAP + seg.get("hold", 0) / len(lines)
        sec = LEAD + sum(l["dur"] for l in lines) + gap * (len(lines) - 1) + TAIL + seg.get("hold", 0) / len(lines)
        segs[sid] = {"id": sid, "chapter": seg["chapter"], "card": seg.get("card"), "gap": gap,
                     "lines": lines, "sec": max(sec, MIN_SEC.get(sid, 0))}
    return segs


def timeline(name, spec, segs):
    start, scenes, srt, n = 0, [], [], 1
    for sid in spec["segments"]:
        s = json.loads(json.dumps(segs[sid]))
        s["from"] = start
        s["frames"] = int(round(s["sec"] * FPS))
        t = LEAD
        for l in s["lines"]:
            l["at"] = int(round(t * FPS))
            l["frames"] = int(round(l["dur"] * FPS))
            a = (start + l["at"]) / FPS
            srt.append(f"{n}\n{srt_time(a)} --> {srt_time(a + l['dur'] + 0.15)}\n{l['text']}\n")
            n += 1
            t += l["dur"] + s["gap"]
        scenes.append(s)
        start += s["frames"]
    return {"version": name, "fps": FPS, "frames": start, "seconds": round(start / FPS, 2),
            "chapterBar": bool(spec.get("chapterBar")), "out": spec["out"],
            "chapters": NARR["chapters"], "scenes": scenes}, "\n".join(srt)


async def main():
    segs = await build_segments()
    all_tl = {}
    for name, spec in NARR["versions"].items():
        tl, srt = timeline(name, spec, segs)
        all_tl[name] = tl
        (SRC / "subtitles").mkdir(exist_ok=True)
        (SRC / f"subtitles/udj_{name}.srt").write_text(srt, encoding="utf-8")
        m, s = divmod(tl["seconds"], 60)
        print(f"{name:22} {int(m)}:{s:05.2f}  " + " ".join(f"{x['id']}={x['frames']/FPS:.0f}" for x in tl["scenes"]))
    (SRC / "remotion/school_timeline.json").write_text(json.dumps(all_tl, ensure_ascii=False, indent=2), encoding="utf-8")
    dst = VIDEO / "assets/audio/narration/school"
    dst.mkdir(parents=True, exist_ok=True)
    for f in (SRC / "public/audio/school").glob("*.wav"):
        (dst / f.name).write_bytes(f.read_bytes())


if __name__ == "__main__":
    asyncio.run(main())
