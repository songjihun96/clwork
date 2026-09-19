"""학교에 전달할 계정을 학교별로 한 벌씩 만든다(학교 1 + 학생 2).

    python -m app.make_school_accounts --dry-run     # 무엇을 만들지 확인만
    python -m app.make_school_accounts               # 실제 생성 + 자격증명 출력
    python -m app.make_school_accounts --reset-password   # 이미 있는 계정 비번 재발급
    python -m app.make_school_accounts --only 동의고등학교       # 한 학교만

나중에 학교를 한 곳 더 열 때는 --only 를 꼭 쓴다. 그냥 다시 돌리면 계정은
건드리지 않지만 **플랜은 목록의 모든 학교에 다시 지급되어** 남은 기간에
개월 수가 그대로 더 얹힌다(예: 15곳이 6개월씩 또 늘어난다).

make_test_accounts.py 와 목적이 다르다. 그쪽은 개발자가 혼자 쓰는 임시
계정이고, 이 스크립트는 **실제 학교에 전달할 계정**을 만든다. 그래서
  - 학교마다 계정을 따로 만들고(이메일에 학교 ID 를 넣어 겹치지 않게)
  - 비밀번호는 계정마다 다르게 무작위로 만들며
  - 이미 있는 계정은 건드리지 않는다(이미 전달한 비밀번호가 바뀌면 안 되므로).
    다시 발급해야 하면 --reset-password 로 명시해야 한다.

학생 계정은 재학생 인증(SchoolVerification)을 승인 상태로 함께 넣는다.
그래야 그 학교 소속 학생으로 잡히고, 기록해(diary)에서도 같은 학교로 보인다.
"""

import argparse
import secrets
import string
import sys
from datetime import date, datetime, timedelta

from .auth import hash_password
from .database import SessionLocal
from .models import Plan, PLAN_RANK, PlanGrant, Role, School, SchoolVerification, User

# 계정을 만들 학교. 정식 명칭이 아니어도 되고, 부분 일치로 찾는다.
SCHOOL_NAMES = [
    "경기관광고등학교",
    "선일빅데이터고등학교",
    "부산정보고등학교",
    "충북비즈니스고등학교",
    "대진전자통신고등학교",
    "경화여자English Business고등학교",  # 통용 명칭: 경화EB고등학교
    "한국도예고등학교",
    "곤지암고등학교",
    "경북공업고등학교",
    "경주디자인고등학교",
    "영남공업고등학교",
    "사천여자고등학교",
    "예일메디텍고등학교",
    "글로벌학산고등학교",
    "논산여자상업고등학교",
    "동의고등학교",
    "마장고등학교",
]

# 정식 명칭과 통용 명칭이 많이 다른 학교의 검색 별칭.
# 학교 계정은 못 고치고 운영자만 넣는 값이다(상담 콘솔에서도 수정 가능).
ALIASES = {
    "경화여자English Business고등학교": "경화EB고등학교,경화여자EB고등학교,경화EB고",
    # 예전 이름(동의공업고등학교)으로 찾는 사람이 아직 많다. 이름이 바뀐
    # 학교는 옛 이름을 별칭에 넣어 둬야 검색에서 사라지지 않는다.
    "동의고등학교": "동의공업고등학교,동의공업고,동의공고",
}

PLAN_LABEL = {"platinum": "플래티넘", "premium": "프리미엄", "basic": "베이직", "free": "무료"}

EMAIL_DOMAIN = "udjschool.kr"
STUDENTS_PER_SCHOOL = 2


def random_password(length: int = 12) -> str:
    """읽고 옮겨 적기 쉬운 문자만 쓴다(0/O, 1/l 같은 혼동 글자 제외)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def find_school(db, wanted: str):
    """이름으로 학교를 찾는다. 정확히 하나로 좁혀지지 않으면 만들지 않는다."""
    exact = db.query(School).filter(School.name == wanted).all()
    if len(exact) == 1:
        return exact[0], ""
    if len(exact) > 1:
        return None, f"같은 이름의 학교가 {len(exact)}곳 있습니다(ID: {[s.id for s in exact]})"

    like = db.query(School).filter(School.name.ilike(f"%{wanted.strip()}%")).all()
    if len(like) == 1:
        return like[0], ""
    if len(like) > 1:
        names = ", ".join(f"{s.name}(#{s.id})" for s in like[:5])
        return None, f"이름이 여러 곳과 겹칩니다: {names}"
    return None, "이 이름으로 찾을 수 없습니다"


def upsert_account(db, *, email, name, role, school_id, reset_password, fixed_password=""):
    """계정을 만든다. 이미 있으면 그대로 두고 (created=False, password=None) 를 돌려준다."""
    user = db.query(User).filter(User.email == email).first()
    if user and not reset_password:
        return user, False, None

    password = fixed_password or random_password()
    if user is None:
        user = User(email=email, name=name, role=role)
        db.add(user)
        created = True
    else:
        created = False

    user.password_hash = hash_password(password)
    user.name = name
    user.role = role
    user.is_active = True
    user.privacy_consent_at = user.privacy_consent_at or datetime.utcnow()
    if role == Role.school:
        user.school_id = school_id
    elif role == Role.student:
        # 학생 계정은 학교를 school_id 가 아니라 재학생 인증으로 잡는다.
        user.birth_date = user.birth_date or date(2009, 3, 2)
    db.flush()
    return user, created, password


def link_student(db, student: User, school_id: int) -> None:
    """재학생 인증을 승인 상태로 넣는다. 이미 있으면 그대로 둔다."""
    v = (
        db.query(SchoolVerification)
        .filter(
            SchoolVerification.user_id == student.id,
            SchoolVerification.school_id == school_id,
        )
        .first()
    )
    if v:
        if v.status != "approved":
            v.status = "approved"
            v.decided_at = datetime.utcnow()
        return
    db.add(
        SchoolVerification(
            user_id=student.id,
            school_id=school_id,
            status="approved",
            note="포털 운영자가 만든 계정",
            decided_at=datetime.utcnow(),
        )
    )


def grant_plan(db, school: School, plan: Plan, months: int, reason: str):
    """학교에 플랜을 무상으로 준다(관리자 지급과 같은 방식).

    돈을 내고 쓰는 학교는 건드리지 않는다. 무상 지급으로 덮으면 남은
    유료 기간이 사라지고, 매출 집계도 어긋나기 때문이다.
    """
    today = date.today()
    paying = (
        school.plan != Plan.free
        and not school.plan_is_free_trial
        and school.plan_expires_at
        and school.plan_expires_at >= today
    )
    if paying:
        return None, f"결제 중인 학교({PLAN_RANK and school.plan.value})라 건너뜀"

    has_time_left = bool(school.plan_expires_at and school.plan_expires_at >= today)
    base = school.plan_expires_at if (
        has_time_left and PLAN_RANK[school.plan] >= PLAN_RANK[plan]
    ) else today
    expires = base + timedelta(days=30 * months)

    school.plan = plan if PLAN_RANK[plan] >= PLAN_RANK[school.plan] else school.plan
    school.plan_expires_at = expires
    school.plan_paused = False
    school.plan_is_free_trial = True          # 매출로 잡히면 안 되는 무상 제공
    school.plan_granted_note = reason[:200]

    db.add(PlanGrant(
        school_id=school.id, school_name=school.name[:120],
        plan=plan, months=months, starts_on=today, expires_on=expires,
        reason=reason[:200], granted_by=None, granted_by_email="(스크립트)",
    ))
    return expires, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="학교만 찾아보고 아무것도 만들지 않는다")
    ap.add_argument("--reset-password", action="store_true",
                    help="이미 있는 계정의 비밀번호를 다시 발급한다")
    ap.add_argument("--plan", default="platinum",
                    choices=[p.value for p in Plan],
                    help="학교에 무상으로 줄 플랜(기본 platinum). free 면 안 준다.")
    ap.add_argument("--plan-months", type=int, default=6,
                    help="플랜 제공 개월 수(기본 6개월)")
    ap.add_argument("--only", nargs="+", default=None,
                    help="목록 중 이 학교들만 처리한다(부분 일치). 학교를 한 곳 "
                         "추가할 때 쓴다 — 나머지 학교의 플랜이 또 연장되는 것을 막는다.")
    ap.add_argument("--password", default="",
                    help="모든 계정에 같은 비밀번호를 쓴다(비공개 베타용). "
                         "비우면 계정마다 무작위로 만든다.")
    args = ap.parse_args()

    if args.password and len(args.password) < 8:
        print("비밀번호는 8자 이상이어야 합니다.")
        return 1

    targets = SCHOOL_NAMES
    if args.only:
        targets = [n for n in SCHOOL_NAMES
                   if any(k in n for k in args.only)]
        # 목록에 없는 이름을 줬으면 그대로 찾아본다. 목록에 넣는 걸 깜빡해도
        # 계정은 만들 수 있게 한다.
        for k in args.only:
            if not any(k in n for n in SCHOOL_NAMES):
                targets = targets + [k]
        if not targets:
            print("--only 로 지정한 학교가 없습니다.")
            return 1
        print(f"--only: {', '.join(targets)}")

    db = SessionLocal()
    found, missing = [], []
    for wanted in targets:
        school, why = find_school(db, wanted)
        if school:
            found.append((wanted, school))
        else:
            missing.append((wanted, why))

    print("=" * 72)
    print(f"찾은 학교 {len(found)}곳 / 못 찾은 학교 {len(missing)}곳")
    print("=" * 72)
    for wanted, school in found:
        note = "" if school.name == wanted else f"  (입력: {wanted})"
        print(f"  #{school.id:<5} {school.name} · {school.region}{note}")
    for wanted, why in missing:
        print(f"  [건너뜀] {wanted} — {why}")

    if missing:
        print()
        print("※ 못 찾은 학교는 계정을 만들지 않습니다. 이름을 확인해 다시 실행하세요.")

    if args.dry_run:
        print("\n--dry-run 이라 아무것도 만들지 않았습니다.")
        db.close()
        return 0

    if not found:
        db.close()
        return 1

    rows = []       # (학교명, 역할, 이메일, 비밀번호 or 안내)
    alias_set = []
    plan_rows = []  # (학교명, 만료일 or 건너뛴 사유)
    want_plan = Plan(args.plan)
    for _wanted, school in found:
        if want_plan != Plan.free:
            expires, why = grant_plan(
                db, school, want_plan, args.plan_months,
                f"비공개 베타 참여 학교 {args.plan_months}개월 무상 제공",
            )
            plan_rows.append((school.name, f"{expires} 까지" if expires else why))

        # 검색 별칭
        alias = ALIASES.get(school.name) or ALIASES.get(_wanted)
        if alias and (school.search_aliases or "") != alias:
            school.search_aliases = alias
            alias_set.append((school.name, alias))

        user, created, pw = upsert_account(
            db, email=f"school-{school.id}@{EMAIL_DOMAIN}",
            name=f"{school.name} 담당자", role=Role.school,
            school_id=school.id, reset_password=args.reset_password,
            fixed_password=args.password,
        )
        rows.append((school.name, "학교", user.email, pw or "(이미 있음 — 비번 유지)"))

        for n in range(1, STUDENTS_PER_SCHOOL + 1):
            stu, created, pw = upsert_account(
                db, email=f"student-{school.id}-{n}@{EMAIL_DOMAIN}",
                name=f"{school.name} 학생{n}", role=Role.student,
                school_id=school.id, reset_password=args.reset_password,
                fixed_password=args.password,
            )
            link_student(db, stu, school.id)
            rows.append((school.name, f"학생{n}", stu.email, pw or "(이미 있음 — 비번 유지)"))

    db.commit()

    if plan_rows:
        print()
        print(f"{PLAN_LABEL.get(want_plan.value, want_plan.value)} 플랜 적용:")
        for name, note in plan_rows:
            print(f"  {name} — {note}")

    if alias_set:
        print()
        print("검색 별칭을 넣었습니다:")
        for name, alias in alias_set:
            print(f"  {name} → {alias}")

    print()
    print("=" * 72)
    print("만든 계정 (이 표를 안전한 곳에 보관하고, 학교에 전달하세요)")
    print("=" * 72)
    print(f"{'학교':<24} {'역할':<6} {'이메일':<34} 비밀번호")
    print("-" * 72)
    for name, role, email, pw in rows:
        print(f"{name[:22]:<24} {role:<6} {email:<34} {pw}")
    print("-" * 72)
    if args.password:
        print(f"모든 계정의 비밀번호: {args.password}")
        print("※ 이메일이 학교 ID 로 유추되는 형식이라, 비공개 베타가 끝나면")
        print("   --reset-password 로 계정마다 다른 비밀번호를 다시 발급하세요.")
    else:
        print("비밀번호는 다시 볼 수 없습니다. 지금 복사해 두세요.")
    print("전달받은 학교는 로그인 후 '내 정보'에서 비밀번호를 바꾸도록 안내해 주세요.")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
