"""테스트용 계정을 만든다. 학생·선생님·학교 계정을 모두 다룬다.

    python -m app.make_test_accounts --check
    python -m app.make_test_accounts --school 262 --password test12345
    python -m app.make_test_accounts --role student --school 262 --teacher tea@x.kr
    python -m app.make_test_accounts --delete

기본값(--role 없음)은 학교 하나에 **선생님 → 학생** 순으로 한 벌을 만들고
서로 연결까지 해준다. 교사 화면에서 학생 일지가 보이는지 바로 확인할 수 있다.

보안 관련
  - 비밀번호는 무작위로 만들어 한 번만 보여준다. --password 로 정할 수도 있다.
  - API 가 아니라 CLI 로만 만들 수 있다. 서버에 접속할 수 있어야 실행된다.
  - 실제 사람의 계정이 아니므로 휴대폰 인증 없이 만들어진다.
    테스트가 끝나면 --delete 로 정리할 것.
"""

import argparse
import secrets
import string
import sys
from datetime import date, datetime

from .auth import hash_password
from .database import Base, SessionLocal, engine
from .models import (
    CoverLetter, Favorite, JournalEntry, QuizTaken, Role, School,
    SchoolVerification, Subscription, User,
)

# 한눈에 알아보도록 같은 도메인을 쓴다. 실제 도메인과 겹치지 않아야 한다.
EMAILS = {
    "student": "teststudent@udjschool.kr",
    "teacher": "testteacher@udjschool.kr",
    "school": "testschool@udjschool.kr",
}
NAMES = {"student": "테스트학생", "teacher": "테스트선생님", "school": "테스트학교담당"}

# 여러 벌을 만들 때 쓰는 꼬리표. 2번째 벌은 teststudent2@... 가 된다.
# 꼬리표가 없으면(1번째 벌) 예전 그대로라 기존 계정을 이어서 쓴다.


def suffixed(email: str, token: str) -> str:
    """이메일 뒤에 꼬리표를 붙인다. 꼬리표가 없으면 원래 주소 그대로다."""
    if not token:
        return email
    local, _, domain = email.partition("@")
    # 점을 넣어 'teststudents1' 처럼 붙어 읽기 어려워지는 것을 막는다.
    return f"{local}.{token}@{domain}"


def make_token(school_id, n: int) -> str:
    """계정을 서로 구분하는 꼬리표.

    학교를 여러 곳 지정하면 학교 ID 를 붙인다. 학교마다 계정이 따로
    생겨야 서로 소속을 빼앗지 않는다.
    같은 학교에서 여러 벌을 만들면 그 뒤에 번호를 더한다.

    학교를 하나만 쓰고 한 벌만 만들면 꼬리표가 없다. 예전에 쓰던
    계정을 그대로 이어 쓰기 위해서다.
    """
    parts = []
    if school_id is not None:
        parts.append(f"s{school_id}")
    if n > 1:
        parts.append(str(n))
    return "".join(parts)


def set_emails(role: str, token: str) -> str:
    return suffixed(EMAILS[role], token)


def next_free_set(db) -> int:
    """아직 안 쓴 번호를 찾는다.

    같은 명령을 다시 돌리면 기존 계정의 소속만 바뀌어, 학교를 바꿔가며
    시험할 때 앞서 만든 계정이 망가졌다. 그래서 부르는 쪽이 번호를 주지
    않으면 비어 있는 다음 번호로 새로 만든다.
    """
    for n in range(1, 100):
        used = any(
            db.query(User).filter(User.email == set_emails(role, n)).first()
            for role in EMAILS
        )
        if not used:
            return n
    return 1


def all_test_emails(db) -> list:
    """지금까지 만든 테스트 계정을 모두 찾는다.

    번호가 몇 번까지 갔는지 모르므로 이메일 모양으로 찾는다.
    """
    out = []
    for base in EMAILS.values():
        local, _, domain = base.partition("@")
        rows = db.query(User).filter(User.email.like(f"{local}%@{domain}")).all()
        out.extend(rows)
    return out
ROLE_LABEL = {"student": "학생", "teacher": "선생님", "school": "학교", "admin": "관리자"}


def random_password(length: int = 14) -> str:
    """읽고 옮겨 적기 쉬운 문자만 쓴다."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def show_status(db) -> int:
    """세 계정이 지금 어떤 상태인지 보여준다. 아무것도 바꾸지 않는다."""
    print("─" * 52)
    rows = all_test_emails(db)
    if not rows:
        print("  만들어 둔 테스트 계정이 없습니다.")
        print("─" * 52)
        return 0
    for user in sorted(rows, key=lambda u: u.email):
        role = user.role.value if user.role else ""
        email = user.email
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print(f"  {ROLE_LABEL[role]:5s}  (없음)   {email}")
            continue

        bits = [f"권한 {user.role.value}"]
        if not user.is_active:
            bits.append("정지됨")
        if user.school_id:
            s = db.get(School, user.school_id)
            bits.append(f"학교 {s.name if s else user.school_id}")

        if role == "student":
            v = (
                db.query(SchoolVerification)
                .filter(SchoolVerification.user_id == user.id)
                .order_by(SchoolVerification.id.desc())
                .first()
            )
            if v:
                s = db.get(School, v.school_id)
                tea = db.get(User, v.teacher_id) if v.teacher_id else None
                bits.append(f"인증 {v.status}" + (f" · {s.name}" if s else ""))
                if tea:
                    bits.append(f"담당 {tea.name}")
            n = db.query(JournalEntry).filter(JournalEntry.user_id == user.id).count()
            if n:
                bits.append(f"일지 {n}건")

        print(f"  {ROLE_LABEL[role]:5s}  {email}")
        print(f"         {' · '.join(bits)}")
    print("─" * 52)
    print("비밀번호를 모르면 아래로 새로 발급하세요.")
    print("  python -m app.make_test_accounts --password test12345")
    return 0


def delete_all(db) -> None:
    # 번호가 붙은 것(teststudent2@...)까지 모두 찾는다.
    for user in all_test_emails(db):
        role = user.role.value if user.role else "student"
        uid = user.id
        # 이 계정이 남긴 자료를 먼저 지운다. 외래키가 걸려 있어 순서를 지켜야 한다.
        for model, col in [
            (JournalEntry, JournalEntry.user_id), (CoverLetter, CoverLetter.user_id),
            (Subscription, Subscription.user_id), (QuizTaken, QuizTaken.user_id),
            (Favorite, Favorite.user_id),
        ]:
            try:
                db.query(model).filter(col == uid).delete(synchronize_session=False)
            except Exception:
                db.rollback()
        # 이 교사가 승인한 다른 학생의 인증은 연결만 끊는다.
        db.query(SchoolVerification).filter(
            SchoolVerification.teacher_id == uid
        ).update({SchoolVerification.teacher_id: None}, synchronize_session=False)
        db.query(SchoolVerification).filter(
            SchoolVerification.user_id == uid
        ).delete(synchronize_session=False)
        db.delete(user)
        print(f"  {ROLE_LABEL.get(role, role)} 계정 삭제: {user.email}")
    db.commit()


def upsert(db, role: str, school: School, password: str, args, token: str = "") -> tuple:
    """계정을 만들거나, 이미 있으면 비밀번호만 새로 발급한다.

    token 은 계정을 구분하는 꼬리표다. 비어 있으면 예전 이메일 그대로라
    쓰던 계정을 이어서 쓰고, 값이 있으면 새 계정이 된다.
    """
    email = getattr(args, "email", None) or set_emails(role, token)
    user = db.query(User).filter(User.email == email).first()
    created = user is None

    if created:
        name = args.name or NAMES[role] + (f"({token})" if token else "")
        user = User(email=email, name=name, role=Role(role))
        db.add(user)

    user.password_hash = hash_password(password)
    user.is_active = True
    user.role = Role(role)
    user.privacy_consent_at = user.privacy_consent_at or datetime.utcnow()

    if role == "student":
        # 만 17세. 결제 화면에서 미성년자 동의 절차까지 확인할 수 있다.
        user.birth_date = user.birth_date or date(2009, 3, 2)
        user.phone = user.phone or "01000000001"
    elif role == "teacher":
        user.phone = user.phone or "01000000002"
        user.class_name = user.class_name or "2학년 3반"
        if school:
            user.school_id = school.id
    elif role == "school":
        user.phone = user.phone or "01000000003"
        if school:
            user.school_id = school.id

    db.commit()
    db.refresh(user)
    return user, created


def link_student(db, student: User, school: School, teacher: User) -> None:
    """재학생 인증을 승인 상태로 만들어 교사-학생을 연결한다."""
    if not school:
        return
    v = (
        db.query(SchoolVerification)
        .filter(SchoolVerification.user_id == student.id,
                SchoolVerification.school_id == school.id)
        .first()
    )
    if not v:
        v = SchoolVerification(user_id=student.id, school_id=school.id)
        db.add(v)
    v.status = "approved"
    v.decided_at = datetime.utcnow()
    if teacher:
        v.teacher_id = teacher.id
        v.class_name = teacher.class_name or ""
    db.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="테스트용 계정 생성 (학생·선생님·학교)")
    parser.add_argument("--role", choices=["student", "teacher", "school"],
                        help="한 종류만 만든다. 없으면 세 계정을 한 벌로 만든다")
    parser.add_argument("--email", help="이메일을 직접 정한다(--role 과 함께 쓸 때)")
    parser.add_argument("--name", help="이름을 직접 정한다")
    parser.add_argument("--school", type=int, help="연결할 학교 ID")
    parser.add_argument("--schools",
                        help="여러 학교에 한 벌씩. 쉼표로 구분 (예: 12,34,56)")
    parser.add_argument("--teacher", help="담당 교사 이메일 (학생만 만들 때 연결용)")
    parser.add_argument("--password", help="비밀번호를 직접 정한다(8자 이상)")
    parser.add_argument("--check", action="store_true", help="상태만 보고 아무것도 바꾸지 않는다")
    parser.add_argument("--delete", action="store_true", help="테스트 계정을 모두 지운다")
    parser.add_argument("--set", type=int,
                        help="몇 번째 벌인지 직접 정한다. 주지 않으면 비어 있는 번호로 새로 만든다")
    parser.add_argument("--reuse", action="store_true",
                        help="새로 만들지 않고 1번째 벌을 다시 쓴다(비밀번호만 재발급)")
    parser.add_argument("--count", type=int, default=1,
                        help="한 번에 만들 벌 수. --set 부터 이어서 만든다")
    args = parser.parse_args()

    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        if args.check:
            return show_status(db)
        if args.delete:
            delete_all(db)
            return 0
        if args.password and len(args.password) < 8:
            print("비밀번호는 8자 이상이어야 합니다.")
            return 1

        # 학교를 여러 곳 지정하면 학교마다 한 벌씩 만든다.
        school_ids = []
        if args.schools:
            for chunk in args.schools.replace(" ", "").split(","):
                if not chunk:
                    continue
                if not chunk.isdigit():
                    print(f"학교 ID 는 숫자여야 합니다: {chunk}")
                    return 1
                school_ids.append(int(chunk))
        elif args.school:
            school_ids.append(args.school)

        schools = []
        for sid in school_ids:
            sc = db.get(School, sid)
            if not sc:
                print(f"학교 ID {sid} 을(를) 찾지 못했습니다.")
                return 1
            schools.append(sc)

        if not schools:
            schools = [None]
            print("경고: 학교를 주지 않아 학교 연결과 재학생 인증을 건너뜁니다.")
            print("      교사 화면에서 학생 일지를 보려면 학교가 필요합니다.\n")

        school = schools[0]

        roles = [args.role] if args.role else ["teacher", "school", "student"]
        count = max(1, args.count)
        start = max(1, args.set) if args.set is not None else 1

        # 여러 벌을 만들 때 이메일을 직접 정하면 서로 겹친다.
        if count > 1 and args.email:
            print("--count 와 --email 은 함께 쓸 수 없습니다. 이메일이 겹칩니다.")
            return 1

        all_made = []
        for sc in schools:
            for k in range(start, start + count):
                # 학교마다 계정을 따로 만든다. 같은 계정의 소속만 바꾸면
                # 앞서 만들어 둔 학교의 시험 환경이 망가진다.
                # --reuse 를 주면 예전처럼 한 벌을 이어서 쓴다.
                token = "" if args.reuse else make_token(sc.id if sc else None, k)
                password = args.password or random_password()
                made = []
                teacher_user = None
                for role in roles:
                    user, created = upsert(db, role, sc, password, args, token)
                    made.append((role, user, created))
                    if role == "teacher":
                        teacher_user = user
                all_made.append((sc, k, password, made, teacher_user))

        # 아래 안내는 마지막 벌 기준으로 이어진다.
        school, k, password, made, teacher_user = all_made[-1]

        # 학생만 따로 만들 때는 --teacher 로 지정한 교사에 붙인다.
        if args.role == "student" and args.teacher:
            teacher_user = db.query(User).filter(
                User.email == args.teacher, User.role == Role.teacher).first()
            if not teacher_user:
                print(f"경고: 교사 '{args.teacher}' 를 찾지 못했습니다.")

        for sc, kk, pw, mm, tt in all_made:
            st = next((u for r, u, _ in mm if r == "student"), None)
            if st and sc:
                link_student(db, st, sc, tt)
        student = next((u for r, u, _ in made if r == "student"), None)

        print()
        for sc, kk, pw, mm, tt in all_made:
            if len(all_made) > 1:
                where = f"{sc.name} (ID {sc.id})" if sc else "학교 없음"
                print(f"[{where} · {kk}번째 벌]")
            for role, user, created in mm:
                print(f"{'만듦' if created else '갱신'}  {ROLE_LABEL[role]:5s}  {user.email}")
            print(f"  비밀번호   {pw}")
            if len(all_made) > 1:
                print()
        print("─" * 52)
        if school:
            print(f"  학교       {school.name} (ID {school.id})")
            if student:
                print(f"  재학생 인증 승인 완료"
                      + (f" · 담당 {teacher_user.name}" if teacher_user else ""))
        print("─" * 52)
        print("  우리동네 직업계고   https://udjschool.ggm.kr")
        print("  기록해              https://diary.ggm.kr")
        print()
        print("비밀번호는 지금만 보입니다. 잊으면 이 명령을 다시 실행하세요.")
        print("정리하려면:  python -m app.make_test_accounts --delete")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
