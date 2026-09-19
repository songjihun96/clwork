"""형제 서비스(기록해)를 위한 서버 간 계정 API.

계정의 원본은 언제나 UDJ 이다. 기록해는 자체 DB에 일지·구독을 두지만,
계정 자체는 이곳에 만들고 여기서 확인한다. 그래야 비밀번호 해시가 한 곳에만
있고, 탈퇴했을 때 양쪽에서 확실히 지워진다.

브라우저가 이 API 를 직접 부르지 않는다. 기록해 서버만 부른다.
그래서 공유 비밀키(PARTNER_SECRET)로 호출자를 확인한다.

backend/.env
    PARTNER_SECRET=충분히-긴-무작위-문자열
"""

import hmac
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .auth import hash_password, verify_password
from .database import get_db
from .models import Role, School, SchoolSubject, SchoolVerification, User

router = APIRouter(prefix="/api/partner", tags=["partner"])

# 개인정보 보호법 제22조의2. main.py 와 같은 값이어야 한다.
CHILD_AGE_LIMIT = 14


def korean_age(birth, today=None) -> int:
    """만 나이."""
    from datetime import date as _date
    today = today or _date.today()
    years = today.year - birth.year
    if (today.month, today.day) < (birth.month, birth.day):
        years -= 1
    return years


def partner_secret() -> str:
    return (os.getenv("PARTNER_SECRET", "") or "").split("#", 1)[0].strip()


def require_partner(x_partner_secret: Optional[str] = Header(None)) -> None:
    """형제 서비스 서버인지 확인한다.

    비교는 hmac.compare_digest 로 한다. 문자열을 == 로 비교하면 앞에서부터
    다른 지점까지의 시간 차이로 키를 추측할 수 있다.
    """
    secret = partner_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="연동이 설정되지 않았습니다.")
    if not x_partner_secret or not hmac.compare_digest(x_partner_secret, secret):
        raise HTTPException(status_code=401, detail="연동 인증에 실패했습니다.")


def profile_of(db: Session, user: User) -> dict:
    """기록해가 자기 DB 에 복사해 둘 정보.

    소속(학교·담당 교사·학급)은 로그인할 때마다 새로 넘겨준다. 그래야 UDJ 에서
    재학생 인증을 받거나 학년이 바뀌어도 기록해에 자동으로 반영된다.
    """
    v = (
        db.query(SchoolVerification)
        .filter(SchoolVerification.user_id == user.id)
        .order_by(SchoolVerification.id.desc())
        .first()
    )
    school = db.get(School, v.school_id) if v else None
    if not school and user.school_id:
        # 교사·학교 계정은 인증 절차 없이 school_id 가 직접 붙는다
        school = db.get(School, user.school_id)

    return {
        "udj_user_id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role.value,
        "phone": user.phone or "",
        "birth_date": user.birth_date.isoformat() if user.birth_date else None,
        "department": user.department or "",
        "grade": user.grade,
        "school_id": school.id if school else None,
        "school_name": school.name if school else "",
        "verified": bool(v and v.status == "approved"),
        "verify_status": v.status if v else "",
        "teacher_udj_id": v.teacher_id if v else None,
        "class_name": (v.class_name if v else "") or user.class_name or "",
        "is_active": bool(user.is_active),
    }


@router.get("/schools/{school_id}/subjects", dependencies=[Depends(require_partner)])
def partner_school_subjects(school_id: int, db: Session = Depends(get_db)):
    """기록해가 학과·과목 드롭다운을 채울 때 부른다.

    기록해는 예전에 한 번 마이그레이션해 온 사본을 두고 있는데, 그 뒤로
    학과가 새로 생기거나 NEIS 시간표가 다시 들어오면 그 사본은 낡는다.
    여기서 그때그때 최신 값을 준다.

    학과 이름은 School.departments(줄바꿈 목록)에서 가져온다 — 이게
    학교마다 가장 먼저, 가장 안정적으로 채워지는 값이다. 과목명은
    SchoolSubject(NEIS 시간표 수집분)에서 가져오는데, 학교에 따라
    비어 있을 수 있다.
    """
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")

    departments = [d.strip() for d in (school.departments or "").splitlines() if d.strip()]
    rows = db.query(SchoolSubject).filter(SchoolSubject.school_id == school_id).all()
    return {
        "school_name": school.name,
        "departments": departments,
        "subjects": [
            {"department": r.department or "", "grade": r.grade, "name": r.name}
            for r in rows
        ],
    }


@router.post("/login", dependencies=[Depends(require_partner)])
def partner_login(payload: dict, db: Session = Depends(get_db)):
    """이메일·비밀번호를 확인하고 프로필을 돌려준다.

    실패 사유를 자세히 알려주지 않는다. 계정이 있는지 없는지가 새어 나가면
    가입 여부를 확인하는 데 쓰일 수 있다.
    """
    email = str(payload.get("email") or "").strip()
    password = str(payload.get("password") or "")
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 맞지 않습니다.")
    if not user.is_active:
        if user.guardian_email and not user.guardian_consent_at:
            raise HTTPException(
                status_code=403,
                detail=f"보호자 동의가 아직 완료되지 않았습니다. {user.guardian_email} 로 보낸 메일을 확인해주세요.",
            )
        raise HTTPException(status_code=403, detail="정지된 계정입니다. 관리자에게 문의하세요.")
    return profile_of(db, user)


@router.get("/users/{udj_user_id}", dependencies=[Depends(require_partner)])
def partner_get_user(udj_user_id: int, db: Session = Depends(get_db)):
    """토큰을 갱신할 때 최신 소속 정보를 다시 받아가는 용도."""
    user = db.get(User, udj_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
    return profile_of(db, user)


@router.post("/users", dependencies=[Depends(require_partner)])
def partner_create_user(payload: dict, db: Session = Depends(get_db)):
    """기록해 화면에서 가입한 사람의 계정을 UDJ 에 만든다.

    휴대폰 인증은 기록해가 UDJ 의 인증 API 를 그대로 쓰므로, 여기서는 이미
    확인된 번호를 값으로 받는다. 만 14세 미만 처리도 UDJ 규칙을 따른다.
    """
    email = str(payload.get("email") or "").strip()
    if not email:
        raise HTTPException(status_code=400, detail="이메일이 필요합니다.")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="이미 가입된 이메일입니다.")

    birth = payload.get("birth_date")
    birth_date = datetime.fromisoformat(str(birth)).date() if birth else None
    is_child = bool(birth_date and korean_age(birth_date) < CHILD_AGE_LIMIT)
    guardian_email = str(payload.get("guardian_email") or "").strip()
    if is_child and not guardian_email:
        raise HTTPException(
            status_code=400,
            detail=f"만 {CHILD_AGE_LIMIT}세 미만은 법정대리인(보호자) 이메일이 필요합니다.",
        )

    user = User(
        email=email,
        password_hash=hash_password(str(payload.get("password") or "")),
        name=str(payload.get("name") or "")[:60],
        role=Role.student,
        phone=str(payload.get("phone") or "")[:30],
        birth_date=birth_date,
        guardian_email=guardian_email if is_child else "",
        privacy_consent_at=datetime.utcnow(),
        is_active=not is_child,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {
        "profile": profile_of(db, user),
        "guardian_consent_required": is_child,
        "guardian_email": guardian_email if is_child else "",
    }


@router.patch("/users/{udj_user_id}", dependencies=[Depends(require_partner)])
def partner_update_user(udj_user_id: int, payload: dict, db: Session = Depends(get_db)):
    """기록해 화면에서 고친 정보를 UDJ 에 반영한다.

    이메일과 권한은 바꾸지 않는다. 휴대폰번호는 본인확인 수단이라
    UDJ 의 번호 변경 절차(비밀번호 확인 + 문자 인증)를 거쳐야 한다.
    """
    user = db.get(User, udj_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")

    if "name" in payload:
        name = str(payload["name"] or "").strip()
        if len(name) < 2:
            raise HTTPException(status_code=400, detail="이름은 2자 이상 입력해주세요.")
        user.name = name[:60]
    if "department" in payload:
        user.department = str(payload["department"] or "").strip()[:60]
    if "grade" in payload:
        g = payload["grade"]
        user.grade = int(g) if g else None
    db.commit()
    return profile_of(db, user)


@router.post("/users/{udj_user_id}/change-password", dependencies=[Depends(require_partner)])
def partner_change_password(udj_user_id: int, payload: dict, db: Session = Depends(get_db)):
    user = db.get(User, udj_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
    if not verify_password(str(payload.get("current_password") or ""), user.password_hash):
        raise HTTPException(status_code=400, detail="현재 비밀번호가 맞지 않습니다.")
    new_password = str(payload.get("new_password") or "")
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="새 비밀번호는 8자 이상이어야 합니다.")
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    db.commit()
    return {"ok": True}


@router.post("/users/{udj_user_id}/delete", dependencies=[Depends(require_partner)])
def partner_delete_user(udj_user_id: int, payload: dict, db: Session = Depends(get_db)):
    """탈퇴. 기록해가 자기 쪽 자료를 먼저 지운 뒤 이곳을 부른다.

    계정이 한 곳에만 있으므로, 여기서 지우면 두 서비스 모두에서 로그인할 수 없다.
    """
    import sys
    # 이 모듈이 속한 패키지의 main 을 정확히 집는다.
    # 'app' 이라는 이름의 패키지가 두 서비스에 모두 있어, 상대 임포트만으로는
    # 다른 서비스의 main 을 잡을 수 있다.
    udj_main = sys.modules[__package__ + ".main"]

    user = db.get(User, udj_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
    if not verify_password(str(payload.get("password") or ""), user.password_hash):
        raise HTTPException(status_code=400, detail="비밀번호가 일치하지 않습니다.")

    class _Body:
        password = str(payload.get("password") or "")

    return udj_main.delete_my_account(payload=_Body(), db=db, user=user)


# ── 선생님 계정 관리 (기록해 화면에서 대신 호출) ──────────────────
# 계정 원본이 여기(UDJ) 뿐이라, 기록해에 화면을 옮겨도 실제 role·school_id
# 변경은 여기서만 할 수 있다. 아래 4개는 예전에 SchoolAdmin.jsx(UDJ 자체
# 화면)에 있던 것과 같은 로직이다 — 그 화면은 없앴고, 기록해 화면이 이
# API 를 통해 같은 일을 한다.


def _teacher_out(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "class_name": u.class_name or "",
        "is_active": u.is_active,
        "created_at": u.created_at,
    }


@router.get("/schools/{school_id}/teachers", dependencies=[Depends(require_partner)])
def partner_list_teachers(school_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(User)
        .filter(User.school_id == school_id, User.role == Role.teacher)
        .order_by(User.class_name, User.name)
        .all()
    )
    return [_teacher_out(t) for t in rows]


@router.get("/schools/{school_id}/teacher-candidates", dependencies=[Depends(require_partner)])
def partner_search_teacher_candidates(
    school_id: int, q: str, db: Session = Depends(get_db)
):
    """선생님 권한을 줄 대상을 찾는다. 이미 가입한 계정을 아이디·이름·연락처로 검색."""
    term = (q or "").strip()
    if len(term) < 2:
        raise HTTPException(status_code=400, detail="2글자 이상 입력해주세요.")
    rows = (
        db.query(User)
        .filter(
            User.role.in_([Role.student, Role.teacher]),
            # SQL 의 IN 은 NULL 을 절대 못 맞힌다(school_id IS NULL 인 학생도
            # 후보여야 하므로 이 조건만 따로 뺀다) — in_([None, school_id]) 로
            # 쓰면 school_id 가 없는 계정이 통째로 검색에서 빠지는 버그가 된다.
            or_(User.role == Role.teacher, User.school_id.is_(None), User.school_id == school_id),
            or_(
                User.email.ilike(f"%{term}%"),
                User.name.ilike(f"%{term}%"),
                User.phone.ilike(f"%{term}%"),
            ),
        )
        .limit(20)
        .all()
    )
    return [
        {
            "id": u.id,
            "email": u.email,
            "name": u.name,
            "phone": u.phone or "",
            "role": u.role.value,
            "class_name": u.class_name or "",
            "is_our_teacher": u.role == Role.teacher and u.school_id == school_id,
            "other_school": u.role == Role.teacher and u.school_id not in (None, school_id),
        }
        for u in rows
    ]


@router.post("/schools/{school_id}/teachers/grant", dependencies=[Depends(require_partner)])
def partner_grant_teacher(school_id: int, payload: dict, db: Session = Depends(get_db)):
    """이미 가입한 계정에 이 학교의 선생님 권한을 부여한다."""
    from .main import school_has_perk

    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")
    if not school_has_perk(db, school, "teacher_accounts"):
        raise HTTPException(
            status_code=403,
            detail="선생님 계정 발급은 현재 플랜에서 제공하지 않습니다. 플랜을 확인해주세요.",
        )
    target = db.get(User, payload.get("user_id"))
    if not target:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
    if target.role in (Role.admin, Role.school):
        raise HTTPException(status_code=400, detail="관리자·학교 계정에는 부여할 수 없습니다.")
    if target.role == Role.teacher and target.school_id not in (None, school_id):
        raise HTTPException(status_code=400, detail="다른 학교의 선생님으로 등록된 계정입니다.")

    target.role = Role.teacher
    target.school_id = school_id
    target.class_name = str(payload.get("class_name") or "").strip()[:40]
    target.must_change_password = False
    db.commit()
    return {"ok": True, "teacher": _teacher_out(target)}


@router.put("/schools/{school_id}/teachers/{teacher_id}", dependencies=[Depends(require_partner)])
def partner_update_teacher(
    school_id: int, teacher_id: int, payload: dict, db: Session = Depends(get_db)
):
    """담당 학급 변경 / 활성·정지."""
    t = db.get(User, teacher_id)
    if not t or t.school_id != school_id or t.role != Role.teacher:
        raise HTTPException(status_code=404, detail="선생님 계정을 찾을 수 없습니다.")
    if payload.get("class_name") is not None:
        t.class_name = str(payload["class_name"]).strip()[:40]
    if payload.get("is_active") is not None:
        t.is_active = bool(payload["is_active"])
    db.commit()
    return {"ok": True, "teacher": _teacher_out(t)}


@router.delete("/schools/{school_id}/teachers/{teacher_id}", dependencies=[Depends(require_partner)])
def partner_revoke_teacher(school_id: int, teacher_id: int, db: Session = Depends(get_db)):
    """선생님 권한만 해제한다. 계정 자체는 남기고 일반 사용자로 되돌린다."""
    t = db.get(User, teacher_id)
    if not t or t.school_id != school_id or t.role != Role.teacher:
        raise HTTPException(status_code=404, detail="선생님 계정을 찾을 수 없습니다.")
    t.role = Role.student
    t.school_id = None
    t.class_name = ""
    db.commit()
    return {"ok": True}
