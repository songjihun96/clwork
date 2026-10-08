"""2026-10 마이그레이션: 학교급(중·고) · 공지사항 개편 · 공지 알림.

    python -m app.migrate_2026_10_notices status      # 무엇이 적용됐는지 확인
    python -m app.migrate_2026_10_notices upgrade     # 적용(여러 번 돌려도 안전)
    python -m app.migrate_2026_10_notices downgrade   # 되돌리기(새 칸·새 표 삭제)

이 프로젝트는 alembic 을 쓰지 않는다. 서버를 다시 켜면 main.py 의 _ensure_columns
와 create_all 이 같은 일을 하므로 **보통은 upgrade 를 따로 돌릴 필요가 없다.**
이 파일은 (1) 배포 전에 미리 적용·확인하거나 (2) 문제가 생겼을 때 되돌리는 용도다.

**기존 데이터**
  · schools.school_level      : 기존 학교는 모두 'high'(NEIS 고등학교 목록에서 온 학교)
  · school_account_requests   : 기존 신청은 모두 'high'
  · notices                   : 기존 공지는 '게시된 게시판 공지'(status=published, kind=board)
                                메일·문자 알림은 꺼진 상태 → 배포만으로 아무것도 발송되지 않는다
  새 표 school_contacts · notification_logs 는 비어서 시작한다.

**downgrade 주의** — 새로 만든 중학교 학교·중학교 계정 자체는 지우지 않는다(계정
데이터 보호). 칸만 지우므로 되돌린 뒤에는 중학교 계정이 고등학교 계정처럼 보인다.
되돌리기 전에 관리자 화면에서 중학교 계정을 정지해 두는 것을 권한다.
"""
from __future__ import annotations

import sys

from sqlalchemy import inspect, text

from .database import engine

NEW_COLUMNS = {
    "schools": {
        "school_level": "VARCHAR(10) NOT NULL DEFAULT 'high'",
        "notice_email": "VARCHAR(120) DEFAULT ''",
        "notice_email_enabled": "BOOLEAN NOT NULL DEFAULT {TRUE}",
    },
    "school_account_requests": {
        "school_level": "VARCHAR(10) NOT NULL DEFAULT 'high'",
        "region": "VARCHAR(20) DEFAULT ''",
        "notice_consent": "BOOLEAN NOT NULL DEFAULT {FALSE}",
    },
    "notices": {
        "kind": "VARCHAR(12) NOT NULL DEFAULT 'board'",
        "category": "VARCHAR(12) NOT NULL DEFAULT 'notice'",
        "status": "VARCHAR(10) NOT NULL DEFAULT 'published'",
        "published_at": "{TS}",
        "target_level": "VARCHAR(10) NOT NULL DEFAULT 'all'",
        "email_enabled": "BOOLEAN NOT NULL DEFAULT {FALSE}",
        "sms_enabled": "BOOLEAN NOT NULL DEFAULT {FALSE}",
        "updated_at": "{TS}",
    },
}
NEW_TABLES = ("notification_logs", "school_contacts")   # 지울 때는 이 순서(외래키)


def _ddl(sql: str) -> str:
    pg = engine.dialect.name == "postgresql"
    return (sql.replace("{TRUE}", "TRUE" if pg else "1")
               .replace("{FALSE}", "FALSE" if pg else "0")
               .replace("{TS}", "TIMESTAMP" if pg else "DATETIME"))


def status() -> dict:
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    out = {"tables": {t: t in tables for t in NEW_TABLES}, "columns": {}}
    for table, cols in NEW_COLUMNS.items():
        have = {c["name"] for c in insp.get_columns(table)} if table in tables else set()
        out["columns"][table] = {c: c in have for c in cols}
    return out


def upgrade() -> None:
    from .models import NotificationLog, SchoolContact  # noqa: F401 (메타데이터 등록)
    from .database import Base
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, cols in NEW_COLUMNS.items():
            if table not in tables:
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for col, ddl in cols.items():
                if col not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {_ddl(ddl)}"))
                    print(f"  + {table}.{col}")
    Base.metadata.create_all(bind=engine, tables=[
        Base.metadata.tables[t] for t in ("school_contacts", "notification_logs")])
    print("  + 표 school_contacts, notification_logs (없으면 만듦)")
    # 표가 먼저 만들어져 있었다면(동의 칸을 넣기 전 버전) 칸을 보탠다.
    insp = inspect(engine)
    have = {c["name"] for c in insp.get_columns("school_contacts")}
    with engine.begin() as conn:
        for col, ddl in (("consent_at", "{TS}"), ("consent_source", "VARCHAR(10) DEFAULT ''")):
            if col not in have:
                conn.execute(text(f"ALTER TABLE school_contacts ADD COLUMN {col} {_ddl(ddl)}"))
                print(f"  + school_contacts.{col}")


def downgrade() -> None:
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for t in NEW_TABLES:
            if t in tables:
                conn.execute(text(f"DROP TABLE {t}"))
                print(f"  - 표 {t}")
        for table, cols in NEW_COLUMNS.items():
            if table not in tables:
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for col in cols:
                if col in have:
                    # SQLite 3.35+ 와 PostgreSQL 모두 DROP COLUMN 을 지원한다.
                    if engine.dialect.name == "sqlite":
                        conn.execute(text(f"DROP INDEX IF EXISTS ix_{table}_{col}"))
                    conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {col}"))
                    print(f"  - {table}.{col}")


def main(argv) -> int:
    cmd = argv[1] if len(argv) > 1 else "status"
    if cmd == "upgrade":
        upgrade()
    elif cmd == "downgrade":
        downgrade()
    elif cmd != "status":
        print(__doc__)
        return 1
    st = status()
    for t, ok in st["tables"].items():
        print(f"표 {t}: {'있음' if ok else '없음'}")
    for table, cols in st["columns"].items():
        print(f"{table}: " + ", ".join(f"{c}{'' if ok else '(없음)'}" for c, ok in cols.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
