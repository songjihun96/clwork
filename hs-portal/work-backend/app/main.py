"""우리업무 — 기동 지점.

    gunicorn app.main:app -k uvicorn.workers.UvicornWorker -b 127.0.0.1:8300

**한 프로세스 안에 이것만 있다.** 우리동네 직업계고·기록해·상담 코드는
여기 없다. 그래서 이 서비스를 재시작해도 그쪽은 아무 영향이 없다.
"""

import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine
from . import models  # noqa: F401  (표를 등록하려면 import 가 필요하다)
from . import work
from . import visits
from . import settlement
from . import payroll

app = FastAPI(title="우리업무 API", version="1.0.0", docs_url=None, redoc_url=None)

# 새 표는 이게 만들어 준다. 이미 있으면 건드리지 않는다.
Base.metadata.create_all(bind=engine)


def _add_missing_columns() -> None:
    """이미 만들어진 표에 뒤늦게 늘린 칸을 붙인다.

    `create_all` 은 **없는 표만** 만든다. 이미 있는 표에 컬럼을 더해 주지는
    않으므로, 새 칸을 추가하고 배포하면 그 칸만 조용히 없는 채로 돈다 —
    그러다 처음 읽는 순간 터진다. 여기서 한 번 맞춰 둔다.

    (표가 몇 개뿐이라 이 정도면 충분하다. 더 복잡해지면 alembic 을 쓴다.)
    """
    import sqlalchemy as sa
    want = {
        "work_attendance": [
            ("left_at", "TIMESTAMP"),
            ("auto_closed", "BOOLEAN DEFAULT FALSE"),
            ("edited_by", "INTEGER"),
            ("edited_at", "TIMESTAMP"),
        ],
        "work_orgs": [
            ("visit_sites", "TEXT"),
        ],
        "work_visit_daily": [
            ("excluded", "INTEGER DEFAULT 0"),
            ("rule", "INTEGER DEFAULT 1"),
        ],
    }
    insp = sa.inspect(engine)
    with engine.begin() as conn:
        for table, cols in want.items():
            if not insp.has_table(table):
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for name, sqltype in cols:
                if name in have:
                    continue
                conn.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {name} {sqltype}"))
                print(f"[우리업무] 칸 추가: {table}.{name}", file=sys.stderr, flush=True)


_add_missing_columns()

# 화면과 API 가 같은 도메인(workwoori.ggm.kr)이라 보통은 CORS 가 필요 없다.
# 로컬에서 화면만 따로 띄워 볼 때를 위해 열어 둘 수 있게만 해 둔다.
_origins = [o.strip() for o in os.getenv("WORK_ALLOWED_ORIGINS", "").split(",") if o.strip()]
if _origins:
    app.add_middleware(
        CORSMiddleware, allow_origins=_origins, allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )

app.include_router(work.router)
app.include_router(visits.router)
app.include_router(settlement.router)
app.include_router(payroll.router)


@app.on_event("startup")
def _startup() -> None:
    # 관리자가 하나도 없을 때만 .env 의 값으로 첫 계정을 만든다.
    work.ensure_first_admin()
    # 지난 날 방문 수를 로그에서 접어 둔다(10분마다, 워커 하나만).
    visits.start_collector()


@app.get("/api/work/health")
def health():
    """살아 있는지 확인하는 자리. 감시 도구와 UptimeRobot 이 여기를 찌른다."""
    return {"ok": True, "service": "work"}
