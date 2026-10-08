"""사이트 방문자 수 — 화면 아래에 "오늘 · 누적"으로 보여 준다.

**세는 법.** 브라우저가 처음 열릴 때 한 번 `POST /api/visit` 을 부른다.
브라우저는 자기만의 임의 값(visitor_id)을 localStorage 에 두고 같이 보낸다.
하루에 같은 값은 한 번만 센다.

  · IP 로 세지 않는 이유 — 학교 와이파이는 반 전체가 IP 하나다. IP 로 세면
    한 반이 한 명이 된다.
  · 대신 IP 하나가 하루에 새 방문자를 끝없이 만들지 못하게 막는다
    (MAX_NEW_PER_IP). 숫자를 부풀리려고 값을 바꿔 가며 부르는 걸 막는다.
  · 봇은 대부분 스크립트를 안 돌리므로 여기까지 오지 않는다. 와도 UA 로 거른다.

**감시 도구(monitor.py)의 접속자 수와는 다르다.** 그쪽은 nginx 로그로 "지금
몇 명"을 보는 운영용이고, 이건 방문객에게 보여 주는 누적 숫자다. 로그는
2주 뒤 지워지므로 누적을 거기서 낼 수 없다.

누적 시작값은 관리자가 Setting `visit_base` 에 넣을 수 있다(이 기능을 넣기
전의 방문을 더해 두고 싶을 때).
"""

from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timedelta, date
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import SECRET_KEY, require_admin
from .database import get_db
from .models import Setting, SiteVisitDay, SiteVisitSeen, User

router = APIRouter(prefix="/api", tags=["visits"])

KST = timedelta(hours=9)
MAX_NEW_PER_IP = 200
BASE_KEY = "visit_base"

_BOT = re.compile(
    r"bot|crawl|spider|slurp|yeti|daum|facebookexternalhit|embedly|preview|"
    r"headless|lighthouse|monitor|uptime|scanner|python|curl|wget|httpclient",
    re.I,
)

# 합계는 한 번 셀 때마다 전체 표를 더하지 않도록 잠깐 기억한다(워커별).
_TOTAL = {"value": None, "at": 0.0}
_TOTAL_TTL = 30.0


def today_kst() -> date:
    return (datetime.utcnow() + KST).date()


def _hash(*parts: str) -> str:
    raw = "|".join(parts) + "|" + SECRET_KEY
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _base(db: Session) -> int:
    row = db.get(Setting, BASE_KEY)
    try:
        return max(int((row.value if row else "0") or 0), 0)
    except ValueError:
        return 0


def stats(db: Session) -> dict:
    today = today_kst()
    row = db.get(SiteVisitDay, today)
    now = time.time()
    if _TOTAL["value"] is None or now - _TOTAL["at"] > _TOTAL_TTL:
        _TOTAL["value"] = int(db.query(func.coalesce(func.sum(SiteVisitDay.count), 0)).scalar() or 0)
        _TOTAL["at"] = now
    return {"today": int(row.count if row else 0),
            "total": _TOTAL["value"] + _base(db)}


class VisitIn(BaseModel):
    visitor_id: str = Field(default="", max_length=80)


@router.post("/visit")
def record_visit(payload: VisitIn, request: Request, db: Session = Depends(get_db)):
    ua = request.headers.get("user-agent", "")
    vid = (payload.visitor_id or "").strip()
    if vid and ua and not _BOT.search(ua):
        _count(db, vid, _client_ip(request))
    return stats(db)


@router.get("/visit-stats")
def get_visit_stats(db: Session = Depends(get_db)):
    return stats(db)


def _count(db: Session, visitor_id: str, ip: str) -> None:
    today = today_kst()
    key = _hash("v", visitor_id)
    ip_key = _hash("ip", ip, today.isoformat())
    if db.query(SiteVisitSeen.id).filter(SiteVisitSeen.day == today,
                                         SiteVisitSeen.visitor_key == key).first():
        return
    new_from_ip = db.query(func.count(SiteVisitSeen.id)).filter(
        SiteVisitSeen.day == today, SiteVisitSeen.ip_key == ip_key).scalar() or 0
    if new_from_ip >= MAX_NEW_PER_IP:
        return
    try:
        db.add(SiteVisitSeen(day=today, visitor_key=key, ip_key=ip_key))
        db.flush()
    except IntegrityError:
        # 같은 사람이 탭 두 개를 동시에 열었다 — 다른 요청이 이미 셌다.
        db.rollback()
        return
    # 워커가 여럿이라 읽고 더해 쓰면 동시에 들어온 방문이 사라진다.
    # UPDATE count = count + 1 로 DB 가 더하게 한다.
    updated = (db.query(SiteVisitDay).filter(SiteVisitDay.day == today)
               .update({SiteVisitDay.count: SiteVisitDay.count + 1},
                       synchronize_session=False))
    if not updated:
        db.add(SiteVisitDay(day=today, count=1))
    try:
        db.commit()
    except IntegrityError:
        # 오늘 첫 방문 두 개가 동시에 표를 만들려 했다. 다시 더한다.
        db.rollback()
        try:
            db.add(SiteVisitSeen(day=today, visitor_key=key, ip_key=ip_key))
            db.flush()
            db.query(SiteVisitDay).filter(SiteVisitDay.day == today).update(
                {SiteVisitDay.count: SiteVisitDay.count + 1}, synchronize_session=False)
            db.commit()
        except IntegrityError:
            db.rollback()     # 같은 사람이 동시에 두 번 — 한 번은 이미 셌다
            return
    if _TOTAL["value"] is not None:
        _TOTAL["value"] += 1
    # 이틀 지난 "이미 셌다" 기록은 필요 없다.
    db.query(SiteVisitSeen).filter(SiteVisitSeen.day < today - timedelta(days=1)).delete(
        synchronize_session=False)
    db.commit()


# ---------------------------------------------------------------- 관리
class BaseIn(BaseModel):
    base: int = Field(..., ge=0, le=1_000_000_000)


@router.get("/admin/visit-stats")
def admin_visit_stats(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    rows = (db.query(SiteVisitDay).order_by(SiteVisitDay.day.desc()).limit(30).all())
    return {**stats(db), "base": _base(db),
            "days": [{"day": r.day.isoformat(), "count": r.count} for r in rows]}


@router.put("/admin/visit-stats")
def admin_set_base(payload: BaseIn, db: Session = Depends(get_db),
                   user: User = Depends(require_admin)):
    row = db.get(Setting, BASE_KEY)
    if row is None:
        db.add(Setting(key=BASE_KEY, value=str(payload.base)))
    else:
        row.value = str(payload.base)
    db.commit()
    return admin_visit_stats(db, user)
