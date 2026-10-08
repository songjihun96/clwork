"""기록해 공지사항 · 학교 계정 공지 알림 메일.

UDJ 공지와 **별개**다. 기록해 DB 에 저장하고, 기록해 관리자 화면에서 쓰고,
기록해 공지사항 화면에만 보인다(UDJ 와 주고받지 않는다).

알림 메일은 기록해의 **학교 계정**(중·고)에게만 보낸다. 학생·선생님 개인 계정에는
보내지 않는다. 받는 주소는 학교별 설정(diary_school_notice_settings)의 공지 알림
이메일, 비어 있으면 학교 계정 로그인 메일이다.

발송은 UDJ 와 같은 방식이다 — 게시하면 학교마다 발송 기록 한 줄(pending)을 만들고,
응답한 뒤 백그라운드에서 보낸다. 같은 공지·같은 학교는 한 줄뿐이라 다시 게시해도
두 번 나가지 않고, 실패해도 공지 게시는 그대로다. 실패한 건만 다시 보낸다.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import get_current_user_optional, require_admin, require_roles
from .database import SessionLocal, get_db
from .models import (DiaryNotice, DiaryNotificationLog, DiarySchoolNoticeSetting, Role,
                     User)

router = APIRouter(prefix="/api", tags=["notices"])

require_school = require_roles(Role.school)

CATEGORIES = {
    "notice": "공지", "update": "업데이트", "maintenance": "점검",
    "event": "이벤트", "important": "중요",
}
LEVELS = {"all": "전체 학교", "high": "고등학교", "middle": "중학교"}
STATUS_LABEL = {"pending": "대기", "sending": "발송 중", "sent": "성공",
                "failed": "실패", "cancelled": "보낼 수 없음"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
STUCK_AFTER = timedelta(minutes=10)
# 이벤트 공지는 메일을 보내지 않는다(게시판만). 영리 목적이 섞이면 광고성 정보가 되어
# 사전 수신 동의·'(광고)' 표시가 필요하다(정보통신망법 제50조) — 아예 보내지 않는다.
NO_SEND_CATEGORIES = ("event",)


def site_url() -> str:
    return (os.getenv("DIARY_SITE_URL", "") or "https://diary.ggm.kr").split("#", 1)[0].strip().rstrip("/")


def _now() -> datetime:
    return datetime.utcnow()


def visible_query(db: Session, admin: bool = False):
    q = db.query(DiaryNotice)
    if admin:
        return q
    now = _now()
    return q.filter(DiaryNotice.status == "published",
                    or_(DiaryNotice.starts_at.is_(None), DiaryNotice.starts_at <= now),
                    or_(DiaryNotice.ends_at.is_(None), DiaryNotice.ends_at >= now))


def notice_out(n: DiaryNotice, admin: bool = False) -> dict:
    out = {
        "id": n.id, "title": n.title, "body": n.body or "",
        "category": n.category, "category_label": CATEGORIES.get(n.category, "공지"),
        "is_important": bool(n.is_important), "status": n.status,
        "published_at": n.published_at or n.created_at,
        "starts_at": n.starts_at, "ends_at": n.ends_at, "created_at": n.created_at,
    }
    if admin:
        out.update({"target_level": n.target_level, "email_enabled": bool(n.email_enabled),
                    "updated_at": n.updated_at})
    return out


# ── 공개 ─────────────────────────────────────────────────
@router.get("/notices")
def list_notices(category: str = Query("", max_length=12),
                 page: int = Query(1, ge=1, le=500), size: int = Query(30, ge=1, le=100),
                 db: Session = Depends(get_db)):
    """공지사항 목록. 로그인하지 않아도 본다. 중요 공지가 위, 그다음 최신순."""
    q = visible_query(db)
    if category in CATEGORIES:
        q = q.filter(DiaryNotice.category == category)
    total = q.count()
    rows = (q.order_by(DiaryNotice.is_important.desc(),
                       func.coalesce(DiaryNotice.published_at, DiaryNotice.created_at).desc())
            .offset((page - 1) * size).limit(size).all())
    return {"items": [notice_out(n) for n in rows], "total": total, "page": page,
            "categories": [{"key": k, "label": v} for k, v in CATEGORIES.items()]}


@router.get("/notices/{notice_id}")
def get_notice(notice_id: int, db: Session = Depends(get_db),
               user: Optional[User] = Depends(get_current_user_optional)):
    admin = bool(user and user.role == Role.admin)
    n = visible_query(db, admin).filter(DiaryNotice.id == notice_id).first()
    if n is None:
        raise HTTPException(status_code=404, detail="공지를 찾을 수 없습니다.")
    return notice_out(n)


# ── 받는 곳 ──────────────────────────────────────────────
def mask_email(a: str) -> str:
    if "@" not in (a or ""):
        return a or ""
    local, dom = a.split("@", 1)
    return f"{local[:2]}***@{dom}"


def targets(db: Session, n: DiaryNotice) -> Tuple[List[dict], dict]:
    """학교 계정이 있는 학교마다 하나. 학교급은 그 학교 계정의 학교급(UDJ 가 정한 값)."""
    by_school: Dict[int, List[User]] = {}
    for u in db.query(User).filter(User.role == Role.school, User.school_id.isnot(None)).all():
        by_school.setdefault(u.school_id, []).append(u)
    settings = {s.school_id: s for s in db.query(DiarySchoolNoticeSetting).all()}
    out, stat = [], {"schools": 0, "inactive": 0, "opted_out": 0}
    for sid, users in sorted(by_school.items()):
        active = [u for u in users if u.is_active]
        level = (active or users)[0].school_level or "high"
        if n.target_level in ("high", "middle") and level != n.target_level:
            continue
        if not active:
            stat["inactive"] += 1
            continue
        st = settings.get(sid)
        if st is not None and not st.enabled:
            stat["opted_out"] += 1
            continue
        stat["schools"] += 1
        addr = ((st.notice_email if st else "") or "").strip() or active[0].email
        out.append({"target_key": f"school:{sid}", "school_id": sid,
                    "school_name": active[0].school_name or "", "address": addr})
    return out, stat


def _problem(addr: str) -> str:
    if not addr:
        return "이메일 주소 없음"
    if not EMAIL_RE.match(addr):
        return "잘못된 이메일 형식"
    return ""


def preview(db: Session, n: DiaryNotice) -> dict:
    if not n.email_enabled or n.category in NO_SEND_CATEGORIES:
        return {"schools": 0, "inactive": 0, "opted_out": 0, "email": 0, "email_unreachable": 0}
    ts, stat = targets(db, n)
    return {**stat, "email": sum(1 for t in ts if not _problem(t["address"])),
            "email_unreachable": sum(1 for t in ts if _problem(t["address"]))}


def enqueue(db: Session, n: DiaryNotice) -> int:
    if n.status != "published" or not n.email_enabled or n.category in NO_SEND_CATEGORIES:
        return 0
    ts, _ = targets(db, n)
    have = {k for (k,) in db.query(DiaryNotificationLog.target_key)
            .filter(DiaryNotificationLog.notice_id == n.id).all()}
    added = 0
    for t in ts:
        if t["target_key"] in have:
            continue
        why = _problem(t["address"])
        db.add(DiaryNotificationLog(notice_id=n.id, channel="email", target_key=t["target_key"],
                                    school_id=t["school_id"], school_name=t["school_name"][:120],
                                    address=t["address"][:120],
                                    status="cancelled" if why else "pending", error=why))
        added += 1
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return added


def email_parts(n: DiaryNotice, school_name: str) -> Tuple[str, str]:
    when = (n.published_at or n.created_at or _now()) + timedelta(hours=9)
    body = (n.body or "").strip()
    if len(body) > 2000:
        body = body[:2000] + "\n…(이하 생략 — 공지 상세에서 확인해 주세요)"
    url = site_url()
    text = (
        f"{school_name or '학교'} 담당자님, 안녕하세요.\n"
        f"기록해에 새 공지가 올라왔습니다.\n\n"
        f"■ {n.title}\n게시일: {when:%Y-%m-%d}\n\n{body}\n\n"
        f"공지 상세보기: {url}/notices/{n.id}\n"
        f"기록해 바로가기: {url}/\n\n"
        f"이 메일은 학교 계정의 공지 알림 설정에 따라 발송되었습니다. "
        f"알림을 끄려면 기록해 > 우리 학교 > 공지 알림 설정에서 바꿔 주세요."
    )
    return f"[기록해] {n.title}", text


def process(notice_id: Optional[int] = None, log_ids: Optional[List[int]] = None) -> dict:
    from . import mailer
    db = SessionLocal()
    done = {"sent": 0, "failed": 0}
    try:
        q = db.query(DiaryNotificationLog.id).filter(DiaryNotificationLog.status == "pending")
        if notice_id is not None:
            q = q.filter(DiaryNotificationLog.notice_id == notice_id)
        if log_ids:
            q = q.filter(DiaryNotificationLog.id.in_(log_ids))
        for (log_id,) in q.order_by(DiaryNotificationLog.id).all():
            claimed = db.execute(
                update(DiaryNotificationLog)
                .where(DiaryNotificationLog.id == log_id, DiaryNotificationLog.status == "pending")
                .values(status="sending", attempts=DiaryNotificationLog.attempts + 1,
                        updated_at=_now())).rowcount
            db.commit()
            if not claimed:
                continue
            row = db.get(DiaryNotificationLog, log_id)
            n = db.get(DiaryNotice, row.notice_id)
            try:
                if n is None:
                    ok, err = False, "공지가 지워졌습니다."
                else:
                    subject, body = email_parts(n, row.school_name)
                    ok, err = mailer.send(row.address, subject, body, from_name="기록해")
            except Exception as exc:
                ok, err = False, f"{type(exc).__name__}: {exc}"
            row.status = "sent" if ok else "failed"
            row.error = "" if ok else (err or "알 수 없는 오류")[:300]
            row.sent_at = _now() if ok else None
            db.commit()
            done["sent" if ok else "failed"] += 1
    except Exception as exc:
        print(f"[기록해 공지 알림] 발송 중 오류: {exc!r}", file=sys.stderr, flush=True)
    finally:
        db.close()
    return done


# ── 관리자 ───────────────────────────────────────────────
class NoticeIn(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    body: str = ""
    category: str = "notice"
    is_important: bool = False
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    target_level: str = "all"
    email_enabled: bool = False
    publish: bool = True


def _apply(n: DiaryNotice, p: NoticeIn) -> None:
    if p.category not in CATEGORIES:
        raise HTTPException(status_code=422, detail="알 수 없는 공지 유형입니다.")
    if p.target_level not in LEVELS:
        raise HTTPException(status_code=422, detail="알 수 없는 대상 학교급입니다.")
    if p.starts_at and p.ends_at and p.ends_at < p.starts_at:
        raise HTTPException(status_code=422, detail="종료일은 시작일보다 뒤여야 합니다.")
    n.title = p.title.strip()[:150]
    n.body = (p.body or "").strip()
    n.category = p.category
    n.is_important = bool(p.is_important)
    n.starts_at, n.ends_at = p.starts_at, p.ends_at
    n.target_level = p.target_level
    n.email_enabled = bool(p.email_enabled) and p.category not in NO_SEND_CATEGORIES


def _publish(db: Session, n: DiaryNotice, background: BackgroundTasks) -> int:
    if n.status != "published":
        n.status = "published"
        n.published_at = n.published_at or _now()
        db.commit()
    added = enqueue(db, n)
    background.add_task(process, n.id)
    return added


def _summary(db: Session, ids: List[int]) -> Dict[int, dict]:
    out: Dict[int, dict] = {}
    if not ids:
        return out
    for nid, st, cnt in (db.query(DiaryNotificationLog.notice_id, DiaryNotificationLog.status,
                                  func.count(DiaryNotificationLog.id))
                         .filter(DiaryNotificationLog.notice_id.in_(ids))
                         .group_by(DiaryNotificationLog.notice_id, DiaryNotificationLog.status).all()):
        out.setdefault(nid, {"email": {}})["email"][st] = cnt
    return out


def _get(db: Session, notice_id: int) -> DiaryNotice:
    n = db.get(DiaryNotice, notice_id)
    if n is None:
        raise HTTPException(status_code=404, detail="공지를 찾을 수 없습니다.")
    return n


@router.get("/admin/notices")
def admin_list(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    rows = db.query(DiaryNotice).order_by(DiaryNotice.created_at.desc()).limit(300).all()
    sums = _summary(db, [n.id for n in rows])
    return [{**notice_out(n, admin=True), "send": sums.get(n.id, {})} for n in rows]


@router.post("/admin/notices/preview")
def admin_preview(payload: NoticeIn, db: Session = Depends(get_db),
                  user: User = Depends(require_admin)):
    n = DiaryNotice(title=payload.title)
    _apply(n, payload)
    return preview(db, n)


@router.post("/admin/notices")
def admin_create(payload: NoticeIn, background: BackgroundTasks, db: Session = Depends(get_db),
                 user: User = Depends(require_admin)):
    n = DiaryNotice(author_id=user.id, title=payload.title, status="draft")
    _apply(n, payload)
    db.add(n)
    db.commit()
    db.refresh(n)
    queued = _publish(db, n, background) if payload.publish else 0
    return {**notice_out(n, admin=True), "queued": queued}


@router.put("/admin/notices/{notice_id}")
def admin_update(notice_id: int, payload: NoticeIn, background: BackgroundTasks,
                 db: Session = Depends(get_db), user: User = Depends(require_admin)):
    n = _get(db, notice_id)
    _apply(n, payload)
    db.commit()
    queued = _publish(db, n, background) if (payload.publish or n.status == "published") else 0
    return {**notice_out(n, admin=True), "queued": queued}


@router.post("/admin/notices/{notice_id}/publish")
def admin_publish(notice_id: int, background: BackgroundTasks, db: Session = Depends(get_db),
                  user: User = Depends(require_admin)):
    n = _get(db, notice_id)
    queued = _publish(db, n, background)
    return {**notice_out(n, admin=True), "queued": queued}


@router.post("/admin/notices/{notice_id}/unpublish")
def admin_unpublish(notice_id: int, db: Session = Depends(get_db),
                    user: User = Depends(require_admin)):
    n = _get(db, notice_id)
    n.status = "draft"
    db.query(DiaryNotificationLog).filter(DiaryNotificationLog.notice_id == n.id,
                                          DiaryNotificationLog.status == "pending").update(
        {DiaryNotificationLog.status: "cancelled", DiaryNotificationLog.error: "게시 취소"},
        synchronize_session=False)
    db.commit()
    return notice_out(n, admin=True)


@router.delete("/admin/notices/{notice_id}")
def admin_delete(notice_id: int, db: Session = Depends(get_db),
                 user: User = Depends(require_admin)):
    n = _get(db, notice_id)
    db.query(DiaryNotificationLog).filter(DiaryNotificationLog.notice_id == n.id).delete(
        synchronize_session=False)
    db.delete(n)
    db.commit()
    return {"ok": True}


def _log_out(r: DiaryNotificationLog) -> dict:
    return {"id": r.id, "notice_id": r.notice_id, "channel": r.channel, "school_id": r.school_id,
            "school_name": r.school_name or "", "address": mask_email(r.address),
            "status": r.status, "status_label": STATUS_LABEL.get(r.status, r.status),
            "error": r.error or "", "attempts": r.attempts or 0, "sent_at": r.sent_at,
            "created_at": r.created_at}


@router.get("/admin/notices/{notice_id}/logs")
def admin_logs(notice_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    rows = (db.query(DiaryNotificationLog).filter(DiaryNotificationLog.notice_id == notice_id)
            .order_by(DiaryNotificationLog.school_name).all())
    return [_log_out(r) for r in rows]


def _reset(db: Session, q) -> List[int]:
    ids = []
    for r in q.all():
        stuck = r.status == "sending" and (r.updated_at or r.created_at) < _now() - STUCK_AFTER
        if r.status != "failed" and not stuck:
            continue
        st = db.get(DiarySchoolNoticeSetting, r.school_id) if r.school_id else None
        if st is not None and (st.notice_email or "").strip():
            r.address = st.notice_email.strip()[:120]
        r.status, r.error = "pending", ""
        ids.append(r.id)
    db.commit()
    return ids


@router.post("/admin/notification-logs/{log_id}/retry")
def admin_retry_one(log_id: int, background: BackgroundTasks, db: Session = Depends(get_db),
                    user: User = Depends(require_admin)):
    r = db.get(DiaryNotificationLog, log_id)
    if r is None:
        raise HTTPException(status_code=404, detail="발송 기록을 찾을 수 없습니다.")
    if r.status == "sent":
        raise HTTPException(status_code=409, detail="이미 보낸 건입니다. 중복 발송은 하지 않습니다.")
    ids = _reset(db, db.query(DiaryNotificationLog).filter(DiaryNotificationLog.id == log_id))
    if not ids:
        raise HTTPException(status_code=409, detail="실패한 건만 다시 보낼 수 있습니다.")
    background.add_task(process, None, ids)
    return {"ok": True, "queued": len(ids)}


@router.post("/admin/notices/{notice_id}/retry-failed")
def admin_retry_failed(notice_id: int, background: BackgroundTasks,
                       db: Session = Depends(get_db), user: User = Depends(require_admin)):
    ids = _reset(db, db.query(DiaryNotificationLog).filter(DiaryNotificationLog.notice_id == notice_id))
    if ids:
        background.add_task(process, None, ids)
    return {"ok": True, "queued": len(ids)}


# ── 학교 계정: 공지 알림 설정 ─────────────────────────────
class SettingsIn(BaseModel):
    notice_email: str = Field("", max_length=120)
    enabled: bool = True


def _settings_out(db: Session, user: User) -> dict:
    st = db.get(DiarySchoolNoticeSetting, user.school_id)
    return {"school_id": user.school_id, "school_name": user.school_name or "",
            "school_level": user.school_level or "high",
            "notice_email": (st.notice_email if st else "") or "",
            "enabled": bool(st.enabled) if st else True,
            "fallback_email": user.email}


def _my_school(user: User) -> None:
    if not user.school_id:
        raise HTTPException(status_code=400, detail="계정에 연결된 학교가 없습니다.")


@router.get("/school/notification-settings")
def get_settings(db: Session = Depends(get_db), user: User = Depends(require_school)):
    _my_school(user)
    return _settings_out(db, user)


@router.put("/school/notification-settings")
def put_settings(payload: SettingsIn, db: Session = Depends(get_db),
                 user: User = Depends(require_school)):
    _my_school(user)
    email = payload.notice_email.strip()
    if email and not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="공지 알림 이메일 형식이 올바르지 않습니다.")
    st = db.get(DiarySchoolNoticeSetting, user.school_id)
    if st is None:
        st = DiarySchoolNoticeSetting(school_id=user.school_id)
        db.add(st)
    st.notice_email = email
    st.enabled = bool(payload.enabled)
    db.commit()
    return _settings_out(db, user)
