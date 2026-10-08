"""회원만 보는 영상 — 온라인 직업계고설명회(특강 카드 포함)와 학교 홍보 인터뷰.

**왜 따로 두나.** 설명회 영상은 원래 `/api/media` 로 누구나 받아 갔다.
"회원가입해야 볼 수 있게"를 화면에서 버튼만 가리는 걸로 끝내면, 주소를
아는 사람은 그대로 받아 간다. 그래서 합격생 영상(paidvideo.py)과 같은
방식을 쓴다 — 파일은 /api/media 에서 거르고, **로그인한 사람에게만** 짧게
사는 티켓이 붙은 주소를 내준다.

합격생 영상과 다른 것은 "누가 보나" 하나다. 거기는 돈을 낸 사람, 여기는
가입한 사람 누구나. 그래서 티켓의 purpose 를 따로 둔다 — 회원 티켓으로 파는
영상을 받아 가는 일이 없어야 한다.

**파는 영상과 겹치면 파는 쪽이 이긴다.** 같은 파일이 설명회에도 붙고
합격생 영상에도 붙어 있으면, 여기 길로 가입만 한 사람이 산 사람 몫을
받아 간다. 저장할 때 막고(briefing.py·interviews.py), 흘려보낼 때 한 번 더
막는다.

**관리자 미리보기.** 영상 관리 화면은 <video src="/api/media/..."> 로 파일을
바로 튼다. 잠근 파일은 거기서 403 이 나서, 관리자에게 주는 주소에는
관리자 티켓을 붙인다(`admin_media_url`).
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from .auth import ALGORITHM, SECRET_KEY
from .database import get_db
from .models import Role, User, Video

router = APIRouter(prefix="/api", tags=["member-video"])

TICKET_MINUTES = 180
TICKET_PURPOSE = "member_video"
ADMIN_PURPOSE = "admin_media"
ADMIN_TICKET_HOURS = 12


# ---------------------------------------------------------------- 티켓
def _encode(payload: dict) -> str:
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _decode(token: str) -> Optional[dict]:
    if not token:
        return None
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def make_ticket(user_id: int, video_id: int) -> str:
    return _encode({
        "sub": str(user_id), "vid": int(video_id), "purpose": TICKET_PURPOSE,
        "exp": datetime.utcnow() + timedelta(minutes=TICKET_MINUTES),
    })


def read_ticket(token: str, video_id: int) -> Optional[int]:
    data = _decode(token)
    if not data or data.get("purpose") != TICKET_PURPOSE:
        return None
    try:
        if int(data.get("vid") or 0) != int(video_id):
            return None
        return int(data.get("sub"))
    except (TypeError, ValueError):
        return None


def stream_url(user: User, video_id: int) -> str:
    return "/api/member-video/stream/%d?t=%s" % (int(video_id), make_ticket(user.id, video_id))


def admin_media_url(file_url: str, user: User) -> str:
    """관리자 화면에 줄 파일 주소. 잠근 파일도 미리보기가 되게 티켓을 붙인다.

    파일마다가 아니라 관리자 한 사람에게 주는 티켓이다 — 관리자는 원래 모든
    영상을 볼 수 있고, 영상 관리 화면 한 번에 수십 개를 그린다.
    """
    if not file_url or not user or "?" in file_url:
        return file_url
    token = _encode({
        "sub": str(user.id), "purpose": ADMIN_PURPOSE,
        "exp": datetime.utcnow() + timedelta(hours=ADMIN_TICKET_HOURS),
    })
    return f"{file_url}?t={token}"


def admin_from_ticket(db: Session, token: str) -> Optional[User]:
    data = _decode(token)
    if not data or data.get("purpose") != ADMIN_PURPOSE:
        return None
    try:
        user = db.get(User, int(data.get("sub")))
    except (TypeError, ValueError):
        return None
    if not user or not user.is_active or user.role != Role.admin:
        return None
    return user


# ---------------------------------------------------------------- 어떤 영상이 회원 전용인가
_CACHE = {"ids": None, "names": None, "at": 0.0}
_CACHE_TTL = 30.0


def invalidate() -> None:
    _CACHE["ids"] = None
    _CACHE["names"] = None


def _paid_ids(db: Session) -> set:
    from . import paidvideo
    return paidvideo.video_ids_in(paidvideo.load_config(db))


def member_video_ids(db: Session) -> set:
    """설명회 + 학교 인터뷰가 쓰는 영상. 파는 영상은 뺀다(그쪽 규칙이 이긴다)."""
    now = time.time()
    if _CACHE["ids"] is not None and (now - _CACHE["at"]) < _CACHE_TTL:
        return _CACHE["ids"]
    from . import briefing, interviews
    cfg = briefing.load_config(db)
    ids = set()
    if cfg.get("video_id"):
        ids.add(int(cfg["video_id"]))
    for ch in cfg.get("chapters") or []:
        if ch.get("video_id"):
            ids.add(int(ch["video_id"]))
        for it in ch.get("items") or []:
            if it.get("video_id"):
                ids.add(int(it["video_id"]))
    ids |= interviews.video_ids(db)
    # 설명회 특강 카드로 올린 롱폼도 회원만 본다.
    ids |= {vid for (vid,) in db.query(Video.id).filter(Video.is_lecture.is_(True)).all()}
    ids -= _paid_ids(db)
    names = set()
    if ids:
        for (path,) in db.query(Video.file_path).filter(Video.id.in_(ids)).all():
            base = os.path.basename(path or "")
            if base:
                names.add(base)
    _CACHE.update(ids=ids, names=names, at=now)
    return ids


def protected_filenames(db: Session) -> set:
    member_video_ids(db)
    return _CACHE["names"] or set()


def is_member_video(db: Session, video_id: int) -> bool:
    return int(video_id) in member_video_ids(db)


# ---------------------------------------------------------------- 흘려보내기
@router.get("/member-video/stream/{video_id}")
def stream_member_video(video_id: int, t: str = Query("", description="시청 티켓"),
                        db: Session = Depends(get_db)):
    """영상 알맹이. 티켓이 맞고, 그 계정이 살아 있고, 회원 전용 영상일 때만."""
    user_id = read_ticket(t, video_id)
    if not user_id:
        raise HTTPException(status_code=403, detail="로그인 후 볼 수 있는 영상입니다.")
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=403, detail="로그인 후 볼 수 있는 영상입니다.")
    # 캐시가 아니라 지금 구성으로 다시 본다 — 방금 설명회에서 뺀 영상이나
    # 파는 영상으로 옮긴 영상이 티켓 수명 동안 계속 나가면 안 된다.
    invalidate()
    if video_id not in member_video_ids(db):
        raise HTTPException(status_code=404, detail="영상을 찾을 수 없습니다.")
    from . import videos as videos_mod
    v = db.get(Video, video_id)
    path = videos_mod._abs_path(v.file_path if v else "")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="영상 파일이 없습니다.")
    # FileResponse 가 Range 요청을 처리한다 — 앞으로 감기가 되려면 필요하다.
    return FileResponse(path, media_type="video/mp4")
