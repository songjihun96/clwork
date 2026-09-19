import hashlib
import json
import os
import random
import re
import secrets
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import (BackgroundTasks, Depends, FastAPI, File, Form, HTTPException,
                     Query, Request, UploadFile)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session, selectinload

from . import schemas
from .auth import (
    create_access_token,
    get_current_user,
    get_current_user_optional,
    hash_password,
    require_admin,
    require_school,
    require_student,
    require_class_manager,
    require_teacher,
    verify_password,
)
from . import quiz as quiz_logic
from . import geo
from . import mailer
from . import sms
from . import toss
from . import spellcheck
from . import dept_fields as dept_fields_mod
from . import ai
from . import articles as articles_mod
from .database import Base, SessionLocal, engine, get_db
from .models import (
    PLAN_PRICE,
    Setting,
    Subscription,
    SubscriptionOrder,
    CoverLetter,
    PLAN_RANK,
    AdmissionEvent,
    AdminAuditLog,
    Article,
    Coed,
    DeliveryStatus,
    Favorite,
    GuardianConsent,
    Inquiry,
    InquiryStatus,
    JournalEntry,
    Notice,
    NoticeRead,
    PhoneVerification,
    ORDER_STATUS_LABEL,
    OrderStatus,
    PasswordReset,
    Plan,
    PlanGrant,
    PlanOrder,
    QuizTaken,
    Role,
    School,
    SchoolVerification,
    SchoolExposure, SchoolSubject,
    SchoolView,
    SchoolViewHit,
    User,
    QuizDemand,
)

Base.metadata.create_all(bind=engine)

# 업로드 파일 저장 위치. /api/uploads 로 서빙하므로 nginx 설정 변경이 필요 없다.
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _ensure_enum_values() -> None:
    """PostgreSQL은 이미 만들어진 ENUM 타입에 새 값을 자동으로 추가하지 않는다.
    Role에 'teacher', OrderStatus에 'paid'/'expired' 를 새로 넣었으므로
    DB의 enum 타입에도 반영한다. (SQLite는 문자열이라 할 일이 없다)"""
    if engine.dialect.name != "postgresql":
        return
    from sqlalchemy import text

    try:
        # 기존 라벨로 enum 타입을 찾아 새 값을 추가한다.
        wanted = {"school": ("teacher", "cs"), "approved": ("paid", "expired")}
        plan = []
        with engine.connect() as conn:
            for anchor, labels in wanted.items():
                rows = conn.execute(
                    text(
                        "SELECT DISTINCT t.typname FROM pg_type t "
                        "JOIN pg_enum e ON e.enumtypid = t.oid "
                        "WHERE e.enumlabel = :anchor"
                    ),
                    {"anchor": anchor},
                ).fetchall()
                for r in rows:
                    plan.append((r[0], labels))

        # ALTER TYPE ... ADD VALUE 는 트랜잭션 밖(AUTOCOMMIT)에서 실행해야 안전하다.
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            for tname, labels in plan:
                for label in labels:
                    conn.execute(
                        text(f'ALTER TYPE "{tname}" ADD VALUE IF NOT EXISTS \'{label}\'')
                    )
    except Exception as exc:  # 실패해도 서버는 뜨게 하고 로그만 남긴다
        print(f"[warn] enum 값 보강 실패: {exc}")


_ensure_enum_values()


def _ensure_columns() -> None:
    """create_all은 기존 테이블에 새 컬럼을 추가하지 못한다.
    이미 만들어진 DB에 새 컬럼이 없으면 여기서 보강한다.
    SQLite와 PostgreSQL의 타입 표기가 달라 방언별로 DDL을 고른다."""
    from sqlalchemy import inspect, text

    is_pg = engine.dialect.name == "postgresql"
    bool_default = "BOOLEAN DEFAULT FALSE" if is_pg else "BOOLEAN DEFAULT 0"
    ts_type = "TIMESTAMP" if is_pg else "DATETIME"

    inspector = inspect(engine)
    plan = {
        "schools": {
            "plan_is_free_trial": "BOOLEAN DEFAULT FALSE" if is_pg else "BOOLEAN DEFAULT 0",
            "plan_granted_note": "VARCHAR(200) DEFAULT ''",
            # 플랜이 끝난 흔적. 안 남기면 연장을 놓친 학교를 못 찾는다.
            "plan_expired_at": "DATE",
            "plan_expired_from": "VARCHAR(20) DEFAULT ''",
            "mail_host": "VARCHAR(120) DEFAULT ''",
            "mail_port": "INTEGER DEFAULT 587",
            "mail_username": "VARCHAR(120) DEFAULT ''",
            "mail_password_enc": "TEXT DEFAULT ''",
            "mail_from": "VARCHAR(120) DEFAULT ''",
            "mail_ssl": bool_default,
            "is_visible": "BOOLEAN DEFAULT TRUE" if is_pg else "BOOLEAN DEFAULT 1",
            "dept_fields": "VARCHAR(200) DEFAULT ''",
            "plan_paused": bool_default,
            "search_aliases": "VARCHAR(300) DEFAULT ''",
            "youtube_urls": "TEXT DEFAULT ''",
            "inquiry_notify_email": "VARCHAR(120) DEFAULT ''",
        },
        # 새 표는 create_all 이 만들어 주지만, 이미 만들어진 뒤에 늘린 칸은
        # 여기 적어야 한다.
        "video_transcripts": {
            "stage": "VARCHAR(16) DEFAULT ''",
            "started_at": ts_type,
        },
        "users": {
            "phone": "VARCHAR(30) DEFAULT ''",
            "privacy_consent_at": ts_type,
            "birth_date": "DATE",
            "department": "VARCHAR(60) DEFAULT ''",
            "grade": "INTEGER",
            "guardian_email": "VARCHAR(120) DEFAULT ''",
            "guardian_consent_at": ts_type,
            "class_name": "VARCHAR(40) DEFAULT ''",
            "must_change_password": bool_default,
        },
        "admission_events": {
            "kind": "VARCHAR(20) DEFAULT 'admission'",
            "start_time": "VARCHAR(5)",
            "end_time": "VARCHAR(5)",
            "location": "VARCHAR(200) DEFAULT ''",
            "registration_url": "VARCHAR(500) DEFAULT ''",
        },
        "plan_orders": {
            "deposit_code": "VARCHAR(30) DEFAULT ''",
            "tax_email": "VARCHAR(255) DEFAULT ''",
            "tax_manager": "VARCHAR(60) DEFAULT ''",
            "due_at": ts_type,
            "paid_at": ts_type,
        },
        "notices": {
            "image_url": "VARCHAR(300) DEFAULT ''",
        },
        "school_verifications": {
            "class_name": "VARCHAR(40) DEFAULT ''",
            "teacher_id": "INTEGER",
        },
        # 산 사람에게 영상을 열어 주려면 신청이 계정에 묶여 있어야 한다.
        "service_applications": {
            "user_id": "INTEGER",
        },
        # 브라우저로 전화를 받는 기능을 넣으며 늘어난 컬럼.
        "cs_counselor_profiles": {
            "sip_uri": "VARCHAR(200) DEFAULT ''",
            "sip_uri_expires_at": ts_type,
        },
    }
    # 대상 테이블이 아직 없으면(완전 새 DB) create_all이 모델대로 만들었으므로 건너뛴다.
    existing_tables = set(inspector.get_table_names())
    for table, additions in plan.items():
        if table not in existing_tables:
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        missing = {k: v for k, v in additions.items() if k not in existing}
        if not missing:
            continue
        with engine.begin() as conn:
            for col, ddl in missing.items():
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))


_ensure_columns()


# ── 관리자 활동 기록 ───────────────────────────────────────────
# 개인정보 안전성 확보조치 기준 제8조: 개인정보취급자의 접속·처리 기록을
# 최소 1년 보관한다. 보관 기간이 지난 기록은 자동으로 지운다.
AUDIT_RETENTION_DAYS = 365


def write_audit(
    db: Session,
    request: Optional[Request],
    actor: Optional[User],
    action: str,
    target_type: str = "",
    target_id="",
    detail: str = "",
) -> None:
    """관리자 행위를 한 줄 남긴다. 실패해도 본 기능을 막지 않는다."""
    try:
        ip = ""
        agent = ""
        if request is not None:
            ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
                  or (request.client.host if request.client else ""))
            agent = request.headers.get("user-agent", "")[:200]
        db.add(AdminAuditLog(
            actor_id=actor.id if actor else None,
            actor_email=(actor.email if actor else "")[:120],
            actor_role=(actor.role.value if actor and actor.role else "")[:20],
            action=action[:60],
            target_type=target_type[:40],
            target_id=str(target_id)[:40],
            detail=detail[:300],
            ip=ip[:45],
            user_agent=agent,
        ))
        db.commit()
    except Exception as exc:  # 기록 실패가 서비스를 멈추면 안 된다
        db.rollback()
        print(f"[감사로그] 기록 실패: {exc}", flush=True)


def purge_expired_verifications(db: Session) -> None:
    """목적을 다한 본인확인 기록을 파기한다.

    개인정보 보호법 제21조는 처리 목적을 달성하면 지체 없이 파기하도록 한다.
    인증번호 기록에는 휴대폰번호와 요청 IP가 남으므로 오래 두지 않는다.
    - 인증번호 기록: 발급 24시간 후 삭제(재발송 제한 계산에 1시간만 쓰인다)
    - 법정대리인 동의 요청: 동의 없이 만료된 건만 삭제.
      동의한 건은 동의 사실을 입증할 자료라 남긴다.
    """
    try:
        now = datetime.utcnow()
        db.query(PhoneVerification).filter(
            PhoneVerification.created_at < now - timedelta(hours=24)
        ).delete(synchronize_session=False)
        db.query(GuardianConsent).filter(
            GuardianConsent.consented_at.is_(None),
            GuardianConsent.expires_at < now - timedelta(days=1),
        ).delete(synchronize_session=False)
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"[파기] 실패: {exc}", flush=True)


def purge_old_audit_logs(db: Session) -> int:
    """보관 기간(1년)이 지난 기록을 지운다."""
    cutoff = datetime.utcnow() - timedelta(days=AUDIT_RETENTION_DAYS)
    n = db.query(AdminAuditLog).filter(AdminAuditLog.created_at < cutoff).delete()
    db.commit()
    return n


# 플랜 가격: 관리자가 설정하면 DB(settings)에 저장하고, 없으면 코드 기본값을 쓴다.
def get_plan_price(db: Session, plan: Plan) -> int:
    row = db.query(Setting).filter(Setting.key == f"plan_price_{plan.value}").first()
    if row and str(row.value).isdigit():
        return int(row.value)
    return PLAN_PRICE.get(plan, 0)


def get_plan_price_year(db: Session, plan: Plan) -> int:
    """1년치를 한 번에 낼 때의 값.

    **안 정해 두면 월 가격 × 12 다.** 0 을 "1년에 0원"으로 읽으면 관리자가
    이 칸을 비워 둔 순간 공짜가 되어 버린다.
    """
    row = db.query(Setting).filter(
        Setting.key == f"plan_price_year_{plan.value}").first()
    if row and str(row.value).isdigit() and int(row.value) > 0:
        return int(row.value)
    return get_plan_price(db, plan) * 12


def plan_amount(db: Session, plan: Plan, months: int) -> int:
    """이 플랜을 이 기간만큼 쓸 때 낼 금액.

    12개월이 찰 때마다 연 가격을 쓰고, 남는 달만 월 가격으로 센다.
    (예: 15개월 = 연 1 + 월 3)

    이 계산을 한 곳에 모아 둔다 — 신청 화면과 실제 청구가 각자 계산하면
    화면에 보인 값과 입금 요청액이 어긋나고, 그건 돈 문제라 그냥 사고다.
    """
    months = max(int(months or 0), 0)
    years, rest = divmod(months, 12)
    return get_plan_price_year(db, plan) * years + get_plan_price(db, plan) * rest


BANK_KEYS = ("bank_name", "bank_account", "bank_holder", "payment_note", "due_days")
BANK_DEFAULTS = {
    "bank_name": "",
    "bank_account": "",
    "bank_holder": "특성화고신문",
    "payment_note": "입금자명에 아래 입금 코드를 포함해 주세요. 세금계산서는 요청 시 발행해 드립니다.",
    "due_days": "14",
}


# ---------- 상단 메뉴 공개 여부 ----------
#
# 아직 준비가 안 된 메뉴를 내려 두기 위한 것이다(영상을 다 찍기 전의 특강처럼).
# 배포로 메뉴를 넣었다 뺐다 하면 그때마다 zip 을 다시 올려야 해서, 결국
# 준비가 덜 된 채로 열어 두게 된다.
#
# **메뉴만 감춘다.** 주소를 직접 치면 열린다 — 유료 서비스 신청처럼 그 안에
# 이미 걸어 둔 길이 있을 수 있어서, 여기서 통째로 막으면 그 링크까지 죽는다.
# 서버가 실제로 막아야 하는 것(숏츠 영상)은 그쪽에 따로 잠금이 있다.
NAV_KEYS = ("search", "events", "special", "quiz")
NAV_LABEL = {
    "search": "학교 검색", "events": "학교 일정",
    "special": "온라인 직업계고 설명회", "quiz": "진로 테스트",
}


def get_nav(db: Session) -> dict:
    rows = db.query(Setting).filter(
        Setting.key.in_([f"nav_{k}" for k in NAV_KEYS])).all()
    saved = {r.key.replace("nav_", "", 1): r.value for r in rows}
    # 설정한 적이 없으면 켜진 것으로 본다 — 지금까지 보이던 메뉴가 이 기능을
    # 넣었다는 이유만으로 사라지면 안 된다.
    return {k: saved.get(k, "true") != "false" for k in NAV_KEYS}


def set_nav(db: Session, data: dict) -> None:
    for k in NAV_KEYS:
        if k not in data:
            continue
        key = f"nav_{k}"
        row = db.query(Setting).filter(Setting.key == key).first()
        if row is None:
            row = Setting(key=key)
            db.add(row)
        row.value = "true" if data[k] else "false"
    db.commit()


# ---------- 플로팅 버튼 (오른쪽 아래 동그란 버튼) ----------
FAB_KEYS = ("enabled", "url", "label", "roles", "action")
FAB_DEFAULTS = {
    "enabled": "false",
    "url": "",
    "label": "문의하기",
    "roles": "school,teacher",   # 이 역할의 계정에게만 보인다
    # 눌렀을 때 무엇을 하는가.
    #   link    — 등록한 주소를 새 탭으로 연다(원래 동작)
    #   inquiry — 교육·컨설팅 문의 폼을 그 자리에서 띄운다
    # 폼을 띄우는 쪽은 보던 화면을 잃지 않는다. 새 탭으로 보내면 문의를
    # 그만두는 순간 처음 보던 자리로 못 돌아온다.
    "action": "link",
}


def get_fab(db: Session) -> dict:
    out = dict(FAB_DEFAULTS)
    rows = db.query(Setting).filter(Setting.key.in_([f"fab_{k}" for k in FAB_KEYS])).all()
    for r in rows:
        key = r.key.replace("fab_", "", 1)
        if key in out and r.value is not None:
            out[key] = r.value
    return {
        "enabled": out["enabled"] == "true",
        "url": out["url"],
        "label": out["label"],
        "roles": [x for x in out["roles"].split(",") if x],
        "action": out["action"] if out["action"] in ("link", "inquiry") else "link",
    }


def set_fab(db: Session, data: dict) -> None:
    for k in FAB_KEYS:
        if k not in data or data[k] is None:
            continue
        value = data[k]
        if k == "enabled":
            value = "true" if value else "false"
        elif k == "roles":
            value = ",".join(value) if isinstance(value, list) else str(value)
        key = f"fab_{k}"
        row = db.query(Setting).filter(Setting.key == key).first()
        if row:
            row.value = str(value)
        else:
            db.add(Setting(key=key, value=str(value)))
    db.commit()


def get_bank_info(db: Session) -> dict:
    """관리자가 설정한 입금 계좌 정보."""
    out = dict(BANK_DEFAULTS)
    rows = db.query(Setting).filter(Setting.key.in_([f"bank_{k}" for k in BANK_KEYS])).all()
    for r in rows:
        key = r.key.replace("bank_", "", 1)
        if key in out and r.value is not None:
            out[key] = r.value
    return out


def set_bank_info(db: Session, data: dict) -> None:
    for k in BANK_KEYS:
        if k not in data or data[k] is None:
            continue
        key = f"bank_{k}"
        row = db.query(Setting).filter(Setting.key == key).first()
        if row:
            row.value = str(data[k])
        else:
            db.add(Setting(key=key, value=str(data[k])))
    db.commit()


def make_deposit_code(db: Session) -> str:
    """입금자명에 넣을 고유 코드. 헷갈리는 글자(0,O,1,I)는 뺀다."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    for _ in range(30):
        code = "UDJ-" + "".join(random.choices(alphabet, k=4))
        if not db.query(PlanOrder).filter(PlanOrder.deposit_code == code).first():
            return code
    return "UDJ-" + secrets.token_hex(3).upper()


def get_plan_perk_keys(db: Session, plan: Plan) -> List[str]:
    """이 플랜에서 켜져 있는 혜택 항목의 키 목록.

    학교 목록·지도를 만들 때 학교마다 여러 번 불린다(530개면 1,500회 이상).
    매번 settings 를 읽으면 그것만으로 요청이 100ms 넘게 걸리므로,
    요청 단위(Session 수명)로 결과를 기억해 둔다. 세션은 요청마다 새로
    만들어지므로 설정을 바꾸면 다음 요청부터 바로 반영된다.
    """
    cache = getattr(db, "_perk_key_cache", None)
    if cache is None:
        cache = {}
        try:
            db._perk_key_cache = cache
        except AttributeError:
            cache = None
    if cache is not None and plan in cache:
        return cache[plan]

    result = _load_plan_perk_keys(db, plan)
    if cache is not None:
        cache[plan] = result
    return result


def _load_plan_perk_keys(db: Session, plan: Plan) -> List[str]:
    row = db.query(Setting).filter(Setting.key == f"plan_perks_{plan.value}").first()
    if row and row.value:
        try:
            items = json.loads(row.value)
            if isinstance(items, list):
                # 카탈로그에 있는 키만 인정한다(옛 형식·삭제된 항목은 무시)
                return [k for k in items if k in PERK_LABEL]
        except (ValueError, TypeError):
            pass
    return list(PLAN_DEFAULT_PERKS.get(plan, []))


def get_plan_perks(db: Session, plan: Plan) -> List[str]:
    """화면에 보여줄 혜택 문구 목록. 카탈로그 순서를 따른다."""
    enabled = set(get_plan_perk_keys(db, plan))
    return [label for key, label in PERK_CATALOG if key in enabled]


def set_plan_perk_keys(db: Session, plan: Plan, keys: List[str]) -> None:
    valid = [k for k in keys if k in PERK_LABEL]
    value = json.dumps(valid, ensure_ascii=False)
    key = f"plan_perks_{plan.value}"
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))
    db.commit()


def set_plan_price(db: Session, plan: Plan, price: int, per: str = "month") -> None:
    key = ("plan_price_" if per == "month" else "plan_price_year_") + plan.value
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        row.value = str(price)
    else:
        db.add(Setting(key=key, value=str(price)))
    db.commit()


app = FastAPI(title="우리동네 직업계고(ㅇㅈ) API", version="1.0.0")

# 배포 시에는 환경변수 ALLOWED_ORIGINS 에 실제 사이트 주소를 넣는다.
#   예) ALLOWED_ORIGINS=https://udt.example.com,https://www.udt.example.com
# nginx 리버스 프록시로 프론트와 API를 같은 도메인에 묶으면 사실 CORS가
# 필요 없지만, 다른 도메인/서브도메인을 쓰거나 직접 API를 부를 때를 대비해 둔다.
_allowed = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]

_cors_kwargs = dict(
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
if _allowed:
    # 운영: 지정한 도메인만 허용
    _cors_kwargs["allow_origins"] = _allowed
else:
    # 로컬/모바일 테스트: localhost와 사설 IP 대역 허용
    _cors_kwargs["allow_origin_regex"] = (
        r"http://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|"
        r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
        r"172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}):(5173|5174|5175|4173)"
    )

app.add_middleware(CORSMiddleware, **_cors_kwargs)

# 업로드된 이미지 서빙. /api 아래에 두어 nginx 프록시를 그대로 탄다.
app.mount("/api/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# 롱폼·숏츠 영상. 숏츠에서 롱폼의 정확한 초로 이어 주는 것이 목적이라
# 재생을 우리가 쥐고 있어야 해서 파일도 직접 서빙한다.
from . import videos as _videos


# HEAD 도 받는다. 예전 StaticFiles 는 받아 줬고, 재생기·프록시가 본편을
# 받기 전에 HEAD 로 길이와 형식을 먼저 물어보는 경우가 있다.
@app.api_route("/api/media/{name}", methods=["GET", "HEAD"])
def serve_media(name: str, db: Session = Depends(get_db)):
    """영상 파일. 예전에는 StaticFiles 로 통째로 열어 뒀다.

    **파는 영상이 생기면서 그럴 수 없게 됐다.** 잠근 길(/api/graduate-video/
    stream)을 아무리 잘 만들어도 이 폴더가 열려 있으면 옆문이 열린 셈이라,
    파일 이름만 알면 원본을 그냥 받아 간다. 그래서 파는 영상에 붙은 파일은
    여기서 거른다 — 무료 영상은 예전과 똑같이 나간다.
    """
    # 파일 이름만 받는다. ../ 로 폴더를 거슬러 올라가지 못하게 자른다.
    safe = os.path.basename(name or "")
    if not safe or safe != name:
        raise HTTPException(status_code=404, detail="없는 파일입니다.")
    try:
        blocked = _paidvideo.protected_filenames(db)
    except Exception:
        # 판단을 못 하면 내보내지 않는다. 무료 영상이 잠깐 안 나오는 쪽이
        # 파는 영상이 새어 나가는 쪽보다 낫다.
        raise HTTPException(status_code=503, detail="잠시 후 다시 시도해 주세요.")
    if safe in blocked:
        raise HTTPException(status_code=403, detail="시청 권한이 필요한 영상입니다.")
    path = os.path.join(_videos.MEDIA_DIR, safe)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="없는 파일입니다.")
    return FileResponse(path)


app.include_router(_videos.router)

# 온라인 직업계고설명회(강사 프로필 등).
from . import briefing as _briefing
app.include_router(_briefing.router)

# 유료 서비스 신청 접수(컨설팅·상담·영상).
from . import applications as _applications
app.include_router(_applications.router)

# 진로 테스트 추천 학과 챗봇. 사실은 정보표에서만, 말투는 Claude 가 맡는다.
from . import career_chat as _career_chat
app.include_router(_career_chat.router)

# 돈을 낸 사람만 보는 영상. /api/media 정적 폴더를 안 타고 따로 흘려보낸다.
from . import paidvideo as _paidvideo
app.include_router(_paidvideo.router)

# 형제 서비스(기록해) 전용 서버 간 API. 브라우저가 아니라 기록해 서버만 부른다.
from . import partner as _partner
app.include_router(_partner.router)

# 상담 사이트(udjcs.ggm.kr) 전용 API. 권한이 제한된 상담원만 쓴다.
from . import cs as _cs
app.include_router(_cs.router)

# 전화 상담(콜센터). 관문은 위 cs.py 와 같은 것을 쓰고 파일만 나눠 두었다.
# 전화망 자체는 app/phone/ 이 맡는다. 사업자를 바꿔도 이 아래는 손대지 않는다.
from . import callcenter as _cc
from .callcenter import intake as _cc_intake
app.include_router(_cc.router)
# 전화망이 우리에게 물어보는 자리(VoiceML). 인증 없이 열려 있고 서명으로만 막는다.
app.include_router(_cc.voice_router)
# 통화 음성 중계. 워커 1개짜리 별도 프로세스(udt-audio)에서만 실제로 쓰인다.
app.include_router(_cc.audio_router)

# 서버·트래픽 감시. 바탕화면 위젯이 /api/monitor/snapshot 하나만 부른다.
from . import monitor as _monitor
app.include_router(_monitor.router)


@app.on_event("startup")
async def _callcenter_startup() -> None:
    """링 타임아웃을 넘기는 배경 타이머를 띄운다.

    워커마다 하나씩 뜨지만, 넘김이 ring_step 을 조건으로 건 UPDATE 라서
    같은 전화가 두 번 넘어가지 않는다(callcenter/engine.py 참고).
    """
    _seed_inquiry_types()
    await _cc.start_background()
    # 1분마다 서버 상태를 한 줄씩 남긴다(그래프·증가율·가동률의 원재료).
    _monitor.start_sampler()


@app.on_event("shutdown")
async def _callcenter_shutdown() -> None:
    await _cc.stop_background()


def _seed_inquiry_types() -> None:
    """문의 유형이 하나도 없으면 기본값을 넣는다.

    빈 드롭다운을 보면 상담원이 유형을 안 고르고, 그러면 통계가 통째로
    비어버린다. 관리자가 나중에 얼마든지 바꿀 수 있다.
    """
    from .models import CsInquiryType

    db = SessionLocal()
    try:
        if db.query(CsInquiryType).count() > 0:
            return
        defaults = [
            "학교 정보 문의", "회원가입·로그인", "재학생 인증",
            "구독·결제", "일지(기록해)", "제휴·광고", "기타",
        ]
        for i, name in enumerate(defaults):
            db.add(CsInquiryType(name=name, sort_order=(i + 1) * 10))
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"[warn] 문의 유형 기본값 생성 실패: {exc}")
    finally:
        db.close()

# NEIS 수집 전에도 드롭다운이 비어 보이지 않도록 두는 기본값.
# 실제 목록은 수집된 학교에서 뽑아 쓴다.
REGION_ORDER = [
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
    "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
]

CATEGORY_ORDER = [
    "특성화고", "마이스터고", "종합고", "특목고", "과학고", "외국어고", "국제고",
    "예술고", "체육고", "자율고", "일반고",
]


# 모든 플랜에 항상 제공되는 기본 기능. 토글 대상이 아니다.
BASE_FEATURES = [
    ("listing", "검색 결과 노출"),
    ("basic_info", "기본 정보 등록"),
    ("intro", "학교 소개 작성"),
    ("profile_detail", "학과·시설 상세 등록"),
    ("hero_image", "대표 이미지 노출"),
    ("inquiry_mail", "문의 답변 메일 발송"),
    ("quick_inquiry", "빠른 문의 배지"),
    ("teacher_accounts", "선생님 계정 발급"),
]
BASE_FEATURE_KEYS = {k for k, _ in BASE_FEATURES}

# 플랜별로 켜고 끄는 '유료 혜택'. 관리자가 관리자 화면에서 조정한다.
PERK_CATALOG = [
    ("search_upper", "일반 학교보다 상단 노출"),
    ("search_pin", "검색 결과 상위 고정"),
    ("search_top", "검색 결과 최상단 고정"),
    ("card_highlight", "검색 카드 색상 강조"),
    ("events", "참가 행사 일정 등록"),
    ("briefing", "학교 설명회 일정 등록"),
    ("banner", "추천 학교 배너 노출"),
    ("article_priority", "메인 소식 우선 노출"),
    ("stats_views", "조회수 통계"),
    ("stats_daily", "일자별 상세 통계"),
    ("stats_favorite", "즐겨찾기 전환 분석"),
]
PERK_LABEL = dict(PERK_CATALOG)

# 플랜별 기본으로 켜져 있는 유료 혜택
PLAN_DEFAULT_PERKS = {
    Plan.free: [],
    Plan.basic: ["search_upper", "events", "stats_views"],
    Plan.premium: ["search_upper", "search_pin", "card_highlight", "events",
                   "briefing", "article_priority", "stats_views", "stats_daily"],
    Plan.platinum: [k for k, _ in PERK_CATALOG],  # 전체
}


PLAN_META = {
    Plan.free: {
        "label": "무료",
        "perks": ["검색 결과 노출", "기본 정보 등록", "학교 소개 작성"],
    },
    Plan.basic: {
        "label": "베이직",
        "perks": ["일반 학교보다 상단 노출", "참가 행사 일정 등록", "조회수 통계"],
    },
    Plan.premium: {
        "label": "프리미엄",
        "perks": ["베이직 혜택 전체", "검색 결과 상위 고정", "대표 이미지 노출", "일자별 상세 통계"],
    },
    Plan.platinum: {
        "label": "플래티넘",
        "perks": ["프리미엄 혜택 전체", "검색 결과 최상단 고정", "추천 학교 배너 노출", "즐겨찾기 전환 분석"],
    },
}


# ============================================================
# 공통 헬퍼
# ============================================================
def expire_plans(db: Session) -> None:
    """만료일이 지난 유료 플랜을 무료로 되돌린다."""
    today = date.today()
    stale = (
        db.query(School)
        .filter(School.plan != Plan.free, School.plan_expires_at.isnot(None))
        .filter(School.plan_expires_at < today)
        .all()
    )
    for s in stale:
        # 무료로 되돌리기 **전에** 흔적을 남긴다. 되돌리고 나면 언제 무엇이
        # 끝났는지 알 길이 없어, 연장을 놓친 학교를 찾아낼 수 없다.
        s.plan_expired_at = s.plan_expires_at
        s.plan_expired_from = s.plan.value
        s.plan = Plan.free
        s.plan_expires_at = None
        s.plan_is_free_trial = False
        s.plan_granted_note = ""
    if stale:
        db.commit()


PLAN_ORDER_SQL = case(
    (School.plan == Plan.platinum, 3),
    (School.plan == Plan.premium, 2),
    (School.plan == Plan.basic, 1),
    else_=0,
)



def school_has_perk(db: Session, school: School, perk_key: str) -> bool:
    """이 학교의 현재 플랜에서 해당 혜택이 켜져 있는지.
    플랜이 일시정지면 무료 플랜 기준으로 판정한다."""
    if perk_key in BASE_FEATURE_KEYS:
        return True   # 기본 기능은 플랜과 무관하게 항상 제공
    if school is None:
        return False
    plan = Plan.free if school.plan_paused else school.plan
    return perk_key in set(get_plan_perk_keys(db, plan))


def plans_with_perk(db: Session, perk_key: str) -> List[Plan]:
    """해당 혜택이 켜져 있는 플랜 목록. 검색 정렬·필터에 쓴다."""
    if perk_key in BASE_FEATURE_KEYS:
        return [Plan.free, Plan.basic, Plan.premium, Plan.platinum]
    return [
        p for p in (Plan.free, Plan.basic, Plan.premium, Plan.platinum)
        if perk_key in set(get_plan_perk_keys(db, p))
    ]


def plan_order_sql(db: Session):
    """검색 노출 우선순위를 혜택 설정에 따라 만든다.
    최상단 고정(3) > 상위 고정(2) > 상단 노출(1) > 기본(0)"""
    top = plans_with_perk(db, "search_top")
    pin = plans_with_perk(db, "search_pin")
    upper = plans_with_perk(db, "search_upper")
    return case(
        (School.plan.in_(top), 3) if top else (School.id.is_(None), 3),
        (School.plan.in_(pin), 2) if pin else (School.id.is_(None), 2),
        (School.plan.in_(upper), 1) if upper else (School.id.is_(None), 1),
        else_=0,
    )


def favorite_ids(db: Session, user: Optional[User]) -> set:
    if user is None or user.role != Role.student:
        return set()
    rows = db.query(Favorite.school_id).filter(Favorite.user_id == user.id).all()
    return {r[0] for r in rows}


def can_quick_inquiry(school: School) -> bool:
    """'빠른 문의' 가능 여부 = 활성화된 학교 계정이 있는지.

    답변 메일은 학교가 SMTP를 등록하지 않아도 포털 계정으로 대신 보내주므로,
    학교가 로그인해서 답변할 수 있는 상태이기만 하면 된다.
    """
    return any(a.role == Role.school and a.is_active for a in (school.accounts or []))


def to_list_item(school: School, fav: bool, db: Session = None) -> dict:
    # 플랜이 일시정지면 유료 혜택(색상·우선노출)을 무효화해 무료처럼 취급한다.
    effective_plan = Plan.free if school.plan_paused else school.plan
    # 혜택 토글 반영: 꺼져 있으면 카드 강조·대표이미지를 노출하지 않는다.
    highlight = school_has_perk(db, school, "card_highlight") if db is not None else True
    show_hero = school_has_perk(db, school, "hero_image") if db is not None else True
    quick_ok = can_quick_inquiry(school) and (
        school_has_perk(db, school, "quick_inquiry") if db is not None else True
    )
    return {
        "id": school.id,
        "name": school.name,
        "category": school.category,
        "region": school.region,
        "address": school.address,
        "coed": school.coed,
        "dormitory": school.dormitory,
        "foundation": school.foundation or "",
        "phone": school.phone or "",
        "website": school.website or "",
        "latitude": school.latitude,
        "longitude": school.longitude,
        "slogan": school.slogan or "",
        "hero_image": (school.hero_image or "") if show_hero else "",
        # 카드 색상 강조가 꺼져 있으면 무료처럼 표시한다
        "plan": effective_plan if highlight else Plan.free,
        "actual_plan": school.plan,  # 관리자용: 정지 전 실제 플랜
        "plan_paused": school.plan_paused,
        "is_visible": school.is_visible,
        "is_favorite": fav,
        "can_quick_inquiry": quick_ok,
    }


def d_day(target: date) -> int:
    return (target - date.today()).days


def _event_out(e: AdmissionEvent) -> dict:
    return {
        "id": e.id,
        "kind": e.kind or "admission",
        "title": e.title,
        "start_date": e.start_date,
        "end_date": e.end_date,
        "start_time": e.start_time,
        "end_time": e.end_time,
        "location": e.location or "",
        "registration_url": e.registration_url or "",
        "description": e.description or "",
        "d_day": d_day(e.start_date),
    }


# 개인정보보호법: 수집한 문의(이메일 등)는 목적 달성 후 보유기간이 지나면 파기한다.
# 접수일로부터 이 일수가 지난 문의는 자동 삭제된다.
INQUIRY_RETENTION_DAYS = 365


def purge_old_inquiries(db: Session, school_id: Optional[int] = None) -> int:
    """보유기간이 지난 문의를 삭제한다. 접수·조회 시점에 값싸게 호출한다."""
    cutoff = datetime.utcnow() - timedelta(days=INQUIRY_RETENTION_DAYS)
    q = db.query(Inquiry).filter(Inquiry.created_at < cutoff)
    if school_id is not None:
        q = q.filter(Inquiry.school_id == school_id)
    removed = q.delete(synchronize_session=False)
    if removed:
        db.commit()
    return removed




# ============================================================
# 메타 정보
# ============================================================
def ordered_distinct(db: Session, column, order: List[str], visible_only: bool = False) -> List[str]:
    """DB에 실제로 있는 값만, 정해둔 순서대로 돌려준다.
    visible_only=True면 노출(is_visible)된 학교의 값만 포함한다."""
    q = db.query(column)
    if visible_only:
        q = q.filter(School.is_visible.is_(True))
    found = {v for (v,) in q.distinct().all() if v}
    ranked = [v for v in order if v in found]
    rest = sorted(found - set(ranked))
    return ranked + rest


def extract_sigungu(address: str) -> str:
    """주소에서 시/군/구를 뽑는다.
    예) '서울특별시 양천구 목동로 170' -> '양천구'
        '경기도 안양시 만안구 삼덕로 49' -> '안양시 만안구'
        '경상남도 창원시 의창구 ...' -> '창원시 의창구'
        '세종특별자치시 ...' -> '' (구 없음)
    규칙: 두 번째 어절이 시/군/구. 세 번째 어절이 '구'로 끝나면 합친다(큰 시의 구).
    """
    if not address:
        return ""
    parts = address.split()
    if len(parts) < 2:
        return ""
    second = parts[1]
    # 두 번째가 시/군/구로 끝나야 유효 (아니면 세종처럼 구가 없는 것)
    if not (second.endswith("시") or second.endswith("군") or second.endswith("구")):
        return ""
    # 세 번째가 '구'로 끝나면 '○○시 ○○구' 형태로 합침
    if len(parts) >= 3 and parts[2].endswith("구"):
        return f"{second} {parts[2]}"
    return second


# ---------- 학과 계열 필터 ----------
DEPT_FILTER_KEY = "dept_field_filter_enabled"


def dept_filter_enabled(db: Session) -> bool:
    """관리자가 켜둔 경우에만 학과 계열 필터를 노출한다. 기본값은 켜짐."""
    row = db.query(Setting).filter(Setting.key == DEPT_FILTER_KEY).first()
    return True if row is None else row.value == "1"


def refresh_dept_fields(school: School) -> None:
    """학과 목록이 바뀌면 계열 캐시를 다시 계산한다."""
    school.dept_fields = dept_fields_mod.to_storage(school.departments or "")


def available_dept_fields(db: Session) -> List[dict]:
    """실제로 그 계열을 가진 학교가 있는 항목만 돌려준다."""
    rows = (
        db.query(School.dept_fields)
        .filter(School.is_visible.is_(True), School.dept_fields != "")
        .distinct()
        .all()
    )
    present = set()
    for (val,) in rows:
        present.update(k for k in (val or "").split(",") if k)
    return [o for o in dept_fields_mod.options() if o["key"] in present]


@app.get("/api/meta")
def get_meta(db: Session = Depends(get_db)):
    """검색 드롭다운을 채우는 데 쓰는 선택지 목록. 수집된 학교 기준."""
    return {
        "regions": ordered_distinct(db, School.region, REGION_ORDER, visible_only=True),
        "categories": ordered_distinct(db, School.category, CATEGORY_ORDER, visible_only=True),
        "coed_options": [c.value for c in Coed],
        "dept_field_enabled": dept_filter_enabled(db),
        "dept_fields": available_dept_fields(db) if dept_filter_enabled(db) else [],
        "school_count": db.query(School).filter(School.is_visible.is_(True)).count(),
        "plans": [
            {
                "plan": p.value,
                "label": PLAN_META[p]["label"],
                "price_per_month": get_plan_price(db, p),
                "price_per_year": get_plan_price_year(db, p),
                "rank": PLAN_RANK[p],
                "perks": get_plan_perks(db, p),
                "base_features": [label for _k, label in BASE_FEATURES],
            }
            for p in [Plan.free, Plan.basic, Plan.premium, Plan.platinum]
        ],
    }


# ============================================================
# 인증
# ============================================================
# ── 만 14세 미만 아동 가입 ────────────────────────────────────
CHILD_AGE_LIMIT = 14              # 개인정보 보호법 제22조의2 기준
ADULT_AGE = 19                    # 민법상 성년. 미만이면 결제에 법정대리인 동의가 필요하다
GUARDIAN_CONSENT_TTL_DAYS = 7     # 동의 링크 유효 기간


def korean_age(birth: date, today: Optional[date] = None) -> int:
    """만 나이를 계산한다."""
    today = today or date.today()
    years = today.year - birth.year
    if (today.month, today.day) < (birth.month, birth.day):
        years -= 1
    return years


def send_guardian_consent_mail(user: User, consent: GuardianConsent) -> bool:
    """법정대리인에게 동의 요청 메일을 보낸다."""
    cfg = mailer.system_config()
    if not cfg.is_ready():
        print(f"[보호자동의] 메일 미설정으로 발송 못 함 (user={user.id})", flush=True)
        return False
    base = (os.getenv("SITE_BASE_URL", "") or "https://udjschool.ggm.kr").rstrip("/")
    link = f"{base}/guardian-consent/{consent.token}"
    subject = "[우리동네 직업계고] 자녀의 회원가입 동의 요청"
    body = (
        f"안녕하세요. 우리동네 직업계고입니다.\n\n"
        f"만 {CHILD_AGE_LIMIT}세 미만 아동인 {user.name}님이 회원가입을 신청했습니다.\n"
        "개인정보 보호법에 따라 법정대리인의 동의가 있어야 가입이 완료됩니다.\n\n"
        f"아래 주소에서 수집 항목을 확인하시고 동의해주세요.\n\n"
        f"    {link}\n\n"
        f"이 링크는 {GUARDIAN_CONSENT_TTL_DAYS}일 후 만료됩니다.\n"
        "동의 전까지 계정은 사용할 수 없으며, 동의하지 않으시면 그대로 두시면 됩니다.\n\n"
        "우리동네 직업계고 드림"
    )
    ok, err = mailer.send_email(cfg, consent.guardian_email, subject, body,
                                from_name="우리동네 직업계고")
    if not ok:
        print(f"[보호자동의] 발송 실패 (user={user.id}): {err}", flush=True)
    return ok


@app.post("/api/auth/signup")
def signup(payload: schemas.SignupIn, db: Session = Depends(get_db)):
    """학생 계정만 셀프 가입할 수 있다. 학교 계정은 관리자가 만든다.

    만 14세 미만이면 계정을 비활성으로 만들고 법정대리인 동의를 받는다.
    """
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="이미 가입된 이메일입니다.")

    # 검증을 모두 마친 뒤에 인증 토큰을 소모한다.
    # 먼저 소모하면 아래 검증에 걸렸을 때 인증이 날아가 문자를 다시 받아야 한다.
    age = korean_age(payload.birth_date)
    if age < 0 or age > 120:
        raise HTTPException(status_code=400, detail="생년월일을 다시 확인해주세요.")

    is_child = age < CHILD_AGE_LIMIT
    guardian_email = (payload.guardian_email or "").strip()
    if is_child and not guardian_email:
        raise HTTPException(
            status_code=400,
            detail=f"만 {CHILD_AGE_LIMIT}세 미만은 법정대리인(보호자) 이메일이 필요합니다.",
        )

    # 휴대폰 본인확인을 마친 번호만 받는다.
    verified_phone = consume_phone_token(
        db, payload.phone_verification_token, "signup", payload.phone
    )

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        name=payload.name,
        role=Role.student,
        phone=verified_phone,
        privacy_consent_at=datetime.utcnow(),  # 동의 시각 기록
        birth_date=payload.birth_date,
        guardian_email=guardian_email if is_child else "",
        is_active=not is_child,   # 아동은 동의 전까지 사용할 수 없다
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    if not is_child:
        return {"access_token": create_access_token(user), "user": user_out(user)}

    consent = GuardianConsent(
        user_id=user.id,
        guardian_email=guardian_email,
        token=secrets.token_urlsafe(32),
        expires_at=datetime.utcnow() + timedelta(days=GUARDIAN_CONSENT_TTL_DAYS),
    )
    db.add(consent)
    db.commit()
    sent = send_guardian_consent_mail(user, consent)

    return {
        "guardian_consent_required": True,
        "guardian_email": guardian_email,
        "mail_sent": sent,
        "message": (
            f"만 {CHILD_AGE_LIMIT}세 미만은 보호자 동의가 필요합니다. "
            f"{guardian_email} 로 동의 요청 메일을 보냈습니다."
        ),
    }


@app.get("/api/guardian-consent/{token}")
def guardian_consent_info(token: str, db: Session = Depends(get_db)):
    """보호자가 동의 화면에서 볼 정보."""
    consent = db.query(GuardianConsent).filter(GuardianConsent.token == token).first()
    if not consent:
        raise HTTPException(status_code=404, detail="유효하지 않은 링크입니다.")
    return {
        "student_name": consent.user.name if consent.user else "",
        "guardian_email": consent.guardian_email,
        "expired": datetime.utcnow() > consent.expires_at,
        "consented": consent.consented_at is not None,
        "items": ["이름", "이메일 주소", "비밀번호", "연락처(선택)", "생년월일"],
        "purpose": "회원 식별과 진학 정보 제공, 문의 답변",
        "retention": "회원 탈퇴 시까지",
    }


@app.post("/api/guardian-consent/{token}")
def guardian_consent_submit(token: str, request: Request, db: Session = Depends(get_db)):
    """법정대리인이 동의하면 계정을 활성화한다."""
    consent = db.query(GuardianConsent).filter(GuardianConsent.token == token).first()
    if not consent:
        raise HTTPException(status_code=404, detail="유효하지 않은 링크입니다.")
    if consent.consented_at:
        return {"ok": True, "already": True}
    if datetime.utcnow() > consent.expires_at:
        raise HTTPException(status_code=400, detail="동의 링크가 만료되었습니다. 다시 가입해주세요.")

    now = datetime.utcnow()
    consent.consented_at = now
    consent.consent_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "")
    )[:45]
    user = consent.user
    if user:
        user.is_active = True
        user.guardian_consent_at = now
    db.commit()
    return {"ok": True, "student_name": user.name if user else ""}


def plan_days_left(school) -> Optional[int]:
    """플랜이 며칠 남았나. 무료·무기한이면 None.

    날짜만 보고 센다(시각 무시) — 사람은 "오늘 자정까지"로 세지, 시분초로
    세지 않는다. 만료일 당일은 0(오늘까지), 지났으면 음수다.

    plan_expires_at 은 Date 컬럼이라 보통 date 로 온다. 다만 다른 곳에서
    datetime 을 넣어 두는 경우가 있어 둘 다 받아 준다.
    """
    if not school or not school.plan_expires_at:
        return None
    if getattr(school, "plan", None) is None or school.plan == Plan.free:
        return None
    end = school.plan_expires_at
    if isinstance(end, datetime):
        end = end.date()
    return (end - datetime.utcnow().date()).days


def user_out(user: User) -> dict:
    s = user.school
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "school_id": user.school_id,
        "school_name": s.name if s else None,
        "phone": user.phone or "",
        # 학교 계정이 상단에서 남은 기간을 보게 한다. 여기 실어 보내면
        # 화면이 그것 하나 때문에 요청을 더 보내지 않아도 된다.
        #
        # **학교 계정에만 실어 보낸다.** 같은 학교의 학생·선생님도 school_id
        # 는 갖고 있지만, 결제가 언제 끝나는지는 그쪽이 알 일이 아니다.
        # 화면에서 안 그리는 것과 응답에 없는 것은 다르다.
        **({
            "plan": s.plan.value if s and s.plan else None,
            "plan_expires_at": s.plan_expires_at if s else None,
            "plan_days_left": plan_days_left(s),
            "plan_paused": bool(getattr(s, "plan_paused", False)) if s else False,
        } if user.role == Role.school else {}),
    }


# ---------- 로그인 시도 제한 (무차별 대입 방어) ----------
# 외부 라이브러리 없이 메모리로 IP+이메일별 실패 횟수를 추적한다.
# 단일 서버 기준. 여러 서버로 확장하면 Redis 등으로 옮겨야 한다.
_LOGIN_FAILS: dict[str, list[float]] = {}
LOGIN_MAX_FAILS = 5          # 이 횟수 이상 실패하면
LOGIN_WINDOW_SEC = 300       # 최근 5분 내
LOGIN_BLOCK_SEC = 300        # 5분 차단


def _login_key(request: Request, email: str) -> str:
    ip = request.client.host if request.client else "unknown"
    return f"{ip}:{email.lower().strip()}"


def _check_login_allowed(key: str) -> None:
    import time as _t
    now = _t.time()
    fails = [t for t in _LOGIN_FAILS.get(key, []) if now - t < LOGIN_WINDOW_SEC]
    _LOGIN_FAILS[key] = fails
    if len(fails) >= LOGIN_MAX_FAILS:
        raise HTTPException(
            status_code=429,
            detail="로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요.",
        )


def _record_login_fail(key: str) -> None:
    import time as _t
    _LOGIN_FAILS.setdefault(key, []).append(_t.time())


def _clear_login_fails(key: str) -> None:
    _LOGIN_FAILS.pop(key, None)


@app.post("/api/auth/login", response_model=schemas.TokenOut)
def login(payload: schemas.LoginIn, request: Request, db: Session = Depends(get_db)):
    key = _login_key(request, payload.email)
    _check_login_allowed(key)
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        _record_login_fail(key)
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 맞지 않습니다.")
    if not user.is_active:
        # 보호자 동의를 기다리는 아동 계정이면 정지가 아니라 대기 상태임을 알려준다.
        if user.guardian_email and not user.guardian_consent_at:
            raise HTTPException(
                status_code=403,
                detail=(f"보호자 동의가 아직 완료되지 않았습니다. "
                        f"{user.guardian_email} 로 보낸 메일의 링크를 확인해주세요."),
            )
        raise HTTPException(status_code=403, detail="정지된 계정입니다. 관리자에게 문의하세요.")
    _clear_login_fails(key)  # 성공하면 실패 기록 초기화
    return {"access_token": create_access_token(user), "user": user_out(user)}


@app.get("/api/auth/me", response_model=schemas.UserOut)
def me(user: User = Depends(get_current_user)):
    return user_out(user)


@app.delete("/api/auth/me")
def delete_my_account(
    payload: schemas.DeleteAccountIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """회원 탈퇴. 본인 확인을 위해 비밀번호를 검증한 뒤, 계정과 개인정보를 삭제한다.
    - 학생: 즐겨찾기·비밀번호 재설정 기록과 계정을 지운다.
    - 학교 계정: 계정만 삭제하고 학교 정보(공개 데이터)는 남긴다.
    - 관리자: 안전을 위해 셀프 탈퇴를 막는다(다른 관리자가 처리).
    """
    from .models import PasswordReset, NoticeRead, Notice

    if user.role == Role.admin:
        raise HTTPException(status_code=400, detail="관리자 계정은 탈퇴할 수 없습니다.")

    # 본인 확인: 비밀번호가 맞아야 탈퇴 진행
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=400, detail="비밀번호가 일치하지 않습니다.")

    # users 를 참조하는 모든 테이블을 정리해야 한다. 하나라도 남으면 외래키 제약에
    # 걸려 탈퇴가 통째로 실패한다.
    try:
        # (1) 본인이 남긴 개인정보 — 삭제
        db.query(Favorite).filter(Favorite.user_id == user.id).delete(synchronize_session=False)
        db.query(PasswordReset).filter(PasswordReset.user_id == user.id).delete(synchronize_session=False)
        db.query(JournalEntry).filter(JournalEntry.user_id == user.id).delete(synchronize_session=False)
        db.query(QuizTaken).filter(QuizTaken.user_id == user.id).delete(synchronize_session=False)
        db.query(NoticeRead).filter(NoticeRead.user_id == user.id).delete(synchronize_session=False)
        db.query(SchoolVerification).filter(
            SchoolVerification.user_id == user.id
        ).delete(synchronize_session=False)
        db.query(GuardianConsent).filter(
            GuardianConsent.user_id == user.id
        ).delete(synchronize_session=False)

        # 본인확인용으로 남은 인증번호 기록(휴대폰번호 포함)도 지운다.
        if user.phone:
            db.query(PhoneVerification).filter(
                PhoneVerification.phone == _normalize_phone(user.phone)
            ).delete(synchronize_session=False)

        # (2) 남겨야 하는 기록 — 연결만 끊는다
        # 승인 이력·공지 등은 다른 이용자에게 필요한 자료라 지우지 않는다.
        db.query(SchoolVerification).filter(
            SchoolVerification.teacher_id == user.id
        ).update({SchoolVerification.teacher_id: None}, synchronize_session=False)
        db.query(Notice).filter(Notice.author_id == user.id).update(
            {Notice.author_id: None}, synchronize_session=False
        )
        db.query(PlanOrder).filter(PlanOrder.requested_by == user.id).update(
            {PlanOrder.requested_by: None}, synchronize_session=False
        )
        db.query(Inquiry).filter(Inquiry.answered_by == user.id).update(
            {Inquiry.answered_by: None}, synchronize_session=False
        )
        # 관리자 활동 기록은 안전성 확보조치 기준 제8조에 따라 1년 보관해야 하므로
        # 행 자체는 남기고 계정 연결만 끊는다.
        db.query(AdminAuditLog).filter(AdminAuditLog.actor_id == user.id).update(
            {AdminAuditLog.actor_id: None}, synchronize_session=False
        )

        db.delete(user)
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"[탈퇴] 실패 (user={user.id}): {exc}", flush=True)
        raise HTTPException(
            status_code=500,
            detail="탈퇴 처리 중 오류가 발생했습니다. 고객센터로 문의해주세요.",
        )

    return {"ok": True, "message": "탈퇴가 완료되었습니다. 개인정보가 삭제되었습니다."}


# ---------- 아이디(이메일) 찾기 ----------
def mask_phone(phone: str) -> str:
    """01012345678 -> 010****5678 (기록에 원본을 남기지 않는다)."""
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) < 7:
        return "***"
    return f"{digits[:3]}{'*' * (len(digits) - 7)}{digits[-4:]}"


def mask_email(email: str) -> str:
    """abc@naver.com -> ab***@naver.com (가운데를 가린다)."""
    try:
        local, domain = email.split("@", 1)
    except ValueError:
        return "***"
    if len(local) <= 2:
        shown = local[0] if local else "*"
    else:
        shown = local[:2]
    return f"{shown}{'*' * max(3, len(local) - len(shown))}@{domain}"


def _normalize_phone(phone: str) -> str:
    """비교용으로 숫자만 남긴다(010-1234-5678 == 01012345678)."""
    return "".join(ch for ch in (phone or "") if ch.isdigit())


# ---------- 휴대폰 본인확인 (SMS) ----------
PHONE_CODE_TTL_MIN = 3          # 인증번호 유효 시간
PHONE_MAX_ATTEMPTS = 5          # 인증번호 확인 시도 한도
PHONE_TOKEN_TTL_MIN = 10        # 인증 성공 후 작업을 마쳐야 하는 시간
PHONE_SEND_LIMIT = 5            # 같은 번호로 1시간에 보낼 수 있는 횟수
PHONE_RESEND_COOLDOWN_SEC = 60  # 재발송 대기 시간. 연타로 문자가 낭비되는 것을 막는다
PHONE_PURPOSES = ("signup", "find_id", "reset_pw", "change_pw", "change_phone")


def find_user_by_phone(db: Session, phone: str, exclude_id: Optional[int] = None):
    """휴대폰번호로 사용자를 찾는다.

    예전에는 전체 사용자를 파이썬으로 불러와 비교했다. 회원이 늘수록 가입·번호
    변경이 통째로 느려지므로, 인덱스를 타는 직접 조회로 바꿨다.
    저장할 때 숫자만 남기지만 옛 자료에는 하이픈이 있을 수 있어 함께 본다.
    """
    digits = _normalize_phone(phone)
    if not digits:
        return None
    variants = {digits}
    if len(digits) == 11:
        variants.add(f"{digits[:3]}-{digits[3:7]}-{digits[7:]}")
    elif len(digits) == 10:
        variants.add(f"{digits[:3]}-{digits[3:6]}-{digits[6:]}")
    q = db.query(User).filter(User.phone.in_(sorted(variants)))
    if exclude_id is not None:
        q = q.filter(User.id != exclude_id)
    return q.first()


def _client_ip(request: Optional[Request]) -> str:
    if request is None:
        return ""
    return (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "")
    )[:45]


def issue_phone_code(
    db: Session, request: Request, phone: str, purpose: str, to_email: str = ""
) -> dict:
    """인증번호를 만들어 문자(또는 메일)로 보낸다."""
    digits = _normalize_phone(phone)
    if not (digits.startswith("01") and 10 <= len(digits) <= 11):
        raise HTTPException(status_code=400, detail="휴대폰번호 형식이 올바르지 않습니다.")
    if purpose not in PHONE_PURPOSES:
        raise HTTPException(status_code=400, detail="잘못된 요청입니다.")

    # 같은 번호로 과도하게 보내는 것을 막는다(문자 폭탄 방지).
    since = datetime.utcnow() - timedelta(hours=1)
    recent = (
        db.query(PhoneVerification)
        .filter(PhoneVerification.phone == digits, PhoneVerification.created_at >= since)
        .count()
    )
    if recent >= PHONE_SEND_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="인증번호를 너무 많이 요청했습니다. 잠시 후 다시 시도해주세요.",
        )

    # 문자가 도착하기 전에 연타하면 그만큼 요금이 나간다. 잠깐 기다리게 한다.
    # 목적이 다르면(가입 -> 비밀번호 변경 등) 막지 않는다. 같은 절차를 연타할 때만 제한한다.
    last = (
        db.query(PhoneVerification)
        .filter(PhoneVerification.phone == digits, PhoneVerification.purpose == purpose)
        .order_by(PhoneVerification.created_at.desc())
        .first()
    )
    if last:
        waited = (datetime.utcnow() - last.created_at).total_seconds()
        if waited < PHONE_RESEND_COOLDOWN_SEC:
            left = int(PHONE_RESEND_COOLDOWN_SEC - waited) + 1
            raise HTTPException(
                status_code=429,
                detail=f"인증번호를 방금 보냈습니다. {left}초 후에 다시 시도해주세요.",
            )

    purge_expired_verifications(db)

    code = f"{secrets.randbelow(1_000_000):06d}"
    row = PhoneVerification(
        phone=digits,
        purpose=purpose,
        code_hash=_hash_code(code),
        expires_at=datetime.utcnow() + timedelta(minutes=PHONE_CODE_TTL_MIN),
        ip=_client_ip(request),
    )
    db.add(row)
    db.commit()

    ch = sms.channel()
    if ch == "email":
        ok, err = _send_code_by_email(to_email, code)
        if not ok:
            print(f"[본인확인] 메일 발송 실패({purpose}): {err}", flush=True)
    else:
        text = f"[우리동네 직업계고] 인증번호 {code} (유효시간 {PHONE_CODE_TTL_MIN}분)"
        ok, err = sms.send_sms(digits, text)
        if not ok:
            print(f"[본인확인] 문자 발송 실패({purpose}): {err}", flush=True)
    return {"ok": True, "sent": ok, "channel": ch, "ttl_min": PHONE_CODE_TTL_MIN}


def _send_code_by_email(to_email: str, code: str) -> tuple:
    """문자 대신 메일로 인증번호를 보낸다."""
    if not to_email:
        raise HTTPException(status_code=400, detail="인증번호를 받을 이메일이 필요합니다.")
    cfg = mailer.system_config()
    if not cfg.is_ready():
        return False, "메일 발송이 설정되지 않았습니다."
    subject = "[우리동네 직업계고] 본인확인 인증번호"
    body = (
        f"본인확인 인증번호는 아래와 같습니다.\n\n"
        f"    {code}\n\n"
        f"이 번호는 {PHONE_CODE_TTL_MIN}분 후 만료됩니다.\n"
        "본인이 요청하지 않았다면 이 메일을 무시하세요."
    )
    return mailer.send_email(cfg, to_email, subject, body, from_name="우리동네 직업계고")


def verify_phone_code(db: Session, phone: str, code: str, purpose: str) -> str:
    """인증번호를 확인하고 일회용 토큰을 돌려준다."""
    digits = _normalize_phone(phone)
    row = (
        db.query(PhoneVerification)
        .filter(
            PhoneVerification.phone == digits,
            PhoneVerification.purpose == purpose,
            PhoneVerification.verified_at.is_(None),
        )
        .order_by(PhoneVerification.created_at.desc())
        .first()
    )
    if not row:
        raise HTTPException(status_code=400, detail="인증번호를 먼저 요청해주세요.")
    if datetime.utcnow() > row.expires_at:
        raise HTTPException(status_code=400, detail="인증번호가 만료되었습니다. 다시 요청해주세요.")
    if (row.attempts or 0) >= PHONE_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="확인 시도가 너무 많습니다. 다시 요청해주세요.")

    row.attempts = (row.attempts or 0) + 1
    if row.code_hash != _hash_code((code or "").strip()):
        db.commit()
        left = max(PHONE_MAX_ATTEMPTS - row.attempts, 0)
        raise HTTPException(status_code=400, detail=f"인증번호가 맞지 않습니다. ({left}회 남음)")

    row.verified_at = datetime.utcnow()
    row.token = secrets.token_urlsafe(32)
    db.commit()
    return row.token


def consume_phone_token(db: Session, token: str, purpose: str, phone: str = "") -> str:
    """인증 토큰을 검증하고 소모한다. 인증된 번호(숫자만)를 돌려준다."""
    if not token:
        raise HTTPException(status_code=400, detail="휴대폰 인증이 필요합니다.")
    row = (
        db.query(PhoneVerification)
        .filter(PhoneVerification.token == token, PhoneVerification.purpose == purpose)
        .first()
    )
    if not row or not row.verified_at or row.token_used:
        raise HTTPException(status_code=400, detail="휴대폰 인증을 다시 진행해주세요.")
    if datetime.utcnow() > row.verified_at + timedelta(minutes=PHONE_TOKEN_TTL_MIN):
        raise HTTPException(status_code=400, detail="인증 후 시간이 지났습니다. 다시 인증해주세요.")
    if phone and _normalize_phone(phone) != row.phone:
        raise HTTPException(status_code=400, detail="인증한 번호와 입력한 번호가 다릅니다.")

    row.token_used = True
    db.commit()
    return row.phone


@app.post("/api/phone/send-code")
def phone_send_code(
    payload: schemas.PhoneCodeIn,
    request: Request,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """인증번호 발송.

    문자 채널이면 입력한 번호로 보낸다.
    메일 채널이면 '그 사람이 이미 증명한 주소'로만 보낸다. 로그인 상태면 계정
    주소를, 가입 단계면 지금 입력 중인 주소를 쓴다. 클라이언트가 임의 주소를
    지정해 남의 인증번호를 받아가는 일이 없도록 서버가 정한다.
    """
    if payload.purpose in ("signup", "change_phone"):
        if find_user_by_phone(db, payload.phone):
            raise HTTPException(status_code=400, detail="이미 사용 중인 휴대폰번호입니다.")

    if payload.purpose == "change_pw":
        if not user:
            raise HTTPException(status_code=401, detail="로그인 후 이용해주세요.")
        if not user.phone:
            raise HTTPException(
                status_code=400,
                detail="등록된 휴대폰번호가 없습니다. 먼저 번호를 등록해주세요.",
            )
        if _normalize_phone(payload.phone) != _normalize_phone(user.phone):
            raise HTTPException(status_code=400, detail="등록된 휴대폰번호와 다릅니다.")

    to_email = ""
    if sms.channel() == "email":
        if user:
            # 로그인 상태(비밀번호 변경·번호 변경)면 계정에 등록된 주소로 보낸다.
            to_email = user.email
        elif payload.purpose == "signup":
            to_email = str(payload.email or "").strip()
            if not to_email:
                raise HTTPException(status_code=400, detail="이메일을 먼저 입력해주세요.")
        elif payload.purpose == "reset_pw":
            acct = db.query(User).filter(User.email == str(payload.email or "").strip()).first()
            if not acct:
                # 계정 존재 여부가 새지 않도록 성공한 것처럼 응답한다.
                return {
                    "ok": True, "sent": True, "channel": "email",
                    "sent_to": mask_email(str(payload.email or "")),
                    "ttl_min": PHONE_CODE_TTL_MIN,
                }
            to_email = acct.email
        else:
            raise HTTPException(status_code=400, detail="로그인 후 이용해주세요.")

    result = issue_phone_code(db, request, payload.phone, payload.purpose, to_email)
    result["sent_to"] = mask_email(to_email) if to_email else mask_phone(payload.phone)
    return result


@app.get("/api/verify-config")
def verify_config():
    """프런트가 인증 방식을 알 수 있게 알려준다."""
    ch = sms.channel()
    return {
        "channel": ch,
        # 메일 채널에서는 아이디 찾기에 인증번호를 쓸 수 없다.
        "find_id_requires_verification": ch == "sms",
        "ttl_min": PHONE_CODE_TTL_MIN,
    }


@app.post("/api/phone/verify-code")
def phone_verify_code(payload: schemas.PhoneVerifyIn, db: Session = Depends(get_db)):
    token = verify_phone_code(db, payload.phone, payload.code, payload.purpose)
    return {"ok": True, "verification_token": token, "ttl_min": PHONE_TOKEN_TTL_MIN}


@app.post("/api/auth/find-id")
def find_id(payload: schemas.FindIdIn, db: Session = Depends(get_db)):
    """이름 + 휴대폰번호가 모두 일치하는 계정의 이메일(=아이디)을 마스킹해서 보여준다.

    이름만으로는 동명이인의 이메일이 노출되므로, 2차 식별 수단인 휴대폰번호를 함께 확인한다.
    학교·관리자 계정은 공개 조회 대상에서 제외한다(관리자에게 문의).
    """
    name = payload.name.strip()
    if sms.channel() == "email":
        # 찾으려는 대상이 이메일 주소라 메일로 인증할 수 없다. 이름+번호 일치로만 확인한다.
        phone = _normalize_phone(payload.phone)
        if not phone:
            raise HTTPException(status_code=400, detail="휴대폰번호를 입력해주세요.")
    else:
        # 본인 번호임을 확인한 경우에만 조회할 수 있다(타인 번호 대입 방지).
        phone = consume_phone_token(
            db, payload.phone_verification_token or "", "find_id", payload.phone
        )

    candidates = (
        db.query(User)
        .filter(User.name == name, User.role == Role.student)
        .all()
    )
    matched = [u for u in candidates if u.phone and _normalize_phone(u.phone) == phone]
    return {"emails": [mask_email(u.email) for u in matched]}


# ---------- 비밀번호 재설정 ----------
RESET_CODE_TTL_MIN = 30
RESET_MAX_ATTEMPTS = 5


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


@app.post("/api/auth/forgot-password")
def forgot_password(payload: schemas.ForgotPasswordIn, db: Session = Depends(get_db)):
    """가입 이메일로 6자리 인증코드를 보낸다.

    계정 존재 여부가 새어나가지 않도록, 존재하든 아니든 같은 응답을 준다.
    """
    generic = {
        "ok": True,
        "message": "가입된 이메일이라면 인증코드를 보내드렸습니다. 메일함을 확인해주세요.",
    }
    user = db.query(User).filter(User.email == str(payload.email).strip()).first()
    if not user or not user.is_active:
        return generic

    # 기존 미사용 코드는 무효화하고 새 코드 발급
    db.query(PasswordReset).filter(
        PasswordReset.user_id == user.id, PasswordReset.used.is_(False)
    ).update({PasswordReset.used: True}, synchronize_session=False)

    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(
        PasswordReset(
            user_id=user.id,
            code_hash=_hash_code(code),
            expires_at=datetime.utcnow() + timedelta(minutes=RESET_CODE_TTL_MIN),
        )
    )
    db.commit()

    cfg = mailer.system_config()
    if not cfg.is_ready():
        # 메일 미설정이면 자체 발송이 불가하므로 관리자 재설정을 안내한다.
        return {
            "ok": True,
            "mail_configured": False,
            "message": "메일 발송이 설정되지 않아 코드를 보낼 수 없습니다. 포털 관리자에게 비밀번호 재설정을 요청해주세요.",
        }

    subject = "[우리동네 직업계고] 비밀번호 재설정 인증코드"
    body = (
        f"{user.name}님, 비밀번호 재설정 인증코드는 아래와 같습니다.\n\n"
        f"    {code}\n\n"
        f"이 코드는 {RESET_CODE_TTL_MIN}분 후 만료됩니다.\n"
        "본인이 요청하지 않았다면 이 메일을 무시하세요."
    )
    ok, err = mailer.send_email(cfg, user.email, subject, body, from_name="우리동네 직업계고")
    # 응답에는 성공/실패를 노출하지 않지만(계정 열거 방지), 운영자가 볼 수 있게 서버 로그에 남긴다.
    if ok:
        print(f"[비밀번호재설정] {user.email} 로 코드 발송 성공", flush=True)
    else:
        print(f"[비밀번호재설정] {user.email} 발송 실패: {err}", flush=True)
    return generic


@app.post("/api/auth/reset-password")
def reset_password(payload: schemas.ResetPasswordIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == str(payload.email).strip()).first()
    if not user:
        raise HTTPException(status_code=400, detail="인증코드가 올바르지 않거나 만료되었습니다.")

    reset = (
        db.query(PasswordReset)
        .filter(PasswordReset.user_id == user.id, PasswordReset.used.is_(False))
        .order_by(PasswordReset.created_at.desc())
        .first()
    )
    if not reset or reset.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="인증코드가 올바르지 않거나 만료되었습니다.")
    if reset.attempts >= RESET_MAX_ATTEMPTS:
        reset.used = True
        db.commit()
        raise HTTPException(status_code=400, detail="시도 횟수를 초과했습니다. 코드를 다시 요청해주세요.")

    if reset.code_hash != _hash_code(payload.code.strip()):
        reset.attempts += 1
        db.commit()
        raise HTTPException(status_code=400, detail="인증코드가 올바르지 않거나 만료되었습니다.")

    user.password_hash = hash_password(payload.new_password)
    reset.used = True
    db.commit()
    return {"ok": True, "message": "비밀번호가 변경되었습니다. 새 비밀번호로 로그인해주세요."}


@app.get("/api/me")
def get_my_account(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """마이페이지에 보여줄 내 등록 정보."""
    out = {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "phone": user.phone or "",
        "role": user.role.value,
        "created_at": user.created_at,
        "school_name": "",
        "class_name": user.class_name or "",
    }
    if user.school_id:
        s = db.get(School, user.school_id)
        out["school_name"] = s.name if s else ""
    # 학생은 재학생 인증 상태도 함께 보여준다
    if user.role == Role.student:
        v = (
            db.query(SchoolVerification)
            .filter(
                SchoolVerification.user_id == user.id,
                SchoolVerification.status == "approved",
            )
            .first()
        )
        if v:
            out["verified_school"] = v.school.name if v.school else ""
            out["class_name"] = v.class_name or ""
    return out


@app.put("/api/me")
def update_my_account(
    payload: schemas.MyAccountIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """내 등록 정보(이름·연락처)를 수정한다.
    이메일(로그인 아이디)과 역할, 소속 학교는 본인이 바꿀 수 없다."""
    name = (payload.name or "").strip()
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="이름은 2자 이상 입력해주세요.")
    user.name = name[:60]
    db.commit()
    return get_my_account(db=db, user=user)


@app.post("/api/me/change-phone")
def change_my_phone(
    payload: schemas.ChangePhoneIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """등록된 휴대폰번호를 바꾼다.

    휴대폰번호는 아이디·비밀번호 찾기의 본인확인 수단이다. 계정을 탈취당한
    사람이 번호만 바꿔치기해 계정을 완전히 가져가는 일을 막기 위해
    현재 비밀번호와 새 번호의 SMS 인증을 모두 요구한다.
    """
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="현재 비밀번호가 맞지 않습니다.")

    new_phone = consume_phone_token(
        db, payload.phone_verification_token, "change_phone", payload.new_phone
    )
    old_phone = user.phone or ""
    if _normalize_phone(old_phone) == new_phone:
        raise HTTPException(status_code=400, detail="현재 등록된 번호와 동일합니다.")

    # 다른 계정이 이미 쓰는 번호면 막는다(계정 찾기가 꼬인다).
    if find_user_by_phone(db, new_phone, exclude_id=user.id):
        raise HTTPException(status_code=400, detail="이미 사용 중인 휴대폰번호입니다.")

    user.phone = new_phone
    db.commit()

    write_audit(
        db, request, user, action="user.change_phone",
        target_type="user", target_id=user.id,
        detail=f"{mask_phone(old_phone)} -> {mask_phone(new_phone)}",
    )

    # 이전 번호로도 알려 본인이 모르는 변경을 알아챌 수 있게 한다.
    if old_phone:
        ok, err = sms.send_sms(
            _normalize_phone(old_phone),
            "[우리동네 직업계고] 등록된 휴대폰번호가 변경되었습니다. "
            "본인이 아니라면 문의해주세요.",
        )
        if not ok:
            print(f"[번호변경] 이전 번호 통지 실패: {err}", flush=True)

    return {"ok": True, "phone": user.phone, "message": "휴대폰번호가 변경되었습니다."}


@app.post("/api/auth/reset-password-by-phone")
def reset_password_by_phone(payload: schemas.ResetPasswordByPhoneIn, db: Session = Depends(get_db)):
    """메일 대신 휴대폰 인증으로 비밀번호를 재설정한다.

    이메일과 인증한 번호가 같은 계정의 것일 때만 통과시킨다.
    """
    phone = consume_phone_token(
        db, payload.phone_verification_token, "reset_pw", payload.phone
    )
    user = db.query(User).filter(User.email == str(payload.email).strip()).first()
    if not user or not user.is_active or not user.phone:
        raise HTTPException(status_code=400, detail="이메일 또는 휴대폰번호가 맞지 않습니다.")
    if _normalize_phone(user.phone) != phone:
        raise HTTPException(status_code=400, detail="이메일 또는 휴대폰번호가 맞지 않습니다.")

    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    db.commit()
    return {"ok": True, "message": "비밀번호가 변경되었습니다. 새 비밀번호로 로그인해주세요."}


@app.post("/api/auth/change-password")
def change_password(
    payload: schemas.ChangePasswordIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """로그인한 사용자가 현재 비밀번호를 확인하고 새 비밀번호로 바꾼다."""
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="현재 비밀번호가 맞지 않습니다.")
    # 등록된 본인 번호로 인증을 마쳐야 한다.
    # 인증 도입 이전에 가입해 번호가 없는 계정은 대조할 수단이 없으므로,
    # 비밀번호 확인만으로 진행한다(그렇지 않으면 영영 못 바꾼다).
    if user.phone:
        consume_phone_token(
            db, payload.phone_verification_token or "", "change_pw", user.phone
        )
    if verify_password(payload.new_password, user.password_hash):
        raise HTTPException(status_code=400, detail="기존과 다른 비밀번호로 설정해주세요.")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"ok": True, "message": "비밀번호가 변경되었습니다."}


# ============================================================
# 학교 검색 / 상세
# ============================================================
def apply_school_filters(
    q,
    db: Session,
    *,
    name: Optional[str] = None,
    region: Optional[str] = None,
    sigungu: Optional[str] = None,
    category: Optional[str] = None,
    coed=None,
    dept_field: Optional[str] = None,
    include_hidden: bool = False,
):
    """목록·지도가 똑같은 조건으로 걸러지도록 한곳에 모아둔다.

    예전에는 두 엔드포인트가 각자 필터를 갖고 있어서, 새 필터를 추가할 때
    한쪽만 고치면 지도에 엉뚱한 학교가 찍혔다.
    """
    if name:
        type_ends = _TYPE_QUERIES.get(_norm(name))
        if type_ends:
            # '상고'·'공고'는 특정 학교 이름이 아니라 **종류**다. 부분 일치로
            # 찾으면 정작 '서울여자상업고등학교'는 안 나오고(이름에 '상고'가
            # 통째로 들어있지 않다) '서울영상고'만 나온다. 그래서 이 말들은
            # 이름이 그 종류로 끝나는지로 바꿔서 찾는다.
            # '공업계 고등학교'처럼 띄어 쓴 이름도 있어서 두 꼴을 함께 본다.
            pats = []
            for end in type_ends:
                pats.append(School.name.ilike(f"%{end}"))
                pats.append(School.name.ilike(f"%{end[:-4]} 고등학교"))
            q = q.filter(or_(*pats))
        else:
            # 정식 명칭뿐 아니라 통용되는 별칭(search_aliases)으로도 찾을 수 있게 한다.
            # '경화EB고등학교'처럼 학교·학생이 실제로 쓰는 이름이 정식 명칭과
            # 많이 다른 경우가 있어서다.
            needle = f"%{name.strip()}%"
            q = q.filter(or_(School.name.ilike(needle), School.search_aliases.ilike(needle)))
    if region:
        q = q.filter(School.region == region)
    if sigungu:
        # 주소에 '양천구' 또는 '수원시'(구 미선택 시)가 포함된 학교
        q = q.filter(School.address.contains(sigungu.strip()))
    if category:
        q = q.filter(School.category == category)
    if dept_field and dept_filter_enabled(db):
        # ",it,design," 형태라 앞뒤 쉼표를 붙여 정확히 일치하는 키만 찾는다.
        q = q.filter(School.dept_fields.like(f"%,{dept_field},%"))
    if coed:
        q = q.filter(School.coed == coed)
    if not include_hidden:
        q = q.filter(School.is_visible.is_(True))
    return q


_SCHOOL_ABBR_TYPE_RE = re.compile(r"(.)업고등학교$")

# 학교 이름에 섞인 알파벳을 한글로 읽은 소리. 'EB' 를 '이비' 라고 치는 사람이 많다.
_LETTER_SOUND = {
    "a": "에이", "b": "비", "c": "씨", "d": "디", "e": "이", "f": "에프",
    "g": "지", "h": "에이치", "i": "아이", "j": "제이", "k": "케이", "l": "엘",
    "m": "엠", "n": "엔", "o": "오", "p": "피", "q": "큐", "r": "알",
    "s": "에스", "t": "티", "u": "유", "v": "브이", "w": "더블유", "x": "엑스",
    "y": "와이", "z": "지",
}
_LATIN_RUN_RE = re.compile(r"[A-Za-z]+(?:\s+[A-Za-z]+)*")


def _latin_initials(name: str) -> str:
    """이어진 영어 낱말을 첫 글자만 남긴다.

    'English Business' -> 'EB'. 학교도 학생도 정식 명칭 대신 이 머리글자로
    부르는 경우가 많다(경화여자English Business고등학교 -> 경화EB고).
    """
    def repl(m):
        return "".join(w[0].upper() for w in m.group(0).split())
    return _LATIN_RUN_RE.sub(repl, name)


def _letters_to_korean(name: str) -> str:
    """알파벳을 한글 소리로 바꾼다. 'EB' -> '이비', 'IT' -> '아이티'."""
    return "".join(_LETTER_SOUND.get(ch.lower(), ch) if ch.isascii() and ch.isalpha() else ch
                   for ch in name)


def _norm(text: str) -> str:
    """띄어쓰기·대소문자 차이를 없앤다."""
    return "".join(text.split()).lower()


# --- 오타를 견디는 비교 -------------------------------------------------
# 한글을 자모로 쪼갠 뒤, 소리가 같아 자주 헷갈리는 모음을 하나로 합쳐서 본다.
# '애니고'/'에니고', '왜관'/'외관' 처럼 듣고 옮겨 적을 때 갈리는 것들이다.
_CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_JONG = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"
# 합쳐서 볼 모음. 뜻이 갈리는 모음(ㅢ/ㅣ 등)까지 합치면 엉뚱한 학교가 걸리므로
# 실제로 소리가 구별되지 않는 것만 둔다.
_VOWEL_FOLD = {"ㅐ": "ㅔ", "ㅒ": "ㅖ", "ㅙ": "ㅚ", "ㅞ": "ㅚ"}


def _to_jamo(text: str) -> str:
    """한글 음절을 자모로 펼친다. 한글이 아니면 그대로 둔다."""
    out = []
    for ch in text:
        code = ord(ch) - 0xAC00
        if 0 <= code <= 11171:
            cho, rest = divmod(code, 588)
            jung, jong = divmod(rest, 28)
            out.append(_CHO[cho])
            out.append(_VOWEL_FOLD.get(_JUNG[jung], _JUNG[jung]))
            if jong:
                out.append(_JONG[jong])
        else:
            out.append(ch)
    return "".join(out)


def _fold_text(text: str) -> str:
    """헷갈리는 모음만 대표값으로 바꾼 '음절' 글자열.

    '에니고' 와 '애니고' 가 같은 값이 된다. 비교는 음절 단위로 해야 한다 —
    자모로 펼쳐 놓고 비교하면 모음으로 시작하는 글자가 전부 'ㅇ' 으로
    시작해서, 앞머리가 같은지 보는 검사가 무력해진다.
    """
    out = []
    for ch in text:
        code = ord(ch) - 0xAC00
        if 0 <= code <= 11171:
            cho, rest = divmod(code, 588)
            jung, jong = divmod(rest, 28)
            folded = _VOWEL_FOLD.get(_JUNG[jung], _JUNG[jung])
            jung = _JUNG.index(folded)
            out.append(chr(0xAC00 + (cho * 21 + jung) * 28 + jong))
        else:
            out.append(ch)
    return "".join(out)


def _edit_distance(a: str, b: str, cap: int) -> int:
    """두 글자열이 몇 군데나 다른가. cap 을 넘으면 바로 cap+1 로 끊는다."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


# 학교 종류를 부르는 굳어진 줄임말.
#
# 아래 둘은 규칙으로 이미 만들어지므로 여기 적지 않는다.
#   (.)업고등학교 -> (.)고   : 공업->공고, 상업->상고, 농업->농고, 실업->실고
#   ~고등학교     -> ~고     : 정보고, 해양고, 전산고, 특성화고, 마이스터고 …
# 규칙으로 안 나오는 것만 적는다. 한 이름에 여러 줄임말이 있을 수 있다.
_TYPE_ABBR = {
    "수산고등학교": ("수고",),
    "종합고등학교": ("종고",),
    "공업계고등학교": ("공고", "공업계고"),
    "상업계고등학교": ("상고", "상업계고"),
    "농업계고등학교": ("농고", "농업계고"),
    "여자상업고등학교": ("여상",),
    "여자정보고등학교": ("여정",),
    "여자고등학교": ("여고",),
    "과학고등학교": ("과고",),
    "외국어고등학교": ("외고",),
    "예술고등학교": ("예고",),
    "체육고등학교": ("체고",),
}

# '상고'처럼 학교 **종류**만 친 검색어. 특정 학교의 앞머리가 아니라 그 종류
# 전부를 찾는 것이다. 이름이 실제로 그 종류로 끝날 때만 걸어야 한다 —
# 끝 글자만 보고 맞히면 '서울영상고'가 '상고' 검색에 딸려 나온다.
_TYPE_QUERIES = {
    "공고": ("공업고등학교", "공업계고등학교"),
    "공업고": ("공업고등학교", "공업계고등학교"),
    "상고": ("상업고등학교", "상업계고등학교"),
    "상업고": ("상업고등학교", "상업계고등학교"),
    "농고": ("농업고등학교", "농업계고등학교"),
    "농업고": ("농업고등학교", "농업계고등학교"),
    "실고": ("실업고등학교",),
    "실업고": ("실업고등학교",),
    "수고": ("수산고등학교",),
    "수산고": ("수산고등학교",),
    "종고": ("종합고등학교",),
    "종합고": ("종합고등학교",),
    "여상": ("여자상업고등학교",),
    "여고": ("여자고등학교",),
    "과고": ("과학고등학교",),
    "외고": ("외국어고등학교",),
    "예고": ("예술고등학교",),
    "체고": ("체육고등학교",),
    "해양고": ("해양고등학교",),
    "정보고": ("정보고등학교",),
    "전산고": ("전산고등학교",),
}


def school_search_keys(name: str) -> set:
    """이 학교를 찾을 때 쓰일 수 있는 이름 형태들.

    사람들은 정식 명칭 그대로 치지 않는다. 그래서 같은 학교를 가리키는
    여러 형태를 미리 만들어 두고 그중 하나에만 걸려도 찾게 한다.

      경화여자English Business고등학교
        -> 경화여자EB고등학교 / 경화여자EB고        (영문 머리글자)
        -> 경화여자이비고등학교 / 경화여자이비고     (머리글자를 한글로 읽은 것)
      안양공업고등학교     -> 안양공고               (~업고등학교의 흔한 줄임)
      서울여자상업고등학교 -> 서울여상               (굳어진 종류 줄임말)
    """
    bases = {name, _latin_initials(name)}
    bases |= {_letters_to_korean(b) for b in list(bases)}

    out = set()
    for base in bases:
        out.add(base)
        # '공업계 고등학교'처럼 띄어 쓴 이름도 붙여서 함께 본다.
        flat = base.replace(" ", "")
        out.add(flat)
        m = _SCHOOL_ABBR_TYPE_RE.search(flat)
        if m:
            out.add(flat[: m.start()] + m.group(1) + "고")
        if flat.endswith("고등학교"):
            out.add(flat[: -len("고등학교")] + "고")
        for full, shorts in _TYPE_ABBR.items():
            if flat.endswith(full):
                head = flat[: -len(full)]
                out |= {head + s for s in shorts}
    return {_norm(k) for k in out if k}


def _is_subsequence(needle: str, hay: str) -> bool:
    """needle 의 글자들이 hay 안에 순서대로 있는가.

    '이화미디어고' 가 '이화여자대학교병설미디어고등학교' 안에 순서대로 들어
    있다. 긴 학교명을 앞머리와 특징적인 낱말만 남겨 부르는 습관을 이렇게
    받아 준다.
    """
    it = iter(hay)
    return all(ch in it for ch in needle)


def school_name_matches(query: str, name: str, aliases: str = "",
                        allow_typo: bool = True) -> bool:
    """검색어가 이 학교를 가리키는가(느슨한 판정).

    정확한 부분 일치로 못 찾았을 때만 쓴다. 너무 헐거우면 엉뚱한 학교가
    쏟아지므로 이렇게 좁힌다.
      - '상고'·'공고'처럼 **학교 종류**를 부르는 말은 따로 본다. 특정
        학교가 아니라 그 종류 전부를 찾는 검색이라, 앞머리 규칙도 글자 수
        규칙도 적용하지 않는다. 대신 이름이 실제로 그 종류로 끝날 때만
        걸어야 한다 — 끝 글자만 보면 '서울영상고'가 '상고'에 딸려 온다.
      - 그 밖의 검색어는 3글자 이상이어야 하고, '고등학교'의 일부('고',
        '고등', '학교' …)만 친 것은 받지 않는다. 그걸 받아주면 전부 걸린다.
      - 첫 글자가 학교 이름의 첫 글자와 같아야 한다. 줄임말은 앞머리를
        떼지 않는다('이화…' 를 '미디어고' 라고 부르지는 않는다).
      - 오타 보정은 자모 1개 차이까지만 본다. 그 이상 봐주면 이름이
        비슷한 다른 학교가 함께 나온다.
    """
    q = _norm(query)
    if q in _TYPE_QUERIES:
        flat = _norm(name)
        return any(flat.endswith(full) for full in _TYPE_QUERIES[q])

    if len(q) < 3 or _norm("고등학교").find(q) >= 0:
        return False

    keys = school_search_keys(name)
    for alias in (aliases or "").split(","):
        alias = alias.strip()
        if alias:
            keys |= school_search_keys(alias)

    # 소리가 같은 모음을 합쳐 두면 '에니고'와 '애니고'가 같은 값이 된다.
    qf = _fold_text(q)
    for key in keys:
        kf = _fold_text(key)
        if qf in kf or kf in qf:
            return True
        if kf[:1] != qf[:1]:      # 앞머리가 다르면 여기서 끊는다
            continue
        if _is_subsequence(qf, kf):
            return True
        # 줄임말 자체를 한 글자 잘못 친 경우(예: '예일메디텍고' -> '예일메디택고').
        # 이건 제대로 걸리는 학교가 하나도 없을 때만 본다 — '서울여상' 처럼
        # 한 글자 차이로 다른 학교('서울영상고')와 겹치는 이름이 있어서,
        # 오타 보정을 늘 켜두면 맞게 친 사람에게 엉뚱한 학교가 섞여 나온다.
        if allow_typo and len(qf) >= 4 and _edit_distance(_to_jamo(q), _to_jamo(key), 1) <= 1:
            return True
    return False


@app.get("/api/schools", response_model=schemas.SchoolListOut)
def search_schools(
    name: Optional[str] = Query(None, description="학교 이름 부분 검색"),
    region: Optional[str] = None,
    sigungu: Optional[str] = None,
    category: Optional[str] = None,
    coed: Optional[Coed] = None,
    dept_field: Optional[str] = Query(None, description="학과 계열 키(it, design ...)"),
    sort: str = Query("recommended", pattern="^(recommended|name|views)$"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    include_hidden: bool = Query(False, description="관리자 전용: 숨긴 학교도 포함"),
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    expire_plans(db)

    q = db.query(School).options(selectinload(School.accounts))

    q = apply_school_filters(
        q, db,
        name=name, region=region, sigungu=sigungu, category=category,
        coed=coed, dept_field=dept_field,
        include_hidden=bool(include_hidden and user and user.role == Role.admin),
    )
    total = q.count()

    if total == 0 and name and name.strip():
        # 정식 명칭이 부분 일치하지 않으면, 통용되는 줄임말로 검색했을
        # 가능성을 본다('안양공고', '경화EB고', '경화이비고', '이화미디어고').
        # 0건일 때만 — 매 검색마다 전체 학교를 파이썬에서 훑는 비용을 피한다.
        fallback_base = db.query(School).options(selectinload(School.accounts))
        fallback_base = apply_school_filters(
            fallback_base, db,
            name=None, region=region, sigungu=sigungu, category=category,
            coed=coed, dept_field=dept_field,
            include_hidden=bool(include_hidden and user and user.role == Role.admin),
        )
        candidates = fallback_base.all()
        # 오타 보정 없이 먼저 본다. 제대로 친 검색어에 엉뚱한 학교가 섞이지
        # 않게, 오타 보정은 이렇게 해서도 한 곳도 못 찾았을 때만 쓴다.
        matched_ids = [
            s.id for s in candidates
            if school_name_matches(name, s.name, s.search_aliases or "", allow_typo=False)
        ]
        if not matched_ids:
            matched_ids = [
                s.id for s in candidates
                if school_name_matches(name, s.name, s.search_aliases or "")
            ]
        if matched_ids:
            q = db.query(School).options(
                selectinload(School.accounts)
            ).filter(School.id.in_(matched_ids))
            total = len(matched_ids)

    if sort == "name":
        q = q.order_by(School.name.asc())
    elif sort == "views":
        q = q.order_by(School.view_count.desc(), School.name.asc())
    else:
        # 기본 정렬: 상위 플랜일수록 먼저, 그다음 이름
        q = q.order_by(
            plan_order_sql(db).desc(),
            School.name.asc(),
        )

    rows = q.offset((page - 1) * size).limit(size).all()
    favs = favorite_ids(db, user)
    items = [to_list_item(s, s.id in favs, db) for s in rows]
    # 목록에 떴다는 것을 센다. 나중에 '노출 대비 클릭'을 볼 수 있다.
    bump_exposure(db, [s.id for s in rows], "search")
    return {"total": total, "page": page, "size": size, "items": items}


@app.get("/api/schools/map", response_model=List[schemas.SchoolListItem])
def schools_for_map(
    region: Optional[str] = None,
    sigungu: Optional[str] = None,
    category: Optional[str] = None,
    coed: Optional[Coed] = None,
    name: Optional[str] = None,
    dept_field: Optional[str] = None,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """지도 뷰용. 목록 검색과 '완전히 같은 조건'으로 걸러 좌표가 있는 학교만 내려준다.

    필터 조건은 apply_school_filters 한곳에서만 관리하므로 목록과 어긋나지 않는다.
    좌표가 없는 학교는 지도에 찍을 수 없어 빠진다(목록보다 적을 수 있다).
    """
    q = db.query(School).options(
        selectinload(School.accounts)
    ).filter(
        School.latitude.isnot(None), School.longitude.isnot(None)
    )
    q = apply_school_filters(
        q, db,
        name=name, region=region, sigungu=sigungu, category=category,
        coed=coed, dept_field=dept_field,
    )
    favs = favorite_ids(db, user)
    return [to_list_item(s, s.id in favs, db) for s in q.limit(1000).all()]


# ---------- 조회수 집계 ----------
VIEW_DEDUP_MINUTES = 30     # 같은 사람이 같은 학교를 다시 봐도 이 시간 안에는 안 센다


def _viewer_key(request: Request, user) -> str:
    """열람자를 구분하는 값. 원본을 남기지 않도록 해시해서 쓴다."""
    if user:
        raw = f"u:{user.id}"
    else:
        ip = (
            request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else "")
        )
        agent = request.headers.get("user-agent", "")
        raw = f"a:{ip}|{agent}"
    secret = os.getenv("SECRET_KEY", "change-me")
    return hashlib.sha256((raw + secret).encode()).hexdigest()[:64]


@app.post("/api/schools/{school_id}/view")
def count_school_view(
    school_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """학교 상세를 열었을 때 조회수를 1 올린다.

    같은 사람이 짧은 시간에 반복해 열거나 자동으로 여러 학교를 훑는 경우는 세지
    않는다. 학교 본인 계정과 관리자도 제외한다.
    """
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")

    if user and (user.role == Role.admin or (user.role == Role.school and user.school_id == school_id)):
        return {"counted": False, "reason": "self", "view_count": school.view_count or 0}

    now = datetime.utcnow()
    key = _viewer_key(request, user)

    # 보관 기간이 지난 기록은 지운다(개인정보 최소보유).
    db.query(SchoolViewHit).filter(
        SchoolViewHit.created_at < now - timedelta(hours=2)
    ).delete(synchronize_session=False)

    duplicate = (
        db.query(SchoolViewHit)
        .filter(
            SchoolViewHit.school_id == school_id,
            SchoolViewHit.viewer_key == key,
            SchoolViewHit.created_at >= now - timedelta(minutes=VIEW_DEDUP_MINUTES),
        )
        .first()
    )
    if duplicate:
        db.commit()
        return {"counted": False, "reason": "duplicate", "view_count": school.view_count or 0}

    db.add(SchoolViewHit(school_id=school_id, viewer_key=key, created_at=now))
    school.view_count = (school.view_count or 0) + 1
    today = date.today()
    log = (
        db.query(SchoolView)
        .filter(SchoolView.school_id == school_id, SchoolView.viewed_on == today)
        .first()
    )
    if log:
        log.count += 1
    else:
        db.add(SchoolView(school_id=school_id, viewed_on=today, count=1))
    db.commit()
    return {"counted": True, "view_count": school.view_count}


def bump_exposure(db: Session, school_ids, kind: str) -> None:
    """검색 목록에 뜨거나 진로 테스트에 추천된 횟수를 센다.

    조회수만으로는 '아무도 안 본다'와 '보여줬는데 안 눌린다'를 가릴 수 없다.
    둘은 학교에 할 말이 다르므로 따로 센다.

    화면이 느려지면 안 되므로 하루 한 줄에 더하기만 한다.
    실패해도 검색 결과는 나가야 하니 조용히 넘어간다.
    """
    ids = [i for i in set(school_ids or []) if i]
    if not ids:
        return
    col = SchoolExposure.search_count if kind == "search" else SchoolExposure.quiz_count
    today = date.today()
    try:
        rows = {r.school_id: r for r in db.query(SchoolExposure).filter(
            SchoolExposure.school_id.in_(ids),
            SchoolExposure.shown_on == today).all()}
        for sid in ids:
            row = rows.get(sid)
            if row is None:
                row = SchoolExposure(school_id=sid, shown_on=today,
                                     search_count=0, quiz_count=0)
                db.add(row)
                rows[sid] = row
            if kind == "search":
                row.search_count = (row.search_count or 0) + 1
            else:
                row.quiz_count = (row.quiz_count or 0) + 1
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"[노출 집계] 실패: {exc!r}", flush=True)


def bump_demand(db: Session, region: str, axes) -> None:
    """어느 지역 학생이 어떤 계열을 원했는지 센다.

    수요가 많은데 그 지역에 학교가 적으면, 그 지역 학교에는 강한
    영업 근거가 된다. 개인을 알아볼 수 있는 것은 남기지 않는다.
    """
    region = (region or "").strip()[:40]
    if not region or not axes:
        return
    today = date.today()
    try:
        for axis in list(axes)[:3]:
            row = (db.query(QuizDemand)
                   .filter(QuizDemand.region == region, QuizDemand.axis == axis,
                           QuizDemand.asked_on == today).first())
            if row:
                row.count = (row.count or 0) + 1
            else:
                db.add(QuizDemand(region=region, axis=axis, asked_on=today, count=1))
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"[수요 집계] 실패: {exc!r}", flush=True)


@app.get("/api/schools/{school_id}", response_model=schemas.SchoolDetailOut)
def school_detail(
    school_id: int,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")

    # 조회수는 여기서 세지 않는다. GET 은 새로고침·즐겨찾기 등으로
    # 여러 번 불리므로 그대로 세면 부풀려진다.
    # 화면이 열릴 때 POST /api/schools/{id}/view 를 한 번 호출해 집계한다.

    favs = favorite_ids(db, user)

    base = to_list_item(school, school.id in favs, db)
    base.update(
        {
            "intro": school.intro or "",
            "departments": [d.strip() for d in (school.departments or "").splitlines() if d.strip()],
            "facilities": school.facilities or "",
            "admission_info": school.admission_info or "",
            "youtube_videos": schemas.youtube_videos(school.youtube_urls or ""),
            "employment_rate": school.employment_rate,
            "student_count": school.student_count,
            "established_year": school.established_year,
            "view_count": school.view_count or 0,
            "events": [
                _event_out(e)
                for e in sorted(school.events, key=lambda e: e.start_date)
            ],
        }
    )
    # 만료일은 **관리자에게만** 붙인다. 이 응답은 학생·방문자도 받는 학교
    # 상세라서, 그냥 넣으면 남의 학교 결제 정보가 아무에게나 나간다.
    if user and user.role == Role.admin:
        base["plan_expires_at"] = school.plan_expires_at
        base["plan_days_left"] = plan_days_left(school)
    return base


# ============================================================
# 비교하기
# ============================================================
@app.get("/api/schools/compare/list", response_model=List[schemas.SchoolDetailOut])
def compare_schools(
    ids: str = Query(..., description="쉼표로 구분한 학교 id (최대 3개)"),
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    try:
        id_list = [int(x) for x in ids.split(",") if x.strip()][:3]
    except ValueError:
        raise HTTPException(status_code=400, detail="id 형식이 올바르지 않습니다.")
    result = []
    for sid in id_list:
        school = db.get(School, sid)
        if not school:
            continue
        base = to_list_item(school, False, db)
        base.update(
            {
                "intro": school.intro or "",
                "departments": [d.strip() for d in (school.departments or "").splitlines() if d.strip()],
                "facilities": school.facilities or "",
                "admission_info": school.admission_info or "",
                "youtube_videos": [],
                "employment_rate": school.employment_rate,
                "student_count": school.student_count,
                "established_year": school.established_year,
                "view_count": school.view_count or 0,
                "events": [],
            }
        )
        result.append(base)
    return result


# ============================================================
# 즐겨찾기 (학생 전용)
# ============================================================
@app.get("/api/favorites", response_model=List[schemas.FavoriteOut])
def list_favorites(db: Session = Depends(get_db), user: User = Depends(require_student)):
    rows = (
        db.query(Favorite)
        .filter(Favorite.user_id == user.id)
        .order_by(Favorite.created_at.desc())
        .all()
    )
    out = []
    for f in rows:
        s = f.school
        out.append(
            {
                "school": to_list_item(s, True, db),
                "memo": f.memo or "",
                "created_at": f.created_at,
            }
        )
    return out


@app.post("/api/favorites")
def add_favorite(
    payload: schemas.FavoriteIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_student),
):
    if not db.get(School, payload.school_id):
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")
    exist = (
        db.query(Favorite)
        .filter(Favorite.user_id == user.id, Favorite.school_id == payload.school_id)
        .first()
    )
    if exist:
        exist.memo = payload.memo or exist.memo
        db.commit()
        return {"ok": True, "already": True}
    db.add(Favorite(user_id=user.id, school_id=payload.school_id, memo=payload.memo))
    db.commit()
    return {"ok": True, "already": False}


@app.patch("/api/favorites/{school_id}")
def update_favorite_memo(
    school_id: int,
    payload: schemas.FavoriteIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_student),
):
    fav = (
        db.query(Favorite)
        .filter(Favorite.user_id == user.id, Favorite.school_id == school_id)
        .first()
    )
    if not fav:
        raise HTTPException(status_code=404, detail="즐겨찾기에 없는 학교입니다.")
    fav.memo = payload.memo
    db.commit()
    return {"ok": True}


@app.delete("/api/favorites/{school_id}")
def remove_favorite(
    school_id: int, db: Session = Depends(get_db), user: User = Depends(require_student)
):
    db.query(Favorite).filter(
        Favorite.user_id == user.id, Favorite.school_id == school_id
    ).delete()
    db.commit()
    return {"ok": True}


@app.get("/api/favorites/calendar", response_model=List[dict])
def favorites_calendar(db: Session = Depends(get_db), user: User = Depends(require_student)):
    """즐겨찾기한 학교들의 학교 일정을 D-day 순으로 모아본다."""
    ids = [f.school_id for f in db.query(Favorite).filter(Favorite.user_id == user.id).all()]
    if not ids:
        return []
    events = (
        db.query(AdmissionEvent)
        .filter(AdmissionEvent.school_id.in_(ids))
        .filter(AdmissionEvent.start_date >= date.today() - timedelta(days=7))
        .order_by(AdmissionEvent.start_date.asc())
        .all()
    )
    return [
        {**_event_out(e), "school_id": e.school_id, "school_name": e.school.name,
         "start_date": e.start_date.isoformat(),
         "end_date": e.end_date.isoformat() if e.end_date else None}
        for e in events
    ]



# ============================================================
# 학교 문의 (Q&A) — 접수는 로그인 없이 누구나
# ============================================================
# 개인정보 수집·이용 동의 안내문. 프론트에서도 보여주고, 서버가 원본을 갖는다.
PRIVACY_NOTICE = {
    "collected": ["이메일 주소(필수)", "이름(선택)", "연락처(선택)", "문의 내용"],
    "purpose": "남기신 문의에 대한 답변을 이메일로 보내드리기 위해 수집·이용합니다.",
    "retention": f"접수일로부터 {INQUIRY_RETENTION_DAYS}일 보관 후 파기하며, 학교가 삭제하면 즉시 파기됩니다.",
    "recipient": "선택하신 학교의 담당 계정만 열람합니다. 제3자에게 제공하지 않습니다.",
    "right_to_refuse": "동의를 거부할 수 있으나, 이 경우 문의 답변을 받을 수 없습니다.",
}


@app.get("/api/privacy/inquiry")
def inquiry_privacy_notice():
    """문의 폼에 표시할 개인정보 수집·이용 안내문."""
    return PRIVACY_NOTICE


# 이용약관. 서버가 원문을 갖고, 가입 화면과 약관 페이지에서 보여준다.
# ============================================================
# 환불 규정 (유료 플랜)
# 전자상거래법상 청약철회·대금 환급 조건 표시 의무에 대응한다.
# ※ 실제 운영 전 세무·법률 전문가 검토를 권장한다.
# ============================================================
REFUND_POLICY = {
    "service_name": "우리동네 직업계고(ㅇㅈ)",
    "effective_date": "2026-08-16",
    "summary": [
        "서비스 시작 전 취소는 전액 환불됩니다.",
        "시작 후 중도 해지는 남은 일수만큼 일할 계산해 환불합니다.",
        "환불은 신청일로부터 영업일 기준 7일 이내에 입금 계좌로 처리합니다.",
    ],
    "articles": [
        {
            "title": "제1조 (목적)",
            "body": "이 규정은 우리동네 직업계고(ㅇㅈ)(이하 '서비스')가 학교에 제공하는 유료 노출 플랜의 "
                    "청약철회, 계약 해지, 대금 환급의 조건과 절차를 정함을 목적으로 합니다. "
                    "부가서비스 '기록해'의 개인 자기소개서 이용권은 이 규정이 아니라 "
                    "기록해의 환불 규정(diary.ggm.kr/refund)을 따릅니다.",
        },
        {
            "title": "제2조 (서비스의 성격)",
            "body": "유료 플랜은 신청한 기간 동안 검색 노출 우선순위, 일정 등록, 통계 제공 등의 기능을 "
                    "제공하는 기간제 서비스입니다. 서비스는 입금이 확인되고 운영자가 승인한 시점부터 시작됩니다.",
        },
        {
            "title": "제3조 (서비스 시작 전 취소)",
            "body": "입금 후 서비스가 시작되기 전(운영자 승인 전)에 취소를 요청하시면 결제하신 금액 전액을 환불합니다. "
                    "입금 전 신청은 별도 절차 없이 취소하실 수 있으며, 입금 기한이 지나면 자동으로 만료됩니다.",
        },
        {
            "title": "제4조 (서비스 시작 후 중도 해지)",
            "body": "서비스 시작 후 해지를 요청하시면, 이미 제공된 기간을 제외하고 남은 일수에 대해 일할 계산하여 환불합니다. "
                    "환불액 = 결제금액 × (남은 일수 ÷ 전체 이용일수). 이미 제공된 노출 기간은 환불 대상이 아닙니다.",
        },
        {
            "title": "제5조 (서비스 장애에 따른 보상)",
            "body": "운영자의 귀책사유로 서비스가 연속 24시간 이상 중단된 경우, 중단된 기간의 2배에 해당하는 기간을 "
                    "무상 연장하거나 해당 기간에 상응하는 금액을 환불합니다. 다만 천재지변, 정기 점검 등 "
                    "사전 공지된 중단은 제외합니다.",
        },
        {
            "title": "제6조 (환불이 제한되는 경우)",
            "body": "학교가 허위 정보를 등록하거나 약관을 위반하여 이용이 정지된 경우, 이미 제공된 기간에 대한 "
                    "환불은 제한될 수 있습니다. 이 경우 사유를 사전에 서면(이메일)으로 안내합니다.",
        },
        {
            "title": "제7조 (환불 절차)",
            "body": "환불은 학교 담당자가 이메일 또는 유선으로 요청하시면 접수됩니다. 접수 후 영업일 기준 7일 이내에 "
                    "결제하신 계좌 또는 학교가 지정한 계좌로 입금해 드립니다. 세금계산서가 이미 발행된 경우에는 "
                    "수정세금계산서를 함께 발행합니다.",
        },
        {
            "title": "제8조 (규정의 변경)",
            "body": "이 규정은 시행일부터 적용됩니다. 규정을 변경하는 경우 시행일 7일 전에 "
                    "서비스 화면에 공지하며, 이미 결제가 완료된 건에 대해서는 결제 당시의 "
                    "규정을 적용합니다.",
        },
        {
            "title": "제9조 (문의처)",
            "body": "환불 및 결제 관련 문의는 070-7867-7970 또는 news@sinmoon.net 으로 연락해 주시기 바랍니다. "
                    "운영 기관: 특성화고신문 (사업자등록번호 214-13-75982, 대표 강승구)",
        },
    ],
}


TERMS_OF_SERVICE = {
    "service_name": "우리동네 직업계고(ㅇㅈ)",
    "effective_date": "2026-08-21",
    "articles": [
        {
            "title": "제1조 (목적)",
            "body": "이 약관은 우리동네 직업계고(ㅇㅈ)(이하 '서비스')가 제공하는 직업계고 정보 검색·진로 안내 서비스의 이용 조건과 절차, 이용자와 서비스의 권리·의무를 정함을 목적으로 합니다.",
        },
        {
            "title": "제2조 (서비스의 내용)",
            "body": "서비스는 전국 특성화고·마이스터고 등의 공개 정보 검색, 학교별 소개, 진로 적성 테스트, 특성화고신문 기사 안내 등을 제공합니다. 학교 정보는 나이스 교육정보 개방 포털 등 공개 출처를 바탕으로 하며, 정확성을 보장하지 않습니다.",
        },
        {
            "title": "제3조 (회원가입 및 본인확인)",
            "body": (
                "① 이용자는 이메일, 비밀번호, 이름, 생년월일, 휴대폰번호를 입력하고 이 약관과 "
                "개인정보 수집·이용에 동의하여 회원가입할 수 있습니다.\n"
                "② 휴대폰번호는 본인확인과 아이디·비밀번호 찾기에 사용되는 필수 항목이며, "
                "가입 시 문자 또는 이메일로 발송되는 인증번호 확인 절차를 거쳐야 합니다. "
                "하나의 휴대폰번호로는 하나의 계정만 만들 수 있습니다.\n"
                "③ 만 14세 미만 아동은 개인정보 보호법 제22조의2에 따라 법정대리인의 동의를 "
                "받아야 가입이 완료되며, 동의 전까지 계정은 이용할 수 없습니다.\n"
                "④ 타인의 정보를 도용해 가입할 수 없습니다."
            ),
        },
        {
            "title": "제4조 (이용자의 의무)",
            "body": "이용자는 서비스를 부정한 목적으로 이용하거나, 다른 이용자·학교의 권리를 침해하는 행위, 허위 정보 등록, 시스템에 부담을 주는 행위를 해서는 안 됩니다.",
        },
        {
            "title": "제5조 (게시물의 관리)",
            "body": (
                "① 이용자가 작성한 게시물에 대한 책임은 작성자에게 있습니다.\n"
                "② 서비스는 타인의 권리를 침해하거나 관계 법령·이 약관에 어긋나는 게시물을 "
                "숨기거나 삭제할 수 있습니다. 이 경우 작성자에게 그 사유를 통지합니다.\n"
                "③ 게시물로 권리를 침해받은 자가 삭제를 요청하면, 정보통신망법 제44조의2에 따라 "
                "해당 게시물의 접근을 30일간 임시로 차단할 수 있으며 작성자에게 이를 알립니다.\n"
                "④ 작성자는 조치에 이의가 있으면 고객센터를 통해 재검토를 요청할 수 있습니다."
            ),
        },
        {
            "title": "제6조 (유료 서비스와 검색 결과 노출)",
            "body": (
                "① 서비스는 학교를 대상으로 유료 노출 플랜을 제공하며, 이용 조건과 환불은 "
                "별도의 환불 규정에 따릅니다.\n"
                "② 검색 결과의 기본 정렬인 '추천순'은 제휴(유료 플랜) 학교를 우선 노출한 뒤 "
                "이름 순으로 정렬합니다. 이 사실은 검색 화면에 함께 표시합니다.\n"
                "③ 이용자는 이름순·조회순을 선택하여 제휴 여부와 무관한 순서로 볼 수 있습니다.\n"
                "④ 유료 플랜은 노출 순서에만 영향을 미치며, 학교 정보의 내용에는 "
                "영향을 주지 않습니다.\n"
                "⑤ 서비스는 체험 등의 목적으로 학교에 플랜을 무상으로 제공할 수 있습니다. "
                "무상 제공 기간이 끝나면 별도 통지 없이 무료 플랜으로 전환되며, "
                "이에 대한 환불이나 보상은 발생하지 않습니다. 제공 기간과 종료일은 "
                "학교 관리자 화면에서 확인할 수 있습니다."
            ),
        },
        {
            "title": "제7조 (부가서비스와 학교 이용권)",
            "body": (
                "① 서비스는 같은 계정으로 이용할 수 있는 부가서비스 '기록해'(diary.ggm.kr)를 "
                "함께 운영합니다. 기록해의 일지·일기 작성과 선생님께 제출하는 기능은 "
                "무료로 제공됩니다.\n"
                "② 기록해의 자기소개서 작성과 AI 첨삭 기능은 유료이며, 학교가 이용 "
                "인원수를 정해 신청합니다. 학생 개인은 결제하지 않습니다.\n"
                "③ 요금은 '1명당 단가 × 인원수'로 산정하며, 학교가 신청한 인원은 운영자가 "
                "확인한 뒤 확정됩니다. 확인 과정에서 인원과 금액이 조정될 수 있습니다.\n"
                "④ 학교는 확보한 인원수 범위에서 소속 학생에게 이용 권한을 배정하며, "
                "배정과 회수는 학교가 정합니다. 회수된 학생이 이미 작성한 자기소개서는 "
                "삭제되지 않으며 열람할 수 있습니다.\n"
                "⑤ 이용권의 청약철회와 환불은 기록해의 환불 규정에 따릅니다. "
                "승인 전 취소는 전액 환불되며, 이용이 시작된 뒤에는 남은 기간만큼 일할 "
                "계산하여 환불합니다.\n"
                "⑥ AI 첨삭과 자동 생성 결과는 참고 자료이며, 진학이나 취업의 결과를 "
                "보장하지 않습니다. 이용자는 제출 전 내용을 스스로 확인해야 합니다.\n"
                "⑦ 이용자가 계정을 탈퇴하면 기록해에 저장된 일지·자기소개서도 함께 "
                "삭제됩니다.\n"
                "⑧ 2026년 8월 21일 이전에 학생 개인이 결제한 이용권은 남은 기간 동안 "
                "그대로 이용할 수 있으며, 결제 당시의 규정에 따라 환불합니다."
            ),
        },
        {
            "title": "제8조 (회원 탈퇴 및 자격 상실)",
            "body": "이용자는 언제든지 계정 설정에서 탈퇴할 수 있으며, 탈퇴 시 개인정보는 관련 법령에 따라 파기됩니다. 서비스는 이용자가 약관을 위반한 경우 이용을 제한하거나 계정을 정지할 수 있습니다.",
        },
        {
            "title": "제9조 (면책)",
            "body": "서비스는 천재지변, 시스템 장애, 이용자 귀책 사유로 인한 손해에 대해 책임지지 않습니다. 학교 정보의 최신성·정확성은 각 학교 및 공개 출처에 따르며, 최종 확인은 이용자 본인의 책임입니다.",
        },
        {
            "title": "제10조 (약관의 변경)",
            "body": "서비스는 필요 시 약관을 변경할 수 있으며, 변경 시 시행일과 내용을 서비스 화면에 공지합니다.",
        },
    ],
}


@app.get("/api/terms")
def get_terms():
    """이용약관 원문. 가입 화면과 약관 페이지에서 보여준다."""
    return TERMS_OF_SERVICE


@app.get("/api/refund-policy")
def get_refund_policy():
    """환불 규정. 플랜 신청 화면과 환불 규정 페이지에서 보여준다."""
    return REFUND_POLICY


def _notify_school_of_inquiry(to_addr: str, school_name: str, asker: str,
                              question: str) -> None:
    """문의가 들어왔다고 학교에 알린다. 실패해도 조용히 넘어간다.

    문의자의 이메일·전화번호는 일부러 넣지 않는다. 이 메일의 목적은 '확인해
    보라'는 알림이고, 연락처는 로그인해서 보면 된다. 메일은 전달·전거되기
    쉬워서, 굳이 옮겨 담지 않는 편이 안전하다.
    """
    cfg = mailer.system_config()
    if not cfg.is_ready():
        print("[문의 알림] 메일 계정이 설정되지 않아 보내지 못했습니다.", flush=True)
        return
    short = question.strip()
    if len(short) > 300:
        short = short[:300] + " …"
    subject = f"[우리동네 직업계고] {school_name}에 새 문의가 들어왔습니다"
    body = (
        f"{school_name} 페이지에 문의가 접수되었습니다.\n\n"
        f"보낸 사람: {asker or '(이름 미입력)'}\n"
        f"내용:\n{short}\n\n"
        "답변은 학교 관리 > 문의 관리 화면에서 남기실 수 있습니다.\n"
        "문의자의 연락처도 그 화면에서 확인하실 수 있습니다.\n\n"
        "이 알림을 받는 주소는 학교 관리 > 학교 정보에서 바꾸거나 끌 수 있습니다."
    )
    ok, err = mailer.send_email(cfg, to_addr, subject, body,
                                from_name="우리동네 직업계고")
    if not ok:
        print(f"[문의 알림] 발송 실패({to_addr}): {err}", flush=True)


@app.post("/api/schools/{school_id}/inquiries")
def create_inquiry(
    school_id: int,
    payload: schemas.InquiryCreate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """방문자가 학교에 질문을 남긴다. 이메일은 답변 발송 목적으로만 수집한다."""
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")

    # 보유기간이 지난 문의를 이 학교 범위에서 정리한다.
    purge_old_inquiries(db, school_id=school_id)

    inquiry = Inquiry(
        school_id=school_id,
        asker_name=(payload.asker_name or "").strip(),
        contact_email=str(payload.contact_email).strip(),
        contact_phone=(payload.contact_phone or "").strip(),
        question=payload.question.strip(),
        privacy_consent=payload.privacy_consent,
        status=InquiryStatus.pending,
        delivery_status=DeliveryStatus.pending,
    )
    db.add(inquiry)
    db.commit()
    db.refresh(inquiry)

    # 상담 콘솔에도 같은 건을 올려 둔다. 답변은 여전히 학교가 하지만,
    # 상담원이 "오늘 들어온 일"을 전화와 홈페이지 두 화면으로 나눠 보면
    # 놓치는 건은 반드시 그 사이에서 생긴다.
    # 실패해도 방문자의 문의 접수는 그대로 성공한다(intake 안에서 삼킨다).
    _cc_intake.record_homepage_inquiry(
        db,
        question=inquiry.question,
        name=inquiry.asker_name,
        phone=inquiry.contact_phone,
        email=inquiry.contact_email,
        school_name=school.name,
        subject=f"{school.name} 문의",
        inquiry_id=inquiry.id,
    )

    # 학교가 알림 주소를 넣어 뒀으면 메일로 알린다. 발송은 뒤로 미룬다 —
    # SMTP 가 느리거나 막혀 있을 때 문의를 남긴 사람이 기다리게 두면 안 된다.
    notify_to = (school.inquiry_notify_email or "").strip()
    if notify_to:
        background.add_task(
            _notify_school_of_inquiry, notify_to, school.name,
            inquiry.asker_name, inquiry.question,
        )

    return {
        "ok": True,
        "message": "문의가 접수되었습니다. 학교가 답변하면 입력하신 이메일로 보내드립니다.",
    }


# ============================================================
# 학교 계정 전용
# ============================================================
def my_school(db: Session, user: User) -> School:
    if not user.school_id:
        raise HTTPException(status_code=400, detail="계정에 연결된 학교가 없습니다.")
    school = db.get(School, user.school_id)
    if not school:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")
    return school


@app.get("/api/school-admin/profile")
def get_my_profile(db: Session = Depends(get_db), user: User = Depends(require_school)):
    s = my_school(db, user)
    effective = Plan.free if s.plan_paused else s.plan
    return {
        # 현재 플랜에서 제공되는 기능 (기본 기능 + 켜져 있는 유료 혜택)
        "base_features": [label for _k, label in BASE_FEATURES],
        "my_perks": get_plan_perks(db, effective),
        "my_perk_keys": get_plan_perk_keys(db, effective),
        "id": s.id,
        "name": s.name,
        "category": s.category,
        "region": s.region,
        "address": s.address,
        "coed": s.coed.value,
        "dormitory": s.dormitory,
        "foundation": s.foundation or "",
        "phone": s.phone or "",
        "website": s.website or "",
        "slogan": s.slogan or "",
        "intro": s.intro or "",
        "departments": s.departments or "",
        "facilities": s.facilities or "",
        "admission_info": s.admission_info or "",
        "youtube_urls": s.youtube_urls or "",
        "inquiry_notify_email": s.inquiry_notify_email or "",
        "employment_rate": s.employment_rate,
        "student_count": s.student_count,
        "established_year": s.established_year,
        "hero_image": s.hero_image or "",
        "plan": s.plan.value,
        "plan_expires_at": s.plan_expires_at.isoformat() if s.plan_expires_at else None,
        # 무상 체험이면 화면에서 안내 문구를 달리 보여준다.
        "plan_is_free_trial": bool(s.plan_is_free_trial),
        "plan_granted_note": s.plan_granted_note or "",
    }


@app.put("/api/school-admin/profile")
def update_my_profile(
    payload: schemas.SchoolProfileUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_school),
):
    s = my_school(db, user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(s, field, value)
    refresh_dept_fields(s)   # 학과가 바뀌었으면 계열 캐시를 다시 계산
    db.commit()
    return {"ok": True}


@app.get("/api/school-admin/stats", response_model=schemas.SchoolStatsOut)
def my_stats(db: Session = Depends(get_db), user: User = Depends(require_school)):
    s = my_school(db, user)
    fav_count = db.query(Favorite).filter(Favorite.school_id == s.id).count()

    # 최근 14일 조회수
    start = date.today() - timedelta(days=13)
    logs = {
        v.viewed_on: v.count
        for v in db.query(SchoolView)
        .filter(SchoolView.school_id == s.id, SchoolView.viewed_on >= start)
        .all()
    }
    daily = [
        {"day": (start + timedelta(days=i)).isoformat(), "count": logs.get(start + timedelta(days=i), 0)}
        for i in range(14)
    ]

    # 같은 지역·계열 안에서 몇 번째로 노출되는지
    ranked = (
        db.query(School.id)
        .filter(School.region == s.region, School.category == s.category)
        .order_by(
            plan_order_sql(db).desc(),
            School.name.asc(),
        )
        .all()
    )
    rank_hint = next((i + 1 for i, (sid,) in enumerate(ranked) if sid == s.id), 0)

    return {
        "view_count": s.view_count or 0,
        "favorite_count": fav_count,
        "plan": s.plan,
        "plan_expires_at": s.plan_expires_at,
        "plan_is_free_trial": bool(s.plan_is_free_trial),
        "search_rank_hint": rank_hint,
        "daily_views": daily,
    }


@app.get("/api/school-admin/events", response_model=List[schemas.EventOut])
def my_events(db: Session = Depends(get_db), user: User = Depends(require_school)):
    s = my_school(db, user)
    return [_event_out(e) for e in sorted(s.events, key=lambda e: e.start_date)]


def _require_event_perk(db: Session, s: School, kind: str) -> None:
    need = "briefing" if kind == "briefing" else "events"
    if not school_has_perk(db, s, need):
        label = "학교 설명회" if need == "briefing" else "참가 행사"
        raise HTTPException(
            status_code=403,
            detail=f"{label} 등록은 현재 플랜에서 제공하지 않습니다. 플랜을 확인해주세요.",
        )


@app.post("/api/school-admin/events")
def add_event(
    payload: schemas.EventIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_school),
):
    s = my_school(db, user)
    _require_event_perk(db, s, payload.kind)
    db.add(AdmissionEvent(school_id=s.id, **payload.model_dump()))
    db.commit()
    return {"ok": True}


@app.post("/api/school-admin/events/batch", response_model=List[schemas.EventOut])
def add_events_batch(
    payload: schemas.EventBatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_school),
):
    """같은 일정을 여러 날짜에 걸쳐 한 번에 등록한다."""
    s = my_school(db, user)
    _require_event_perk(db, s, payload.kind)
    created = []
    for slot in payload.dates:
        fields = slot.model_dump()
        # 날짜 칸에 장소를 적었으면 그 날짜만 그 장소로. 안 적었으면 공통 장소.
        fields["location"] = fields.get("location") or payload.location
        e = AdmissionEvent(
            school_id=s.id, kind=payload.kind, title=payload.title,
            registration_url=payload.registration_url,
            description=payload.description, **fields,
        )
        db.add(e)
        created.append(e)
    db.commit()
    for e in created:
        db.refresh(e)
    return [_event_out(e) for e in created]


@app.delete("/api/school-admin/events/{event_id}")
def delete_event(
    event_id: int, db: Session = Depends(get_db), user: User = Depends(require_school)
):
    e = db.get(AdmissionEvent, event_id)
    if not e or e.school_id != user.school_id:
        raise HTTPException(status_code=404, detail="일정을 찾을 수 없습니다.")
    db.delete(e)
    db.commit()
    return {"ok": True}


@app.put("/api/school-admin/events/{event_id}", response_model=schemas.EventOut)
def update_event(
    event_id: int,
    payload: schemas.EventUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_school),
):
    e = db.get(AdmissionEvent, event_id)
    if not e or e.school_id != user.school_id:
        raise HTTPException(status_code=404, detail="일정을 찾을 수 없습니다.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(e, field, value)
    db.commit()
    db.refresh(e)
    return _event_out(e)


# ---------- 재학생 인증 관리 (학교) ----------
@app.post("/api/school-admin/orders", response_model=schemas.OrderOut)
def request_plan(
    payload: schemas.OrderIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_school),
):
    """플랜을 신청한다. 관리자가 입금을 확인하고 승인하면 실제로 적용된다."""
    s = my_school(db, user)
    if payload.plan == Plan.free:
        raise HTTPException(status_code=400, detail="무료 플랜은 신청 대상이 아닙니다.")
    pending = (
        db.query(PlanOrder)
        .filter(
            PlanOrder.school_id == s.id,
            PlanOrder.status.in_([OrderStatus.pending, OrderStatus.paid]),
        )
        .first()
    )
    if pending:
        raise HTTPException(status_code=400, detail="이미 승인 대기 중인 신청이 있습니다.")
    bank = get_bank_info(db)
    try:
        due_days = int(bank.get("due_days") or 14)
    except ValueError:
        due_days = 14
    order = PlanOrder(
        school_id=s.id,
        requested_by=user.id,
        plan=payload.plan,
        months=payload.months,
        amount=plan_amount(db, payload.plan, payload.months),
        note=payload.note,
        deposit_code=make_deposit_code(db),
        due_at=datetime.utcnow() + timedelta(days=due_days),
        tax_email=(payload.tax_email or "").strip()[:255],
        tax_manager=(payload.tax_manager or "").strip()[:60],
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order_out(order)


def order_out(o: PlanOrder) -> dict:
    return {
        "id": o.id,
        "school_id": o.school_id,
        "school_name": o.school.name,
        "plan": o.plan,
        "months": o.months,
        "amount": o.amount,
        "status": o.status,
        "status_label": ORDER_STATUS_LABEL.get(
            o.status.value if hasattr(o.status, "value") else str(o.status), ""
        ),
        "note": o.note or "",
        "deposit_code": o.deposit_code or "",
        "tax_email": o.tax_email or "",
        "tax_manager": o.tax_manager or "",
        "created_at": o.created_at,
        "due_at": o.due_at,
        "paid_at": o.paid_at,
        "handled_at": o.handled_at,
    }


@app.get("/api/school-admin/orders", response_model=List[schemas.OrderOut])
def my_orders(db: Session = Depends(get_db), user: User = Depends(require_school)):
    s = my_school(db, user)
    rows = (
        db.query(PlanOrder)
        .filter(PlanOrder.school_id == s.id)
        .order_by(PlanOrder.created_at.desc())
        .all()
    )
    return [order_out(o) for o in rows]


# ============================================================
# 학교 계정 — 메일 계정(SMTP) 설정
# ============================================================
# ============================================================
# 학교 계정 — 문의 관리
# ============================================================
def inquiry_out(i: Inquiry) -> dict:
    return {
        "id": i.id,
        "asker_name": i.asker_name or "",
        "contact_email": i.contact_email,
        "contact_phone": i.contact_phone or "",
        "question": i.question,
        "status": i.status,
        "answer": i.answer or "",
        "answered_at": i.answered_at,
        "delivery_status": i.delivery_status,
        "delivery_error": i.delivery_error or "",
        "created_at": i.created_at,
    }


@app.get("/api/school-admin/inquiries", response_model=List[schemas.InquiryOut])
def my_inquiries(
    status: Optional[InquiryStatus] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_school),
):
    s = my_school(db, user)
    purge_old_inquiries(db, school_id=s.id)
    q = db.query(Inquiry).filter(Inquiry.school_id == s.id)
    if status:
        q = q.filter(Inquiry.status == status)
    rows = q.order_by(Inquiry.created_at.desc()).all()
    return [inquiry_out(i) for i in rows]


@app.post("/api/school-admin/inquiries/{inquiry_id}/answer")
def answer_inquiry(
    inquiry_id: int,
    answer: str = Form(...),
    files: List[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    user: User = Depends(require_school),
):
    """답변을 저장하고, 문의자가 남긴 이메일로 (첨부파일과 함께) 답변을 발송한다."""
    s = my_school(db, user)
    inquiry = db.get(Inquiry, inquiry_id)
    if not inquiry or inquiry.school_id != s.id:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다.")

    # 첨부파일 읽기 (개수 5개, 합계 10MB 제한)
    MAX_FILES = 5
    MAX_TOTAL = 10 * 1024 * 1024
    attachments = []
    total = 0
    if files:
        if len(files) > MAX_FILES:
            raise HTTPException(status_code=400, detail=f"첨부파일은 최대 {MAX_FILES}개까지 가능합니다.")
        for f in files:
            content = f.file.read()
            if not content:
                continue
            total += len(content)
            if total > MAX_TOTAL:
                raise HTTPException(status_code=400, detail="첨부파일 총 용량은 10MB를 넘을 수 없습니다.")
            attachments.append((f.filename or "attachment", content, f.content_type))

    inquiry.answer = answer.strip()
    inquiry.status = InquiryStatus.answered
    inquiry.answered_at = datetime.utcnow()
    inquiry.answered_by = user.id

    subject = f"[{s.name}] 문의하신 내용에 대한 답변입니다."
    attach_note = (
        f"\n첨부파일 {len(attachments)}개가 함께 발송되었습니다.\n" if attachments else ""
    )
    body = (
        f"{inquiry.asker_name or '문의자'}님, 안녕하세요.\n"
        f"{s.name}에 남겨주신 문의에 대한 답변을 보내드립니다.\n\n"
        "──────────────────────────────\n"
        f"[문의하신 내용]\n{inquiry.question}\n\n"
        f"[답변]\n{inquiry.answer}\n"
        f"{attach_note}"
        "──────────────────────────────\n\n"
        "본 메일은 귀하가 직접 남기신 문의에 대한 답변으로 발송되었습니다.\n"
        "회신이 필요하시면 이 메일에 답장하지 마시고, 학교 대표번호로 문의해 주세요.\n"
        f"※ 입력하신 개인정보는 답변 발송 목적으로만 이용되며, "
        f"접수일로부터 {INQUIRY_RETENTION_DAYS}일 후 파기됩니다."
    )

    # 문의 답변은 학교가 아니라 포털 계정으로 발송한다. (학교 주소를 발신자로
    # 위조하면 SPF/DKIM 검사에 걸려 스팸 처리되므로, 발신은 포털 도메인으로 한다)
    cfg = mailer.system_config()
    if cfg.is_ready():
        body += (
            "\n\n──────────────────────────────\n"
            "본 메일은 우리동네 직업계고 포털이 "
            f"{s.name}의 답변을 대신 전달한 것입니다.\n"
            "추가 문의는 학교 대표번호"
            + (f"({s.phone})" if s.phone else "")
            + "로 연락해 주세요.\n"
        )
        ok, err = mailer.send_email(
            cfg,
            inquiry.contact_email,
            subject,
            body,
            from_name=f"{s.name} · 우리동네 직업계고",
            attachments=attachments,
        )
        inquiry.delivery_status = DeliveryStatus.sent if ok else DeliveryStatus.failed
        inquiry.delivery_error = "" if ok else err
    else:
        inquiry.delivery_status = DeliveryStatus.not_configured
        inquiry.delivery_error = (
            "메일 발송 계정이 없어 이메일이 나가지 않았습니다. "
            "포털 관리자에게 문의해주세요."
        )

    db.commit()
    db.refresh(inquiry)
    return {
        "ok": True,
        "delivery_status": inquiry.delivery_status.value,
        "delivery_error": inquiry.delivery_error or "",
    }


@app.delete("/api/school-admin/inquiries/{inquiry_id}")
def delete_inquiry(
    inquiry_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_school),
):
    """문의를 삭제한다(개인정보 파기). 문의자 요청 또는 처리 완료 후 사용."""
    s = my_school(db, user)
    inquiry = db.get(Inquiry, inquiry_id)
    if not inquiry or inquiry.school_id != s.id:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다.")
    db.delete(inquiry)
    db.commit()
    return {"ok": True}


# ============================================================
# 관리자 전용
# ============================================================
@app.post("/api/admin/schools")
def create_school(
    payload: schemas.SchoolCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    school = School(**payload.model_dump())
    db.add(school)
    db.commit()
    db.refresh(school)
    return {"ok": True, "id": school.id}


@app.patch("/api/admin/schools/{school_id}")
def admin_update_school(
    school_id: int,
    payload: schemas.SchoolAdminUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(school, field, value)
    refresh_dept_fields(school)
    db.commit()
    return {"ok": True}


@app.delete("/api/admin/schools/{school_id}")
def admin_delete_school(
    school_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)
):
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")
    db.query(User).filter(User.school_id == school_id).update({User.school_id: None})
    db.delete(school)
    db.commit()
    return {"ok": True}


@app.post("/api/admin/schools/{school_id}/reset-profile")
def admin_reset_school_profile(
    school_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)
):
    """학교 계정이 채운 상세정보만 비운다. NEIS 기본정보(이름·주소·계열·전화·
    홈페이지·좌표)와 플랜은 건드리지 않는다.

    학과·기숙사 여부·대표 이미지는 남긴다. 학교가 고칠 수 있는 칸이지만
    다시 채우는 비용이 커서, 잘못 눌렀을 때 잃는 것이 크다.
      - 학과: 원래 NEIS 에서 받아온 값이라 지우면 학교마다
        import_neis --majors 를 다시 돌려야 한다(느리다). 계열 검색이 쓰는
        dept_fields 캐시도 같이 둔다 — 둘 중 하나만 남기면 학과는 보이는데
        계열 검색에는 안 잡힌다.
      - 기숙사 여부: import_dormitory 로 받아온 값이다.
      - 대표 이미지: 학교가 올린 파일이라 지우면 다시 받아올 길이 없다.
    """
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")

    school.slogan = ""
    school.intro = ""
    school.facilities = ""
    school.admission_info = ""
    school.youtube_urls = ""
    school.employment_rate = None
    school.student_count = None
    school.established_year = None
    # 학교 일정도 학교가 등록한 것이라 함께 비운다.
    db.query(AdmissionEvent).filter(AdmissionEvent.school_id == school_id).delete()
    db.commit()
    return {"ok": True}


@app.post("/api/admin/schools/{school_id}/reset-plan")
def admin_reset_school_plan(
    school_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)
):
    """이 학교만 무료 플랜으로 되돌리고 만료일·플랜신청 내역을 지운다."""
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")

    school.plan = Plan.free
    school.plan_expires_at = None
    db.query(PlanOrder).filter(PlanOrder.school_id == school_id).delete()
    db.commit()
    return {"ok": True}


@app.post("/api/admin/school-accounts")
def create_school_account(
    payload: schemas.SchoolAccountIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """학교용 계정은 이 경로로만 만들어진다."""
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="이미 가입된 이메일입니다.")
    if not db.get(School, payload.school_id):
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")
    account = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        name=payload.name,
        role=Role.school,
        school_id=payload.school_id,
    )
    db.add(account)
    db.commit()
    return {"ok": True, "id": account.id}


@app.get("/api/admin/users")
def list_users(
    role: Optional[Role] = None,
    q: Optional[str] = Query(None, description="이름·이메일·연락처 검색"),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """계정 목록.

    개인정보 보호를 위해, 검색어(q) 없이 호출하면 관리자 계정만 반환한다.
    학생·학교 계정은 이름·이메일·연락처로 검색해야 조회된다.
    """
    query = db.query(User)
    if role:
        query = query.filter(User.role == role)

    if q and q.strip():
        like = f"%{q.strip()}%"
        # 이름·이메일·연락처 + 연결된 학교명으로도 검색
        query = query.outerjoin(School, User.school_id == School.id).filter(
            or_(
                User.name.ilike(like),
                User.email.ilike(like),
                User.phone.ilike(like),
                School.name.ilike(like),
            )
        )
    else:
        # 검색어가 없으면 관리자 계정만 노출 (개인정보 최소 노출)
        query = query.filter(User.role == Role.admin)

    return [
        {
            "id": u.id,
            "email": u.email,
            "name": u.name,
            "phone": u.phone or "",
            "role": u.role.value,
            "school_name": u.school.name if u.school else None,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat(),
        }
        for u in query.order_by(User.created_at.desc()).all()
    ]


@app.patch("/api/admin/users/{user_id}/active")
def toggle_user(
    user_id: int,
    request: Request,
    active: bool,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
    if target.id == user.id:
        raise HTTPException(status_code=400, detail="본인 계정은 정지할 수 없습니다.")
    target.is_active = active
    db.commit()
    write_audit(db, request, user,
                action="user.activate" if active else "user.deactivate",
                target_type="user", target_id=target.id, detail=target.email)
    return {"ok": True}


@app.post("/api/admin/users/{user_id}/reset-password")
def admin_reset_password(
    user_id: int,
    request: Request,
    payload: schemas.AdminResetPasswordIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """관리자가 사용자의 비밀번호를 새로 지정한다(메일 재설정이 어려울 때 사용)."""
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
    target.password_hash = hash_password(payload.new_password)
    db.commit()
    write_audit(db, request, user, action="user.reset_password",
                target_type="user", target_id=target.id, detail=target.email)
    return {"ok": True}


@app.get("/api/admin/orders", response_model=List[schemas.OrderOut])
def all_orders(
    status: Optional[OrderStatus] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    q = db.query(PlanOrder)
    if status:
        q = q.filter(PlanOrder.status == status)
    return [order_out(o) for o in q.order_by(PlanOrder.created_at.desc()).all()]


# ---------- 견적서 / 거래명세서 ----------
# 공급자 정보 (푸터·약관과 동일한 값)
SUPPLIER = {
    "name": "특성화고신문",
    "biz_no": "214-13-75982",
    "ceo": "강승구",
    "address": "경기도 양주시 고암동 128-2 대영빌딩 4층 4-1호",
    "tel": "070-7867-7970",
    "email": "news@sinmoon.net",
}


def _contract_html(order: PlanOrder, bank: dict, perks: list) -> str:
    """용역계약서. 브라우저 인쇄(Ctrl+P)로 PDF 저장 후 날인해 사용한다."""
    today = date.today().strftime("%Y년 %m월 %d일")
    plan_label = PLAN_META[order.plan]["label"]
    supply = int(round(order.amount / 1.1))
    vat = order.amount - supply
    perk_lines = "".join(f"<li>{p}</li>" for p in perks) or "<li>기본 노출 서비스</li>"

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>용역계약서 - {order.school.name}</title>
<style>
  @page {{ size: A4; margin: 20mm; }}
  body {{ font-family:'Malgun Gothic','맑은 고딕',sans-serif; color:#111; font-size:12.5px; line-height:1.75; }}
  h1 {{ text-align:center; letter-spacing:10px; font-size:24px; margin:0 0 4px; }}
  .sub {{ text-align:center; color:#666; margin-bottom:20px; font-size:12px; }}
  table.info {{ width:100%; border-collapse:collapse; margin-bottom:16px; }}
  table.info th, table.info td {{ border:1px solid #999; padding:6px 9px; }}
  table.info th {{ background:#f2f4f6; width:110px; text-align:left; font-weight:600; }}
  h2 {{ font-size:13.5px; margin:16px 0 4px; }}
  ol.terms {{ padding-left:0; list-style:none; margin:0; }}
  ol.terms li {{ margin-bottom:11px; }}
  ul {{ margin:4px 0 0 18px; padding:0; }}
  .sign {{ margin-top:30px; display:flex; gap:30px; }}
  .sign > div {{ flex:1; border:1px solid #999; padding:12px; }}
  .sign .row {{ margin-bottom:7px; }}
  .stamp {{ display:inline-block; width:56px; height:20px; border-bottom:1px solid #333;
            margin-left:6px; text-align:center; color:#aaa; font-size:11px; }}
  .noprint {{ text-align:center; margin:20px 0; }}
  @media print {{ .noprint {{ display:none; }} }}
  button {{ padding:9px 20px; font-size:14px; cursor:pointer; }}
</style></head><body>

<div class="noprint"><button onclick="window.print()">인쇄 / PDF로 저장</button></div>

<h1>용역계약서</h1>
<div class="sub">직업계고 정보 포털 노출 서비스</div>

<p>{SUPPLIER['name']}(이하 "을"이라 한다)과(와) {order.school.name}(이하 "갑"이라 한다)은(는)
아래와 같이 노출 서비스 이용에 관한 계약을 체결한다.</p>

<table class="info">
  <tr><th>계약 명칭</th><td colspan="3">우리동네 직업계고 {plan_label} 플랜 노출 서비스</td></tr>
  <tr><th>계약 기간</th><td>{order.months}개월 (서비스 개시일로부터)</td>
      <th>계약 금액</th><td><b>{order.amount:,}원</b> (공급가액 {supply:,}원 + 부가세 {vat:,}원)</td></tr>
  <tr><th>계약 체결일</th><td>{today}</td>
      <th>대금 지급 기한</th><td>{order.due_at.strftime('%Y-%m-%d') if order.due_at else '별도 협의'}</td></tr>
</table>

<ol class="terms">
  <li><b>제1조 (목적)</b><br>
    본 계약은 "을"이 운영하는 직업계고 정보 포털에 "갑"의 학교 정보를 노출하는 서비스의
    제공 조건과 대금 지급에 관한 사항을 정함을 목적으로 한다.</li>

  <li><b>제2조 (서비스의 내용)</b><br>
    "을"은 계약 기간 동안 "갑"에게 다음 기능을 제공한다.
    <ul>{perk_lines}</ul></li>

  <li><b>제3조 (계약 기간)</b><br>
    계약 기간은 "을"이 대금 입금을 확인하고 서비스를 개시한 날부터 {order.months}개월로 한다.
    기간 만료 후 연장은 "갑"의 재신청으로 이루어지며 자동 갱신되지 않는다.</li>

  <li><b>제4조 (대금 및 지급 방법)</b><br>
    "갑"은 계약 금액 {order.amount:,}원(부가세 포함)을 아래 계좌로 지급한다.<br>
    · 입금 계좌 : {bank.get('bank_name') or '(미설정)'} {bank.get('bank_account') or '(미설정)'} (예금주 {bank.get('bank_holder') or '-'})<br>
    · 입금자명에 식별 코드 <b>{order.deposit_code or '-'}</b> 를 포함한다.</li>

  <li><b>제5조 (세금계산서)</b><br>
    "을"은 대금 입금이 확인된 후 "갑"이 지정한 담당자
    {('(' + order.tax_manager + ')') if order.tax_manager else ''}
    및 이메일{(' ' + order.tax_email) if order.tax_email else ''}로 세금계산서를 발행한다.</li>

  <li><b>제6조 (자료의 제공과 책임)</b><br>
    "갑"은 노출에 필요한 학교 정보·이미지를 "을"에게 제공하며, 해당 자료의 정확성과 사용 권한에 대한
    책임은 "갑"에게 있다. "을"은 제공받은 자료를 본 서비스 목적 범위에서만 이용한다.</li>

  <li><b>제7조 (계약의 해지 및 환불)</b><br>
    계약의 해지와 대금 환급은 "을"이 정한 환불 규정에 따른다. 서비스 개시 전 취소는 전액 환불하며,
    개시 후 중도 해지는 잔여 일수를 일할 계산하여 환불한다.</li>

  <li><b>제8조 (서비스 중단과 보상)</b><br>
    "을"의 귀책사유로 서비스가 연속 24시간 이상 중단된 경우, 중단 기간의 2배에 해당하는 기간을
    무상 연장하거나 그에 상응하는 금액을 환불한다.</li>

  <li><b>제9조 (개인정보 보호)</b><br>
    양 당사자는 본 계약 수행 과정에서 알게 된 개인정보를 관계 법령에 따라 보호하며,
    계약 목적 외로 이용하거나 제3자에게 제공하지 아니한다.</li>

  <li><b>제10조 (분쟁의 해결)</b><br>
    본 계약에 정하지 아니한 사항은 관계 법령과 일반 상관례에 따르며, 분쟁이 발생한 경우
    상호 협의하여 해결하되 협의가 이루어지지 않으면 "을"의 주소지 관할 법원을 제1심 관할로 한다.</li>
</ol>

<p style="margin-top:22px">본 계약의 성립을 증명하기 위하여 계약서 2부를 작성하여
양 당사자가 기명날인 후 각 1부씩 보관한다.</p>
<p style="text-align:center; margin:18px 0 6px"><b>{today}</b></p>

<div class="sign">
  <div>
    <div class="row"><b>"갑" (발주자)</b></div>
    <div class="row">기관명 : {order.school.name}</div>
    <div class="row">주소 : {order.school.address or ''}</div>
    <div class="row">대표자 : <span class="stamp">(인)</span></div>
  </div>
  <div>
    <div class="row"><b>"을" (수급자)</b></div>
    <div class="row">상호 : {SUPPLIER['name']} (사업자번호 {SUPPLIER['biz_no']})</div>
    <div class="row">주소 : {SUPPLIER['address']}</div>
    <div class="row">대표자 : {SUPPLIER['ceo']} <span class="stamp">(인)</span></div>
  </div>
</div>
</body></html>"""


def _doc_html(kind: str, order: PlanOrder, bank: dict) -> str:
    """견적서/거래명세서 HTML. 브라우저에서 인쇄(Ctrl+P)하면 PDF로 저장된다.
    (서버에서 PDF를 만들면 한글 폰트 문제가 생겨 인쇄 방식을 택했다)"""
    title = "견 적 서" if kind == "quote" else "거래명세서"
    supply = int(round(order.amount / 1.1))      # 공급가액
    vat = order.amount - supply                  # 부가세
    today = date.today().strftime("%Y년 %m월 %d일")
    due = order.due_at.strftime("%Y-%m-%d") if order.due_at else "-"
    plan_label = PLAN_META[order.plan]["label"]

    def won(n):
        return f"{n:,}원"

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>{title} - {order.school.name}</title>
<style>
  @page {{ size: A4; margin: 18mm; }}
  body {{ font-family: 'Malgun Gothic','맑은 고딕',sans-serif; color:#111; font-size:13px; }}
  h1 {{ text-align:center; letter-spacing:14px; font-size:26px; margin:0 0 6px; }}
  .sub {{ text-align:center; color:#666; margin-bottom:22px; }}
  table {{ width:100%; border-collapse:collapse; margin-bottom:18px; }}
  th,td {{ border:1px solid #999; padding:7px 9px; }}
  th {{ background:#f2f4f6; width:110px; text-align:left; font-weight:600; }}
  .right {{ text-align:right; }} .center {{ text-align:center; }}
  .total td {{ background:#f8f9fa; font-weight:700; font-size:15px; }}
  .box {{ border:1px solid #999; padding:12px; margin-bottom:18px; background:#fcfcfd; }}
  .code {{ font-family:Consolas,monospace; font-size:17px; font-weight:700; letter-spacing:1px; }}
  .muted {{ color:#666; font-size:12px; line-height:1.7; }}
  .noprint {{ text-align:center; margin:22px 0; }}
  @media print {{ .noprint {{ display:none; }} }}
  button {{ padding:9px 20px; font-size:14px; cursor:pointer; }}
</style></head><body>

<div class="noprint"><button onclick="window.print()">인쇄 / PDF로 저장</button></div>

<h1>{title}</h1>
<div class="sub">{today}</div>

<table>
  <tr><th>공급받는자</th><td colspan="3">{order.school.name}</td></tr>
  <tr><th>주소</th><td colspan="3">{order.school.address or '-'}</td></tr>
  <tr><th>담당자</th><td>{order.tax_manager or '-'}</td>
      <th>이메일</th><td>{order.tax_email or '-'}</td></tr>
</table>

<table>
  <tr><th>공급자</th><td>{SUPPLIER['name']}</td>
      <th>사업자번호</th><td>{SUPPLIER['biz_no']}</td></tr>
  <tr><th>대표자</th><td>{SUPPLIER['ceo']}</td>
      <th>연락처</th><td>{SUPPLIER['tel']}</td></tr>
  <tr><th>주소</th><td colspan="3">{SUPPLIER['address']}</td></tr>
</table>

<table>
  <tr><th class="center">품목</th><th class="center">기간</th>
      <th class="center">단가</th><th class="center">금액</th></tr>
  <tr>
    <td>우리동네 직업계고 · {plan_label} 플랜 노출 서비스</td>
    <td class="center">{order.months}개월</td>
    <td class="right">{won(order.amount // max(order.months, 1))}</td>
    <td class="right">{won(order.amount)}</td>
  </tr>
  <tr><td colspan="3" class="right">공급가액</td><td class="right">{won(supply)}</td></tr>
  <tr><td colspan="3" class="right">부가세(10%)</td><td class="right">{won(vat)}</td></tr>
  <tr class="total"><td colspan="3" class="right">합계 금액</td><td class="right">{won(order.amount)}</td></tr>
</table>

<div class="box">
  <b>입금 안내</b><br>
  은행 : {bank.get('bank_name') or '(관리자 미설정)'} &nbsp;|&nbsp;
  예금주 : {bank.get('bank_holder') or '-'}<br>
  계좌번호 : {bank.get('bank_account') or '(관리자 미설정)'}<br>
  입금 기한 : {due}<br><br>
  <b>입금자명에 아래 코드를 함께 적어주세요</b><br>
  <span class="code">{order.deposit_code or '-'}</span>
  <div class="muted" style="margin-top:8px">{bank.get('payment_note') or ''}</div>
</div>

<div class="muted">
  · 본 {title.replace(' ','')}의 유효기간은 발행일로부터 30일입니다.<br>
  · 세금계산서는 입금 확인 후 담당자 이메일로 발행됩니다.<br>
  · 문의 : {SUPPLIER['tel']} / {SUPPLIER['email']}
</div>
</body></html>"""


def _order_doc(kind: str, order_id: int, db: Session, school_id: int = None):
    o = db.get(PlanOrder, order_id)
    if not o or (school_id is not None and o.school_id != school_id):
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다.")
    bank = get_bank_info(db)
    if kind == "contract":
        html = _contract_html(o, bank, get_plan_perks(db, o.plan))
    else:
        html = _doc_html(kind, o, bank)
    return Response(content=html, media_type="text/html; charset=utf-8")


@app.get("/api/school-admin/orders/{order_id}/quote", include_in_schema=False)
def school_order_quote(
    order_id: int,
    kind: str = Query("quote", pattern="^(quote|statement|contract)$"),
    db: Session = Depends(get_db),
    user: User = Depends(require_school),
):
    """학교가 내려받는 견적서(또는 거래명세서)."""
    return _order_doc(kind, order_id, db, school_id=my_school(db, user).id)


@app.get("/api/admin/orders/{order_id}/quote", include_in_schema=False)
def admin_order_quote(
    order_id: int,
    kind: str = Query("quote", pattern="^(quote|statement|contract)$"),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    return _order_doc(kind, order_id, db)


@app.get("/api/nav-visibility")
def nav_visibility(db: Session = Depends(get_db)):
    """상단 메뉴가 물어본다. 로그인 없이도 답한다."""
    return get_nav(db)


@app.get("/api/admin/nav-visibility")
def admin_get_nav(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return {"items": [{"key": k, "label": NAV_LABEL[k], "visible": v}
                      for k, v in get_nav(db).items()]}


@app.put("/api/admin/nav-visibility")
def admin_set_nav(payload: dict, db: Session = Depends(get_db),
                  user: User = Depends(require_admin)):
    set_nav(db, {k: bool(v) for k, v in payload.items() if k in NAV_KEYS})
    return admin_get_nav(db, user)


@app.get("/api/floating-button")
def floating_button(
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """오른쪽 아래 동그란 버튼 설정. 대상 역할이 아니면 꺼진 것으로 응답한다."""
    cfg = get_fab(db)
    # 문의 폼을 여는 버튼은 주소가 없어도 된다.
    if not cfg["enabled"] or (cfg["action"] == "link" and not cfg["url"]):
        return {"enabled": False}
    role = user.role.value if user else "guest"
    if role not in cfg["roles"]:
        return {"enabled": False}
    return {"enabled": True, "url": cfg["url"], "label": cfg["label"],
            "action": cfg["action"]}


@app.get("/api/admin/floating-button")
def admin_get_fab(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return get_fab(db)


@app.put("/api/admin/floating-button")
def admin_set_fab(
    payload: schemas.FloatingButtonIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    url = (payload.url or "").strip()
    action = payload.action if payload.action in ("link", "inquiry") else "link"
    # javascript: 같은 위험한 주소를 막는다
    if url and not re.match(r"^https?://", url, re.I):
        raise HTTPException(
            status_code=400,
            detail="주소는 http:// 또는 https:// 로 시작해야 합니다.",
        )
    if payload.enabled and action == "link" and not url:
        raise HTTPException(status_code=400, detail="버튼을 켜려면 연결할 주소를 입력해주세요.")
    # guest = 로그인하지 않은 방문자. 문의 폼은 아직 회원이 아닌 학교·기관
    # 담당자가 남기는 창구라, 여기를 못 고르면 정작 필요한 사람에게 안 보인다.
    valid_roles = [r for r in (payload.roles or [])
                   if r in ("guest", "student", "teacher", "school", "admin")]
    set_fab(db, {
        "enabled": payload.enabled,
        "action": action,
        "url": url[:500],
        "label": (payload.label or "바로가기").strip()[:30],
        "roles": valid_roles or ["school", "teacher"],
    })
    return get_fab(db)


# ---------- 입금 계좌 설정 (관리자) ----------
@app.get("/api/admin/bank-info")
def admin_get_bank_info(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return get_bank_info(db)


@app.put("/api/admin/bank-info")
def admin_set_bank_info(
    payload: schemas.BankInfoIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    set_bank_info(db, payload.model_dump(exclude_none=True))
    return get_bank_info(db)


@app.get("/api/school-admin/bank-info")
def school_get_bank_info(db: Session = Depends(get_db), user: User = Depends(require_school)):
    """학교가 입금할 계좌 안내."""
    return get_bank_info(db)


# ---------- 주문 상태 전환 ----------
@app.post("/api/admin/orders/{order_id}/paid")
def admin_mark_paid(
    order_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)
):
    """입금이 확인됐다고 표시한다. (승인은 아직 아님)"""
    o = db.get(PlanOrder, order_id)
    if not o:
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다.")
    if o.status != OrderStatus.pending:
        raise HTTPException(
            status_code=400,
            detail=f"입금 대기 상태인 주문만 확인할 수 있습니다. (현재 {ORDER_STATUS_LABEL.get(o.status.value, o.status.value)})",
        )
    o.status = OrderStatus.paid
    o.paid_at = datetime.utcnow()
    db.commit()
    return order_out(o)


@app.post("/api/admin/orders/{order_id}/expire")
def admin_expire_order(
    order_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)
):
    """기한 내 미입금 신청을 만료 처리한다."""
    o = db.get(PlanOrder, order_id)
    if not o:
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다.")
    if o.status != OrderStatus.pending:
        raise HTTPException(
            status_code=400,
            detail=f"입금 대기 상태인 주문만 만료 처리할 수 있습니다. (현재 {ORDER_STATUS_LABEL.get(o.status.value, o.status.value)})",
        )
    o.status = OrderStatus.expired
    o.handled_at = datetime.utcnow()
    db.commit()
    return order_out(o)


@app.post("/api/admin/orders/{order_id}/approve")
def approve_order(
    order_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)
):
    order = db.get(PlanOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다.")
    # 입금 대기 중이거나 입금 확인된 신청만 승인할 수 있다
    if order.status not in (OrderStatus.pending, OrderStatus.paid):
        raise HTTPException(status_code=400, detail="이미 처리된 신청입니다.")
    school = order.school
    # 남은 기간이 있으면 이어붙이고, 없으면 오늘부터 시작한다.
    base = (
        school.plan_expires_at
        if school.plan_expires_at and school.plan_expires_at > date.today()
        else date.today()
    )
    school.plan = order.plan
    school.plan_expires_at = base + timedelta(days=30 * order.months)
    order.status = OrderStatus.approved
    if not order.paid_at:
        order.paid_at = datetime.utcnow()
    order.handled_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "plan": school.plan.value, "expires_at": school.plan_expires_at.isoformat()}


@app.post("/api/admin/orders/{order_id}/reject")
def reject_order(
    order_id: int,
    reason: str = Query("", max_length=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    order = db.get(PlanOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다.")
    if order.status not in (OrderStatus.pending, OrderStatus.paid):
        raise HTTPException(status_code=400, detail="이미 처리된 신청입니다.")
    order.status = OrderStatus.rejected
    order.note = reason or order.note
    order.handled_at = datetime.utcnow()
    db.commit()
    return {"ok": True}



@app.get("/api/admin/audit-logs")
def admin_audit_logs(
    limit: int = Query(100, ge=1, le=500),
    action: str = Query("", description="특정 행위만 보기"),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """관리자 활동 기록 조회. 조회 시점에 보관 기간이 지난 기록을 정리한다."""
    purge_old_audit_logs(db)
    q = db.query(AdminAuditLog)
    if action:
        q = q.filter(AdminAuditLog.action == action)
    rows = q.order_by(AdminAuditLog.created_at.desc()).limit(limit).all()
    return [{
        "id": r.id,
        "actor_email": r.actor_email,
        "actor_role": r.actor_role,
        "action": r.action,
        "target_type": r.target_type,
        "target_id": r.target_id,
        "detail": r.detail,
        "ip": r.ip,
        "created_at": r.created_at,
    } for r in rows]


@app.get("/api/admin/stats", response_model=schemas.AdminStatsOut)
def admin_stats(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    expire_plans(db)
    school_count = db.query(School).count()
    students = db.query(User).filter(User.role == Role.student).count()
    school_accounts = db.query(User).filter(User.role == Role.school).count()
    pending = db.query(PlanOrder).filter(PlanOrder.status == OrderStatus.pending).count()

    plan_dist = {}
    for p in [Plan.free, Plan.basic, Plan.premium, Plan.platinum]:
        n = db.query(School).filter(School.plan == p).count()
        plan_dist[PLAN_META[p]["label"]] = n

    # 예전에는 "플랜별 학교 수 × 정가"를 매출로 보여 줬다. 무료로 올려 준 학교,
    # 할인, 입금 전 학교까지 정가로 잡혀 실제 들어온 돈과 전혀 달랐다.
    # 이제 **결제가 끝난 주문**만 더한다.
    revenue_info = _paid_revenue(db)

    region_dist = {
        r: c
        for r, c in db.query(School.region, func.count(School.id))
        .group_by(School.region)
        .order_by(func.count(School.id).desc())
        .all()
    }

    top = (
        db.query(School)
        .order_by(School.view_count.desc())
        .limit(8)
        .all()
    )
    top_viewed = [
        {"name": s.name, "views": s.view_count or 0, "plan": PLAN_META[s.plan]["label"]}
        for s in top
    ]

    return {
        "school_count": school_count,
        "student_count": students,
        "school_account_count": school_accounts,
        "pending_orders": pending,
        "monthly_revenue": revenue_info["this_month"]["net"],
        "revenue": revenue_info,
        "plan_distribution": plan_dist,
        "region_distribution": region_dist,
        "top_viewed": top_viewed,
        "quiz_stats": _quiz_stats(db),
    }


def _kst_month_range(offset: int = 0):
    """이번 달(offset=0)·지난달(-1)의 UTC 구간. 달은 한국 날짜로 끊는다."""
    now = datetime.utcnow() + timedelta(hours=9)
    y, m = now.year, now.month + offset
    while m < 1:
        m += 12
        y -= 1
    start = datetime(y, m, 1)
    end = datetime(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return start - timedelta(hours=9), end - timedelta(hours=9), f"{y:04d}-{m:02d}"


def _paid_revenue(db: Session) -> dict:
    """결제 완료 주문의 금액. 이번 달·지난달·전체.

    **무엇을 결제 완료로 보나** — 업무 사이트(work-backend/app/settlement.py)의
    정산과 같은 기준이다. 두 화면의 이번 달 매출이 달라지면 안 된다.
      - 학교 플랜: 입금 확인·승인된 주문, 입금 확인일의 달
      - 구독: 입금 확인된 주문(입금일의 달). 환불은 환불한 날의 달에서 뺀다
      - 유료 신청: 입금 확인·완료 건. 입금 시각 기록이 없어 신청일의 달
    """
    from .models import ServiceApplication

    def one(a=None, b=None):
        def between(col):
            conds = [col.isnot(None)]
            if a is not None:
                conds += [col >= a, col < b]
            return conds

        plan_q = db.query(func.coalesce(func.sum(PlanOrder.amount), 0), func.count(PlanOrder.id)).filter(
            PlanOrder.status.in_([OrderStatus.paid, OrderStatus.approved]), *between(PlanOrder.paid_at))
        plan_sum, plan_n = plan_q.one()

        sub_sum, sub_n = db.query(
            func.coalesce(func.sum(SubscriptionOrder.amount), 0), func.count(SubscriptionOrder.id)
        ).filter(*between(SubscriptionOrder.paid_at)).one()

        refund_sum, refund_n = db.query(
            func.coalesce(func.sum(SubscriptionOrder.amount), 0), func.count(SubscriptionOrder.id)
        ).filter(SubscriptionOrder.paid_at.isnot(None), *between(SubscriptionOrder.refunded_at)).one()

        app_q = db.query(
            func.coalesce(func.sum(ServiceApplication.amount), 0), func.count(ServiceApplication.id)
        ).filter(ServiceApplication.status.in_(("paid", "done")), ServiceApplication.amount > 0,
                 *between(ServiceApplication.created_at))
        app_sum, app_n = app_q.one()

        sales = int(plan_sum) + int(sub_sum) + int(app_sum)
        return {
            "sales": sales,
            "refunds": int(refund_sum),
            "net": sales - int(refund_sum),
            "orders": int(plan_n) + int(sub_n) + int(app_n),
            "refund_count": int(refund_n),
            "by_kind": {"학교 플랜": int(plan_sum), "구독": int(sub_sum), "유료 신청": int(app_sum)},
        }

    a0, b0, m0 = _kst_month_range(0)
    a1, b1, m1 = _kst_month_range(-1)
    return {
        "this_month": {"month": m0, **one(a0, b0)},
        "last_month": {"month": m1, **one(a1, b1)},
        "all_time": one(),
    }


def _quiz_stats(db: Session) -> dict:
    """진로 적성 테스트 참여자 수 (오늘/이번 달/올해/전체)."""
    now = datetime.utcnow()
    today = datetime(now.year, now.month, now.day)
    month = datetime(now.year, now.month, 1)
    year = datetime(now.year, 1, 1)

    def cnt(since=None):
        q = db.query(func.count(QuizTaken.id))
        if since is not None:
            q = q.filter(QuizTaken.created_at >= since)
        return int(q.scalar() or 0)

    members = int(
        db.query(func.count(QuizTaken.id))
        .filter(QuizTaken.user_id.isnot(None))
        .scalar()
        or 0
    )
    total = cnt()
    return {
        "today": cnt(today),
        "month": cnt(month),
        "year": cnt(year),
        "total": total,
        "members": members,          # 로그인 상태로 참여
        "guests": total - members,   # 비로그인 참여
    }


@app.get("/api/admin/stats/export", include_in_schema=False)
def admin_stats_export(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """학교 영업에 바로 쓸 수 있는 현황 리포트(CSV).

    포털 규모·참여율 같은 '제안용 근거'와, 학교별 관심도·미개설 학교 목록 같은
    '영업 대상 리스트'를 함께 담는다. 엑셀에서 열리도록 UTF-8 BOM을 붙인다.
    """
    import csv
    import io

    today = date.today()
    now = datetime.utcnow()

    # ---- 기본 집계 ----
    total_schools = db.query(func.count(School.id)).scalar() or 0
    visible_schools = db.query(func.count(School.id)).filter(School.is_visible.is_(True)).scalar() or 0
    students = db.query(func.count(User.id)).filter(User.role == Role.student).scalar() or 0
    teachers = db.query(func.count(User.id)).filter(User.role == Role.teacher).scalar() or 0

    # 학교 계정이 개설된 학교
    account_school_ids = {
        r[0] for r in db.query(User.school_id)
        .filter(User.role == Role.school, User.school_id.isnot(None)).distinct().all()
    }
    with_account = len(account_school_ids)
    paid = db.query(func.count(School.id)).filter(School.plan != Plan.free).scalar() or 0

    # 학교별 관심도 지표 (한 번에 집계해 N+1 회피)
    fav_map = dict(db.query(Favorite.school_id, func.count(Favorite.id)).group_by(Favorite.school_id).all())
    inq_map = dict(db.query(Inquiry.school_id, func.count(Inquiry.id)).group_by(Inquiry.school_id).all())
    d30_date = today - timedelta(days=30)
    view30_map = dict(
        db.query(SchoolView.school_id, func.coalesce(func.sum(SchoolView.count), 0))
        .filter(SchoolView.viewed_on >= d30_date).group_by(SchoolView.school_id).all()
    )
    # 노출(목록에 뜬 횟수)과 진로 테스트 추천 횟수. 조회수와 견주면
    # '보여줬는데 안 눌린다'가 드러난다.
    show30_map = dict(
        db.query(SchoolExposure.school_id,
                 func.coalesce(func.sum(SchoolExposure.search_count), 0))
        .filter(SchoolExposure.shown_on >= d30_date)
        .group_by(SchoolExposure.school_id).all()
    )
    quiz30_map = dict(
        db.query(SchoolExposure.school_id,
                 func.coalesce(func.sum(SchoolExposure.quiz_count), 0))
        .filter(SchoolExposure.shown_on >= d30_date)
        .group_by(SchoolExposure.school_id).all()
    )

    def pct(n, d):
        return f"{(n / d * 100):.1f}%" if d else "0.0%"

    buf = io.StringIO()
    w = csv.writer(buf)

    w.writerow([f"우리동네 직업계고 · 학교 영업용 현황 리포트"])
    w.writerow(["생성일", today.isoformat()])
    w.writerow([])

    # ---------- 1. 포털 규모 (제안서에 쓰는 숫자) ----------
    w.writerow(["[1. 포털 규모]"])
    w.writerow(["항목", "값", "설명"])
    w.writerow(["등록 학교 수", total_schools, "전국 직업계고 데이터 보유량"])
    w.writerow(["검색 노출 학교 수", visible_schools, "실제 노출 중인 학교"])
    w.writerow(["학생 회원 수", students, "가입한 학생·학부모"])
    w.writerow(["선생님 계정 수", teachers, "학교가 발급한 선생님 계정"])
    w.writerow(["누적 학교 조회수", db.query(func.coalesce(func.sum(School.view_count), 0)).scalar() or 0, "전체 학교 페이지 조회 합계"])
    w.writerow(["최근 30일 조회수",
                db.query(func.coalesce(func.sum(SchoolView.count), 0)).filter(SchoolView.viewed_on >= d30_date).scalar() or 0,
                "최근 한 달 열람 건수"])
    w.writerow([])

    # ---------- 2. 참여율 (영업 핵심 지표) ----------
    w.writerow(["[2. 참여율]"])
    w.writerow(["지표", "수치", "비율", "영업 활용"])
    w.writerow(["학교 계정 개설", with_account, pct(with_account, total_schools),
                "아직 개설 안 한 학교가 주요 영업 대상"])
    w.writerow(["유료 플랜 이용", paid, pct(paid, total_schools), "무료→유료 전환 여지"])
    paid_with_account = (
        db.query(func.count(School.id))
        .filter(School.plan != Plan.free, School.id.in_(account_school_ids or [0]))
        .scalar() or 0
    ) if account_school_ids else 0
    w.writerow(["계정 보유 학교 중 유료", paid_with_account, pct(paid_with_account, with_account),
                "계정을 만든 학교가 실제 결제로 이어진 비율"])
    w.writerow(["즐겨찾기된 학교", len(fav_map), pct(len(fav_map), total_schools), "관심 학교 비중"])
    w.writerow(["문의를 받은 학교", len(inq_map), pct(len(inq_map), total_schools), "실제 문의 발생 학교"])
    w.writerow([])

    # ---------- 3. 진로 테스트 참여 ----------
    q = _quiz_stats(db)
    w.writerow(["[3. 진로 적성 테스트 참여]"])
    w.writerow(["기간", "참여 수"])
    for label, key in [("오늘", "today"), ("이번 달", "month"), ("올해", "year"), ("전체", "total")]:
        w.writerow([label, q.get(key, 0)])
    w.writerow(["회원 참여", q.get("members", 0)])
    w.writerow(["비회원 참여", q.get("guests", 0)])
    w.writerow([])

    # ---------- 4. 최근 30일 일별 조회 추이 ----------
    w.writerow(["[4. 최근 30일 일별 조회수]"])
    w.writerow(["날짜", "조회수"])
    daily = (
        db.query(SchoolView.viewed_on, func.coalesce(func.sum(SchoolView.count), 0))
        .filter(SchoolView.viewed_on >= d30_date)
        .group_by(SchoolView.viewed_on)
        .order_by(SchoolView.viewed_on)
        .all()
    )
    for day, cnt in daily:
        w.writerow([day, cnt])
    if not daily:
        w.writerow(["(기록 없음)", 0])
    w.writerow([])

    # ---------- 5. 지역별 현황 (영업 타겟팅) ----------
    w.writerow(["[5. 지역별 현황]"])
    w.writerow(["지역", "학교 수", "계정 개설", "유료 플랜", "계정 개설률"])
    region_rows = (
        db.query(School.region, func.count(School.id))
        .group_by(School.region).order_by(func.count(School.id).desc()).all()
    )
    for region, cnt in region_rows:
        ids = {r[0] for r in db.query(School.id).filter(School.region == region).all()}
        acc = len(ids & account_school_ids)
        pay = db.query(func.count(School.id)).filter(
            School.region == region, School.plan != Plan.free
        ).scalar() or 0
        w.writerow([region, cnt, acc, pay, pct(acc, cnt)])
    w.writerow([])

    # ---------- 6. 학교별 관심도 (제안 근거) ----------
    w.writerow(["[6. 학교별 관심도 — 조회 많은 순]"])
    w.writerow(["학교명", "지역", "계열", "현재 플랜", "계정 개설",
                "누적 조회", "최근 30일 조회",
                "검색 노출(30일)", "클릭률", "진로테스트 추천(30일)",
                "즐겨찾기", "문의", "연락처"])
    top = (
        db.query(School)
        .order_by(func.coalesce(School.view_count, 0).desc())
        .limit(300).all()
    )
    def ctr(school_id):
        """노출 대비 클릭률. 보여준 적이 없으면 비율을 낼 수 없다."""
        shown = show30_map.get(school_id, 0)
        if not shown:
            return "-"
        return f"{view30_map.get(school_id, 0) / shown * 100:.1f}%"

    for s in top:
        w.writerow([
            s.name, s.region, s.category, PLAN_META[s.plan]["label"],
            "O" if s.id in account_school_ids else "X",
            s.view_count or 0, view30_map.get(s.id, 0),
            show30_map.get(s.id, 0), ctr(s.id), quiz30_map.get(s.id, 0),
            fav_map.get(s.id, 0), inq_map.get(s.id, 0),
            s.phone or "",
        ])
    w.writerow([])

    # ---------- 7. 영업 대상: 관심은 있는데 계정이 없는 학교 ----------
    w.writerow(["[7. 우선 영업 대상 — 관심도는 있으나 계정 미개설]"])
    w.writerow(["학교명", "지역", "계열", "누적 조회", "즐겨찾기", "문의", "연락처", "홈페이지"])
    candidates = []
    for s in db.query(School).filter(School.is_visible.is_(True)).all():
        if s.id in account_school_ids:
            continue
        score = (s.view_count or 0) + fav_map.get(s.id, 0) * 5 + inq_map.get(s.id, 0) * 10
        if score > 0:
            candidates.append((score, s))
    candidates.sort(key=lambda x: -x[0])
    for _score, s in candidates[:200]:
        w.writerow([
            s.name, s.region, s.category, s.view_count or 0,
            fav_map.get(s.id, 0), inq_map.get(s.id, 0), s.phone or "", s.website or "",
        ])
    if not candidates:
        w.writerow(["(해당 학교 없음)"])
    w.writerow([])

    from .import_neis import VOCATIONAL_CATEGORIES, short_region

    # ---------- 8. 노출은 많은데 안 눌리는 학교 ----------
    # 조회수가 낮다고 다 같은 사정이 아니다. 아예 안 보이는 학교와,
    # 보여줬는데 안 눌리는 학교는 할 말이 다르다.
    #   · 안 보임      → 학과·지역 정보가 부실해 검색에 안 걸린다
    #   · 안 눌림      → 소개·사진이 없어 목록에서 매력이 없다
    w.writerow(["[8. 노출은 많은데 클릭이 적은 학교 — 소개 부실 의심]"])
    w.writerow(["학교명", "지역", "계열", "현재 플랜",
                "검색 노출(30일)", "조회(30일)", "클릭률",
                "소개 있음", "학과 있음", "연락처"])
    weak = []
    for s in db.query(School).filter(School.is_visible.is_(True)).all():
        shown = show30_map.get(s.id, 0)
        if shown < 20:          # 표본이 적으면 비율이 의미 없다
            continue
        clicked = view30_map.get(s.id, 0)
        rate = clicked / shown
        if rate < 0.05:         # 20번 떠서 한 번도 안 눌린 수준
            weak.append((shown, s, clicked, rate))
    weak.sort(key=lambda x: -x[0])
    for shown, s, clicked, rate in weak[:150]:
        w.writerow([
            s.name, s.region, s.category, PLAN_META[s.plan]["label"],
            shown, clicked, f"{rate * 100:.1f}%",
            "O" if (s.intro or "").strip() else "X",
            "O" if (s.departments or "").strip() else "X",
            s.phone or "",
        ])
    if not weak:
        w.writerow(["(아직 표본이 모자랍니다. 며칠 쌓인 뒤에 보세요.)"])
    w.writerow([])

    # ---------- 9. 지역별 수요 대비 공급 ----------
    # 학생이 원하는 계열과 그 지역 학교 수를 견준다.
    # 수요가 많은데 학교가 적으면, 그 지역 학교에는 강한 영업 근거가 된다.
    w.writerow(["[9. 지역별 수요 대비 공급 — 진로 테스트 기준]"])
    w.writerow(["지역", "원하는 계열", "학생 수요(30일)",
                "그 지역 해당 계열 학교 수", "학생당 학교", "판단"])

    demand_rows = (
        db.query(QuizDemand.region, QuizDemand.axis,
                 func.coalesce(func.sum(QuizDemand.count), 0))
        .filter(QuizDemand.asked_on >= d30_date)
        .group_by(QuizDemand.region, QuizDemand.axis)
        .order_by(func.sum(QuizDemand.count).desc())
        .all()
    )
    if not demand_rows:
        w.writerow(["(진로 테스트에서 위치를 알려준 기록이 아직 없습니다.)"])
    else:
        # 계열별 키워드로 그 지역에 학교가 몇 곳인지 센다.
        vocational = (db.query(School)
                      .filter(School.category.in_(VOCATIONAL_CATEGORIES)).all())
        for region, axis, want in demand_rows[:60]:
            kw = []
            for g in quiz_logic.DEPARTMENT_GROUPS.get(axis, []):
                kw.extend(g["keywords"])
            # School.region 은 '경기'·'전남' 처럼 줄인 이름이고,
            # 수요 쪽은 '경기도 양주시' 같은 주소다. 학교를 넣을 때 쓰는
            # 같은 함수로 줄여야 '전라남도'와 '전남'이 서로 맞는다.
            want_sido = short_region(region or "")

            supply = 0
            for sc in vocational:
                if want_sido and want_sido != (sc.region or ""):
                    continue
                depts = [d.strip() for d in (sc.departments or "").splitlines() if d.strip()]
                if depts and quiz_logic.department_matches(depts, kw):
                    supply += 1
            per = f"{supply / want:.2f}" if want else "-"
            if supply == 0:
                verdict = "학교 없음 — 신설·영업 기회"
            elif want / max(supply, 1) >= 10:
                verdict = "수요 몰림 — 유료 노출 제안"
            else:
                verdict = ""
            w.writerow([region, quiz_logic.AXIS_LABEL.get(axis, axis),
                        want, supply, per, verdict])
    w.writerow([])

    # ---------- 10. 매출 ----------
    w.writerow(["[10. 플랜·매출]"])
    w.writerow(["플랜", "학교 수", "월 가격(원)"])
    for p in (Plan.free, Plan.basic, Plan.premium, Plan.platinum):
        cnt = db.query(func.count(School.id)).filter(School.plan == p).scalar() or 0
        w.writerow([PLAN_META[p]["label"], cnt, get_plan_price(db, p)])
    revenue = sum(
        get_plan_price(db, p) * (db.query(func.count(School.id)).filter(School.plan == p).scalar() or 0)
        for p in (Plan.basic, Plan.premium, Plan.platinum)
    )
    w.writerow(["월 예상 매출", revenue, ""])

    csv_text = "\ufeff" + buf.getvalue()   # 엑셀 한글 깨짐 방지(BOM)
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="udj-sales-report-{today}.csv"'
        },
    )


# ============================================================
# 진로 적성 테스트
# ============================================================
@app.get("/api/quiz/questions")
def quiz_questions(seed: Optional[int] = Query(None)):
    """문항, 축 정보, 통학 거리 선택지를 내려준다.

    회차마다 문항이 달라진다. 어떤 문항을 냈는지는 seed 로 되살릴 수 있어,
    채점할 때 학생이 실제로 본 문항으로 매길 수 있다.
    seed 를 넘기면 그 회차를 그대로 다시 보여준다(새로고침·공유용).
    """
    if seed is None:
        seed = secrets.randbelow(10 ** 9)
    items = quiz_logic.questions_for(seed)
    return {
        "seed": seed,
        "questions": [
            {"q": q["q"], "scale": q["scale"]}
            for q in items
        ],
        "axis_labels": quiz_logic.AXIS_LABEL,
        "time_options": geo.TIME_OPTIONS,
    }


@app.get("/api/geocode", response_model=schemas.GeocodeOut)
def geocode_address(address: str = Query(..., min_length=2)):
    """
    도로명주소/지번주소를 좌표로 바꾼다. 카카오 REST 키가 있어야 동작.
    브라우저에서 직접 부르면 키가 노출되므로 서버가 대신 호출한다.
    """
    import os

    from .import_neis import geocode as kakao_geocode

    kakao_key = os.getenv("KAKAO_REST_KEY", "").strip()
    if not kakao_key:
        raise HTTPException(
            status_code=503,
            detail="주소 검색이 아직 설정되지 않았습니다. 현재 위치 사용을 눌러주세요.",
        )
    coords = kakao_geocode(address.strip(), kakao_key)
    if not coords:
        raise HTTPException(status_code=404, detail="주소를 찾지 못했습니다. 더 자세히 입력해보세요.")
    return {"lat": coords[0], "lng": coords[1], "address": address.strip()}


@app.get("/api/geo-config")
def geo_config():
    """프론트가 주소 검색 가능 여부를 미리 알 수 있게 한다."""
    import os

    return {"address_search": bool(os.getenv("KAKAO_REST_KEY", "").strip())}


@app.post("/api/quiz/result", response_model=schemas.QuizResultOut)
def quiz_result(
    payload: schemas.QuizSubmit,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    # 1) 채점
    # 학생이 본 문항으로 매긴다. seed 가 없으면 예전 고정 문항으로 본다.
    scored = quiz_logic.score_answers(payload.answers, getattr(payload, "seed", None))
    scores = scored["axis_scores"]
    sub_scores = scored["sub_scores"]
    quality = scored["quality"]
    tops = quiz_logic.top_axes(scores)
    confidence = quiz_logic.score_confidence(scores, tops)

    # 참여 기록 (참여자 수 집계용). 실패해도 결과 제공은 계속한다.
    # 다만 조용히 넘기면 집계가 안 되는 이유를 알 수 없으므로 로그는 반드시 남긴다.
    try:
        db.add(
            QuizTaken(
                user_id=user.id if user else None,
                top_axis=(tops[0] if tops else "")[:30],
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"[진로테스트] 참여 기록 저장 실패: {exc!r}", flush=True)
    dept_groups = quiz_logic.recommended_departments(scores, limit=3)

    # 2) 통학 한도
    time_opt = geo.TIME_BY_KEY.get(payload.commute_time, geo.TIME_BY_KEY["any"])
    limit_km = time_opt["km"]

    has_location = payload.lat is not None and payload.lng is not None

    # 3) 추천 학과 키워드를 모아, 학과가 겹치는 학교를 찾는다.
    all_keywords = []
    for g in dept_groups:
        all_keywords.extend(g["keywords"])

    # 진로 테스트는 직업계고(특성화고·마이스터고)만 추천한다.
    # '일반고만 빼기'로 두면 자율고·과학고·외국어고까지 섞여 나온다.
    from .import_neis import VOCATIONAL_CATEGORIES
    candidates = (db.query(School)
                  .filter(School.category.in_(VOCATIONAL_CATEGORIES)).all())

    scored_schools = []
    for s in candidates:
        depts = [d.strip() for d in (s.departments or "").splitlines() if d.strip()]
        if not depts:
            continue
        matched = quiz_logic.department_matches(depts, all_keywords)
        if not matched:
            continue

        # 거리는 통학 시간 제한이 있을 때만 계산한다.
        # '거리 상관없음'(limit_km is None)이면 결과에 거리를 표시하지 않는다.
        if has_location and limit_km is not None:
            dist = geo.school_distance_km(payload.lat, payload.lng, s)
            # 통학권 밖 학교는 제외한다.
            if not geo.within_commute(payload.lat, payload.lng, s, limit_km):
                continue
        else:
            dist = None

        scored_schools.append(
            {
                "school": s,
                "matched": matched,
                "distance": dist,
                "plan_rank": PLAN_RANK.get(s.plan, 0),
            }
        )

    # 4) 정렬
    #    거리를 계산한 경우(위치 있음 + 통학시간 제한 있음): 가까운 순 -> 플랜
    #    그 외(위치 없음 또는 거리 상관없음): 플랜 높은 순 -> 학과 매칭 많은 순
    use_distance = has_location and limit_km is not None
    if use_distance:
        def sort_key(item):
            dist = item["distance"] if item["distance"] is not None else 99999
            return (dist, -item["plan_rank"], -len(item["matched"]))
    else:
        def sort_key(item):
            return (-item["plan_rank"], -len(item["matched"]), item["school"].name)

    scored_schools.sort(key=sort_key)
    top_schools = scored_schools[:12]

    # 이 학교들이 추천에 떴다는 것을 센다. 검색 노출과 따로 세야
    # '진로 테스트로는 자주 뜨는데 아무도 안 들어온다'가 드러난다.
    bump_exposure(db, [it["school"].id for it in top_schools], "quiz")

    # 어느 지역 학생이 어떤 계열을 원했는지. 수요와 공급을 견주는 데 쓴다.
    # 위치를 안 알려준 경우에는 지역을 알 수 없어 세지 않는다.
    if has_location:
        area = (payload.location_label or "").strip()
        # '경기도 양주시 고암동 …' 에서 시·군까지만 남긴다.
        # 동·번지까지 두면 조각이 잘게 나뉘어 셈이 의미를 잃는다.
        parts = [p for p in area.split() if p]
        region = " ".join(parts[:2]) if len(parts) >= 2 else (parts[0] if parts else "")
        bump_demand(db, region, tops)

    return {
        "scores": scores,
        "sub_scores": sub_scores,
        "top_axes": tops,
        "quality": quality,
        "confidence": confidence,
        "axis_labels": quiz_logic.AXIS_LABEL,
        "departments": [
            {
                "label": g["label"],
                "axis": g["axis"],
                "axis_label": quiz_logic.AXIS_LABEL[g["axis"]],
                "desc": g["desc"],
                "jobs": g["jobs"],
            }
            for g in dept_groups
        ],
        "schools": [
            {
                "id": it["school"].id,
                "name": it["school"].name,
                "region": it["school"].region,
                "address": it["school"].address,
                "category": it["school"].category,
                "coed": it["school"].coed.value,
                "dormitory": it["school"].dormitory,
                "plan": it["school"].plan.value,
                "matched_departments": it["matched"],
                "distance_km": round(it["distance"], 1) if it["distance"] is not None else None,
                "distance_approx": False,
            }
            for it in top_schools
        ],
        "location_label": payload.location_label or ("현재 위치" if has_location else "위치 미설정"),
        "has_location": has_location,
        "shows_distance": use_distance,
        "commute_label": time_opt["label"] if has_location else "전국",
        "matched_count": len(scored_schools),
    }


# ============================================================
# 기사 (특성화고신문)
# ============================================================
def _article_to_out(a: Article) -> dict:
    return {
        "id": a.id,
        "url": a.url,
        "title": a.title,
        "summary": a.summary or "",
        "thumbnail": a.thumbnail or "",
        "published_at": a.published_at,
        "school_id": a.school_id,
        "school_name": a.school.name if a.school else None,
        "school_plan": a.school.plan.value if a.school else None,
        "source": a.source,
    }


@app.get("/api/articles")
def list_articles(
    limit: int = Query(8, ge=1, le=30),
    db: Session = Depends(get_db),
):
    """메인 화면용 기사 목록.

    홍보 형평성을 위해:
    - 매번 무작위로 섞어 노출(새로고침하면 다른 학교 기사가 나온다).
    - 같은 학교 기사는 1건만(한 학교가 메인을 독점하지 않게).
    - 맨 앞 1칸은 유료 플랜(베이직 이상) 학교 중 무작위 1건.
    """
    import random

    picked_school_ids = set()
    used_ids = set()
    result = []

    # 1) 유료 플랜 학교 기사 중 무작위 1건을 맨 앞에
    paid_articles = (
        db.query(Article)
        .join(School, Article.school_id == School.id)
        .filter(
            School.plan.in_(plans_with_perk(db, "article_priority") or [Plan.platinum]),
            School.is_visible.is_(True),
            School.plan_paused.is_(False),
        )
        .all()
    )
    # 학교 중복 없는 풀
    paid_by_school = {}
    for a in paid_articles:
        paid_by_school.setdefault(a.school_id, []).append(a)
    if paid_by_school:
        sid = random.choice(list(paid_by_school.keys()))
        featured = random.choice(paid_by_school[sid])
        result.append(featured)
        picked_school_ids.add(featured.school_id)
        used_ids.add(featured.id)

    # 2) 나머지: 학교에 연결된 기사 전체를 무작위로 섞어 학교당 1건씩 채움
    #    (숨긴 학교의 기사는 제외)
    linked = (
        db.query(Article)
        .join(School, Article.school_id == School.id)
        .filter(School.is_visible.is_(True))
        .all()
    )
    random.shuffle(linked)
    for a in linked:
        if len(result) >= limit:
            break
        if a.school_id in picked_school_ids or a.id in used_ids:
            continue
        result.append(a)
        picked_school_ids.add(a.school_id)
        used_ids.add(a.id)

    # 3) 그래도 모자라면 학교 없는 기사로 채움(무작위)
    if len(result) < limit:
        unlinked = db.query(Article).filter(Article.school_id.is_(None)).all()
        random.shuffle(unlinked)
        for a in unlinked:
            if len(result) >= limit:
                break
            if a.id in used_ids:
                continue
            result.append(a)
            used_ids.add(a.id)

    return [_article_to_out(a) for a in result[:limit]]


@app.get("/api/schools/{school_id}/articles")
def school_articles(
    school_id: int,
    limit: int = Query(6, ge=1, le=20),
    db: Session = Depends(get_db),
):
    """특정 학교에 연결된 기사. 학교 상세페이지에서 쓴다."""
    rows = (
        db.query(Article)
        .filter(Article.school_id == school_id)
        .order_by(Article.published_at.desc().nullslast(), Article.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_article_to_out(a) for a in rows]


@app.get("/api/articles/search")
def search_articles(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """학교 이름 등으로 기사를 검색한다.
    학교명이 매칭되면 그 학교의 기사를, 아니면 제목에서 찾는다."""
    like = f"%{q.strip()}%"
    # 학교명으로 먼저 학교를 찾고, 그 학교 기사 + 제목 매칭을 합친다
    school_ids = [s.id for s in db.query(School).filter(School.name.ilike(like)).all()]
    query = db.query(Article).filter(
        or_(
            Article.school_id.in_(school_ids) if school_ids else False,
            Article.title.ilike(like),
        )
    )
    rows = (
        query.order_by(Article.published_at.desc().nullslast(), Article.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_article_to_out(a) for a in rows]


@app.post("/api/admin/articles/crawl")
def trigger_crawl(user: User = Depends(require_admin)):
    """관리자가 수동으로 기사 수집을 실행한다."""
    result = articles_mod.crawl()
    return result


@app.post("/api/admin/articles/rematch")
def trigger_rematch(user: User = Depends(require_admin)):
    """이미 저장된 기사를 개선된 매칭 로직으로 다시 학교와 연결한다."""
    return articles_mod.rematch_all()


@app.post("/api/admin/articles/dedupe")
def trigger_dedupe(user: User = Depends(require_admin)):
    """제목이 같은 중복 기사를 정리한다."""
    return articles_mod.dedupe()


@app.post("/api/admin/articles/manual", response_model=schemas.ArticleOut)
def add_manual_article(
    payload: schemas.ArticleManualCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """관리자가 기사를 직접 등록한다."""
    art = Article(
        url=payload.url.strip(),
        title=payload.title.strip(),
        summary=payload.summary.strip(),
        thumbnail=payload.thumbnail.strip(),
        school_id=payload.school_id,
        source="manual",
        source_no=articles_mod._extract_no(payload.url),
    )
    db.add(art)
    db.commit()
    db.refresh(art)
    return _article_to_out(art)


@app.delete("/api/admin/articles/{article_id}")
def delete_article(
    article_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    art = db.get(Article, article_id)
    if not art:
        raise HTTPException(status_code=404, detail="기사를 찾을 수 없습니다.")
    db.delete(art)
    db.commit()
    return {"ok": True}


# ============================================================
# 메인 화면용 공개 데이터
# ============================================================
@app.get("/api/home/ranking")
def home_ranking(
    period: str = Query("month", pattern="^(today|month|year)$"),
    limit: int = Query(10, ge=1, le=20),
    db: Session = Depends(get_db),
):
    """기간별 인기 학교 랭킹. 조회 로그(SchoolView)의 기간 합계로 정렬한다."""
    today = date.today()
    if period == "today":
        start = today
    elif period == "year":
        start = today.replace(month=1, day=1)
    else:  # month
        start = today.replace(day=1)

    view_sum = (
        db.query(
            SchoolView.school_id.label("sid"),
            func.sum(SchoolView.count).label("views"),
        )
        .filter(SchoolView.viewed_on >= start)
        .group_by(SchoolView.school_id)
        .subquery()
    )

    rows = (
        db.query(School, view_sum.c.views)
        .join(view_sum, School.id == view_sum.c.sid)
        .filter(School.is_visible.is_(True))  # 숨긴 학교는 랭킹에서 제외
        .order_by(view_sum.c.views.desc())
        .limit(limit)
        .all()
    )

    result = []
    for rank, (s, views) in enumerate(rows, start=1):
        result.append({
            "rank": rank,
            "id": s.id,
            "name": s.name,
            "region": s.region,
            "category": s.category,
            "plan": s.plan.value,
            "views": int(views or 0),
            "hero_image": (s.hero_image or "") if school_has_perk(db, s, "hero_image") else "",
        })
    return {"period": period, "items": result}


@app.get("/api/home/categories")
def home_categories(db: Session = Depends(get_db)):
    """계열별 학교 수. 메인의 '계열별 바로가기'에 쓴다. 숨긴 학교는 세지 않는다."""
    rows = (
        db.query(School.category, func.count(School.id))
        .filter(School.is_visible.is_(True))
        .group_by(School.category)
        .all()
    )
    counts = {cat: cnt for cat, cnt in rows}
    ordered = []
    for cat in CATEGORY_ORDER:
        if cat in counts and counts[cat] > 0:
            ordered.append({"category": cat, "count": counts[cat]})
    return ordered


@app.get("/api/events")
def list_all_events(
    region: Optional[str] = None,
    kind: Optional[str] = Query(None, pattern="^(admission|briefing)$"),
    scope: str = Query("upcoming", pattern="^(upcoming|all)$"),
    db: Session = Depends(get_db),
):
    """전체 학교의 학교 설명회·참가 행사를 모아 보여준다. 지역/종류/기간으로 필터링.
    노출(is_visible) 학교의 일정만 포함한다."""
    q = (
        db.query(AdmissionEvent, School)
        .join(School, AdmissionEvent.school_id == School.id)
        .filter(School.is_visible.is_(True))
    )
    if region:
        q = q.filter(School.region == region)
    if kind:
        q = q.filter(AdmissionEvent.kind == kind)
    if scope == "upcoming":
        # 종료일(없으면 시작일)이 오늘 이후인, 아직 안 지난 일정만
        today = date.today()
        q = q.filter(
            func.coalesce(AdmissionEvent.end_date, AdmissionEvent.start_date) >= today
        )
    rows = q.order_by(AdmissionEvent.start_date.asc()).all()
    return [
        {**_event_out(e), "school_id": s.id, "school_name": s.name,
         "region": s.region, "category": s.category}
        for e, s in rows
    ]


@app.get("/api/sigungu")
def get_sigungu(region: str = Query(...), db: Session = Depends(get_db)):
    """특정 시/도에 속한 시/군/구 목록.

    '수원시 장안구'처럼 구가 있는 큰 시는 시와 구를 나눠서 돌려준다.
    그래야 '수원시 전체'를 한 번에 고를 수 있다.

      [{"city": "수원시", "districts": ["권선구", "영통구", ...]},
       {"city": "과천시", "districts": []}]

    **검색과 같은 기준으로 센다.** 예전에는 숨긴 학교의 주소까지 훑어서
    목록을 만들었다. 그래서 그 시/군/구가 목록에는 뜨는데 고르면 결과가
    0건이었다 — 고를 수 있는데 아무것도 안 나오면 검색이 고장 난 걸로 읽힌다.
    """
    rows = db.query(School.address).filter(
        School.region == region, School.is_visible.is_(True)).all()
    cities: dict = {}
    for (addr,) in rows:
        sg = extract_sigungu(addr or "")
        if not sg:
            continue
        parts = sg.split()
        city = parts[0]
        cities.setdefault(city, set())
        if len(parts) > 1:
            cities[city].add(parts[1])
    return [
        {"city": city, "districts": sorted(districts)}
        for city, districts in sorted(cities.items())
    ]


# ============================================================
# 관리자: 플랜 가격 · 학교 노출 · 플랜 정지
# ============================================================
@app.get("/api/admin/plan-prices")
def admin_get_plan_prices(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """현재 플랜 가격과 혜택 문구(관리자 설정 반영)."""
    return [
        {
            "plan": p.value,
            "label": PLAN_META[p]["label"],
            "price_per_month": get_plan_price(db, p),
            "price_per_year": get_plan_price_year(db, p),
            "perk_keys": get_plan_perk_keys(db, p),
            "perks": get_plan_perks(db, p),
        }
        for p in [Plan.free, Plan.basic, Plan.premium, Plan.platinum]
    ]


@app.get("/api/admin/perk-catalog")
def admin_perk_catalog(user: User = Depends(require_admin)):
    """토글 가능한 유료 혜택 목록과, 항상 제공되는 기본 기능 목록."""
    return {
        "perks": [{"key": k, "label": v} for k, v in PERK_CATALOG],
        "base_features": [{"key": k, "label": v} for k, v in BASE_FEATURES],
    }


@app.patch("/api/admin/plan-perks/{plan}")
def admin_set_plan_perks(
    plan: Plan,
    payload: schemas.PlanPerksIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """플랜에서 켤 혜택 항목을 저장한다. 관리자만 가능하다."""
    if payload.reset:  # 기본값으로 되돌리기
        row = db.query(Setting).filter(Setting.key == f"plan_perks_{plan.value}").first()
        if row:
            db.delete(row)
            db.commit()
    else:
        set_plan_perk_keys(db, plan, payload.keys)
    return {
        "plan": plan.value,
        "perk_keys": get_plan_perk_keys(db, plan),
        "perks": get_plan_perks(db, plan),
    }


@app.patch("/api/admin/plan-prices/{plan}")
def admin_set_plan_price(
    plan: Plan,
    price: int = Query(..., ge=0),
    per: str = Query("month"),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """플랜 가격을 설정한다. per=month 는 월 가격, per=year 는 1년치."""
    if per not in ("month", "year"):
        raise HTTPException(status_code=400, detail="per 는 month 또는 year 입니다.")
    set_plan_price(db, plan, price, per)
    return {"plan": plan.value,
            "price_per_month": get_plan_price(db, plan),
            "price_per_year": get_plan_price_year(db, plan)}


@app.patch("/api/admin/schools/{school_id}/visibility")
def admin_toggle_school_visibility(
    school_id: int,
    visible: bool = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """학교를 사용자에게 보이거나 숨긴다(개별)."""
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")
    school.is_visible = visible
    db.commit()
    return {"id": school_id, "is_visible": visible}


@app.get("/api/admin/dept-field-filter")
def admin_get_dept_filter(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    tagged = db.query(School).filter(School.dept_fields != "").count()
    total = db.query(School).count()
    return {
        "enabled": dept_filter_enabled(db),
        "tagged": tagged,      # 계열이 매겨진 학교 수
        "total": total,
        "fields": available_dept_fields(db),
    }


@app.patch("/api/admin/dept-field-filter")
def admin_set_dept_filter(
    request: Request,
    enabled: bool = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    row = db.query(Setting).filter(Setting.key == DEPT_FILTER_KEY).first()
    if row:
        row.value = "1" if enabled else "0"
    else:
        db.add(Setting(key=DEPT_FILTER_KEY, value="1" if enabled else "0"))
    db.commit()
    write_audit(db, request, user, action="setting.dept_field_filter",
                detail="켜짐" if enabled else "꺼짐")
    return {"ok": True, "enabled": enabled}


@app.post("/api/admin/dept-field-filter/rebuild")
def admin_rebuild_dept_fields(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """학과 목록을 다시 훑어 계열을 매긴다. 분류 규칙을 고쳤을 때 쓴다."""
    changed = 0
    for school in db.query(School).all():
        before = school.dept_fields or ""
        refresh_dept_fields(school)
        if (school.dept_fields or "") != before:
            changed += 1
    db.commit()
    return {"ok": True, "changed": changed, "fields": available_dept_fields(db)}


# ---------- 무상 플랜 지급 ----------
GRANT_MAX_MONTHS = 12


@app.get("/api/admin/schools/{school_id}/plan-status")
def school_plan_status(
    school_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """지급 전에 이 학교가 지금 어떤 상태인지 알려준다.

    결제로 쓰는 중인지, 무상 체험 중인지에 따라 줄 수 있는 플랜이 달라진다.
    """
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")

    today = date.today()
    has_time_left = bool(school.plan_expires_at and school.plan_expires_at > today
                         and school.plan != Plan.free)
    is_paid = has_time_left and not school.plan_is_free_trial
    days_left = (school.plan_expires_at - today).days if has_time_left else 0

    return {
        "school_id": school.id,
        "school_name": school.name,
        "plan": school.plan.value,
        "plan_label": PLAN_META[school.plan]["label"],
        "plan_rank": PLAN_RANK[school.plan],
        "expires_at": school.plan_expires_at,
        "days_left": days_left,
        "is_paid": is_paid,              # 결제해서 이용 중
        "is_free_trial": bool(school.plan_is_free_trial),
        # 결제 고객에게는 상위 플랜을 줄 수 없다(남은 기간이 사라지므로).
        "max_rank": PLAN_RANK[school.plan] if is_paid else PLAN_RANK[Plan.platinum],
        "note": school.plan_granted_note or "",
    }


@app.post("/api/admin/schools/{school_id}/grant-plan")
def grant_plan(
    school_id: int,
    request: Request,
    plan: Plan = Query(..., description="줄 플랜"),
    months: int = Query(1, ge=1, le=GRANT_MAX_MONTHS),
    reason: str = Query("", max_length=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """관리자가 학교에 플랜을 무상으로 준다.

    이미 기간이 남아 있으면 그 뒤에 이어 붙인다. 결제해서 쓰고 있는 학교에
    체험을 주면서 남은 기간을 깎으면 안 되기 때문이다.
    """
    if plan == Plan.free:
        raise HTTPException(status_code=400, detail="무료 플랜은 지급 대상이 아닙니다.")
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")

    today = date.today()
    has_time_left = bool(school.plan_expires_at and school.plan_expires_at > today
                         and school.plan != Plan.free)
    is_paid = has_time_left and not school.plan_is_free_trial

    # 결제해서 쓰는 학교에 상위 플랜을 주면, 남아 있던 기간이 사라져 손해를 끼친다.
    # 그런 경우는 아예 막고 만료 후에 주도록 안내한다.
    if is_paid and PLAN_RANK[plan] > PLAN_RANK[school.plan]:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{school.name}은(는) {PLAN_META[school.plan]['label']} 플랜을 "
                f"{school.plan_expires_at}까지 결제해 이용 중입니다. "
                "상위 플랜을 지금 지급하면 남은 기간이 사라집니다. "
                "같은 등급 이하로 기간만 연장하거나, 만료 후에 지급해주세요."
            ),
        )

    # 같거나 낮은 등급이면 기간만 이어 붙인다(등급은 내리지 않는다).
    base = school.plan_expires_at if (
        has_time_left and PLAN_RANK[school.plan] >= PLAN_RANK[plan]
    ) else today
    expires = base + timedelta(days=30 * months)

    school.plan = plan if PLAN_RANK[plan] >= PLAN_RANK[school.plan] else school.plan
    school.plan_expires_at = expires
    school.plan_paused = False
    # 결제분 위에 같은 등급을 얹은 경우는 무상 표시를 하지 않는다.
    # 그래야 만료 안내가 "무료 체험이 끝났다" 로 잘못 나가지 않는다.
    school.plan_is_free_trial = True if not is_paid else school.plan_is_free_trial
    school.plan_granted_note = (reason or "관리자 지급")[:200]

    db.add(PlanGrant(
        school_id=school.id, school_name=school.name[:120],
        plan=plan, months=months, starts_on=today, expires_on=expires,
        reason=(reason or "")[:200],
        granted_by=user.id, granted_by_email=user.email[:120],
    ))
    db.commit()

    write_audit(db, request, user, action="plan.grant",
                target_type="school", target_id=school.id,
                detail=f"{school.name} · {PLAN_META[plan]['label']} {months}개월 · {reason}")
    return {
        "ok": True, "school": school.name, "plan": school.plan.value,
        "expires_at": school.plan_expires_at,
    }


@app.post("/api/admin/schools/{school_id}/revoke-plan")
def revoke_plan(
    school_id: int,
    request: Request,
    reason: str = Query("", max_length=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """무상으로 준 플랜을 거둬들인다. 결제한 플랜은 건드리지 않는다."""
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")
    if not school.plan_is_free_trial:
        raise HTTPException(
            status_code=400,
            detail="결제로 이용 중인 플랜은 여기서 회수할 수 없습니다.",
        )

    school.plan = Plan.free
    school.plan_expires_at = None
    school.plan_is_free_trial = False
    school.plan_granted_note = ""

    latest = (
        db.query(PlanGrant)
        .filter(PlanGrant.school_id == school.id, PlanGrant.revoked_at.is_(None))
        .order_by(PlanGrant.id.desc())
        .first()
    )
    if latest:
        latest.revoked_at = datetime.utcnow()
    db.commit()

    write_audit(db, request, user, action="plan.revoke",
                target_type="school", target_id=school.id,
                detail=f"{school.name} · {reason}")
    return {"ok": True}


@app.get("/api/admin/plan-grants")
def list_plan_grants(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """무상 지급 이력. 지금 체험 중인 학교를 한눈에 본다."""
    today = date.today()
    rows = (
        db.query(PlanGrant)
        .order_by(PlanGrant.created_at.desc())
        .limit(limit)
        .all()
    )
    return [{
        "id": g.id,
        "school_id": g.school_id,
        "school_name": g.school_name,
        "plan": g.plan.value,
        "plan_label": PLAN_META[g.plan]["label"],
        "months": g.months,
        "starts_on": g.starts_on,
        "expires_on": g.expires_on,
        "reason": g.reason,
        "granted_by": g.granted_by_email,
        "revoked_at": g.revoked_at,
        "active": bool(not g.revoked_at and g.expires_on >= today),
        "created_at": g.created_at,
    } for g in rows]


@app.get("/api/admin/plan-expiry")
def list_plan_expiry(
    days: int = Query(0, ge=0, le=400,
                      description="0 이면 전부, 30 이면 30일 안쪽만"),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """유료 플랜이 걸린 학교를 **만료가 가까운 순서로** 준다.

    학교 하나를 검색해 눌러야 만료일이 보이면, 정작 알아야 할 "이번 달에
    끝나는 곳이 어디인가"를 알 수 없다. 끝나는 순서로 늘어놓아야 그게 보인다.

    **끝난 학교는 따로 담아 준다**(expired). expire_plans() 가 무료로
    되돌리면서 plan_expired_at 에 흔적을 남기므로, 연장을 놓친 곳을 나중에도
    찾아낼 수 있다. 돌고 있는 것과 섞으면 "지금 챙길 곳"이 흐려져서 나눈다.
    """
    rows = (
        db.query(School)
        .filter(School.plan != Plan.free, School.plan_expires_at.isnot(None))
        .order_by(School.plan_expires_at.asc())
        .all()
    )
    out = []
    for s_ in rows:
        left = plan_days_left(s_)
        if left is None:
            continue
        if days and left > days:
            continue
        out.append({
            "school_id": s_.id,
            "school_name": s_.name,
            "region": s_.region or "",
            "plan": s_.plan.value,
            "plan_label": PLAN_META[s_.plan]["label"],
            "expires_at": s_.plan_expires_at,
            "days_left": left,
            "paused": bool(s_.plan_paused),
        })
    # 이미 끝난 곳. 최근에 끝난 순서로 준다 — 오래된 것부터 보여줄 이유가 없다.
    today = date.today()
    gone = (
        db.query(School)
        .filter(School.plan == Plan.free, School.plan_expired_at.isnot(None))
        .order_by(School.plan_expired_at.desc())
        .limit(200)
        .all()
    )
    expired = [{
        "school_id": g.id,
        "school_name": g.name,
        "region": g.region or "",
        "plan": g.plan_expired_from or "",
        "plan_label": PLAN_META.get(
            next((p for p in Plan if p.value == (g.plan_expired_from or "")), Plan.free),
            {}).get("label", g.plan_expired_from or "—"),
        "expired_at": g.plan_expired_at,
        "days_ago": (today - g.plan_expired_at).days,
    } for g in gone]

    return {"items": out,
            "expiring_30": sum(1 for x in out if 0 <= x["days_left"] <= 30),
            "expired": expired,
            "expired_count": len(expired)}


@app.get("/api/admin/category-visibility")
def admin_category_visibility(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """계열별 학교 수와 노출 상태. 관리자 토글 스위치에 쓴다.
    한 계열 안에 노출/숨김이 섞여 있으면 visible=False로 본다(전부 노출일 때만 켜짐)."""
    rows = (
        db.query(
            School.category,
            func.count(School.id).label("total"),
            func.sum(case((School.is_visible.is_(True), 1), else_=0)).label("shown"),
        )
        .group_by(School.category)
        .all()
    )
    by_cat = {cat: (int(total), int(shown or 0)) for cat, total, shown in rows}

    # 정해둔 순서를 먼저 쓰되, 순서 목록에 없는 계열(NEIS에서 새 이름이 들어온 경우)도
    # 반드시 뒤에 붙인다. 목록에 없다는 이유로 토글에서 통째로 빠지면 안 된다.
    ordered = [c for c in CATEGORY_ORDER if c in by_cat]
    ordered += sorted(set(by_cat) - set(ordered))

    result = []
    for cat in ordered:
        total, shown = by_cat[cat]
        result.append({
            "category": cat,
            "count": total,
            "shown": shown,        # 노출 중인 학교 수
            "hidden": total - shown,  # 숨긴 학교 수
            "visible": shown == total,  # 전부 노출이면 켜짐
        })
    return result


@app.patch("/api/admin/schools-visibility-by-category")
def admin_toggle_category_visibility(
    category: str = Query(...),
    visible: bool = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """계열별로 학교 노출을 한 번에 켜고 끈다."""
    updated = (
        db.query(School)
        .filter(School.category == category)
        .update({School.is_visible: visible}, synchronize_session=False)
    )
    db.commit()
    return {"category": category, "is_visible": visible, "updated": updated}


@app.patch("/api/admin/schools/{school_id}/plan-pause")
def admin_pause_plan(
    school_id: int,
    paused: bool = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """승인된 학교의 플랜을 일시정지하거나 해제한다(플랜 등급은 유지)."""
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")
    school.plan_paused = paused
    db.commit()
    return {"id": school_id, "plan_paused": paused, "plan": school.plan.value}


# ══════════════════════════════════════════════════════════
# 개인 구독 (자기소개서 기능)
# 학교 연계 일지·제출은 무료다. 학교와 무관한 개인 자기소개서만 구독 대상.
# ══════════════════════════════════════════════════════════
SUBSCRIPTION_PRICE_KEY = "subscription_price"
SUBSCRIPTION_DEFAULT_PRICE = 5900       # 월 이용료(원)
SUBSCRIPTION_DUE_DAYS = 3               # 입금 기한


def subscription_price(db: Session) -> int:
    row = db.query(Setting).filter(Setting.key == SUBSCRIPTION_PRICE_KEY).first()
    if row and str(row.value).isdigit():
        return int(row.value)
    return SUBSCRIPTION_DEFAULT_PRICE


def make_sub_deposit_code(db: Session) -> str:
    """구독 입금자명에 넣을 고유 코드. 학교 플랜 코드와 구분되게 접두어를 다르게 한다."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    for _ in range(30):
        code = "SUB-" + "".join(random.choices(alphabet, k=4))
        if not db.query(SubscriptionOrder).filter(SubscriptionOrder.deposit_code == code).first():
            return code
    return "SUB-" + secrets.token_hex(3).upper()


def get_subscription(db: Session, user: User) -> Optional[Subscription]:
    return db.query(Subscription).filter(Subscription.user_id == user.id).first()


def subscription_active(db: Session, user: User) -> bool:
    sub = get_subscription(db, user)
    return bool(sub and sub.expires_at > datetime.utcnow())


def require_subscription(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> User:
    """자기소개서 기능 접근 조건. 구독이 없으면 402로 알려 결제를 안내한다."""
    if user.role == Role.admin:
        return user
    if not subscription_active(db, user):
        raise HTTPException(
            status_code=402,
            detail="자기소개서 기능은 구독 후 이용할 수 있습니다.",
        )
    return user


def my_subscription(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sub = get_subscription(db, user)
    pending = (
        db.query(SubscriptionOrder)
        .filter(
            SubscriptionOrder.user_id == user.id,
            SubscriptionOrder.status.in_([OrderStatus.pending, OrderStatus.paid]),
        )
        .order_by(SubscriptionOrder.created_at.desc())
        .first()
    )
    return {
        "active": subscription_active(db, user),
        "expires_at": sub.expires_at if sub else None,
        "price_per_month": subscription_price(db),
        "pending_order": None if not pending else {
            "id": pending.id,
            "months": pending.months,
            "amount": pending.amount,
            "status": pending.status.value,
            "status_label": ORDER_STATUS_LABEL.get(pending.status.value, ""),
            "deposit_code": pending.deposit_code,
            "due_at": pending.due_at,
        },
    }


def create_subscription_order(
    payload: schemas.SubscriptionOrderIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """구독 주문을 만든다. 결제창에 넘길 주문번호와 금액을 돌려준다.

    금액은 반드시 서버에서 정한다. 클라이언트가 보낸 금액을 믿으면
    조작해서 싸게 결제할 수 있다.
    """
    exists = (
        db.query(SubscriptionOrder)
        .filter(
            SubscriptionOrder.user_id == user.id,
            SubscriptionOrder.status.in_([OrderStatus.pending, OrderStatus.paid]),
        )
        .first()
    )
    if exists and exists.created_at > datetime.utcnow() - timedelta(hours=1):
        # 결제창을 닫았다가 다시 여는 경우가 있어 1시간 안이면 기존 주문을 재사용한다.
        return _subscription_order_out(db, exists)

    # 미성년자는 법정대리인 동의 없이 결제할 수 없다(민법 제5조).
    age = korean_age(user.birth_date) if user.birth_date else None
    if age is not None and age < ADULT_AGE:
        if not payload.minor_consent or not (payload.guardian_contact or "").strip():
            raise HTTPException(
                status_code=400,
                detail="만 19세 미만은 법정대리인(보호자) 동의와 연락처가 필요합니다.",
            )

    months = payload.months
    price = subscription_price(db)
    order = SubscriptionOrder(
        user_id=user.id,
        user_email=user.email[:120],
        months=months,
        amount=price * months,
        order_uid=f"SUB{datetime.utcnow():%y%m%d}{secrets.token_hex(6).upper()}",
        deposit_code=make_sub_deposit_code(db),
        due_at=datetime.utcnow() + timedelta(days=SUBSCRIPTION_DUE_DAYS),
        minor_consent=bool(payload.minor_consent),
        guardian_contact=(payload.guardian_contact or "").strip()[:120],
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return _subscription_order_out(db, order)


def _subscription_order_out(db: Session, order: SubscriptionOrder) -> dict:
    return {
        "id": order.id,
        "order_uid": order.order_uid,
        "order_name": f"자기소개서 이용권 {order.months}개월",
        "months": order.months,
        "amount": order.amount,
        "status": order.status.value,
        "client_key": toss.client_key(),
        "test_mode": toss.is_test_mode(),
        "customer_email": order.user_email,
        # 카드 결제가 설정되지 않았을 때만 무통장 안내를 함께 준다.
        "bank": None if toss.is_ready() else get_bank_info(db),
        "deposit_code": None if toss.is_ready() else order.deposit_code,
        "due_at": order.due_at,
    }


def confirm_subscription_payment(
    payload: schemas.PaymentConfirmIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """토스 결제창에서 성공한 결제를 서버에서 최종 승인한다."""
    order = (
        db.query(SubscriptionOrder)
        .filter(SubscriptionOrder.order_uid == payload.order_id)
        .first()
    )
    if not order or order.user_id != user.id:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다.")
    if order.status == OrderStatus.approved:
        return {"ok": True, "already": True}

    # 금액 위변조 확인 — 서버가 저장한 값과 다르면 즉시 중단한다.
    if int(payload.amount) != int(order.amount):
        print(f"[결제] 금액 불일치 order={order.id} 저장 {order.amount} / 요청 {payload.amount}", flush=True)
        raise HTTPException(status_code=400, detail="결제 금액이 올바르지 않습니다.")

    ok, data, err = toss.confirm(payload.payment_key, payload.order_id, order.amount)
    if not ok:
        order.note = err[:200]
        db.commit()
        raise HTTPException(status_code=400, detail=f"결제 승인에 실패했습니다. {err}")

    now = datetime.utcnow()
    order.status = OrderStatus.approved
    order.payment_key = payload.payment_key[:200]
    order.pay_method = (data.get("method") or "")[:30]
    order.receipt_url = ((data.get("receipt") or {}).get("url") or "")[:300]
    order.paid_at = now
    order.handled_at = now

    # 구독 적용. 남은 기간이 있으면 이어서 연장한다.
    sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    base = sub.expires_at if (sub and sub.expires_at > now) else now
    new_expires = base + timedelta(days=30 * order.months)
    if sub:
        sub.expires_at = new_expires
    else:
        db.add(Subscription(user_id=user.id, started_at=now, expires_at=new_expires))
    db.commit()

    write_audit(db, request, user, action="subscription.pay",
                target_type="subscription_order", target_id=order.id,
                detail=f"{order.amount}원 {order.months}개월")
    return {"ok": True, "expires_at": new_expires, "receipt_url": order.receipt_url}


def refund_subscription(
    order_id: int,
    request: Request,
    reason: str = Query("고객 요청", max_length=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """본인이 직접 환불을 요청한다.

    전자상거래법상 청약철회 기간(7일) 안이고 아직 이용하지 않았다면 전액 환불한다.
    그 밖의 경우는 관리자가 개별 판단하도록 신청만 남긴다.
    """
    order = db.get(SubscriptionOrder, order_id)
    if not order or order.user_id != user.id:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다.")
    if order.status != OrderStatus.approved or not order.payment_key:
        raise HTTPException(status_code=400, detail="환불할 수 있는 결제가 아닙니다.")
    if order.refunded_at:
        raise HTTPException(status_code=400, detail="이미 환불된 결제입니다.")

    within_7days = order.paid_at and (datetime.utcnow() - order.paid_at) <= timedelta(days=7)
    used = db.query(CoverLetter).filter(CoverLetter.user_id == user.id).count() > 0
    if not (within_7days and not used):
        raise HTTPException(
            status_code=400,
            detail="자동 환불 대상이 아닙니다. 고객센터로 문의해주세요.",
        )

    ok, _data, err = toss.cancel(order.payment_key, reason)
    if not ok:
        raise HTTPException(status_code=400, detail=f"환불에 실패했습니다. {err}")

    order.refunded_at = datetime.utcnow()
    order.status = OrderStatus.rejected
    order.note = f"환불: {reason}"[:200]
    sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    if sub:
        # 결제분만큼 되돌린다.
        sub.expires_at = sub.expires_at - timedelta(days=30 * order.months)
    db.commit()
    write_audit(db, request, user, action="subscription.refund",
                target_type="subscription_order", target_id=order.id, detail=reason)
    return {"ok": True}


def my_subscription_orders(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = (
        db.query(SubscriptionOrder)
        .filter(SubscriptionOrder.user_id == user.id)
        .order_by(SubscriptionOrder.created_at.desc())
        .limit(30)
        .all()
    )
    return [{
        "id": o.id, "months": o.months, "amount": o.amount,
        "status": o.status.value,
        "status_label": ORDER_STATUS_LABEL.get(o.status.value, ""),
        "deposit_code": o.deposit_code,
        "created_at": o.created_at, "due_at": o.due_at, "paid_at": o.paid_at,
    } for o in rows]


def cancel_subscription_order(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = db.get(SubscriptionOrder, order_id)
    if not order or order.user_id != user.id:
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다.")
    if order.status != OrderStatus.pending:
        raise HTTPException(status_code=400, detail="이미 처리된 신청은 취소할 수 없습니다.")
    order.status = OrderStatus.rejected
    order.handled_at = datetime.utcnow()
    order.note = "이용자 취소"
    db.commit()
    return {"ok": True}


def admin_subscription_orders(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    q = db.query(SubscriptionOrder)
    if status:
        q = q.filter(SubscriptionOrder.status == status)
    rows = q.order_by(SubscriptionOrder.created_at.desc()).limit(200).all()
    return [{
        "id": o.id, "user_email": o.user_email, "months": o.months, "amount": o.amount,
        "status": o.status.value,
        "status_label": ORDER_STATUS_LABEL.get(o.status.value, ""),
        "deposit_code": o.deposit_code,
        "created_at": o.created_at, "due_at": o.due_at, "paid_at": o.paid_at,
    } for o in rows]


def approve_subscription_order(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """입금 확인 후 승인. 남은 기간이 있으면 이어서 연장한다."""
    order = db.get(SubscriptionOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다.")
    if order.status == OrderStatus.approved:
        raise HTTPException(status_code=400, detail="이미 승인된 신청입니다.")

    now = datetime.utcnow()
    sub = db.query(Subscription).filter(Subscription.user_id == order.user_id).first()
    base = sub.expires_at if (sub and sub.expires_at > now) else now
    new_expires = base + timedelta(days=30 * order.months)
    if sub:
        sub.expires_at = new_expires
    else:
        db.add(Subscription(user_id=order.user_id, started_at=now, expires_at=new_expires))

    order.status = OrderStatus.approved
    order.paid_at = order.paid_at or now
    order.handled_at = now
    db.commit()

    write_audit(db, request, user, action="subscription.approve",
                target_type="subscription_order", target_id=order.id,
                detail=f"{order.user_email} {order.months}개월")
    return {"ok": True, "expires_at": new_expires}


def reject_subscription_order(
    order_id: int,
    request: Request,
    reason: str = Query("", max_length=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    order = db.get(SubscriptionOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다.")
    order.status = OrderStatus.rejected
    order.handled_at = datetime.utcnow()
    order.note = reason[:200]
    db.commit()
    write_audit(db, request, user, action="subscription.reject",
                target_type="subscription_order", target_id=order.id, detail=reason)
    return {"ok": True}


@app.get("/api/me/school-profile")
def get_my_school_profile(
    db: Session = Depends(get_db),
    user: User = Depends(require_student),
):
    """내 계정 화면에 쓰는 정보.

    과목 자료가 없는 학교도 있으므로, 학과 목록은 학교에 등록된 학과에서도
    가져온다. 그래야 어디서든 학과를 고를 수 있다.
    """
    v = (
        db.query(SchoolVerification)
        .filter(SchoolVerification.user_id == user.id)
        .order_by(SchoolVerification.id.desc())
        .first()
    )
    school = db.get(School, v.school_id) if v else None

    subject_rows = (
        db.query(SchoolSubject).filter(SchoolSubject.school_id == school.id).all()
        if school else []
    )
    from_subjects = sorted({r.department for r in subject_rows if r.department})
    from_school = [
        d.strip() for d in ((school.departments or "").splitlines() if school else []) if d.strip()
    ]
    # 과목 자료의 학과명이 더 정확하지만, 없으면 학교 학과 목록을 쓴다.
    departments = from_subjects or from_school
    if user.department and user.department not in departments:
        departments = [user.department] + departments

    return {
        "name": user.name,
        "email": user.email,
        "school_name": school.name if school else "",
        "verified": bool(v and v.status == "approved"),
        "verify_status": v.status if v else "",
        "department": user.department or "",
        "grade": user.grade,
        "departments": departments,
        "grades": sorted({r.grade for r in subject_rows if r.grade}) or [1, 2, 3],
        "subject_count": len({r.name for r in subject_rows}),
    }


@app.put("/api/me/school-profile")
def set_my_school_profile(
    department: Optional[str] = Query(None, max_length=60),
    grade: Optional[int] = Query(None, ge=1, le=3),
    db: Session = Depends(get_db),
    user: User = Depends(require_student),
):
    """내 학과·학년을 저장한다. 과목 목록을 내 것에 맞게 좁히는 데 쓴다."""
    if department is not None:
        user.department = department.strip()[:60]
    if grade is not None:
        user.grade = grade
    db.commit()
    return {"ok": True, "department": user.department, "grade": user.grade}


def run_spellcheck(payload: schemas.SpellCheckIn):
    """자주 틀리는 맞춤법을 찾아준다.

    로그인 없이도 쓸 수 있게 열어두되, 본문을 저장하지 않는다.
    자동 교정은 하지 않는다. 무엇을 왜 고칠지 보여주고 선택은 학생이 한다.
    """
    if payload.fields:
        return {"results": spellcheck.check_many(payload.fields),
                "rule_count": spellcheck.rule_count()}
    return {"results": {"text": spellcheck.check(payload.text or "")},
            "rule_count": spellcheck.rule_count()}


# ==================== 선생님 계정 (학교가 발급) ====================
# 선생님 계정 검색·권한부여·해제는 기록해 화면으로 옮겼다(2026-09 이동).
# 계정 원본은 여기(UDJ)뿐이라 실제 처리는 여전히 여기서 하지만, 기록해
# 서버가 partner.py 의 /api/partner/schools/{id}/teachers* 를 통해
# 대신 호출한다 — 아래 5개 엔드포인트와 정확히 같은 로직이 partner.py 에 있다.


# ==================== 선생님 워크스페이스 ====================
def teacher_school(db: Session, user: User) -> School:
    s = db.get(School, user.school_id) if user.school_id else None
    if not s:
        raise HTTPException(status_code=400, detail="소속 학교가 연결되지 않은 계정입니다.")
    return s


@app.get("/api/teacher/me")
def teacher_me(db: Session = Depends(get_db), user: User = Depends(require_teacher)):
    s = teacher_school(db, user)
    return {
        "name": user.name,
        "email": user.email,
        "class_name": user.class_name or "",
        "school_id": s.id,
        "school_name": s.name,
        "must_change_password": bool(user.must_change_password),
    }


@app.post("/api/teacher/change-password")
def teacher_change_password(
    payload: schemas.ChangePasswordIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="현재 비밀번호가 일치하지 않습니다.")
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="새 비밀번호는 8자 이상이어야 합니다.")
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    db.commit()
    return {"ok": True}


@app.get("/api/teacher/students/search")
def teacher_search_students(
    q: str = Query(..., min_length=2),
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher),
):
    """아이디(이메일)·이름·연락처로 학생 계정을 찾는다."""
    s = teacher_school(db, user)
    term = q.strip()
    rows = (
        db.query(User)
        .filter(
            User.role == Role.student,
            User.is_active.is_(True),
            # 다른 학교에 이미 소속된 학생은 검색 대상에서 뺀다 — 우리 학교와
            # 무관한 학생의 이름·연락처가 다른 학교 선생님에게 새면 안 된다.
            User.school_id.in_([None, s.id]),
            or_(
                User.email.ilike(f"%{term}%"),
                User.name.ilike(f"%{term}%"),
                User.phone.ilike(f"%{term}%"),
            ),
        )
        .limit(20)
        .all()
    )
    # 이미 우리 학교에 등록된 학생인지 표시
    reg = {
        v.user_id: v
        for v in db.query(SchoolVerification)
        .filter(SchoolVerification.school_id == s.id)
        .all()
    }
    out = []
    for u in rows:
        v = reg.get(u.id)
        out.append(
            {
                "id": u.id,
                "email": u.email,
                "name": u.name,
                "phone": u.phone or "",
                "registered": bool(v and v.status == "approved"),
                "class_name": v.class_name if v else "",
            }
        )
    return out


@app.get("/api/teacher/students")
def teacher_my_students(
    scope: str = Query("mine", pattern="^(mine|all)$"),
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher),
):
    """인증된 학생 목록. scope=mine이면 내 학급, all이면 우리 학교 전체."""
    s = teacher_school(db, user)
    q = db.query(SchoolVerification).filter(
        SchoolVerification.school_id == s.id,
        SchoolVerification.status == "approved",
    )
    if scope == "mine":
        q = q.filter(SchoolVerification.teacher_id == user.id)
    rows = q.all()
    return [
        {
            "verification_id": v.id,
            "user_id": v.user_id,
            "name": v.user.name if v.user else "",
            "email": v.user.email if v.user else "",
            "phone": (v.user.phone or "") if v.user else "",
            "class_name": v.class_name or "",
            "teacher_name": v.teacher.name if v.teacher else "",
            "is_mine": v.teacher_id == user.id,
            "registered_at": v.decided_at or v.created_at,
        }
        for v in rows
    ]


# ── 학급 이관 ──────────────────────────────────────────────
#
# 학년이 올라가면 학생이 다른 반으로 옮겨가고 담당 선생님도 바뀐다.
# 선생님이 자기 반 목록에서 학생을 골라 새 학급으로 넘기면, 그 학급을
# 맡은 선생님 계정으로 담당이 함께 옮겨간다.
#
# 담당 선생님은 따로 고르지 않는다. 선생님 계정에 적힌 담당 학급
# (예: "2학년 3반")으로 찾는다. 사람이 짝을 맞추다 틀리는 일을 줄이려는
# 것이고, 학급과 담당이 어긋나는 상태 자체를 만들지 않기 위해서다.


def _class_options(db: Session, school_id: int) -> List[dict]:
    """옮겨갈 수 있는 학급 목록.

    선생님 계정에 적힌 담당 학급을 모은다. 담당이 없는 반으로는 보낼 수
    없는데, 그러면 그 학생의 일지를 아무도 못 보게 되기 때문이다.
    """
    rows = (db.query(User)
            .filter(User.school_id == school_id, User.role == Role.teacher,
                    User.is_active.is_(True))
            .order_by(User.class_name, User.name).all())
    out, seen = [], set()
    for t in rows:
        name = (t.class_name or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append({"class_name": name, "teacher_id": t.id, "teacher_name": t.name})
    return out


@app.get("/api/teacher/class-options")
def teacher_class_options(db: Session = Depends(get_db),
                          user: User = Depends(require_class_manager)):
    """학급 드롭다운에 넣을 목록."""
    s = teacher_school(db, user)
    opts = _class_options(db, s.id)
    return {
        "options": opts,
        # 담당 학급이 비어 있는 선생님이 있으면 드롭다운에 안 나온다.
        # 왜 안 보이는지 화면이 설명할 수 있게 함께 알려준다.
        "teachers_without_class": [
            {"id": t.id, "name": t.name}
            for t in db.query(User).filter(
                User.school_id == s.id, User.role == Role.teacher,
                User.is_active.is_(True),
                or_(User.class_name.is_(None), User.class_name == "")).all()
        ],
    }


@app.post("/api/teacher/students/move")
def teacher_move_students(payload: dict, request: Request,
                          db: Session = Depends(get_db),
                          user: User = Depends(require_class_manager)):
    """고른 학생들을 다른 학급으로 옮긴다.

    한 명만 골라도 되고 여럿을 한 번에 골라도 된다. 옮기면 담당 선생님도
    그 학급을 맡은 계정으로 함께 바뀐다.

    선생님 계정은 자기가 맡은 학생만 옮길 수 있다. 학교 계정은 전교생을
    옮길 수 있는데, 학년 전체가 한꺼번에 바뀌는 진급 때 필요하다.
    """
    s = teacher_school(db, user)
    ids = payload.get("user_ids") or []
    target = str(payload.get("class_name") or "").strip()

    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="옮길 학생을 골라주세요.")
    if not target:
        raise HTTPException(status_code=400, detail="옮겨갈 학급을 골라주세요.")

    opt = next((o for o in _class_options(db, s.id) if o["class_name"] == target), None)
    if opt is None:
        raise HTTPException(
            status_code=400,
            detail="담당 선생님이 지정된 학급이 아닙니다. 먼저 그 반의 선생님 계정에 담당 학급을 적어주세요.",
        )

    try:
        ids = [int(i) for i in ids]
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="형식이 올바르지 않습니다.")

    q = db.query(SchoolVerification).filter(
        SchoolVerification.school_id == s.id,
        SchoolVerification.status == "approved",
        SchoolVerification.user_id.in_(ids),
    )
    # 선생님은 자기 학생만. 학교 계정은 전체.
    if user.role == Role.teacher:
        q = q.filter(SchoolVerification.teacher_id == user.id)
    rows = q.all()

    moved, names = 0, []
    for v in rows:
        if v.class_name == target and v.teacher_id == opt["teacher_id"]:
            continue  # 이미 그 반이면 건드리지 않는다
        v.class_name = target
        v.teacher_id = opt["teacher_id"]
        moved += 1
        if v.user:
            names.append(v.user.name)
    db.commit()

    missed = len(ids) - len(rows)
    write_audit(db, request, user, action="teacher.students_move",
                target_type="school", target_id=s.id,
                detail=f"{moved}명 → {target} ({opt['teacher_name']})")
    return {
        "ok": True, "moved": moved, "skipped": missed,
        "class_name": target, "teacher_name": opt["teacher_name"],
        "message": (
            f"{moved}명을 {target}({opt['teacher_name']} 선생님)으로 옮겼습니다."
            if moved else "옮길 학생이 없습니다. 이미 그 학급인지 확인해주세요."
        ) + (f" {missed}명은 담당이 아니라 건너뛰었습니다." if missed else ""),
    }


# ---- 재학생 인증 신청 처리 (선생님) ----
@app.get("/api/teacher/verifications")
def teacher_verifications(
    db: Session = Depends(get_db), user: User = Depends(require_teacher)
):
    """학생이 직접 낸 재학생 인증 신청 목록(대기/처리 내역)."""
    s = teacher_school(db, user)
    rows = (
        db.query(SchoolVerification)
        .filter(SchoolVerification.school_id == s.id)
        .order_by(SchoolVerification.created_at.desc())
        .all()
    )
    return [
        {
            "id": v.id,
            "status": v.status,
            "note": v.note or "",
            "class_name": v.class_name or "",
            "user_id": v.user_id,
            "user_name": v.user.name if v.user else "",
            "user_email": v.user.email if v.user else "",
            "created_at": v.created_at,
        }
        for v in rows
    ]


@app.post("/api/teacher/verifications/{verification_id}/approve")
def teacher_approve_verification(
    verification_id: int,
    payload: schemas.VerifyApprove,
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher),
):
    """신청 승인. 승인하면 그 학생이 우리 학교 재학생(내 학급 명단)으로 잡힌다."""
    s = teacher_school(db, user)
    v = db.get(SchoolVerification, verification_id)
    if not v or v.school_id != s.id:
        raise HTTPException(status_code=404, detail="인증 신청을 찾을 수 없습니다.")
    v.status = "approved"
    v.class_name = (payload.class_name or user.class_name or "").strip()[:40]
    v.teacher_id = user.id
    v.decided_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@app.post("/api/teacher/verifications/{verification_id}/reject")
def teacher_reject_verification(
    verification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher),
):
    s = teacher_school(db, user)
    v = db.get(SchoolVerification, verification_id)
    if not v or v.school_id != s.id:
        raise HTTPException(status_code=404, detail="인증 신청을 찾을 수 없습니다.")
    v.status = "rejected"
    v.teacher_id = user.id
    v.decided_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@app.post("/api/teacher/students")
def teacher_register_student(
    payload: schemas.TeacherRegisterStudent,
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher),
):
    """학생을 우리 학교·내 학급 인원으로 등록한다."""
    s = teacher_school(db, user)
    student = db.get(User, payload.user_id)
    if not student or student.role != Role.student:
        raise HTTPException(status_code=404, detail="학생 계정을 찾을 수 없습니다.")
    class_name = (payload.class_name or user.class_name or "").strip()[:40]

    v = (
        db.query(SchoolVerification)
        .filter(
            SchoolVerification.user_id == student.id,
            SchoolVerification.school_id == s.id,
        )
        .first()
    )
    if v:
        v.status = "approved"
        v.class_name = class_name
        v.teacher_id = user.id
        v.decided_at = datetime.utcnow()
    else:
        db.add(
            SchoolVerification(
                user_id=student.id,
                school_id=s.id,
                status="approved",
                class_name=class_name,
                teacher_id=user.id,
                decided_at=datetime.utcnow(),
            )
        )
    db.commit()
    return {"ok": True}


@app.delete("/api/teacher/students/{user_id}")
def teacher_unregister_student(
    user_id: int, db: Session = Depends(get_db), user: User = Depends(require_teacher)
):
    """재학생 인증 해제. 해제하면 그 학생은 내 학급 명단에서 빠진다."""
    s = teacher_school(db, user)
    v = (
        db.query(SchoolVerification)
        .filter(
            SchoolVerification.user_id == user_id,
            SchoolVerification.school_id == s.id,
        )
        .first()
    )
    if not v:
        raise HTTPException(status_code=404, detail="등록 정보를 찾을 수 없습니다.")
    db.delete(v)
    db.commit()
    return {"ok": True}


# ============================================================
# 공지 · 알림
# ============================================================
def _notice_out(n: Notice, read: bool = False) -> dict:
    return {
        "id": n.id,
        "scope": n.scope,
        "school_id": n.school_id,
        "school_name": n.school.name if n.school else "",
        "title": n.title,
        "body": n.body or "",
        "image_url": n.image_url or "",
        "is_popup": bool(n.is_popup),
        "is_important": bool(n.is_important),
        "author_name": n.author.name if n.author else "",
        "starts_at": n.starts_at,
        "ends_at": n.ends_at,
        "created_at": n.created_at,
        "is_read": read,
    }


def _visible_notices(db: Session, user: Optional[User]):
    """이 사용자에게 보여야 할 공지를 기간 조건까지 반영해 고른다."""
    now = datetime.utcnow()
    q = db.query(Notice).filter(
        or_(Notice.starts_at.is_(None), Notice.starts_at <= now),
        or_(Notice.ends_at.is_(None), Notice.ends_at >= now),
    )

    conds = [Notice.scope == "all"]   # 전체 공지는 누구에게나
    if user is not None:
        if user.role == Role.school and user.school_id:
            # 학교 계정: 우리 학교 대상 공지
            conds.append(
                and_(Notice.scope == "school", Notice.school_id == user.school_id)
            )
        if user.role == Role.teacher and user.school_id:
            # 선생님: 학교 대상 공지 + 학교가 선생님들에게 보낸 공지
            conds.append(
                and_(
                    Notice.scope.in_(["school", "teachers"]),
                    Notice.school_id == user.school_id,
                )
            )
    return q.filter(or_(*conds)).order_by(Notice.created_at.desc())


@app.get("/api/notices")
def list_my_notices(
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """내게 보이는 공지 목록과 안 읽은 개수."""
    rows = _visible_notices(db, user).limit(50).all()
    read_ids = set()
    if user is not None and rows:
        read_ids = {
            r.notice_id
            for r in db.query(NoticeRead)
            .filter(
                NoticeRead.user_id == user.id,
                NoticeRead.notice_id.in_([n.id for n in rows]),
            )
            .all()
        }
    items = [_notice_out(n, n.id in read_ids) for n in rows]
    return {
        "items": items,
        "unread": sum(1 for i in items if not i["is_read"]),
        # 팝업 대상 공지 전체. 실제로 띄울지는 브라우저가
        # '오늘은 그만 보기' 기록을 보고 판단한다(읽음 여부와 무관).
        "popups": [i for i in items if i["is_popup"]],
    }


@app.post("/api/notices/{notice_id}/read")
def mark_notice_read(
    notice_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not db.get(Notice, notice_id):
        raise HTTPException(status_code=404, detail="공지를 찾을 수 없습니다.")
    exists = (
        db.query(NoticeRead)
        .filter(NoticeRead.notice_id == notice_id, NoticeRead.user_id == user.id)
        .first()
    )
    if not exists:
        db.add(NoticeRead(notice_id=notice_id, user_id=user.id))
        db.commit()
    return {"ok": True}


def _create_notice(db, user, payload, scope: str, school_id=None) -> dict:
    n = Notice(
        author_id=user.id,
        scope=scope,
        school_id=school_id,
        title=payload.title.strip()[:150],
        body=(payload.body or "").strip(),
        image_url=(payload.image_url or "").strip()[:300],
        is_popup=bool(payload.is_popup) and scope == "all",
        is_important=bool(payload.is_important),
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    return _notice_out(n)


ALLOWED_IMAGE_TYPES = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg",
    "image/gif": ".gif", "image/webp": ".webp",
}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def _save_uploaded_image(file: UploadFile, prefix: str = "notice") -> str:
    """이미지를 저장하고 접근 URL을 돌려준다."""
    ext = ALLOWED_IMAGE_TYPES.get((file.content_type or "").lower())
    if not ext:
        raise HTTPException(status_code=400, detail="PNG·JPG·GIF·WEBP 이미지만 올릴 수 있습니다.")
    data = file.file.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="이미지는 5MB 이하만 올릴 수 있습니다.")
    if not data:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    name = f"{prefix}_{datetime.utcnow().strftime('%Y%m%d')}_{secrets.token_hex(6)}{ext}"
    with open(os.path.join(UPLOAD_DIR, name), "wb") as f:
        f.write(data)
    return f"/api/uploads/{name}"


@app.post("/api/admin/notices/image")
def admin_upload_notice_image(
    file: UploadFile = File(...), user: User = Depends(require_admin)
):
    return {"url": _save_uploaded_image(file, prefix="notice")}




@app.post("/api/school-admin/hero-image")
def school_upload_hero_image(
    file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(require_school)
):
    """학교 대표 이미지를 업로드한다. hero_image는 BASE_FEATURES(모든 플랜 공통
    기본 기능)라 플랜과 무관하게 항상 업로드·노출된다."""
    s = my_school(db, user)
    return {"url": _save_uploaded_image(file, prefix=f"hero_{s.id}")}


# ---------- 관리자: 전체 공지 / 특정 학교 공지 ----------
@app.get("/api/admin/notices")
def admin_list_notices(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    rows = db.query(Notice).order_by(Notice.created_at.desc()).limit(200).all()
    return [_notice_out(n) for n in rows]


@app.post("/api/admin/notices")
def admin_create_notice(
    payload: schemas.NoticeIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """scope=all 이면 전체 공지, scope=school 이면 특정 학교 공지."""
    if payload.scope not in ("all", "school"):
        raise HTTPException(status_code=400, detail="scope는 all 또는 school 이어야 합니다.")
    school_id = None
    if payload.scope == "school":
        if not payload.school_id or not db.get(School, payload.school_id):
            raise HTTPException(status_code=400, detail="대상 학교를 선택해주세요.")
        school_id = payload.school_id
    return _create_notice(db, user, payload, payload.scope, school_id)


@app.delete("/api/admin/notices/{notice_id}")
def admin_delete_notice(
    notice_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)
):
    n = db.get(Notice, notice_id)
    if not n:
        raise HTTPException(status_code=404, detail="공지를 찾을 수 없습니다.")
    db.query(NoticeRead).filter(NoticeRead.notice_id == notice_id).delete()
    db.delete(n)
    db.commit()
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"status": "ok"}


# 검색엔진(구글/네이버)용 사이트맵. 노출(is_visible) 학교 상세 페이지를 모두 포함한다.
# nginx가 https://도메인/sitemap.xml 요청을 이 엔드포인트로 프록시한다.
@app.get("/api/sitemap.xml", include_in_schema=False)
def sitemap_xml(request: Request, db: Session = Depends(get_db)):
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "https"
    host = request.headers.get("host") or request.url.netloc
    base = f"{proto}://{host}"
    today = date.today().isoformat()

    # 크롤링을 허용할 공개 정적 페이지
    static_pages = [
        ("/", "1.0", "daily"),
        ("/search", "0.9", "daily"),
        ("/events", "0.7", "daily"),
        ("/quiz", "0.6", "monthly"),
        ("/privacy", "0.2", "yearly"),
        ("/terms", "0.2", "yearly"),
        ("/refund", "0.2", "yearly"),
    ]

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for path, prio, freq in static_pages:
        parts.append(
            f"<url><loc>{base}{path}</loc><lastmod>{today}</lastmod>"
            f"<changefreq>{freq}</changefreq><priority>{prio}</priority></url>"
        )

    # 노출 상태인 학교 상세 페이지 전부
    rows = (
        db.query(School.id, School.created_at)
        .filter(School.is_visible.is_(True))
        .all()
    )
    for sid, created in rows:
        lastmod = (created.date().isoformat() if created else today)
        parts.append(
            f"<url><loc>{base}/schools/{sid}</loc><lastmod>{lastmod}</lastmod>"
            f"<changefreq>weekly</changefreq><priority>0.8</priority></url>"
        )

    parts.append("</urlset>")
    xml = "\n".join(parts)
    return Response(content=xml, media_type="application/xml")


# ============================================================
# 기사 자동 수집 스케줄러
# ============================================================
# 몇 시간마다 백그라운드로 특성화고신문 기사를 수집한다.
# 크롤링이 실패해도(예: 서버에서 sinmoon.net 접근 차단) 서비스에는 영향 없다.
# 끄려면 환경변수 ARTICLE_CRAWL_HOURS=0 으로 둔다.
import threading
import time as _time

_CRAWL_HOURS = float(os.getenv("ARTICLE_CRAWL_HOURS", "6"))


def _crawl_loop():
    # 서버 부팅 직후 잠깐 기다렸다 첫 수집 (DB·네트워크 준비 시간)
    _time.sleep(60)
    while True:
        try:
            articles_mod.crawl()
        except Exception:
            pass  # 어떤 경우에도 루프가 죽지 않게
        _time.sleep(_CRAWL_HOURS * 3600)


if _CRAWL_HOURS > 0:
    _t = threading.Thread(target=_crawl_loop, daemon=True)
    _t.start()
