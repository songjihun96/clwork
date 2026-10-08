"""학교 홍보 인터뷰 — 학교에 찾아가 찍은 영상을 모아 보는 곳.

  · 촬영은 학교가 비용을 내고 신청한다. 신청은 따로 표를 만들지 않고
    기존 문의 폼(InquiryForm, via="학교 홍보 인터뷰 촬영 신청")으로 받는다 —
    묻는 것(학교·담당자·연락처·요청사항)이 똑같다.
  · 보는 것은 **가입한 회원만**. 목록(학교 이름·제목·소개)은 누구나 보게
    두고, 재생 주소만 로그인한 사람에게 준다. 무엇이 있는지는 보여야
    가입할 이유가 생긴다.
  · 영상 파일은 영상 관리에 올리고 여기서 고른다. 파일은 membervideo.py 가
    /api/media 에서 걸러 잠근다.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import membervideo
from .auth import get_current_user_optional, require_admin
from .database import get_db
from .models import School, SchoolInterview, User, Video

router = APIRouter(prefix="/api", tags=["interviews"])


def video_ids(db: Session) -> set:
    """인터뷰가 쓰는 영상 전부. 게시 전 것도 넣는다 — 올려 두고 게시만 안 한
    영상이 그 사이 /api/media 로 새면 안 된다."""
    return {vid for (vid,) in db.query(SchoolInterview.video_id)
            .filter(SchoolInterview.video_id.isnot(None)).all()}


# 지역 필터 순서. 학교 검색·문의 폼과 같은 순서를 쓴다.
REGIONS = ("서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
           "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주")
NO_REGION = "기타"


def region_of(db: Session, it: SchoolInterview, s: Optional[School] = None) -> str:
    """인터뷰의 지역. 포털 학교면 학교의 지역, 아니면 직접 적은 지역."""
    if s is None and it.school_id:
        s = db.get(School, it.school_id)
    return ((s.region if s else "") or it.region or "").strip()


def _school_brief(db: Session, it: SchoolInterview) -> dict:
    s = db.get(School, it.school_id) if it.school_id else None
    return {
        "id": s.id if s else None,
        "name": (s.name if s else "") or it.school_name or "",
        "region": region_of(db, it, s),
        "category": s.category if s else "",
    }


def _out(db: Session, it: SchoolInterview, user: Optional[User] = None,
         with_source: bool = False, admin: bool = False) -> dict:
    v = db.get(Video, it.video_id) if it.video_id else None
    out = {
        "id": it.id, "title": it.title, "summary": it.summary or "",
        "speakers": it.speakers or "",
        "school": _school_brief(db, it),
        "thumbnail": it.thumbnail or (v.thumbnail if v else "") or "",
        "duration_sec": v.duration_sec if v else None,
        "filmed_on": it.filmed_on.isoformat() if it.filmed_on else None,
        "view_count": it.view_count or 0,
        "created_at": it.created_at,
    }
    if admin:
        out.update({
            "school_id": it.school_id, "school_name": it.school_name or "",
            "own_region": it.region or "",
            "video_id": it.video_id, "video_title": v.title if v else "",
            "has_file": bool(v and v.file_path),
            "is_published": bool(it.is_published), "sort_order": it.sort_order or 0,
            # 고치는 화면에는 이 인터뷰에 직접 올린 것만 준다(영상 썸네일로 채운
            # 값을 그대로 저장하면 영상 쪽을 바꿔도 안 따라간다).
            "own_thumbnail": it.thumbnail or "",
        })
    if with_source:
        # 로그인 안 한 사람에게는 주소를 만들지 않는다. 화면에서 가리는 건
        # 가리는 게 아니다 — 응답에 없어야 없는 것이다.
        playable = bool(v and v.file_path)
        out["login_required"] = user is None
        out["source"] = ({"file_url": membervideo.stream_url(user, v.id),
                          "duration_sec": v.duration_sec}
                         if (user is not None and playable) else None)
        out["has_video"] = playable
    return out


# ---------------------------------------------------------------- 공개
def _region_order(r: str) -> tuple:
    return (REGIONS.index(r) if r in REGIONS else len(REGIONS), r)


@router.get("/interviews")
def list_interviews(school_id: Optional[int] = Query(None),
                    region: str = Query("", max_length=20),
                    db: Session = Depends(get_db),
                    user: Optional[User] = Depends(get_current_user_optional)):
    """region 을 주면 그 지역 인터뷰만. '기타'는 지역을 모르는 인터뷰.
    regions 는 필터 버튼용 — 거르기 전 전체 기준 지역별 개수라, 한 지역을
    골라도 다른 지역 버튼이 사라지지 않는다."""
    q = db.query(SchoolInterview).filter(SchoolInterview.is_published.is_(True))
    if school_id:
        q = q.filter(SchoolInterview.school_id == school_id)
    rows = q.order_by(SchoolInterview.sort_order.desc(),
                      SchoolInterview.created_at.desc()).all()
    items = [_out(db, it) for it in rows]
    counts: dict = {}
    for x in items:
        r = x["school"]["region"] or NO_REGION
        counts[r] = counts.get(r, 0) + 1
    region = region.strip()
    if region:
        items = [x for x in items if (x["school"]["region"] or NO_REGION) == region]
    return {
        "items": items,
        "total": len(rows),
        "region": region,
        "regions": [{"region": r, "count": counts[r]} for r in sorted(counts, key=_region_order)],
        "logged_in": user is not None,
    }


@router.get("/interviews/{interview_id}")
def get_interview(interview_id: int, db: Session = Depends(get_db),
                  user: Optional[User] = Depends(get_current_user_optional)):
    it = db.get(SchoolInterview, interview_id)
    if not it or not it.is_published:
        raise HTTPException(status_code=404, detail="인터뷰를 찾을 수 없습니다.")
    if user is not None:
        # 조회수는 실제로 볼 수 있는 사람만 센다 — 잠긴 화면만 본 것은 본 게 아니다.
        it.view_count = (it.view_count or 0) + 1
        db.commit()
        db.refresh(it)
    return _out(db, it, user, with_source=True)


# ---------------------------------------------------------------- 관리
class InterviewIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    summary: str = Field(default="", max_length=3000)
    speakers: str = Field(default="", max_length=200)
    school_id: Optional[int] = None
    school_name: str = Field(default="", max_length=80)
    region: str = Field(default="", max_length=20)
    video_id: Optional[int] = None
    thumbnail: str = Field(default="", max_length=300)
    filmed_on: Optional[date] = None
    is_published: bool = False
    sort_order: int = 0


def _apply(db: Session, it: SchoolInterview, p: InterviewIn) -> None:
    if p.school_id and not db.get(School, p.school_id):
        raise HTTPException(status_code=400, detail="고른 학교를 찾을 수 없습니다.")
    if not p.school_id and not p.school_name.strip():
        raise HTTPException(status_code=400, detail="학교를 고르거나 학교 이름을 적어 주세요.")
    if p.region.strip() and p.region.strip() not in REGIONS:
        raise HTTPException(status_code=400, detail="지역은 목록에서 골라 주세요.")
    if p.video_id:
        v = db.get(Video, p.video_id)
        if not v or v.kind != "longform":
            raise HTTPException(status_code=400, detail="고른 영상을 찾을 수 없습니다(롱폼만 쓸 수 있습니다).")
        # 파는 영상(합격생 영상)에 붙은 파일은 못 쓴다. 여기 붙이면 가입만
        # 한 사람이 산 사람 몫을 받아 가게 된다.
        from . import paidvideo
        if p.video_id in paidvideo.video_ids_in(paidvideo.load_config(db)):
            raise HTTPException(status_code=400, detail=(
                f"'{v.title}' 은(는) 합격생 영상(유료)에서 쓰고 있습니다. "
                "파일을 따로 올려 주세요."))
    if p.is_published and not p.video_id:
        raise HTTPException(status_code=400, detail="영상을 고른 뒤에 게시할 수 있습니다.")
    it.title = p.title.strip()
    it.summary = p.summary.strip()
    it.speakers = p.speakers.strip()
    it.school_id = p.school_id or None
    it.school_name = p.school_name.strip()
    # 포털 학교를 고르면 학교의 지역을 쓰므로 이 칸은 비운다(두 값이 어긋나지 않게).
    it.region = "" if p.school_id else p.region.strip()
    it.video_id = p.video_id or None
    it.thumbnail = p.thumbnail.strip()
    it.filmed_on = p.filmed_on
    it.is_published = p.is_published
    it.sort_order = p.sort_order


@router.get("/admin/interviews")
def admin_list(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    rows = db.query(SchoolInterview).order_by(SchoolInterview.sort_order.desc(),
                                              SchoolInterview.created_at.desc()).all()
    return [_out(db, it, admin=True) for it in rows]


@router.post("/admin/interviews")
def admin_create(payload: InterviewIn, db: Session = Depends(get_db),
                 user: User = Depends(require_admin)):
    it = SchoolInterview(title=payload.title)
    _apply(db, it, payload)
    db.add(it)
    db.commit()
    db.refresh(it)
    membervideo.invalidate()
    return _out(db, it, admin=True)


@router.put("/admin/interviews/{interview_id}")
def admin_update(interview_id: int, payload: InterviewIn, db: Session = Depends(get_db),
                 user: User = Depends(require_admin)):
    it = db.get(SchoolInterview, interview_id)
    if not it:
        raise HTTPException(status_code=404, detail="인터뷰를 찾을 수 없습니다.")
    _apply(db, it, payload)
    db.commit()
    db.refresh(it)
    membervideo.invalidate()
    return _out(db, it, admin=True)


@router.delete("/admin/interviews/{interview_id}")
def admin_delete(interview_id: int, db: Session = Depends(get_db),
                 user: User = Depends(require_admin)):
    """인터뷰 묶음만 지운다. 영상 파일은 영상 관리에 그대로 남는다."""
    it = db.get(SchoolInterview, interview_id)
    if not it:
        raise HTTPException(status_code=404, detail="인터뷰를 찾을 수 없습니다.")
    db.delete(it)
    db.commit()
    membervideo.invalidate()
    return {"ok": True}


@router.post("/admin/interviews/thumbnail")
def upload_thumbnail(file: UploadFile = File(...), user: User = Depends(require_admin)):
    from .main import _save_uploaded_image
    return {"url": _save_uploaded_image(file, prefix="interview")}
