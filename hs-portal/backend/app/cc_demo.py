"""전화 상담 데모 서버.

실제 전화 없이 상담원 3명의 순차분배를 눈으로 확인하려고 쓴다.

    backend/.venv/Scripts/python -m app.cc_demo

하는 일

  1. 별도 파일(backend/cc_demo.db)에 데모 DB 를 만든다.
     운영·개발 DB(school_portal.db)는 건드리지 않는다.
  2. 상담원 3명과 관리자, 고객 몇 명을 넣는다.
  3. 이 PC(127.0.0.1)를 사무실 IP 로 등록해 기기 승인 없이 바로 들어가게 한다.
     데모 DB 안에서만 통하는 설정이다.
  4. 8000 포트로 서버를 띄운다. frontend-cs 의 vite 프록시가 보는 포트다.

로그인
    cs1@demo.kr / demo1234!   김상담 (1순위)
    cs2@demo.kr / demo1234!   이상담 (2순위)
    cs3@demo.kr / demo1234!   박상담 (3순위)
    admin@demo.kr / demo1234! 관리자

세 명을 각각 다른 브라우저 창(또는 시크릿 창)으로 열어 로그인하면,
[테스트 전화 걸기] 로 만든 전화가 순서대로 넘어가는 것을 볼 수 있다.
"""

import os
from pathlib import Path

DEMO_DB = Path(__file__).resolve().parent.parent / "cc_demo.db"

# 반드시 app.main 을 불러오기 전에 정해야 한다. database.py 가 import 시점에
# 엔진을 만들기 때문이다.
os.environ["DATABASE_URL"] = f"sqlite:///{DEMO_DB.as_posix()}"
os.environ.setdefault("SECRET_KEY", "demo-only-key-not-for-production-0123456789")
os.environ.setdefault("PHONE_PROVIDER", "mock")
os.environ.setdefault("ENV", "development")

from .auth import hash_password           # noqa: E402
from .callcenter import engine            # noqa: E402
from .database import SessionLocal        # noqa: E402
from .models import CsCustomer, Role, Setting, User  # noqa: E402

DEMO_PASSWORD = "demo1234!"

PEOPLE = [
    ("김상담", "cs1@demo.kr", Role.cs, "상담팀", "주임", "101"),
    ("이상담", "cs2@demo.kr", Role.cs, "상담팀", "사원", "102"),
    ("박상담", "cs3@demo.kr", Role.cs, "상담팀", "사원", "103"),
    ("관리자", "admin@demo.kr", Role.admin, "운영팀", "팀장", "100"),
]

CUSTOMERS = [
    ("홍길동", "01012345678", "STUDENT", "양주공업고등학교"),
    ("김선생", "01023456789", "TEACHER", "의정부공업고등학교"),
    ("서울전자고", "0212345678", "SCHOOL", "서울전자고등학교"),
]


def seed() -> None:
    db = SessionLocal()
    try:
        for index, (name, email, role, dept, position, ext) in enumerate(PEOPLE):
            user = db.query(User).filter(User.email == email).first()
            if user is None:
                user = User(email=email, name=name, role=role,
                            password_hash=hash_password(DEMO_PASSWORD), is_active=True)
                db.add(user)
                db.commit()
                db.refresh(user)
            profile = engine.ensure_profile(db, user)
            profile.department = dept
            profile.position = position
            profile.extension = ext
            profile.ring_order = (index + 1) * 10
            # 관리자는 통화 큐에서 빼둔다. 승인 업무를 하다가 전화를 받게 되면
            # 곤란하다. 필요하면 전화 설정 화면에서 켤 수 있다.
            profile.accepts_calls = role is not Role.admin
            profile.availability_status = "OFFLINE"
        db.commit()

        for name, phone, ctype, school in CUSTOMERS:
            if db.query(CsCustomer).filter(CsCustomer.phone_number == phone).first():
                continue
            db.add(CsCustomer(name=name, phone_number=phone,
                              customer_type=ctype, school_name=school))
        db.commit()

        # 이 데모 DB 안에서만 통하는 설정. 기기 승인 절차를 건너뛰기 위해서다.
        row = db.get(Setting, "cs_office_ips")
        if row is None:
            db.add(Setting(key="cs_office_ips", value="127.0.0.1,::1"))
        else:
            row.value = "127.0.0.1,::1"
        db.commit()
    finally:
        db.close()


def main() -> None:
    import uvicorn

    from .main import app  # noqa: F401  (import 시점에 표를 만든다)

    seed()
    print()
    print(f"  데모 DB   {DEMO_DB}")
    print(f"  Provider  {os.environ['PHONE_PROVIDER']} (실제 전화망 아님 · 음성 안 흐름)")
    print("  로그인    cs1@demo.kr / cs2@demo.kr / cs3@demo.kr / admin@demo.kr")
    print(f"  비밀번호  {DEMO_PASSWORD}")
    print()
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
