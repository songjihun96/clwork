"""유료 서비스 신청 접수.

컨설팅·상담·영상처럼 **사람이 응대해야 하는 신청**을 한 곳에 모은다.
폼마다 테이블을 따로 파지 않는다 — 물어보는 항목이 거의 같고(경로·이름·
연락처·요청사항), 관리자가 볼 때도 한 화면에서 처리하는 편이 낫다.
폼마다 다른 항목은 extra_json 에 담는다.

**결제는 붙이지 않는다.** 신청을 받고 계좌번호를 안내한 뒤, 입금 확인은
사람이 한다(관리자 화면에서 '입금 확인'으로 넘긴다). PG 를 붙이면 가맹점
심사·정산·환불 처리가 따라오는데, 지금 필요한 건 신청을 놓치지 않는 것뿐이다.

**신청자에게 로그인을 요구하지 않는다.** 중학생과 학부모가 대상이라
가입부터 시키면 대부분 거기서 나간다. 대신 스팸을 막을 최소한의 제한을 둔다.
"""

from __future__ import annotations

import csv
import io
import json
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import (APIRouter, BackgroundTasks, Depends, HTTPException, Query,
                     Request)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .auth import get_current_user_optional, require_admin
from .database import get_db
from .models import Role, ServiceApplication, Setting, User

router = APIRouter(prefix="/api", tags=["applications"])

# 무엇을 신청했는지. 값은 DB 에 그대로 들어가므로 함부로 바꾸지 않는다.
KINDS = {
    "plan_consulting": {"label": "직업계고 3년Plan 컨설팅", "amount": 300000},
    "graduate_video": {"label": "합격생 영상", "amount": 100000},
    "counseling": {"label": "직업계고 상담", "amount": 100000},
    "briefing_survey": {"label": "온라인 설명회 시청 신청", "amount": 0},
    "briefing_review": {"label": "온라인 설명회 후기", "amount": 0},
    # 학교·기관이 남기는 교육/컨설팅 문의. 금액은 이야기해 봐야 정해진다.
    "education_inquiry": {"label": "교육·컨설팅 문의", "amount": 0},
    # 합격생 영상을 다 보고 남기는 후기. 산 사람만 남길 수 있어서 로그인이
    # 필요하고, 계정당 한 번이다(아래 LOGIN_REQUIRED 가 둘 다 처리한다).
    "graduate_video_review": {"label": "합격생 영상 후기", "amount": 0},
}

# 문의 폼의 지역 드롭다운. 학교 검색과 같은 순서를 쓴다.
REGIONS = ("서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
           "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주")

STATUSES = ("received", "paid", "done", "cancelled")
STATUS_LABEL = {
    "received": "접수", "paid": "입금 확인", "done": "완료", "cancelled": "취소",
}

FOUND_PATHS = ("소개", "검색", "기타")

# 로그인해야 신청할 수 있는 종류.
#
# 다른 폼은 일부러 로그인을 안 받는다(중학생·학부모가 대상이라 가입부터
# 시키면 대부분 거기서 나간다). 하지만 이 영상은 **산 사람에게 열어 줘야**
# 하는 물건이라, 열어 줄 상대를 알아야 한다. 계정 없이 받으면 입금을
# 확인해 놓고도 누구에게 보여줘야 할지 모른다.
LOGIN_REQUIRED = {"graduate_video", "graduate_video_review"}

# 입금이 확인된 뒤로는 영상을 볼 수 있다. 취소는 당연히 빠지고, '접수'도
# 아직이다 — 돈이 들어왔는지 사람이 확인한 다음이라야 한다.
OWNED_STATUSES = ("paid", "done")

# 설정 키
NOTIFY_KEY = "application_notify_email"
BANK_KEY = "application_bank_info"
DEFAULT_BANK = "기업은행 439-011129-01-016 (예금주: 강승구)"

# ---- 스팸 제한 --------------------------------------------------------
# 로그인 없이 받는 창구라 최소한의 방어가 필요하다. 외부 라이브러리 없이
# 메모리로 IP 별 최근 제출 시각만 센다(단일 서버 기준, 로그인 제한과 같은 방식).
_RECENT: dict[str, list[float]] = {}
MAX_PER_HOUR = 5
WINDOW_SEC = 3600


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate(ip: str) -> None:
    now = time.time()
    recent = [t for t in _RECENT.get(ip, []) if now - t < WINDOW_SEC]
    _RECENT[ip] = recent
    if len(recent) >= MAX_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail="신청이 너무 잦습니다. 잠시 후 다시 시도해 주세요.")


def _record(ip: str) -> None:
    _RECENT.setdefault(ip, []).append(time.time())


# ---- 설정 -------------------------------------------------------------
def _get(db: Session, key: str, default: str = "") -> str:
    row = db.get(Setting, key)
    return (row.value if row and row.value is not None else "") or default


def _set(db: Session, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value


# ---- 모양 -------------------------------------------------------------
class ApplicationIn(BaseModel):
    kind: str
    name: str = Field(min_length=1, max_length=40)
    phone: str = Field(min_length=1, max_length=30)
    email: str = Field(default="", max_length=120)
    found_path: str = Field(default="", max_length=20)
    found_etc: str = Field(default="", max_length=100)
    applicant: str = Field(default="", max_length=20)
    message: str = Field(default="", max_length=2000)
    extra: dict = Field(default_factory=dict)


class ApplicationPatch(BaseModel):
    status: Optional[str] = None
    admin_note: Optional[str] = None


def _utc(dt):
    """저장된 naive UTC 시각에 시간대를 붙여 준다."""
    return dt.replace(tzinfo=timezone.utc).isoformat() if dt else None


def app_out(a: ServiceApplication, db: Optional[Session] = None) -> dict:
    try:
        extra = json.loads(a.extra_json or "{}")
    except ValueError:
        extra = {}
    return {
        "id": a.id, "kind": a.kind,
        "kind_label": KINDS.get(a.kind, {}).get("label", a.kind),
        "name": a.name, "phone": a.phone, "email": a.email or "",
        "found_path": a.found_path or "", "found_etc": a.found_etc or "",
        "applicant": a.applicant or "", "message": a.message or "",
        "extra": extra, "amount": a.amount or 0,
        # 어느 계정에 열어 주는 신청인지. 로그인해서 사는 것(합격생 영상)만
        # 값이 있다. 관리자가 입금을 확인할 때 **누구에게 열리는지** 보이지
        # 않으면, 동명이인이나 대신 신청한 경우에 엉뚱한 계정이 열린다.
        "user_id": a.user_id,
        "account": _account_of(db, a.user_id) if db is not None else None,
        "status": a.status, "status_label": STATUS_LABEL.get(a.status, a.status),
        "admin_note": a.admin_note or "",
        # 시간대를 못 박아 내보낸다. 저장은 UTC 인데 표시가 없으면 브라우저가
        # 제 지역 시간으로 읽어 9시간이 어긋난다(13:43 이 04:43 으로 보였다).
        "created_at": _utc(a.created_at),
    }


def _account_of(db: Session, user_id) -> Optional[dict]:
    if not user_id:
        return None
    u = db.get(User, user_id)
    if not u:
        # 탈퇴했는데 신청은 남은 경우. 지워졌다고 알려 줘야 관리자가 헛되이
        # 입금 확인으로 넘기지 않는다.
        return {"id": user_id, "name": "", "email": "", "gone": True}
    return {"id": u.id, "name": u.name or "", "email": u.email or "", "gone": False}


# ---- 알림 -------------------------------------------------------------
def notify_new_application(to_addr: str, summary: str, body: str) -> None:
    """새 신청이 들어왔다고 메일로 알린다. 뒤에서 돈다 —
    SMTP 가 느리거나 막혀 있을 때 신청한 사람을 기다리게 두면 안 된다."""
    from . import mailer
    cfg = mailer.system_config()
    if not cfg.is_ready():
        return
    try:
        mailer.send_email(cfg, to_addr, f"[신청] {summary}", body,
                          from_name="우리동네 직업계고")
    except Exception as exc:                       # 알림 실패가 접수를 망치지 않는다
        print(f"[신청알림] 실패: {exc}", flush=True)


def _mail_body(a: ServiceApplication) -> str:
    lines = [
        f"신청 종류 : {KINDS.get(a.kind, {}).get('label', a.kind)}",
        f"이름      : {a.name}",
        f"연락처    : {a.phone}",
        f"이메일    : {a.email or '-'}",
        f"신청자    : {a.applicant or '-'}",
        f"알게 된 경로: {a.found_path or '-'}"
        + (f" ({a.found_etc})" if a.found_etc else ""),
        f"금액      : {(a.amount or 0):,}원",
        "",
        "문의 및 요청사항",
        (a.message or "-"),
    ]
    return "\n".join(lines)


# ---- 접수 -------------------------------------------------------------
@router.get("/applications/regions")
def application_regions():
    """문의 폼의 지역 목록. 화면에 목록을 박아 두면 두 곳이 어긋난다."""
    return {"regions": list(REGIONS)}


@router.get("/applications/info")
def application_info(kind: str = Query(...), db: Session = Depends(get_db)):
    """폼 화면이 쓰는 값 — 금액과 계좌 안내. 화면에 숫자를 박아 두지 않는다."""
    if kind not in KINDS:
        raise HTTPException(status_code=404, detail="없는 신청 종류입니다.")
    return {
        "kind": kind, "label": KINDS[kind]["label"],
        "amount": KINDS[kind]["amount"],
        "bank": _get(db, BANK_KEY, DEFAULT_BANK),
        "login_required": kind in LOGIN_REQUIRED,
    }


@router.post("/applications")
def create_application(payload: ApplicationIn, request: Request,
                       background: BackgroundTasks,
                       db: Session = Depends(get_db),
                       user: Optional[User] = Depends(get_current_user_optional)):
    if payload.kind not in KINDS:
        raise HTTPException(status_code=400, detail="없는 신청 종류입니다.")
    if payload.found_path and payload.found_path not in FOUND_PATHS:
        raise HTTPException(status_code=400, detail="알게 된 경로를 다시 선택해 주세요.")
    if payload.kind in LOGIN_REQUIRED and user is None:
        raise HTTPException(
            status_code=401,
            detail="이 영상은 로그인한 계정으로만 신청할 수 있습니다. "
                   "입금이 확인되면 그 계정에서 바로 보실 수 있습니다.")

    # 같은 계정이 같은 것을 두 번 신청하지 못하게 한다.
    #
    # 로그인해서 사는 물건은 계정 하나에 하나면 충분한데, 막지 않으면 화면이
    # 느려 두 번 누른 사람에게 입금 안내가 두 번 나가고 관리자 목록에도 두
    # 줄이 생긴다. 입금 대조는 사람이 눈으로 하는 일이라 그게 그대로 사고다.
    if payload.kind in LOGIN_REQUIRED and user is not None:
        dup = db.query(ServiceApplication).filter(
            ServiceApplication.user_id == user.id,
            ServiceApplication.kind == payload.kind,
            ServiceApplication.status != "cancelled").first()
        if dup is not None:
            if payload.kind.endswith("_review"):
                msg = "이미 후기를 남기셨습니다. 고맙습니다."
            elif dup.status == "received":
                msg = "이미 신청하셨습니다."
            else:
                msg = "이미 결제가 확인된 계정입니다. 바로 시청하실 수 있습니다."
            raise HTTPException(status_code=409, detail=msg)

    ip = _client_ip(request)
    _check_rate(ip)

    a = ServiceApplication(
        kind=payload.kind, name=payload.name.strip(), phone=payload.phone.strip(),
        email=payload.email.strip(), found_path=payload.found_path,
        found_etc=payload.found_etc.strip(), applicant=payload.applicant,
        message=payload.message.strip(),
        extra_json=json.dumps(payload.extra, ensure_ascii=False),
        amount=KINDS[payload.kind]["amount"], status="received",
        user_id=user.id if user else None,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    _record(ip)

    to_addr = _get(db, NOTIFY_KEY).strip()
    if to_addr:
        background.add_task(
            notify_new_application, to_addr,
            f"{KINDS[payload.kind]['label']} · {a.name}", _mail_body(a))

    return {
        "ok": True, "id": a.id, "amount": a.amount,
        "bank": _get(db, BANK_KEY, DEFAULT_BANK),
        "message": "신청이 접수되었습니다.",
    }


def owns(db: Session, user: Optional[User], kind: str) -> bool:
    """이 사람이 이 종류를 사서 볼 수 있는가.

    관리자는 늘 볼 수 있다 — 무엇을 파는지 확인해야 하는 사람이라, 매번
    자기 계정으로 사게 만들 수는 없다.
    """
    if user is None:
        return False
    if user.role == Role.admin:
        return True
    return db.query(ServiceApplication).filter(
        ServiceApplication.user_id == user.id,
        ServiceApplication.kind == kind,
        ServiceApplication.status.in_(OWNED_STATUSES)).first() is not None


def my_application(db: Session, user: Optional[User], kind: str):
    """이 사람이 낸 신청 중 가장 최근 것(상태 무관). 화면이 '입금 확인 중'
    인지 '아직 신청 안 함'인지 구분하는 데 쓴다."""
    if user is None:
        return None
    return (db.query(ServiceApplication)
            .filter(ServiceApplication.user_id == user.id,
                    ServiceApplication.kind == kind)
            .order_by(ServiceApplication.created_at.desc())
            .first())


# ---- 관리 -------------------------------------------------------------
@router.get("/admin/applications")
def list_applications(kind: Optional[str] = Query(None),
                      status: Optional[str] = Query(None),
                      db: Session = Depends(get_db),
                      user: User = Depends(require_admin)):
    q = db.query(ServiceApplication)
    if kind:
        q = q.filter(ServiceApplication.kind == kind)
    if status:
        q = q.filter(ServiceApplication.status == status)
    rows = q.order_by(ServiceApplication.created_at.desc()).limit(500).all()
    counts = {}
    for k in KINDS:
        counts[k] = db.query(ServiceApplication).filter(
            ServiceApplication.kind == k).count()
    return {
        "items": [app_out(a, db) for a in rows],
        "counts": counts,
        "kinds": [{"key": k, "label": v["label"], "amount": v["amount"]}
                  for k, v in KINDS.items()],
        "statuses": [{"key": s, "label": STATUS_LABEL[s]} for s in STATUSES],
    }


@router.patch("/admin/applications/{app_id}")
def update_application(app_id: int, payload: ApplicationPatch,
                       db: Session = Depends(get_db),
                       user: User = Depends(require_admin)):
    a = db.get(ServiceApplication, app_id)
    if not a:
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다.")
    data = payload.model_dump(exclude_unset=True)
    if "status" in data:
        if data["status"] not in STATUSES:
            raise HTTPException(status_code=400, detail="없는 상태입니다.")
        a.status = data["status"]
    if "admin_note" in data:
        a.admin_note = (data["admin_note"] or "")[:1000]
    db.commit()
    db.refresh(a)
    return app_out(a, db)


@router.delete("/admin/applications/{app_id}")
def delete_application(app_id: int, db: Session = Depends(get_db),
                       user: User = Depends(require_admin)):
    a = db.get(ServiceApplication, app_id)
    if not a:
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다.")
    db.delete(a)
    db.commit()
    return {"ok": True}


@router.get("/admin/applications.csv")
def export_applications(kind: Optional[str] = Query(None),
                        db: Session = Depends(get_db),
                        user: User = Depends(require_admin)):
    """엑셀로 내려받는다. BOM 을 붙여야 엑셀이 한글을 안 깬다."""
    q = db.query(ServiceApplication)
    if kind:
        q = q.filter(ServiceApplication.kind == kind)
    rows = q.order_by(ServiceApplication.created_at.desc()).all()

    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf)
    # '열리는 계정'은 화면에도 나오는 값이라 파일에도 같이 넣는다. 두 곳이
    # 다르면 어느 쪽을 믿어야 할지 모르게 된다.
    w.writerow(["신청일", "종류", "상태", "이름", "연락처", "이메일",
                "신청자", "알게 된 경로", "금액", "요청사항", "메모",
                "열리는 계정", "추가 항목"])
    for a in rows:
        acc = _account_of(db, a.user_id)
        try:
            extra = json.loads(a.extra_json or "{}")
        except ValueError:
            extra = {}
        w.writerow([
            a.created_at.strftime("%Y-%m-%d %H:%M") if a.created_at else "",
            KINDS.get(a.kind, {}).get("label", a.kind),
            STATUS_LABEL.get(a.status, a.status),
            a.name, a.phone, a.email or "", a.applicant or "",
            (a.found_path or "") + (f"({a.found_etc})" if a.found_etc else ""),
            a.amount or 0, (a.message or "").replace("\n", " "),
            (a.admin_note or "").replace("\n", " "),
            "" if not acc else ("탈퇴한 계정" if acc["gone"]
                                else f"{acc['name']}({acc['email']})"),
            " / ".join(f"{k}: {v}" for k, v in extra.items()),
        ])
    buf.seek(0)
    today = datetime.utcnow().strftime("%Y%m%d")
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="applications_{today}.csv"'})


@router.get("/admin/application-settings")
def get_settings(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return {"notify_email": _get(db, NOTIFY_KEY),
            "bank": _get(db, BANK_KEY, DEFAULT_BANK)}


class SettingsIn(BaseModel):
    notify_email: str = Field(default="", max_length=120)
    bank: str = Field(default="", max_length=200)


@router.put("/admin/application-settings")
def put_settings(payload: SettingsIn, db: Session = Depends(get_db),
                 user: User = Depends(require_admin)):
    _set(db, NOTIFY_KEY, payload.notify_email.strip())
    _set(db, BANK_KEY, payload.bank.strip() or DEFAULT_BANK)
    db.commit()
    return get_settings(db, user)
