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
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from .database import engine as work_engine, get_db
from .models import (WorkLedgerEntry, WorkOrg, WorkSetting, WorkSettlement,
                     WorkUser)
from .work import admin_only, current_user

router = APIRouter(prefix="/api/work", tags=["settlement"])

KST = timedelta(hours=9)

DEFAULTS = {
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
#   :a ~ :b 는 그 달의 UTC 구간.
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
     """SELECT id, amount, paid_at AS at, 'order #' || id AS ref, months FROM subscription_orders
        WHERE paid_at >= :a AND paid_at < :b""",
     """SELECT id, amount, refunded_at AS at, 'order #' || id AS ref FROM subscription_orders
        WHERE refunded_at >= :a AND refunded_at < :b AND paid_at IS NOT NULL"""),
    # 유료 신청에는 입금 확인 시각 칸이 없어 신청일로 달을 정한다(명세에 표시).
    ("udj_app", "udj", "유료 신청(신청일 기준)",
     """SELECT id, amount, created_at AS at, kind || ' #' || id AS ref FROM service_applications
        WHERE created_at >= :a AND created_at < :b AND amount > 0
          AND status IN ('paid', 'done')""",
     None),
    ("diary_sub", "diary", "구독",
     """SELECT id, amount, paid_at AS at, 'order #' || id AS ref, months FROM subscription_orders
        WHERE paid_at >= :a AND paid_at < :b""",
     # 송금을 마친 시점이 있어야 환불이 끝난 것이다. 부분 환불이 있어 환불액을 쓴다.
     """SELECT id, CASE WHEN COALESCE(refund_amount, 0) > 0 THEN refund_amount ELSE amount END AS amount,
               refund_paid_at AS at, 'order #' || id AS ref FROM subscription_orders
        WHERE refund_paid_at >= :a AND refund_paid_at < :b AND paid_at IS NOT NULL"""),
    ("diary_seat", "diary", "학교 좌석",
     """SELECT id, amount, paid_at AS at, school_name || ' #' || id AS ref, months,
               COALESCE(approved_seats, seats) AS seats, product FROM seat_orders
        WHERE paid_at >= :a AND paid_at < :b
          AND CAST(status AS TEXT) IN ('paid', 'approved')""",
     None),
]


def month_bounds(month: str) -> Tuple[datetime, datetime]:
    """'2026-09' → 그 달의 UTC 구간. 한국 날짜로 끊는다."""
    try:
        y, m = (int(x) for x in month.split("-"))
        start = datetime(y, m, 1)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="달은 2026-09 형식으로 넣어 주세요.")
    end = datetime(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return start - KST, end - KST


def _read_source(db_key: str, sql: str, a: datetime, b: datetime) -> List[dict]:
    eng = _ENGINES.get(db_key)
    if eng is None:
        raise LookupError("not-configured")
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
                    "detail": _detail(r, keys)})
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
    """그 달의 명세 줄 전부. (줄들, 경고들)"""
    a, b = month_bounds(month)
    lines: List[dict] = []
    warnings: List[str] = []
    missing_db = set()

    for key, db_key, label, sale_sql, refund_sql in SOURCES:
        for kind, sql in (("sale", sale_sql), ("refund", refund_sql)):
            if not sql:
                continue
            try:
                for r in _read_source(db_key, sql, a, b):
                    if r["amount"] <= 0:
                        continue
                    lines.append({"source": "auto", "kind": kind, "site": SITE_NAME[db_key],
                                  "label": label + (f" · {r['detail']}" if r["detail"] else ""),
                                  "amount": r["amount"], "day": r["day"], "ref": r["ref"]})
            except LookupError:
                missing_db.add(db_key)
            except Exception as e:
                warnings.append(f"{SITE_NAME[db_key]} {label}: 읽지 못했습니다 ({type(e).__name__})")
                print(f"[우리업무] 매출 읽기 실패 {key}: {e}", file=sys.stderr, flush=True)

    for db_key in sorted(missing_db):
        warnings.append(f"{SITE_NAME[db_key]} 결제 기록을 읽을 DB 주소가 설정되지 않아 자동 매출에서 빠졌습니다.")

    for e in (db.query(WorkLedgerEntry).filter(WorkLedgerEntry.month == month)
              .order_by(WorkLedgerEntry.id).all()):
        lines.append({"source": "manual", "id": e.id, "kind": e.kind, "site": e.site,
                      "label": "직접 입력", "amount": e.amount,
                      "day": e.day.isoformat() if e.day else None, "ref": e.memo})

    lines.sort(key=lambda x: (x["day"] or "", x["kind"], x["site"]))
    return lines, warnings


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
    keep = ("month", "sales", "refunds", "net", "partner_share", "by_site",
            "locked", "locked_at", "negative_net", "warnings")
    out = {k: d.get(k) for k in keep}
    out["rules"] = {"partner_pct": d["rules"]["partner_pct"],
                    "partner_org_name": d["rules"]["partner_org_name"]}
    out["lines"] = [{k: x[k] for k in ("kind", "site", "label", "amount", "day")}
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
    amount: int = Field(gt=0, le=10_000_000_000)
    memo: str = Field(default="", max_length=200)
    day: Optional[date] = None


class SettingsIn(BaseModel):
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
    if db.query(WorkSettlement).filter(WorkSettlement.month == body.month).first():
        raise HTTPException(status_code=400, detail="마감한 달입니다. 마감을 풀고 적어 주세요.")
    e = WorkLedgerEntry(month=body.month, kind=body.kind, site=body.site.strip() or "기타",
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
    return s


@router.put("/settlement/settings")
def write_settings(body: SettingsIn, user: WorkUser = Depends(admin_only),
                   db: Session = Depends(get_db)):
    changes = {k: v for k, v in body.model_dump().items() if v is not None}
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
