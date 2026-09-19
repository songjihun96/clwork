"""ffmpeg를 이용한 실제 쇼츠 렌더링: 구간 자르기 + 9:16 변환 + 자막 굽기."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Any, Optional

from . import subtitles as subs_mod
from .models import ShortCandidate, Transcript
from .utils import find_ffmpeg, safe_filename

logger = logging.getLogger(__name__)


class FfmpegNotFound(RuntimeError):
    pass


class RenderError(RuntimeError):
    pass


def _run(cmd: list[str]) -> None:
    logger.info("ffmpeg 실행: %s", " ".join(cmd))
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="ignore")
    if proc.returncode != 0:
        raise RenderError(f"ffmpeg 실패 (code={proc.returncode}):\n{proc.stderr[-4000:]}")


def probe_duration(ffmpeg_path: str, path: str) -> Optional[float]:
    # ffmpeg.exe와 같은 폴더에 있는 ffprobe를 찾는다. 폴더 경로 어딘가에 "ffmpeg"라는
    # 문자열이 또 들어있을 수 있으므로(예: .../ffmpeg/ffmpeg.exe) 파일명 부분만 바꾼다.
    dir_name, base_name = os.path.split(ffmpeg_path)
    stem, ext = os.path.splitext(base_name)
    probe_base = "ffprobe" + ext if stem == "ffmpeg" else base_name.replace("ffmpeg", "ffprobe", 1)
    ffprobe = os.path.join(dir_name, probe_base) if dir_name else probe_base

    if not os.path.exists(ffprobe):
        # PATH 상의 ffprobe로 대체 시도
        import shutil

        found = shutil.which("ffprobe")
        if not found:
            return None
        ffprobe = found
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        data = json.loads(proc.stdout or "{}")
        return float(data["format"]["duration"])
    except Exception:  # noqa: BLE001
        return None


def _build_video_filter(vertical_style: str, width: int, height: int, subtitle_ass_path: Optional[str]) -> tuple[str, str]:
    """filter_complex 문자열과 최종 비디오 출력 라벨을 만든다."""
    if vertical_style == "blur_pad":
        chain = (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},gblur=sigma=20[bg];"
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[vraw]"
        )
    elif vertical_style == "crop":
        chain = f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}[vraw]"
    else:  # none — 원본 비율 유지, 너무 크면 축소만
        chain = f"[0:v]scale='min({width*2},iw)':-2[vraw]"

    if subtitle_ass_path:
        escaped = subs_mod.ffmpeg_escape_path(subtitle_ass_path)
        chain += f";[vraw]subtitles='{escaped}'[vout]"
        out_label = "[vout]"
    else:
        out_label = "[vraw]"

    return chain, out_label


def render_short(
    input_video_path: str,
    transcript: Transcript,
    candidate: ShortCandidate,
    index: int,
    output_dir: str,
    cfg: dict[str, Any],
    subtitles_enabled: bool,
    vertical_enabled: bool,
) -> dict[str, Any]:
    ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path:
        raise FfmpegNotFound(
            "ffmpeg를 찾을 수 없습니다. https://ffmpeg.org 에서 다운로드해 PATH에 추가하거나, "
            "프로그램 폴더 옆에 ffmpeg/ffmpeg.exe 로 넣어주세요."
        )

    os.makedirs(output_dir, exist_ok=True)
    base_name = f"shorts_{index:02d}_{safe_filename(candidate.title)}"
    out_path = os.path.join(output_dir, f"{base_name}.mp4")

    subtitle_ass_path = None
    if subtitles_enabled:
        subtitle_ass_path = os.path.join(output_dir, f"{base_name}.ass")
        subs_mod.write_ass(transcript, candidate.start_time, candidate.end_time, subtitle_ass_path)

    width, height = (1080, 1920)
    vertical_style = cfg.get("vertical_style", "blur_pad") if vertical_enabled else "none"
    filter_complex, out_label = _build_video_filter(vertical_style, width, height, subtitle_ass_path)

    duration = max(0.1, candidate.end_time - candidate.start_time)

    cmd = [
        ffmpeg_path,
        "-y",
        "-ss", f"{candidate.start_time:.3f}",
        "-i", input_video_path,
        "-t", f"{duration:.3f}",
        "-filter_complex", filter_complex,
        "-map", out_label,
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        out_path,
    ]
    _run(cmd)

    actual_duration = probe_duration(ffmpeg_path, out_path) or duration

    return {
        "output_path": out_path,
        "subtitle_path": subtitle_ass_path,
        "actual_duration": actual_duration,
    }
