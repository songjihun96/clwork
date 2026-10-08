"""온라인 직업계고설명회 API.

강사 프로필과 **강의 구성**(어떤 영상을, 어떤 챕터로 나눠 보여줄지)을 다룬다.
시청 전 설문과 시청 후 후기는 신청 접수(applications.py)를 그대로 쓴다 —
묻는 것이 신청폼과 같은 모양이고, 관리자도 한 화면에서 보는 편이 낫다.

**챕터마다 영상을 따로 붙일 수 있다.** 강의를 챕터 단위로 잘라 올리는 쪽이
흔해서 그쪽을 기본으로 본다. 다만 한 편짜리 긴 영상도 계속 되게 둔다 —
챕터에 영상을 안 고르면 맨 위에 고른 영상의 그 초부터 재생한다. 이미 그렇게
넣어 둔 구성이 안 깨져야 하기 때문이다.

  · 챕터에 영상이 있으면  → 그 영상을 처음부터(또는 적어 둔 초부터)
  · 없으면               → 기본 영상의 start_sec 부터

**왜 프로필을 코드에 안 박았나**
경력 줄은 계속 늘어난다("연200회 이상 연수 진행"은 내년에 숫자가 바뀐다).
이 프로젝트는 배포가 zip 을 서버에서 푸는 방식이라, 글자 한 줄 고치자고
배포를 다시 하게 만들면 결국 아무도 안 고친다. 그래서 관리자가 화면에서
직접 고치게 두고, 값은 Setting 한 줄에 JSON 으로 담는다 — 프로필 하나에
테이블을 새로 파는 것보다 가볍고, 나중에 강사가 여러 명이 되어도 이
JSON 을 배열로 바꾸면 된다.
"""

from __future__ import annotations

import json
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .auth import get_current_user_optional, require_admin
from .database import get_db
from .models import Setting, User

router = APIRouter(prefix="/api", tags=["briefing"])

SETTING_KEY = "lecturer_profile"
CONFIG_KEY = "briefing_config"

MAX_CHAPTERS = 30
MAX_ITEMS = 12

MAX_CAREERS = 40          # 화면에 번호를 매겨 늘어놓는 목록이라 한계를 둔다
MAX_CAREER_LEN = 200


MAX_LINKS = 8


def _empty() -> dict:
    return {"name": "", "title": "", "photo": "", "careers": [],
            "links": [], "cta_label": "", "cta_url": ""}


def _clean_links(raw) -> list:
    """[{label, url}] 만 남긴다. 주소가 없는 줄은 버린다."""
    out = []
    if not isinstance(raw, list):
        return out
    for item in raw[:MAX_LINKS]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        out.append({"label": str(item.get("label") or "").strip()[:40] or url,
                    "url": url[:300]})
    return out


def load_profile(db: Session) -> dict:
    row = db.get(Setting, SETTING_KEY)
    out = _empty()
    if not row or not (row.value or "").strip():
        return out
    try:
        saved = json.loads(row.value)
    except ValueError:
        # 손상된 값 때문에 화면 전체가 죽지 않게 한다. 빈 프로필이 500 보다 낫다.
        return out
    if not isinstance(saved, dict):
        return out
    for key in out:
        if key in saved and saved[key] is not None:
            out[key] = saved[key]
    if not isinstance(out["careers"], list):
        out["careers"] = []
    out["careers"] = [str(c) for c in out["careers"]]
    out["links"] = _clean_links(out.get("links"))
    return out


class LecturerIn(BaseModel):
    name: str = Field(default="", max_length=60)
    title: str = Field(default="", max_length=120)
    photo: str = Field(default="", max_length=300)
    careers: List[str] = Field(default_factory=list)
    # 모양이 어긋난 줄 하나 때문에 저장 전체가 막히면 안 된다.
    # 걸러내는 일은 _clean_links 가 한다.
    links: List[object] = Field(default_factory=list)
    cta_label: str = Field(default="", max_length=60)
    cta_url: str = Field(default="", max_length=300)


@router.get("/lecturer")
def get_lecturer(db: Session = Depends(get_db)):
    """강사 프로필(공개). 아직 아무것도 안 넣었으면 빈 값이 온다."""
    return load_profile(db)


@router.put("/admin/lecturer")
def put_lecturer(payload: LecturerIn, db: Session = Depends(get_db),
                 user: User = Depends(require_admin)):
    careers = [c.strip() for c in payload.careers if c and c.strip()]
    if len(careers) > MAX_CAREERS:
        raise HTTPException(status_code=400,
                            detail=f"경력은 {MAX_CAREERS}줄까지 넣을 수 있습니다.")
    too_long = next((c for c in careers if len(c) > MAX_CAREER_LEN), None)
    if too_long:
        raise HTTPException(
            status_code=400,
            detail=f"경력 한 줄은 {MAX_CAREER_LEN}자 이하로 적어주세요: '{too_long[:20]}…'")

    data = payload.model_dump()
    data["careers"] = careers
    data["links"] = _clean_links(payload.links)
    value = json.dumps(data, ensure_ascii=False)

    row = db.get(Setting, SETTING_KEY)
    if row is None:
        db.add(Setting(key=SETTING_KEY, value=value))
    else:
        row.value = value
    db.commit()
    return load_profile(db)


@router.post("/admin/lecturer/photo")
def upload_lecturer_photo(file: UploadFile = File(...),
                          user: User = Depends(require_admin)):
    # 이미지 저장은 main.py 의 것을 그대로 쓴다. 규칙(형식·크기·이름)이
    # 한 군데에만 있어야 나중에 바꿀 때 빠뜨리지 않는다.
    from .main import _save_uploaded_image
    return {"url": _save_uploaded_image(file, prefix="lecturer")}


# ================================================================ 강의 구성
def _empty_config() -> dict:
    return {"video_id": None, "headline": "", "intro": "", "cover": "",
            "chapters": []}


def _clean_items(raw) -> list:
    """강의 목록을 {title, start_sec} 로 맞춘다.

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


def load_config(db: Session) -> dict:
    row = db.get(Setting, CONFIG_KEY)
    out = _empty_config()
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
    if not isinstance(out["chapters"], list):
        out["chapters"] = []
    fixed = []
    for ch in out["chapters"]:
        if not isinstance(ch, dict):
            continue
        vid = ch.get("video_id")
        try:
            vid = int(vid) if vid else None
        except (TypeError, ValueError):
            vid = None
        fixed.append({
            "title": str(ch.get("title") or ""),
            "video_id": vid,
            "items": _clean_items(ch.get("items")),
            "start_sec": ch.get("start_sec") or 0,
        })
    out["chapters"] = fixed
    return out


class ChapterIn(BaseModel):
    title: str = Field(default="", max_length=200)
    video_id: Optional[int] = None
    # 강의 한 줄. 예전 형식(문자열)과 새 형식({title, start_sec}) 둘 다 받는다 —
    # 이미 저장된 값이 문자열이라, 한쪽만 받으면 예전 구성이 통째로 날아간다.
    items: List[object] = Field(default_factory=list)
    start_sec: float = Field(default=0, ge=0)


class ConfigIn(BaseModel):
    video_id: Optional[int] = None
    headline: str = Field(default="", max_length=200)
    intro: str = Field(default="", max_length=1000)
    cover: str = Field(default="", max_length=300)
    chapters: List[ChapterIn] = Field(default_factory=list)


def _video_out(db: Session, video_id) -> Optional[dict]:
    """강의로 쓸 영상. 공개된 롱폼만 학생에게 내보낸다."""
    from .models import Video
    if not video_id:
        return None
    v = db.get(Video, int(video_id))
    if not v or v.kind != "longform":
        return None
    return {"id": v.id, "title": v.title, "file_url": v.file_path or "",
            "duration_sec": v.duration_sec, "is_public": bool(v.is_public)}


def _source(db: Session, video_id, start_sec, fallback):
    """무엇을, 몇 초부터 재생할지 한 덩이로 만들어 준다.

    화면이 "영상이 있으면 이걸, 없으면 저걸, 초는 이 경우엔…"을 매번 따지게
    두면 챕터·강의·기본값 조합에서 반드시 어긋난다. 서버가 한 번에 정한다.

    여기서 돌려주는 file_url 은 **원본 경로**다. 밖으로 내보내기 전에
    _for_viewer 가 회원용 잠긴 주소로 바꾸거나 지운다.
    """
    if video_id:
        v = _video_out(db, video_id)
        if v and v["is_public"] and v["file_url"]:
            return {"video_id": v["id"], "file_url": v["file_url"],
                    "start": float(start_sec or 0), "duration_sec": v["duration_sec"]}
        # 고르긴 했는데 못 쓴다(비공개거나 파일 없음). 기본 영상으로도 안 보낸다 —
        # 엉뚱한 영상이 재생되는 것보다 안 되는 편이 낫다.
        return None
    if fallback and fallback.get("file_url"):
        return {"video_id": fallback["id"], "file_url": fallback["file_url"],
                "start": float(start_sec or 0), "duration_sec": fallback.get("duration_sec")}
    return None


def _for_viewer(src, user):
    """(source, locked). 설명회는 **회원만** 본다 — 로그인 안 했으면 주소를
    아예 안 만든다. 로그인했으면 /api/media 원본 대신 티켓이 붙은 주소를 준다
    (원본은 membervideo 가 /api/media 에서 걸러 잠가 둔다)."""
    if not src:
        return None, False
    if user is None:
        return None, True
    from . import membervideo
    out = {k: v for k, v in src.items() if k != "video_id"}
    out["file_url"] = membervideo.stream_url(user, src["video_id"])
    return out, False


def _playable(db: Session, ch: dict, fallback, user=None) -> dict:
    out = dict(ch)
    out["source"], out["locked"] = _for_viewer(
        _source(db, ch.get("video_id"), ch.get("start_sec"), fallback), user)
    items = []
    for it in ch.get("items") or []:
        one = dict(it)
        # 강의에 영상이 없으면 챕터 것을 쓴다. 초도 마찬가지 —
        # 강의에 적은 초가 없으면 챕터 시작으로 보낸다.
        vid = it.get("video_id") or ch.get("video_id")
        start = it.get("start_sec")
        if start is None:
            start = 0 if it.get("video_id") else ch.get("start_sec")
        one["source"], one["locked"] = _for_viewer(_source(db, vid, start, fallback), user)
        items.append(one)
    out["items"] = items
    return out


@router.get("/briefing")
def get_briefing(db: Session = Depends(get_db),
                 user: Optional[User] = Depends(get_current_user_optional)):
    """설명회 페이지가 쓰는 것 전부 — 강사, 강의 영상, 챕터.

    강사·챕터 제목은 누구나 본다(무엇을 듣게 되는지 알아야 가입한다).
    재생 주소만 로그인한 회원에게 나간다.
    """
    cfg = load_config(db)
    video = _video_out(db, cfg.get("video_id"))
    # 비공개 영상은 주소조차 내보내지 않는다. 내보내면 그 주소로 그냥 볼 수 있다.
    if video and not video["is_public"]:
        video = {**video, "file_url": "", "locked": True}
    chapters = [_playable(db, ch, video, user) for ch in (cfg.get("chapters") or [])]
    has_video = bool(video and video.get("file_url")) or any(
        ch.get("source") or ch.get("locked") for ch in chapters)
    if video and video.get("file_url"):
        from . import membervideo
        video = {**video, "file_url": membervideo.stream_url(user, video["id"]) if user else ""}
    return {
        "lecturer": load_profile(db),
        "headline": cfg.get("headline") or "",
        "intro": cfg.get("intro") or "",
        "cover": cfg.get("cover") or "",
        "chapters": chapters,
        "video": video,
        "logged_in": user is not None,
        # 영상은 있는데 로그인을 안 해서 못 튼다 — 화면이 [회원가입하고 보기]를 띄운다.
        "login_required": user is None and has_video,
        # 화면 맨 위 요약줄에 쓴다. 세는 규칙이 화면마다 달라지지 않도록
        # 서버가 한 번만 세어 내려보낸다.
        "summary": {
            "chapters": len(chapters),
            "lessons": sum(len(ch.get("items") or []) for ch in chapters),
            "duration_sec": (video or {}).get("duration_sec") or 0,
        },
    }


@router.get("/admin/briefing")
def get_briefing_admin(db: Session = Depends(get_db),
                       user: User = Depends(require_admin)):
    cfg = load_config(db)
    return {**cfg, "video": _video_out(db, cfg.get("video_id"))}


@router.put("/admin/briefing")
def put_briefing(payload: ConfigIn, db: Session = Depends(get_db),
                 user: User = Depends(require_admin)):
    chapters = []
    for ch in payload.chapters:
        title = ch.title.strip()
        if not title:
            continue
        if ch.video_id and _video_out(db, ch.video_id) is None:
            raise HTTPException(status_code=400,
                                detail=f"'{title}' 에 고른 영상을 찾을 수 없습니다.")
        chapters.append({
            "title": title,
            "video_id": ch.video_id or None,
            "items": _clean_items(ch.items),
            "start_sec": round(float(ch.start_sec), 2),
        })
    if len(chapters) > MAX_CHAPTERS:
        raise HTTPException(status_code=400,
                            detail=f"챕터는 {MAX_CHAPTERS}개까지 넣을 수 있습니다.")
    if payload.video_id:
        if _video_out(db, payload.video_id) is None:
            raise HTTPException(status_code=400, detail="고른 영상을 찾을 수 없습니다.")

    data = {"video_id": payload.video_id, "headline": payload.headline.strip(),
            "intro": payload.intro.strip(), "cover": payload.cover.strip(),
            "chapters": chapters}

    # 파는 영상(합격생 영상)에 붙어 있는 파일을 여기에 끌어오지 못하게 막는다.
    # 그 파일은 인증 없는 정적 폴더로 안 나가도록 잠겨 있어서, 여기 붙이면
    # 설명회가 아무 말 없이 403 으로 깨진다.
    from . import paidvideo
    used = paidvideo.video_ids_in(paidvideo.load_config(db))
    mine = {ch["video_id"] for ch in chapters if ch.get("video_id")}
    if payload.video_id:
        mine.add(payload.video_id)
    for ch in chapters:
        for it in ch.get("items") or []:
            if it.get("video_id"):
                mine.add(it["video_id"])
    clash = mine & used
    if clash:
        names = [(_video_out(db, i) or {}).get("title") or str(i) for i in sorted(clash)]
        raise HTTPException(
            status_code=400,
            detail=("'%s' 은(는) 합격생 영상(유료)에서 쓰고 있습니다. 같은 영상을 "
                    "무료로도 주고 팔 수는 없습니다 — 여기 붙이면 재생되지 않습니다. "
                    "합격생 영상 구성에서 빼거나, 파일을 따로 올려 주세요."
                    % ", ".join(names)))

    value = json.dumps(data, ensure_ascii=False)
    row = db.get(Setting, CONFIG_KEY)
    if row is None:
        db.add(Setting(key=CONFIG_KEY, value=value))
    else:
        row.value = value
    db.commit()
    # 잠글 파일 목록이 바뀌었다(새로 붙인 영상은 잠그고, 뺀 영상은 푼다).
    from . import membervideo
    membervideo.invalidate()
    return get_briefing_admin(db, user)


@router.post("/admin/briefing/cover")
def upload_cover(file: UploadFile = File(...),
                 user: User = Depends(require_admin)):
    """설명회 대표 이미지. 맨 위 큰 화면의 배경으로 깔린다."""
    from .main import _save_uploaded_image
    return {"url": _save_uploaded_image(file, prefix="briefing")}
