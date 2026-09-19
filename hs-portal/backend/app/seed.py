"""
첫 관리자 계정을 만든다. 학교 데이터는 import_neis.py 로 따로 수집한다.

    cd backend
    python -m app.seed

비밀번호는 환경변수로 넘길 수 있다.
    ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=... python -m app.seed
"""

import os
import sys

from .auth import hash_password
from .database import Base, SessionLocal, engine
from .models import Role, School, User


def main() -> int:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        email = os.getenv("ADMIN_EMAIL", "admin@school-portal.kr")
        password = os.getenv("ADMIN_PASSWORD", "admin12345")

        if db.query(User).filter(User.role == Role.admin).first():
            print("관리자 계정이 이미 있습니다.")
        else:
            db.add(
                User(
                    email=email,
                    password_hash=hash_password(password),
                    name="포털 관리자",
                    role=Role.admin,
                )
            )
            db.commit()
            print(f"관리자 계정을 만들었습니다: {email}")
            if password == "admin12345":
                print("기본 비밀번호를 쓰고 있습니다. 로그인 후 반드시 바꾸세요.")

        # 데모 학생 계정
        if not db.query(User).filter(User.email == "student@example.com").first():
            db.add(
                User(
                    email="student@example.com",
                    password_hash=hash_password("student12345"),
                    name="김학생",
                    role=Role.student,
                )
            )
            db.commit()
            print("데모 학생 계정: student@example.com / student12345")

        count = db.query(School).count()
        if count == 0:
            print("\n학교 데이터가 아직 없습니다. 아래를 실행해 NEIS에서 받아오세요:")
            print("    python -m app.import_neis --majors")
        else:
            print(f"\n등록된 학교 {count}개")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
