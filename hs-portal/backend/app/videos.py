"""롱폼·숏츠 영상 API.

숏츠는 롱폼의 한 구간에서 잘려 나온 것으로 본다. 그래서 숏츠를 보다가
"전체 영상 보기"를 누르면 롱폼의 **그 초부터** 재생된다. 그 초를 사람이
일일이 적지 않도록 대본을 맞춰 자동으로 찾는 것이 이 기능의 핵심이다
(찾는 방법은 `fingerprint.py` — 소리 자체를 지문으로 떠서 맞춘다).

**대본을 왜 안 쓰나**
예전에는 대본을 받아 적어(STT) 글자를 맞춰 구간을 찾았다. 지금은 안 쓴다.
받아 적기는 외부 업체 할당량에 매번 걸렸고(무료 시간 초과·크레딧 없음),
받아 적어도 시각이 문장 단위라 0.1~0.5초가 한계였다. 소리 지문은 그보다
한 자릿수 정밀하고, 말이 없는 숏츠도 찾고, 아무것도 안 넣어도 된다.

**왜 main.py 에 안 넣었나**
main.py 는 이미 6800줄이다. cs.py·callcenter/ 처럼 기능 단위로 라우터를
나눠 온 관례를 따른다.

**분석은 왜 뒤로 미루나**
1시간 영상을 받아 적는 데 몇 분이 걸린다. 그동안 요청을 붙들고 있으면
gunicorn 워커가 통째로 묶여 다른 화면까지 멈춘다. 그래서 상태만 DB 에
적고 바로 응답한 뒤 뒤에서 처리한다 — 상태가 DB 에 있으니 관리자가
새로고침해도 진행 상황이 그대로 보인다.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
from datetime import datetime
from typing import List, Optional

from fastapi import (APIRouter, BackgroundTasks, Depends, File, Form,
                     HTTPException, Query, UploadFile)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import fingerprint as fp_mod
from . import media as media_mod
from . import shorts_match
from .auth import get_current_user_optional, require_admin
from .database import get_db
from .models import (MATCH_STATUSES, Setting, ShortsMatch, User, Video,
                     VideoFingerprint)

router = APIRouter(prefix="/api", tags=["videos"])

# 영상은 이미지와 따로 둔다. 크기가 자릿수 단위로 다르고, 용량이 찼을 때
# 무엇부터 지울지 판단하려면 섞여 있지 않아야 한다.
MEDIA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "media")
os.makedirs(MEDIA_DIR, exist_ok=True)

ALLOWED_VIDEO_TYPES = {
    "video/mp4": ".mp4", "video/quicktime": ".mov",
    "video/x-m4v": ".m4v", "video/webm": ".webm",
}
# 올릴 수 있는 최대 크기. 환경변수로 뺀 이유는, 이 값을 바꾸려고 배포를
# 다시 하게 만들고 싶지 않아서다 — 디스크 여유는 서버 사정이라 우리가
# 코드에 못 박을 수 없다.
#
# **nginx 의 client_max_body_size 와 반드시 짝을 맞춰야 한다.** 여기만
# 키우면 요청이 우리 코드에 닿기도 전에 nginx 가 413 으로 자른다.
MAX_VIDEO_MB = int(os.environ.get("MAX_VIDEO_MB", "5120"))
MAX_VIDEO_BYTES = MAX_VIDEO_MB * 1024 * 1024
CHUNK = 1024 * 1024


def max_video_label() -> str:
    """사람에게 보여줄 크기. 1024 로 나눠떨어지면 GB 로 말한다."""
    if MAX_VIDEO_MB % 1024 == 0:
        return f"{MAX_VIDEO_MB // 1024}GB"
    return f"{MAX_VIDEO_MB}MB"


# ---------------------------------------------------------------- 설정
def _thresholds(db: Session) -> dict:
    """자동 확정 임계값. 실제 영상으로 돌려 보기 전에는 어느 선이 맞는지
    알 수 없어서 설정으로 빼 둔다(관리자 화면에서 바꾼다)."""
    out = dict(shorts_match.DEFAULT_THRESHOLDS)
    row = db.query(Setting).filter(Setting.key == "shorts_match_thresholds").first()
    if row and (row.value or "").strip():
        try:
            out.update({k: float(v) for k, v in json.loads(row.value).items()})
        except (ValueError, TypeError):
            pass
    return out


# ---------------------------------------------------------------- 공개 여부
# 기능을 다 만들어 두고도 당장은 학생에게 안 보이고 싶을 때가 있다. 영상마다
# is_public 을 끄는 것으로도 되지만, 그러면 관리자도 학생 화면을 못 본다.
# 전체 스위치를 따로 두어 "관리자에게만 보이는 상태"를 만든다.
VIDEOS_PUBLIC_KEY = "videos_public"


def videos_public(db: Session) -> bool:
    row = db.query(Setting).filter(Setting.key == VIDEOS_PUBLIC_KEY).first()
    return bool(row and (row.value or "").strip().lower() == "true")


def _guard_public(db: Session, user: Optional[User]) -> None:
    """공개 전이면 관리자만 통과시킨다.

    403 이 아니라 404 로 막는다. 아직 안 여는 기능이 있다는 사실 자체를
    알릴 이유가 없다.
    """
    if videos_public(db):
        return
    if user is not None and getattr(user.role, "value", user.role) == "admin":
        return
    raise HTTPException(status_code=404, detail="영상을 찾을 수 없습니다.")


# ---------------------------------------------------------------- 출력 모양
def video_out(v: Video, db: Optional[Session] = None, detail: bool = False) -> dict:
    out = {
        "id": v.id, "kind": v.kind, "title": v.title,
        "description": v.description or "",
        "file_url": v.file_path or "", "thumbnail": v.thumbnail or "",
        "duration_sec": v.duration_sec, "category": v.category or "",
        "is_public": bool(v.is_public), "view_count": v.view_count or 0,
        "created_at": v.created_at,
    }
    if not detail or db is None:
        return out

    fpr = db.query(VideoFingerprint).filter(
        VideoFingerprint.video_id == v.id).first()
    out["fingerprint"] = {
        "status": fpr.status if fpr else "none",
        "hashes": fpr.hash_count if fpr else 0,
        "error": (fpr.error or "") if fpr else "",
    }
    if v.kind == "shorts":
        m = db.query(ShortsMatch).filter(ShortsMatch.shorts_id == v.id).first()
        out["match"] = match_out(m, db) if m else None
    else:
        rows = (db.query(ShortsMatch, Video)
                .join(Video, ShortsMatch.shorts_id == Video.id)
                .filter(ShortsMatch.longform_id == v.id)
                .order_by(ShortsMatch.source_start_time.asc().nullslast()).all())
        out["shorts"] = [
            {**video_out(sv), "match": match_out(m, db)} for m, sv in rows
        ]
    return out


def match_out(m: ShortsMatch, db: Optional[Session] = None) -> dict:
    out = {
        "id": m.id, "shorts_id": m.shorts_id, "longform_id": m.longform_id,
        "source_start_time": m.source_start_time,
        "source_end_time": m.source_end_time,
        "status": m.status, "confidence": m.confidence, "method": m.method or "",
        "text_score": m.text_score, "sequence_score": m.sequence_score,
        "audio_score": m.audio_score, "visual_score": m.visual_score,
        "manually_verified": bool(m.manually_verified),
        "manually_modified": bool(m.manually_modified),
        "note": m.note or "", "analyzed_at": m.analyzed_at,
    }
    if db is not None:
        lf = db.get(Video, m.longform_id)
        out["longform_title"] = lf.title if lf else ""
    return out


# ---------------------------------------------------------------- 입력 모양
class VideoIn(BaseModel):
    kind: str = Field(default="longform", pattern="^(longform|shorts)$")
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    category: str = Field(default="", max_length=40)
    is_public: bool = False
    thumbnail: str = ""
    # 숏츠일 때만: 어느 롱폼에서 나왔는지
    longform_id: Optional[int] = None


class VideoPatch(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None
    category: Optional[str] = Field(default=None, max_length=40)
    is_public: Optional[bool] = None
    thumbnail: Optional[str] = None
    longform_id: Optional[int] = None


class MatchEditIn(BaseModel):
    source_start_time: float = Field(ge=0)
    source_end_time: float = Field(ge=0)
    note: str = ""


# ---------------------------------------------------------------- 분석 (뒤에서 돎)
def _forget_protected() -> None:
    """유료 영상 보호 목록을 다시 짜게 한다.

    영상 파일이 바뀌거나 사라지면 그 목록도 낡는다. paidvideo 를 위에서
    import 하면 서로 물고 도는 모양이 되므로 쓸 때 불러온다.
    """
    try:
        from . import paidvideo
        paidvideo.invalidate_protected()
    except Exception:            # 목록은 30초면 저절로 낫는다 — 여기서 안 막는다
        pass


def _abs_path(file_url: str) -> str:
    """/api/media/xxx.mp4 → 실제 디스크 경로."""
    name = os.path.basename(file_url or "")
    return os.path.join(MEDIA_DIR, name) if name else ""


def run_match(match_id: int) -> None:
    """숏츠 하나가 롱폼의 몇 초에서 나왔는지 소리로 찾는다.

    뒤에서 도는 함수라 예외를 밖으로 안 던진다.
    """
    from .database import SessionLocal
    db = SessionLocal()
    try:
        m = db.get(ShortsMatch, match_id)
        if not m:
            return
        # 관리자가 손댄 구간은 재분석이 덮어쓰지 않는다. 사람이 눈으로 보고
        # 고친 값이 기계 추정보다 옳다.
        if m.manually_modified:
            m.status = "confirmed" if m.manually_verified else "needs_review"
            db.commit()
            return

        shorts = db.get(Video, m.shorts_id)
        longform = db.get(Video, m.longform_id)
        if not shorts or not longform:
            m.status = "failed"
            m.note = "영상을 찾을 수 없습니다."
            db.commit()
            return

        m.analyzed_at = datetime.utcnow()
        m.method = "audio"
        m.text_score = m.sequence_score = None

        lf_fp = _load_fingerprint(db, longform.id)
        sf_fp = _load_fingerprint(db, shorts.id)
        if lf_fp is None or sf_fp is None:
            # 지문이 없으면 할 수 있는 게 없다. 어느 쪽이 없는지 짚어 준다 —
            # "실패"만 띄우면 무엇을 해야 할지 알 수 없다.
            missing = "롱폼" if lf_fp is None else "숏츠"
            m.status = "failed"
            m.note = (f"{missing}의 소리 지문이 없습니다. "
                      "영상을 다시 올리거나 [소리 지문 만들기]를 눌러주세요.")
            db.commit()
            return

        hit = fp_mod.locate(lf_fp, sf_fp)
        if not hit:
            m.status = "needs_review"
            m.audio_score = None
            m.note = ("소리가 겹치는 자리를 못 찾았습니다. 다른 롱폼에서 잘린 "
                      "숏츠이거나, 편집으로 소리가 많이 바뀐 경우입니다.")
            db.commit()
            return

        m.audio_score = hit.score
        m.source_start_time = shorts_match.clamp(hit.start_sec, longform.duration_sec)
        m.source_end_time = shorts_match.clamp(
            hit.start_sec + (shorts.duration_sec or 0), longform.duration_sec)
        m.confidence = _audio_confidence(hit)

        th = _thresholds(db)
        m.status = ("completed" if shorts_match.is_auto_confirmable(m.confidence, th)
                    else shorts_match.decide_status(m.confidence, th))
        m.note = "" if m.status == "completed" else "신뢰도가 낮아 확인이 필요합니다."
        db.commit()
    except Exception as exc:                      # 뒤에서 도는 일이 서비스를 죽이지 않는다
        db.rollback()
        try:
            m = db.get(ShortsMatch, match_id)
            if m:
                m.status = "failed"
                m.note = f"분석 중 오류: {exc}"[:400]
                db.commit()
        except Exception:
            pass
        print(f"[숏츠매칭] 실패 match_id={match_id}: {exc}", flush=True)
    finally:
        db.close()


def _audio_confidence(hit) -> float:
    """지문만으로 판단할 때의 신뢰도.

    표 수보다 **몰림의 뚜렷함**이 훨씬 잘 가른다 — 배경음악이 크게 깔린
    진짜 매칭이 표 278개, 아무 상관 없는 소리가 158개라 개수로는 못 가르지만,
    뚜렷함은 진짜 5~40배, 가짜 1.1배로 확연히 갈린다.
    """
    p = float(getattr(hit, "prominence", 0.0))
    return round(min(0.60 + min(p / 20.0, 1.0) * 0.39, 0.99), 4)


def run_fingerprint(video_id: int) -> None:
    """영상 하나의 오디오 지문을 만들어 저장한다. 뒤에서 돈다.

    1시간 영상이면 몇십 초 걸린다. 한 번 만들어 두면 그 롱폼에 붙는 숏츠가
    전부 재사용하므로, 영상을 올릴 때 미리 만들어 둔다.
    """
    from .database import SessionLocal
    db = SessionLocal()
    try:
        v = db.get(Video, video_id)
        if not v:
            return
        row = db.query(VideoFingerprint).filter(
            VideoFingerprint.video_id == video_id).first()
        if not row:
            row = VideoFingerprint(video_id=video_id)
            db.add(row)
        row.status = "processing"
        row.error = ""
        db.commit()

        path = _abs_path(v.file_path)
        if not path or not os.path.exists(path):
            row.status, row.error = "failed", "영상 파일이 없습니다."
            db.commit()
            return
        if not fp_mod.available():
            row.status, row.error = "failed", fp_mod.missing_reason()
            db.commit()
            return

        fp = fp_mod.build(path)
        if fp is None:
            row.status, row.error = "failed", "소리에서 지문을 만들지 못했습니다."
            db.commit()
            return
        row.data = fp.to_bytes()
        row.hash_count = fp.count
        row.frames = fp.frames
        row.status, row.error = "completed", ""
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"[지문] 실패 video_id={video_id}: {exc}", flush=True)
    finally:
        db.close()


def _load_fingerprint(db: Session, video_id: int):
    row = db.query(VideoFingerprint).filter(
        VideoFingerprint.video_id == video_id).first()
    if not row or row.status != "completed" or not row.data:
        return None
    return fp_mod.Fingerprint.from_bytes(row.data)


# ================================================================
# 관리자
# ================================================================
def _get_video(db: Session, video_id: int) -> Video:
    v = db.get(Video, video_id)
    if not v:
        raise HTTPException(status_code=404, detail="영상을 찾을 수 없습니다.")
    return v


def _ensure_match(db: Session, shorts: Video, longform_id: int) -> ShortsMatch:
    """숏츠↔롱폼 연결 행을 만들거나 가져온다."""
    lf = db.get(Video, longform_id)
    if not lf or lf.kind != "longform":
        raise HTTPException(status_code=400, detail="연결할 롱폼을 찾을 수 없습니다.")
    m = db.query(ShortsMatch).filter(ShortsMatch.shorts_id == shorts.id).first()
    if m:
        if m.longform_id != longform_id:
            # 롱폼을 바꾸면 예전 구간은 의미가 없다. 사람이 고친 값이라도
            # 다른 영상의 시각이므로 지우고 처음부터 다시 찾는다.
            m.longform_id = longform_id
            m.source_start_time = m.source_end_time = None
            m.status = "pending"
            m.manually_modified = m.manually_verified = False
            m.confidence = m.text_score = m.sequence_score = m.audio_score = None
        return m
    m = ShortsMatch(shorts_id=shorts.id, longform_id=longform_id, status="pending")
    db.add(m)
    db.flush()
    return m


@router.post("/admin/videos")
def create_video(payload: VideoIn, db: Session = Depends(get_db),
                 user: User = Depends(require_admin)):
    v = Video(kind=payload.kind, title=payload.title.strip(),
              description=payload.description, category=payload.category,
              is_public=payload.is_public, thumbnail=payload.thumbnail,
              created_by=user.id)
    db.add(v)
    db.flush()
    if payload.kind == "shorts" and payload.longform_id:
        _ensure_match(db, v, payload.longform_id)
    db.commit()
    db.refresh(v)
    return video_out(v, db, detail=True)


@router.get("/admin/videos")
def list_videos_admin(kind: Optional[str] = Query(None, pattern="^(longform|shorts)$"),
                      db: Session = Depends(get_db),
                      user: User = Depends(require_admin)):
    q = db.query(Video)
    if kind:
        q = q.filter(Video.kind == kind)
    rows = q.order_by(Video.created_at.desc()).all()
    out = [video_out(v) for v in rows]

    # 숏츠는 "어느 롱폼에 붙었는지"가 목록 자체에 실려야 한다.
    # 예전에는 롱폼 상세 안에서만 숏츠를 볼 수 있었는데, 그러면 롱폼을
    # 지운 순간 거기 붙어 있던 숏츠가 화면 어디에도 안 나와 지울 수조차
    # 없었다 — 연결만 끊겼을 뿐 영상 파일은 그대로 남아 있는데도.
    ids = [v.id for v in rows if v.kind == "shorts"]
    if ids:
        links = {}
        for m, title in (db.query(ShortsMatch, Video.title)
                         .outerjoin(Video, ShortsMatch.longform_id == Video.id)
                         .filter(ShortsMatch.shorts_id.in_(ids)).all()):
            links[m.shorts_id] = {
                "match_id": m.id, "longform_id": m.longform_id,
                "longform_title": title or "", "status": m.status,
                "confidence": m.confidence,
                "source_start_time": m.source_start_time,
                "source_end_time": m.source_end_time,
            }
        for o in out:
            if o["kind"] == "shorts":
                o["link"] = links.get(o["id"])
    return out


@router.get("/admin/videos/{video_id}")
def get_video_admin(video_id: int, db: Session = Depends(get_db),
                    user: User = Depends(require_admin)):
    return video_out(_get_video(db, video_id), db, detail=True)


@router.patch("/admin/videos/{video_id}")
def update_video(video_id: int, payload: VideoPatch, db: Session = Depends(get_db),
                 user: User = Depends(require_admin)):
    v = _get_video(db, video_id)
    data = payload.model_dump(exclude_unset=True)
    relink = "longform_id" in data
    longform_id = data.pop("longform_id", None)
    for field, value in data.items():
        setattr(v, field, value)
    if relink and v.kind == "shorts":
        if longform_id:
            _ensure_match(db, v, longform_id)
        else:
            # 일부러 null 을 보낸 것 — 잘못 붙였거나, 붙어 있던 롱폼이
            # 사라져 연결 껍데기만 남은 경우 떼어낸다.
            db.query(ShortsMatch).filter(
                ShortsMatch.shorts_id == v.id).delete(synchronize_session=False)
    db.commit()
    db.refresh(v)
    return video_out(v, db, detail=True)


def _purge_video(db: Session, v: Video) -> str:
    """영상 하나와 거기 달린 행들을 지우고, 지울 파일 경로를 돌려준다.

    이 프로젝트 모델에는 relationship 이 없어 지우는 순서를 우리가 지켜야
    한다(안 그러면 외래키 위반으로 500 이 난다). 파일은 커밋한 뒤에 지우므로
    여기서는 경로만 모아 돌려준다 — 되돌릴 수 없는 짓을 커밋보다 먼저 하면,
    커밋이 실패했을 때 행은 남고 파일만 사라진다.
    """
    db.query(ShortsMatch).filter(
        (ShortsMatch.shorts_id == v.id) | (ShortsMatch.longform_id == v.id)
    ).delete(synchronize_session=False)
    db.query(VideoFingerprint).filter(
        VideoFingerprint.video_id == v.id).delete(synchronize_session=False)
    path = _abs_path(v.file_path)
    db.delete(v)
    _forget_protected()
    return path


@router.delete("/admin/videos/{video_id}")
def delete_video(video_id: int,
                 with_shorts: bool = Query(False),
                 db: Session = Depends(get_db),
                 user: User = Depends(require_admin)):
    """영상을 지운다.

    롱폼은 with_shorts 로 딸린 숏츠까지 함께 지울지 고를 수 있다. 기본값은
    숏츠를 남기고 연결만 끊는 것 — 숏츠는 따로 올린 별개의 영상이라, 롱폼
    하나 지웠다고 덩달아 사라지면 곤란하다. 남은 숏츠는 목록의 숏츠 탭에
    "연결 안 됨"으로 그대로 보이므로 거기서 다시 붙이거나 지우면 된다.
    """
    v = _get_video(db, video_id)
    targets = [v]
    if v.kind == "longform" and with_shorts:
        ids = [row[0] for row in db.query(ShortsMatch.shorts_id).filter(
            ShortsMatch.longform_id == video_id).all()]
        if ids:
            targets += db.query(Video).filter(Video.id.in_(ids)).all()

    paths = [_purge_video(db, t) for t in targets]
    db.commit()
    for path in paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
    return {"ok": True, "deleted": len(targets)}


@router.post("/admin/videos/{video_id}/file")
def upload_video_file(video_id: int, background: BackgroundTasks,
                      file: UploadFile = File(...),
                      db: Session = Depends(get_db),
                      user: User = Depends(require_admin)):
    """영상 파일을 올린다.

    이미지처럼 file.read() 로 통째로 읽지 않는다. 1GB 영상을 메모리에 올리면
    gunicorn 워커가 그대로 죽는다. 조각내어 디스크로 흘려보낸다.
    """
    v = _get_video(db, video_id)
    ext = ALLOWED_VIDEO_TYPES.get((file.content_type or "").lower())
    if not ext:
        raise HTTPException(status_code=400, detail="MP4·MOV·M4V·WEBM 만 올릴 수 있습니다.")

    name = f"v{v.id}_{secrets.token_hex(8)}{ext}"
    dest = os.path.join(MEDIA_DIR, name)
    written = 0
    try:
        with open(dest, "wb") as out:
            while True:
                chunk = file.file.read(CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_VIDEO_BYTES:
                    raise HTTPException(
                        status_code=400,
                        detail=f"영상은 {max_video_label()} 이하만 올릴 수 있습니다.")
                out.write(chunk)
    except HTTPException:
        if os.path.exists(dest):
            os.remove(dest)
        raise
    if written == 0:
        os.remove(dest)
        raise HTTPException(status_code=400, detail="빈 파일입니다.")

    old = _abs_path(v.file_path)
    v.file_path = f"/api/media/{name}"
    _forget_protected()          # 파는 영상이면 새 파일 이름도 막혀야 한다
    v.size_bytes = written
    v.duration_sec = media_mod.probe_duration(dest) or v.duration_sec
    db.commit()
    if old and old != dest and os.path.exists(old):
        try:
            os.remove(old)
        except OSError:
            pass
    # 지문은 올리자마자 뒤에서 만들어 둔다. 나중에 숏츠가 붙을 때마다
    # 다시 만들면 그만큼 배로 걸린다.
    if fp_mod.available():
        background.add_task(run_fingerprint, v.id)

    return {"ok": True, "file_url": v.file_path, "size_bytes": written,
            "duration_sec": v.duration_sec,
            "fingerprint": fp_mod.available(),
            "note": "" if media_mod.have_ffprobe() else
                    "ffprobe 가 없어 영상 길이를 재지 못했습니다."}


@router.delete("/admin/videos/{video_id}/file")
def delete_video_file(video_id: int, db: Session = Depends(get_db),
                      user: User = Depends(require_admin)):
    """원본 파일만 지운다(디스크 회수).

    대본과 찾아 둔 구간은 남는다. 분석이 끝난 롱폼 원본은 용량이 크므로
    지워 자리를 비우되, 숏츠↔롱폼 연결은 그대로 쓰게 하려는 것이다.
    """
    v = _get_video(db, video_id)
    path = _abs_path(v.file_path)
    v.file_path = ""
    v.size_bytes = None
    db.commit()
    _forget_protected()
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
    return {"ok": True}


# ---------------------------------------------------------------- 대본
def _disk_free_mb() -> Optional[int]:
    try:
        return shutil.disk_usage(MEDIA_DIR).free // (1024 * 1024)
    except OSError:
        return None


@router.get("/admin/stt-status")
def stt_status(user: User = Depends(require_admin)):
    """구간 찾기가 지금 가능한 상태인지 알려 준다.

    이름이 stt-status 인 것은 예전에 자동 전사 상태를 알려 주던 자리라서다.
    화면 쪽 호출을 한꺼번에 바꾸지 않으려고 주소는 그대로 두었다.
    """
    return {
        "ffmpeg": media_mod.have_ffmpeg(),
        "ffmpeg_note": media_mod.missing_reason(),
        "fingerprint": fp_mod.available(),
        "fingerprint_note": fp_mod.missing_reason(),
        "max_video_mb": MAX_VIDEO_MB,
        "max_video_label": max_video_label(),
        # 남은 디스크도 함께 준다. "올릴 수 있는 크기"만 알려 주고 정작
        # 넣을 자리가 없으면, 몇 기가를 다 보낸 뒤에야 실패한다.
        "disk_free_mb": _disk_free_mb(),
    }


@router.post("/admin/videos/{video_id}/fingerprint")
def start_fingerprint(video_id: int, background: BackgroundTasks,
                      db: Session = Depends(get_db),
                      user: User = Depends(require_admin)):
    """지문을 다시 만든다(영상을 바꿨거나 예전에 실패했을 때)."""
    v = _get_video(db, video_id)
    if not v.file_path:
        raise HTTPException(status_code=400, detail="먼저 영상 파일을 올려주세요.")
    if not fp_mod.available():
        raise HTTPException(status_code=400, detail=fp_mod.missing_reason())
    background.add_task(run_fingerprint, v.id)
    return {"ok": True, "status": "processing"}


# ---------------------------------------------------------------- 매칭
@router.post("/admin/videos/{video_id}/match")
def start_match(video_id: int, background: BackgroundTasks,
                db: Session = Depends(get_db),
                user: User = Depends(require_admin)):
    """숏츠 하나의 원본 구간을 찾는다."""
    v = _get_video(db, video_id)
    if v.kind != "shorts":
        raise HTTPException(status_code=400, detail="숏츠만 분석할 수 있습니다.")
    m = db.query(ShortsMatch).filter(ShortsMatch.shorts_id == v.id).first()
    if not m:
        raise HTTPException(status_code=400, detail="연결할 롱폼을 먼저 지정해주세요.")
    m.status = "processing"
    db.commit()
    background.add_task(run_match, m.id)
    return {"ok": True, "status": "processing"}


@router.post("/admin/videos/{longform_id}/match-all")
def start_match_all(longform_id: int, background: BackgroundTasks,
                    db: Session = Depends(get_db),
                    user: User = Depends(require_admin)):
    """롱폼에 붙은 숏츠를 한꺼번에 분석한다.

    롱폼 대본은 DB 에 저장된 한 벌을 숏츠마다 다시 읽을 뿐, 다시 받아 적지
    않는다. 숏츠 30개라고 STT 를 30번 돌리면 시간도 돈도 30배가 된다.
    """
    lf = _get_video(db, longform_id)
    if lf.kind != "longform":
        raise HTTPException(status_code=400, detail="롱폼이 아닙니다.")
    rows = db.query(ShortsMatch).filter(ShortsMatch.longform_id == longform_id).all()
    queued = []
    for m in rows:
        if m.manually_modified:      # 사람이 고친 건 건드리지 않는다
            continue
        m.status = "processing"
        queued.append(m.id)
    db.commit()
    for mid in queued:
        background.add_task(run_match, mid)
    return {"ok": True, "queued": len(queued), "total": len(rows)}


@router.get("/admin/videos/{longform_id}/match-progress")
def match_progress(longform_id: int, db: Session = Depends(get_db),
                   user: User = Depends(require_admin)):
    """일괄 분석 진행률. 상태가 DB 에 있어 새로고침해도 그대로 이어진다."""
    rows = db.query(ShortsMatch).filter(ShortsMatch.longform_id == longform_id).all()
    total = len(rows)
    done = sum(1 for m in rows if m.status not in ("pending", "processing"))
    return {
        "total": total, "done": done,
        "percent": round(done / total * 100, 1) if total else 0.0,
        "by_status": {s: sum(1 for m in rows if m.status == s) for s in MATCH_STATUSES},
        "items": [match_out(m, db) for m in rows],
    }


@router.put("/admin/matches/{match_id}")
def edit_match(match_id: int, payload: MatchEditIn, db: Session = Depends(get_db),
               user: User = Depends(require_admin)):
    """관리자가 구간을 직접 고친다. 이후 재분석이 이 값을 덮어쓰지 않는다."""
    m = db.get(ShortsMatch, match_id)
    if not m:
        raise HTTPException(status_code=404, detail="분석 결과를 찾을 수 없습니다.")
    if payload.source_end_time <= payload.source_start_time:
        raise HTTPException(status_code=400, detail="종료 시각이 시작 시각보다 뒤여야 합니다.")
    lf = db.get(Video, m.longform_id)
    duration = lf.duration_sec if lf else None
    m.source_start_time = shorts_match.clamp(payload.source_start_time, duration)
    m.source_end_time = shorts_match.clamp(payload.source_end_time, duration)
    m.manually_modified = True
    m.manually_verified = True
    m.status = "confirmed"
    m.note = payload.note
    db.commit()
    return match_out(m, db)


@router.post("/admin/matches/{match_id}/confirm")
def confirm_match(match_id: int, db: Session = Depends(get_db),
                  user: User = Depends(require_admin)):
    """AI 가 찾은 구간을 그대로 확정한다."""
    m = db.get(ShortsMatch, match_id)
    if not m:
        raise HTTPException(status_code=404, detail="분석 결과를 찾을 수 없습니다.")
    if m.source_start_time is None:
        raise HTTPException(status_code=400, detail="확정할 구간이 없습니다.")
    m.manually_verified = True
    m.status = "confirmed"
    db.commit()
    return match_out(m, db)


class ThresholdsIn(BaseModel):
    """자동 확정 기준. 실제 영상으로 돌려 보기 전에는 어느 선이 맞는지 알 수
    없어서 관리자가 조정할 수 있게 둔다."""
    confirm: float = Field(ge=0.0, le=1.0)


@router.get("/admin/videos-thresholds")
def get_thresholds(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return _thresholds(db)


@router.put("/admin/videos-thresholds")
def set_thresholds(payload: ThresholdsIn, db: Session = Depends(get_db),
                   user: User = Depends(require_admin)):
    row = db.query(Setting).filter(Setting.key == "shorts_match_thresholds").first()
    if not row:
        row = Setting(key="shorts_match_thresholds")
        db.add(row)
    current = _thresholds(db)
    current["confirm"] = payload.confirm
    row.value = json.dumps(current)
    db.commit()
    return current


class VisibilityIn(BaseModel):
    public: bool


@router.put("/admin/videos-visibility")
def set_visibility(payload: VisibilityIn, db: Session = Depends(get_db),
                   user: User = Depends(require_admin)):
    row = db.query(Setting).filter(Setting.key == VIDEOS_PUBLIC_KEY).first()
    if not row:
        row = Setting(key=VIDEOS_PUBLIC_KEY)
        db.add(row)
    row.value = "true" if payload.public else "false"
    db.commit()
    return {"ok": True, "public": payload.public}


# ================================================================
# 공개 (학생·방문자)
# ================================================================
@router.get("/videos/visibility")
def get_visibility(db: Session = Depends(get_db)):
    """화면이 메뉴를 보여줄지 정하는 데 쓴다. 로그인 없이도 물어볼 수 있다."""
    return {"public": videos_public(db)}


@router.get("/videos")
def list_videos(kind: Optional[str] = Query(None, pattern="^(longform|shorts)$"),
                db: Session = Depends(get_db),
                user: Optional[User] = Depends(get_current_user_optional)):
    _guard_public(db, user)
    q = db.query(Video).filter(Video.is_public.is_(True))
    if kind:
        q = q.filter(Video.kind == kind)
    return [video_out(v) for v in q.order_by(Video.created_at.desc()).all()]


@router.get("/videos/{video_id}")
def get_video(video_id: int, db: Session = Depends(get_db),
              user: Optional[User] = Depends(get_current_user_optional)):
    _guard_public(db, user)
    v = db.get(Video, video_id)
    if not v or not v.is_public:
        raise HTTPException(status_code=404, detail="영상을 찾을 수 없습니다.")
    out = video_out(v, db, detail=True)

    if v.kind == "shorts":
        out.pop("match", None)
        m = db.query(ShortsMatch).filter(ShortsMatch.shorts_id == v.id).first()
        # 확정된 구간만 학생에게 보여준다. 애매한 추정으로 엉뚱한 데서
        # 재생을 시작하면 아무 연결도 없느니만 못하다.
        lf = db.get(Video, m.longform_id) if m else None
        usable = (m and m.status in ("confirmed", "completed")
                  and m.source_start_time is not None and lf and lf.is_public)
        out["source"] = ({
            "longform_id": lf.id, "longform_title": lf.title,
            "start": m.source_start_time, "end": m.source_end_time,
        } if usable else None)
    else:
        visible = [s for s in out.get("shorts", []) if s.get("is_public")]
        for s in visible:
            mm = s.pop("match", None)
            s["source_start_time"] = (mm or {}).get("source_start_time")
        out["shorts"] = visible
    return out


@router.post("/videos/{video_id}/view")
def count_view(video_id: int, db: Session = Depends(get_db),
               user: Optional[User] = Depends(get_current_user_optional)):
    _guard_public(db, user)
    v = db.get(Video, video_id)
    if v and v.is_public:
        v.view_count = (v.view_count or 0) + 1
        db.commit()
    return {"ok": True}
