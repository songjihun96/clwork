"""UDJ 공지사항 · 공지 알림 · 우리동네직업계고 담당 선생님 공지.

**두 갈래**
  · board      : 공지사항 게시판. 사이트 공지를 올리고, 원하면 학교 계정(중·고)이
                 정해 둔 '공지 알림 이메일'로 알린다.
  · vocational : 우리동네직업계고 공지. 직업계고(고등학교)의 담당 선생님에게
                 메일·문자로 보낸다. 중학교는 대상이 아니다.

기록해 공지는 이것과 **별개**다(기록해 DB·기록해 관리자 화면). 여기에는 서비스
구분 칸을 두지 않는다.

**발송 흐름** — 게시 요청 안에서 메일·문자를 보내지 않는다.
    게시 → 받을 곳마다 NotificationLog(pending) 한 줄 → 응답 → 백그라운드에서 발송
같은 공지·같은 받는 곳·같은 수단은 표의 유일 제약 때문에 한 줄뿐이라, 다시 게시하거나
새로고침해도 두 번 나가지 않는다. 실패는 기록만 하고 공지 게시는 그대로 둔다.
실패한 줄만 관리자가 다시 보낼 수 있다.

**수신 동의**(2026-10-08)
  · 담당 선생님은 공지 수신(개인정보 수집·이용) 동의가 있어야 보낸다(consent_at).
    동의가 없으면 '수신 동의 없음'으로 기록만 남고 나가지 않는다.
  · '이벤트' 유형 공지는 광고성 정보가 될 수 있어 메일·문자를 보내지 않는다(게시판만).

**개인정보** — 관리자 화면에는 주소를 가려서 보여 준다(ab***@x.kr, 010-****-1234).
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import (get_current_user, get_current_user_optional, require_admin,
                   require_school_any, school_level_of)
from .database import SessionLocal, get_db
from .models import (Notice, NoticeRead, NotificationLog, Role, School, SchoolContact,
                     User)

router = APIRouter(prefix="/api", tags=["notices"])

KINDS = ("board", "vocational")
CATEGORIES = {
    "notice": "공지", "update": "업데이트", "maintenance": "점검",
    "event": "이벤트", "important": "중요",
}
LEVELS = {"all": "전체 학교", "high": "고등학교", "middle": "중학교"}
STATUS_LABEL = {"pending": "대기", "sending": "발송 중", "sent": "성공",
                "failed": "실패", "cancelled": "보낼 수 없음"}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^01[016789]\d{7,8}$")
SMS_MAX_BYTES = 90          # 단문(SMS) 한도. sms.py 가 단문으로 보낸다.
STUCK_AFTER = timedelta(minutes=10)
# 메일·문자를 보내지 않는 유형. 이벤트는 영리 목적이 섞이면 광고성 정보(정보통신망법
# 제50조: 사전 수신 동의·'(광고)' 표시 필요)가 되므로 아예 보내지 않는다.
NO_SEND_CATEGORIES = ("event",)


def site_url() -> str:
    return (os.getenv("PUBLIC_SITE_URL", "") or "https://udjschool.ggm.kr").split("#", 1)[0].strip().rstrip("/")


# ══════════════════════════════════════════════════════════════
#  보이는 범위
# ══════════════════════════════════════════════════════════════
def _now() -> datetime:
    return datetime.utcnow()


def visible_query(db: Session, user: Optional[User]):
    """이 사람에게 보이는 게시 공지. 기간·게시 상태·대상을 모두 반영한다."""
    now = _now()
    q = db.query(Notice).filter(
        Notice.status == "published",
        or_(Notice.starts_at.is_(None), Notice.starts_at <= now),
        or_(Notice.ends_at.is_(None), Notice.ends_at >= now),
    )
    board = [and_(Notice.kind == "board", Notice.scope == "all")]
    if user is not None and user.role == Role.admin:
        return q
    if user is not None and user.role == Role.school and user.school_id:
        board.append(and_(Notice.kind == "board", Notice.scope == "school",
                          Notice.school_id == user.school_id))
        # 우리동네직업계고 공지는 고등학교 학교 계정에게도 보인다(메일을 놓쳤을 때).
        if school_level_of(user) == "high":
            board.append(Notice.kind == "vocational")
    return q.filter(or_(*board))


def can_view(db: Session, n: Notice, user: Optional[User]) -> bool:
    return visible_query(db, user).filter(Notice.id == n.id).first() is not None


def notice_out(n: Notice, read: bool = False, admin: bool = False) -> dict:
    out = {
        "id": n.id,
        "kind": n.kind or "board",
        "scope": n.scope,
        "school_id": n.school_id,
        "school_name": n.school.name if n.school else "",
        "title": n.title,
        "body": n.body or "",
        "image_url": n.image_url or "",
        "category": n.category or "notice",
        "category_label": CATEGORIES.get(n.category or "notice", "공지"),
        "is_popup": bool(n.is_popup),
        "is_important": bool(n.is_important),
        "status": n.status or "published",
        # 예전 공지는 게시 시각 칸이 없다 — 작성 시각을 게시 시각으로 본다.
        "published_at": n.published_at or n.created_at,
        "starts_at": n.starts_at,
        "ends_at": n.ends_at,
        "created_at": n.created_at,
        "is_read": read,
    }
    if admin:
        out.update({
            "author_name": n.author.name if n.author else "",
            "target_level": n.target_level or "all",
            "email_enabled": bool(n.email_enabled),
            "sms_enabled": bool(n.sms_enabled),
            "updated_at": n.updated_at,
        })
    return out


# ══════════════════════════════════════════════════════════════
#  공개 API
# ══════════════════════════════════════════════════════════════
@router.get("/notices")
def list_notices(
    category: str = Query("", max_length=12),
    kind: str = Query("", max_length=12),
    page: int = Query(1, ge=1, le=500),
    size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """내게 보이는 공지. 중요 공지를 위에, 그다음 최신순.
    머리의 종 모양(안 읽은 수·팝업)과 공지사항 화면이 함께 쓴다."""
    q = visible_query(db, user)
    if category in CATEGORIES:
        q = q.filter(Notice.category == category)
    if kind in KINDS:
        q = q.filter(Notice.kind == kind)
    total = q.count()
    rows = (q.order_by(Notice.is_important.desc(),
                       func.coalesce(Notice.published_at, Notice.created_at).desc())
            .offset((page - 1) * size).limit(size).all())
    read_ids = set()
    if user is not None and rows:
        read_ids = {r.notice_id for r in db.query(NoticeRead).filter(
            NoticeRead.user_id == user.id,
            NoticeRead.notice_id.in_([n.id for n in rows])).all()}
    items = [notice_out(n, n.id in read_ids) for n in rows]
    return {
        "items": items,
        "total": total,
        "page": page,
        "unread": sum(1 for i in items if not i["is_read"]),
        "popups": [i for i in items if i["is_popup"]],
        "categories": [{"key": k, "label": v} for k, v in CATEGORIES.items()],
    }


@router.get("/notices/{notice_id}")
def get_notice(notice_id: int, db: Session = Depends(get_db),
               user: Optional[User] = Depends(get_current_user_optional)):
    n = db.get(Notice, notice_id)
    if n is None or not can_view(db, n, user):
        raise HTTPException(status_code=404, detail="공지를 찾을 수 없습니다.")
    return notice_out(n)


@router.post("/notices/{notice_id}/read")
def mark_read(notice_id: int, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    if not db.get(Notice, notice_id):
        raise HTTPException(status_code=404, detail="공지를 찾을 수 없습니다.")
    if not db.query(NoticeRead).filter(NoticeRead.notice_id == notice_id,
                                       NoticeRead.user_id == user.id).first():
        db.add(NoticeRead(notice_id=notice_id, user_id=user.id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    return {"ok": True}


# ══════════════════════════════════════════════════════════════
#  받는 곳 고르기
# ══════════════════════════════════════════════════════════════
def mask_email(a: str) -> str:
    if "@" not in (a or ""):
        return a or ""
    local, dom = a.split("@", 1)
    return f"{local[:2]}***@{dom}"


def mask_phone(p: str) -> str:
    d = re.sub(r"\D", "", p or "")
    return f"{d[:3]}-****-{d[-4:]}" if len(d) >= 8 else ("" if not d else "***")


def _school_accounts(db: Session) -> Dict[int, List[User]]:
    out: Dict[int, List[User]] = {}
    for u in db.query(User).filter(User.role == Role.school, User.school_id.isnot(None)).all():
        out.setdefault(u.school_id, []).append(u)
    return out


def board_targets(db: Session, n: Notice) -> Tuple[List[dict], dict]:
    """게시판 공지 메일 대상: 학교 계정이 있는 학교의 '공지 알림 이메일'.
    학생·선생님 개인 계정은 대상이 아니다. (대상들, 집계)"""
    accounts = _school_accounts(db)
    q = db.query(School).filter(School.id.in_(list(accounts) or [-1]))
    level = n.target_level or "all"
    if level in ("high", "middle"):
        q = q.filter(School.school_level == level)
    if n.scope == "school" and n.school_id:
        q = q.filter(School.id == n.school_id)
    targets, stat = [], {"schools": 0, "inactive": 0, "opted_out": 0}
    for s in q.order_by(School.name).all():
        active = [u for u in accounts.get(s.id, []) if u.is_active]
        if not active:
            stat["inactive"] += 1           # 계정이 모두 정지된 학교
            continue
        if not s.notice_email_enabled:
            stat["opted_out"] += 1          # 학교가 알림을 끈 경우
            continue
        stat["schools"] += 1
        addr = (s.notice_email or "").strip() or active[0].email
        targets.append({"channel": "email", "recipient_type": "school_account",
                        "target_key": f"school:{s.id}", "school_id": s.id,
                        "contact_id": None, "address": addr, "school_name": s.name})
    return targets, stat


def vocational_targets(db: Session, n: Notice) -> Tuple[List[dict], dict]:
    """우리동네직업계고 공지 대상: 노출 중인 고등학교의 담당 선생님(주 담당자)."""
    schools = {s.id: s for s in db.query(School).filter(
        School.school_level == "high", School.is_visible.is_(True)).all()}
    contacts = (db.query(SchoolContact)
                .filter(SchoolContact.role == "udj_contact",
                        SchoolContact.is_primary.is_(True),
                        SchoolContact.school_id.in_(list(schools) or [-1]))
                .order_by(SchoolContact.school_id).all())
    targets, stat = [], {"schools": 0, "contacts": 0, "inactive": 0, "no_consent": 0}
    seen = set()
    for c in contacts:
        if not c.is_active:
            stat["inactive"] += 1
            continue
        if c.school_id in seen:
            continue                         # 주 담당자가 둘 적혀 있으면 앞사람만
        seen.add(c.school_id)
        base = {"recipient_type": "udj_contact", "target_key": f"contact:{c.id}",
                "school_id": c.school_id, "contact_id": c.id,
                "school_name": schools[c.school_id].name,
                # 동의가 없으면 보내지 않고 까닭만 기록한다.
                "blocked": "" if c.consent_at else "수신 동의 없음"}
        if c.consent_at:
            stat["contacts"] += 1
        else:
            stat["no_consent"] += 1
        if n.email_enabled:
            targets.append({**base, "channel": "email", "address": (c.email or "").strip()})
        if n.sms_enabled:
            targets.append({**base, "channel": "sms",
                            "address": re.sub(r"\D", "", c.phone or "")})
    stat["schools"] = stat["contacts"]
    return targets, stat


def build_targets(db: Session, n: Notice) -> Tuple[List[dict], dict]:
    if (n.category or "notice") in NO_SEND_CATEGORIES:
        return [], {"schools": 0, "contacts": 0, "inactive": 0, "no_consent": 0, "opted_out": 0}
    if n.kind == "vocational":
        if not (n.email_enabled or n.sms_enabled):
            return [], {"schools": 0, "contacts": 0, "inactive": 0}
        return vocational_targets(db, n)
    if not n.email_enabled:
        return [], {"schools": 0, "inactive": 0, "opted_out": 0}
    return board_targets(db, n)


def _problem(t: dict) -> str:
    """보낼 수 없는 대상이면 그 까닭. 보낼 수 있으면 빈 문자열."""
    if t.get("blocked"):
        return t["blocked"]
    a = t["address"]
    if t["channel"] == "email":
        if not a:
            return "이메일 주소 없음"
        if not EMAIL_RE.match(a):
            return "잘못된 이메일 형식"
    else:
        if not a:
            return "휴대폰 번호 없음"
        if not PHONE_RE.match(a):
            return "잘못된 휴대폰 번호"
    return ""


def preview(db: Session, n: Notice) -> dict:
    targets, stat = build_targets(db, n)
    email = [t for t in targets if t["channel"] == "email"]
    sms = [t for t in targets if t["channel"] == "sms"]
    unreachable = lambda ts: sum(1 for t in ts if _problem(t) and not t.get("blocked"))  # noqa: E731
    return {
        **stat,
        "email": sum(1 for t in email if not _problem(t)),
        "email_unreachable": unreachable(email),
        "sms": sum(1 for t in sms if not _problem(t)),
        "sms_unreachable": unreachable(sms),
        "blocked_category": (n.category or "notice") in NO_SEND_CATEGORIES,
    }


def enqueue(db: Session, n: Notice) -> int:
    """받을 곳마다 한 줄. 이미 줄이 있는 곳(보냈거나 보내는 중)은 건너뛴다 → 중복 없음.
    보낼 수 없는 곳(주소 없음 등)은 cancelled 로 남겨 관리자가 까닭을 보게 한다."""
    if n.status != "published":
        return 0
    targets, _ = build_targets(db, n)
    have = {(r.channel, r.target_key): r for r in db.query(NotificationLog)
            .filter(NotificationLog.notice_id == n.id).all()}
    added = 0
    for t in targets:
        why = _problem(t)
        old = have.get((t["channel"], t["target_key"]))
        if old is not None:
            # 한 번도 나가지 않은 줄(동의 없음·주소 없음·게시 취소)은 이제 보낼 수 있으면 되살린다.
            # 보냈거나 보내는 중·실패한 줄은 건드리지 않는다(중복 발송 방지, 실패는 재발송으로).
            if old.status == "cancelled" and not why:
                old.address, old.status, old.error = t["address"][:120], "pending", ""
                added += 1
            continue
        db.add(NotificationLog(
            notice_id=n.id, channel=t["channel"], recipient_type=t["recipient_type"],
            target_key=t["target_key"], school_id=t["school_id"], contact_id=t["contact_id"],
            address=t["address"][:120], status="cancelled" if why else "pending", error=why))
        added += 1
    try:
        db.commit()
    except IntegrityError:
        # 동시에 두 번 게시한 경우. 유일 제약이 막았으니 이미 들어간 것으로 충분하다.
        db.rollback()
    return added


# ══════════════════════════════════════════════════════════════
#  보내기
# ══════════════════════════════════════════════════════════════
def _fit_bytes(text: str, limit: int) -> str:
    out = ""
    for ch in text:
        if len((out + ch).encode("euc-kr", errors="replace")) > limit:
            break
        out += ch
    return out


def sms_text(n: Notice) -> str:
    head = "[우리동네직업계고] 새 공지: "
    tail = " (메일 확인)"
    room = SMS_MAX_BYTES - len((head + tail).encode("euc-kr", errors="replace"))
    title = n.title.strip()
    cut = _fit_bytes(title, room)
    if cut != title:
        cut = _fit_bytes(title, room - 2) + ".."
    return head + cut + tail


def email_parts(n: Notice, school_name: str) -> Tuple[str, str]:
    prefix = "[우리동네직업계고]" if n.kind == "vocational" else "[UDJ]"
    when = (n.published_at or n.created_at or _now()) + timedelta(hours=9)
    body = (n.body or "").strip()
    if len(body) > 2000:
        body = body[:2000] + "\n…(이하 생략 — 공지 상세에서 확인해 주세요)"
    url = site_url()
    text = (
        f"{school_name} 담당자님, 안녕하세요.\n"
        f"우리동네 직업계고에 새 공지가 올라왔습니다.\n\n"
        f"■ {n.title}\n"
        f"게시일: {when:%Y-%m-%d}\n\n"
        f"{body}\n\n"
        f"공지 상세보기: {url}/notices/{n.id}\n"
        f"우리동네 직업계고 바로가기: {url}/\n\n"
        f"이 메일은 학교 계정의 공지 알림 설정에 따라 발송되었습니다."
        + (" 알림을 끄려면 학교 관리 > 공지 알림 설정에서 바꿔 주세요." if n.kind == "board"
           else " 담당자가 바뀌었다면 학교 관리 > 공지 알림 설정에서 고쳐 주세요.")
    )
    return f"{prefix} {n.title}", text


def _send_one(db: Session, row: NotificationLog, n: Notice) -> Tuple[bool, str]:
    from . import mailer, sms
    if row.channel == "email":
        cfg = mailer.system_config()
        if not cfg.is_ready():
            return False, "메일 발송 설정(SMTP_*)이 없습니다."
        s = db.get(School, row.school_id) if row.school_id else None
        subject, body = email_parts(n, s.name if s else "학교")
        return mailer.send_email(cfg, row.address, subject, body, from_name="우리동네 직업계고")
    return sms.send_sms(row.address, sms_text(n))


def process(notice_id: Optional[int] = None, log_ids: Optional[List[int]] = None) -> dict:
    """pending 줄을 하나씩 '집어서' 보낸다. 집기는 조건부 UPDATE 라 여러 프로세스가
    동시에 돌아도 한 줄을 두 번 보내지 않는다. 백그라운드에서 부른다."""
    db = SessionLocal()
    done = {"sent": 0, "failed": 0}
    try:
        q = db.query(NotificationLog.id).filter(NotificationLog.status == "pending")
        if notice_id is not None:
            q = q.filter(NotificationLog.notice_id == notice_id)
        if log_ids:
            q = q.filter(NotificationLog.id.in_(log_ids))
        for (log_id,) in q.order_by(NotificationLog.id).all():
            claimed = db.execute(
                update(NotificationLog)
                .where(NotificationLog.id == log_id, NotificationLog.status == "pending")
                .values(status="sending", attempts=NotificationLog.attempts + 1,
                        updated_at=_now())).rowcount
            db.commit()
            if not claimed:
                continue
            row = db.get(NotificationLog, log_id)
            n = db.get(Notice, row.notice_id)
            try:
                ok, err = _send_one(db, row, n) if n else (False, "공지가 지워졌습니다.")
            except Exception as exc:     # 한 건이 실패해도 나머지는 계속 보낸다
                ok, err = False, f"{type(exc).__name__}: {exc}"
            row.status = "sent" if ok else "failed"
            row.error = "" if ok else (err or "알 수 없는 오류")[:300]
            row.sent_at = _now() if ok else None
            db.commit()
            done["sent" if ok else "failed"] += 1
    except Exception as exc:
        print(f"[공지 알림] 발송 중 오류: {exc!r}", file=sys.stderr, flush=True)
    finally:
        db.close()
    return done


def summary(db: Session, notice_ids: List[int]) -> Dict[int, dict]:
    out: Dict[int, dict] = {}
    if not notice_ids:
        return out
    for nid, ch, st, cnt in (db.query(NotificationLog.notice_id, NotificationLog.channel,
                                      NotificationLog.status, func.count(NotificationLog.id))
                             .filter(NotificationLog.notice_id.in_(notice_ids))
                             .group_by(NotificationLog.notice_id, NotificationLog.channel,
                                       NotificationLog.status).all()):
        out.setdefault(nid, {}).setdefault(ch, {})[st] = cnt
    return out


# ══════════════════════════════════════════════════════════════
#  관리자
# ══════════════════════════════════════════════════════════════
class NoticeIn(BaseModel):
    kind: str = "board"
    scope: str = "all"                   # board 만: all | school
    school_id: Optional[int] = None
    title: str = Field(min_length=1, max_length=150)
    body: str = ""
    image_url: str = Field("", max_length=300)
    category: str = "notice"
    is_popup: bool = False
    is_important: bool = False
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    target_level: str = "all"
    email_enabled: bool = False
    sms_enabled: bool = False
    publish: bool = True                 # false = 임시저장


def _apply(db: Session, n: Notice, p: NoticeIn) -> None:
    if p.kind not in KINDS:
        raise HTTPException(status_code=422, detail="알 수 없는 공지 종류입니다.")
    if p.category not in CATEGORIES:
        raise HTTPException(status_code=422, detail="알 수 없는 공지 유형입니다.")
    if p.target_level not in LEVELS:
        raise HTTPException(status_code=422, detail="알 수 없는 대상 학교급입니다.")
    if p.starts_at and p.ends_at and p.ends_at < p.starts_at:
        raise HTTPException(status_code=422, detail="종료일은 시작일보다 뒤여야 합니다.")
    scope, school_id = "all", None
    if p.kind == "board":
        if p.scope not in ("all", "school"):
            raise HTTPException(status_code=422, detail="scope는 all 또는 school 이어야 합니다.")
        scope = p.scope
        if scope == "school":
            if not p.school_id or not db.get(School, p.school_id):
                raise HTTPException(status_code=400, detail="대상 학교를 선택해주세요.")
            school_id = p.school_id
    n.kind = p.kind
    n.scope = scope
    n.school_id = school_id
    n.title = p.title.strip()[:150]
    n.body = (p.body or "").strip()
    n.image_url = (p.image_url or "").strip()[:300]
    n.category = p.category
    n.is_popup = bool(p.is_popup) and p.kind == "board" and scope == "all"
    n.is_important = bool(p.is_important)
    n.starts_at = p.starts_at
    n.ends_at = p.ends_at
    # 직업계고 공지는 고등학교 담당 선생님 대상이라 학교급 선택이 없다.
    n.target_level = "high" if p.kind == "vocational" else p.target_level
    no_send = p.category in NO_SEND_CATEGORIES      # 이벤트: 게시판에만 올린다
    n.email_enabled = bool(p.email_enabled) and not no_send
    # 문자는 우리동네직업계고 공지에서만 쓴다(학교 계정 알림은 메일만).
    n.sms_enabled = bool(p.sms_enabled) and p.kind == "vocational" and not no_send


def _publish(db: Session, n: Notice, background: BackgroundTasks) -> int:
    if n.status != "published":
        n.status = "published"
        n.published_at = n.published_at or _now()
        db.commit()
    added = enqueue(db, n)
    background.add_task(process, n.id)
    return added


@router.get("/admin/notices")
def admin_list(kind: str = Query("", max_length=12), db: Session = Depends(get_db),
               user: User = Depends(require_admin)):
    q = db.query(Notice)
    if kind in KINDS:
        q = q.filter(Notice.kind == kind)
    rows = q.order_by(Notice.created_at.desc()).limit(300).all()
    sums = summary(db, [n.id for n in rows])
    return [{**notice_out(n, admin=True), "send": sums.get(n.id, {})} for n in rows]


@router.post("/admin/notices/preview")
def admin_preview(payload: NoticeIn, db: Session = Depends(get_db),
                  user: User = Depends(require_admin)):
    """게시 전에 몇 곳에 나가는지. 저장하지 않는다."""
    n = Notice(title=payload.title or "-")
    _apply(db, n, payload)
    return preview(db, n)


@router.get("/admin/notices/{notice_id}/preview")
def admin_preview_saved(notice_id: int, db: Session = Depends(get_db),
                        user: User = Depends(require_admin)):
    n = db.get(Notice, notice_id)
    if n is None:
        raise HTTPException(status_code=404, detail="공지를 찾을 수 없습니다.")
    return preview(db, n)


@router.post("/admin/notices")
def admin_create(payload: NoticeIn, background: BackgroundTasks,
                 db: Session = Depends(get_db), user: User = Depends(require_admin)):
    n = Notice(author_id=user.id, title=payload.title, status="draft")
    _apply(db, n, payload)
    db.add(n)
    db.commit()
    db.refresh(n)
    queued = _publish(db, n, background) if payload.publish else 0
    return {**notice_out(n, admin=True), "queued": queued}


@router.put("/admin/notices/{notice_id}")
def admin_update(notice_id: int, payload: NoticeIn, background: BackgroundTasks,
                 db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """고친다. 게시 중이면 그대로 게시 상태를 유지하고, 새로 생긴 받는 곳에만
    보낸다(이미 받은 곳은 줄이 있어 다시 안 나간다)."""
    n = db.get(Notice, notice_id)
    if n is None:
        raise HTTPException(status_code=404, detail="공지를 찾을 수 없습니다.")
    if n.kind != payload.kind:
        raise HTTPException(status_code=422, detail="공지 종류는 바꿀 수 없습니다.")
    _apply(db, n, payload)
    db.commit()
    queued = 0
    if payload.publish or n.status == "published":
        queued = _publish(db, n, background)
    return {**notice_out(n, admin=True), "queued": queued}


@router.post("/admin/notices/{notice_id}/publish")
def admin_publish(notice_id: int, background: BackgroundTasks,
                  db: Session = Depends(get_db), user: User = Depends(require_admin)):
    n = db.get(Notice, notice_id)
    if n is None:
        raise HTTPException(status_code=404, detail="공지를 찾을 수 없습니다.")
    queued = _publish(db, n, background)
    return {**notice_out(n, admin=True), "queued": queued}


@router.post("/admin/notices/{notice_id}/unpublish")
def admin_unpublish(notice_id: int, db: Session = Depends(get_db),
                    user: User = Depends(require_admin)):
    """게시 취소. 아직 안 나간 알림(pending)은 취소한다 — 이미 나간 건 되돌릴 수 없다."""
    n = db.get(Notice, notice_id)
    if n is None:
        raise HTTPException(status_code=404, detail="공지를 찾을 수 없습니다.")
    n.status = "draft"
    db.query(NotificationLog).filter(NotificationLog.notice_id == n.id,
                                     NotificationLog.status == "pending").update(
        {NotificationLog.status: "cancelled", NotificationLog.error: "게시 취소"},
        synchronize_session=False)
    db.commit()
    return notice_out(n, admin=True)


@router.delete("/admin/notices/{notice_id}")
def admin_delete(notice_id: int, db: Session = Depends(get_db),
                 user: User = Depends(require_admin)):
    n = db.get(Notice, notice_id)
    if n is None:
        raise HTTPException(status_code=404, detail="공지를 찾을 수 없습니다.")
    db.query(NoticeRead).filter(NoticeRead.notice_id == notice_id).delete(synchronize_session=False)
    db.query(NotificationLog).filter(NotificationLog.notice_id == notice_id).delete(
        synchronize_session=False)
    db.delete(n)
    db.commit()
    return {"ok": True}


def _log_out(r: NotificationLog, names: Dict[int, str]) -> dict:
    return {
        "id": r.id, "notice_id": r.notice_id, "channel": r.channel,
        "recipient_type": r.recipient_type, "school_id": r.school_id,
        "school_name": names.get(r.school_id, ""),
        "address": mask_email(r.address) if r.channel == "email" else mask_phone(r.address),
        "status": r.status, "status_label": STATUS_LABEL.get(r.status, r.status),
        "error": r.error or "", "attempts": r.attempts or 0,
        "sent_at": r.sent_at, "created_at": r.created_at,
    }


def _names(db: Session, rows) -> Dict[int, str]:
    ids = {r.school_id for r in rows if r.school_id}
    return {s.id: s.name for s in db.query(School).filter(School.id.in_(ids or [-1])).all()}


@router.get("/admin/notices/{notice_id}/logs")
def admin_logs(notice_id: int, db: Session = Depends(get_db),
               user: User = Depends(require_admin)):
    rows = (db.query(NotificationLog).filter(NotificationLog.notice_id == notice_id)
            .order_by(NotificationLog.school_id, NotificationLog.channel).all())
    names = _names(db, rows)
    return [_log_out(r, names) for r in rows]


@router.get("/admin/notification-logs")
def admin_all_logs(status: str = Query("", max_length=10), db: Session = Depends(get_db),
                   user: User = Depends(require_admin)):
    q = db.query(NotificationLog)
    if status in STATUS_LABEL:
        q = q.filter(NotificationLog.status == status)
    rows = q.order_by(NotificationLog.created_at.desc()).limit(300).all()
    names = _names(db, rows)
    return [_log_out(r, names) for r in rows]


def _reset_for_retry(db: Session, q) -> List[int]:
    """실패한 줄(과 오래 '보내는 중'에 멈춘 줄)을 다시 pending 으로. 주소는 지금
    담당자 정보로 새로 읽는다 — 주소가 틀려서 실패했다면 고친 뒤 다시 보내기 때문."""
    ids = []
    for r in q.all():
        stuck = r.status == "sending" and (r.updated_at or r.created_at) < _now() - STUCK_AFTER
        if r.status != "failed" and not stuck:
            continue
        if r.contact_id:
            c = db.get(SchoolContact, r.contact_id)
            if c is not None:
                r.address = (c.email if r.channel == "email" else re.sub(r"\D", "", c.phone or ""))[:120]
        elif r.school_id and r.channel == "email":
            s = db.get(School, r.school_id)
            if s is not None and (s.notice_email or "").strip():
                r.address = s.notice_email.strip()[:120]
        r.status, r.error = "pending", ""
        ids.append(r.id)
    db.commit()
    return ids


@router.post("/admin/notification-logs/{log_id}/retry")
def admin_retry_one(log_id: int, background: BackgroundTasks, db: Session = Depends(get_db),
                    user: User = Depends(require_admin)):
    r = db.get(NotificationLog, log_id)
    if r is None:
        raise HTTPException(status_code=404, detail="발송 기록을 찾을 수 없습니다.")
    if r.status == "sent":
        raise HTTPException(status_code=409, detail="이미 보낸 건입니다. 중복 발송은 하지 않습니다.")
    ids = _reset_for_retry(db, db.query(NotificationLog).filter(NotificationLog.id == log_id))
    if not ids:
        raise HTTPException(status_code=409, detail="실패한 건만 다시 보낼 수 있습니다.")
    background.add_task(process, None, ids)
    return {"ok": True, "queued": len(ids)}


@router.post("/admin/notices/{notice_id}/retry-failed")
def admin_retry_failed(notice_id: int, background: BackgroundTasks,
                       db: Session = Depends(get_db), user: User = Depends(require_admin)):
    ids = _reset_for_retry(db, db.query(NotificationLog).filter(
        NotificationLog.notice_id == notice_id))
    if ids:
        background.add_task(process, None, ids)
    return {"ok": True, "queued": len(ids)}


# ══════════════════════════════════════════════════════════════
#  학교 계정: 공지 알림 설정 · 담당 선생님
# ══════════════════════════════════════════════════════════════
class ContactIn(BaseModel):
    name: str = Field("", max_length=40)
    position: str = Field("", max_length=40)
    email: str = Field("", max_length=120)
    phone: str = Field("", max_length=30)
    is_active: bool = True
    # 공지 수신(이메일·문자) 개인정보 수집·이용 동의. 끄면 동의를 거둔 것으로 보고 안 보낸다.
    consent: bool = False


class SettingsIn(BaseModel):
    notice_email: str = Field("", max_length=120)
    notice_email_enabled: bool = True
    contact: Optional[ContactIn] = None


def primary_contact(db: Session, school_id: int) -> Optional[SchoolContact]:
    return (db.query(SchoolContact)
            .filter(SchoolContact.school_id == school_id, SchoolContact.role == "udj_contact",
                    SchoolContact.is_primary.is_(True))
            .order_by(SchoolContact.id).first())


def contact_out(c: Optional[SchoolContact]) -> Optional[dict]:
    if c is None:
        return None
    return {"id": c.id, "name": c.name, "position": c.position or "", "email": c.email or "",
            "phone": c.phone or "", "is_active": bool(c.is_active), "updated_at": c.updated_at,
            "consent": c.consent_at is not None, "consent_at": c.consent_at,
            "consent_source": c.consent_source or ""}


CONTACT_CONSENT_TEXT = {
    "items": "담당 선생님 이름·직위·이메일·휴대폰",
    "purpose": "우리동네 직업계고 운영 공지(학교 인터뷰 촬영·행사·서비스 안내 등)를 이메일과 문자로 보내기 위해 이용합니다. 광고성 정보는 보내지 않습니다.",
    "retention": "담당자 변경 또는 동의 철회 시까지",
    "right_to_refuse": "동의하지 않으면 공지를 이메일·문자로 받지 않습니다. 공지는 학교 관리 화면에서 볼 수 있습니다.",
}


def save_contact(db: Session, school_id: int, p: ContactIn, source: str = "school") -> SchoolContact:
    email = p.email.strip()
    phone = p.phone.strip()
    if email and not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="담당 선생님 이메일 형식이 올바르지 않습니다.")
    if phone and not PHONE_RE.match(re.sub(r"\D", "", phone)):
        raise HTTPException(status_code=422, detail="담당 선생님 휴대폰 번호 형식이 올바르지 않습니다.")
    c = primary_contact(db, school_id)
    if c is None:
        c = SchoolContact(school_id=school_id, role="udj_contact", is_primary=True)
        db.add(c)
    c.name = p.name.strip()
    c.position = p.position.strip()
    changed = (c.email or "") != email or re.sub(r"\D", "", c.phone or "") != re.sub(r"\D", "", phone)
    c.email = email
    c.phone = phone
    c.is_active = bool(p.is_active)
    if not p.consent:
        c.consent_at, c.consent_source = None, ""          # 철회 또는 미동의
    elif c.consent_at is None or changed:
        # 새로 동의했거나 연락처가 바뀌었다(바뀐 연락처는 그 사람의 새 동의로 본다).
        c.consent_at, c.consent_source = _now(), source
    return c


def _settings_out(db: Session, s: School) -> dict:
    accounts = [u.email for u in (s.accounts or []) if u.role == Role.school and u.is_active]
    out = {
        "school_id": s.id, "school_name": s.name, "school_level": s.school_level or "high",
        "notice_email": s.notice_email or "",
        "notice_email_enabled": bool(s.notice_email_enabled),
        # 비워 두면 이 주소로 간다. 화면에서 알려 준다.
        "fallback_email": accounts[0] if accounts else "",
    }
    if (s.school_level or "high") == "high":
        out["contact"] = contact_out(primary_contact(db, s.id))
        out["contact_consent_text"] = CONTACT_CONSENT_TEXT
    return out


@router.get("/school/notification-settings")
def get_settings(db: Session = Depends(get_db), user: User = Depends(require_school_any)):
    s = db.get(School, user.school_id) if user.school_id else None
    if s is None:
        raise HTTPException(status_code=400, detail="계정에 연결된 학교가 없습니다.")
    return _settings_out(db, s)


@router.put("/school/notification-settings")
def put_settings(payload: SettingsIn, db: Session = Depends(get_db),
                 user: User = Depends(require_school_any)):
    s = db.get(School, user.school_id) if user.school_id else None
    if s is None:
        raise HTTPException(status_code=400, detail="계정에 연결된 학교가 없습니다.")
    email = payload.notice_email.strip()
    if email and not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="공지 알림 이메일 형식이 올바르지 않습니다.")
    s.notice_email = email
    s.notice_email_enabled = bool(payload.notice_email_enabled)
    if payload.contact is not None:
        # 담당 선생님(우리동네직업계고 공지 수신)은 고등학교만 둔다.
        if (s.school_level or "high") != "high":
            raise HTTPException(status_code=403, detail="담당 선생님 등록은 고등학교 학교 계정만 할 수 있습니다.")
        save_contact(db, s.id, payload.contact, source="school")
    db.commit()
    return _settings_out(db, s)


# ══════════════════════════════════════════════════════════════
#  관리자: 학교급 · 담당 선생님 · 학교 계정 목록
# ══════════════════════════════════════════════════════════════
class LevelIn(BaseModel):
    school_level: str


@router.put("/admin/schools/{school_id}/school-level")
def admin_set_level(school_id: int, payload: LevelIn, db: Session = Depends(get_db),
                    user: User = Depends(require_admin)):
    s = db.get(School, school_id)
    if s is None:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")
    if payload.school_level not in ("high", "middle"):
        raise HTTPException(status_code=422, detail="학교급은 high 또는 middle 입니다.")
    s.school_level = payload.school_level
    if payload.school_level == "middle":
        # 중학교는 직업계고 공개 목록에 나오지 않는다.
        s.is_visible = False
    db.commit()
    return {"id": s.id, "school_level": s.school_level, "is_visible": bool(s.is_visible)}


@router.get("/admin/schools/{school_id}/contact")
def admin_get_contact(school_id: int, db: Session = Depends(get_db),
                      user: User = Depends(require_admin)):
    if db.get(School, school_id) is None:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")
    return {"contact": contact_out(primary_contact(db, school_id))}


@router.put("/admin/schools/{school_id}/contact")
def admin_put_contact(school_id: int, payload: ContactIn, db: Session = Depends(get_db),
                      user: User = Depends(require_admin)):
    s = db.get(School, school_id)
    if s is None:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")
    if (s.school_level or "high") != "high":
        raise HTTPException(status_code=422, detail="담당 선생님은 고등학교에만 둡니다.")
    # 관리자가 고칠 때 consent=True 는 '담당 선생님 본인에게 동의를 받았음을 확인'했다는 뜻이다.
    c = save_contact(db, school_id, payload, source="admin")
    db.commit()
    return {"contact": contact_out(c)}


@router.get("/admin/school-accounts")
def admin_school_accounts(
    level: str = Query("", max_length=10),
    status: str = Query("", max_length=10),
    q: str = Query("", max_length=60),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """학교 계정 목록. 학교급(중·고)·이용 상태(이용중/이용중지)·검색(학교명·학교코드·
    담당자명·이메일)으로 거른다. 승인 대기·승인 완료는 학교 계정 신청 목록에서 본다."""
    qy = db.query(User, School).join(School, School.id == User.school_id).filter(
        User.role == Role.school)
    if level in ("high", "middle"):
        qy = qy.filter(School.school_level == level)
    if status == "active":
        qy = qy.filter(User.is_active.is_(True))
    elif status == "inactive":
        qy = qy.filter(User.is_active.is_(False))
    if q.strip():
        like = f"%{q.strip()}%"
        qy = qy.filter(or_(School.name.ilike(like), School.school_code.ilike(like),
                           User.name.ilike(like), User.email.ilike(like)))
    rows = qy.order_by(School.name).limit(500).all()
    counts = dict(db.query(School.school_level, func.count(User.id))
                  .join(User, User.school_id == School.id)
                  .filter(User.role == Role.school).group_by(School.school_level).all())
    return {
        "items": [{
            "user_id": u.id, "email": u.email, "manager_name": u.name,
            "is_active": bool(u.is_active), "school_id": s.id, "school_name": s.name,
            "school_code": s.school_code or "", "region": s.region,
            "school_level": s.school_level or "high",
            "notice_email": s.notice_email or "", "created_at": u.created_at,
        } for u, s in rows],
        "counts": {"high": counts.get("high", 0), "middle": counts.get("middle", 0)},
    }
