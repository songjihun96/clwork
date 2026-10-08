"""정산 — 매출 명세, 우리동네 소프트 / 협력사 배분, 직원 인센티브.

**계산 순서 (2026-09-15 대표와 정한 기준)**

    매출 − 환불 = 순매출
    순매출 × 60% = 협력사 몫          ← 협력사 대표
    순매출 − 협력사 몫 = 우리 몫       ← 우리동네 소프트 대표 (40%)
    우리 몫 × 1% = 직원 1인 인센티브  (1인당 월 300만원까지, 직원 각자)
    우리 몫 − 인센티브 합계 = 우리동네 소프트에 남는 금액

비율과 상한은 관리자 화면에서 바꿀 수 있다. **마감한 달은 마감 시점의 비율로
고정된다** — 규칙을 바꿔도 이미 지급한 달의 숫자가 따라 바뀌지 않게.

**원 단위 반올림.** 협력사 몫을 먼저 반올림으로 정하고 우리 몫은 나머지로 둔다.
둘을 각각 반올림하면 합이 순매출과 1원 어긋날 수 있다. 인센티브는 내림이다 —
지급액을 부풀리는 쪽으로 반올림하지 않는다.

**결제 유형(2026-09-27).** 매출 줄마다 개인·학교·우등직·영상·기타 중 하나를
붙인다. 어느 결제 기록이 어느 유형인지는 DEFAULT_PTYPE 이 정하고, 관리자가
정산 규칙에서 바꿀 수 있다(ptype_map). 토스 **테스트 키로 승인된 결제**
(is_test)는 돈이 오가지 않았으므로 매출에서 빼고 따로 센다.

**매출 원본은 두 사이트의 결제 기록이다.** 이 서비스는 그 DB 를 **읽기만** 한다.
표 구조를 import 하지 않고 SQL 로 필요한 칸만 읽는 건, 이 프로세스가 두 백엔드와
분리돼 있어서다. 대신 칸 이름이 바뀌면 여기도 고쳐야 한다(아래 SOURCES).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, create_engine, inspect, or_, text
from sqlalchemy.orm import Session

from .database import engine as work_engine, get_db
from .models import (WorkLedgerEntry, WorkOrg, WorkSetting, WorkSettlement,
                     WorkUser)
from .work import admin_only, current_user

router = APIRouter(prefix="/api/work", tags=["settlement"])

KST = timedelta(hours=9)

# 결제 유형. 키는 DB·주소에 그대로 들어가므로 함부로 바꾸지 않는다.
PAYMENT_TYPES = {
    "personal": "개인 결제",
    "school": "학교 결제",
    "udj": "우등직 결제",
    "video": "영상 결제",
    "other": "기타 결제",
}

# 결제 기록(출처)마다 기본 결제 유형. 관리자가 정산 규칙에서 바꿀 수 있다.
DEFAULT_PTYPE = {
    "udj_plan": "udj",        # 우리동네 직업계고 학교 노출 플랜
    "udj_sub": "udj",         # 우리동네 직업계고 구독
    "udj_app": "udj",         # 컨설팅·상담 등 유료 신청
    "udj_video": "video",     # 합격생 영상
    "diary_sub": "personal",  # 기록해 개인 이용권
    "diary_seat": "school",   # 기록해 학교 이용권(좌석)
}

DEFAULTS = {
    "ptype_map": "",               # {출처: 결제 유형} JSON. 비면 DEFAULT_PTYPE
    "partner_org_id": "",          # 60% 를 받는 협력사
    "partner_pct": "60",           # 협력사 몫(%)
    "incentive_pct": "1",          # 우리 몫의 몇 % 를 직원 1인에게
    "incentive_cap": "3000000",    # 1인당 월 상한(원)
}


# ─────────────────────────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────────────────────────

def get_settings(db: Session) -> dict:
    out = dict(DEFAULTS)
    for row in db.query(WorkSetting).filter(WorkSetting.key.in_(list(DEFAULTS))).all():
        out[row.key] = row.value
    return out


def _num(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
# 결제 기록 읽기
# ─────────────────────────────────────────────────────────────────────────────

def _engine_for(env_key: str, fallback_to_work: bool):
    url = (os.getenv(env_key, "") or "").strip()
    if not url:
        return work_engine if fallback_to_work else None
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=0)


# 우리동네 직업계고 DB 는 이 서비스와 같은 DB 라 따로 안 적으면 그걸 쓴다.
# 기록해는 DB 가 따로라 주소를 넣어야 읽는다. 안 넣으면 화면에 그렇게 알린다.
_ENGINES = {
    "udj": _engine_for("SALES_UDJ_DATABASE_URL", fallback_to_work=True),
    "diary": _engine_for("SALES_DIARY_DATABASE_URL", fallback_to_work=False),
}

SITE_NAME = {"udj": "우리동네 직업계고", "diary": "기록해"}

# (출처 키, DB, 설명, 매출 SQL, 환불 SQL 또는 None)
#   매출: 금액·기준시각(UTC)·참고. 환불: 금액·환불시각(UTC)·참고.
#   :a ~ :b 는 조회 구간(UTC).
#   {TEST} 는 테스트 결제 표시 칸(is_test)을 읽는 자리다. 그 칸이 아직 없는
#   DB(백엔드가 새 칸을 만들기 전)면 비워서 예전처럼 읽는다 — TEST_TABLES 참고.
#   status 는 DB 마다 enum/문자열이 달라 문자열로 바꿔 비교한다.
SOURCES: List[Tuple[str, str, str, str, Optional[str]]] = [
    # 결제 금액은 한 번에 들어온다. 12개월 플랜이면 결제한 달에 12개월치 전액이 잡힌다.
    # 명세에 몇 개월짜리인지(plan·months)를 같이 보여 준다.
    ("udj_plan", "udj", "학교 플랜",
     """SELECT p.id, p.amount, p.paid_at AS at, COALESCE(s.name, '') || ' #' || p.id AS ref,
               CAST(p.plan AS TEXT) AS plan, p.months AS months
        FROM plan_orders p LEFT JOIN schools s ON s.id = p.school_id
        WHERE p.paid_at >= :a AND p.paid_at < :b
          AND CAST(p.status AS TEXT) IN ('paid', 'approved')""",
     None),
    ("udj_sub", "udj", "구독",
     """SELECT id, amount, paid_at AS at, 'order #' || id AS ref, months{TEST} FROM subscription_orders
        WHERE paid_at >= :a AND paid_at < :b""",
     """SELECT id, amount, refunded_at AS at, 'order #' || id AS ref{TEST} FROM subscription_orders
        WHERE refunded_at >= :a AND refunded_at < :b AND paid_at IS NOT NULL"""),
    # 유료 신청에는 입금 확인 시각 칸이 없어 신청일로 달을 정한다(명세에 표시).
    ("udj_app", "udj", "유료 신청(신청일 기준)",
     """SELECT id, amount, created_at AS at, kind || ' #' || id AS ref FROM service_applications
        WHERE created_at >= :a AND created_at < :b AND amount > 0
          AND status IN ('paid', 'done') AND kind <> 'graduate_video'""",
     None),
    # 합격생 영상. 유료 신청과 같은 표지만 결제 유형(영상 결제)이 달라 따로 읽는다.
    ("udj_video", "udj", "합격생 영상(신청일 기준)",
     """SELECT id, amount, created_at AS at, kind || ' #' || id AS ref FROM service_applications
        WHERE created_at >= :a AND created_at < :b AND amount > 0
          AND status IN ('paid', 'done') AND kind = 'graduate_video'""",
     None),
    ("diary_sub", "diary", "개인 이용권",
     """SELECT id, amount, paid_at AS at, 'order #' || id AS ref, months{TEST} FROM subscription_orders
        WHERE paid_at >= :a AND paid_at < :b""",
     # 송금을 마친 시점이 있어야 환불이 끝난 것이다. 부분 환불이 있어 환불액을 쓴다.
     """SELECT id, CASE WHEN COALESCE(refund_amount, 0) > 0 THEN refund_amount ELSE amount END AS amount,
               refund_paid_at AS at, 'order #' || id AS ref{TEST} FROM subscription_orders
        WHERE refund_paid_at >= :a AND refund_paid_at < :b AND paid_at IS NOT NULL"""),
    ("diary_seat", "diary", "학교 좌석",
     """SELECT id, amount, paid_at AS at, school_name || ' #' || id AS ref, months,
               COALESCE(approved_seats, seats) AS seats, product FROM seat_orders
        WHERE paid_at >= :a AND paid_at < :b
          AND CAST(status AS TEXT) IN ('paid', 'approved')""",
     None),
]


# {TEST} 를 쓰는 출처가 읽는 표.
TEST_TABLES = {"udj_sub": "subscription_orders", "diary_sub": "subscription_orders"}
_HAS_TEST_COL: Dict[str, bool] = {}


def _test_col(db_key: str, table: str) -> str:
    """is_test 칸이 있으면 읽는 SQL 조각, 없으면 빈 문자열. 있을 때만 기억해 둔다
    (백엔드가 칸을 만든 뒤에는 다시 묻지 않게)."""
    if _HAS_TEST_COL.get(db_key + table):
        return ", is_test AS is_test"
    eng = _ENGINES.get(db_key)
    if eng is None:
        return ""
    try:
        cols = {c["name"] for c in inspect(eng).get_columns(table)}
    except Exception:
        return ""
    if "is_test" in cols:
        _HAS_TEST_COL[db_key + table] = True
        return ", is_test AS is_test"
    return ""


def ptype_map(db: Session) -> Dict[str, str]:
    """출처 → 결제 유형. 관리자가 바꾼 것이 있으면 그것을 쓴다."""
    out = dict(DEFAULT_PTYPE)
    raw = get_settings(db).get("ptype_map") or ""
    try:
        saved = json.loads(raw) if raw else {}
    except ValueError:
        saved = {}
    for k, v in (saved or {}).items():
        if k in out and v in PAYMENT_TYPES:
            out[k] = v
    return out


def month_bounds(month: str) -> Tuple[datetime, datetime]:
    """'2026-09' → 그 달의 UTC 구간. 한국 날짜로 끊는다."""
    try:
        y, m = (int(x) for x in month.split("-"))
        start = datetime(y, m, 1)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="달은 2026-09 형식으로 넣어 주세요.")
    end = datetime(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return start - KST, end - KST


def _read_source(db_key: str, sql: str, a: datetime, b: datetime,
                 source_key: str = "") -> List[dict]:
    eng = _ENGINES.get(db_key)
    if eng is None:
        raise LookupError("not-configured")
    if "{TEST}" in sql:
        sql = sql.replace("{TEST}", _test_col(db_key, TEST_TABLES.get(source_key, "")))
    with eng.connect() as conn:
        rows = conn.execute(text(sql), {"a": a, "b": b}).mappings().all()
    out = []
    for r in rows:
        at = r["at"]
        if isinstance(at, str):
            at = datetime.fromisoformat(at)
        keys = r.keys()
        out.append({"amount": int(r["amount"] or 0),
                    "day": (at + KST).date().isoformat() if at else None,
                    "ref": str(r["ref"]),
                    "detail": _detail(r, keys),
                    "is_test": bool(r["is_test"]) if "is_test" in keys else False})
    return out


PLAN_LABEL = {"free": "무료", "basic": "베이직", "premium": "프리미엄", "platinum": "플래티넘"}
PRODUCT_LABEL = {"essay": "자기소개서", "research": "연구·논문"}


def _detail(r, keys) -> str:
    """'프리미엄 12개월', '30명 12개월' 같은 설명. 몇 개월짜리 결제인지가 보여야 한다."""
    parts = []
    if "plan" in keys and r["plan"]:
        parts.append(PLAN_LABEL.get(str(r["plan"]), str(r["plan"])))
    if "product" in keys and r["product"]:
        parts.append(PRODUCT_LABEL.get(str(r["product"]), str(r["product"])))
    if "seats" in keys and r["seats"]:
        parts.append(f"{int(r['seats'])}명")
    if "months" in keys and r["months"]:
        parts.append(f"{int(r['months'])}개월")
    return " ".join(parts)


def collect_lines(db: Session, month: str) -> Tuple[List[dict], List[str]]:
    """그 달의 명세 줄 전부. (줄들, 경고들). 테스트 결제는 빠진다."""
    a, b = month_bounds(month)
    lines, warnings, _tests = collect_range(
        db, a, b, lambda q: q.filter(WorkLedgerEntry.month == month))
    return lines, warnings


def collect_range(db: Session, a: datetime, b: datetime, manual_filter
                  ) -> Tuple[List[dict], List[str], List[dict]]:
    """UTC 구간 [a, b) 의 명세 줄. (실제 줄들, 경고들, 테스트 결제 줄들)

    manual_filter 는 직접 입력한 줄을 고르는 함수다 — 직접 입력은 달 단위로
    적으므로 달 화면과 기간 화면이 고르는 법이 다르다."""
    lines: List[dict] = []
    tests: List[dict] = []
    warnings: List[str] = []
    missing_db = set()
    pmap = ptype_map(db)

    for key, db_key, label, sale_sql, refund_sql in SOURCES:
        for kind, sql in (("sale", sale_sql), ("refund", refund_sql)):
            if not sql:
                continue
            try:
                for r in _read_source(db_key, sql, a, b, key):
                    if r["amount"] <= 0:
                        continue
                    line = {"source": "auto", "source_key": key, "kind": kind,
                            "site": SITE_NAME[db_key],
                            "payment_type": pmap.get(key, "other"),
                            "label": label + (f" · {r['detail']}" if r["detail"] else ""),
                            "amount": r["amount"], "day": r["day"], "ref": r["ref"]}
                    (tests if r["is_test"] else lines).append(line)
            except LookupError:
                missing_db.add(db_key)
            except Exception as e:
                warnings.append(f"{SITE_NAME[db_key]} {label}: 읽지 못했습니다 ({type(e).__name__})")
                print(f"[우리업무] 매출 읽기 실패 {key}: {e}", file=sys.stderr, flush=True)

    for db_key in sorted(missing_db):
        warnings.append(f"{SITE_NAME[db_key]} 결제 기록을 읽을 DB 주소가 설정되지 않아 자동 매출에서 빠졌습니다.")

    for e in manual_filter(db.query(WorkLedgerEntry)).order_by(WorkLedgerEntry.id).all():
        pt = e.payment_type if e.payment_type in PAYMENT_TYPES else "other"
        lines.append({"source": "manual", "id": e.id, "kind": e.kind, "site": e.site,
                      "payment_type": pt,
                      "label": "직접 입력", "amount": e.amount,
                      "day": e.day.isoformat() if e.day else None, "ref": e.memo})

    lines.sort(key=lambda x: (x["day"] or "", x["kind"], x["site"]))
    tests.sort(key=lambda x: (x["day"] or "", x["kind"]))
    return lines, warnings, tests


def by_payment_type(lines: List[dict]) -> List[dict]:
    """결제 유형별 건수·매출·환불·순매출·비율. 다섯 유형을 늘 같은 순서로 낸다
    (0원인 유형도 빠지지 않아야 표가 달마다 모양이 같다). 비율은 매출 기준."""
    rows = {k: {"key": k, "label": v, "count": 0, "sales": 0, "refunds": 0}
            for k, v in PAYMENT_TYPES.items()}
    for x in lines:
        row = rows[x.get("payment_type") if x.get("payment_type") in rows else "other"]
        if x["kind"] == "sale":
            row["count"] += 1
            row["sales"] += x["amount"]
        else:
            row["refunds"] += x["amount"]
    total_sales = sum(r["sales"] for r in rows.values())
    out = []
    for r in rows.values():
        r["net"] = r["sales"] - r["refunds"]
        r["ratio"] = round(r["sales"] * 100 / total_sales, 1) if total_sales else 0.0
        out.append(r)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 계산
# ─────────────────────────────────────────────────────────────────────────────

def compute(db: Session, month: str) -> dict:
    s = get_settings(db)
    partner_pct = _num(s["partner_pct"], 60.0)
    inc_pct = _num(s["incentive_pct"], 1.0)
    inc_cap = int(_num(s["incentive_cap"], 3_000_000))

    lines, warnings = collect_lines(db, month)
    sales = sum(x["amount"] for x in lines if x["kind"] == "sale")
    order_count = sum(1 for x in lines if x["kind"] == "sale")
    refunds = sum(x["amount"] for x in lines if x["kind"] == "refund")
    net = sales - refunds

    by_site: Dict[str, dict] = {}
    for x in lines:
        row = by_site.setdefault(x["site"], {"sales": 0, "refunds": 0})
        row["sales" if x["kind"] == "sale" else "refunds"] += x["amount"]
    for row in by_site.values():
        row["net"] = row["sales"] - row["refunds"]

    # 순매출이 마이너스인 달(환불이 더 많은 달)은 나눌 돈이 없다.
    base = max(0, net)
    partner = int(round(base * partner_pct / 100))
    ours = base - partner

    _, month_end = month_bounds(month)
    staff = (db.query(WorkUser)
             .filter(WorkUser.role == "staff", WorkUser.is_active.is_(True),
                     WorkUser.created_at < month_end)
             .order_by(WorkUser.name).all())
    per_person = min(inc_cap, int(ours * inc_pct // 100))
    incentives = [{"user_id": u.id, "name": u.name, "amount": per_person,
                   "capped": per_person == inc_cap and ours * inc_pct / 100 > inc_cap}
                  for u in staff]
    inc_total = per_person * len(staff)

    org_name = ""
    if s["partner_org_id"]:
        org = db.get(WorkOrg, int(s["partner_org_id"]))
        org_name = org.name if org else ""

    return {
        "month": month,
        "rules": {"partner_pct": partner_pct, "our_pct": 100 - partner_pct,
                  "incentive_pct": inc_pct, "incentive_cap": inc_cap,
                  "partner_org_id": s["partner_org_id"], "partner_org_name": org_name},
        "sales": sales, "refunds": refunds, "net": net, "order_count": order_count,
        "partner_share": partner, "our_share": ours,
        "incentive_each": per_person, "incentive_total": inc_total,
        "our_remaining": ours - inc_total,
        "incentives": incentives,
        "by_site": by_site,
        "by_type": by_payment_type(lines),
        "lines": lines,
        "warnings": warnings,
        "negative_net": net < 0,
    }


def _this_month() -> str:
    return (datetime.utcnow() + KST).strftime("%Y-%m")


def month_view(db: Session, month: str) -> dict:
    """마감한 달이면 저장된 표를, 아니면 지금 계산한 표를."""
    locked = db.query(WorkSettlement).filter(WorkSettlement.month == month).first()
    if locked:
        data = json.loads(locked.data)
        data["locked"] = True
        data["locked_at"] = (locked.locked_at + KST).strftime("%Y-%m-%d %H:%M")
        data["paid"] = json.loads(locked.paid or "{}")
        if "by_type" not in data:
            # 결제 유형이 생기기 전에 마감한 달. 저장된 줄로 다시 세면 유형 없는 줄은 기타로 간다.
            data["by_type"] = by_payment_type(data.get("lines", []))
        return data
    data = compute(db, month)
    data["locked"] = False
    data["paid"] = {}
    return data


# ─────────────────────────────────────────────────────────────────────────────
# 누가 무엇을 보나
# ─────────────────────────────────────────────────────────────────────────────

def _partner_can_see(db: Session, user: WorkUser) -> bool:
    if user.role != "partner" or not user.org_id:
        return False
    return get_settings(db)["partner_org_id"] == str(user.org_id)


def _for_partner(d: dict) -> dict:
    """협력사에게는 자기 몫까지만. 직원 인센티브와 우리 쪽 잔액은 내부 정보다.
    명세 줄의 참고(주문 번호·학교명)도 뺀다 — 고객 정보다."""
    keep = ("month", "sales", "refunds", "net", "partner_share", "by_site", "by_type",
            "locked", "locked_at", "negative_net", "warnings")
    out = {k: d.get(k) for k in keep}
    out["rules"] = {"partner_pct": d["rules"]["partner_pct"],
                    "partner_org_name": d["rules"]["partner_org_name"]}
    out["lines"] = [{k: x.get(k) for k in ("kind", "site", "label", "amount", "day", "payment_type")}
                    for x in d["lines"]]
    out["partner_paid"] = bool((d.get("paid") or {}).get("partner"))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 바깥으로
# ─────────────────────────────────────────────────────────────────────────────

class EntryIn(BaseModel):
    month: str
    kind: str = "sale"
    site: str = "기타"
    payment_type: str = "other"
    amount: int = Field(gt=0, le=10_000_000_000)
    memo: str = Field(default="", max_length=200)
    day: Optional[date] = None


class SettingsIn(BaseModel):
    ptype_map: Optional[Dict[str, str]] = None
    partner_org_id: Optional[str] = None
    partner_pct: Optional[float] = Field(default=None, ge=0, le=100)
    incentive_pct: Optional[float] = Field(default=None, ge=0, le=100)
    incentive_cap: Optional[int] = Field(default=None, ge=0)


class PaidIn(BaseModel):
    target: str          # "partner" 또는 "user:12"
    paid: bool


@router.get("/settlement")
def settlement(month: str = "", user: WorkUser = Depends(current_user),
               db: Session = Depends(get_db)):
    month = month or _this_month()
    if user.role == "admin":
        return month_view(db, month)
    if _partner_can_see(db, user):
        return _for_partner(month_view(db, month))
    raise HTTPException(status_code=403, detail="정산을 볼 권한이 없습니다.")


@router.get("/settlement/months")
def settlement_months(count: int = 12, user: WorkUser = Depends(current_user),
                      db: Session = Depends(get_db)):
    """최근 몇 달 요약. 달마다 결제 기록을 다시 읽으므로 12달 정도로 둔다."""
    if user.role != "admin" and not _partner_can_see(db, user):
        raise HTTPException(status_code=403, detail="정산을 볼 권한이 없습니다.")
    count = max(1, min(count, 24))
    now = datetime.utcnow() + KST
    y, m = now.year, now.month
    out = []
    for _ in range(count):
        month = f"{y:04d}-{m:02d}"
        d = month_view(db, month)
        row = {"month": month, "sales": d["sales"], "refunds": d["refunds"], "net": d["net"],
               "order_count": d.get("order_count", sum(1 for x in d["lines"] if x["kind"] == "sale")),
               "partner_share": d["partner_share"], "locked": d["locked"]}
        if user.role == "admin":
            row.update({"our_share": d["our_share"], "incentive_total": d["incentive_total"],
                        "our_remaining": d["our_remaining"]})
        else:
            row["partner_paid"] = bool((d.get("paid") or {}).get("partner"))
        out.append(row)
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out


@router.post("/settlement/entries")
def add_entry(body: EntryIn, user: WorkUser = Depends(admin_only),
              db: Session = Depends(get_db)):
    month_bounds(body.month)
    if body.kind not in ("sale", "refund"):
        raise HTTPException(status_code=400, detail="매출 또는 환불만 적을 수 있습니다.")
    if body.payment_type not in PAYMENT_TYPES:
        raise HTTPException(status_code=400, detail="알 수 없는 결제 유형입니다.")
    if db.query(WorkSettlement).filter(WorkSettlement.month == body.month).first():
        raise HTTPException(status_code=400, detail="마감한 달입니다. 마감을 풀고 적어 주세요.")
    e = WorkLedgerEntry(month=body.month, kind=body.kind, site=body.site.strip() or "기타",
                        payment_type=body.payment_type,
                        amount=body.amount, memo=body.memo.strip(), day=body.day,
                        created_by=user.id)
    db.add(e)
    db.commit()
    return {"ok": True, "id": e.id}


@router.delete("/settlement/entries/{entry_id}")
def delete_entry(entry_id: int, user: WorkUser = Depends(admin_only),
                 db: Session = Depends(get_db)):
    e = db.get(WorkLedgerEntry, entry_id)
    if e is None:
        raise HTTPException(status_code=404, detail="없는 줄입니다.")
    if db.query(WorkSettlement).filter(WorkSettlement.month == e.month).first():
        raise HTTPException(status_code=400, detail="마감한 달입니다. 마감을 풀고 지워 주세요.")
    db.delete(e)
    db.commit()
    return {"ok": True}


@router.post("/settlement/{month}/lock")
def lock_month(month: str, user: WorkUser = Depends(admin_only),
               db: Session = Depends(get_db)):
    month_bounds(month)
    if month >= _this_month():
        raise HTTPException(status_code=400, detail="끝나지 않은 달은 마감할 수 없습니다.")
    if db.query(WorkSettlement).filter(WorkSettlement.month == month).first():
        raise HTTPException(status_code=400, detail="이미 마감한 달입니다.")
    data = compute(db, month)
    if data["warnings"]:
        # 읽지 못한 매출이 있는 채로 얼리면 틀린 숫자로 돈이 나간다.
        raise HTTPException(status_code=400,
                            detail="매출을 다 읽지 못해 마감할 수 없습니다: " + " / ".join(data["warnings"]))
    db.add(WorkSettlement(month=month, data=json.dumps(data, ensure_ascii=False),
                          paid="{}", locked_by=user.id))
    db.flush()
    # 정산 완료 = 그 달 급여명세서 확정. 같은 트랜잭션에서 해야 둘이 어긋나지 않는다.
    from .payroll import finalize_month
    finalize_month(db, month, data)
    db.commit()
    return month_view(db, month)


@router.post("/settlement/{month}/unlock")
def unlock_month(month: str, user: WorkUser = Depends(admin_only),
                 db: Session = Depends(get_db)):
    row = db.query(WorkSettlement).filter(WorkSettlement.month == month).first()
    if row is None:
        raise HTTPException(status_code=404, detail="마감하지 않은 달입니다.")
    if any((json.loads(row.paid or "{}")).values()):
        raise HTTPException(status_code=400,
                            detail="지급 완료로 표시한 항목이 있어 풀 수 없습니다. 지급 표시를 먼저 지워 주세요.")
    db.delete(row)
    from .payroll import unfinalize_month
    unfinalize_month(db, month)
    db.commit()
    return month_view(db, month)


@router.patch("/settlement/{month}/paid")
def mark_paid(month: str, body: PaidIn, user: WorkUser = Depends(admin_only),
              db: Session = Depends(get_db)):
    row = db.query(WorkSettlement).filter(WorkSettlement.month == month).first()
    if row is None:
        raise HTTPException(status_code=400, detail="마감한 달만 지급 표시를 할 수 있습니다.")
    paid = json.loads(row.paid or "{}")
    if body.paid:
        paid[body.target] = (datetime.utcnow() + KST).strftime("%Y-%m-%d %H:%M")
    else:
        paid.pop(body.target, None)
    row.paid = json.dumps(paid, ensure_ascii=False)
    db.commit()
    return month_view(db, month)


@router.get("/settlement/settings")
def read_settings(user: WorkUser = Depends(admin_only), db: Session = Depends(get_db)):
    s = get_settings(db)
    s["diary_connected"] = _ENGINES["diary"] is not None
    s["ptype_map"] = ptype_map(db)
    s["payment_types"] = [{"key": k, "label": v} for k, v in PAYMENT_TYPES.items()]
    s["sources"] = [{"key": k, "site": SITE_NAME[dbk], "label": label,
                     "default": DEFAULT_PTYPE.get(k, "other")}
                    for k, dbk, label, _s, _r in SOURCES]
    return s


@router.put("/settlement/settings")
def write_settings(body: SettingsIn, user: WorkUser = Depends(admin_only),
                   db: Session = Depends(get_db)):
    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    if "ptype_map" in changes:
        m = changes["ptype_map"]
        bad = [k for k, v in m.items() if k not in DEFAULT_PTYPE or v not in PAYMENT_TYPES]
        if bad:
            raise HTTPException(status_code=400, detail="알 수 없는 출처나 결제 유형입니다: " + ", ".join(bad))
        # 기본값과 같은 것은 저장하지 않는다 — 나중에 기본값을 고치면 따라가게.
        changes["ptype_map"] = json.dumps({k: v for k, v in m.items() if DEFAULT_PTYPE[k] != v})
    if "partner_org_id" in changes and changes["partner_org_id"]:
        if db.get(WorkOrg, int(changes["partner_org_id"])) is None:
            raise HTTPException(status_code=400, detail="없는 협력사입니다.")
    for k, v in changes.items():
        row = db.get(WorkSetting, k)
        if row is None:
            db.add(WorkSetting(key=k, value=str(v)))
        else:
            row.value = str(v)
    db.commit()
    return read_settings(user, db)


# ─────────────────────────────────────────────────────────────────────────────
# 매출 통계 — 기간·결제 유형별
# ─────────────────────────────────────────────────────────────────────────────

MAX_RANGE_DAYS = 400


def _day(s: str, name: str) -> date:
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{name}은(는) 2026-09-01 형식으로 넣어 주세요.")


@router.get("/sales")
def sales(start: str = "", end: str = "", payment_type: str = "",
          user: WorkUser = Depends(current_user), db: Session = Depends(get_db)):
    """기간(한국 날짜, 양끝 포함)·결제 유형별 매출.

    **정산(달 화면)과 같은 결제 기록·같은 규칙**으로 센다. 다만 이 화면은
    늘 지금의 결제 기록을 다시 읽는다 — 마감한 달의 고정된 숫자와는 그사이
    바뀐 환불 등만큼 다를 수 있다(화면에 적는다).

    합계는 걸러 낸 줄에서 다시 더하지 않고 유형별 합을 더해 만든다 —
    전체와 유형별 합이 어긋날 길을 없앤다.

    **협력사는 지정된 홈페이지의 매출만 본다.** 지정은 방문 통계와 같은 것
    (WorkOrg.visit_sites, 관리자 → 계정 → 기업별 '볼 수 있는 사이트')을 쓴다.
    주문 번호·학교명 같은 참고와 직접 입력 줄의 메모는 고객 정보라 빼고,
    테스트 결제 건수도 관리자에게만 보여 준다."""
    sites = None                     # None = 전부(관리자)
    if user.role != "admin":
        from .visits import allowed_sites
        sites = [s[0] for s in allowed_sites(db, user)] if user.role == "partner" else []
        if not sites:
            raise HTTPException(status_code=403, detail="매출을 볼 권한이 없습니다.")
    today = (datetime.utcnow() + KST).date()
    d1 = _day(start, "시작일") if start else today.replace(day=1)
    d2 = _day(end, "종료일") if end else today
    if d2 < d1:
        raise HTTPException(status_code=400, detail="종료일이 시작일보다 앞섭니다.")
    if (d2 - d1).days > MAX_RANGE_DAYS:
        raise HTTPException(status_code=400, detail=f"한 번에 {MAX_RANGE_DAYS}일까지 볼 수 있습니다.")
    if payment_type and payment_type not in PAYMENT_TYPES:
        raise HTTPException(status_code=400, detail="알 수 없는 결제 유형입니다.")

    a = datetime(d1.year, d1.month, d1.day) - KST
    b = datetime(d2.year, d2.month, d2.day) + timedelta(days=1) - KST

    # 직접 입력은 날짜가 있으면 그 날로, 날짜가 없으면 그 달 1일로 본다.
    months_in = []
    y, m = d1.year, d1.month
    while (y, m) <= (d2.year, d2.month):
        if d1 <= date(y, m, 1) <= d2:
            months_in.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)

    def manual(q):
        return q.filter(or_(and_(WorkLedgerEntry.day >= d1, WorkLedgerEntry.day <= d2),
                            and_(WorkLedgerEntry.day.is_(None), WorkLedgerEntry.month.in_(months_in))))

    lines, warnings, tests = collect_range(db, a, b, manual)
    if sites is not None:
        lines = [x for x in lines if x["site"] in sites]
        tests = []
        warnings = [w for w in warnings if any(w.startswith(s) for s in sites)]

    types = by_payment_type(lines)
    total = {k: sum(t[k] for t in types) for k in ("count", "sales", "refunds", "net")}
    shown = [x for x in lines if not payment_type or x["payment_type"] == payment_type]
    shown.sort(key=lambda x: (x["day"] or "", x["kind"]), reverse=True)
    if user.role != "admin":
        shown = [{k: x.get(k) for k in ("kind", "site", "label", "amount", "day", "payment_type")}
                 for x in shown]
    return {
        "start": d1.isoformat(), "end": d2.isoformat(),
        "payment_type": payment_type,
        # 이 사람이 보는 사이트. None 이면 전부(관리자).
        "sites": sites,
        "payment_types": [{"key": k, "label": v} for k, v in PAYMENT_TYPES.items()],
        "types": types,
        "total": total,
        "selected": next((t for t in types if t["key"] == payment_type), None),
        "lines": shown,
        "test": {"count": sum(1 for x in tests if x["kind"] == "sale"),
                 "sales": sum(x["amount"] for x in tests if x["kind"] == "sale"),
                 "refunds": sum(x["amount"] for x in tests if x["kind"] == "refund")},
        "warnings": warnings,
    }


@router.get("/incentive/me")
def my_incentive(user: WorkUser = Depends(current_user), db: Session = Depends(get_db)):
    """직원 본인의 이번 달 예상 인센티브와 지난 달들.

    이번 달은 아직 끝나지 않아 **예상**이다. 금액만 보여 주고 매출 명세는
    보여 주지 않는다 — 직원이 볼 권한이 있는 건 자기 몫까지다."""
    if user.role != "staff":
        raise HTTPException(status_code=403, detail="직원 계정만 볼 수 있습니다.")
    now = datetime.utcnow() + KST
    y, m = now.year, now.month
    out = []
    for i in range(6):
        month = f"{y:04d}-{m:02d}"
        d = month_view(db, month)
        mine = next((x for x in d["incentives"] if x["user_id"] == user.id), None)
        out.append({
            "month": month,
            "amount": mine["amount"] if mine else 0,
            "capped": bool(mine and mine["capped"]),
            "locked": d["locked"],
            "paid_at": (d.get("paid") or {}).get(f"user:{user.id}"),
            "estimate": i == 0 and not d["locked"],
        })
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return {"cap": int(_num(get_settings(db)["incentive_cap"], 3_000_000)), "months": out}
