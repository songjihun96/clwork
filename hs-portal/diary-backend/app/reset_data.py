"""기록해 데이터 초기화.

    python -m app.reset_data --scope diary_journals --yes
    python -m app.reset_data --scope diary_all --yes

계정은 UDJ 에 있으므로 이곳에서 지워도 로그인은 계속 된다. 다음 로그인 때
사본이 다시 만들어진다. 그래서 '전체 초기화' 도 계정을 없애지는 못한다.

되돌릴 수 없다. 반드시 백업 후 실행할 것.
"""

import argparse
import sys

from .database import Base, SessionLocal, engine
from .models import (
    AuditLog, CoverLetter, JournalEntry, SchoolSeat, SchoolSubject, SeatCode,
    SeatHolder, SeatOrder, Setting, Subscription, SubscriptionOrder,
    UnmatchedDeposit, User,
)

SCOPES = {
    "diary_journals": "일지·일기만 삭제",
    "diary_seats": "이용권만 초기화(좌석·코드·신청)",
    "diary_all": "전체 초기화(계정 사본 포함, 설정은 유지)",
}


def wipe_seats(db) -> None:
    """이용권 관련 표를 지운다.

    학생에게 준 좌석을 먼저 지우고 학교 좌석을 지운다. 순서를 뒤집으면
    남은 좌석이 어느 학교 것인지 알 수 없는 상태가 잠깐 생긴다.
    """
    wipe(db, SeatHolder, "학생에게 준 좌석")
    wipe(db, SeatCode, "등록 코드")
    wipe(db, SchoolSeat, "학교 좌석")
    wipe(db, SeatOrder, "이용권 신청")
    wipe(db, UnmatchedDeposit, "미매칭 입금")
    # 결제 주체가 학교로 바뀌기 전의 개인 구독. 남아 있으면 함께 지운다.
    wipe(db, Subscription, "예전 개인 구독")
    wipe(db, SubscriptionOrder, "예전 개인 결제")


def wipe(db, model, label: str) -> None:
    n = db.query(model).delete(synchronize_session=False)
    print(f"  {label}: {n}건 삭제")


def main() -> int:
    parser = argparse.ArgumentParser(description="기록해 데이터 초기화")
    parser.add_argument("--scope", required=True, choices=sorted(SCOPES))
    parser.add_argument("--yes", action="store_true", help="확인 없이 실행")
    args = parser.parse_args()

    if not args.yes:
        print("되돌릴 수 없는 작업입니다. --yes 를 붙여야 실행됩니다.")
        return 1

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        print(f"[기록해] {SCOPES[args.scope]}")

        if args.scope == "diary_journals":
            wipe(db, JournalEntry, "일지·일기")

        elif args.scope == "diary_seats":
            wipe_seats(db)
            print("  일지·자기소개서는 그대로 둡니다.")

        elif args.scope == "diary_all":
            wipe(db, JournalEntry, "일지·일기")
            wipe(db, CoverLetter, "자기소개서")
            wipe_seats(db)
            wipe(db, SchoolSubject, "과목 목록")
            wipe(db, AuditLog, "활동 기록")
            # 계정 사본은 지워도 UDJ 에서 다시 받아온다. 남은 참조가 없으므로 함께 지운다.
            wipe(db, User, "계정 사본")
            print("  설정(구독가·계좌)은 그대로 둡니다.")

        db.commit()
        print("완료했습니다.")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"실패: {exc}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
