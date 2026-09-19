"""업무 시스템 (workwoori.ggm.kr) — 계정·할 일·요청사항·출근.

**무엇인가.** 관리자가 직원에게 할 일을 내리고, 협업기업이 요청사항을 올리고,
누가 출근했는지 보는 사내 도구다. 같은 서버에 얹혀 있지만 우리동네 직업계고·
기록해와는 **계정도 토큰도 완전히 따로**다.

**왜 계정을 따로 두나.** 기존 `users` 표는 학생·학교·선생님의 것이다. 거기에
협업기업 직원을 섞으면, 권한 검사 한 줄만 빠뜨려도 남의 회사 사람이 학생
개인정보가 있는 화면에 닿는다. 표를 나누면 그 사고가 **구조적으로 불가능**해진다.
토큰도 따로 서명해서(`WORK_SECRET_KEY`), 한쪽 토큰으로 다른 쪽을 못 연다.

**출근은 버튼이 아니라 접속으로 본다.** 로그인한 사람이 이 API 를 부르면
그날 첫 시각이 출근으로 남는다. 누르는 수고가 없고 "체크를 깜빡했다"가 안
생기는 대신, **퇴근 시각은 알 수 없다** — 마지막 활동 시각이 그 근사치이고,
화면에도 그렇게 적는다. 실제보다 정확한 척하지 않기 위해서다.

**권한 세 가지**
  - `admin`   관리자 — 전부 본다. 계정을 만들고 할 일을 배분한다.
  - `staff`   직원 — 자기 할 일만 본다. 상태와 메모를 바꾼다.
  - `partner` 협업기업 — 자기 회사 요청만 본다. 새 요청을 올린다.
"""

from __future__ import annotations

import os
import re
import secrets
import time
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from .database import get_db
from .models import (
    WorkAttendance,
    WorkOrg,
    WorkRequest,
    WorkTask,
    WorkUser,
)

router = APIRouter(prefix="/api/work", tags=["work"])

# ─────────────────────────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────────────────────────

# 업무 시스템 전용 서명키. 다른 서비스의 토큰과 절대 섞이면 안 되므로 따로 둔다.
# 값이 없으면 기동할 때마다 새로 만들어져서, 재시작하면 전원 로그아웃된다.
# 운영에서는 .env 에 반드시 넣는다.
SECRET_KEY = (os.getenv("WORK_SECRET_KEY", "") or "").strip() or secrets.token_urlsafe(48)
ALGORITHM = "HS256"
TOKEN_HOURS = int(os.getenv("WORK_TOKEN_HOURS", "12"))

# 이 시각을 넘겨 첫 접속하면 지각으로 본다. "09:00" 형식.
WORK_START = os.getenv("WORK_START_TIME", "09:00")

KST = timedelta(hours=9)

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)

ROLES = ("admin", "staff", "partner")
TASK_STATUS = ("todo", "doing", "done", "hold")
REQ_STATUS = ("new", "reading", "answered", "closed")


def now_kst() -> datetime:
    return datetime.utcnow() + KST


def today_kst() -> date:
    return now_kst().date()


# ─────────────────────────────────────────────────────────────────────────────
# 로그인과 관문
# ─────────────────────────────────────────────────────────────────────────────

def make_token(user: WorkUser) -> str:
    return jwt.encode(
        {
            "sub": str(user.id),
            "role": user.role,
            # 업무 시스템 토큰임을 못 박는다. 다른 서비스 토큰을 들고 와도
            # 여기서 걸린다.
            "aud": "work",
            "exp": datetime.utcnow() + timedelta(hours=TOKEN_HOURS),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def current_user(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    db: Session = Depends(get_db),
) -> WorkUser:
    if creds is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    try:
        payload = jwt.decode(creds.credentials, SECRET_KEY,
                             algorithms=[ALGORITHM], audience="work")
        user_id = int(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="다시 로그인해 주세요.")

    user = db.get(WorkUser, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="쓸 수 없는 계정입니다.")

    # **여기가 출근 기록이다.** 관문을 지나는 모든 요청이 흔적을 남긴다.
    touch_attendance(db, user, request)
    return user


def require(*roles: str):
    def dep(user: WorkUser = Depends(current_user)) -> WorkUser:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
        return user
    return dep


admin_only = require("admin")
staff_only = require("staff", "admin")
partner_only = require("partner", "admin")


def touch_attendance(db: Session, user: WorkUser, request: Request) -> None:
    """그날 첫 접속이면 만들고, 아니면 마지막 활동 시각만 민다.

    협업기업은 우리 직원이 아니므로 출근을 안 센다. 관리자는 센다 —
    본인도 그날 일을 시작했는지 보이는 편이 낫다.
    """
    if user.role == "partner":
        return
    now = datetime.utcnow()
    day = today_kst()
    row = (
        db.query(WorkAttendance)
        .filter(WorkAttendance.user_id == user.id, WorkAttendance.work_date == day)
        .first()
    )
    if row is None:
        row = WorkAttendance(
            user_id=user.id, work_date=day,
            first_seen_at=now, last_seen_at=now,
            ip=(request.client.host if request.client else "")[:45],
            user_agent=(request.headers.get("user-agent") or "")[:200],
        )
        db.add(row)
    else:
        # 1분 안쪽의 연속 호출까지 매번 쓰면 화면 한 번 열 때마다 UPDATE 가
        # 여러 번 나간다. 의미 있는 간격으로만 민다.
        if (now - row.last_seen_at).total_seconds() < 60:
            return
        row.last_seen_at = now
    try:
        db.commit()
    except Exception:
        db.rollback()


# ─────────────────────────────────────────────────────────────────────────────
# 주고받는 모양
# ─────────────────────────────────────────────────────────────────────────────

class LoginIn(BaseModel):
    login_id: str
    password: str


class PasswordIn(BaseModel):
    current_password: str = ""
    new_password: str = Field(min_length=8, max_length=72)


class UserIn(BaseModel):
    login_id: str = Field(min_length=3, max_length=40)
    name: str = Field(min_length=1, max_length=40)
    role: str = "staff"
    org_id: Optional[int] = None
    phone: str = ""
    email: str = ""
    memo: str = ""


class UserPatch(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    org_id: Optional[int] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    memo: Optional[str] = None
    is_active: Optional[bool] = None


class OrgIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    contact: str = ""
    is_active: bool = True


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = ""
    assignee_id: int
    priority: int = 0
    due_at: Optional[datetime] = None
    request_id: Optional[int] = None


class TaskPatch(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    assignee_id: Optional[int] = None
    status: Optional[str] = None
    priority: Optional[int] = None
    due_at: Optional[datetime] = None
    progress_note: Optional[str] = None


class RequestIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = ""
    priority: int = 0


class AttendancePatch(BaseModel):
    """관리자가 고치는 값. "09:12" 형식, 빈 문자열이면 지운다."""
    first_seen: Optional[str] = None
    left_at: Optional[str] = None


class RequestPatch(BaseModel):
    status: Optional[str] = None
    admin_note: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# 보여 줄 모양으로 바꾸기
# ─────────────────────────────────────────────────────────────────────────────

def kst_str(dt: Optional[datetime], fmt: str = "%Y-%m-%d %H:%M") -> Optional[str]:
    return (dt + KST).strftime(fmt) if dt else None


def user_out(u: WorkUser, org_name: str = "") -> dict:
    return {
        "id": u.id, "login_id": u.login_id, "name": u.name, "role": u.role,
        "org_id": u.org_id, "org_name": org_name,
        "phone": u.phone, "email": u.email, "memo": u.memo,
        "is_active": u.is_active, "must_change_password": u.must_change_password,
        "last_login_at": kst_str(u.last_login_at),
        "created_at": kst_str(u.created_at),
    }


def task_out(t: WorkTask, names: dict) -> dict:
    overdue = bool(
        t.due_at and t.status not in ("done",) and t.due_at < datetime.utcnow()
    )
    return {
        "id": t.id, "title": t.title, "body": t.body,
        "assignee_id": t.assignee_id, "assignee": names.get(t.assignee_id, "?"),
        "created_by": t.created_by, "creator": names.get(t.created_by, ""),
        "status": t.status, "priority": t.priority,
        "due_at": kst_str(t.due_at), "overdue": overdue,
        "progress_note": t.progress_note,
        "request_id": t.request_id,
        "created_at": kst_str(t.created_at),
        "done_at": kst_str(t.done_at),
    }


def request_out(r: WorkRequest, org_names: dict, names: dict) -> dict:
    return {
        "id": r.id, "title": r.title, "body": r.body,
        "org_id": r.org_id, "org_name": org_names.get(r.org_id, "?"),
        "author": names.get(r.created_by, ""),
        "status": r.status, "priority": r.priority,
        "admin_note": r.admin_note,
        "handled_by": names.get(r.handled_by, ""),
        "handled_at": kst_str(r.handled_at),
        "created_at": kst_str(r.created_at),
    }


def _names(db: Session) -> dict:
    return {u.id: u.name for u in db.query(WorkUser.id, WorkUser.name).all()}


def _org_names(db: Session) -> dict:
    return {o.id: o.name for o in db.query(WorkOrg.id, WorkOrg.name).all()}


# ─────────────────────────────────────────────────────────────────────────────
# 로그인
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = (
        db.query(WorkUser)
        .filter(func.lower(WorkUser.login_id) == body.login_id.strip().lower())
        .first()
    )
    # 아이디가 없을 때와 비밀번호가 틀렸을 때의 답을 같게 둔다. 다르면
    # 어떤 아이디가 존재하는지 알아낼 수 있다.
    if user is None or not user.is_active or not pwd.verify(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 맞지 않습니다.")

    user.last_login_at = datetime.utcnow()
    db.commit()
    org = db.get(WorkOrg, user.org_id) if user.org_id else None
    return {
        "token": make_token(user),
        "me": user_out(user, org.name if org else ""),
    }


@router.get("/me")
def me(user: WorkUser = Depends(current_user), db: Session = Depends(get_db)):
    org = db.get(WorkOrg, user.org_id) if user.org_id else None
    return user_out(user, org.name if org else "")


@router.post("/me/password")
def change_password(body: PasswordIn, user: WorkUser = Depends(current_user),
                    db: Session = Depends(get_db)):
    # 초기 비밀번호를 아직 안 바꾼 사람은 현재 비밀번호를 다시 안 묻는다.
    # 방금 그걸로 로그인해서 들어왔기 때문이다.
    if not user.must_change_password:
        if not pwd.verify(body.current_password or "", user.password_hash):
            raise HTTPException(status_code=400, detail="현재 비밀번호가 맞지 않습니다.")
    user.password_hash = pwd.hash(body.new_password)
    user.must_change_password = False
    db.commit()
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# 첫 화면에 필요한 것 (권한마다 다르다)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/summary")
def summary(user: WorkUser = Depends(current_user), db: Session = Depends(get_db)):
    out = {"role": user.role, "name": user.name, "today": today_kst().isoformat()}

    if user.role in ("admin", "staff"):
        out["my_today"] = _my_today(db, user)
        q = db.query(WorkTask)
        if user.role == "staff":
            q = q.filter(WorkTask.assignee_id == user.id)
        out["my_tasks"] = {
            "todo": q.filter(WorkTask.status == "todo").count(),
            "doing": q.filter(WorkTask.status == "doing").count(),
            "overdue": q.filter(
                WorkTask.status.in_(("todo", "doing")),
                WorkTask.due_at.isnot(None),
                WorkTask.due_at < datetime.utcnow(),
            ).count(),
        }

    if user.role == "admin":
        # 출근을 세는 대상과 같은 범위여야 한다. 아래 /attendance 는
        # 직원과 관리자를 함께 보여 주므로 여기도 둘 다 센다.
        staff_total = db.query(WorkUser).filter(
            WorkUser.role.in_(("staff", "admin")), WorkUser.is_active.is_(True)).count()
        today = today_kst()
        present = db.query(WorkAttendance).filter(
            WorkAttendance.work_date == today).count()
        left = db.query(WorkAttendance).filter(
            WorkAttendance.work_date == today,
            WorkAttendance.left_at.isnot(None)).count()
        out["attendance"] = {"staff_total": staff_total, "present": present,
                             "left": left, "working": present - left}
        out["requests"] = {
            "new": db.query(WorkRequest).filter(WorkRequest.status == "new").count(),
            "open": db.query(WorkRequest).filter(
                WorkRequest.status.in_(("new", "reading"))).count(),
        }
        out["tasks_all"] = {
            "todo": db.query(WorkTask).filter(WorkTask.status == "todo").count(),
            "doing": db.query(WorkTask).filter(WorkTask.status == "doing").count(),
        }

    if user.role == "partner":
        q = db.query(WorkRequest).filter(WorkRequest.org_id == user.org_id)
        out["requests"] = {
            "total": q.count(),
            "open": q.filter(WorkRequest.status.in_(("new", "reading"))).count(),
            "answered": q.filter(WorkRequest.status == "answered").count(),
        }
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 할 일
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/tasks")
def list_tasks(
    status_filter: str = "",
    assignee_id: Optional[int] = None,
    user: WorkUser = Depends(current_user),
    db: Session = Depends(get_db),
):
    """직원은 자기 것만, 관리자는 전부(원하면 사람별로)."""
    if user.role == "partner":
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")

    q = db.query(WorkTask)
    if user.role == "staff":
        q = q.filter(WorkTask.assignee_id == user.id)
    elif assignee_id:
        q = q.filter(WorkTask.assignee_id == assignee_id)

    if status_filter:
        wanted = [s for s in status_filter.split(",") if s in TASK_STATUS]
        if wanted:
            q = q.filter(WorkTask.status.in_(wanted))

    rows = q.order_by(
        # 끝난 일은 아래로, 급한 것과 기한이 임박한 것이 위로.
        (WorkTask.status == "done"),
        WorkTask.priority.desc(),
        WorkTask.due_at.is_(None),
        WorkTask.due_at.asc(),
        WorkTask.created_at.desc(),
    ).limit(300).all()
    names = _names(db)
    return [task_out(t, names) for t in rows]


@router.post("/tasks")
def create_task(body: TaskIn, user: WorkUser = Depends(admin_only),
                db: Session = Depends(get_db)):
    target = db.get(WorkUser, body.assignee_id)
    if target is None or not target.is_active or target.role == "partner":
        raise HTTPException(status_code=400, detail="지시할 수 없는 대상입니다.")
    t = WorkTask(
        title=body.title.strip(), body=body.body,
        assignee_id=target.id, created_by=user.id,
        priority=max(0, min(2, body.priority)),
        due_at=body.due_at, request_id=body.request_id,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return task_out(t, _names(db))


@router.patch("/tasks/{task_id}")
def update_task(task_id: int, body: TaskPatch,
                user: WorkUser = Depends(current_user), db: Session = Depends(get_db)):
    t = db.get(WorkTask, task_id)
    if t is None:
        raise HTTPException(status_code=404, detail="없는 업무입니다.")

    if user.role == "staff":
        # 직원은 **자기 일의 진행 상태와 메모만** 바꾼다. 제목·담당자·기한을
        # 바꿀 수 있으면 지시가 지시가 아니게 된다.
        if t.assignee_id != user.id:
            raise HTTPException(status_code=403, detail="내 업무가 아닙니다.")
        if body.status is not None:
            if body.status not in TASK_STATUS:
                raise HTTPException(status_code=400, detail="모르는 상태입니다.")
            t.status = body.status
        if body.progress_note is not None:
            t.progress_note = body.progress_note[:400]
    elif user.role == "admin":
        for field in ("title", "body", "priority", "due_at", "progress_note"):
            v = getattr(body, field)
            if v is not None:
                setattr(t, field, v)
        if body.status is not None:
            if body.status not in TASK_STATUS:
                raise HTTPException(status_code=400, detail="모르는 상태입니다.")
            t.status = body.status
        if body.assignee_id is not None:
            target = db.get(WorkUser, body.assignee_id)
            if target is None or target.role == "partner":
                raise HTTPException(status_code=400, detail="지시할 수 없는 대상입니다.")
            t.assignee_id = target.id
    else:
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")

    t.done_at = datetime.utcnow() if t.status == "done" else None
    db.commit()
    db.refresh(t)
    return task_out(t, _names(db))


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int, user: WorkUser = Depends(admin_only),
                db: Session = Depends(get_db)):
    t = db.get(WorkTask, task_id)
    if t is None:
        raise HTTPException(status_code=404, detail="없는 업무입니다.")
    db.delete(t)
    db.commit()
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# 협업기업 요청사항
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/requests")
def list_requests(
    status_filter: str = "",
    user: WorkUser = Depends(current_user),
    db: Session = Depends(get_db),
):
    """협업기업은 **자기 회사 것만** 본다. 다른 회사 요청은 보이지 않는다."""
    if user.role == "staff":
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
    q = db.query(WorkRequest)
    if user.role == "partner":
        if not user.org_id:
            return []
        q = q.filter(WorkRequest.org_id == user.org_id)
    if status_filter:
        wanted = [s for s in status_filter.split(",") if s in REQ_STATUS]
        if wanted:
            q = q.filter(WorkRequest.status.in_(wanted))
    rows = q.order_by(
        (WorkRequest.status == "closed"),
        WorkRequest.priority.desc(),
        WorkRequest.created_at.desc(),
    ).limit(300).all()
    return [request_out(r, _org_names(db), _names(db)) for r in rows]


@router.post("/requests")
def create_request(body: RequestIn, user: WorkUser = Depends(partner_only),
                   db: Session = Depends(get_db)):
    if user.role == "partner" and not user.org_id:
        raise HTTPException(status_code=400, detail="소속 기업이 지정되지 않았습니다.")
    r = WorkRequest(
        org_id=user.org_id, created_by=user.id,
        title=body.title.strip(), body=body.body,
        priority=max(0, min(2, body.priority)),
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return request_out(r, _org_names(db), _names(db))


@router.patch("/requests/{req_id}")
def update_request(req_id: int, body: RequestPatch,
                   user: WorkUser = Depends(admin_only), db: Session = Depends(get_db)):
    r = db.get(WorkRequest, req_id)
    if r is None:
        raise HTTPException(status_code=404, detail="없는 요청입니다.")
    if body.status is not None:
        if body.status not in REQ_STATUS:
            raise HTTPException(status_code=400, detail="모르는 상태입니다.")
        r.status = body.status
    if body.admin_note is not None:
        r.admin_note = body.admin_note
    r.handled_by = user.id
    r.handled_at = datetime.utcnow()
    db.commit()
    db.refresh(r)
    return request_out(r, _org_names(db), _names(db))


# ─────────────────────────────────────────────────────────────────────────────
# 출근 현황
# ─────────────────────────────────────────────────────────────────────────────

def close_past_days(db: Session) -> int:
    """퇴근을 안 누른 채 날이 넘어간 기록을 마지막 활동 시각으로 닫는다.

    **왜 자동으로 닫나.** 안 닫으면 그 날은 영영 빈칸으로 남고, 월말에
    근무일수를 세면 "퇴근 안 찍은 날"이 무더기로 나온다. 그렇다고 아무 값이나
    넣으면 안 되므로, 근거가 있는 유일한 값(그날 마지막으로 시스템을 쓴 시각)을
    쓰고 **auto_closed 표시를 남긴다.** 화면에도 '자동'이라고 적는다 —
    본인이 찍은 시각인 척하면 근태 다툼이 났을 때 쓸 수 없는 기록이 된다.

    별도 타이머를 두지 않고 화면을 볼 때 훑는다. 워커가 여럿이라 타이머는
    여러 번 돌고, 하루 몇 줄 고치자고 백그라운드 작업을 따로 둘 이유가 없다.
    """
    rows = (
        db.query(WorkAttendance)
        .filter(WorkAttendance.work_date < today_kst(),
                WorkAttendance.left_at.is_(None))
        .limit(500)
        .all()
    )
    if not rows:
        return 0
    for a in rows:
        a.left_at = a.last_seen_at
        a.auto_closed = True
    try:
        db.commit()
    except Exception:
        db.rollback()
        return 0
    return len(rows)


def _late_after() -> tuple:
    try:
        h, m = WORK_START.split(":")
        return int(h), int(m)
    except (ValueError, AttributeError):
        return 9, 0


@router.get("/attendance")
def attendance(on: str = "", user: WorkUser = Depends(admin_only),
               db: Session = Depends(get_db)):
    """그날 누가 언제 처음 접속했는지. 안 보이는 사람이 곧 미접속이다."""
    close_past_days(db)
    try:
        day = date.fromisoformat(on) if on else today_kst()
    except ValueError:
        day = today_kst()

    staff = (
        db.query(WorkUser)
        .filter(WorkUser.role.in_(("staff", "admin")), WorkUser.is_active.is_(True))
        .order_by(WorkUser.role.desc(), WorkUser.name.asc())
        .all()
    )
    rows = {
        a.user_id: a for a in db.query(WorkAttendance)
        .filter(WorkAttendance.work_date == day).all()
    }
    lh, lm = _late_after()
    now = now_kst()

    out = []
    for u in staff:
        a = rows.get(u.id)
        if a is None:
            out.append({
                "user_id": u.id, "name": u.name, "role": u.role,
                "state": "absent", "first_seen": None, "last_seen": None,
                "minutes_ago": None, "late": False,
            })
            continue
        first = a.first_seen_at + KST
        last = a.last_seen_at + KST
        left = (a.left_at + KST) if a.left_at else None
        # 퇴근을 눌렀으면 그게 우선이다. 안 눌렀으면 최근 활동으로 자리에
        # 있는지만 본다 — '자리 비움'과 '퇴근'은 다른 얘기라 섞지 않는다.
        state = "left" if left else ("in" if (now - last) < timedelta(minutes=30) else "away")
        out.append({
            "user_id": u.id, "name": u.name, "role": u.role,
            "state": state,
            "first_seen": first.strftime("%H:%M"),
            "last_seen": last.strftime("%H:%M"),
            "left_at": left.strftime("%H:%M") if left else None,
            "worked_hours": (round((left - first).total_seconds() / 3600, 1)
                             if left else None),
            "auto_closed": bool(a.auto_closed),
            "edited": a.edited_by is not None,
            "minutes_ago": int((now - last).total_seconds() // 60),
            "late": (first.hour, first.minute) > (lh, lm),
        })
    return {
        "date": day.isoformat(),
        "start_time": WORK_START,
        "present": sum(1 for x in out if x["state"] != "absent"),
        "total": len(out),
        "rows": out,
        # 화면에 그대로 적을 문장. 이 방식의 한계를 감추지 않는다.
        "note": "출근은 그날 처음 접속한 시각으로 자동 기록되고, 퇴근은 본인이 버튼을 눌러야 남습니다. 퇴근을 안 누른 채 날이 지나면 마지막 활동 시각으로 닫고 '자동'으로 표시합니다.",
    }


def _today_row(db: Session, user: WorkUser) -> Optional[WorkAttendance]:
    return (
        db.query(WorkAttendance)
        .filter(WorkAttendance.user_id == user.id,
                WorkAttendance.work_date == today_kst())
        .first()
    )


def _my_today(db: Session, user: WorkUser) -> dict:
    """내 오늘 근무 상태. 위젯의 퇴근 버튼이 이걸 보고 모양을 정한다."""
    a = _today_row(db, user)
    if a is None:
        return {"tracked": False}
    first = a.first_seen_at + KST
    left = (a.left_at + KST) if a.left_at else None
    lh, lm = _late_after()
    return {
        "tracked": True,
        "first_seen": first.strftime("%H:%M"),
        "left_at": left.strftime("%H:%M") if left else None,
        "worked_hours": round((left - first).total_seconds() / 3600, 1) if left else None,
        "auto_closed": bool(a.auto_closed),
        "late": (first.hour, first.minute) > (lh, lm),
    }


@router.post("/attendance/leave")
def clock_out(user: WorkUser = Depends(current_user), db: Session = Depends(get_db)):
    """퇴근을 찍는다.

    협업기업은 우리 직원이 아니라 근무를 안 센다. 이미 찍혀 있으면 시각을
    덮어쓰지 않는다 — 실수로 두 번 눌러도 처음 찍은 시각이 맞는 기록이다.
    (고쳐야 하면 '퇴근 취소' 후 다시 누른다.)
    """
    if user.role == "partner":
        raise HTTPException(status_code=403, detail="근무 기록 대상이 아닙니다.")
    a = _today_row(db, user)
    if a is None:
        raise HTTPException(status_code=400, detail="오늘 출근 기록이 아직 없습니다.")
    if a.left_at is None:
        a.left_at = datetime.utcnow()
        db.commit()
    return _my_today(db, user)


@router.post("/attendance/leave/cancel")
def undo_clock_out(user: WorkUser = Depends(current_user), db: Session = Depends(get_db)):
    """잘못 누른 퇴근을 되돌린다. 그날 것만 가능하다."""
    if user.role == "partner":
        raise HTTPException(status_code=403, detail="근무 기록 대상이 아닙니다.")
    a = _today_row(db, user)
    if a is None:
        raise HTTPException(status_code=400, detail="오늘 출근 기록이 없습니다.")
    a.left_at = None
    db.commit()
    return _my_today(db, user)


def _parse_hm(value: str, day: date) -> Optional[datetime]:
    """"09:12" 를 그날의 UTC 시각으로. 빈 값이면 None."""
    v = (value or "").strip()
    if not v:
        return None
    try:
        h, m = v.split(":")
        local = datetime(day.year, day.month, day.day, int(h), int(m))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="시각은 09:30 처럼 넣어 주세요.")
    return local - KST


@router.patch("/attendance/{target_id}")
def edit_attendance(target_id: int, body: AttendancePatch, on: str = "",
                    user: WorkUser = Depends(admin_only),
                    db: Session = Depends(get_db)):
    """관리자가 출근·퇴근 시각을 고친다.

    깜빡하고 안 찍은 날, 접속 없이 외근한 날처럼 자동 기록이 실제와 다른 경우가
    반드시 생긴다. 고칠 길이 없으면 그 기록은 못 쓰는 기록이 된다.

    **고친 기록에는 누가 고쳤는지 남긴다.** 나중에 근태를 따질 때 자동 기록과
    사람이 손댄 기록을 구분할 수 있어야 한다.
    """
    try:
        day = date.fromisoformat(on) if on else today_kst()
    except ValueError:
        raise HTTPException(status_code=400, detail="날짜는 2026-09-13 형식으로 넣어 주세요.")

    target = db.get(WorkUser, target_id)
    if target is None or target.role == "partner":
        raise HTTPException(status_code=404, detail="근무 기록 대상이 아닙니다.")
    # 출퇴근 기록이 곧 급여다. 정산 완료(급여명세서 확정)한 달은 고치면 명세서와 어긋난다.
    from .models import WorkSettlement
    if db.query(WorkSettlement).filter(WorkSettlement.month == day.strftime("%Y-%m")).first():
        raise HTTPException(status_code=400,
                            detail="정산 완료된 달의 출퇴근 기록입니다. 정산 완료를 취소한 뒤 고쳐 주세요.")

    row = (
        db.query(WorkAttendance)
        .filter(WorkAttendance.user_id == target_id, WorkAttendance.work_date == day)
        .first()
    )
    first = _parse_hm(body.first_seen, day) if body.first_seen is not None else None

    if row is None:
        # 아예 기록이 없던 날도 만들어 줄 수 있어야 한다(접속 없이 일한 날).
        if first is None:
            raise HTTPException(status_code=400, detail="출근 시각을 넣어야 기록을 만들 수 있습니다.")
        row = WorkAttendance(user_id=target_id, work_date=day,
                             first_seen_at=first, last_seen_at=first)
        db.add(row)
    elif first is not None:
        row.first_seen_at = first
        if row.last_seen_at < first:
            row.last_seen_at = first

    if body.left_at is not None:
        left = _parse_hm(body.left_at, day)
        if left is not None and left < row.first_seen_at:
            raise HTTPException(status_code=400, detail="퇴근이 출근보다 빠릅니다.")
        row.left_at = left
        # 사람이 정한 값이므로 '자동' 표시는 뗀다.
        row.auto_closed = False

    row.edited_by = user.id
    row.edited_at = datetime.utcnow()
    db.commit()

    return {"ok": True, "date": day.isoformat()}


@router.get("/attendance/me")
def my_attendance(days: int = 14, user: WorkUser = Depends(current_user),
                  db: Session = Depends(get_db)):
    close_past_days(db)
    days = max(1, min(days, 90))
    since = today_kst() - timedelta(days=days)
    rows = (
        db.query(WorkAttendance)
        .filter(WorkAttendance.user_id == user.id, WorkAttendance.work_date >= since)
        .order_by(WorkAttendance.work_date.desc())
        .all()
    )
    lh, lm = _late_after()
    def one(a):
        first = a.first_seen_at + KST
        left = (a.left_at + KST) if a.left_at else None
        return {
            "date": a.work_date.isoformat(),
            "first_seen": first.strftime("%H:%M"),
            "last_seen": (a.last_seen_at + KST).strftime("%H:%M"),
            "left_at": left.strftime("%H:%M") if left else None,
            "worked_hours": round((left - first).total_seconds() / 3600, 1) if left else None,
            "auto_closed": bool(a.auto_closed),
            "edited": a.edited_by is not None,
            "late": (first.hour, first.minute) > (lh, lm),
        }
    return [one(a) for a in rows]


# ─────────────────────────────────────────────────────────────────────────────
# 계정·기업 관리 (관리자만)
# ─────────────────────────────────────────────────────────────────────────────

LOGIN_RE = re.compile(r"^[a-zA-Z0-9._-]{3,40}$")


@router.get("/admin/users")
def list_users(user: WorkUser = Depends(admin_only), db: Session = Depends(get_db)):
    orgs = _org_names(db)
    rows = db.query(WorkUser).order_by(WorkUser.role.asc(), WorkUser.name.asc()).all()
    return [user_out(u, orgs.get(u.org_id, "")) for u in rows]


@router.post("/admin/users")
def create_user(body: UserIn, user: WorkUser = Depends(admin_only),
                db: Session = Depends(get_db)):
    login_id = body.login_id.strip()
    if not LOGIN_RE.match(login_id):
        raise HTTPException(status_code=400,
                            detail="아이디는 영문·숫자·.-_ 3~40자여야 합니다.")
    if body.role not in ROLES:
        raise HTTPException(status_code=400, detail="모르는 권한입니다.")
    if body.role == "partner" and not body.org_id:
        raise HTTPException(status_code=400, detail="협업기업 계정은 소속 기업이 필요합니다.")
    exists = db.query(WorkUser).filter(
        func.lower(WorkUser.login_id) == login_id.lower()).first()
    if exists:
        raise HTTPException(status_code=409, detail="이미 쓰고 있는 아이디입니다.")

    # 초기 비밀번호는 서버가 만든다. 사람이 정하면 'test1234' 같은 것이 남는다.
    temp = secrets.token_urlsafe(9)
    u = WorkUser(
        login_id=login_id, name=body.name.strip(), role=body.role,
        org_id=body.org_id if body.role == "partner" else None,
        phone=body.phone, email=body.email, memo=body.memo,
        password_hash=pwd.hash(temp), must_change_password=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    # 임시 비밀번호는 **이 응답에서 딱 한 번만** 보여 준다. 저장해 두지 않는다.
    return {"user": user_out(u, _org_names(db).get(u.org_id, "")),
            "temp_password": temp}


@router.patch("/admin/users/{user_id}")
def patch_user(user_id: int, body: UserPatch, user: WorkUser = Depends(admin_only),
               db: Session = Depends(get_db)):
    u = db.get(WorkUser, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="없는 계정입니다.")
    if body.role is not None and body.role not in ROLES:
        raise HTTPException(status_code=400, detail="모르는 권한입니다.")
    # 마지막 관리자를 잠그거나 강등하면 아무도 못 들어온다.
    if u.role == "admin" and (body.role not in (None, "admin") or body.is_active is False):
        others = db.query(WorkUser).filter(
            WorkUser.role == "admin", WorkUser.is_active.is_(True),
            WorkUser.id != u.id).count()
        if others == 0:
            raise HTTPException(status_code=400, detail="마지막 관리자입니다. 먼저 다른 관리자를 만드세요.")

    for field in ("name", "role", "phone", "email", "memo", "is_active"):
        v = getattr(body, field)
        if v is not None:
            setattr(u, field, v)
    if body.org_id is not None:
        u.org_id = body.org_id
    if u.role != "partner":
        u.org_id = None
    db.commit()
    db.refresh(u)
    return user_out(u, _org_names(db).get(u.org_id, ""))


def _delete_impact(db: Session, uid: int) -> dict:
    return {
        "tasks": db.query(WorkTask).filter(WorkTask.assignee_id == uid).count(),
        "open_tasks": db.query(WorkTask).filter(
            WorkTask.assignee_id == uid, WorkTask.status != "done").count(),
        "attendance_days": db.query(WorkAttendance).filter(WorkAttendance.user_id == uid).count(),
        "requests": db.query(WorkRequest).filter(WorkRequest.created_by == uid).count(),
    }


@router.delete("/admin/users/{user_id}")
def delete_user(user_id: int, preview: bool = False,
                user: WorkUser = Depends(admin_only), db: Session = Depends(get_db)):
    """계정을 지운다. `preview=true` 면 지우지 않고 무엇이 같이 사라지는지만 알려 준다.

    **같이 지우는 것:** 그 사람이 받은 업무, 그 사람의 출근 기록.
    **남기는 것:** 그 사람이 올린 협업 요청(기업의 기록이다), 그 사람이 배분한
    업무·처리한 요청·고친 출근 기록 — 이런 곳에서는 '누가'만 비운다.

    **지우는 순서가 중요하다.** PostgreSQL 은 아직 이 계정을 가리키는 줄이 하나라도
    있으면 계정 삭제를 거부한다. 가리키는 쪽을 먼저 비우거나 지우고, 계정은 맨
    마지막에 지운다. (로컬 SQLite 는 기본으로 이 검사를 안 해서 시험에서 안 걸린다.)

    되돌릴 수 없으므로, 기록을 남겨야 하는 사람이면 '중지'를 쓰는 편이 맞다.
    """
    target = db.get(WorkUser, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="없는 계정입니다.")
    if target.id == user.id:
        raise HTTPException(status_code=400, detail="지금 로그인한 본인 계정은 지울 수 없습니다.")
    if target.role == "admin":
        others = db.query(WorkUser).filter(
            WorkUser.role == "admin", WorkUser.is_active.is_(True),
            WorkUser.id != target.id).count()
        if others == 0:
            raise HTTPException(status_code=400, detail="마지막 관리자는 지울 수 없습니다.")

    impact = _delete_impact(db, target.id)
    if preview:
        return {"preview": True, "name": target.name, "role": target.role, **impact}

    uid = target.id
    try:
        # 1) '누가'만 비우면 되는 칸
        db.query(WorkTask).filter(WorkTask.created_by == uid).update(
            {WorkTask.created_by: None}, synchronize_session=False)
        db.query(WorkRequest).filter(WorkRequest.created_by == uid).update(
            {WorkRequest.created_by: None}, synchronize_session=False)
        db.query(WorkRequest).filter(WorkRequest.handled_by == uid).update(
            {WorkRequest.handled_by: None}, synchronize_session=False)
        db.query(WorkAttendance).filter(WorkAttendance.edited_by == uid).update(
            {WorkAttendance.edited_by: None}, synchronize_session=False)
        # 2) 그 사람 몫이라 같이 지우는 줄
        db.query(WorkTask).filter(WorkTask.assignee_id == uid).delete(synchronize_session=False)
        db.query(WorkAttendance).filter(WorkAttendance.user_id == uid).delete(synchronize_session=False)
        # 3) 마지막에 계정
        db.query(WorkUser).filter(WorkUser.id == uid).delete(synchronize_session=False)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"삭제하지 못했습니다 ({type(e).__name__}).")
    return {"deleted": True, **impact}


@router.post("/admin/users/{user_id}/reset-password")
def reset_password(user_id: int, user: WorkUser = Depends(admin_only),
                   db: Session = Depends(get_db)):
    u = db.get(WorkUser, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="없는 계정입니다.")
    temp = secrets.token_urlsafe(9)
    u.password_hash = pwd.hash(temp)
    u.must_change_password = True
    db.commit()
    return {"temp_password": temp}


@router.get("/admin/orgs")
def list_orgs(user: WorkUser = Depends(admin_only), db: Session = Depends(get_db)):
    counts = dict(
        db.query(WorkUser.org_id, func.count(WorkUser.id))
        .filter(WorkUser.org_id.isnot(None)).group_by(WorkUser.org_id).all()
    )
    rows = db.query(WorkOrg).order_by(WorkOrg.name.asc()).all()
    return [{
        "id": o.id, "name": o.name, "contact": o.contact,
        "is_active": o.is_active, "user_count": counts.get(o.id, 0),
        "created_at": kst_str(o.created_at),
    } for o in rows]


@router.post("/admin/orgs")
def create_org(body: OrgIn, user: WorkUser = Depends(admin_only),
               db: Session = Depends(get_db)):
    name = body.name.strip()
    if db.query(WorkOrg).filter(WorkOrg.name == name).first():
        raise HTTPException(status_code=409, detail="이미 있는 기업입니다.")
    o = WorkOrg(name=name, contact=body.contact, is_active=body.is_active)
    db.add(o)
    db.commit()
    db.refresh(o)
    return {"id": o.id, "name": o.name, "contact": o.contact,
            "is_active": o.is_active, "user_count": 0,
            "created_at": kst_str(o.created_at)}


# ─────────────────────────────────────────────────────────────────────────────
# 서버 상태 (관리자만) — 감시 API 를 대신 불러다 준다
# ─────────────────────────────────────────────────────────────────────────────
#
# **왜 여기서 다시 부르나.** 감시 API 는 우리동네 직업계고 백엔드(8000)에 있고,
# 토큰 하나로 열린다. 그 토큰을 브라우저에 내려보내면 업무 시스템에 로그인한
# 사람 누구나(직원·협업기업 포함) 서버 내부를 보게 된다. 그래서 **토큰은 이
# 프로세스 안에만 두고**, 관리자인지 확인한 다음 필요한 만큼만 추려서 준다.

MONITOR_URL = (os.getenv("MONITOR_URL", "http://127.0.0.1:8000") or "").rstrip("/")
MONITOR_TOKEN = (os.getenv("MONITOR_TOKEN", "") or "").strip()

_server_cache: dict = {"at": 0.0, "data": None}


def _fetch_monitor() -> dict:
    import json as _json
    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        MONITOR_URL + "/api/monitor/snapshot",
        headers={"X-Monitor-Token": MONITOR_TOKEN, "User-Agent": "work-backend"},
    )
    with urllib.request.urlopen(req, timeout=8) as r:
        return _json.loads(r.read().decode("utf-8"))


@router.get("/admin/server")
def server_status(user: WorkUser = Depends(admin_only)):
    """서버가 지금 괜찮은지. 화면에 필요한 만큼만 추려서 돌려준다."""
    if not MONITOR_TOKEN:
        return {"available": False,
                "reason": "work-backend/.env 에 MONITOR_TOKEN 을 넣으면 여기에 서버 상태가 나옵니다."}

    # 감시 쪽도 4초 캐시가 있지만, 화면이 여러 개 열려 있어도 부르는 횟수가
    # 늘지 않도록 이쪽에서도 한 번 막아 둔다.
    now = time.time()
    if _server_cache["data"] is not None and now - float(_server_cache["at"]) < 10:
        return _server_cache["data"]

    try:
        snap = _fetch_monitor()
    except Exception as e:
        name = type(e).__name__
        detail = "감시 토큰이 맞지 않습니다." if "HTTPError" in name else "감시 API 에 닿지 못했습니다."
        return {"available": False, "reason": f"{detail} ({name})"}

    sysv, disk, tr = snap["system"], snap["disk"], snap["traffic"]
    units = snap["services"]["units"] + snap["services"]["probes"]
    ssl_days = [c["days_left"] for c in snap.get("ssl", [])]
    bk = snap.get("backup", {})

    out = {
        "available": True,
        "status": snap.get("status", "ok"),
        "collected_at": snap.get("collected_at", "")[-8:],
        "alerts": [{"level": a["level"], "message": a["message"]}
                   for a in snap.get("alerts", [])][:5],
        "alert_count": len(snap.get("alerts", [])),
        "cpu": sysv.get("cpu_percent"),
        "mem": sysv.get("mem_percent"),
        "disk": disk.get("percent"),
        "disk_free_mb": disk.get("free_mb"),
        "disk_days_left": disk.get("days_left"),
        "uptime_hours": sysv.get("uptime_hours"),
        "down": [u.get("unit") or u.get("name")
                 for u in units if not u.get("ok")],
        "service_total": len(units),
        "visitors": {k: v.get("visitors_now", 0) for k, v in tr.get("sites", {}).items()},
        "errors_5xx": tr.get("status", {}).get("5xx", 0),
        "ssl_days_left": min(ssl_days) if ssl_days else None,
        "backup_age_hours": bk.get("age_hours") if bk.get("found") else None,
        "uptime_percent": (snap.get("uptime") or {}).get("percent"),
    }
    _server_cache["at"], _server_cache["data"] = now, out
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 첫 관리자 만들기
# ─────────────────────────────────────────────────────────────────────────────

def ensure_first_admin() -> None:
    """관리자가 하나도 없으면 .env 의 값으로 하나 만든다.

    가입 화면이 없는 시스템이라 첫 사람을 넣을 길이 필요하다. 이미 관리자가
    있으면 아무것도 안 한다 — 실수로 비밀번호가 되돌아가는 일이 없도록.
    """
    login_id = (os.getenv("WORK_ADMIN_ID", "") or "").strip()
    password = (os.getenv("WORK_ADMIN_PASSWORD", "") or "").strip()
    if not login_id or not password:
        return
    from .database import SessionLocal
    db = SessionLocal()
    try:
        if db.query(WorkUser).filter(WorkUser.role == "admin").count() > 0:
            return
        db.add(WorkUser(
            login_id=login_id,
            name=(os.getenv("WORK_ADMIN_NAME", "") or "관리자").strip(),
            role="admin", password_hash=pwd.hash(password),
            must_change_password=True,
        ))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
