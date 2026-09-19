"""영상 파일을 다루는 자리 — 길이 재기, 오디오 뽑기, 오디오 대조.

**ffmpeg 이 없어도 죽지 않는다**

운영 서버에 ffmpeg 이 깔려 있지 않을 수 있다(2026-09 확인 시점엔 없었다).
그래서 이 파일의 모든 함수는 ffmpeg 이 없으면 예외 대신 `None` 이나
`(False, 이유)` 를 돌려준다. 부르는 쪽은 "오디오 검증은 건너뛰고 텍스트만으로
판정" 하면 된다 — 매칭 자체는 대본만 있으면 돌아가기 때문이다.

**왜 numpy 를 안 쓰나**

오디오 대조에 흔히 쓰는 상호상관은 numpy 가 편하지만, UDJ 백엔드에는 지금
수치 라이브러리가 하나도 없다. 이 기능 하나 때문에 numpy·scipy 를 얹으면
배포 크기와 설치 실패 위험만 늘어난다. 우리가 필요한 건 "이 구간이 그
숏츠와 같은 소리인가"를 가리는 정도라, 100ms 단위 에너지 곡선을 견주는
것으로 충분하다. 그건 표준 라이브러리만으로 된다.
"""

from __future__ import annotations

import array
import math
import os
import shutil
import subprocess
from typing import List, Optional, Tuple

# 오디오를 얼마나 거칠게 볼지. 8kHz 모노로 낮춰 받는다 — 말소리를 가릴
# 정도면 충분하고, 데이터가 작을수록 순수 파이썬으로도 빠르다.
SAMPLE_RATE = 8000
BIN_MS = 100                     # 에너지 곡선 한 칸의 길이
BIN_SAMPLES = SAMPLE_RATE * BIN_MS // 1000
FFMPEG_TIMEOUT = 300


def have_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg"))


def have_ffprobe() -> bool:
    return bool(shutil.which("ffprobe"))


def missing_reason() -> str:
    if not have_ffmpeg():
        return "서버에 ffmpeg 이 없어 오디오 검증을 건너뜁니다(apt install ffmpeg)."
    return ""


def probe_duration(path: str) -> Optional[float]:
    """영상 길이(초). 못 재면 None."""
    if not have_ffprobe() or not os.path.exists(path):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=60,
        )
        return round(float(out.stdout.strip()), 3) if out.returncode == 0 else None
    except (subprocess.SubprocessError, ValueError):
        return None


def extract_audio(src: str, dst: str, start: Optional[float] = None,
                  duration: Optional[float] = None) -> Tuple[bool, str]:
    """영상에서 오디오만 뽑아 파일로 만든다(STT 에 넣을 용도).

    영상을 통째로 STT 에 올리면 느리고 비싸다. 오디오만 mp3 로 줄여 보낸다.
    """
    if not have_ffmpeg():
        return False, missing_reason()
    if not os.path.exists(src):
        return False, "영상 파일이 없습니다."
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if start is not None:
        cmd += ["-ss", str(max(float(start), 0.0))]
    cmd += ["-i", src]
    if duration is not None:
        cmd += ["-t", str(max(float(duration), 0.0))]
    cmd += ["-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", dst]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT)
    except subprocess.SubprocessError as exc:
        return False, f"오디오 추출이 실패했습니다: {exc}"
    if r.returncode != 0 or not os.path.exists(dst):
        return False, f"오디오 추출이 실패했습니다: {(r.stderr or '')[:200]}"
    return True, ""


def energy_envelope(path: str, start: Optional[float] = None,
                    duration: Optional[float] = None) -> Optional[List[float]]:
    """구간의 소리 크기 곡선(100ms 마다 한 칸)을 뽑는다.

    ffmpeg 으로 8kHz 모노 raw PCM 을 받아 100ms 씩 묶어 제곱평균을 낸다.
    말이 있는 자리와 쉬는 자리의 무늬가 곧 그 구간의 지문 노릇을 한다.
    """
    if not have_ffmpeg() or not os.path.exists(path):
        return None
    cmd = ["ffmpeg", "-v", "error"]
    if start is not None:
        cmd += ["-ss", str(max(float(start), 0.0))]
    cmd += ["-i", path]
    if duration is not None:
        cmd += ["-t", str(max(float(duration), 0.0))]
    cmd += ["-vn", "-f", "s16le", "-acodec", "pcm_s16le",
            "-ac", "1", "-ar", str(SAMPLE_RATE), "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=FFMPEG_TIMEOUT)
    except subprocess.SubprocessError:
        return None
    if r.returncode != 0 or not r.stdout:
        return None

    pcm = array.array("h")
    usable = len(r.stdout) - (len(r.stdout) % 2)
    pcm.frombytes(r.stdout[:usable])

    out: List[float] = []
    for i in range(0, len(pcm) - BIN_SAMPLES + 1, BIN_SAMPLES):
        chunk = pcm[i:i + BIN_SAMPLES]
        total = 0
        for v in chunk:
            total += v * v
        out.append(math.sqrt(total / len(chunk)))
    return out or None


def _correlate(a: List[float], b: List[float]) -> float:
    """길이가 같은 두 곡선의 상관계수(-1~1)."""
    n = min(len(a), len(b))
    if n < 3:
        return 0.0
    a, b = a[:n], b[:n]
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    if da == 0 or db == 0:
        return 0.0
    return num / (da * db)


def envelope_similarity(short_env: List[float], long_env: List[float],
                        max_lag_bins: Optional[int] = None) -> float:
    """숏츠 곡선이 롱폼 구간 곡선과 얼마나 닮았나(0~1).

    구간 추정이 몇 초 어긋날 수 있으므로 밀어 가며 가장 잘 맞는 자리를
    고른다. 밀 수 있는 범위를 좁게 잡으면(예전엔 3초) 숏츠 앞에 인트로가
    붙은 경우 제자리를 못 찾아 0점이 나왔다. 기본값은 롱폼 창에서 숏츠가
    들어갈 수 있는 모든 자리다.
    """
    if not short_env or not long_env:
        return 0.0
    span = min(len(short_env), len(long_env))
    limit = len(long_env) - span
    if max_lag_bins is not None:
        limit = min(limit, max_lag_bins)
    best = -1.0
    for lag in range(0, max(limit, 0) + 1):
        best = max(best, _correlate(short_env, long_env[lag:lag + span]))
    # 상관계수 -1~1 을 0~1 로 옮긴다. 음의 상관은 '안 닮음'과 같이 본다.
    return round(max(best, 0.0), 4)


def make_audio_verifier(longform_path: str, shorts_path: str):
    """shorts_match.match(audio_verify=...) 에 넘길 함수를 만든다.

    ffmpeg 이 없으면 None 을 돌려준다 — 그러면 매칭은 텍스트만으로 판정하고,
    신뢰도 계산에서도 오디오 몫을 빼고 다시 나눈다.
    """
    if not have_ffmpeg():
        return None
    if not (os.path.exists(longform_path) and os.path.exists(shorts_path)):
        return None

    short_env = energy_envelope(shorts_path)
    if not short_env:
        return None

    # 숏츠 전체 길이(초). 곡선 한 칸이 BIN_MS 라서 칸 수로 되짚는다.
    short_sec = len(short_env) * BIN_MS / 1000.0

    def verify(start: float, end: float) -> float:
        # 롱폼에서 떠 오는 창은 **숏츠 길이**를 기준으로 잡는다.
        #
        # 예전에는 찾은 구간 길이(end-start)에 3초만 붙였다. 그런데 숏츠가
        # 그보다 길면(인트로·아웃트로가 붙은 경우가 흔하다) 숏츠 곡선의 앞부분만
        # 창과 견주게 되고, 그 앞부분이 바로 원본에 없는 인트로라 0점이 나왔다.
        # 숏츠가 통째로 들어갈 만큼 창을 넓게 뜨고, 그 안에서 제자리를 찾는다.
        pad = max(short_sec * 0.5, 5.0)
        s = max(float(start) - pad, 0.0)
        dur = max(float(end) - float(start), short_sec) + pad * 2
        long_env = energy_envelope(longform_path, start=s, duration=dur)
        if not long_env:
            return 0.0
        return envelope_similarity(short_env, long_env)

    return verify
