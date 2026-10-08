"""나레이션 음성(TTS) 생성 + 장면 타이밍(timeline.json) + 자막(SRT) 만들기.

    python script/build_audio.py            # 전 버전
    python script/build_audio.py 90s 60s    # 일부만
    python script/build_audio.py --no-tts   # TTS 를 다시 받지 않고 public/audio 의 기존 WAV(예: 성우 녹음) 길이로만 타이밍 재계산

- 음성: Microsoft Edge 신경망 TTS(edge-tts, ko-KR-SunHiNeural).
  정식 방송·광고 송출 전에는 성우 녹음으로 바꾸는 것을 권한다(원고·자막은 그대로 쓰면 된다).
- 장면 길이 = 앞 여백 + (문장 길이 + 문장 사이 쉼) 합 + 뒤 여백. 화면을 보여 줄 최소 시간보다
  짧으면 최소 시간으로 늘리고, 전체가 목표 길이에 못 미치면 화면 위주 장면을 고르게 늘린다.
"""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import edge_tts

SRC = Path(__file__).resolve().parents[1]
VIDEO = SRC.parent
FPS = 60
NARR = json.loads((SRC / "script/narration.json").read_text(encoding="utf-8"))  # 학생 홍보영상 원고
AUDIO_PUBLIC = SRC / "public/audio"
AUDIO_ASSETS = VIDEO / "assets/audio/narration"

# 장면별 최소 노출 시간(초) — 실제 화면을 읽을 시간을 보장한다.
MIN_SEC = {
    "90s": {"intro": 7.5, "home": 6, "search": 10, "map": 6, "school": 9.5, "compare": 6,
            "admission": 7.5, "quiz": 11, "recap": 5.5, "users": 8.5, "outro": 7.5},
    "60s": {"intro": 6.5, "search": 6, "map": 4.5, "school": 7.5, "compare": 5, "admission": 5,
            "quiz": 8.5, "users": 5.5, "outro": 6.5},
    "30s": {"intro": 5.5, "search": 5, "school": 5, "quiz": 7, "outro": 5.5},
    "15s": {"intro": 3.2, "montage": 6.6, "outro": 4.4},
}
# 목표보다 짧을 때 늘려 줄 장면(화면 중심 장면)
STRETCH = {"search", "map", "school", "compare", "admission", "quiz", "home", "montage", "recap"}
LEAD, GAP, TAIL = 0.35, 0.3, 0.5


def probe(p: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(p)], capture_output=True, text=True)
    return float(out.stdout.strip())


async def tts(text: str, out: Path, voice: str, rate: str):
    """TTS 를 받은 뒤 앞뒤 무음을 잘라 48kHz WAV 로 저장한다."""
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = out.with_suffix(".raw.mp3")
    await edge_tts.Communicate(text, voice, rate=rate).save(str(raw))
    trim = ("silenceremove=start_periods=1:start_threshold=-48dB:start_silence=0.04,areverse,"
            "silenceremove=start_periods=1:start_threshold=-48dB:start_silence=0.08,areverse")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(raw), "-af", trim,
                    "-ar", "48000", "-ac", "1", str(out)], check=True)
    raw.unlink()


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


NO_TTS = "--no-tts" in sys.argv


async def build(ver: str):
    spec = NARR["versions"][ver]
    voice, rate = NARR["voice"], NARR.get("rate", "+0%")
    scenes = []
    for sc in spec["scenes"]:
        lines = []
        for i, ln in enumerate(sc["lines"]):
            rel = f"audio/{ver}/{sc['id']}_{i}.wav"
            out = SRC / "public" / rel
            if not (NO_TTS and out.exists()):
                await tts(ln.get("tts", ln["text"]), out, voice, rate)
            dur = probe(out)
            lines.append({"text": ln["text"], "src": rel, "dur": round(dur, 3)})
        speech = LEAD + sum(l["dur"] for l in lines) + GAP * (len(lines) - 1) + TAIL
        scenes.append({"id": sc["id"], "lines": lines, "sec": max(speech, MIN_SEC[ver][sc["id"]])})

    total = sum(s["sec"] for s in scenes)
    target = spec["target"]
    if total < target:
        flex = [s for s in scenes if s["id"] in STRETCH]
        extra = (target - total) / len(flex)
        for s in flex:
            s["sec"] += extra
    total = sum(s["sec"] for s in scenes)

    # 프레임 단위로 고정 + 문장 시작 프레임 계산
    start = 0
    srt, n = [], 1
    for s in scenes:
        s["from"] = start
        s["frames"] = int(round(s["sec"] * FPS))
        t = LEAD
        for l in s["lines"]:
            l["at"] = int(round(t * FPS))          # 장면 안에서의 시작 프레임
            l["frames"] = int(round(l["dur"] * FPS))
            a = (start + l["at"]) / FPS
            srt.append(f"{n}\n{srt_time(a)} --> {srt_time(a + l['dur'] + 0.15)}\n{l['text']}\n")
            n += 1
            t += l["dur"] + GAP
        start += s["frames"]

    tl = {"version": ver, "fps": FPS, "frames": start, "seconds": round(start / FPS, 2), "scenes": scenes}
    print(f"{ver}: {tl['seconds']}s  (target {target}s)  " +
          ", ".join(f"{s['id']} {s['frames']/FPS:.1f}" for s in scenes))
    return tl, "\n".join(srt)


async def main():
    vers = [a for a in sys.argv[1:] if not a.startswith("--")] or list(NARR["versions"].keys())
    tl_path = SRC / "remotion/timeline.json"
    all_tl = json.loads(tl_path.read_text(encoding="utf-8")) if tl_path.exists() else {}
    for v in vers:
        tl, srt = await build(v)
        all_tl[v] = tl
        (VIDEO / "assets/audio").mkdir(parents=True, exist_ok=True)
        (SRC / "subtitles").mkdir(exist_ok=True)
        (SRC / f"subtitles/udj_intro_{v}.srt").write_text(srt, encoding="utf-8")
        # 원본 나레이션 파일을 assets 에도 남긴다
        dst = AUDIO_ASSETS / v
        dst.mkdir(parents=True, exist_ok=True)
        for f in (AUDIO_PUBLIC / v).glob("*.wav"):
            (dst / f.name).write_bytes(f.read_bytes())
    tl_path.write_text(json.dumps(all_tl, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
