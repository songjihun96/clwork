"""급여 — 출퇴근 기록 기반 시급 계산, 월별 급여명세서, PDF.

**계산 (2026-09-15 대표와 정한 기준)**

    하루 근무시간 = 퇴근 − 출근 − 휴게
        휴게: 4시간 이상 30분, 8시간 이상 1시간 (근로기준법 제54조 기준 자동 차감)
    기본급     = 그 달 근무시간 × 시급
    주휴수당   = 주(월~일) 근무 15시간 이상이면 min(주 근무, 40) ÷ 40 × 8시간 × 시급
                 그 주의 **일요일이 속한 달**에 지급한다 — 달을 걸친 주가 두 번 잡히지 않게.
                 아직 끝나지 않은 주는 넣지 않는다. 프리랜서는 주휴 대상이 아니다.
    연장·야간 가산 없음 (상시 5명 미만 사업장)
    + 식대(비과세 한도까지) + 고정 수당 + 정산 인센티브 + 그 달 추가 항목
    − 공제
        근로자:   국민연금·건강·장기요양·고용보험 자동, 근로소득세는 관리자 입력,
                  지방소득세 = 소득세 × 10%
        프리랜서: 지급액 × 3.3% (소득세 3% + 지방소득세 0.3%)
    원 단위 계산 후 공제액은 10원 미만을 버린다(보험료·원천세 관행).

**확정.** 정산 탭에서 '정산 완료'를 누르면 그 달 명세서를 계산해 스냅샷으로
얼린다. 그 뒤로는 출퇴근 기록·기본값·요율이 바뀌어도 명세서는 그대로다.
교부한 명세서가 나중에 저절로 달라지면 안 된다.

**요율은 참고용 기본값이다.** 해마다 바뀌므로 화면에서 고칠 수 있게 두었고,
실제 신고는 공단 고지·세무사 기준을 따라야 한다. 명세서에도 그렇게 적는다.
"""

from __future__ import annotations

import io
import json
import os
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .database import get_db
from .models import (WorkAttendance, WorkPayProfile, WorkPayslip, WorkSetting,
                     WorkSettlement, WorkUser)
from .work import admin_only, current_user

router = APIRouter(prefix="/api/work", tags=["payroll"])

KST = timedelta(hours=9)

RATE_DEFAULTS = {
    "company_name": "우리동네 소프트",
    "pay_day": "10",               # 다음 달 며칠에 지급하나
    "min_wage": "10320",           # 2026년 최저시급
    "pension_rate": "4.75",        # 국민연금 근로자분(%)
    "pension_min": "400000",       # 기준소득월액 하한
    "pension_max": "6370000",      # 기준소득월액 상한
    "health_rate": "3.595",        # 건강보험 근로자분(%)
    "ltc_rate": "13.14",           # 장기요양 = 건강보험료의 %
    "employment_rate": "0.9",      # 고용보험 근로자분(%)
    "freelancer_rate": "3.3",      # 사업소득 원천징수(%)
    "meal_limit": "200000",        # 식대 비과세 한도
}


def _f(v, d=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def rates(db: Session) -> dict:
    out = dict(RATE_DEFAULTS)
    for row in db.query(WorkSetting).filter(WorkSetting.key.in_(["pay_" + k for k in RATE_DEFAULTS])).all():
        out[row.key[4:]] = row.value
    return out


def floor10(x: float) -> int:
    """10원 미만 버림. 소수 계산은 3.3 ÷ 1.1 × 11만 = 3299.9999… 처럼 경계 바로 아래로
    떨어질 수 있어, 버리기 전에 아주 작은 값을 더해 오차를 흡수한다."""
    return int(x + 1e-6) // 10 * 10


def month_days(month: str):
    y, m = (int(x) for x in month.split("-"))
    first = date(y, m, 1)
    nxt = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return first, nxt - timedelta(days=1)


def _today() -> date:
    return (datetime.utcnow() + KST).date()


# ─────────────────────────────────────────────────────────────────────────────
# 근무시간
# ─────────────────────────────────────────────────────────────────────────────

def break_minutes(raw: int) -> int:
    if raw >= 8 * 60:
        return 60
    if raw >= 4 * 60:
        return 30
    return 0


def day_rows(db: Session, user_id: int, start: date, end: date) -> Dict[date, dict]:
    today = _today()
    out = {}
    for a in (db.query(WorkAttendance)
              .filter(WorkAttendance.user_id == user_id,
                      WorkAttendance.work_date >= start, WorkAttendance.work_date <= end)
              .all()):
        first = a.first_seen_at + KST
        left = (a.left_at + KST) if a.left_at else None
        if left is None:
            # 퇴근 전(오늘)이면 아직 셀 수 없다. 지난 날은 자동 마감이 채워 둔다.
            out[a.work_date] = {"day": a.work_date, "first": first.strftime("%H:%M"), "left": None,
                                "raw": 0, "break": 0, "minutes": 0, "in_progress": a.work_date >= today,
                                "auto_closed": False, "edited": a.edited_by is not None}
            continue
        raw = max(0, int((left - first).total_seconds() // 60))
        brk = break_minutes(raw)
        out[a.work_date] = {"day": a.work_date, "first": first.strftime("%H:%M"),
                            "left": left.strftime("%H:%M"), "raw": raw, "break": brk,
                            "minutes": max(0, raw - brk), "in_progress": False,
                            "auto_closed": bool(a.auto_closed), "edited": a.edited_by is not None}
    return out


def hm(minutes: int) -> str:
    h, m = divmod(int(minutes), 60)
    return f"{h}시간 {m:02d}분" if m else f"{h}시간"


# ─────────────────────────────────────────────────────────────────────────────
# 한 사람 한 달 계산
# ─────────────────────────────────────────────────────────────────────────────

def compute_slip(db: Session, user: WorkUser, month: str, settle_view: Optional[dict] = None) -> dict:
    r = rates(db)
    prof = db.query(WorkPayProfile).filter(WorkPayProfile.user_id == user.id).first()
    employment = prof.employment if prof else "employee"
    wage = prof.hourly_wage if prof else 0
    first, last = month_days(month)
    today = _today()

    # 주휴 계산에 앞뒤 주가 필요하다.
    days = day_rows(db, user.id, first - timedelta(days=6), last + timedelta(days=6))
    in_month = [days[d] for d in sorted(days) if first <= d <= last]
    work_minutes = sum(x["minutes"] for x in in_month)
    base_pay = work_minutes * wage // 60

    # 주휴: 일요일이 이 달에 있는 주
    weeks = []
    juhyu_pay = 0
    if employment == "employee":
        sunday = first + timedelta(days=(6 - first.weekday()) % 7)
        while sunday <= last:
            monday = sunday - timedelta(days=6)
            wk = sum(days[d]["minutes"] for d in days if monday <= d <= sunday)
            finished = sunday < today
            eligible = finished and wk >= 15 * 60
            jmin = min(wk, 2400) * 480 // 2400 if eligible else 0
            pay = jmin * wage // 60
            juhyu_pay += pay
            weeks.append({"from": monday.isoformat(), "to": sunday.isoformat(), "minutes": wk,
                          "finished": finished, "eligible": eligible, "juhyu_minutes": jmin, "pay": pay})
            sunday += timedelta(days=7)

    slip = (db.query(WorkPayslip).filter(WorkPayslip.user_id == user.id, WorkPayslip.month == month).first())
    extras = json.loads(slip.extras or "[]") if slip else []
    overrides = json.loads(slip.overrides or "{}") if slip else {}
    income_tax_in = slip.income_tax if slip else 0

    incentive = 0
    if settle_view:
        mine = next((x for x in settle_view.get("incentives", []) if x["user_id"] == user.id), None)
        incentive = mine["amount"] if mine else 0

    meal = prof.meal_allowance if prof else 0
    meal_limit = int(_f(r["meal_limit"], 200000))
    fixed = prof.fixed_allowance if prof else 0

    items = [{"key": "base", "name": "기본급", "amount": base_pay, "taxable": True,
              "calc": f"근무 {hm(work_minutes)} × 시급 {wage:,}원"}]
    if employment == "employee":
        items.append({"key": "juhyu", "name": "주휴수당", "amount": juhyu_pay, "taxable": True,
                      "calc": f"주 15시간 이상 근무한 주 {sum(1 for w in weeks if w['eligible'])}주 × (주 근무 ÷ 40 × 8시간) × 시급"})
    if fixed:
        items.append({"key": "fixed", "name": (prof.fixed_allowance_name or "고정수당"), "amount": fixed,
                      "taxable": True, "calc": "매월 고정"})
    if meal:
        if employment == "employee":
            items.append({"key": "meal", "name": "식대", "amount": meal, "taxable": meal > meal_limit,
                          "calc": f"월 {meal_limit:,}원까지 비과세"})
        else:
            items.append({"key": "meal", "name": "식대", "amount": meal, "taxable": True, "calc": "매월 고정"})
    if incentive:
        items.append({"key": "incentive", "name": "인센티브", "amount": incentive, "taxable": True,
                      "calc": "정산 인센티브(우리동네 소프트 몫의 비율, 상한 적용)"})
    for i, e in enumerate(extras):
        items.append({"key": f"extra{i}", "name": e.get("name", "기타"), "amount": int(e.get("amount", 0)),
                      "taxable": bool(e.get("taxable", True)), "calc": e.get("calc", "") or "그 달 추가"})

    gross = sum(x["amount"] for x in items)
    taxable = sum(x["amount"] for x in items if x["taxable"])
    if employment == "employee" and meal > meal_limit:
        # 식대가 한도를 넘으면 넘는 부분만 과세다. 위에서 식대 전액을 과세로 잡았으니 한도만큼 뺀다.
        taxable -= meal_limit

    ded = []
    if employment == "employee":
        pen_base = min(max(taxable, int(_f(r["pension_min"]))), int(_f(r["pension_max"]))) if taxable > 0 else 0
        pension = floor10(pen_base * _f(r["pension_rate"]) / 100)
        health = floor10(max(taxable, 0) * _f(r["health_rate"]) / 100)
        ltc = floor10(health * _f(r["ltc_rate"]) / 100)
        emp = floor10(max(taxable, 0) * _f(r["employment_rate"]) / 100)
        tax = floor10(income_tax_in)
        auto = [
            ("pension", "국민연금", pension, f"과세 {pen_base:,}원 × {r['pension_rate']}%"),
            ("health", "건강보험", health, f"과세 {taxable:,}원 × {r['health_rate']}%"),
            ("ltc", "장기요양보험", ltc, f"건강보험료 × {r['ltc_rate']}%"),
            ("employment", "고용보험", emp, f"과세 {taxable:,}원 × {r['employment_rate']}%"),
            ("income_tax", "근로소득세", tax, "간이세액표·세무사 기준 입력"),
        ]
        for key, name, amt, calc in auto:
            if key in overrides:
                amt, calc = int(overrides[key]), calc + " (직접 수정)"
            ded.append({"key": key, "name": name, "amount": amt, "calc": calc})
        tax_now = next(x["amount"] for x in ded if x["key"] == "income_tax")
        local = floor10(tax_now * 0.1)
        if "local_tax" in overrides:
            ded.append({"key": "local_tax", "name": "지방소득세", "amount": int(overrides["local_tax"]),
                        "calc": "근로소득세 × 10% (직접 수정)"})
        else:
            ded.append({"key": "local_tax", "name": "지방소득세", "amount": local, "calc": "근로소득세 × 10%"})
    else:
        pct = _f(r["freelancer_rate"], 3.3)
        it = floor10(gross * round(pct / 1.1, 6) / 100)   # 3.3% 중 소득세 3%
        lt = floor10(it * 0.1)                          # 지방소득세 0.3%
        for key, name, amt, calc in (("income_tax", "사업소득세", it, f"지급액 {gross:,}원 × {pct / 1.1:.1f}%"),
                                     ("local_tax", "지방소득세", lt, "사업소득세 × 10%")):
            if key in overrides:
                amt, calc = int(overrides[key]), calc + " (직접 수정)"
            ded.append({"key": key, "name": name, "amount": amt, "calc": calc})

    total_ded = sum(x["amount"] for x in ded)

    warnings = []
    min_wage = int(_f(r["min_wage"], 0))
    if employment == "employee" and wage and wage < min_wage:
        warnings.append(f"시급 {wage:,}원이 최저시급 {min_wage:,}원보다 낮습니다.")
    if not prof or not wage:
        warnings.append("시급이 설정되지 않았습니다.")
    auto_days = [x["day"].isoformat() for x in in_month if x["auto_closed"] and not x["edited"]]
    if auto_days:
        warnings.append(f"퇴근을 안 눌러 자동으로 닫힌 날 {len(auto_days)}일은 확인이 필요합니다: {', '.join(auto_days)}")
    unfinished = [w for w in weeks if not w["finished"]]
    if unfinished:
        warnings.append("아직 끝나지 않은 주가 있어 주휴수당이 덜 잡혀 있습니다(달이 끝나면 채워집니다).")

    pay_day = int(_f(r["pay_day"], 10))
    ny, nm = (first.year + (first.month == 12), 1 if first.month == 12 else first.month + 1)

    return {
        "month": month, "user_id": user.id, "name": user.name,
        "login_id": user.login_id,
        "employee_no": (prof.employee_no if prof and prof.employee_no else f"W{user.id:04d}"),
        "department": (prof.department if prof and prof.department else (user.memo or "")),
        "employment": employment, "hourly_wage": wage,
        "company": r["company_name"],
        "pay_date": f"{ny:04d}-{nm:02d}-{min(pay_day, 28):02d}",
        "work_days": sum(1 for x in in_month if x["minutes"] > 0),
        "work_minutes": work_minutes,
        "days": [{**x, "day": x["day"].isoformat()} for x in in_month],
        "weeks": weeks,
        "items": items, "deductions": ded,
        "gross": gross, "taxable": taxable, "total_deduction": total_ded,
        "net": gross - total_ded,
        "extras": extras, "income_tax_input": income_tax_in, "overrides": overrides,
        "note": slip.note if slip else "",
        "warnings": warnings,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 달 단위
# ─────────────────────────────────────────────────────────────────────────────

def _locked(db: Session, month: str) -> bool:
    return db.query(WorkSettlement).filter(WorkSettlement.month == month).first() is not None


def targets(db: Session, month: str, settle_view: Optional[dict]) -> List[WorkUser]:
    """그 달 명세서를 받을 사람: 시급을 정해 둔 직원, 그 달 출근 기록이 있는 직원, 인센티브 대상."""
    first, last = month_days(month)
    ids = set()
    ids |= {p.user_id for p in db.query(WorkPayProfile.user_id).all()}
    ids |= {a.user_id for a in db.query(WorkAttendance.user_id)
            .filter(WorkAttendance.work_date >= first, WorkAttendance.work_date <= last).all()}
    if settle_view:
        ids |= {x["user_id"] for x in settle_view.get("incentives", [])}
    if not ids:
        return []
    users = db.query(WorkUser).filter(WorkUser.id.in_(ids), WorkUser.role == "staff").all()
    return sorted(users, key=lambda u: u.name)


def finalize_month(db: Session, month: str, settle_view: dict) -> int:
    """정산 완료 때 settlement.lock_month 가 부른다. 확정한 명세서 수를 돌려준다."""
    n = 0
    for u in targets(db, month, settle_view):
        data = compute_slip(db, u, month, settle_view)
        slip = db.query(WorkPayslip).filter(WorkPayslip.user_id == u.id, WorkPayslip.month == month).first()
        if slip is None:
            slip = WorkPayslip(user_id=u.id, month=month)
            db.add(slip)
        slip.name = u.name
        slip.employment = data["employment"]
        slip.snapshot = json.dumps(data, ensure_ascii=False)
        slip.status = "final"
        slip.finalized_at = datetime.utcnow()
        n += 1
    return n


def unfinalize_month(db: Session, month: str) -> None:
    for slip in db.query(WorkPayslip).filter(WorkPayslip.month == month).all():
        slip.status = "draft"
        slip.snapshot = None
        slip.finalized_at = None


def _settle_view(db: Session, month: str) -> dict:
    from .settlement import month_view
    return month_view(db, month)


def slip_view(db: Session, user: WorkUser, month: str) -> dict:
    slip = db.query(WorkPayslip).filter(WorkPayslip.user_id == user.id, WorkPayslip.month == month).first()
    if slip and slip.status == "final" and slip.snapshot:
        d = json.loads(slip.snapshot)
        d["status"] = "final"
        d["finalized_at"] = (slip.finalized_at + KST).strftime("%Y-%m-%d %H:%M") if slip.finalized_at else ""
        return d
    d = compute_slip(db, user, month, _settle_view(db, month))
    d["status"] = "draft"
    return d


# ─────────────────────────────────────────────────────────────────────────────
# PDF
# ─────────────────────────────────────────────────────────────────────────────

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/msttcorefonts/malgun.ttf",
    "/usr/share/fonts/truetype/malgun/malgun.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
    "/usr/share/fonts/truetype/unfonts-core/UnDotum.ttf",
    "/usr/share/fonts/truetype/baekmuk/dotum.ttf",
    "C:/Windows/Fonts/malgun.ttf",       # 개발 PC
]
_FONT = None


def _font() -> str:
    """기록해 이력서 PDF 와 같은 방식으로 한글 글꼴을 찾는다."""
    global _FONT
    if _FONT:
        return _FONT
    path = next((p for p in FONT_CANDIDATES if os.path.exists(p)), "")
    if not path:
        for root in ("/usr/share/fonts", "/usr/local/share/fonts"):
            for dp, _d, fs in os.walk(root) if os.path.isdir(root) else []:
                for f in fs:
                    if f.lower().endswith(".ttf") and ("nanum" in f.lower() or "malgun" in f.lower()):
                        path = os.path.join(dp, f)
                        break
                if path:
                    break
    if not path:
        raise HTTPException(status_code=500,
                            detail="서버에 한글 글꼴이 없어 PDF 를 만들 수 없습니다(apt-get install fonts-nanum).")
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    pdfmetrics.registerFont(TTFont("KR", path))
    _FONT = "KR"
    return _FONT


def render_pdf(d: dict) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                        TableStyle)
    except ImportError:
        raise HTTPException(status_code=500,
                            detail="PDF 라이브러리가 없습니다. work-backend 를 기록해 파이썬 환경으로 실행해 주세요.")
    font = _font()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"급여명세서 {d['month']} {d['name']}")
    S = lambda size, **kw: ParagraphStyle("s", fontName=font, fontSize=size, leading=size * 1.45, **kw)
    won = lambda n: f"{int(n):,}원"
    y, m = d["month"].split("-")
    freelancer = d["employment"] == "freelancer"
    title = "사업소득 지급명세서" if freelancer else "임금명세서"

    flow = [
        Paragraph(f"{y}년 {int(m)}월 {title}", S(18, alignment=1)),
        Spacer(1, 5 * mm),
    ]
    info = [
        ["회사", d["company"], "지급일", d["pay_date"]],
        ["성명", d["name"], "사번", d["employee_no"]],
        ["소속", d["department"] or "-", "구분", "사업소득(3.3%)" if freelancer else "근로소득"],
        ["시급", won(d["hourly_wage"]), "근무", f"{d['work_days']}일 · {hm(d['work_minutes'])}"],
    ]
    t = Table(info, colWidths=[22 * mm, 64 * mm, 22 * mm, 70 * mm])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), font, 9.5),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f0fd")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f1f0fd")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9c8dc")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    flow += [t, Spacer(1, 6 * mm)]

    def section(head, rows, total_label, total):
        data = [[head, "금액", "계산 방법"]] + [
            [r["name"] + ("" if r.get("taxable", True) else " (비과세)"), won(r["amount"]),
             Paragraph(r.get("calc", ""), S(8.5))] for r in rows
        ] + [[total_label, won(total), ""]]
        tb = Table(data, colWidths=[40 * mm, 34 * mm, 104 * mm], repeatRows=1)
        tb.setStyle(TableStyle([
            ("FONT", (0, 0), (-1, -1), font, 9.5),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4f46c9")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f1f0fd")),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9c8dc")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        return tb

    flow += [section("지급 항목", d["items"], "지급 총액", d["gross"]), Spacer(1, 4 * mm),
             section("공제 항목", d["deductions"], "공제 총액", d["total_deduction"]), Spacer(1, 4 * mm)]

    net = Table([["실수령액", won(d["net"])]], colWidths=[74 * mm, 104 * mm])
    net.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), font, 13),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#4f46c9")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    flow += [net, Spacer(1, 6 * mm)]

    # 근로시간 수는 명세서에 적어야 하는 계산 근거다(근로기준법 시행령 제27조의2).
    rows = [["날짜", "출근", "퇴근", "휴게", "근무", "비고"]]
    for x in d["days"]:
        note = []
        if x.get("auto_closed") and not x.get("edited"):
            note.append("자동 마감")
        if x.get("edited"):
            note.append("관리자 수정")
        rows.append([x["day"], x["first"], x["left"] or "-", f"{x['break']}분",
                     hm(x["minutes"]), ", ".join(note)])
    rows.append(["합계", "", "", "", hm(d["work_minutes"]), f"{d['work_days']}일"])
    dt = Table(rows, colWidths=[30 * mm, 22 * mm, 22 * mm, 20 * mm, 34 * mm, 50 * mm], repeatRows=1)
    dt.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), font, 8.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ebebf3")),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f1f0fd")),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d8d8e6")),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    flow += [Paragraph("근무 내역", S(11)), Spacer(1, 2 * mm), dt, Spacer(1, 5 * mm)]

    if d.get("weeks"):
        wr = [["주", "주 근무", "주휴 인정", "주휴수당"]] + [
            [f"{w['from']} ~ {w['to']}", hm(w["minutes"]),
             hm(w["juhyu_minutes"]) if w["eligible"] else ("15시간 미만" if w["finished"] else "진행 중"),
             won(w["pay"])] for w in d["weeks"]]
        wt = Table(wr, colWidths=[62 * mm, 34 * mm, 42 * mm, 40 * mm])
        wt.setStyle(TableStyle([
            ("FONT", (0, 0), (-1, -1), font, 8.5),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ebebf3")),
            ("ALIGN", (3, 0), (3, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d8d8e6")),
        ]))
        flow += [Paragraph("주휴수당 계산", S(11)), Spacer(1, 2 * mm), wt, Spacer(1, 5 * mm)]

    foot = ("근로기준법 제48조 제2항에 따른 임금명세서입니다. " if not freelancer else "") + \
           "휴게시간은 근무 4시간 이상 30분, 8시간 이상 1시간을 차감했습니다. " + \
           "공제액은 10원 미만을 버렸고, 4대보험·세액은 참고 계산으로 실제 고지·신고액과 다를 수 있습니다."
    if d.get("note"):
        flow.append(Paragraph("비고: " + d["note"], S(9)))
    flow += [Paragraph(foot, S(8, textColor=colors.HexColor("#6b6b85"))),
             Paragraph(f"확정 {d.get('finalized_at', '')} · {d['company']}", S(8, textColor=colors.HexColor("#6b6b85")))]
    doc.build(flow)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# 바깥으로
# ─────────────────────────────────────────────────────────────────────────────

class ProfileIn(BaseModel):
    employment: str = "employee"
    hourly_wage: int = Field(ge=0, le=1_000_000)
    meal_allowance: int = Field(default=0, ge=0, le=10_000_000)
    fixed_allowance: int = Field(default=0, ge=0, le=100_000_000)
    fixed_allowance_name: str = Field(default="직책수당", max_length=30)
    employee_no: str = Field(default="", max_length=30)
    department: str = Field(default="", max_length=40)


class SlipEdit(BaseModel):
    extras: Optional[List[dict]] = None
    income_tax: Optional[int] = Field(default=None, ge=0)
    overrides: Optional[Dict[str, int]] = None
    note: Optional[str] = Field(default=None, max_length=300)


def _user_or_404(db: Session, uid: int) -> WorkUser:
    u = db.get(WorkUser, uid)
    if u is None or u.role != "staff":
        raise HTTPException(status_code=404, detail="직원 계정이 아닙니다.")
    return u


@router.get("/payroll/settings")
def get_rates(user: WorkUser = Depends(admin_only), db: Session = Depends(get_db)):
    return rates(db)


@router.put("/payroll/settings")
def put_rates(body: dict, user: WorkUser = Depends(admin_only), db: Session = Depends(get_db)):
    for k, v in body.items():
        if k not in RATE_DEFAULTS:
            continue
        row = db.get(WorkSetting, "pay_" + k)
        if row is None:
            db.add(WorkSetting(key="pay_" + k, value=str(v)))
        else:
            row.value = str(v)
    db.commit()
    return rates(db)


@router.get("/payroll/profiles")
def list_profiles(user: WorkUser = Depends(admin_only), db: Session = Depends(get_db)):
    profs = {p.user_id: p for p in db.query(WorkPayProfile).all()}
    out = []
    for u in db.query(WorkUser).filter(WorkUser.role == "staff").order_by(WorkUser.name).all():
        p = profs.get(u.id)
        out.append({"user_id": u.id, "name": u.name, "is_active": u.is_active,
                    "employment": p.employment if p else "employee",
                    "hourly_wage": p.hourly_wage if p else 0,
                    "meal_allowance": p.meal_allowance if p else 0,
                    "fixed_allowance": p.fixed_allowance if p else 0,
                    "fixed_allowance_name": p.fixed_allowance_name if p else "직책수당",
                    "employee_no": p.employee_no if p else "",
                    "department": p.department if p else "",
                    "configured": p is not None})
    return out


@router.put("/payroll/profiles/{user_id}")
def put_profile(user_id: int, body: ProfileIn, user: WorkUser = Depends(admin_only),
                db: Session = Depends(get_db)):
    _user_or_404(db, user_id)
    if body.employment not in ("employee", "freelancer"):
        raise HTTPException(status_code=400, detail="근로자 또는 프리랜서만 고를 수 있습니다.")
    p = db.query(WorkPayProfile).filter(WorkPayProfile.user_id == user_id).first()
    if p is None:
        p = WorkPayProfile(user_id=user_id)
        db.add(p)
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    db.commit()
    return {"ok": True}


@router.get("/payroll")
def month_payroll(month: str, user: WorkUser = Depends(admin_only), db: Session = Depends(get_db)):
    month_days(month)
    sv = _settle_view(db, month)
    out = []
    for u in targets(db, month, sv):
        d = slip_view(db, u, month)
        out.append({k: d[k] for k in ("user_id", "name", "employment", "hourly_wage", "work_days",
                                      "work_minutes", "gross", "total_deduction", "net", "status", "warnings")})
    return {"month": month, "locked": _locked(db, month), "slips": out,
            "totals": {k: sum(x[k] for x in out) for k in ("gross", "total_deduction", "net")}}


@router.get("/payroll/slip")
def get_slip(month: str, user_id: Optional[int] = None,
             user: WorkUser = Depends(current_user), db: Session = Depends(get_db)):
    if user.role == "admin":
        target = _user_or_404(db, user_id or 0)
    elif user.role == "staff" and (user_id in (None, user.id)):
        target = user
    else:
        raise HTTPException(status_code=403, detail="볼 수 없는 명세서입니다.")
    d = slip_view(db, target, month)
    if user.role != "admin" and d["status"] != "final":
        raise HTTPException(status_code=404, detail="아직 확정되지 않은 달입니다.")
    return d


@router.patch("/payroll/slip")
def edit_slip(month: str, user_id: int, body: SlipEdit, user: WorkUser = Depends(admin_only),
              db: Session = Depends(get_db)):
    target = _user_or_404(db, user_id)
    if _locked(db, month):
        raise HTTPException(status_code=400, detail="정산 완료된 달입니다. 정산 완료를 취소하고 고쳐 주세요.")
    slip = db.query(WorkPayslip).filter(WorkPayslip.user_id == user_id, WorkPayslip.month == month).first()
    if slip is None:
        slip = WorkPayslip(user_id=user_id, month=month, name=target.name)
        db.add(slip)
    if body.extras is not None:
        clean = []
        for e in body.extras[:20]:
            name = str(e.get("name", "")).strip()[:30]
            if not name:
                continue
            clean.append({"name": name, "amount": int(e.get("amount", 0)),
                          "taxable": bool(e.get("taxable", True)), "calc": str(e.get("calc", ""))[:80]})
        slip.extras = json.dumps(clean, ensure_ascii=False)
    if body.income_tax is not None:
        slip.income_tax = body.income_tax
    if body.overrides is not None:
        slip.overrides = json.dumps({k: int(v) for k, v in body.overrides.items()})
    if body.note is not None:
        slip.note = body.note
    db.commit()
    return slip_view(db, target, month)


@router.get("/payroll/me")
def my_payslips(user: WorkUser = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "staff":
        raise HTTPException(status_code=403, detail="직원 계정만 볼 수 있습니다.")
    rows = (db.query(WorkPayslip)
            .filter(WorkPayslip.user_id == user.id, WorkPayslip.status == "final")
            .order_by(WorkPayslip.month.desc()).all())
    out = []
    for s in rows:
        d = json.loads(s.snapshot or "{}")
        out.append({"month": s.month, "gross": d.get("gross", 0), "total_deduction": d.get("total_deduction", 0),
                    "net": d.get("net", 0), "pay_date": d.get("pay_date", ""),
                    "work_minutes": d.get("work_minutes", 0)})
    return out


@router.get("/payroll/pdf")
def payslip_pdf(month: str, user_id: Optional[int] = None,
                user: WorkUser = Depends(current_user), db: Session = Depends(get_db)):
    if user.role == "admin":
        target = _user_or_404(db, user_id or 0)
    elif user.role == "staff" and user_id in (None, user.id):
        target = user
    else:
        raise HTTPException(status_code=403, detail="받을 수 없는 명세서입니다.")
    slip = db.query(WorkPayslip).filter(WorkPayslip.user_id == target.id, WorkPayslip.month == month).first()
    if slip is None or slip.status != "final" or not slip.snapshot:
        raise HTTPException(status_code=400, detail="정산 완료된 달만 PDF 로 받을 수 있습니다.")
    d = json.loads(slip.snapshot)
    d["finalized_at"] = (slip.finalized_at + KST).strftime("%Y-%m-%d %H:%M") if slip.finalized_at else ""
    pdf = render_pdf(d)
    from urllib.parse import quote
    fname = f"급여명세서_{month}_{target.name}.pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}"})
