"""
데이터베이스 연결.

로컬에서는 SQLite 파일을, 실제 서버에서는 PostgreSQL을 쓴다.
환경변수 DATABASE_URL 이 있으면 그걸 쓰고, 없으면 로컬 SQLite로 떨어진다.

  - 로컬:  (설정 없음) -> sqlite:///./school_portal.db
  - 서버:  DATABASE_URL=postgresql://user:pw@host:5432/dbname

네이버 클라우드 등에서 PostgreSQL을 쓰려면 DATABASE_URL 만 넣으면 된다.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if DATABASE_URL:
    # 일부 제공자는 'postgres://' 로 주는데 SQLAlchemy는 'postgresql://' 를 원한다.
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    # 커넥션 풀. gunicorn 워커 3개 기준 최대 3 x (10+20) = 90 개까지 열릴 수 있으므로
    # PostgreSQL 의 max_connections(기본 100)를 넘지 않도록 여유를 두고 잡는다.
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,   # 끊긴 커넥션을 미리 걸러낸다
        pool_size=10,
        max_overflow=20,
        pool_recycle=1800,    # 30분마다 재연결(방화벽·DB 타임아웃 대비)
    )
else:
    # 로컬 개발용 SQLite.
    # 상대경로("./school_portal.db")를 쓰면 프로세스를 어느 디렉터리에서 띄웠는지에
    # 따라 다른 파일을 보게 되어, 서비스 재시작·배포 후 데이터가 사라진 것처럼 보인다.
    # 항상 backend/ 아래의 같은 파일을 가리키도록 절대경로로 고정한다.
    DB_FILE = Path(__file__).resolve().parent.parent / "school_portal.db"
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
