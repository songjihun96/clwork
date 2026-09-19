"""공용 유틸리티: ffmpeg 탐색, 시간 포맷, zip 묶기."""

from __future__ import annotations

import os
import shutil
import zipfile

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_ffmpeg() -> str | None:
    """ffmpeg 실행파일을 찾는다.

    우선순위: 1) 앱 폴더 옆 ffmpeg/ffmpeg.exe (배포용 동봉) 2) 시스템 PATH.
    다른 PC에 배포할 때는 ffmpeg 폴더를 앱과 함께 복사하면 별도 설치 없이 동작한다.
    """
    bundled = os.path.join(APP_DIR, "ffmpeg", "ffmpeg.exe")
    if os.path.exists(bundled):
        return bundled
    bundled_nowin = os.path.join(APP_DIR, "ffmpeg", "ffmpeg")
    if os.path.exists(bundled_nowin):
        return bundled_nowin
    found = shutil.which("ffmpeg")
    if found:
        return found
    return None


def fmt_hms(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def fmt_mmss(seconds: float) -> str:
    seconds = max(0.0, seconds)
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def safe_filename(name: str, max_len: int = 40) -> str:
    bad = '<>:"/\\|?*\n\r\t'
    cleaned = "".join(c for c in name if c not in bad).strip()
    cleaned = cleaned or "untitled"
    return cleaned[:max_len]


def zip_folder(folder_path: str, zip_path: str) -> str:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(folder_path):
            for file in files:
                full = os.path.join(root, file)
                rel = os.path.relpath(full, folder_path)
                zf.write(full, rel)
    return zip_path
