"""전화 상담 API.

기존 상담 사이트(cs.py)와 같은 관문을 쓴다. 접두사도 /api/cs 를 유지한다.
그래야 사무실 IP·기기승인·감사로그가 전화 화면에도 그대로 걸린다. 전화만
따로 열어두면 가장 민감한 화면이 가장 허술해진다.

고객 개인정보(이름·전화·이메일)는 목록에서 가려서 준다. 통화 중인 상담원의
화면처럼 실제 값이 필요한 자리에서만 reveal 을 요청하고, 그 사실을 감사로그에
남긴다.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
)
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .. import phone as phone_pkg
from ..cs import audit, mask_email, require_cs, require_cs_admin
from ..database import SessionLocal, get_db
from ..models import (
    AVAILABILITY_STATUSES,
    CALL_CLOSED_STATUSES,
    CONSULTATION_CHANNELS,
    CONSULTATION_PRIORITIES,
    CONSULTATION_STATUSES,
    CUSTOMER_TYPES,
    CsCallLog,
    CsCallSession,
    CsConsultation,
    CsCounselorProfile,
    CsCustomer,
    CsInquiryType,
    Role,
    School,
    Setting,
    User,
)
from . import engine, hub, intake, options, sounds, voice
from .phones import format_phone, is_valid_phone, mask_phone, normalize_phone, phone_variants

log = logging.getLogger("callcenter.api")

router = APIRouter(prefix="/api/cs", tags=["cs-phone"])


# ── 직렬화 ────────────────────────────────────────────────────


def customer_row(c: CsCustomer, reveal: bool = False) -> dict:
    return {
        "id": c.id,
        "name": c.name or "",
        "phone_number": format_phone(c.phone_number) if reveal else mask_phone(c.phone_number),
        "email": (c.email or "") if reveal else mask_email(c.email or ""),
        "customer_type": c.customer_type,
        "school_name": c.school_name or "",
        "school_id": c.school_id,
        "user_id": c.user_id,
        "memo": c.memo or "",
        "masked": not reveal,
        "created_at": iso_utc(c.created_at),
        "updated_at": iso_utc(c.updated_at),
    }


def consultation_row(x: CsConsultation, counselor_name: str = "",
                     customer_name: str = "", type_name: str = "") -> dict:
    return {
        "id": x.id,
        "customer_id": x.customer_id,
        "customer_name": customer_name,
        "counselor_id": x.counselor_id,
        "counselor_name": counselor_name,
        "call_log_id": x.call_log_id,
        "channel": x.channel,
        "inquiry_type_id": x.inquiry_type_id,
        "inquiry_type_name": type_name,
        "subject": x.subject or "",
        "content": x.content or "",
        "result": x.result or "",
        "status": x.status,
        "priority": x.priority,
        "started_at": iso_utc(x.started_at),
        "ended_at": iso_utc(x.ended_at),
        "created_at": iso_utc(x.created_at),
    }


def call_row(c: CsCallLog, reveal: bool = False, counselor_name: str = "",
             customer_name: str = "") -> dict:
    return {
        "id": c.id,
        "provider": c.provider,
        "external_call_id": c.external_call_id or "",
        "customer_id": c.customer_id,
        "customer_name": customer_name,
        "counselor_id": c.counselor_id,
        "counselor_name": counselor_name,
        "phone_number": format_phone(c.phone_number) if reveal else mask_phone(c.phone_number),
        "direction": c.direction,
        "status": c.status,
        "started_at": iso_utc(c.started_at),
        "answered_at": iso_utc(c.answered_at),
        "ended_at": iso_utc(c.ended_at),
        "duration_seconds": c.duration_seconds or 0,
        "recording_url": c.recording_url or "",
    }


def iso_utc(dt) -> Optional[str]:
    """UTC 라고 못 박아서 내보낸다.

    서버는 datetime.utcnow() 로 시각을 만든다. 그런데 .isoformat() 은 시간대
    표시가 없는 문자열을 준다. 브라우저의 new Date() 는 그런 값을 **현지시각**
    으로 읽으므로, 한국(UTC+9)에서는 통화 시간이 9시간으로 나온다.

    그래서 전화 관련 시각은 끝에 Z 를 붙여 UTC 임을 밝힌다. 통화 시간처럼
    초를 다투는 값에서는 이 한 글자가 화면의 진위를 가른다.
    """
    if dt is None:
        return None
    return dt.isoformat() + "Z"


def _names(db: Session, user_ids) -> dict:
    ids = {i for i in user_ids if i}
    if not ids:
        return {}
    return {u.id: u.name for u in db.query(User).filter(User.id.in_(ids)).all()}


# ══════════════════════════════════════════════════════════════
#  고객
# ══════════════════════════════════════════════════════════════


class CustomerIn(BaseModel):
    name: str = Field("", max_length=60)
    phone_number: str = Field(..., max_length=30)
    email: str = Field("", max_length=120)
    customer_type: str = "OTHER"
    school_name: str = Field("", max_length=120)
    school_id: Optional[int] = None
    memo: str = ""


@router.get("/customers")
def list_customers(
    q: str = "",
    customer_type: str = "",
    limit: int = Query(30, le=200),
    offset: int = 0,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    query = db.query(CsCustomer)
    if q.strip():
        term = q.strip()
        # 전화번호로 찾을 때는 표기가 달라도 걸리도록 후보를 넓힌다.
        variants = phone_variants(term)
        conds = [CsCustomer.name.ilike(f"%{term}%"), CsCustomer.school_name.ilike(f"%{term}%")]
        for v in variants:
            conds.append(CsCustomer.phone_number.like(f"%{v}%"))
        query = query.filter(or_(*conds))
    if customer_type in CUSTOMER_TYPES:
        query = query.filter(CsCustomer.customer_type == customer_type)

    total = query.count()
    rows = query.order_by(CsCustomer.updated_at.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [customer_row(c) for c in rows]}


@router.get("/customers/lookup")
def lookup_customer(
    phone: str,
    request: Request,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    """발신번호로 고객을 찾는다. 전화가 울리는 순간 화면이 부르는 API.

    통화 중에는 가리지 않은 번호가 필요하다. 대신 누가 언제 열어봤는지 남긴다.
    """
    normalized = normalize_phone(phone)
    if not normalized:
        raise HTTPException(status_code=400, detail="전화번호가 올바르지 않습니다.")

    row = db.query(CsCustomer).filter(CsCustomer.phone_number == normalized).first()
    if row is None:
        # 예전에 정규화 없이 들어간 값이 남아 있을 수 있어 한 번 더 훑는다.
        for v in phone_variants(normalized):
            row = db.query(CsCustomer).filter(CsCustomer.phone_number == v).first()
            if row is not None:
                break

    if row is None:
        return {"found": False, "phone_number": format_phone(normalized),
                "raw_phone": normalized, "customer": None}

    audit(db, request, user, "cs.customer_lookup", "cs_customer", row.id, "통화 중 조회")
    stats = _customer_stats(db, row.id)
    return {"found": True, "phone_number": format_phone(normalized),
            "raw_phone": normalized, "customer": customer_row(row, reveal=True), **stats}


def _customer_stats(db: Session, customer_id: int) -> dict:
    total = db.query(func.count(CsConsultation.id)).filter(
        CsConsultation.customer_id == customer_id).scalar() or 0
    open_count = db.query(func.count(CsConsultation.id)).filter(
        CsConsultation.customer_id == customer_id,
        CsConsultation.status.in_(options.open_statuses(db))).scalar() or 0
    last = db.query(CsConsultation.created_at).filter(
        CsConsultation.customer_id == customer_id).order_by(
        CsConsultation.created_at.desc()).first()
    calls = db.query(func.count(CsCallLog.id)).filter(
        CsCallLog.customer_id == customer_id).scalar() or 0
    return {
        "consultation_count": total,
        "open_consultation_count": open_count,
        "last_consulted_at": iso_utc(last[0]) if last else None,
        "call_count": calls,
    }


@router.post("/customers")
def create_customer(
    payload: CustomerIn,
    request: Request,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    if not is_valid_phone(payload.phone_number):
        raise HTTPException(status_code=400, detail="전화번호가 올바르지 않습니다.")
    if payload.customer_type not in CUSTOMER_TYPES:
        raise HTTPException(status_code=400, detail="고객 유형이 올바르지 않습니다.")

    normalized = normalize_phone(payload.phone_number)
    existing = db.query(CsCustomer).filter(CsCustomer.phone_number == normalized).first()
    if existing is not None:
        # 같은 번호로 두 고객을 만들면 다음 전화 때 어느 쪽을 띄울지 알 수 없다.
        raise HTTPException(status_code=409, detail="이미 등록된 전화번호입니다.")

    school_name = payload.school_name.strip()
    if payload.school_id and not school_name:
        school = db.get(School, payload.school_id)
        school_name = school.name if school else ""

    row = CsCustomer(
        name=payload.name.strip(),
        phone_number=normalized,
        email=payload.email.strip(),
        customer_type=payload.customer_type,
        school_name=school_name,
        school_id=payload.school_id,
        memo=payload.memo.strip(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    audit(db, request, user, "cs.customer_create", "cs_customer", row.id, row.name or "이름 없음")
    return customer_row(row, reveal=True)


@router.get("/customers/{customer_id}")
def get_customer(
    customer_id: int,
    request: Request,
    reveal: bool = False,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    row = db.get(CsCustomer, customer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="고객을 찾을 수 없습니다.")
    if reveal:
        audit(db, request, user, "cs.customer_reveal", "cs_customer", row.id, "원문 열람")
    return {**customer_row(row, reveal=reveal), **_customer_stats(db, row.id)}


@router.put("/customers/{customer_id}")
def update_customer(
    customer_id: int,
    payload: CustomerIn,
    request: Request,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    row = db.get(CsCustomer, customer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="고객을 찾을 수 없습니다.")
    if not is_valid_phone(payload.phone_number):
        raise HTTPException(status_code=400, detail="전화번호가 올바르지 않습니다.")
    if payload.customer_type not in CUSTOMER_TYPES:
        raise HTTPException(status_code=400, detail="고객 유형이 올바르지 않습니다.")

    normalized = normalize_phone(payload.phone_number)
    clash = db.query(CsCustomer).filter(
        CsCustomer.phone_number == normalized, CsCustomer.id != customer_id).first()
    if clash is not None:
        raise HTTPException(status_code=409, detail="다른 고객이 쓰는 전화번호입니다.")

    row.name = payload.name.strip()
    row.phone_number = normalized
    row.email = payload.email.strip()
    row.customer_type = payload.customer_type
    row.school_name = payload.school_name.strip()
    row.school_id = payload.school_id
    row.memo = payload.memo.strip()
    db.commit()
    audit(db, request, user, "cs.customer_update", "cs_customer", row.id, row.name or "")
    return customer_row(row, reveal=True)


@router.get("/customers/{customer_id}/consultations")
def customer_consultations(
    customer_id: int,
    limit: int = Query(30, le=200),
    offset: int = 0,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    query = db.query(CsConsultation).filter(CsConsultation.customer_id == customer_id)
    total = query.count()
    rows = query.order_by(CsConsultation.created_at.desc()).offset(offset).limit(limit).all()
    names = _names(db, [r.counselor_id for r in rows])
    types = {t.id: t.name for t in db.query(CsInquiryType).all()}
    return {
        "total": total,
        "items": [
            consultation_row(r, names.get(r.counselor_id, ""), "", types.get(r.inquiry_type_id, ""))
            for r in rows
        ],
    }


@router.get("/customers/{customer_id}/call-logs")
def customer_call_logs(
    customer_id: int,
    limit: int = Query(30, le=200),
    offset: int = 0,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    query = db.query(CsCallLog).filter(CsCallLog.customer_id == customer_id)
    total = query.count()
    rows = query.order_by(CsCallLog.started_at.desc()).offset(offset).limit(limit).all()
    names = _names(db, [r.counselor_id for r in rows])
    return {
        "total": total,
        "items": [call_row(r, counselor_name=names.get(r.counselor_id, "")) for r in rows],
    }


# ══════════════════════════════════════════════════════════════
#  상담
# ══════════════════════════════════════════════════════════════


class ConsultationIn(BaseModel):
    customer_id: Optional[int] = None
    call_log_id: Optional[int] = None
    channel: str = "PHONE"
    inquiry_type_id: Optional[int] = None
    subject: str = Field("", max_length=200)
    content: str = ""
    result: str = ""
    status: str = "RECEIVED"
    priority: str = "NORMAL"


def _validate_consultation(payload: ConsultationIn) -> None:
    if payload.channel not in CONSULTATION_CHANNELS:
        raise HTTPException(status_code=400, detail="상담 채널이 올바르지 않습니다.")
    if payload.status not in CONSULTATION_STATUSES:
        raise HTTPException(status_code=400, detail="상담 상태가 올바르지 않습니다.")
    if payload.priority not in CONSULTATION_PRIORITIES:
        raise HTTPException(status_code=400, detail="우선순위가 올바르지 않습니다.")


@router.get("/consultations")
def list_consultations(
    status: str = "",
    channel: str = "",
    counselor_id: Optional[int] = None,
    mine: bool = False,
    q: str = "",
    limit: int = Query(30, le=200),
    offset: int = 0,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    query = db.query(CsConsultation)
    if status == "open":
        query = query.filter(CsConsultation.status.in_(options.open_statuses(db)))
    elif status in CONSULTATION_STATUSES:
        query = query.filter(CsConsultation.status == status)
    if channel in CONSULTATION_CHANNELS:
        query = query.filter(CsConsultation.channel == channel)
    if mine:
        query = query.filter(CsConsultation.counselor_id == user.id)
    elif counselor_id:
        query = query.filter(CsConsultation.counselor_id == counselor_id)
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(or_(CsConsultation.subject.ilike(term),
                                 CsConsultation.content.ilike(term)))

    total = query.count()
    rows = query.order_by(CsConsultation.created_at.desc()).offset(offset).limit(limit).all()
    names = _names(db, [r.counselor_id for r in rows])
    types = {t.id: t.name for t in db.query(CsInquiryType).all()}
    cust_ids = {r.customer_id for r in rows if r.customer_id}
    customers = {
        c.id: (c.name or mask_phone(c.phone_number))
        for c in db.query(CsCustomer).filter(CsCustomer.id.in_(cust_ids)).all()
    } if cust_ids else {}
    return {
        "total": total,
        "items": [
            consultation_row(r, names.get(r.counselor_id, ""),
                             customers.get(r.customer_id, ""), types.get(r.inquiry_type_id, ""))
            for r in rows
        ],
    }


@router.post("/consultations")
def create_consultation(
    payload: ConsultationIn,
    request: Request,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    _validate_consultation(payload)
    row = CsConsultation(
        customer_id=payload.customer_id,
        counselor_id=user.id,
        call_log_id=payload.call_log_id,
        channel=payload.channel,
        inquiry_type_id=payload.inquiry_type_id,
        subject=payload.subject.strip(),
        content=payload.content.strip(),
        result=payload.result.strip(),
        status=payload.status,
        priority=payload.priority,
        started_at=datetime.utcnow(),
    )
    if payload.status == "COMPLETED":
        row.ended_at = datetime.utcnow()
    db.add(row)
    db.commit()
    db.refresh(row)
    audit(db, request, user, "cs.consultation_create", "cs_consultation", row.id, row.subject)
    return consultation_row(row, user.name)


@router.get("/consultations/{consultation_id}")
def get_consultation(
    consultation_id: int,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    row = db.get(CsConsultation, consultation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="상담을 찾을 수 없습니다.")
    counselor = db.get(User, row.counselor_id) if row.counselor_id else None
    customer = db.get(CsCustomer, row.customer_id) if row.customer_id else None
    itype = db.get(CsInquiryType, row.inquiry_type_id) if row.inquiry_type_id else None
    return consultation_row(
        row,
        counselor.name if counselor else "",
        (customer.name or mask_phone(customer.phone_number)) if customer else "",
        itype.name if itype else "",
    )


@router.put("/consultations/{consultation_id}")
def update_consultation(
    consultation_id: int,
    payload: ConsultationIn,
    request: Request,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    row = db.get(CsConsultation, consultation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="상담을 찾을 수 없습니다.")
    _validate_consultation(payload)

    row.customer_id = payload.customer_id
    row.call_log_id = payload.call_log_id
    row.channel = payload.channel
    row.inquiry_type_id = payload.inquiry_type_id
    row.subject = payload.subject.strip()
    row.content = payload.content.strip()
    row.result = payload.result.strip()
    row.priority = payload.priority
    if row.status != payload.status:
        row.status = payload.status
        row.ended_at = datetime.utcnow() if payload.status == "COMPLETED" else None
    db.commit()
    audit(db, request, user, "cs.consultation_update", "cs_consultation", row.id, row.status)
    counselor = db.get(User, row.counselor_id) if row.counselor_id else None
    return consultation_row(row, counselor.name if counselor else "")


class AssignIn(BaseModel):
    counselor_id: int


@router.post("/consultations/{consultation_id}/assign")
def assign_consultation(
    consultation_id: int,
    payload: AssignIn,
    request: Request,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    row = db.get(CsConsultation, consultation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="상담을 찾을 수 없습니다.")
    target = db.get(User, payload.counselor_id)
    if target is None or target.role not in (Role.cs, Role.admin) or not target.is_active:
        raise HTTPException(status_code=400, detail="배정할 수 없는 상담원입니다.")
    row.counselor_id = target.id
    if row.status == "NEW":
        row.status = "RECEIVED"
    db.commit()
    audit(db, request, user, "cs.consultation_assign", "cs_consultation", row.id, target.name)
    return consultation_row(row, target.name)


# ══════════════════════════════════════════════════════════════
#  상담원
# ══════════════════════════════════════════════════════════════


def counselor_row(u: User, p: CsCounselorProfile, in_call: bool = False,
                  reveal: bool = False) -> dict:
    """상담원 한 줄.

    전화번호는 관리자에게만 원문으로 준다. number 모드에서는 이 번호로 실제
    벨이 울리므로 관리자가 보고 고칠 수 있어야 하지만, 동료의 개인 휴대폰을
    상담원 전원이 볼 이유는 없다.
    """

    return {
        "id": u.id,
        "name": u.name,
        "email": mask_email(u.email),
        "role": u.role.value,
        "is_active": bool(u.is_active),
        "ring_order": p.ring_order,
        "availability_status": p.availability_status,
        "accepts_calls": bool(p.accepts_calls),
        "extension": p.extension or "",
        "phone_number": (
            (format_phone(p.phone_number) if reveal else mask_phone(p.phone_number))
            if p.phone_number else ""
        ),
        "department": p.department or "",
        "position": p.position or "",
        "in_call": in_call,
        # 브라우저 전화기가 지금 등록돼 있는가. sip 모드에서 이게 꺼져 있으면
        # 그 상담원에게는 전화가 가지 않는다.
        "sip_registered": bool(
            p.sip_uri and p.sip_uri_expires_at
            and p.sip_uri_expires_at > datetime.utcnow()
        ),
        "last_status_at": iso_utc(p.last_status_at),
        "last_login_at": iso_utc(p.last_login_at),
    }


@router.get("/counselors")
def list_counselors(user: User = Depends(require_cs), db: Session = Depends(get_db)):
    """상담원과 지금 상태. 순차분배 순서대로 준다."""
    users = (
        db.query(User)
        .filter(User.role.in_([Role.cs, Role.admin]), User.is_active.is_(True))
        .all()
    )
    busy_ids = {
        c.counselor_id
        for c in db.query(CsCallLog).filter(CsCallLog.status == "ANSWERED").all()
        if c.counselor_id
    }
    items = []
    for u in users:
        profile = engine.ensure_profile(db, u)
        items.append(counselor_row(u, profile, in_call=u.id in busy_ids,
                                   reveal=user.role == Role.admin))
    items.sort(key=lambda x: (x["ring_order"], x["id"]))
    return {"total": len(items), "items": items}


class StatusIn(BaseModel):
    status: str


@router.put("/counselors/me/status")
def set_my_status(
    payload: StatusIn,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    if payload.status not in AVAILABILITY_STATUSES:
        raise HTTPException(status_code=400, detail="모르는 상태입니다.")
    profile = engine.set_availability(db, user, payload.status)
    return counselor_row(user, profile)


@router.get("/counselors/me")
def my_counselor(user: User = Depends(require_cs), db: Session = Depends(get_db)):
    profile = engine.ensure_profile(db, user)
    profile.last_login_at = datetime.utcnow()
    db.commit()
    return counselor_row(user, profile)


class OrderIn(BaseModel):
    counselor_ids: List[int]


@router.put("/counselors/order")
def set_order(
    payload: OrderIn,
    request: Request,
    user: User = Depends(require_cs_admin),
    db: Session = Depends(get_db),
):
    """순차분배 순서를 통째로 다시 매긴다. 화면에서 끌어 옮긴 결과를 받는다."""
    for index, cid in enumerate(payload.counselor_ids):
        target = db.get(User, cid)
        if target is None:
            continue
        profile = engine.ensure_profile(db, target)
        profile.ring_order = (index + 1) * 10
    db.commit()
    audit(db, request, user, "cs.counselor_order", "system", "",
          f"{len(payload.counselor_ids)}명 재정렬")
    return list_counselors(user=user, db=db)


class CounselorPatch(BaseModel):
    ring_order: Optional[int] = None
    accepts_calls: Optional[bool] = None
    extension: Optional[str] = None
    phone_number: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None


@router.put("/counselors/{counselor_id}")
def update_counselor(
    counselor_id: int,
    payload: CounselorPatch,
    request: Request,
    user: User = Depends(require_cs_admin),
    db: Session = Depends(get_db),
):
    target = db.get(User, counselor_id)
    if target is None or target.role not in (Role.cs, Role.admin):
        raise HTTPException(status_code=404, detail="상담원을 찾을 수 없습니다.")
    profile = engine.ensure_profile(db, target)
    if payload.ring_order is not None:
        profile.ring_order = max(1, payload.ring_order)
    if payload.accepts_calls is not None:
        profile.accepts_calls = payload.accepts_calls
    if payload.extension is not None:
        profile.extension = payload.extension.strip()[:20]
    if payload.phone_number is not None:
        profile.phone_number = normalize_phone(payload.phone_number)
    if payload.department is not None:
        profile.department = payload.department.strip()[:60]
    if payload.position is not None:
        profile.position = payload.position.strip()[:40]
    db.commit()
    audit(db, request, user, "cs.counselor_update", "user", target.id, target.name)
    return counselor_row(target, profile, reveal=True)


# ══════════════════════════════════════════════════════════════
#  통화
# ══════════════════════════════════════════════════════════════


@router.get("/calls/active")
def active_calls(user: User = Depends(require_cs), db: Session = Depends(get_db)):
    """지금 울리거나 통화 중이거나 대기열에 있는 콜.

    WebSocket 이 끊겼다 붙었을 때 화면을 되살리는 데 쓴다. 실시간 채널만
    믿으면 새로고침 한 번에 전화가 사라진다.
    """
    sessions = (
        db.query(CsCallSession)
        .filter(CsCallSession.state.in_(["RINGING", "QUEUED", "ANSWERED"]))
        .order_by(CsCallSession.created_at.asc())
        .all()
    )
    out = []
    for s in sessions:
        call = db.get(CsCallLog, s.call_log_id)
        if call is None:
            continue
        customer = db.query(CsCustomer).filter(
            CsCustomer.phone_number == call.phone_number).first()
        counselor = db.get(User, s.current_counselor_id) if s.current_counselor_id else None
        # 나에게 울리는 전화만 원문 번호를 준다. 남의 통화 상대 번호까지
        # 모두에게 뿌릴 이유가 없다.
        mine = s.current_counselor_id == user.id or call.counselor_id == user.id
        out.append({
            **call_row(call, reveal=mine, counselor_name=counselor.name if counselor else "",
                       customer_name=(customer.name if customer else "")),
            "session_state": s.state,
            "ring_step": s.ring_step,
            # 발신 통화는 벨이 울리는 게 아니라 내가 건 것이다. 같은 배너를
            # 띄우면 내가 건 전화에 [받기] 버튼이 나온다.
            "ringing_for_me": (s.state == "RINGING" and s.current_counselor_id == user.id
                               and call.direction == "INBOUND"),
            "outbound_for_me": (call.direction == "OUTBOUND"
                                and call.counselor_id == user.id
                                and s.state in ("RINGING", "ANSWERED")),
            "ring_deadline": iso_utc(s.ring_deadline),
            "queued_at": iso_utc(s.queued_at),
            "customer_id": customer.id if customer else None,
            "is_new_customer": customer is None,
        })
    return {"total": len(out), "items": out}


@router.get("/call-logs")
def list_call_logs(
    direction: str = "",
    status: str = "",
    counselor_id: Optional[int] = None,
    q: str = "",
    limit: int = Query(30, le=200),
    offset: int = 0,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    query = db.query(CsCallLog)
    if direction in ("INBOUND", "OUTBOUND"):
        query = query.filter(CsCallLog.direction == direction)
    if status == "closed":
        query = query.filter(CsCallLog.status.in_(CALL_CLOSED_STATUSES))
    elif status:
        query = query.filter(CsCallLog.status == status)
    if counselor_id:
        query = query.filter(CsCallLog.counselor_id == counselor_id)
    if q.strip():
        for v in phone_variants(q.strip()) or [q.strip()]:
            query = query.filter(CsCallLog.phone_number.like(f"%{v}%"))
            break

    total = query.count()
    rows = query.order_by(CsCallLog.started_at.desc()).offset(offset).limit(limit).all()
    names = _names(db, [r.counselor_id for r in rows])
    return {
        "total": total,
        "items": [call_row(r, counselor_name=names.get(r.counselor_id, "")) for r in rows],
    }


@router.post("/calls/{call_id}/answer")
def answer(call_id: int, request: Request, user: User = Depends(require_cs),
           db: Session = Depends(get_db)):
    try:
        call = engine.answer_call(db, call_id, user)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    audit(db, request, user, "cs.call_answer", "cs_call_log", call.id, "")
    return call_row(call, reveal=True, counselor_name=user.name)


@router.post("/calls/{call_id}/reject")
def reject(call_id: int, request: Request, user: User = Depends(require_cs),
           db: Session = Depends(get_db)):
    try:
        call = engine.reject_call(db, call_id, user)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    audit(db, request, user, "cs.call_reject", "cs_call_log", call.id, "")
    return {"ok": True}


@router.post("/calls/{call_id}/hangup")
def hangup(call_id: int, request: Request, user: User = Depends(require_cs),
           db: Session = Depends(get_db)):
    try:
        call = engine.hangup_call(db, call_id, user)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    audit(db, request, user, "cs.call_hangup", "cs_call_log", call.id,
          f"{call.duration_seconds}초")
    return call_row(call, reveal=True, counselor_name=user.name)


class OutboundIn(BaseModel):
    phone_number: str
    customer_id: Optional[int] = None


@router.post("/calls/outbound")
def outbound(
    payload: OutboundIn,
    request: Request,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    """상담원이 고객에게 건다.

    발신번호 표시는 사업자 설정을 따른다. CS 가 임의로 바꿀 수 없고,
    바꿔서도 안 된다(전기통신사업법상 발신번호 변작 금지).
    """
    provider = phone_pkg.get_provider()
    if not provider.capabilities().get("outbound"):
        raise HTTPException(status_code=501, detail="지금 전화 사업자는 발신을 지원하지 않습니다.")
    if not is_valid_phone(payload.phone_number):
        raise HTTPException(status_code=400, detail="전화번호가 올바르지 않습니다.")

    call = engine.make_outbound_call(db, user, payload.phone_number)
    if payload.customer_id:
        call.customer_id = payload.customer_id
        db.commit()
    audit(db, request, user, "cs.call_outbound", "cs_call_log", call.id,
          mask_phone(call.phone_number))
    return call_row(call, reveal=True, counselor_name=user.name)


class LinkCustomerIn(BaseModel):
    customer_id: int


@router.post("/calls/{call_id}/customer")
def link_call_customer(
    call_id: int,
    payload: LinkCustomerIn,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    """통화 기록에 고객을 잇는다. 신규 고객을 통화 중에 등록했을 때 쓴다."""
    call = db.get(CsCallLog, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="통화를 찾을 수 없습니다.")
    if db.get(CsCustomer, payload.customer_id) is None:
        raise HTTPException(status_code=404, detail="고객을 찾을 수 없습니다.")
    call.customer_id = payload.customer_id
    db.commit()
    return {"ok": True}


class TransferIn(BaseModel):
    counselor_id: Optional[int] = None
    phone_number: str = ""


@router.post("/calls/{call_id}/transfer")
def transfer(
    call_id: int,
    payload: TransferIn,
    request: Request,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    """통화 중인 전화를 다른 상담원이나 외부 번호로 돌린다."""
    if not payload.counselor_id and not payload.phone_number.strip():
        raise HTTPException(status_code=400, detail="넘길 상담원이나 번호를 지정하세요.")
    try:
        call = engine.transfer_call(
            db, call_id, user,
            to_counselor_id=payload.counselor_id,
            to_number=payload.phone_number,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    target = (
        db.get(User, payload.counselor_id).name
        if payload.counselor_id and db.get(User, payload.counselor_id)
        else mask_phone(payload.phone_number)
    )
    audit(db, request, user, "cs.call_transfer", "cs_call_log", call.id, target)
    return call_row(call, reveal=True)


# ── 개발용 가짜 전화 ─────────────────────────────────────────


class MockCallIn(BaseModel):
    phone_number: str


@router.post("/calls/mock/incoming")
def mock_incoming(
    payload: MockCallIn,
    request: Request,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    """테스트 전화 걸기.

    Mock Provider 일 때만 열린다. 실제 사업자를 붙인 뒤에도 이 문이 열려
    있으면 아무나 가짜 전화를 만들어 상담원을 부를 수 있다.
    """
    provider = phone_pkg.get_provider()
    if provider.name != "mock":
        raise HTTPException(status_code=403, detail="테스트 전화는 Mock Provider 에서만 됩니다.")
    if not is_valid_phone(payload.phone_number):
        raise HTTPException(status_code=400, detail="전화번호가 올바르지 않습니다.")

    snap = provider.receive_call(normalize_phone(payload.phone_number))
    call = engine.start_inbound_call(
        db,
        from_number=payload.phone_number,
        external_call_id=snap.external_call_id,
        provider_name=provider.name,
    )
    audit(db, request, user, "cs.call_mock", "cs_call_log", call.id, "테스트 전화")
    return call_row(call, reveal=True)


@router.post("/calls/{call_id}/mock/answered")
def mock_remote_answered(
    call_id: int,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    """발신 통화에서 상대가 받았다고 가정한다. Mock Provider 전용.

    실제 사업자에서는 망이 CALL_ANSWERED 웹훅을 올려준다. Mock 에는 상대가
    없으므로, 발신 이후의 흐름(통화시간·상담기록·종료)을 검사하려면 이 문이
    필요하다. 실제 사업자를 붙이면 닫힌다.
    """
    provider = phone_pkg.get_provider()
    if provider.name != "mock":
        raise HTTPException(status_code=403, detail="Mock Provider 에서만 됩니다.")
    call = db.get(CsCallLog, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="통화를 찾을 수 없습니다.")
    if call.direction != "OUTBOUND" or call.counselor_id != user.id:
        raise HTTPException(status_code=409, detail="내가 건 전화가 아닙니다.")
    provider.answer_call(call.external_call_id or f"call-{call.id}")
    engine.mark_answered(db, call)
    return call_row(call, reveal=True, counselor_name=user.name)


@router.post("/phone/webrtc-token")
def webrtc_token(
    request: Request,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    """브라우저가 전화를 받을 수 있게 SIP 등록 토큰을 내준다.

    토큰 수명이 5~7분이라 브라우저는 만료 전에 다시 불러야 한다. 부를 때마다
    SIP 주소가 바뀌므로, **발급하면서 그 주소를 이 상담원 앞으로 기록해 둔다.**
    브라우저가 스스로 "제 주소는 이겁니다" 하고 신고하게 두면, 남의 전화를
    자기에게 돌리도록 거짓말할 수 있다.

    전화 사업자 API 키는 이 함수 밖으로 나가지 않는다. 브라우저는 자기
    계정용 단기 자격증명만 받는다.
    """
    provider = phone_pkg.get_provider()
    issue = getattr(provider, "issue_webrtc_token", None)
    if issue is None or not provider.capabilities().get("webrtc_audio"):
        raise HTTPException(
            status_code=501,
            detail="지금 전화 사업자는 브라우저 통화를 지원하지 않습니다.",
        )
    try:
        creds = issue()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    if not creds.get("sip_uri"):
        raise HTTPException(status_code=502, detail="SIP 주소를 받지 못했습니다.")

    profile = engine.ensure_profile(db, user)
    profile.sip_uri = creds["sip_uri"][:200]
    exp = creds.get("expires_at")
    try:
        profile.sip_uri_expires_at = (
            datetime.utcfromtimestamp(int(exp)) if exp
            else datetime.utcnow() + timedelta(minutes=5)
        )
    except (TypeError, ValueError, OSError):
        profile.sip_uri_expires_at = datetime.utcnow() + timedelta(minutes=5)
    db.commit()

    # 비밀번호는 로그·감사기록에 남기지 않는다. 발급 사실만 남긴다.
    audit(db, request, user, "cs.webrtc_token", "user", user.id, "브라우저 전화기 등록")
    return {
        "sip_username": creds.get("sip_username", ""),
        "sip_password": creds.get("sip_password", ""),
        "ws_url": creds.get("ws_url", ""),
        "realm": creds.get("realm", ""),
        "ice_servers": creds.get("ice_servers", []),
        "expires_at": iso_utc(profile.sip_uri_expires_at),
    }


@router.delete("/phone/webrtc-token")
def drop_webrtc_token(user: User = Depends(require_cs), db: Session = Depends(get_db)):
    """브라우저를 닫거나 오프라인이 될 때 등록을 지운다.

    지우지 않으면 아무도 없는 주소로 전화가 돌아가 20초를 버린다.
    """
    profile = engine.ensure_profile(db, user)
    profile.sip_uri = ""
    profile.sip_uri_expires_at = None
    db.commit()
    return {"ok": True}


# ── 사업자 웹훅 ──────────────────────────────────────────────


@router.post("/phone/webhook/{provider_name}")
async def phone_webhook(provider_name: str, request: Request):
    """전화 사업자 → 우리. 서명을 검증하지 못하면 받지 않는다.

    이 문은 인증 없이 인터넷에 열려 있다. 서명 검증이 유일한 방어선이므로
    실패하면 조용히 무시하지 말고 401 로 끊는다.
    """
    provider = phone_pkg.get_provider()
    if provider.name != provider_name:
        raise HTTPException(status_code=404, detail="사용 중인 사업자가 아닙니다.")

    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    if not provider.verify_webhook(headers, body):
        raise HTTPException(status_code=401, detail="서명 검증에 실패했습니다.")

    data = await request.json()
    event = getattr(provider, "parse_webhook", lambda _: None)(data)
    if event is None:
        return {"ok": True, "ignored": True}

    db = SessionLocal()
    try:
        _handle_provider_event(db, event, provider.name)
    finally:
        db.close()
    return {"ok": True}


def _handle_provider_event(db: Session, event, provider_name: str) -> None:
    """망에서 올라온 사건을 엔진의 말로 옮긴다."""
    from ..phone.base import CallEventType

    call = db.query(CsCallLog).filter(
        CsCallLog.external_call_id == event.external_call_id).first()

    if event.type == CallEventType.CALL_INCOMING:
        if call is None:
            engine.start_inbound_call(
                db, from_number=event.from_number, to_number=event.to_number,
                external_call_id=event.external_call_id, provider_name=provider_name,
            )
        return

    if call is None:
        return

    if event.type in (CallEventType.CALL_ENDED, CallEventType.CALL_FAILED):
        # 고객이 먼저 끊은 경우다. 받은 적 없으면 부재중으로 남는다.
        engine.hangup_call(db, call.id)
    elif event.type == CallEventType.CALL_ANSWERED:
        # 발신 통화에서 상대가 받은 순간이다. 세션 상태까지 함께 옮겨야
        # 상담원 화면의 통화 시간이 돌기 시작한다.
        engine.mark_answered(db, call)


# ══════════════════════════════════════════════════════════════
#  설정 · 문의 유형
# ══════════════════════════════════════════════════════════════


class PhoneSettingsIn(BaseModel):
    ring_timeout_seconds: int = Field(20, ge=3, le=120)
    sequential_enabled: bool = True
    queue_enabled: bool = True
    # number : 상담원 휴대폰으로 건다. 사업자 부가서비스 없이 오늘 당장 된다.
    # stream : 통화 음성을 우리 서버가 받아 브라우저로 중계한다. 부가서비스 불필요.
    # sip    : 상담원의 SIP/WebRTC 단말로 건다. 사업자의 SIP 지원이 필요하다.
    agent_dial_mode: str = "number"


@router.get("/phone/settings")
def get_phone_settings(user: User = Depends(require_cs), db: Session = Depends(get_db)):
    provider = phone_pkg.get_provider()
    dial_row = db.get(Setting, voice.SETTING_DIAL_MODE)
    return {
        # 기동 때 어댑터를 못 만들었으면 그 이유. 화면이 빨갛게 띄운다.
        "provider_error": provider_error,
        "ring_timeout_seconds": engine.get_ring_timeout(db),
        "sequential_enabled": engine.sequential_enabled(db),
        "queue_enabled": engine.queue_enabled(db),
        "agent_dial_mode": (dial_row.value if dial_row and dial_row.value else "number"),
        "provider": provider.name,
        "provider_capabilities": provider.capabilities(),
        # 화면이 이 값을 보고 "지금은 음성이 흐르지 않습니다" 를 알린다.
        "audio_ready": bool(provider.capabilities().get("webrtc_audio")),
        "recorder": phone_pkg.get_recorder().name,
    }


@router.put("/phone/settings")
def put_phone_settings(
    payload: PhoneSettingsIn,
    request: Request,
    user: User = Depends(require_cs_admin),
    db: Session = Depends(get_db),
):
    def put(key: str, value: str) -> None:
        row = db.get(Setting, key)
        if row is None:
            db.add(Setting(key=key, value=value))
        else:
            row.value = value

    put(engine.SETTING_RING_TIMEOUT, str(payload.ring_timeout_seconds))
    put(engine.SETTING_SEQUENTIAL, "true" if payload.sequential_enabled else "false")
    put(engine.SETTING_QUEUE, "true" if payload.queue_enabled else "false")
    if payload.agent_dial_mode in engine.DIAL_MODES:
        put(voice.SETTING_DIAL_MODE, payload.agent_dial_mode)
    db.commit()
    audit(db, request, user, "cs.phone_settings", "system", "",
          f"링 {payload.ring_timeout_seconds}초")
    return get_phone_settings(user=user, db=db)


class InquiryTypeIn(BaseModel):
    name: str = Field(..., max_length=60)
    sort_order: int = 100
    is_active: bool = True


@router.get("/inquiry-types")
def list_inquiry_types(user: User = Depends(require_cs), db: Session = Depends(get_db)):
    rows = db.query(CsInquiryType).order_by(
        CsInquiryType.sort_order.asc(), CsInquiryType.id.asc()).all()
    return {
        "total": len(rows),
        "items": [
            {"id": r.id, "name": r.name, "sort_order": r.sort_order, "is_active": bool(r.is_active)}
            for r in rows
        ],
    }


@router.post("/inquiry-types")
def create_inquiry_type(
    payload: InquiryTypeIn,
    request: Request,
    user: User = Depends(require_cs_admin),
    db: Session = Depends(get_db),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="이름을 입력하세요.")
    if db.query(CsInquiryType).filter(CsInquiryType.name == name).first():
        raise HTTPException(status_code=409, detail="이미 있는 문의 유형입니다.")
    row = CsInquiryType(name=name, sort_order=payload.sort_order, is_active=payload.is_active)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit(db, request, user, "cs.inquiry_type_create", "cs_inquiry_type", row.id, name)
    return {"id": row.id, "name": row.name, "sort_order": row.sort_order,
            "is_active": bool(row.is_active)}


@router.put("/inquiry-types/{type_id}")
def update_inquiry_type(
    type_id: int,
    payload: InquiryTypeIn,
    request: Request,
    user: User = Depends(require_cs_admin),
    db: Session = Depends(get_db),
):
    row = db.get(CsInquiryType, type_id)
    if row is None:
        raise HTTPException(status_code=404, detail="문의 유형을 찾을 수 없습니다.")
    row.name = payload.name.strip()
    row.sort_order = payload.sort_order
    # 지우지 않고 감춘다. 지우면 지난 상담의 유형이 사라져 통계를 다시 못 그린다.
    row.is_active = payload.is_active
    db.commit()
    audit(db, request, user, "cs.inquiry_type_update", "cs_inquiry_type", row.id, row.name)
    return {"id": row.id, "name": row.name, "sort_order": row.sort_order,
            "is_active": bool(row.is_active)}


class OptionIn(BaseModel):
    code: str
    label: Optional[str] = None
    is_active: Optional[bool] = None
    is_open: Optional[bool] = None


class OptionsIn(BaseModel):
    statuses: List[OptionIn] = []
    priorities: List[OptionIn] = []


@router.get("/consultation-options")
def get_consultation_options(user: User = Depends(require_cs), db: Session = Depends(get_db)):
    """상담 상태·우선순위의 이름과 사용 여부.

    화면이 이름을 하드코딩하지 않고 여기서 받아 쓴다. 그래야 관리자가 바꾼
    이름이 상담원 화면·목록·통계에 한꺼번에 반영된다.
    """
    return {
        "statuses": options.status_options(db),
        "priorities": options.priority_options(db),
    }


@router.put("/consultation-options")
def put_consultation_options(
    payload: OptionsIn,
    request: Request,
    user: User = Depends(require_cs_admin),
    db: Session = Depends(get_db),
):
    if payload.statuses:
        options.save_status_options(db, [o.model_dump() for o in payload.statuses])
    if payload.priorities:
        options.save_priority_options(db, [o.model_dump() for o in payload.priorities])
    audit(db, request, user, "cs.consultation_options", "system", "", "상태·우선순위 설정")
    return get_consultation_options(user=user, db=db)


# ══════════════════════════════════════════════════════════════
#  전화 소리 (수신 벨 · 발신음 · 고객 대기음)
# ══════════════════════════════════════════════════════════════


@router.get("/phone/sounds")
def list_sounds(user: User = Depends(require_cs)):
    """무엇이 올라와 있는지. 올린 게 없으면 기본 소리가 난다."""
    return {kind: sounds.info(kind) for kind in sounds.KINDS}


@router.get("/phone/sounds/{kind}/file")
def get_sound_file(kind: str, user: User = Depends(require_cs)):
    """상담원 브라우저가 벨소리·발신음을 내려받는 자리."""
    from fastapi.responses import FileResponse

    if kind not in sounds.BROWSER_KINDS:
        raise HTTPException(status_code=404, detail="없는 소리입니다.")
    path = sounds.browser_path(kind)
    if path is None:
        raise HTTPException(status_code=404, detail="올린 소리가 없습니다.")
    # 파일이 바뀌면 브라우저가 새로 받아야 한다. 캐시를 막는다.
    return FileResponse(path, headers={"Cache-Control": "no-store"})


@router.put("/phone/sounds/{kind}")
async def put_sound(
    kind: str,
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(require_cs_admin),
    db: Session = Depends(get_db),
):
    """소리를 올린다.

    수신 벨·발신음은 올린 파일 그대로 둔다. 브라우저가 재생하므로 형식을
    가리지 않는다.

    대기음은 전화망으로 나가야 해서 8kHz μ-law 여야 한다. 그 변환은
    브라우저가 미리 해서 보낸다(서버 파이썬 버전에 기대지 않기 위해서다).
    """
    if kind not in sounds.KINDS:
        raise HTTPException(status_code=404, detail="없는 소리입니다.")

    limit = sounds.MAX_HOLD_BYTES if kind == "hold" else sounds.MAX_BROWSER_BYTES
    data = await file.read(limit + 1)
    if not data:
        raise HTTPException(status_code=400, detail="파일이 비어 있습니다.")
    if len(data) > limit:
        raise HTTPException(
            status_code=413,
            detail=(f"파일이 너무 큽니다. 대기음은 {sounds.MAX_HOLD_SECONDS}초까지"
                    if kind == "hold" else "파일이 너무 큽니다. 2MB 까지 올릴 수 있습니다."),
        )

    if kind == "hold":
        saved = sounds.save_hold(data)
        detail = f"{saved / sounds.SAMPLE_RATE:.1f}초"
    else:
        sounds.save_browser_sound(kind, data, file.filename or "")
        detail = file.filename or ""

    audit(db, request, user, "cs.phone_sound", "system", kind, detail)
    return {"ok": True, **sounds.info(kind)}


@router.delete("/phone/sounds/{kind}")
def delete_sound(
    kind: str,
    request: Request,
    user: User = Depends(require_cs_admin),
    db: Session = Depends(get_db),
):
    """기본 소리로 되돌린다."""
    if kind not in sounds.KINDS:
        raise HTTPException(status_code=404, detail="없는 소리입니다.")
    sounds.clear(kind)
    audit(db, request, user, "cs.phone_sound_clear", "system", kind, "기본 소리로")
    return {"ok": True, **sounds.info(kind)}


# ══════════════════════════════════════════════════════════════
#  통계
# ══════════════════════════════════════════════════════════════


@router.get("/phone/summary")
def phone_summary(user: User = Depends(require_cs), db: Session = Depends(get_db)):
    """사이드바 배지에 쓸 짧은 숫자들."""
    today = datetime.utcnow().date()
    start = datetime(today.year, today.month, today.day)
    return {
        "consultations_open": db.query(func.count(CsConsultation.id)).filter(
            CsConsultation.status.in_(options.open_statuses(db))).scalar() or 0,
        "calls_ringing": db.query(func.count(CsCallSession.id)).filter(
            CsCallSession.state.in_(["RINGING", "QUEUED"])).scalar() or 0,
        "calls_in_progress": db.query(func.count(CsCallSession.id)).filter(
            CsCallSession.state == "ANSWERED").scalar() or 0,
        "missed_today": db.query(func.count(CsCallLog.id)).filter(
            CsCallLog.status == "MISSED", CsCallLog.started_at >= start).scalar() or 0,
    }


@router.get("/statistics")
def statistics(user: User = Depends(require_cs), db: Session = Depends(get_db)):
    now = datetime.utcnow()
    today = datetime(now.year, now.month, now.day)
    week = today - timedelta(days=today.weekday())
    month = datetime(now.year, now.month, 1)

    def consultations_since(since):
        return db.query(func.count(CsConsultation.id)).filter(
            CsConsultation.created_at >= since).scalar() or 0

    # 상담원별 실적. 상담 건수와 통화 건수는 뜻이 달라 따로 센다.
    per_counselor = []
    users = db.query(User).filter(
        User.role.in_([Role.cs, Role.admin]), User.is_active.is_(True)).all()
    for u in users:
        consult_n = db.query(func.count(CsConsultation.id)).filter(
            CsConsultation.counselor_id == u.id).scalar() or 0
        done_n = db.query(func.count(CsConsultation.id)).filter(
            CsConsultation.counselor_id == u.id,
            CsConsultation.status == "COMPLETED").scalar() or 0
        call_n = db.query(func.count(CsCallLog.id)).filter(
            CsCallLog.counselor_id == u.id, CsCallLog.status == "COMPLETED").scalar() or 0
        avg_sec = db.query(func.avg(CsCallLog.duration_seconds)).filter(
            CsCallLog.counselor_id == u.id, CsCallLog.status == "COMPLETED").scalar() or 0
        per_counselor.append({
            "counselor_id": u.id, "name": u.name,
            "consultations": consult_n, "completed": done_n,
            "calls": call_n, "avg_call_seconds": int(avg_sec),
        })
    per_counselor.sort(key=lambda x: -x["consultations"])

    types = db.query(CsInquiryType).order_by(CsInquiryType.sort_order.asc()).all()
    per_type = []
    for t in types:
        n = db.query(func.count(CsConsultation.id)).filter(
            CsConsultation.inquiry_type_id == t.id).scalar() or 0
        per_type.append({"id": t.id, "name": t.name, "count": n})
    untyped = db.query(func.count(CsConsultation.id)).filter(
        CsConsultation.inquiry_type_id.is_(None)).scalar() or 0
    if untyped:
        per_type.append({"id": None, "name": "미분류", "count": untyped})

    per_channel = []
    for ch in CONSULTATION_CHANNELS:
        n = db.query(func.count(CsConsultation.id)).filter(
            CsConsultation.channel == ch).scalar() or 0
        per_channel.append({"channel": ch, "count": n})

    return {
        "consultations_today": consultations_since(today),
        "consultations_week": consultations_since(week),
        "consultations_month": consultations_since(month),
        "consultations_open": db.query(func.count(CsConsultation.id)).filter(
            CsConsultation.status.in_(options.open_statuses(db))).scalar() or 0,
        "calls_in_progress": db.query(func.count(CsCallSession.id)).filter(
            CsCallSession.state == "ANSWERED").scalar() or 0,
        "calls_waiting": db.query(func.count(CsCallSession.id)).filter(
            CsCallSession.state == "QUEUED").scalar() or 0,
        "missed_today": db.query(func.count(CsCallLog.id)).filter(
            CsCallLog.status == "MISSED", CsCallLog.started_at >= today).scalar() or 0,
        "calls_today": db.query(func.count(CsCallLog.id)).filter(
            CsCallLog.started_at >= today).scalar() or 0,
        "per_counselor": per_counselor,
        "per_type": per_type,
        "per_channel": per_channel,
    }


# ══════════════════════════════════════════════════════════════
#  홈페이지 문의 연동 (서버 간 호출)
# ══════════════════════════════════════════════════════════════


class InboundInquiryIn(BaseModel):
    name: str = ""
    phone_number: str = ""
    email: str = ""
    subject: str = ""
    content: str
    school_name: str = ""
    customer_type: str = "OTHER"


@router.post("/inbound/inquiry")
def inbound_inquiry(
    payload: InboundInquiryIn,
    x_cs_inbound_secret: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """UDJ 홈페이지 → CS. 브라우저가 아니라 UDJ 서버가 부른다.

    상담원 로그인 없이 상담을 만드는 유일한 문이므로, 공유 비밀키가 없으면
    열지 않는다. 키가 설정돼 있지 않으면 기능 자체를 닫는다.
    """
    secret = (os.getenv("CS_INBOUND_SECRET", "") or "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="연동이 설정되지 않았습니다.")
    if not x_cs_inbound_secret or x_cs_inbound_secret.strip() != secret:
        raise HTTPException(status_code=401, detail="인증에 실패했습니다.")

    row = intake.record_homepage_inquiry(
        db,
        question=payload.content,
        name=payload.name,
        phone=payload.phone_number,
        email=payload.email,
        school_name=payload.school_name,
        subject=payload.subject,
        customer_type=payload.customer_type,
    )
    if row is None:
        raise HTTPException(status_code=500, detail="상담을 만들지 못했습니다.")
    return {"ok": True, "consultation_id": row.id}


# ══════════════════════════════════════════════════════════════
#  WebSocket
# ══════════════════════════════════════════════════════════════


@router.websocket("/ws/calls")
async def ws_calls(websocket: WebSocket, token: str = "", device: str = ""):
    await hub.calls_socket(websocket, token=token, device=device)


# ══════════════════════════════════════════════════════════════
#  배경 작업 (링 타임아웃 · 아웃박스 청소)
# ══════════════════════════════════════════════════════════════

_ticker_task: Optional[asyncio.Task] = None
TICK_SECONDS = 1.0


async def _ticker() -> None:
    """1초마다 만료된 링을 다음 상담원에게 넘긴다.

    동기 DB 세션을 이벤트 루프에서 직접 돌리면 다른 요청이 밀리므로
    스레드풀로 보낸다. 워커가 여러 개여도 낙관적 UPDATE 덕에 중복되지 않는다.
    """
    purge_countdown = 0
    while True:
        try:
            await asyncio.sleep(TICK_SECONDS)
            purge_countdown += 1

            def work():
                db = SessionLocal()
                try:
                    engine.tick_timeouts(db)
                    if purge_countdown % 600 == 0:   # 10분마다
                        hub.purge_old_events(db)
                finally:
                    db.close()

            await run_in_threadpool(work)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # 한 번의 실패로 타이머가 죽으면 모든 전화가 첫 상담원에게 묶인다.
            log.warning("링 타이머 오류: %s", exc)


# 기동할 때 전화 어댑터를 만들다 실패하면 그 이유를 여기 담아 둔다.
# 화면과 로그가 이 값을 보고 "전화가 안 된다"고 분명히 말한다.
provider_error: Optional[str] = None


async def start_background() -> None:
    """배경 타이머를 띄우고, 전화 설정이 제대로 됐는지 지금 확인한다.

    설정이 틀렸으면 여기서 알아야 한다. 첫 전화가 걸려온 순간에 알게 되면
    그 전화는 이미 놓친 뒤다.

    다만 **여기서 예외를 밖으로 던지지 않는다.** 이 백엔드는 본 사이트
    (udjschool.ggm.kr)와 같은 프로세스라, 전화 키 하나가 틀렸다고 서버가
    죽으면 학교 검색까지 함께 멈춘다. 전화만 못 쓰게 두고 크게 알린다.
    """
    global _ticker_task, provider_error

    name = phone_pkg.provider_name()
    try:
        provider = phone_pkg.get_provider()
        provider_error = None
        # print 로 남긴다. gunicorn 아래에서는 logger 의 info 가 안 보인다.
        print(f"[전화] 어댑터 준비됨: {provider.name} "
              f"(브라우저 통화 {'가능' if provider.capabilities().get('webrtc_audio') else '불가'})",
              flush=True)
    except Exception as exc:
        provider_error = str(exc)
        print("=" * 60, flush=True)
        print(f"[전화] 어댑터를 만들지 못했습니다 (PHONE_PROVIDER={name})", flush=True)
        print(f"[전화] {exc}", flush=True)
        print("[전화] 전화 기능만 멈춥니다. 본 사이트는 정상 동작합니다.", flush=True)
        print("=" * 60, flush=True)

    if _ticker_task is None or _ticker_task.done():
        _ticker_task = asyncio.create_task(_ticker())


async def stop_background() -> None:
    global _ticker_task
    if _ticker_task is not None:
        _ticker_task.cancel()
        _ticker_task = None
