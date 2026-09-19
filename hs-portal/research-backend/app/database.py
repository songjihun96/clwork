"""연구·논문 서비스의 자체 데이터베이스.

기록해(diary)와도, UDJ 와도 **완전히 다른 DB** 다. 계정도 여기서 직접
만들고 확인한다 — 나중에 별도 사이트로 세울 것이라, 처음부터 어디에도
기대지 않게 둔다.

환경변수는 RESEARCH_DATABASE_URL 을 쓴다. DATABASE_URL 을 그대로 쓰면
같은 서버에서 기록해와 나란히 띄울 때 서로의 DB 를 가리키게 된다.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("RESEARCH_DATABASE_URL", "").strip()

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
    DB_FILE = Path(__file__).resolve().parent.parent / "research.db"
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
