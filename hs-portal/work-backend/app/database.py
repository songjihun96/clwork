"""데이터베이스 연결.

**표는 우리 것만 만든다.** 여기 `Base` 는 이 서비스 전용이라, 같은
PostgreSQL 을 쓰더라도 `create_all` 이 건드리는 표는 `work_*` 뿐이다.
우리동네 직업계고의 표는 이 프로세스가 존재조차 모른다.

DATABASE_URL 이 없으면 로컬 SQLite 로 떨어진다. **운영에서 이러면 빈 DB 에
붙어서 "아무 기록도 없음"처럼 보인다** — 2026-09-13 에 실제로 그 사고가
났으므로, 기동할 때 어느 쪽에 붙었는지 로그로 남긴다.
"""

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        # 사내 인원이 쓰는 도구라 크게 잡을 이유가 없다. UDJ 쪽이 쓸 연결을
        # 남겨 둬야 하므로 일부러 작게 둔다(PostgreSQL max_connections 공유).
        pool_size=5,
        max_overflow=5,
        pool_recycle=1800,
    )
    _where = DATABASE_URL.split("@")[-1]
else:
    DB_FILE = Path(__file__).resolve().parent.parent / "work.db"
    engine = create_engine(f"sqlite:///{DB_FILE}",
                           connect_args={"check_same_thread": False})
    _where = f"SQLite {DB_FILE}"

print(f"[우리업무] DB: {_where}", file=sys.stderr, flush=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
