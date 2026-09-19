"""
reset-data.bat 이 부르는 데이터 초기화 메뉴.

배치 파일은 ASCII만 담을 수 있어(한국어 Windows가 CP949로 읽어 한글이 깨진다)
한글 안내와 확인 절차는 여기서 처리한다.

지우는 범위를 세 가지로 나눈다:
  1. 계정만      : 학생/학교 계정, 즐겨찾기, 플랜신청 삭제. 학교·관리자·좌표 유지.
  2. 학교도 함께  : 위 + 학교 전체 삭제. 관리자만 남는다. (NEIS 재수집 필요)
  3. 완전 초기화  : DB 파일을 통째로 지운다. start.bat 재실행 때 처음부터.
"""

import sys
from pathlib import Path

from sqlalchemy import func

from .database import SessionLocal, engine
from .models import (
    AdminAuditLog, CoverLetter, CsDevice, Favorite, GuardianConsent, Notice,
    NoticeRead, PlanGrant, PlanOrder, QuizDemand, Role, School,
    SchoolExposure, Subscription,
    SubscriptionOrder, User,
)

DB_PATH = Path(__file__).resolve().parent.parent / "school_portal.db"
# SQLite면 파일 삭제(4번)가 가능하지만, PostgreSQL 등에선 파일이 없다.
IS_SQLITE = engine.dialect.name == "sqlite"


def counts(db):
    from .models import Plan

    return {
        "학교": db.query(School).count(),
        "└ 유료 플랜 학교": db.query(School).filter(School.plan != Plan.free).count(),
        "학생 계정": db.query(User).filter(User.role == Role.student).count(),
        "학교 계정": db.query(User).filter(User.role == Role.school).count(),
        "즐겨찾기": db.query(Favorite).count(),
        "플랜 신청": db.query(PlanOrder).count(),
        "누적 조회수": int(
            db.query(func.coalesce(func.sum(School.view_count), 0)).scalar() or 0
        ),
    }


def show_counts(db):
    print("  현재 데이터:")
    for k, v in counts(db).items():
        print(f"    - {k}: {v}개")
    print()


def confirm(prompt: str) -> bool:
    try:
        ans = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return ans in ("y", "yes", "예", "ㅇ")


def clear_accounts_and_content(db) -> None:
    """학교와 관리자는 남기고 나머지를 지운다.

    users 를 지우기 전에 users 를 참조하는 자식 행을 모두 정리해야 한다.
    (PostgreSQL 은 외래키가 엄격해 하나라도 남으면 삭제가 막힌다)
    """
    from .models import (
        Inquiry, JournalEntry, PasswordReset, QuizTaken, SchoolVerification,
    )

    db.query(Favorite).delete()
    # 학생이 쓴 일지와 재학생 인증 기록
    db.query(JournalEntry).delete()
    db.query(SchoolVerification).delete()
    # 진로 테스트 참여 기록은 통계라 남기고 사용자 연결만 끊는다
    db.query(QuizTaken).update({QuizTaken.user_id: None}, synchronize_session=False)
    db.query(PlanOrder).delete()
    # 비밀번호 재설정 기록은 임시 인증용이라 통째로 지운다.
    # (PostgreSQL은 외래키가 엄격해 남아있으면 계정 삭제가 막힌다)
    db.query(PasswordReset).delete()
    # 계정에 딸린 자료를 먼저 지운다. 하나라도 남으면 외래키에 걸려
    # 계정 삭제가 통째로 실패한다. 지울 때마다 여기에 더해야 한다.
    for model in (CoverLetter, Subscription, SubscriptionOrder,
                  GuardianConsent, NoticeRead, CsDevice):
        db.query(model).delete(synchronize_session=False)

    doomed_ids = [
        u.id for u in db.query(User).filter(User.role != Role.admin).all()
    ]
    if doomed_ids:
        # 지우기 아까운 것들은 연결만 끊는다.
        # 문의 답변, 공지 글쓴이, 무상 플랜 지급자, 감사 로그가 그렇다.
        for model, col in (
            (Inquiry, Inquiry.answered_by),
            (Notice, Notice.author_id),
            (PlanGrant, PlanGrant.granted_by),
            (AdminAuditLog, AdminAuditLog.actor_id),
        ):
            db.query(model).filter(col.in_(doomed_ids)).update(
                {col: None}, synchronize_session=False)

    # 관리자를 뺀 모든 계정(학생·교사·학교·상담원) 삭제
    db.query(User).filter(User.role != Role.admin).delete(synchronize_session=False)
    db.commit()


def clear_schools(db) -> None:
    """학교와 그에 딸린 것들을 지운다. 학교 계정의 연결도 끊는다.
    query.delete()는 벌크 삭제라 ORM cascade를 타지 않으므로
    학교를 참조하는 자식 테이블을 직접 지운다."""
    from .models import (
        AdmissionEvent, Article, Inquiry, SchoolVerification, SchoolView,
    )

    # 학교 계정의 연결을 먼저 끊는다
    db.query(User).filter(User.role == Role.school).update(
        {User.school_id: None}, synchronize_session=False
    )
    # 학교를 참조하는 모든 자식 삭제
    db.query(Favorite).delete()
    db.query(PlanOrder).delete()
    db.query(AdmissionEvent).delete()
    db.query(Inquiry).delete()
    db.query(SchoolView).delete()
    db.query(SchoolVerification).delete()
    # 기사는 학교 참조를 끊고 남긴다(기사 자체는 유지할 수 있게).
    # 학교가 사라지면 매칭이 깨지므로 school_id만 비운다.
    db.query(Article).update({Article.school_id: None}, synchronize_session=False)
    db.query(School).delete()
    db.commit()


def reset_plans(db) -> None:
    """모든 학교의 플랜을 무료로 되돌리고, 만료일과 신청 내역을 지운다.
    학교 정보·좌표·계정은 그대로 둔다."""
    from .models import Plan

    db.query(School).update(
        {School.plan: Plan.free, School.plan_expires_at: None}
    )
    db.query(PlanOrder).delete()
    db.commit()


def reset_views(db) -> None:
    """학교 조회수를 0으로 되돌리고 조회 기록을 지운다.
    학교 정보·계정·플랜은 그대로 둔다. (메인 인기 랭킹도 함께 초기화됨)"""
    from .models import SchoolView

    db.query(SchoolView).delete()
    db.query(School).update({School.view_count: 0}, synchronize_session=False)
    db.commit()


def clear_all_but_schools_and_admin(db) -> None:
    """학교 기본정보·위치정보와 관리자 계정만 남기고 전부 초기화한다.

    남는 것 : 학교의 NEIS 기본정보(이름·계열·지역·주소·연락처·좌표 등), 관리자 계정,
              크롤링해 둔 신문 기사
    지우는 것: 학생/학교/선생님 계정, 즐겨찾기, 일지, 재학생 인증,
              문의, 입시·설명회 일정, 플랜 신청, 조회 기록,
              진로 테스트 참여 기록
    되돌리는 것: 학교 계정이 입력한 상세정보(소개·학과·시설 등), SMTP 설정,
              플랜(무료), 조회수(0), 노출 상태(노출)
    """
    from .models import (
        AdmissionEvent, Inquiry, JournalEntry, PasswordReset, Plan,
        QuizTaken, SchoolVerification, SchoolView,
    )

    # 1) 자식 테이블부터 정리 (users/schools 를 참조하는 것들)
    # 기사(Article)는 다시 수집하기 번거로우므로 지우지 않는다
    for model in (
        JournalEntry, SchoolVerification, QuizTaken, Favorite,
        PlanOrder, PasswordReset, Inquiry, AdmissionEvent, SchoolView,
        # 노출·수요 집계도 학교를 참조한다.
        SchoolExposure, QuizDemand,
        # 계정을 참조하는 것들. 하나라도 빠지면 계정 삭제가 통째로 막힌다.
        CoverLetter, Subscription, SubscriptionOrder, GuardianConsent,
        NoticeRead, CsDevice, PlanGrant, Notice,
    ):
        db.query(model).delete()
    # 감사 로그는 남기되 사람 연결만 끊는다. 누가 무엇을 했는지는
    # 기록으로 남아 있어야 한다.
    db.query(AdminAuditLog).update({AdminAuditLog.actor_id: None},
                                   synchronize_session=False)
    db.commit()

    # 2) 관리자를 뺀 모든 계정 삭제
    db.query(User).filter(User.role != Role.admin).delete(synchronize_session=False)
    # 관리자에 남아있을 수 있는 학교 연결도 끊는다
    db.query(User).update({User.school_id: None}, synchronize_session=False)
    db.commit()

    # 3) 학교는 남기되, 학교 계정이 채웠던 내용과 과금·노출 상태를 되돌린다
    db.query(School).update(
        {
            # 학교 계정이 직접 입력한 상세 정보
            School.slogan: "",
            School.intro: "",
            School.departments: "",
            School.facilities: "",
            School.admission_info: "",
            School.employment_rate: None,
            School.student_count: None,
            School.established_year: None,
            School.hero_image: "",
            # 문의 답변용 SMTP 설정
            School.mail_host: "",
            School.mail_port: 587,
            School.mail_username: "",
            School.mail_password_enc: "",
            School.mail_from: "",
            School.mail_ssl: False,
            # 노출·과금
            School.plan: Plan.free,
            School.plan_expires_at: None,
            School.plan_paused: False,
            School.is_visible: True,
            School.view_count: 0,
        },
        synchronize_session=False,
    )
    db.commit()


def paid_plan_count(db) -> int:
    from .models import Plan

    return db.query(School).filter(School.plan != Plan.free).count()


def main() -> int:
    print()
    print("  ==========================================")
    print("    데이터 초기화")
    print("  ==========================================")
    print()

    if IS_SQLITE and not DB_PATH.exists():
        print("  데이터베이스가 아직 없습니다. start.bat 을 먼저 실행하세요.")
        return 0

    db = SessionLocal()
    try:
        show_counts(db)
        print("  무엇을 할까요?")
        print()
        print("    1. 플랜만 초기화")
        print("       (모든 학교를 무료 플랜으로 되돌리고 플랜신청 내역 삭제)")
        print("       학교 정보·좌표·계정은 그대로 둡니다.")
        print()
        print("    2. 계정 지우기")
        print("       (학생/학교 계정, 즐겨찾기, 플랜신청 삭제)")
        print("       학교 정보와 좌표, 관리자 계정은 그대로 둡니다.")
        print()
        print("    3. 학교까지 함께 지우기")
        print("       (위 + 학교 전체 삭제. 관리자만 남음)")
        print("       다시 채우려면 update-schools.bat 을 실행해야 합니다.")
        print()
        print("    4. 완전 초기화")
        if IS_SQLITE:
            print("       (DB 파일을 통째로 삭제. start.bat 재실행 때 처음부터 새로 만듭니다)")
        else:
            print("       (서버 DB의 모든 데이터를 비웁니다. 관리자 포함. 표 구조는 유지)")
        print()
        print("    0. 취소")
        print()

        try:
            choice = input("  번호를 고르세요 (0-4): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  취소했습니다.")
            return 0

        if choice == "1":
            print()
            print("  [1] 모든 학교를 무료 플랜으로 되돌리고 플랜신청 내역을 지웁니다.")
            print(f"      현재 유료 플랜 학교: {paid_plan_count(db)}개")
            if not confirm("  정말 초기화할까요? (y/n): "):
                print("  취소했습니다.")
                return 0
            reset_plans(db)
            print("\n  완료했습니다. 모든 학교가 무료 플랜이 되었습니다.")
            show_counts(db)

        elif choice == "2":
            print()
            print("  [2] 학교 기본정보·좌표와 관리자만 남기고 전부 지웁니다.")
            print("      (계정·일지·문의·일정·조회기록 등 / 기사는 보존)")
            if not confirm("  정말 지울까요? (y/n): "):
                print("  취소했습니다.")
                return 0
            clear_all_but_schools_and_admin(db)
            print("\n  완료했습니다.")
            show_counts(db)

        elif choice == "3":
            print()
            print("  [3] 학교를 포함해 계정을 모두 지웁니다. 관리자만 남습니다.")
            print("      학교를 다시 받으려면 update-schools.bat 을 실행해야 합니다.")
            if not confirm("  정말 지울까요? (y/n): "):
                print("  취소했습니다.")
                return 0
            clear_accounts_and_content(db)
            clear_schools(db)
            print("\n  완료했습니다.")
            show_counts(db)

        elif choice == "4":
            print()
            if IS_SQLITE:
                print("  [4] DB 파일을 통째로 삭제합니다. 관리자 계정도 사라집니다.")
                print("      start.bat 을 다시 실행하면 처음부터 새로 만듭니다.")
                if not confirm("  정말 삭제할까요? (y/n): "):
                    print("  취소했습니다.")
                    return 0
                db.close()
                DB_PATH.unlink()
                print("\n  DB 파일을 삭제했습니다. 이제 start.bat 을 실행하세요.")
                return 0
            else:
                # PostgreSQL 등 서버 DB: 파일 삭제 개념이 없다.
                # 모든 데이터를 비우되(관리자 포함), 표 구조는 남긴다.
                print("  [4] 서버 DB의 모든 데이터를 비웁니다. (관리자 계정 포함)")
                print("      표 구조는 남으며, 백엔드 재시작이나 seed로 관리자를 다시 만들 수 있습니다.")
                print("      되돌릴 수 없으니 미리 pg_dump 백업을 권장합니다.")
                if not confirm("  정말 모두 비울까요? (y/n): "):
                    print("  취소했습니다.")
                    return 0
                from .models import AdmissionEvent, PasswordReset, SchoolView, Inquiry, Article
                for model in [Favorite, PlanOrder, AdmissionEvent,
                              PasswordReset, SchoolView, Inquiry, Article, School, User]:
                    try:
                        db.query(model).delete()
                    except Exception:
                        pass
                db.commit()
                print("\n  모든 데이터를 비웠습니다.")
                print("  관리자 계정을 다시 만들려면: .venv/bin/python -m app.seed")
                return 0

        else:
            print("  취소했습니다.")
            return 0

        return 0
    finally:
        db.close()


# ------------------------------------------------------------------
# 비대화형(CLI) 모드 — 보조 도구가 SSH로 실행할 때 쓴다.
#   python -m app.reset_data --scope plans   --yes
#   python -m app.reset_data --scope accounts --yes
#   python -m app.reset_data --scope schools  --yes
#   python -m app.reset_data --scope all      --yes
#   python -m app.reset_data --status         (지우지 않고 현황만 출력)
# ------------------------------------------------------------------
SCOPE_LABEL = {
    "views": "조회수만 초기화",
    "plans": "플랜만 초기화",
    "accounts": "학교·관리자 빼고 전체 초기화",
    "schools": "학교까지 삭제",
    "all": "완전 초기화",
}


def run_scope(db, scope: str) -> None:
    if scope == "views":
        reset_views(db)
    elif scope == "plans":
        reset_plans(db)
    elif scope == "accounts":
        clear_all_but_schools_and_admin(db)
    elif scope == "schools":
        clear_accounts_and_content(db)
        clear_schools(db)
    elif scope == "all":
        from .models import (
            AdmissionEvent, Article, Inquiry, JournalEntry, PasswordReset,
            QuizTaken, SchoolVerification, SchoolView, Setting,
        )
        # 자식 테이블부터 지운 뒤 부모(schools, users)를 지운다
        order = [
            JournalEntry, SchoolVerification, QuizTaken, Favorite,
            PlanOrder, AdmissionEvent, PasswordReset, SchoolView, Inquiry,
            Article, School, User,
        ]
        for model in order:
            try:
                db.query(model).delete()
                db.commit()
            except Exception as exc:
                db.rollback()
                print(f"  [건너뜀] {model.__tablename__}: {exc.__class__.__name__}")
    else:
        raise ValueError(f"알 수 없는 범위: {scope}")


def cli() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="데이터 초기화 (비대화형)")
    ap.add_argument("--scope", choices=list(SCOPE_LABEL))
    ap.add_argument("--yes", action="store_true", help="확인 없이 즉시 실행")
    ap.add_argument("--status", action="store_true", help="현황만 출력")
    args = ap.parse_args()

    if not args.status and not args.scope:
        return main()  # 인자가 없으면 기존 대화형 메뉴

    db = SessionLocal()
    try:
        if args.status:
            for k, v in counts(db).items():
                print(f"{k}: {v}")
            return 0

        if not args.yes:
            print("실행하려면 --yes 를 함께 주세요. (되돌릴 수 없습니다)")
            return 1

        print(f"[초기화 시작] {SCOPE_LABEL[args.scope]}")
        print("--- 실행 전 ---")
        for k, v in counts(db).items():
            print(f"  {k}: {v}")

        run_scope(db, args.scope)

        print("--- 실행 후 ---")
        for k, v in counts(db).items():
            print(f"  {k}: {v}")
        print("[초기화 완료]")
        if args.scope == "all":
            print("관리자 계정을 다시 만들려면: python -m app.seed")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(cli())
