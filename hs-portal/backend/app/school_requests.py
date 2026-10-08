"""학교 계정 발급 신청.

학교 계정은 지금까지 관리자만 만들 수 있었고(main.py 의
/api/admin/school-accounts), 그건 그대로 둔다. 여기는 그 앞단이다.

    학교가 신청 → 운영자가 전화로 확인 → 승인
                                         ↓
                        학교 계정 생성 + 아이디·임시 비밀번호 메일 발송

**왜 전화 확인인가.** 학교 계정은 그 학교의 정보를 고치고 진학정보까지
입력하는 계정이다. 메일 주소만 보고 열어 주면 남이 학교 행세를 할 수 있다.
그래서 자동 승인을 두지 않는다 — 승인은 사람이 누른다.

담당자 휴대폰·이메일을 받으므로 동의를 함께 받고, 처리가 끝난 신청서는
보관 기간이 지나면 파기한다.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from .auth import hash_password, require_admin
from .database import get_db
from .models import Coed, Role, School, SchoolAccountRequest, SchoolContact, User

router = APIRouter(prefix="/api", tags=["school-account-request"])

STATUSES = ("received", "called", "approved", "rejected")
STATUS_LABEL = {
    "received": "접수", "called": "통화 완료", "approved": "승인", "rejected": "반려",
}
# 아직 손이 더 가야 하는 신청. 관리자 화면의 '처리할 신청' 개수가 이걸 센다.
OPEN_STATUSES = ("received", "called")

# 처리가 끝난 신청서를 남겨 두는 기간. 승인 건은 "누가 언제 계정을 받았나"의
# 근거라 더 오래 두고, 반려 건은 짧게 두고 지운다.
APPROVED_RETENTION_DAYS = 365
REJECTED_RETENTION_DAYS = 90

PRIVACY_NOTICE = {
    "collected": ["담당자 이름·직위(필수)", "담당자 휴대전화(필수)", "담당자 이메일(필수)",
                  "학교 대표번호(선택)", "통화 가능한 시간대(선택)"],
    "purpose": "학교 계정 발급 여부를 전화로 확인하고, 승인 시 계정 정보를 보내드리기 위해 수집·이용합니다.",
    "retention": (f"승인 건은 {APPROVED_RETENTION_DAYS}일, 반려·미처리 건은 "
                  f"{REJECTED_RETENTION_DAYS}일 보관 후 파기합니다."),
    "recipient": "포털 운영자만 열람하며, 제3자에게 제공하지 않습니다.",
    "right_to_refuse": "동의를 거부할 수 있으나, 이 경우 학교 계정 발급 신청을 받을 수 없습니다.",
    # 선택 동의 — 고등학교 담당자가 '우리동네직업계고 공지'를 받는 데 쓴다.
    "notice_optional": {
        "items": "담당자 이름·휴대전화·이메일",
        "purpose": "우리동네 직업계고 운영 공지(학교 인터뷰 촬영·행사·서비스 안내 등)를 이메일과 문자로 보내드리기 위해 이용합니다. 광고성 정보는 보내지 않습니다.",
        "retention": "담당자 변경 또는 동의 철회 시까지(학교 관리 > 공지 알림 설정에서 언제든 철회할 수 있습니다)",
        "right_to_refuse": "동의하지 않아도 학교 계정 발급에는 영향이 없습니다. 이 경우 공지를 이메일·문자로 받지 않습니다.",
    },
}

PHONE_RE = re.compile(r"^[0-9\-+() ]{8,30}$")

# 학교급. 고등학교는 포털 학교 목록에서 고르고, 중학교는 목록에 없으니 이름·지역을 적는다.
LEVELS = {"high": "고등학교", "middle": "중학교"}
# 학교 검색과 같은 지역 목록.
REGIONS = ("서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
           "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주")


def random_password(length: int = 12) -> str:
    """전화로 불러 주기 쉬운 임시 비밀번호. 헷갈리는 글자(0/O, 1/l)는 뺀다.
    (make_school_accounts.py 와 같은 규칙)"""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


class RequestIn(BaseModel):
    # 목록에서 고른 경우에만 채워진다. 없으면 school_name 을 직접 적은 것이다.
    school_id: Optional[int] = None
    school_name: str = Field(min_length=2, max_length=120)
    school_level: str = "high"            # high / middle
    region: str = Field("", max_length=20)
    manager_name: str = Field(min_length=1, max_length=40)
    manager_position: str = Field("", max_length=40)
    manager_phone: str = Field(min_length=8, max_length=30)
    manager_email: EmailStr
    school_phone: str = Field("", max_length=30)
    call_time: str = Field("", max_length=60)
    privacy_consent: bool = False
    notice_consent: bool = False         # (선택) 우리동네직업계고 공지 수신 동의


class AdminPatch(BaseModel):
    status: Optional[str] = None
    admin_note: Optional[str] = Field(None, max_length=300)


def _out(db: Session, r: SchoolAccountRequest, admin: bool = False) -> dict:
    school = db.get(School, r.school_id) if r.school_id else None
    # 이미 학교 계정이 있는 학교인지. 있으면 관리자 화면에서 눈에 띄게 알린다 —
    # 모르고 승인하면 한 학교에 계정이 둘이 된다.
    existing = []
    if school is not None:
        existing = [
            {"id": u.id, "email": u.email, "is_active": bool(u.is_active)}
            for u in (school.accounts or []) if u.role == Role.school
        ]
    data = {
        "id": r.id,
        "school_id": r.school_id,
        "school_name": r.school_name,
        "school_level": r.school_level or "high",
        "school_level_label": LEVELS.get(r.school_level or "high", "고등학교"),
        "region": r.region or (school.region if school else ""),
        "school_matched": school is not None,
        "school_region": school.region if school else "",
        "school_category": school.category if school else "",
        "existing_accounts": existing,
        "manager_name": r.manager_name,
        "manager_position": r.manager_position or "",
        "manager_phone": r.manager_phone,
        "manager_email": r.manager_email,
        "school_phone": r.school_phone or "",
        "call_time": r.call_time or "",
        "notice_consent": bool(r.notice_consent),
        "status": r.status,
        "status_label": STATUS_LABEL.get(r.status, r.status),
        "admin_note": r.admin_note or "",
        "mail_sent": bool(r.mail_sent),
        "mail_error": r.mail_error or "",
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "handled_at": r.handled_at.isoformat() if r.handled_at else None,
    }
    if not admin:
        # 접수 확인용 응답에는 개인정보를 되돌려 주지 않는다.
        return {"id": r.id, "status": r.status, "status_label": data["status_label"]}
    return data


def purge_old_requests(db: Session) -> int:
    """보관 기간이 지난 신청서를 지운다. 담당자 연락처가 남아 있어서다."""
    now = datetime.utcnow()
    n = db.query(SchoolAccountRequest).filter(
        SchoolAccountRequest.status == "approved",
        SchoolAccountRequest.created_at < now - timedelta(days=APPROVED_RETENTION_DAYS),
    ).delete(synchronize_session=False)
    n += db.query(SchoolAccountRequest).filter(
        SchoolAccountRequest.status != "approved",
        SchoolAccountRequest.created_at < now - timedelta(days=REJECTED_RETENTION_DAYS),
    ).delete(synchronize_session=False)
    if n:
        db.commit()
    return n


@router.get("/privacy/school-account-request")
def privacy_notice():
    return PRIVACY_NOTICE


@router.post("/school-account-requests")
def create_request(
    payload: RequestIn,
    background: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
):
    """학교가 남기는 신청. 로그인 없이 받는다 — 계정이 없어서 신청하는 것이다."""
    if not payload.privacy_consent:
        raise HTTPException(status_code=422, detail="개인정보 수집·이용에 동의해야 신청할 수 있습니다.")
    if payload.school_level not in LEVELS:
        raise HTTPException(status_code=422, detail="학교 유형(중학교·고등학교)을 골라 주세요.")
    region = payload.region.strip()
    if region and region not in REGIONS:
        raise HTTPException(status_code=422, detail="지역은 목록에서 골라 주세요.")
    if payload.school_level == "middle":
        if not region:
            raise HTTPException(status_code=422, detail="중학교는 지역을 골라 주세요.")
        if payload.school_id:
            # 포털 학교 목록은 고등학교(직업계고)다. 중학교가 그중 하나를 고를 수는 없다.
            sel = db.get(School, payload.school_id)
            if sel is None or (sel.school_level or "high") != "middle":
                raise HTTPException(status_code=422,
                                    detail="중학교는 학교 이름을 직접 적어 주세요(고등학교 목록에서 고를 수 없습니다).")
    if not PHONE_RE.match(payload.manager_phone.strip()):
        raise HTTPException(status_code=422, detail="휴대전화 번호 형식이 올바르지 않습니다.")
    if payload.school_phone and not PHONE_RE.match(payload.school_phone.strip()):
        raise HTTPException(status_code=422, detail="학교 대표번호 형식이 올바르지 않습니다.")

    school = db.get(School, payload.school_id) if payload.school_id else None
    if payload.school_id and school is None:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")

    # 같은 학교·같은 담당자가 짧은 사이에 여러 번 누르는 것만 막는다. 이미
    # 계정이 있는 학교의 신청은 막지 않는다 — 담당자가 바뀌어 다시 받는
    # 경우가 있어서, 접수해 두고 관리자 화면에서 알려 준다.
    dup = db.query(SchoolAccountRequest).filter(
        SchoolAccountRequest.manager_email == str(payload.manager_email),
        SchoolAccountRequest.status.in_(OPEN_STATUSES),
    ).first()
    if dup:
        raise HTTPException(
            status_code=409,
            detail="같은 이메일로 접수된 신청이 이미 처리 대기 중입니다. 확인 전화를 기다려 주세요.",
        )

    ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
          or (request.client.host if request.client else ""))[:45]
    row = SchoolAccountRequest(
        school_id=school.id if school else None,
        school_name=(school.name if school else payload.school_name.strip())[:120],
        school_level=payload.school_level,
        region=(school.region if school else region)[:20],
        manager_name=payload.manager_name.strip(),
        manager_position=payload.manager_position.strip(),
        manager_phone=payload.manager_phone.strip(),
        manager_email=str(payload.manager_email).strip().lower(),
        school_phone=payload.school_phone.strip(),
        call_time=payload.call_time.strip(),
        privacy_consent=True,
        # 공지 수신 동의는 담당 선생님을 두는 고등학교만 의미가 있다.
        notice_consent=bool(payload.notice_consent) and payload.school_level == "high",
        ip=ip,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    background.add_task(_notify_admin, row.school_name, row.manager_name,
                        row.manager_phone, row.call_time)
    return {
        "ok": True, "id": row.id,
        "message": "신청이 접수되었습니다. 담당자 확인 전화를 드린 뒤 계정을 발급해 드립니다.",
    }


def _notify_admin(school_name: str, manager: str, phone: str, call_time: str) -> None:
    """새 신청이 들어왔다고 운영자에게 알린다. 실패해도 접수는 그대로다."""
    from . import applications as apps_mod
    from . import mailer
    from .database import SessionLocal

    db = SessionLocal()
    try:
        to_addr = apps_mod._get(db, apps_mod.NOTIFY_KEY).strip()
    except Exception:
        to_addr = ""
    finally:
        db.close()
    if not to_addr:
        return
    cfg = mailer.system_config()
    if not cfg.is_ready():
        return
    body = (f"학교 계정 발급 신청이 접수되었습니다.\n\n"
            f"학교      : {school_name}\n담당자    : {manager}\n"
            f"휴대전화  : {phone}\n통화 가능 : {call_time or '-'}\n\n"
            f"관리자 화면 → 학교 계정 신청에서 확인 후 승인해 주세요.")
    try:
        mailer.send_email(cfg, to_addr, f"[학교 계정 신청] {school_name}", body,
                          from_name="우리동네 직업계고")
    except Exception as exc:
        print(f"[학교계정신청] 알림 실패: {exc}", flush=True)


# ══════════════════════════════════════════════════════════════
#  관리자
# ══════════════════════════════════════════════════════════════
@router.get("/admin/school-account-requests")
def list_requests(
    status: Optional[str] = Query(None),
    level: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    purge_old_requests(db)
    q = db.query(SchoolAccountRequest)
    if status in STATUSES:
        q = q.filter(SchoolAccountRequest.status == status)
    elif status == "open":            # 승인 대기(접수·통화 완료)
        q = q.filter(SchoolAccountRequest.status.in_(OPEN_STATUSES))
    if level in LEVELS:
        q = q.filter(SchoolAccountRequest.school_level == level)
    rows = q.order_by(SchoolAccountRequest.created_at.desc()).limit(300).all()
    open_count = db.query(SchoolAccountRequest).filter(
        SchoolAccountRequest.status.in_(OPEN_STATUSES)).count()
    return {
        "items": [_out(db, r, admin=True) for r in rows],
        "open_count": open_count,
        "statuses": [{"key": k, "label": STATUS_LABEL[k]} for k in STATUSES],
        "levels": [{"key": k, "label": v} for k, v in LEVELS.items()],
    }


def _row(db: Session, request_id: int) -> SchoolAccountRequest:
    r = db.get(SchoolAccountRequest, request_id)
    if r is None:
        raise HTTPException(status_code=404, detail="신청서를 찾을 수 없습니다.")
    return r


@router.patch("/admin/school-account-requests/{request_id}")
def update_request(
    request_id: int,
    payload: AdminPatch,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """상태·메모를 고친다. 승인은 따로 있다(계정을 만들어야 해서)."""
    r = _row(db, request_id)
    if payload.status is not None:
        if payload.status not in STATUSES:
            raise HTTPException(status_code=422, detail="알 수 없는 상태입니다.")
        if payload.status == "approved":
            raise HTTPException(status_code=422, detail="승인은 승인 단추로만 할 수 있습니다.")
        if r.status == "approved":
            raise HTTPException(status_code=409, detail="이미 승인해 계정이 만들어진 신청서입니다.")
        r.status = payload.status
        r.handled_at = datetime.utcnow()
        r.handled_by = user.id
    if payload.admin_note is not None:
        r.admin_note = payload.admin_note.strip()
    db.commit()
    return _out(db, r, admin=True)


@router.post("/admin/school-account-requests/{request_id}/approve")
def approve_request(
    request_id: int,
    http_request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """전화 확인이 끝난 신청을 승인한다 — 학교 계정을 만들고 메일로 보낸다.

    임시 비밀번호는 **응답에도 함께 돌려준다.** 메일이 막혀 있을 때 관리자가
    전화로 불러 줄 수 있어야 하기 때문이다. 화면 밖으로는 나가지 않는다.
    """
    from .main import write_audit

    r = _row(db, request_id)
    if r.status == "approved":
        raise HTTPException(status_code=409, detail="이미 승인된 신청서입니다.")
    if not r.school_id and (r.school_level or "high") == "middle":
        # 중학교는 포털 학교 목록에 없다. 승인하면서 숨김 학교로 만든다 — 공개
        # 검색·지도·사이트맵은 숨김 학교를 빼므로 직업계고 목록에 섞이지 않는다.
        if db.query(User).filter(User.email == r.manager_email).first():
            raise HTTPException(status_code=409, detail="이미 가입된 이메일입니다. 기존 계정을 확인해 주세요.")
        ms = School(name=r.school_name[:80], category="중학교", region=r.region or "기타",
                    address="", coed=Coed.coed, phone=r.school_phone or "",
                    school_level="middle", is_visible=False)
        db.add(ms)
        db.flush()
        r.school_id = ms.id
    if not r.school_id:
        raise HTTPException(
            status_code=422,
            detail="학교가 연결되지 않은 신청서입니다. 먼저 학교를 찾아 연결하거나 학교를 등록해 주세요.",
        )
    school = db.get(School, r.school_id)
    if school is None:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")
    if db.query(User).filter(User.email == r.manager_email).first():
        raise HTTPException(status_code=409, detail="이미 가입된 이메일입니다. 기존 계정을 확인해 주세요.")

    password = random_password()
    account = User(
        email=r.manager_email,
        password_hash=hash_password(password),
        name=(r.manager_name or school.name)[:60],
        role=Role.school,
        school_id=school.id,
        phone=r.manager_phone or "",
        # 전화로 불러 준 비밀번호를 그대로 쓰게 두지 않는다.
        must_change_password=True,
    )
    db.add(account)
    db.flush()

    # 고등학교: 신청한 담당자를 '우리동네직업계고 담당 선생님'으로 둔다(이미 있으면 그대로).
    if (school.school_level or "high") == "high" and not db.query(SchoolContact).filter(
            SchoolContact.school_id == school.id, SchoolContact.role == "udj_contact").first():
        db.add(SchoolContact(school_id=school.id, role="udj_contact", is_primary=True,
                             name=r.manager_name or "", position=r.manager_position or "",
                             email=r.manager_email or "", phone=r.manager_phone or "",
                             # 신청서에서 공지 수신에 동의한 경우에만 발송 대상이 된다.
                             consent_at=r.created_at if r.notice_consent else None,
                             consent_source="request" if r.notice_consent else ""))

    sent, err = _send_account_mail(r.manager_email, school.name, r.manager_name, password,
                                   level=school.school_level or "high")
    r.status = "approved"
    r.created_user_id = account.id
    r.mail_sent = sent
    r.mail_error = "" if sent else (err or "")[:300]
    r.handled_at = datetime.utcnow()
    r.handled_by = user.id
    db.commit()

    write_audit(db, http_request, user, "school_account_request_approve",
                "school_account_request", r.id,
                f"{school.name} / {r.manager_email} / 메일 {'발송' if sent else '실패'}")
    return {
        "ok": True, "user_id": account.id, "email": account.email,
        # 메일이 나갔든 아니든 화면에 띄워 준다. 실패했을 때만 보여주면
        # 관리자가 실패를 놓쳤을 때 알려 줄 방법이 없다.
        "temp_password": password,
        "mail_sent": sent, "mail_error": "" if sent else err,
    }


def _send_account_mail(to_addr: str, school_name: str, manager: str,
                       password: str, level: str = "high") -> tuple[bool, str]:
    from . import mailer

    cfg = mailer.system_config()
    if not cfg.is_ready():
        return False, "메일 계정이 설정되지 않았습니다(SMTP_*)."
    body = (
        f"{manager}님, 안녕하세요.\n\n"
        f"신청하신 {school_name} 학교 계정이 발급되었습니다.\n\n"
        f"  아이디(이메일) : {to_addr}\n"
        f"  임시 비밀번호  : {password}\n\n"
        f"https://udjschool.ggm.kr/login 에서 로그인하신 뒤\n"
        f"임시 비밀번호를 반드시 새 비밀번호로 바꿔 주세요.\n\n"
        + ("로그인하시면 직업계고 진학 정보·학교 탐색·설명회 등 진학 지원 자료를 이용하실 수 있습니다.\n"
           if level == "middle" else
           "로그인하시면 학교 정보·학교 일정·문의 답변을 직접 관리하실 수 있습니다.\n")
        + "문의 사항은 이 메일로 회신해 주세요.\n"
    )
    try:
        return mailer.send_email(cfg, to_addr, f"[우리동네 직업계고] {school_name} 학교 계정 안내",
                                 body, from_name="우리동네 직업계고")
    except Exception as exc:
        return False, str(exc)


@router.post("/admin/school-account-requests/{request_id}/link-school")
def link_school(
    request_id: int,
    school_id: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """학교명을 직접 적어 낸 신청서에 실제 학교를 이어 준다(승인 전 준비)."""
    r = _row(db, request_id)
    if r.status == "approved":
        raise HTTPException(status_code=409, detail="이미 승인된 신청서입니다.")
    school = db.get(School, school_id)
    if school is None:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")
    r.school_id = school.id
    r.school_name = school.name
    db.commit()
    return _out(db, r, admin=True)


@router.delete("/admin/school-account-requests/{request_id}")
def delete_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    db.delete(_row(db, request_id))
    db.commit()
    return {"ok": True}
