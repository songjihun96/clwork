"""돈을 낸 사람만 보는 영상 (합격생 영상).

**왜 따로 두나.** 특강·설명회 영상은 누구나 본다. 그래서 `/api/media` 라는
인증 없는 정적 폴더로 그냥 내보내도 됐다. 이건 파는 물건이라 그 길로
내보내면 안 된다 — 주소가 한 번 새면 그 뒤로는 아무나 원본을 받아 간다.
여기서는 파일을 **권한을 확인한 요청에만** 흘려보낸다.

**티켓을 쓰는 이유.** <video src="..."> 는 Authorization 헤더를 못 붙인다.
브라우저가 알아서 붙이는 건 쿠키뿐인데 이 서비스는 토큰을 localStorage 에
둔다. 그래서 목록을 받을 때(여기는 헤더가 붙는다) 짧게 사는 서명 티켓을
같이 내주고, 재생 요청은 그 티켓으로 본인을 밝힌다.

**막지 못하는 것.** 녹화와 캡처는 웹에서 못 막는다. 브라우저에 그런 수단이
없다. 화면이 검게 나오게 하려면 DRM 과 하드웨어 보호 등급이 맞아떨어져야
하는데 윈도우 크롬은 거기 해당하지 않고, 폰 카메라로 모니터를 찍는 건 어떤
방법으로도 못 막는다. 그래서 여기서는 **누가 흘렸는지 드러나게** 하는 쪽을
택했다 — 보는 사람의 이름과 연락처 끝자리를 화면에 겹쳐 두고, 유출본이 돌면
출처를 짚는다.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import applications as apps
from . import videos as videos_mod
from .auth import ALGORITHM, SECRET_KEY, get_current_user_optional, require_admin
from .database import get_db
from .models import Setting, User, Video

router = APIRouter(prefix="/api", tags=["paidvideo"])

KIND = "graduate_video"
REVIEW_KIND = "graduate_video_review"
CONFIG_KEY = "graduate_video_config"

MAX_CHAPTERS = 30
MAX_ITEMS = 12

# 티켓 수명. 길면 새어 나간 주소가 오래 살고, 짧으면 보다가 끊긴다.
# 세 시간이면 이 영상(세 챕터)을 여유 있게 다 본다.
TICKET_MINUTES = 180
TICKET_PURPOSE = "paidvideo"


def _empty() -> dict:
    return {"headline": "", "intro": "", "cover": "", "chapters": []}


def _clean_items(raw) -> list:
    """챕터 안의 강의 목록. 설명회(briefing.py)와 같은 모양으로 맞춘다 —
    관리 화면(ChapterEditor)을 그대로 나눠 쓰기 때문이다.

    start_sec 이 None 이면 "이 강의는 따로 시각이 없다"는 뜻이고, 화면은
    챕터 시작 시각으로 보낸다. 0 과 None 을 구분해야 하는 이유가 여기 있다 —
    0 은 "영상 맨 처음"이라는 뜻이라 뭉뚱그리면 안 된다.
    """
    out = []
    if not isinstance(raw, list):
        return out
    for item in raw[:MAX_ITEMS]:
        if isinstance(item, str):
            title, start, vid = item.strip(), None, None
        elif isinstance(item, dict):
            title = str(item.get("title") or "").strip()
            start = item.get("start_sec")
            try:
                start = None if start is None else max(round(float(start), 2), 0.0)
            except (TypeError, ValueError):
                start = None
            vid = item.get("video_id")
            try:
                vid = int(vid) if vid else None
            except (TypeError, ValueError):
                vid = None
        else:
            continue
        if title:
            out.append({"title": title[:200], "start_sec": start, "video_id": vid})
    return out


def _clean_chapters(raw) -> list:
    out = []
    if not isinstance(raw, list):
        return out
    for item in raw[:MAX_CHAPTERS]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        vid = item.get("video_id")
        try:
            vid = int(vid) if vid else None
        except (TypeError, ValueError):
            vid = None
        start = item.get("start_sec")
        try:
            start = max(round(float(start or 0), 2), 0.0)
        except (TypeError, ValueError):
            start = 0.0
        out.append({"title": title[:200], "video_id": vid, "start_sec": start,
                    "items": _clean_items(item.get("items"))})
    return out


def load_config(db: Session) -> dict:
    row = db.get(Setting, CONFIG_KEY)
    out = _empty()
    if not row or not (row.value or "").strip():
        return out
    try:
        saved = json.loads(row.value)
    except ValueError:
        return out
    if not isinstance(saved, dict):
        return out
    for key in out:
        if key in saved and saved[key] is not None:
            out[key] = saved[key]
    out["chapters"] = _clean_chapters(out.get("chapters"))
    return out


def save_config(db: Session, cfg: dict) -> None:
    row = db.get(Setting, CONFIG_KEY)
    value = json.dumps(cfg, ensure_ascii=False)
    if row is None:
        db.add(Setting(key=CONFIG_KEY, value=value))
    else:
        row.value = value
    db.commit()
    invalidate_protected()


# ------------------------------------------------- 정적 폴더에서 빼내기
#
# 영상 파일은 /api/media 라는 **인증 없는 정적 폴더**에 있다. 무료 특강은
# 그래도 되지만 파는 영상이 거기 남아 있으면, 잠근 길을 아무리 잘 만들어도
# 옆문이 열려 있는 셈이다. 파일 이름만 알면 원본을 그냥 받아 간다.
#
# 그래서 "이 파일들은 정적 폴더로 내보내지 말라"는 목록을 여기서 만들고,
# main.py 의 /api/media 가 그 목록을 보고 거른다.
#
# 매 요청마다 DB 를 두 번 읽게 두지 않으려고 잠깐 기억해 둔다. 구성이
# 바뀌거나 영상 파일이 바뀌면 곧바로 지우고(invalidate_protected), 혹시
# 지우는 걸 놓친 자리가 있어도 30초면 저절로 낫는다.
_CACHE: dict = {"names": None, "at": 0.0}
_CACHE_TTL = 30.0


def invalidate_protected() -> None:
    _CACHE["names"] = None
    # 회원 영상 목록은 "파는 영상을 뺀 것"이라 이쪽이 바뀌면 같이 바뀐다.
    from . import membervideo
    membervideo.invalidate()


def protected_filenames(db: Session) -> set:
    """정적 폴더로 내보내면 안 되는 파일 이름."""
    now = time.time()
    if _CACHE["names"] is not None and (now - _CACHE["at"]) < _CACHE_TTL:
        return _CACHE["names"]
    ids = []
    for ch in load_config(db).get("chapters") or []:
        if ch.get("video_id"):
            ids.append(ch["video_id"])
        for it in ch.get("items") or []:
            if it.get("video_id"):
                ids.append(it["video_id"])
    names = set()
    if ids:
        for (path,) in db.query(Video.file_path).filter(Video.id.in_(ids)).all():
            base = os.path.basename(path or "")
            if base:
                names.add(base)
    _CACHE["names"] = names
    _CACHE["at"] = now
    return names


# ---------------------------------------------------------------- 티켓
def make_ticket(user_id: int, video_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "vid": int(video_id),
        # 로그인 토큰으로 영상을 받거나 그 반대로 쓰는 일이 없게 못 박는다.
        "purpose": TICKET_PURPOSE,
        "exp": datetime.utcnow() + timedelta(minutes=TICKET_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def read_ticket(token: str, video_id: int) -> Optional[int]:
    """티켓이 이 영상에 대해 유효하면 사용자 id 를 돌려준다."""
    try:
        data = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
    if data.get("purpose") != TICKET_PURPOSE:
        return None
    try:
        if int(data.get("vid") or 0) != int(video_id):
            return None
        return int(data.get("sub"))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- 모양
def video_ids_in(cfg: dict) -> set:
    """구성이 쓰는 영상 번호 전부(챕터 + 그 안의 강의)."""
    out = set()
    for ch in cfg.get("chapters") or []:
        if ch.get("video_id"):
            out.add(int(ch["video_id"]))
        for it in ch.get("items") or []:
            if it.get("video_id"):
                out.add(int(it["video_id"]))
    return out


def assert_not_in_briefing(db: Session, ids: set) -> None:
    """특강(설명회)이 쓰는 영상을 파는 영상에 붙이지 못하게 막는다.

    붙이면 그 파일이 보호 목록에 들어가고, 정적 폴더로 나가던 특강 쪽이
    그날부터 403 으로 깨진다. 아무 말 없이 깨지는 것이 제일 나쁘다.

    같은 강의를 무료로도 주고 팔 수는 없다 — 한 파일을 두 규칙으로 낼 수는
    없기 때문이다. 정말 둘 다 쓰려면 영상을 두 개로 올려야 한다.
    """
    if not ids:
        return
    from . import briefing as briefing_mod
    used = video_ids_in(briefing_mod.load_config(db))
    clash = ids & used
    if not clash:
        return
    names = [(db.get(Video, i).title if db.get(Video, i) else str(i)) for i in sorted(clash)]
    raise HTTPException(
        status_code=400,
        detail=("'%s' 은(는) 설명회(특강)에서 쓰고 있습니다. 같은 영상을 무료로도 주고 "
                "팔 수는 없습니다 — 파는 영상으로 두면 특강 쪽이 재생되지 않습니다. "
                "설명회에서 빼거나, 파일을 따로 올려 주세요." % ", ".join(names)))


def _video_brief(db: Session, video_id) -> Optional[dict]:
    if not video_id:
        return None
    v = db.get(Video, int(video_id))
    if not v:
        return None
    return {"id": v.id, "title": v.title, "duration_sec": v.duration_sec,
            "has_file": bool(v.file_path)}


def _watermark(user: User) -> str:
    """화면에 겹쳐 둘 글자. 이름과 연락처 끝 네 자리.

    번호 전체는 안 띄운다 — 어깨너머로 남의 번호가 읽히면 그것대로 사고다.
    끝 네 자리면 유출본에서 계정을 짚기에 충분하다.
    """
    tail = "".join(ch for ch in (user.phone or "") if ch.isdigit())[-4:]
    name = (user.name or user.email or "").strip()
    return (name + " " + tail).strip()


def _source(db: Session, video_id, start_sec, owned: bool, user):
    """무엇을, 몇 초부터 재생할지 한 덩이로 만들어 준다.

    설명회(briefing.py)와 두 가지가 다르다.
      · 주소가 **티켓이 붙은 잠긴 길**이다. 원본 파일 경로는 절대 안 내보낸다.
      · **공개 여부를 안 본다.** 파는 영상은 오히려 비공개여야 맞다 —
        공개로 두면 특강 목록에 그냥 뜬다.
    """
    if not video_id:
        return None
    v = db.get(Video, int(video_id))
    if not v or not v.file_path:
        return None
    if not owned or not user:
        # 안 산 사람에게는 주소 자체를 안 만든다. 화면에서 가리는 건 가리는
        # 게 아니다 — 응답에 없어야 없는 것이다.
        return None
    return {"file_url": ("/api/graduate-video/stream/%d?t=%s"
                         % (v.id, make_ticket(user.id, v.id))),
            "start": float(start_sec or 0),
            "duration_sec": v.duration_sec}


def _playable(db: Session, ch: dict, owned: bool, user) -> dict:
    out = dict(ch)
    out["source"] = _source(db, ch.get("video_id"), ch.get("start_sec"), owned, user)
    items = []
    for it in ch.get("items") or []:
        one = dict(it)
        # 강의에 영상이 없으면 챕터 것을 쓴다. 초도 마찬가지 —
        # 강의에 적은 초가 없으면 챕터 시작으로 보낸다.
        vid = it.get("video_id") or ch.get("video_id")
        start = it.get("start_sec")
        if start is None:
            start = 0 if it.get("video_id") else ch.get("start_sec")
        one["source"] = _source(db, vid, start, owned, user)
        items.append(one)
    out["items"] = items
    return out


# ---------------------------------------------------------------- 공개
@router.get("/graduate-video")
def get_paid_video(db: Session = Depends(get_db),
                   user: Optional[User] = Depends(get_current_user_optional)):
    """합격생 영상 페이지가 쓰는 것 전부.

    **살 수 있는지, 샀는지, 무엇을 보는지를 서버가 정한다.** 화면이
    "로그인했나 → 신청했나 → 입금됐나"를 스스로 따지게 두면 어느 한 줄이
    빠졌을 때 안 산 사람에게 주소가 나간다.
    """
    from . import briefing as briefing_mod

    cfg = load_config(db)
    owned = apps.owns(db, user, KIND)
    mine = apps.my_application(db, user, KIND)
    chapters = [_playable(db, ch, owned, user) for ch in (cfg.get("chapters") or [])]

    # 영상 길이는 산 사람이 아니어도 알려 준다 — 사기 전에 분량을 아는 것은
    # 사는 데 필요한 정보다. 재생 주소만 안 나간다.
    #
    # 같은 영상을 여러 챕터가 나눠 쓰는 경우가 흔하다(한 편을 잘라 쓴 것).
    # 챕터마다 더하면 한 시간짜리가 세 시간으로 보이므로 영상 단위로 센다.
    seen, total = set(), 0.0
    for ch in cfg.get("chapters") or []:
        ids = [ch.get("video_id")] + [it.get("video_id") for it in (ch.get("items") or [])]
        for vid in ids:
            if not vid or vid in seen:
                continue
            seen.add(vid)
            v = _video_brief(db, vid)
            if v and v["duration_sec"]:
                total += float(v["duration_sec"])

    return {
        "headline": cfg.get("headline") or "",
        "intro": cfg.get("intro") or "",
        "cover": cfg.get("cover") or "",
        # 강사는 설명회와 같은 사람이라 그 프로필을 그대로 쓴다. 두 벌로
        # 나눠 두면 경력 한 줄을 고칠 때 한쪽만 고쳐 놓고 잊는다.
        "lecturer": briefing_mod.load_profile(db),
        "chapters": chapters,
        "summary": {
            "chapters": len(chapters),
            "lessons": sum(len(ch.get("items") or []) for ch in chapters),
            "duration_sec": total,
        },
        "owned": owned,
        "logged_in": user is not None,
        # 이미 후기를 남겼는지. 화면이 브라우저에만 표시를 남겨 두면 기기를
        # 바꾸거나 캐시를 지운 사람에게 또 묻는다 — 서버가 알고 있어야 한다.
        "reviewed": apps.my_application(db, user, REVIEW_KIND) is not None,
        "application": ({"status": mine.status,
                         "status_label": apps.STATUS_LABEL.get(mine.status, mine.status)}
                        if mine else None),
        "watermark": _watermark(user) if (owned and user) else "",
    }


@router.get("/graduate-video/stream/{video_id}")
def stream_paid_video(video_id: int, t: str = Query("", description="시청 티켓"),
                      db: Session = Depends(get_db)):
    """영상 알맹이. 티켓이 맞고, 그 사람이 실제로 샀을 때만 내보낸다.

    티켓만 믿지 않고 **살 권리를 매번 다시 확인한다.** 티켓은 세 시간을
    사는데, 그 사이에 환불이나 취소로 상태가 바뀌었을 수 있다.
    """
    user_id = read_ticket(t, video_id)
    if not user_id:
        raise HTTPException(status_code=403, detail="시청 권한을 확인할 수 없습니다.")
    user = db.get(User, user_id)
    if not user or not user.is_active or not apps.owns(db, user, KIND):
        raise HTTPException(status_code=403, detail="시청 권한이 없습니다.")

    cfg = load_config(db)
    allowed = set()
    for ch in cfg.get("chapters") or []:
        allowed.add(ch.get("video_id"))
        for it in ch.get("items") or []:
            allowed.add(it.get("video_id"))
    if video_id not in allowed:
        # 산 사람이라도 아무 영상이나 이 길로 받아 갈 수는 없다.
        raise HTTPException(status_code=404, detail="영상을 찾을 수 없습니다.")

    v = db.get(Video, video_id)
    path = videos_mod._abs_path(v.file_path if v else "")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="영상 파일이 없습니다.")
    # FileResponse 가 Range 요청을 처리한다 — 이게 없으면 앞으로 감기가 안 된다.
    return FileResponse(path, media_type="video/mp4")


# ---------------------------------------------------------------- 관리
class ItemIn(BaseModel):
    title: str = Field(default="", max_length=200)
    video_id: Optional[int] = None
    start_sec: Optional[float] = None


class ChapterIn(BaseModel):
    title: str = Field(default="", max_length=200)
    video_id: Optional[int] = None
    start_sec: float = 0
    items: List[ItemIn] = []


class ConfigIn(BaseModel):
    headline: str = Field(default="", max_length=200)
    intro: str = Field(default="", max_length=2000)
    cover: str = Field(default="", max_length=300)
    chapters: List[ChapterIn] = []


@router.get("/admin/graduate-video")
def admin_get(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return load_config(db)


@router.put("/admin/graduate-video")
def admin_put(payload: ConfigIn, db: Session = Depends(get_db),
              user: User = Depends(require_admin)):
    chapters = []
    for ch in payload.chapters:
        title = (ch.title or "").strip()
        if not title:
            # 빈 제목을 조용히 버리면 저장한 뒤 챕터가 사라진 것처럼 보인다.
            raise HTTPException(status_code=400, detail="제목이 없는 챕터가 있습니다.")
        if ch.video_id and db.get(Video, ch.video_id) is None:
            raise HTTPException(status_code=400, detail="없는 영상을 골랐습니다.")
        items = []
        for it in (ch.items or [])[:MAX_ITEMS]:
            t = (it.title or "").strip()
            if not t:
                raise HTTPException(status_code=400,
                                    detail=f"'{title}' 안에 제목이 없는 강의가 있습니다.")
            if it.video_id and db.get(Video, it.video_id) is None:
                raise HTTPException(status_code=400, detail="없는 영상을 골랐습니다.")
            items.append({"title": t[:200], "video_id": it.video_id or None,
                          "start_sec": it.start_sec})
        chapters.append({"title": title[:200], "video_id": ch.video_id or None,
                         "start_sec": max(float(ch.start_sec or 0), 0.0),
                         "items": items})
    cfg = {"headline": (payload.headline or "").strip(),
           "intro": (payload.intro or "").strip(),
           "cover": (payload.cover or "").strip()[:300],
           "chapters": chapters[:MAX_CHAPTERS]}
    assert_not_in_briefing(db, video_ids_in(cfg))
    save_config(db, cfg)
    return admin_get(db, user)


@router.post("/admin/graduate-video/cover")
def upload_cover(file: UploadFile = File(...), user: User = Depends(require_admin)):
    """맨 위 큰 화면의 배경. 설명회와 저장 방식이 같아 같은 함수를 쓴다."""
    from .main import _save_uploaded_image
    return {"url": _save_uploaded_image(file, prefix="gradvideo")}
