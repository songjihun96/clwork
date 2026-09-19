"""전화에 쓰는 소리를 보관한다.

**누가 듣는 소리인가**로 나뉘고, 그에 따라 다루는 법이 다르다.

  ring  수신 벨소리 — 전화가 오면 **상담원**이 듣는다
  dial  발신음     — 전화를 걸어 상대가 받기 전까지 **상담원**이 듣는다
        이 둘은 전화망과 무관해 올린 파일을 **그대로** 두고 브라우저가 재생한다.
        브라우저가 알아서 해독하므로 mp3·m4a·wav 무엇이든 된다.

  hold  대기음     — 상담원 연결을 기다리는 동안 **고객**이 듣는다
        이건 전화망으로 나가야 해서 **8kHz μ-law 원본**으로 둔다.
        변환은 브라우저가 한다(파이썬 3.13 에서 audioop 이 사라져,
        서버 파이썬 버전에 기대지 않기 위해서다).

셋 다 올리지 않으면 기본 소리가 난다. 수신·발신은 브라우저가 만들어 내고,
대기음은 음성 중계가 만들어 낸다.

파일로 둔다. 백엔드(8000)와 음성 중계(8010)가 서로 다른 프로세스라 메모리에
두면 한쪽만 갱신되고, DB 에 넣기에는 덩치가 크다. 같은 서버의 같은 파일을
양쪽이 읽는 것이 가장 단순하다.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

# backend/media/phone/
MEDIA_DIR = Path(__file__).resolve().parent.parent.parent / "media" / "phone"

SAMPLE_RATE = 8000
FRAME_BYTES = 160

# 대기음은 통화 내내 되풀이된다. 길면 파일만 커지고 얻는 게 없다.
MAX_HOLD_SECONDS = 90
MAX_HOLD_BYTES = SAMPLE_RATE * MAX_HOLD_SECONDS

# 상담원 브라우저가 내려받는다. 너무 크면 전화가 울리기 전에 못 받는다.
MAX_BROWSER_BYTES = 2 * 1024 * 1024

KINDS = ("ring", "dial", "hold")

# 브라우저가 그대로 재생하는 것들. hold 만 성격이 다르다.
BROWSER_KINDS = ("ring", "dial")


def _dir() -> Path:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    return MEDIA_DIR


def hold_path() -> Path:
    return _dir() / "hold.ulaw"


def browser_path(kind: str) -> Optional[Path]:
    """확장자를 알아야 브라우저에 무슨 형식인지 알려줄 수 있어 찾아 쓴다."""
    for p in sorted(_dir().glob(f"{kind}.*")):
        return p
    return None


def save_hold(data: bytes) -> int:
    """이미 8kHz μ-law 로 바뀐 소리를 받는다."""
    if len(data) > MAX_HOLD_BYTES:
        data = data[:MAX_HOLD_BYTES]
    # 프레임(160바이트) 단위로 잘라 둔다. 남는 꼬리는 재생할 때 어차피
    # 못 쓰고, 두면 끝에서 딱딱 소리가 난다.
    usable = (len(data) // FRAME_BYTES) * FRAME_BYTES
    hold_path().write_bytes(data[:usable])
    return usable


def save_browser_sound(kind: str, data: bytes, filename: str) -> Path:
    """수신 벨·발신음은 올린 그대로 둔다. 브라우저가 알아서 재생한다."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in (".mp3", ".wav", ".ogg", ".m4a", ".aac", ".webm"):
        ext = ".mp3"
    for old in _dir().glob(f"{kind}.*"):
        old.unlink(missing_ok=True)
    path = _dir() / f"{kind}{ext}"
    path.write_bytes(data)
    return path


def clear(kind: str) -> None:
    if kind == "hold":
        hold_path().unlink(missing_ok=True)
        return
    for old in _dir().glob(f"{kind}.*"):
        old.unlink(missing_ok=True)


def info(kind: str) -> dict:
    if kind == "hold":
        p = hold_path()
        if not p.exists():
            return {"exists": False, "seconds": 0}
        size = p.stat().st_size
        return {
            "exists": True,
            "seconds": round(size / SAMPLE_RATE, 1),
            "updated_at": int(p.stat().st_mtime),
        }
    p = browser_path(kind)
    if p is None:
        return {"exists": False}
    return {
        "exists": True,
        "filename": p.name,
        "bytes": p.stat().st_size,
        "updated_at": int(p.stat().st_mtime),
    }


# ── 대기음 읽기 (음성 중계가 쓴다) ──────────────────────────────

_cache: Optional[Tuple[float, list]] = None


def hold_frames() -> Optional[list]:
    """대기음을 20ms 조각들로. 올린 것이 없으면 None.

    관리자가 파일을 바꾸면 서버를 다시 띄우지 않아도 반영돼야 한다.
    파일이 바뀐 시각을 봐서 바뀌었을 때만 다시 읽는다.
    """
    global _cache
    p = hold_path()
    if not p.exists():
        _cache = None
        return None
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return None
    if _cache is not None and _cache[0] == mtime:
        return _cache[1]

    try:
        raw = p.read_bytes()
    except OSError:
        return None
    frames = [raw[i:i + FRAME_BYTES] for i in range(0, len(raw), FRAME_BYTES)]
    frames = [f for f in frames if len(f) == FRAME_BYTES]
    if not frames:
        _cache = None
        return None
    _cache = (mtime, frames)
    return frames
