"""기록해 자체 데이터베이스.

UDJ 와 완전히 다른 DB 를 쓴다. 계정만 UDJ 에서 확인하고, 일지·자소서·구독은
모두 이곳에 저장한다.
"""

import os
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
        # AI 워커 스레드/프로세스를 늘리면 동시에 열리는 DB 커넥션도 늘어난다 —
        # 트래픽이 커지면 .env 의 DB_POOL_SIZE/DB_MAX_OVERFLOW 만 올리면 된다.
        pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")),
        pool_recycle=1800,
    )
else:
    # 로컬 개발용. 실행 위치와 무관하게 같은 파일을 보도록 절대경로로 고정한다.
    DB_FILE = Path(__file__).resolve().parent.parent / "diary.db"
    engine = create_engine(
        f"sqlite:///{DB_FILE}",
        connect_args={"check_same_thread": False},
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
