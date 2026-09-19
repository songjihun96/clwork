"""상담 사이트(udjcs.ggm.kr) 전용 API.

우리동네 직업계고를 상담 직원이 대신 들여다보는 창구다. 같은 DB 를 보지만
관리자 패널과는 권한이 다르다. 여기서 할 수 없는 일은 엔드포인트 자체를
두지 않았다. 화면에서 숨기는 것만으로는 막았다고 할 수 없기 때문이다.

접근 제한은 두 겹이다.

1) 사무실 IP        — 설정에 등록한 대역에서 오면 그대로 통과한다.
2) 기기 승인        — 그 밖에서 오면 관리자가 승인한 기기여야 한다.

기기 식별은 완벽하지 않다. 브라우저가 알려주는 값(User-Agent 등)은 위조되고,
서버가 발급한 토큰도 복사될 수 있다. 그래서 토큰만 믿지 않고 ①비밀번호를 먼저
확인하고 ②승인된 기기인지 보고 ③언제든 끊을 수 있게 했다. 요청마다 다시
확인하므로, 승인을 취소하면 이미 로그인한 사람도 즉시 막힌다.

설정(Setting 테이블)
    cs_office_ips   사무실 IP. 쉼표로 구분하며 대역(CIDR)도 쓸 수 있다.
                    비워 두면 모든 접속이 기기 승인 대상이 된다.
"""

import hashlib
import ipaddress
import secrets
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .auth import create_access_token, get_current_user, hash_password, verify_password
from .database import get_db
from .models import (
    AdminAuditLog,
    CsDevice,
    Inquiry,
    InquiryStatus,
    OrderStatus,
    ORDER_STATUS_LABEL,
    Plan,
    PlanOrder,
    Role,
    School,
    SchoolVerification,
    Setting,
    Subscription,
    User,
)

router = APIRouter(prefix="/api/cs", tags=["cs"])

# 기기 승인 요청을 무한정 쌓아두지 않는다. 오래된 대기 건은 자동으로 지운다.
PENDING_DEVICE_TTL_DAYS = 14


# ── 공통 ──────────────────────────────────────────────────────


def client_ip(request: Optional[Request]) -> str:
    """nginx 뒤에 있으므로 X-Forwarded-For 를 먼저 본다."""
    if request is None:
        return ""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.get(Setting, key)
    return row.value if row and row.value is not None else default


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value
    db.commit()


def office_networks(db: Session) -> List[str]:
    raw = get_setting(db, "cs_office_ips", "")
    return [p.strip() for p in raw.split(",") if p.strip()]


def ip_allowed(ip: str, patterns: List[str]) -> bool:
    """등록된 IP·대역에 들어오는지 본다.

    형식이 잘못된 값 하나 때문에 전체 판정이 무너지지 않도록 개별로 감싼다.
    """
    if not ip or not patterns:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for pat in patterns:
        try:
            if addr in ipaddress.ip_network(pat, strict=False):
                return True
        except ValueError:
            continue
    return False


def audit(
    db: Session,
    request: Optional[Request],
    actor: Optional[User],
    action: str,
    target_type: str = "",
    target_id="",
    detail: str = "",
) -> None:
    """상담원 행위를 남긴다. 기록 실패가 업무를 막지는 않는다.

    개인정보 안전성 확보조치 기준 제8조. 관리자 로그와 같은 표에 쌓이고,
    action 이 'cs.' 로 시작하므로 나중에 구분해 볼 수 있다.
    """
    try:
        db.add(AdminAuditLog(
            actor_id=actor.id if actor else None,
            actor_email=(actor.email if actor else "")[:120],
            actor_role=(actor.role.value if actor and actor.role else "")[:20],
            action=action[:60],
            target_type=target_type[:40],
            target_id=str(target_id)[:40],
            detail=detail[:300],
            ip=client_ip(request)[:45],
            user_agent=(request.headers.get("user-agent", "") if request else "")[:200],
        ))
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"[CS 감사로그] 기록 실패: {exc}", flush=True)


def mask_email(value: str) -> str:
    """앞 두 글자만 남긴다. abcdefg@x.com -> ab*****@x.com"""
    if not value or "@" not in value:
        return value or ""
    local, _, domain = value.partition("@")
    if len(local) <= 2:
        return f"{local[:1]}*@{domain}"
    return f"{local[:2]}{'*' * (len(local) - 2)}@{domain}"


def mask_phone(value: str) -> str:
    """가운데를 가린다. 01012345678 -> 010-****-5678"""
    digits = "".join(c for c in (value or "") if c.isdigit())
    if len(digits) < 7:
        return "***" if digits else ""
    return f"{digits[:3]}-****-{digits[-4:]}"


# ── 기기·IP 관문 ───────────────────────────────────────────────


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def purge_stale_devices(db: Session) -> None:
    cutoff = datetime.utcnow() - timedelta(days=PENDING_DEVICE_TTL_DAYS)
    try:
        db.query(CsDevice).filter(
            CsDevice.status == "pending", CsDevice.created_at < cutoff
        ).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()


def find_device(db: Session, token: Optional[str]) -> Optional[CsDevice]:
    if not token:
        return None
    return db.query(CsDevice).filter(CsDevice.token_hash == hash_token(token)).first()


def gate(
    db: Session,
    request: Request,
    user: User,
    device_token: Optional[str],
) -> dict:
    """이 접속을 허용할지 판정한다.

    관리자는 기기 승인 대상이 아니다. 승인하는 사람이 승인을 못 받아 못
    들어오는 상황을 막기 위해서다. 대신 접속 기록은 남긴다.
    """
    ip = client_ip(request)
    if ip_allowed(ip, office_networks(db)):
        return {"how": "office_ip", "device": None}

    if user.role == Role.admin:
        return {"how": "admin", "device": None}

    device = find_device(db, device_token)
    if device is None or device.user_id != user.id:
        return {"how": "none", "device": None}
    if device.status == "approved":
        # 마지막 접속 기록만 조용히 갱신한다.
        device.last_ip = ip[:45]
        device.last_seen_at = datetime.utcnow()
        db.commit()
        return {"how": "device", "device": device}
    return {"how": device.status, "device": device}


def register_device(db: Session, request: Request, user: User) -> CsDevice:
    """새 기기의 승인 요청을 만들고 토큰을 발급한다."""
    purge_stale_devices(db)
    token = secrets.token_urlsafe(32)
    device = CsDevice(
        user_id=user.id,
        token_hash=hash_token(token),
        code=secrets.token_hex(3).upper(),
        status="pending",
        user_agent=request.headers.get("user-agent", "")[:200],
        first_ip=client_ip(request)[:45],
        last_ip=client_ip(request)[:45],
        last_seen_at=datetime.utcnow(),
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    device.plain_token = token  # 응답에만 실어 보내고 서버에는 남기지 않는다
    return device


def require_cs(
    request: Request,
    user: User = Depends(get_current_user),
    x_cs_device: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    """상담 사이트의 모든 요청이 지나는 관문.

    권한과 기기를 요청마다 다시 확인한다. 그래야 승인을 끊은 순간부터
    실제로 막힌다.
    """
    if user.role not in (Role.cs, Role.admin):
        raise HTTPException(status_code=403, detail="상담 사이트 접근 권한이 없습니다.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="사용할 수 없는 계정입니다.")

    result = gate(db, request, user, x_cs_device)
    if result["how"] in ("none", "pending", "revoked"):
        raise HTTPException(
            status_code=403,
            detail="승인되지 않은 기기입니다. 관리자 승인 후 다시 로그인해주세요.",
        )
    return user


def require_cs_admin(user: User = Depends(require_cs)) -> User:
    if user.role != Role.admin:
        raise HTTPException(status_code=403, detail="관리자만 할 수 있습니다.")
    return user


# ── 로그인 ────────────────────────────────────────────────────


class LoginIn(BaseModel):
    email: EmailStr
    password: str
    device_label: str = ""


@router.post("/login")
def cs_login(
    payload: LoginIn,
    request: Request,
    x_cs_device: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """상담원 로그인.

    비밀번호를 먼저 확인한 뒤에 기기를 본다. 그래야 아무나 승인 요청을
    쌓아둘 수 없다.
    """
    user = db.query(User).filter(User.email == str(payload.email).strip()).first()
    if not user or not verify_password(payload.password, user.password_hash):
        # 계정이 없는 것과 비밀번호가 틀린 것을 구분해 알리지 않는다.
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")
    if user.role not in (Role.cs, Role.admin):
        raise HTTPException(status_code=403, detail="상담 사이트 접근 권한이 없습니다.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="사용할 수 없는 계정입니다.")

    result = gate(db, request, user, x_cs_device)

    if result["how"] == "none":
        device = register_device(db, request, user)
        if payload.device_label:
            device.label = payload.device_label[:60]
            db.commit()
        audit(db, request, user, "cs.device_request", "cs_device", device.id,
              f"코드 {device.code}")
        return {
            "ok": False,
            "device_status": "pending",
            "device_token": device.plain_token,
            "device_code": device.code,
            "message": "새 기기입니다. 관리자 승인 후 이용할 수 있습니다.",
        }

    if result["how"] in ("pending", "revoked"):
        device = result["device"]
        audit(db, request, user, "cs.login_blocked", "cs_device",
              device.id if device else "", f"상태 {result['how']}")
        return {
            "ok": False,
            "device_status": result["how"],
            "device_code": device.code if device else "",
            "message": (
                "관리자 승인을 기다리는 중입니다."
                if result["how"] == "pending"
                else "이 기기는 사용이 중지되었습니다."
            ),
        }

    token = create_access_token(user)
    audit(db, request, user, "cs.login", "user", user.id, f"경로 {result['how']}")
    return {
        "ok": True,
        "token": token,
        "how": result["how"],
        # is_admin 을 여기서 함께 주지 않으면, 로그인 직후에는 관리자 메뉴가
        # 뜨지 않다가 새로고침해야 나타난다. /me 응답과 모양을 맞춘다.
        "user": {"id": user.id, "name": user.name, "email": user.email,
                 "role": user.role.value,
                 "is_admin": user.role == Role.admin,
                 "how": result["how"]},
    }


@router.get("/me")
def cs_me(request: Request, user: User = Depends(require_cs), db: Session = Depends(get_db)):
    # 화면 배지에 쓸 접속 경로. 판정은 require_cs 가 이미 끝냈으므로
    # 여기서는 표시용으로만 다시 본다(기기 기록을 건드리지 않는다).
    how = "office_ip" if ip_allowed(client_ip(request), office_networks(db)) else "device"
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role.value,
        "is_admin": user.role == Role.admin,
        "how": how,
        "ip": client_ip(request),
    }


# ── 대시보드 ──────────────────────────────────────────────────


@router.get("/summary")
def cs_summary(user: User = Depends(require_cs), db: Session = Depends(get_db)):
    """오늘 처리해야 할 것만 짧게 보여준다."""
    today = datetime.utcnow().date()
    return {
        "inquiries_pending": db.query(func.count(Inquiry.id)).filter(
            Inquiry.status == InquiryStatus.pending).scalar() or 0,
        "verifications_pending": db.query(func.count(SchoolVerification.id)).filter(
            SchoolVerification.status == "pending").scalar() or 0,
        "orders_pending": db.query(func.count(PlanOrder.id)).filter(
            PlanOrder.status == OrderStatus.pending).scalar() or 0,
        "plans_expiring": db.query(func.count(School.id)).filter(
            School.plan != Plan.free,
            School.plan_expires_at.isnot(None),
            School.plan_expires_at <= today + timedelta(days=30),
            School.plan_expires_at >= today,
        ).scalar() or 0,
    }


# ── 회원 조회 ─────────────────────────────────────────────────


def user_row(u: User, school_name: str = "", reveal: bool = False) -> dict:
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email if reveal else mask_email(u.email),
        "phone": (u.phone or "") if reveal else mask_phone(u.phone or ""),
        "role": u.role.value,
        "school_id": u.school_id,
        "school_name": school_name,
        "class_name": u.class_name or "",
        "department": u.department or "",
        "grade": u.grade,
        "is_active": bool(u.is_active),
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "masked": not reveal,
    }


@router.get("/users")
def cs_users(
    q: str = Query("", description="이름·이메일·연락처 일부"),
    role: str = "",
    limit: int = Query(30, le=100),
    offset: int = 0,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    """회원 검색. 목록에서는 연락처를 언제나 가린다."""
    query = db.query(User)
    term = q.strip()
    if term:
        digits = "".join(c for c in term if c.isdigit())
        conds = [User.name.ilike(f"%{term}%"), User.email.ilike(f"%{term}%")]
        if len(digits) >= 4:
            conds.append(User.phone.ilike(f"%{digits}%"))
        query = query.filter(or_(*conds))
    if role in ("student", "teacher", "school", "cs", "admin"):
        query = query.filter(User.role == Role(role))

    total = query.count()
    rows = (query.order_by(User.created_at.desc())
            .offset(offset).limit(limit).all())

    names = {}
    ids = [r.school_id for r in rows if r.school_id]
    if ids:
        names = dict(db.query(School.id, School.name).filter(School.id.in_(ids)).all())

    return {
        "total": total,
        "items": [user_row(r, names.get(r.school_id, "")) for r in rows],
    }


@router.get("/users/{user_id}")
def cs_user_detail(
    user_id: int,
    request: Request,
    reveal: bool = Query(False, description="연락처 원본 보기. 기록이 남는다."),
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="회원을 찾을 수 없습니다.")

    if reveal:
        # 마스킹을 푸는 것 자체가 개인정보 열람이다. 반드시 남긴다.
        audit(db, request, user, "cs.reveal_contact", "user", target.id,
              f"{target.name} 연락처 원본 열람")

    school_name = ""
    if target.school_id:
        s = db.get(School, target.school_id)
        school_name = s.name if s else ""

    sub = db.query(Subscription).filter(Subscription.user_id == target.id).first()
    verifications = (
        db.query(SchoolVerification)
        .filter(SchoolVerification.user_id == target.id)
        .order_by(SchoolVerification.created_at.desc())
        .limit(10).all()
    )
    v_names = {}
    v_ids = [v.school_id for v in verifications]
    if v_ids:
        v_names = dict(db.query(School.id, School.name).filter(School.id.in_(v_ids)).all())

    return {
        **user_row(target, school_name, reveal=reveal),
        "guardian_email": (target.guardian_email or "") if reveal
                          else mask_email(target.guardian_email or ""),
        "guardian_consent_at": target.guardian_consent_at.isoformat()
                               if target.guardian_consent_at else None,
        "must_change_password": bool(target.must_change_password),
        "subscription": None if sub is None else {
            "expires_at": sub.expires_at.isoformat() if sub.expires_at else None,
            "active": bool(sub.expires_at and sub.expires_at > datetime.utcnow()),
        },
        "verifications": [
            {
                "id": v.id,
                "school_id": v.school_id,
                "school_name": v_names.get(v.school_id, ""),
                "status": v.status,
                "class_name": v.class_name or "",
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in verifications
        ],
    }


class PasswordResetIn(BaseModel):
    reason: str = Field("", max_length=200)


@router.post("/users/{user_id}/password-reset")
def cs_send_password_reset(
    user_id: int,
    payload: PasswordResetIn,
    request: Request,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    """본인 확인이 끝난 회원에게 재설정 코드를 보낸다.

    상담원이 새 비밀번호를 정해 주지는 않는다. 알려준 비밀번호는 상담원이
    계정에 들어갈 수 있다는 뜻이라 사고가 나면 책임 소재가 흐려진다.
    """
    from .mailer import system_config, send_email
    from .models import PasswordReset

    target = db.get(User, user_id)
    if target is None or not target.is_active:
        raise HTTPException(status_code=404, detail="회원을 찾을 수 없습니다.")

    db.query(PasswordReset).filter(
        PasswordReset.user_id == target.id, PasswordReset.used.is_(False)
    ).update({PasswordReset.used: True}, synchronize_session=False)

    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(PasswordReset(
        user_id=target.id,
        code_hash=hashlib.sha256(code.encode()).hexdigest(),
        expires_at=datetime.utcnow() + timedelta(minutes=10),
    ))
    db.commit()

    cfg = system_config()
    if not cfg.is_ready():
        raise HTTPException(status_code=503, detail="메일 발송이 설정되지 않았습니다.")

    ok, err = send_email(
        cfg, target.email,
        "[우리동네 직업계고] 비밀번호 재설정 인증코드",
        f"{target.name}님, 비밀번호 재설정 인증코드는 아래와 같습니다.\n\n"
        f"    {code}\n\n"
        "이 코드는 10분 후 만료됩니다.\n"
        "본인이 요청하지 않았다면 이 메일을 무시하고 고객센터로 알려주세요.",
        from_name="우리동네 직업계고",
    )
    audit(db, request, user, "cs.password_reset_sent", "user", target.id,
          (payload.reason or "")[:200])
    if not ok:
        raise HTTPException(status_code=502, detail=f"메일 발송에 실패했습니다: {err}")
    return {"ok": True, "message": "재설정 코드를 회원 이메일로 보냈습니다."}


# ── 학교 ──────────────────────────────────────────────────────


@router.get("/schools")
def cs_schools(
    q: str = "",
    region: str = "",
    plan: str = "",
    limit: int = Query(30, le=100),
    offset: int = 0,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    query = db.query(School)
    if q.strip():
        query = query.filter(School.name.ilike(f"%{q.strip()}%"))
    if region:
        query = query.filter(School.region == region)
    if plan in ("free", "basic", "premium", "platinum"):
        query = query.filter(School.plan == Plan(plan))

    total = query.count()
    rows = query.order_by(School.name).offset(offset).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id": s.id,
                "name": s.name,
                "category": s.category,
                "region": s.region,
                "phone": s.phone or "",
                "plan": s.plan.value if s.plan else "free",
                "plan_expires_at": s.plan_expires_at.isoformat() if s.plan_expires_at else None,
                "plan_paused": bool(s.plan_paused),
                "is_visible": bool(s.is_visible),
                "view_count": s.view_count or 0,
            }
            for s in rows
        ],
    }


# 상담원이 고칠 수 있는 항목만 둔다. 플랜·노출·메일 설정은 여기 없다.
# search_aliases(검색 별칭)는 학교 계정에는 열어 주지 않는다 — 학교가 직접
# 넣게 하면 남의 학교 이름을 적어 검색을 가로챌 수 있어서, 운영자만 고친다.
SCHOOL_EDITABLE = (
    "phone", "website", "slogan", "intro", "departments",
    "facilities", "admission_info", "employment_rate",
    "student_count", "established_year", "search_aliases",
)


@router.get("/schools/{school_id}")
def cs_school_detail(
    school_id: int,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    s = db.get(School, school_id)
    if s is None:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")

    accounts = db.query(User).filter(User.school_id == s.id).all()
    orders = (db.query(PlanOrder).filter(PlanOrder.school_id == s.id)
              .order_by(PlanOrder.created_at.desc()).limit(10).all())
    return {
        "id": s.id,
        "name": s.name,
        "category": s.category,
        "region": s.region,
        "address": s.address,
        "plan": s.plan.value if s.plan else "free",
        "plan_expires_at": s.plan_expires_at.isoformat() if s.plan_expires_at else None,
        "plan_paused": bool(s.plan_paused),
        "plan_is_free_trial": bool(s.plan_is_free_trial),
        "is_visible": bool(s.is_visible),
        "view_count": s.view_count or 0,
        "editable": {k: getattr(s, k) for k in SCHOOL_EDITABLE},
        "accounts": [
            {"id": a.id, "name": a.name, "email": mask_email(a.email),
             "role": a.role.value, "is_active": bool(a.is_active)}
            for a in accounts
        ],
        "orders": [
            {"id": o.id, "plan": o.plan.value, "months": o.months,
             "amount": o.amount, "status": o.status.value,
             "status_label": ORDER_STATUS_LABEL.get(o.status.value, o.status.value),
             "deposit_code": o.deposit_code or "",
             "created_at": o.created_at.isoformat() if o.created_at else None}
            for o in orders
        ],
    }


class SchoolPatch(BaseModel):
    phone: Optional[str] = None
    website: Optional[str] = None
    slogan: Optional[str] = None
    intro: Optional[str] = None
    departments: Optional[str] = None
    facilities: Optional[str] = None
    admission_info: Optional[str] = None
    employment_rate: Optional[float] = None
    student_count: Optional[int] = None
    established_year: Optional[int] = None
    # 통용되는 다른 이름(쉼표 구분). 예: "경화EB고등학교,경화여자EB고"
    search_aliases: Optional[str] = None


@router.patch("/schools/{school_id}")
def cs_update_school(
    school_id: int,
    payload: SchoolPatch,
    request: Request,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    s = db.get(School, school_id)
    if s is None:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")

    changed = []
    for field in SCHOOL_EDITABLE:
        new = getattr(payload, field, None)
        if new is None:
            continue
        old = getattr(s, field)
        if old == new:
            continue
        setattr(s, field, new)
        changed.append(field)

    if "departments" in changed:
        # 학과가 바뀌면 계열 캐시를 다시 계산해야 검색에서 제대로 걸린다.
        try:
            from . import dept_fields as dept_fields_mod
            s.dept_fields = dept_fields_mod.to_storage(s.departments or "")
        except Exception as exc:
            print(f"[CS] 계열 재계산 실패: {exc}", flush=True)

    if not changed:
        return {"ok": True, "changed": []}

    db.commit()
    audit(db, request, user, "cs.school_update", "school", s.id,
          f"{s.name} — {', '.join(changed)}")
    return {"ok": True, "changed": changed}


# ── 문의 ──────────────────────────────────────────────────────


@router.get("/inquiries")
def cs_inquiries(
    status: str = "",
    school_id: Optional[int] = None,
    limit: int = Query(30, le=100),
    offset: int = 0,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    query = db.query(Inquiry)
    if status in ("pending", "answered"):
        query = query.filter(Inquiry.status == InquiryStatus(status))
    if school_id:
        query = query.filter(Inquiry.school_id == school_id)

    total = query.count()
    rows = (query.order_by(Inquiry.created_at.desc())
            .offset(offset).limit(limit).all())
    names = {}
    ids = [r.school_id for r in rows]
    if ids:
        names = dict(db.query(School.id, School.name).filter(School.id.in_(ids)).all())

    return {
        "total": total,
        "items": [
            {
                "id": r.id,
                "school_id": r.school_id,
                "school_name": names.get(r.school_id, ""),
                "asker_name": r.asker_name or "",
                "contact_email": mask_email(r.contact_email),
                "contact_phone": mask_phone(r.contact_phone or ""),
                "question": r.question,
                "status": r.status.value,
                "answer": r.answer or "",
                "delivery_status": r.delivery_status.value if r.delivery_status else "",
                "delivery_error": r.delivery_error or "",
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "answered_at": r.answered_at.isoformat() if r.answered_at else None,
            }
            for r in rows
        ],
    }


class AnswerIn(BaseModel):
    answer: str = Field(..., min_length=1)


@router.post("/inquiries/{inquiry_id}/answer")
def cs_answer_inquiry(
    inquiry_id: int,
    payload: AnswerIn,
    request: Request,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    """문의에 답하고 질문자 메일로, 포털 계정을 통해 보낸다."""
    from . import mailer
    from .models import DeliveryStatus

    inq = db.get(Inquiry, inquiry_id)
    if inq is None:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다.")

    s = db.get(School, inq.school_id)
    if s is None:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")

    inq.answer = payload.answer.strip()
    inq.status = InquiryStatus.answered
    inq.answered_at = datetime.utcnow()
    inq.answered_by = user.id

    subject = f"[{s.name}] 문의하신 내용에 대한 답변입니다."
    body = (
        f"{inq.asker_name or '문의자'}님, 안녕하세요.\n"
        f"{s.name}에 남겨주신 문의에 대한 답변을 보내드립니다.\n\n"
        "──────────────────────────────\n"
        f"[문의하신 내용]\n{inq.question}\n\n"
        f"[답변]\n{inq.answer}\n"
        "──────────────────────────────\n\n"
        "본 메일은 귀하가 직접 남기신 문의에 대한 답변으로 발송되었습니다.\n"
        "회신이 필요하시면 이 메일에 답장하지 마시고, 학교 대표번호로 문의해 주세요.\n"
        "※ 입력하신 개인정보는 답변 발송 목적으로만 이용되며, 보유기간이 지나면 파기됩니다."
    )

    # 학교 주소를 발신자로 위조하면 SPF/DKIM 에 걸려 스팸으로 빠진다.
    # 발신은 항상 포털 도메인으로 한다.
    cfg = mailer.system_config()

    if not cfg.is_ready():
        inq.delivery_status = DeliveryStatus.not_configured
        inq.delivery_error = "메일 발송 계정이 없어 이메일이 나가지 않았습니다."
        db.commit()
        audit(db, request, user, "cs.inquiry_answer", "inquiry", inq.id, "메일 미설정")
        return {"ok": True, "sent": False,
                "message": "답변은 저장했지만 메일 서버가 없어 발송하지 못했습니다."}

    body += (
        "\n\n──────────────────────────────\n"
        f"본 메일은 우리동네 직업계고 포털이 {s.name}의 답변을 대신 전달한 것입니다.\n"
        "추가 문의는 학교 대표번호"
        + (f"({s.phone})" if s.phone else "")
        + "로 연락해 주세요.\n"
    )

    ok, err = mailer.send_email(
        cfg, inq.contact_email, subject, body,
        from_name=f"{s.name} · 우리동네 직업계고",
    )
    inq.delivery_status = DeliveryStatus.sent if ok else DeliveryStatus.failed
    inq.delivery_error = "" if ok else str(err)[:300]
    db.commit()
    audit(db, request, user, "cs.inquiry_answer", "inquiry", inq.id,
          f"{s.name} / 발송 {'성공' if ok else '실패'}")
    return {"ok": True, "sent": bool(ok),
            "message": "답변을 보냈습니다." if ok else f"저장했으나 발송에 실패했습니다: {err}"}


# ── 재학생 인증 ────────────────────────────────────────────────


@router.get("/verifications")
def cs_verifications(
    status: str = "pending",
    limit: int = Query(30, le=100),
    offset: int = 0,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    query = db.query(SchoolVerification)
    if status in ("pending", "approved", "rejected"):
        query = query.filter(SchoolVerification.status == status)

    total = query.count()
    rows = (query.order_by(SchoolVerification.created_at.desc())
            .offset(offset).limit(limit).all())

    s_names = dict(db.query(School.id, School.name).filter(
        School.id.in_([r.school_id for r in rows] or [0])).all())
    students = {u.id: u for u in db.query(User).filter(
        User.id.in_([r.user_id for r in rows] or [0])).all()}

    return {
        "total": total,
        "items": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "student": students[r.user_id].name if r.user_id in students else "(탈퇴)",
                "student_email": mask_email(students[r.user_id].email)
                                 if r.user_id in students else "",
                "school_id": r.school_id,
                "school_name": s_names.get(r.school_id, ""),
                "status": r.status,
                "note": r.note or "",
                "class_name": r.class_name or "",
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


class VerificationDecideIn(BaseModel):
    decision: str = Field(..., pattern="^(approved|rejected)$")
    note: str = Field("", max_length=200)


@router.post("/verifications/{verification_id}/decide")
def cs_decide_verification(
    verification_id: int,
    payload: VerificationDecideIn,
    request: Request,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    v = db.get(SchoolVerification, verification_id)
    if v is None:
        raise HTTPException(status_code=404, detail="인증 신청을 찾을 수 없습니다.")
    if v.status != "pending":
        raise HTTPException(status_code=400, detail="이미 처리된 신청입니다.")

    v.status = payload.decision
    v.decided_at = datetime.utcnow()
    db.commit()
    audit(db, request, user, "cs.verification_decide", "school_verification", v.id,
          f"{payload.decision} {payload.note}".strip()[:300])
    return {"ok": True, "status": v.status}


# ── 결제·구독 ─────────────────────────────────────────────────


@router.get("/orders")
def cs_orders(
    status: str = "",
    q: str = Query("", description="학교명 또는 입금코드"),
    limit: int = Query(30, le=100),
    offset: int = 0,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    query = db.query(PlanOrder)
    if status in ("pending", "paid", "approved", "rejected", "expired"):
        query = query.filter(PlanOrder.status == OrderStatus(status))
    term = q.strip()
    if term:
        ids = [i for (i,) in db.query(School.id).filter(School.name.ilike(f"%{term}%")).all()]
        query = query.filter(or_(
            PlanOrder.deposit_code.ilike(f"%{term}%"),
            PlanOrder.school_id.in_(ids or [0]),
        ))

    total = query.count()
    rows = (query.order_by(PlanOrder.created_at.desc())
            .offset(offset).limit(limit).all())
    s_names = dict(db.query(School.id, School.name).filter(
        School.id.in_([r.school_id for r in rows] or [0])).all())

    return {
        "total": total,
        "items": [
            {
                "id": o.id,
                "school_id": o.school_id,
                "school_name": s_names.get(o.school_id, ""),
                "plan": o.plan.value,
                "months": o.months,
                "amount": o.amount,
                "status": o.status.value,
                "status_label": ORDER_STATUS_LABEL.get(o.status.value, o.status.value),
                "deposit_code": o.deposit_code or "",
                "note": o.note or "",
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "due_at": o.due_at.isoformat() if o.due_at else None,
                "paid_at": o.paid_at.isoformat() if o.paid_at else None,
            }
            for o in rows
        ],
    }


class ConfirmPaidIn(BaseModel):
    note: str = Field("", max_length=200)


@router.post("/orders/{order_id}/confirm-paid")
def cs_confirm_paid(
    order_id: int,
    payload: ConfirmPaidIn,
    request: Request,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    """통장에 입금이 들어온 것을 확인해 준다.

    여기까지가 상담원의 몫이다. 플랜을 실제로 켜는 최종 승인은 관리자만 한다.
    돈이 들어온 것을 확인하는 일과 서비스를 여는 일을 나눠 두면, 한 사람의
    실수나 착오로 유료 기능이 열리는 일이 없다.
    """
    o = db.get(PlanOrder, order_id)
    if o is None:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다.")
    if o.status != OrderStatus.pending:
        raise HTTPException(
            status_code=400,
            detail=f"입금 대기 상태인 주문만 확인할 수 있습니다. (현재 {ORDER_STATUS_LABEL.get(o.status.value, o.status.value)})",
        )

    o.status = OrderStatus.paid
    o.paid_at = datetime.utcnow()
    if payload.note:
        o.note = ((o.note or "") + f" / 입금확인: {payload.note}").strip()[:200]
    db.commit()
    audit(db, request, user, "cs.order_confirm_paid", "plan_order", o.id,
          f"{o.amount}원 {payload.note}".strip()[:300])
    return {"ok": True, "status": o.status.value,
            "message": "입금 확인으로 바꿨습니다. 최종 승인은 관리자가 합니다."}


@router.get("/subscriptions")
def cs_subscriptions(
    q: str = "",
    limit: int = Query(30, le=100),
    offset: int = 0,
    user: User = Depends(require_cs),
    db: Session = Depends(get_db),
):
    """기록해 개인 구독 현황. 조회만 한다."""
    query = db.query(Subscription, User).join(User, Subscription.user_id == User.id)
    term = q.strip()
    if term:
        query = query.filter(or_(User.name.ilike(f"%{term}%"),
                                 User.email.ilike(f"%{term}%")))
    total = query.count()
    rows = (query.order_by(Subscription.expires_at.desc())
            .offset(offset).limit(limit).all())
    now = datetime.utcnow()
    return {
        "total": total,
        "items": [
            {
                "user_id": u.id,
                "name": u.name,
                "email": mask_email(u.email),
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "expires_at": s.expires_at.isoformat() if s.expires_at else None,
                "active": bool(s.expires_at and s.expires_at > now),
            }
            for s, u in rows
        ],
    }


# ── 관리자 전용: 상담원·기기·IP ────────────────────────────────


@router.get("/admin/devices")
def cs_list_devices(
    status: str = "",
    user: User = Depends(require_cs_admin),
    db: Session = Depends(get_db),
):
    query = db.query(CsDevice, User).join(User, CsDevice.user_id == User.id)
    if status in ("pending", "approved", "revoked"):
        query = query.filter(CsDevice.status == status)
    rows = query.order_by(CsDevice.created_at.desc()).limit(200).all()
    return {
        "items": [
            {
                "id": d.id,
                "code": d.code,
                "label": d.label or "",
                "status": d.status,
                "user_id": u.id,
                "user_name": u.name,
                "user_email": u.email,
                "user_agent": d.user_agent or "",
                "first_ip": d.first_ip or "",
                "last_ip": d.last_ip or "",
                "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d, u in rows
        ]
    }


class DeviceDecideIn(BaseModel):
    decision: str = Field(..., pattern="^(approved|revoked)$")
    label: str = Field("", max_length=60)


@router.post("/admin/devices/{device_id}/decide")
def cs_decide_device(
    device_id: int,
    payload: DeviceDecideIn,
    request: Request,
    user: User = Depends(require_cs_admin),
    db: Session = Depends(get_db),
):
    d = db.get(CsDevice, device_id)
    if d is None:
        raise HTTPException(status_code=404, detail="기기를 찾을 수 없습니다.")
    d.status = payload.decision
    if payload.label:
        d.label = payload.label[:60]
    d.decided_by = user.id
    d.decided_at = datetime.utcnow()
    db.commit()
    audit(db, request, user, "cs.device_decide", "cs_device", d.id,
          f"{payload.decision} (코드 {d.code})")
    return {"ok": True, "status": d.status}


@router.delete("/admin/devices/{device_id}")
def cs_delete_device(
    device_id: int,
    request: Request,
    user: User = Depends(require_cs_admin),
    db: Session = Depends(get_db),
):
    d = db.get(CsDevice, device_id)
    if d is None:
        raise HTTPException(status_code=404, detail="기기를 찾을 수 없습니다.")
    code = d.code
    db.delete(d)
    db.commit()
    audit(db, request, user, "cs.device_delete", "cs_device", device_id, f"코드 {code}")
    return {"ok": True}


@router.get("/admin/agents")
def cs_list_agents(
    user: User = Depends(require_cs_admin),
    db: Session = Depends(get_db),
):
    rows = db.query(User).filter(User.role == Role.cs).order_by(User.created_at.desc()).all()
    counts = dict(
        db.query(CsDevice.user_id, func.count(CsDevice.id))
        .filter(CsDevice.status == "approved")
        .group_by(CsDevice.user_id).all()
    )
    return {
        "items": [
            {
                "id": u.id,
                "name": u.name,
                "email": u.email,
                "is_active": bool(u.is_active),
                "devices": counts.get(u.id, 0),
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in rows
        ]
    }


class AgentIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    email: EmailStr
    password: str = Field(..., min_length=8)


@router.post("/admin/agents")
def cs_create_agent(
    payload: AgentIn,
    request: Request,
    user: User = Depends(require_cs_admin),
    db: Session = Depends(get_db),
):
    email = str(payload.email).strip().lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="이미 쓰고 있는 이메일입니다.")
    agent = User(
        email=email,
        password_hash=hash_password(payload.password),
        name=payload.name.strip(),
        role=Role.cs,
        is_active=True,
        must_change_password=True,  # 첫 로그인 후 본인이 바꾸게 한다
        privacy_consent_at=datetime.utcnow(),
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    audit(db, request, user, "cs.agent_create", "user", agent.id, email)
    return {"ok": True, "id": agent.id}


class AgentPatch(BaseModel):
    is_active: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=8)


@router.patch("/admin/agents/{agent_id}")
def cs_update_agent(
    agent_id: int,
    payload: AgentPatch,
    request: Request,
    user: User = Depends(require_cs_admin),
    db: Session = Depends(get_db),
):
    agent = db.get(User, agent_id)
    if agent is None or agent.role != Role.cs:
        raise HTTPException(status_code=404, detail="상담원을 찾을 수 없습니다.")

    changed = []
    if payload.is_active is not None and bool(agent.is_active) != payload.is_active:
        agent.is_active = payload.is_active
        changed.append("사용중지 해제" if payload.is_active else "사용중지")
        if not payload.is_active:
            # 계정을 멈추면 기기도 함께 끊는다. 한쪽만 막으면 구멍이 남는다.
            db.query(CsDevice).filter(CsDevice.user_id == agent.id).update(
                {CsDevice.status: "revoked"}, synchronize_session=False)
    if payload.password:
        agent.password_hash = hash_password(payload.password)
        agent.must_change_password = True
        changed.append("비밀번호 재설정")

    if not changed:
        return {"ok": True, "changed": []}
    db.commit()
    audit(db, request, user, "cs.agent_update", "user", agent.id, ", ".join(changed))
    return {"ok": True, "changed": changed}


class OfficeIpsIn(BaseModel):
    ips: str = Field("", max_length=1000)


@router.get("/admin/office-ips")
def cs_get_office_ips(
    request: Request,
    user: User = Depends(require_cs_admin),
    db: Session = Depends(get_db),
):
    return {"ips": get_setting(db, "cs_office_ips", ""), "your_ip": client_ip(request)}


@router.put("/admin/office-ips")
def cs_set_office_ips(
    payload: OfficeIpsIn,
    request: Request,
    user: User = Depends(require_cs_admin),
    db: Session = Depends(get_db),
):
    """사무실 IP 를 저장한다. 형식이 틀린 값은 미리 걸러 알려준다."""
    parts = [p.strip() for p in payload.ips.split(",") if p.strip()]
    bad = []
    for p in parts:
        try:
            ipaddress.ip_network(p, strict=False)
        except ValueError:
            bad.append(p)
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"IP 형식이 올바르지 않습니다: {', '.join(bad)}",
        )
    set_setting(db, "cs_office_ips", ",".join(parts))
    audit(db, request, user, "cs.office_ips_set", "setting", "cs_office_ips",
          ",".join(parts)[:300])
    return {"ok": True, "ips": ",".join(parts)}


@router.get("/admin/audit")
def cs_audit_log(
    actor: str = "",
    action: str = "",
    limit: int = Query(50, le=200),
    offset: int = 0,
    user: User = Depends(require_cs_admin),
    db: Session = Depends(get_db),
):
    """상담원이 무엇을 했는지 본다. 상담원 본인은 볼 수 없다."""
    query = db.query(AdminAuditLog).filter(AdminAuditLog.action.like("cs.%"))
    if actor:
        query = query.filter(AdminAuditLog.actor_email.ilike(f"%{actor}%"))
    if action:
        query = query.filter(AdminAuditLog.action.ilike(f"%{action}%"))
    total = query.count()
    rows = (query.order_by(AdminAuditLog.created_at.desc())
            .offset(offset).limit(limit).all())
    return {
        "total": total,
        "items": [
            {
                "id": r.id,
                "actor_email": r.actor_email,
                "actor_role": r.actor_role,
                "action": r.action,
                "target_type": r.target_type,
                "target_id": r.target_id,
                "detail": r.detail,
                "ip": r.ip,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }
