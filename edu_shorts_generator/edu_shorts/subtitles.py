"""쇼츠용 자막(.ass) 생성.

Whisper의 단어 단위 타임스탬프를 이용해 쇼츠 구간(start~end)에 해당하는
부분만 잘라내고, 시간을 쇼츠 로컬 기준(0초부터)으로 다시 맞춘 뒤,
세로형 쇼츠에서 읽기 좋게 2~3초/한 줄 정도의 짧은 자막 큐로 묶는다.
"""

from __future__ import annotations

import os

from .models import Transcript, Word

MAX_CUE_CHARS = 26
MAX_CUE_SECONDS = 4.0


def _fmt_ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs == 100:
        cs = 0
        s += 1
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _collect_words(transcript: Transcript, start_time: float, end_time: float) -> list[Word]:
    words: list[Word] = []
    for seg in transcript.segments:
        if seg.end < start_time or seg.start > end_time:
            continue
        if seg.words:
            for w in seg.words:
                if w.end < start_time or w.start > end_time or not w.text:
                    continue
                words.append(w)
        elif seg.text.strip():
            # 단어 타임스탬프가 없으면 세그먼트 전체를 하나의 "단어"로 취급
            words.append(Word(start=max(seg.start, start_time), end=min(seg.end, end_time), text=seg.text.strip()))
    return words


def build_cues(transcript: Transcript, start_time: float, end_time: float) -> list[tuple[float, float, str]]:
    words = _collect_words(transcript, start_time, end_time)
    cues: list[tuple[float, float, str]] = []
    buf: list[Word] = []

    def flush():
        if not buf:
            return
        text = " ".join(w.text for w in buf).strip()
        if not text:
            buf.clear()
            return
        s = buf[0].start - start_time
        e = buf[-1].end - start_time
        cues.append((max(0.0, s), max(0.0, e), text))
        buf.clear()

    for w in words:
        buf.append(w)
        text_len = sum(len(x.text) for x in buf) + len(buf) - 1
        duration = buf[-1].end - buf[0].start
        ends_sentence = w.text.strip().endswith((".", "!", "?", "다", "요", "죠", "다.", "요.", "죠."))
        if text_len >= MAX_CUE_CHARS or duration >= MAX_CUE_SECONDS or (ends_sentence and text_len >= 8):
            flush()
    flush()
    return cues


ASS_HEADER_TEMPLATE = """[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Malgun Gothic,{fontsize},&H00FFFFFF,&H000000FF,&H00101010,&H00000000,1,0,0,0,100,100,0,0,1,{outline},1,2,60,60,{marginv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def write_ass(
    transcript: Transcript,
    start_time: float,
    end_time: float,
    output_path: str,
    width: int = 1080,
    height: int = 1920,
) -> str:
    cues = build_cues(transcript, start_time, end_time)
    fontsize = max(48, width // 16)
    outline = max(2, fontsize // 20)
    marginv = height // 10

    lines = [ASS_HEADER_TEMPLATE.format(width=width, height=height, fontsize=fontsize, outline=outline, marginv=marginv)]
    for s, e, text in cues:
        text = text.replace("\n", " ").replace("{", "(").replace("}", ")")
        lines.append(f"Dialogue: 0,{_fmt_ass_time(s)},{_fmt_ass_time(e)},Default,,0,0,0,,{text}\n")

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8-sig") as f:
        f.writelines(lines)
    return output_path


def ffmpeg_escape_path(path: str) -> str:
    """ffmpeg의 subtitles= 필터에 넣기 위한 경로 이스케이프 (윈도우 드라이브 콜론 대응)."""
    p = os.path.abspath(path).replace("\\", "/")
    p = p.replace(":", "\\:")
    return p
