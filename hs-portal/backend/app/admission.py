"""진학정보 — 학교가 직접 입력한 졸업생 진로 통계 (플래티넘 혜택 "admission_stats").

두 갈래로 나뉜다.

  · /api/school-admin/admission/…  학교 계정이 숫자를 넣고 고치는 곳.
    학교는 **토큰에서만** 정한다(경로에 학교 id 를 받지 않는다). 그래서
    다른 학교 행을 짚어도 "없는 행"이 될 뿐 고칠 길이 없다. 들어올 때마다
    플랜 혜택을 서버에서 다시 본다 — 화면에서 탭을 숨기는 것은 편의일 뿐이다.

  · /api/schools/{id}/admission, /api/admission/…  학생·방문자가 보는 곳.
    (1) 그 학교 플랜에 혜택이 켜져 있고 (2) 학교가 정한 공개 범위 안의
    사람이며 (3) 학교가 공개로 둔 연도·행만 집계한다.

**없는 숫자를 만들지 않는다.** 입력되지 않은 연도는 추세에서 빠지고,
졸업생 수가 0 이면 비율 대신 None 을 돌려준다. "최근 3년" 도 실제로 있는
연도만 쓰고, 몇 년치로 계산했는지를 함께 내보낸다.

엑셀(.xlsx)은 표준 라이브러리(zipfile + xml)로 읽고 쓴다. 우리가 다루는
것은 글자·정수뿐이라 이것으로 충분하고, 서버에 새 패키지를 깔 일이 없다.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Tuple
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from .auth import get_current_user_optional, require_school
from .database import get_db
from .models import (
    AdmissionEmployment,
    AdmissionRecord,
    AdmissionSetting,
    AdmissionStat,
    Plan,
    Role,
    School,
    SchoolVerification,
    User,
)

router = APIRouter(prefix="/api", tags=["admission"])

PERK_KEY = "admission_stats"

# ── 허용 값. 화면 표기는 여기 한 곳에서만 정한다. ─────────────────────────
UNIVERSITY_TYPES = {"4_YEAR": "4년제", "JUNIOR_COLLEGE": "전문대", "OTHER": "기타 교육기관"}

REGIONS = {
    "SEOUL": "서울", "CAPITAL_AREA": "경기·인천", "CHUNGCHEONG": "충청권",
    "YEONGNAM": "영남권", "HONAM": "호남권", "GANGWON": "강원권", "JEJU": "제주권",
    "OTHER": "기타",
}
CAPITAL_REGIONS = ("SEOUL", "CAPITAL_AREA")

DEPT_CATEGORIES = {
    "HUMANITIES": "인문사회", "BUSINESS": "경상계열", "NATURAL": "자연과학",
    "ENGINEERING": "공학", "IT_SOFTWARE": "IT/소프트웨어", "MEDICAL": "의약학",
    "ARTS": "예체능", "EDUCATION": "교육", "SERVICE": "서비스", "AGRICULTURE": "농림수산",
    "HEALTH": "보건", "OTHER": "기타",
}

EMPLOYMENT_FIELDS = {
    "IT_SOFTWARE": "IT/소프트웨어", "MANUFACTURING": "제조", "MACHINE": "기계",
    "ELECTRONICS": "전기전자", "SERVICE": "서비스", "FINANCE": "금융",
    "PUBLIC": "공공기관", "OTHER": "기타",
}

ADMISSION_TYPES = {"": "미입력", "EARLY": "수시", "REGULAR": "정시",
                   "SPECIAL": "특별전형", "OTHER": "기타"}

VISIBILITY = {"PUBLIC": "전체 공개", "MEMBERS": "로그인 사용자만",
              "STUDENTS": "우리 학교 학생만", "PRIVATE": "비공개"}

SCHOOL_TYPES = {"GENERAL_HIGH": "일반고", "VOCATIONAL_HIGH": "직업계고"}
# 학교 유형을 따로 정하지 않았을 때 계열로 판단한다. 종합고는 직업 과정이
# 있어 직업계고 화면(취업 지표 포함)을 기본으로 한다. 학교가 바꿀 수 있다.
VOCATIONAL_CATEGORIES = ("특성화고", "마이스터고", "종합고")

MIN_YEAR = 2000
MAX_COUNT = 100_000
TOP_N = 10

IMPORT_MAX_BYTES = 2 * 1024 * 1024
IMPORT_MAX_ROWS = 5000
# 압축을 푼 크기 상한. 2MB 짜리 xlsx 가 수 GB 로 부풀어 서버를 멈추게 하는
# 것(zip bomb)을 막는다.
XLSX_MAX_UNZIPPED = 40 * 1024 * 1024

DISCLAIMER = [
    "본 취업/진학 정보는 해당 학교가 직접 입력한 데이터를 기반으로 합니다.",
    "입력된 데이터를 기준으로 통계가 산출되며, 입력되지 않은 정보는 임의로 추가하거나 추정하지 않습니다.",
    "연도 및 데이터 입력 방식에 따라 실제 진학 결과와 차이가 있을 수 있습니다.",
]


def max_year() -> int:
    return date.today().year


def labels_payload() -> dict:
    as_list = lambda d: [{"key": k, "label": v} for k, v in d.items()]  # noqa: E731
    return {
        "university_types": as_list(UNIVERSITY_TYPES),
        "regions": as_list(REGIONS),
        "department_categories": as_list(DEPT_CATEGORIES),
        "employment_fields": as_list(EMPLOYMENT_FIELDS),
        "admission_types": [x for x in as_list(ADMISSION_TYPES) if x["key"]],
        "visibility": as_list(VISIBILITY),
        "school_types": as_list(SCHOOL_TYPES),
        "min_year": MIN_YEAR,
        "max_year": max_year(),
    }


# ══════════════════════════════════════════════════════════════
#  권한
# ══════════════════════════════════════════════════════════════
def has_perk(db: Session, school: School) -> bool:
    # main.py 가 이 모듈을 불러오므로 위에서 import 하면 순환한다.
    from .main import school_has_perk
    return school_has_perk(db, school, PERK_KEY)


def get_setting(db: Session, school_id: int) -> AdmissionSetting:
    """행이 없으면 저장하지 않은 기본값을 돌려준다(비공개)."""
    row = db.get(AdmissionSetting, school_id)
    return row or AdmissionSetting(school_id=school_id, visibility="PRIVATE",
                                   school_type="", small_count_threshold=0)


def school_type_of(school: School, setting: AdmissionSetting) -> str:
    if setting.school_type in SCHOOL_TYPES:
        return setting.school_type
    return "VOCATIONAL_HIGH" if school.category in VOCATIONAL_CATEGORIES else "GENERAL_HIGH"


def manage_school(db: Session, user: User) -> School:
    """학교 계정 + 플랜 혜택. 관리 API 는 전부 이걸 먼저 지난다."""
    if not user.school_id:
        raise HTTPException(status_code=400, detail="계정에 연결된 학교가 없습니다.")
    school = db.get(School, user.school_id)
    if not school:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")
    if not has_perk(db, school):
        raise HTTPException(
            status_code=403,
            detail="진학정보는 플래티넘 플랜 전용 기능입니다. 플랜을 확인해주세요.",
        )
    return school


def _belongs_to(db: Session, user: User, school_id: int) -> bool:
    """이 학교 사람인가 — 학교 계정·선생님·재학생(인증 승인)."""
    if user.school_id == school_id and user.role in (Role.school, Role.teacher, Role.student):
        return True
    if user.role == Role.student:
        return db.query(SchoolVerification.id).filter(
            SchoolVerification.user_id == user.id,
            SchoolVerification.school_id == school_id,
            SchoolVerification.status == "approved",
        ).first() is not None
    return False


def check_view(db: Session, school: School, setting: AdmissionSetting,
               user: Optional[User]) -> None:
    """볼 수 없으면 예외. 비공개·혜택 없음은 '없는 페이지'(404)로 돌려 존재도
    드러내지 않는다. 로그인·소속 제한은 무엇이 필요한지 알려준다."""
    if user is not None and user.role == Role.admin:
        return
    if not has_perk(db, school):
        raise HTTPException(status_code=404, detail="이 학교는 진학정보를 제공하지 않습니다.")
    # 학교 계정·선생님은 공개 범위와 상관없이 우리 학교 화면을 미리 볼 수 있다.
    if user is not None and user.school_id == school.id and user.role in (Role.school, Role.teacher):
        return
    vis = setting.visibility
    if vis == "PUBLIC":
        return
    if vis == "MEMBERS":
        if user is None:
            raise HTTPException(status_code=401, detail="로그인한 사용자만 볼 수 있는 진학정보입니다.")
        return
    if vis == "STUDENTS":
        if user is None:
            raise HTTPException(status_code=401, detail="이 학교 학생만 볼 수 있는 진학정보입니다. 로그인해주세요.")
        if not _belongs_to(db, user, school.id):
            raise HTTPException(status_code=403, detail="이 학교 학생만 볼 수 있는 진학정보입니다.")
        return
    raise HTTPException(status_code=404, detail="이 학교는 진학정보를 제공하지 않습니다.")


def can_view(db: Session, school: School, setting: AdmissionSetting,
             user: Optional[User]) -> bool:
    try:
        check_view(db, school, setting, user)
        return True
    except HTTPException:
        return False


def published_years(db: Session, school_id: int) -> List[int]:
    rows = db.query(AdmissionStat.year).filter(
        AdmissionStat.school_id == school_id, AdmissionStat.is_published.is_(True),
    ).order_by(AdmissionStat.year.desc()).all()
    return [r[0] for r in rows]


def is_indexable(db: Session, school: School) -> bool:
    """검색엔진에 내보낼 페이지인가 — 전체 공개 + 혜택 + 공개 연도가 있음."""
    return (get_setting(db, school.id).visibility == "PUBLIC"
            and has_perk(db, school) and bool(published_years(db, school.id)))


# ── 주요 취업처 ────────────────────────────────────────────────
# School.major_employers 한 칸에 줄바꿈으로 담는다(학과 목록과 같은 방식).
MAX_EMPLOYERS = 30
MAX_EMPLOYER_LEN = 60


def clean_employers(raw) -> List[str]:
    """줄바꿈·쉼표 문자열이나 목록을 받아 빈 줄·중복을 뺀 목록으로."""
    if raw is None:
        return []
    parts = raw if isinstance(raw, list) else re.split(r"[\n,]", str(raw))
    out: List[str] = []
    for p in parts:
        name = " ".join(str(p or "").split())[:MAX_EMPLOYER_LEN]
        if name and name not in out:
            out.append(name)
    if len(out) > MAX_EMPLOYERS:
        raise HTTPException(status_code=422, detail=f"주요 취업처는 {MAX_EMPLOYERS}곳까지 적을 수 있습니다.")
    return out


def join_employers(items: List[str]) -> str:
    return "\n".join(items)


def employers_of(school: School) -> List[str]:
    return [x.strip() for x in (school.major_employers or "").splitlines() if x.strip()]


def has_viewable_info(db: Session, school: School, user: Optional[User]) -> bool:
    """학교 상세에 '취업/진학 정보' 링크를 띄울지. 볼 수 없는 사람에게는 안 띄운다.
    진학 통계가 없어도 주요 취업처가 있으면 띄운다."""
    if not published_years(db, school.id) and not employers_of(school):
        return False
    return can_view(db, school, get_setting(db, school.id), user)


# ══════════════════════════════════════════════════════════════
#  입력값 검증 — API 와 엑셀 업로드가 같은 규칙을 쓴다
# ══════════════════════════════════════════════════════════════
def _squash(s) -> str:
    return re.sub(r"[\s·/．.,_\-]", "", str(s or "")).upper()


def _alias_map(base: Dict[str, str], extra: Dict[str, Iterable[str]]) -> Dict[str, str]:
    m = {}
    for code, label in base.items():
        m[_squash(code)] = code
        m[_squash(label)] = code
    for code, words in extra.items():
        for w in words:
            m[_squash(w)] = code
    return m


_UNIV_ALIAS = _alias_map(UNIVERSITY_TYPES, {
    "4_YEAR": ["4년제", "4년제대학", "대학교", "FOUR_YEAR", "4YEAR"],
    "JUNIOR_COLLEGE": ["전문대학", "전문대", "2년제", "3년제"],
    "OTHER": ["기타", "기타교육기관", "사이버대", "기능대"],
})
_REGION_ALIAS = _alias_map(REGIONS, {
    "SEOUL": ["서울특별시", "서울시"],
    "CAPITAL_AREA": ["경기", "인천", "경기도", "인천광역시", "경기인천", "수도권"],
    "CHUNGCHEONG": ["충청", "충북", "충남", "대전", "세종", "충청북도", "충청남도"],
    "YEONGNAM": ["영남", "부산", "대구", "울산", "경북", "경남", "경상북도", "경상남도"],
    "HONAM": ["호남", "광주", "전북", "전남", "전라북도", "전라남도"],
    "GANGWON": ["강원", "강원도"],
    "JEJU": ["제주", "제주도"],
    "OTHER": ["해외", "기타"],
})
_CAT_ALIAS = _alias_map(DEPT_CATEGORIES, {
    "HUMANITIES": ["인문", "사회", "인문계열", "사회계열"],
    "BUSINESS": ["경상", "경영", "경제", "상경"],
    "NATURAL": ["자연", "자연계열"],
    "ENGINEERING": ["공학계열", "공과"],
    "IT_SOFTWARE": ["IT", "소프트웨어", "IT소프트웨어", "정보통신", "컴퓨터"],
    "MEDICAL": ["의약", "의학", "약학"],
    "ARTS": ["예체능계열", "예술", "체육", "디자인"],
    "EDUCATION": ["교육계열", "사범"],
    "AGRICULTURE": ["농림", "수산", "농업"],
    "HEALTH": ["보건계열", "간호"],
})
_ADM_ALIAS = _alias_map({k: v for k, v in ADMISSION_TYPES.items() if k}, {
    "SPECIAL": ["특별", "특성화고특별전형", "재직자전형"],
})


def _to_int(v) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    s = str(v).strip().replace(",", "")
    if s == "":
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    if f != int(f):
        return None
    return int(f)


def _year_ok(y: Optional[int]) -> bool:
    return y is not None and MIN_YEAR <= y <= max_year()


def clean_record(raw: dict) -> Tuple[Optional[dict], List[str]]:
    """대학 진학 한 줄을 검사한다. 코드(4_YEAR)든 한글(4년제)이든 받는다."""
    errs: List[str] = []
    year = _to_int(raw.get("year"))
    if not _year_ok(year):
        errs.append(f"연도 형식 오류 ({MIN_YEAR}~{max_year()} 사이 숫자)")
    uname = str(raw.get("university_name") or "").strip()
    if not uname:
        errs.append("대학명 누락")
    elif len(uname) > 80:
        errs.append("대학명이 너무 깁니다(80자)")
    utype_raw = raw.get("university_type")
    utype = _UNIV_ALIAS.get(_squash(utype_raw))
    if not str(utype_raw or "").strip():
        errs.append("대학 유형 누락")
    elif not utype:
        errs.append(f"대학 유형을 알 수 없음: {utype_raw} (4년제/전문대/기타)")
    region_raw = raw.get("region")
    region = _REGION_ALIAS.get(_squash(region_raw))
    if not str(region_raw or "").strip():
        errs.append("지역 누락")
    elif not region:
        errs.append(f"지역을 알 수 없음: {region_raw}")
    dname = str(raw.get("department_name") or "").strip()
    if not dname:
        errs.append("학과명 누락")
    elif len(dname) > 80:
        errs.append("학과명이 너무 깁니다(80자)")
    cat_raw = raw.get("department_category")
    cat = _CAT_ALIAS.get(_squash(cat_raw))
    if not str(cat_raw or "").strip():
        errs.append("학과 계열 누락")
    elif not cat:
        errs.append(f"학과 계열을 알 수 없음: {cat_raw}")
    adm_raw = str(raw.get("admission_type") or "").strip()
    adm = _ADM_ALIAS.get(_squash(adm_raw), None) if adm_raw else ""
    if adm is None:
        errs.append(f"전형을 알 수 없음: {adm_raw} (수시/정시/특별전형/기타 또는 비움)")
    cnt = _to_int(raw.get("student_count"))
    if cnt is None:
        errs.append("진학자 수가 숫자가 아님")
    elif cnt < 0:
        errs.append("진학자 수 < 0")
    elif cnt == 0:
        errs.append("진학자 수는 1명 이상")
    elif cnt > MAX_COUNT:
        errs.append("진학자 수가 너무 큽니다")
    if errs:
        return None, errs
    return {
        "year": year, "university_name": uname, "university_type": utype,
        "region": region, "department_name": dname, "department_category": cat,
        "admission_type": adm or "", "student_count": cnt,
        "is_published": bool(raw.get("is_published", True)),
    }, []


STAT_COUNT_FIELDS = ("total_graduates", "four_year_count", "junior_college_count",
                     "other_higher_count", "employment_count", "other_count")


class StatIn(BaseModel):
    total_graduates: int = Field(ge=0, le=MAX_COUNT)
    four_year_count: int = Field(0, ge=0, le=MAX_COUNT)
    junior_college_count: int = Field(0, ge=0, le=MAX_COUNT)
    other_higher_count: int = Field(0, ge=0, le=MAX_COUNT)
    employment_count: int = Field(0, ge=0, le=MAX_COUNT)
    other_count: int = Field(0, ge=0, le=MAX_COUNT)
    same_field_count: Optional[int] = Field(None, ge=0, le=MAX_COUNT)
    diff_field_count: Optional[int] = Field(None, ge=0, le=MAX_COUNT)
    is_published: bool = True


def stat_errors(p: StatIn) -> List[str]:
    errs = []
    adm = p.four_year_count + p.junior_college_count + p.other_higher_count
    if adm > p.total_graduates:
        errs.append(f"진학자 수({adm}) > 졸업생 수({p.total_graduates})")
    total = adm + p.employment_count + p.other_count
    if total > p.total_graduates:
        errs.append(f"취업자 + 진학자 + 기타({total}) > 졸업생 수({p.total_graduates})")
    same = (p.same_field_count or 0) + (p.diff_field_count or 0)
    if same > adm:
        errs.append(f"동일·비동일계열 진학 합계({same}) > 진학자 수({adm})")
    return errs


class RecordBatchIn(BaseModel):
    rows: List[dict] = Field(min_length=1, max_length=500)


class SettingsIn(BaseModel):
    visibility: str
    school_type: str = ""
    small_count_threshold: int = Field(0, ge=0, le=10)


class EmploymentIn(BaseModel):
    items: Dict[str, int]


# ══════════════════════════════════════════════════════════════
#  집계
# ══════════════════════════════════════════════════════════════
def _rate(n: Optional[int], total: Optional[int]) -> Optional[float]:
    if not total or n is None:
        return None
    return round(n * 100.0 / total, 1)


def stat_out(s: AdmissionStat) -> dict:
    adm = s.four_year_count + s.junior_college_count + s.other_higher_count
    g = s.total_graduates
    return {
        "id": s.id, "year": s.year, "total_graduates": g,
        "four_year_count": s.four_year_count, "junior_college_count": s.junior_college_count,
        "other_higher_count": s.other_higher_count, "admission_count": adm,
        "employment_count": s.employment_count, "other_count": s.other_count,
        "same_field_count": s.same_field_count, "diff_field_count": s.diff_field_count,
        "admission_rate": _rate(adm, g), "four_year_rate": _rate(s.four_year_count, g),
        "junior_college_rate": _rate(s.junior_college_count, g),
        "other_higher_rate": _rate(s.other_higher_count, g),
        "employment_rate": _rate(s.employment_count, g), "other_rate": _rate(s.other_count, g),
        "is_published": bool(s.is_published),
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _sum_stats(stats: List[AdmissionStat]) -> Optional[dict]:
    """여러 해를 더한 값. 비율은 합계끼리 나눈다(연도별 비율의 평균이 아니다 —
    졸업생 수가 다른 해를 똑같이 치면 작은 해가 과하게 반영된다)."""
    if not stats:
        return None
    agg = AdmissionStat(year=0, total_graduates=0, four_year_count=0, junior_college_count=0,
                        other_higher_count=0, employment_count=0, other_count=0)
    same = diff = None
    for s in stats:
        for f in STAT_COUNT_FIELDS:
            setattr(agg, f, getattr(agg, f) + (getattr(s, f) or 0))
        if s.same_field_count is not None:
            same = (same or 0) + s.same_field_count
        if s.diff_field_count is not None:
            diff = (diff or 0) + s.diff_field_count
    agg.same_field_count, agg.diff_field_count = same, diff
    agg.is_published = True
    out = stat_out(agg)
    out.pop("id"); out.pop("updated_at")
    out["year"] = None
    out["years"] = sorted(s.year for s in stats)
    return out


def _dist(pairs: Iterable[Tuple[str, int]], labels: Dict[str, str]) -> List[dict]:
    pairs = [(k, int(v or 0)) for k, v in pairs if v]
    total = sum(v for _, v in pairs)
    order = list(labels.keys())
    pairs.sort(key=lambda kv: (-kv[1], order.index(kv[0]) if kv[0] in order else 99))
    return [{"key": k, "label": labels.get(k, k), "count": v, "percent": _rate(v, total)}
            for k, v in pairs]


def _mask(count: int, threshold: int) -> dict:
    if threshold and count < threshold:
        return {"count": None, "masked": True}
    return {"count": count, "masked": False}


class RecordFilter:
    def __init__(self, years: List[int], university_type: str = "", region: str = "",
                 department_category: str = "", published_only: bool = True):
        self.years = years
        self.university_type = university_type if university_type in UNIVERSITY_TYPES else ""
        self.region = region if region in REGIONS else ""
        self.department_category = (department_category
                                    if department_category in DEPT_CATEGORIES else "")
        self.published_only = published_only

    def apply(self, q, school_id: int):
        q = q.filter(AdmissionRecord.school_id == school_id)
        if self.years:
            q = q.filter(AdmissionRecord.year.in_(self.years))
        if self.published_only:
            q = q.filter(AdmissionRecord.is_published.is_(True))
        if self.university_type:
            q = q.filter(AdmissionRecord.university_type == self.university_type)
        if self.region:
            q = q.filter(AdmissionRecord.region == self.region)
        if self.department_category:
            q = q.filter(AdmissionRecord.department_category == self.department_category)
        return q


def _group(db: Session, school_id: int, flt: RecordFilter, col) -> List[Tuple[str, int]]:
    total = func.sum(AdmissionRecord.student_count)
    return flt.apply(db.query(col, total), school_id).group_by(col).all()


def _top(db: Session, school_id: int, flt: RecordFilter, name_col, extra_cols,
         threshold: int, limit: int = TOP_N) -> List[dict]:
    total = func.sum(AdmissionRecord.student_count).label("n")
    q = flt.apply(db.query(name_col, *[func.max(c) for c in extra_cols], total), school_id)
    rows = q.group_by(name_col).order_by(total.desc(), name_col.asc()).limit(limit).all()
    out = []
    for r in rows:
        item = {"name": r[0], **_mask(int(r[-1] or 0), threshold)}
        for i, c in enumerate(extra_cols):
            item[c.key] = r[1 + i]
        out.append(item)
    return out


def _record_block(db: Session, school_id: int, flt: RecordFilter, threshold: int) -> dict:
    n_total = flt.apply(db.query(func.coalesce(func.sum(AdmissionRecord.student_count), 0)),
                        school_id).scalar() or 0
    return {
        "record_total": int(n_total),
        "region_distribution": _dist(_group(db, school_id, flt, AdmissionRecord.region), REGIONS),
        "record_type_distribution": _dist(
            _group(db, school_id, flt, AdmissionRecord.university_type), UNIVERSITY_TYPES),
        "category_distribution": _dist(
            _group(db, school_id, flt, AdmissionRecord.department_category), DEPT_CATEGORIES),
        "top_universities": [
            {**u, "university_type_label": UNIVERSITY_TYPES.get(u["university_type"], ""),
             "region_label": REGIONS.get(u["region"], "")}
            for u in _top(db, school_id, flt, AdmissionRecord.university_name,
                          [AdmissionRecord.university_type, AdmissionRecord.region], threshold)
        ],
        "top_departments": [
            {**d, "department_category_label":
                DEPT_CATEGORIES.get(d["department_category"], "")}
            for d in _top(db, school_id, flt, AdmissionRecord.department_name,
                          [AdmissionRecord.department_category], threshold)
        ],
    }


def _employment(db: Session, school_id: int, years: List[int]) -> List[dict]:
    if not years:
        return []
    rows = db.query(AdmissionEmployment.field, func.sum(AdmissionEmployment.count)).filter(
        AdmissionEmployment.school_id == school_id, AdmissionEmployment.year.in_(years),
    ).group_by(AdmissionEmployment.field).all()
    return _dist(rows, EMPLOYMENT_FIELDS)


def _path_distribution(summary: Optional[dict]) -> List[dict]:
    """졸업 후 진로(대학 진학 / 취업 / 기타). 합이 졸업생 수와 다르면 '미입력'
    으로 남은 인원을 따로 보여준다 — 억지로 어디에 붙이지 않는다."""
    if not summary or not summary["total_graduates"]:
        return []
    g = summary["total_graduates"]
    parts = [("ADMISSION", "대학 진학", summary["admission_count"]),
             ("EMPLOYMENT", "취업", summary["employment_count"]),
             ("OTHER", "기타", summary["other_count"])]
    rest = g - sum(p[2] for p in parts)
    if rest > 0:
        parts.append(("UNKNOWN", "미입력", rest))
    return [{"key": k, "label": l, "count": n, "percent": _rate(n, g)} for k, l, n in parts if n]


def _type_distribution(summary: Optional[dict]) -> List[dict]:
    if not summary:
        return []
    adm = summary["admission_count"]
    parts = [("4_YEAR", summary["four_year_count"]),
             ("JUNIOR_COLLEGE", summary["junior_college_count"]),
             ("OTHER", summary["other_higher_count"])]
    return [{"key": k, "label": UNIVERSITY_TYPES[k], "count": n, "percent": _rate(n, adm)}
            for k, n in parts if n]


def _recent3(db: Session, school: School, stats_by_year: Dict[int, AdmissionStat]) -> dict:
    years = sorted(stats_by_year, reverse=True)[:3]
    if not years:
        return {"available": False, "message": "최근 3년 데이터를 확인할 수 없습니다.",
                "years": []}
    agg = _sum_stats([stats_by_year[y] for y in years])
    flt = RecordFilter(years)
    by_region = dict(_group(db, school.id, flt, AdmissionRecord.region))
    rec_total = sum(int(v or 0) for v in by_region.values())
    capital = sum(int(by_region.get(r) or 0) for r in CAPITAL_REGIONS)
    return {
        "available": True,
        "years": sorted(years),
        "year_count": len(years),
        # 3개년이 다 없으면 화면에서 "최근 N개년" 으로 고쳐 부른다.
        "complete": len(years) == 3,
        "total_graduates": agg["total_graduates"],
        "admission_rate": agg["admission_rate"],
        "four_year_rate": agg["four_year_rate"],
        "junior_college_rate": agg["junior_college_rate"],
        "employment_rate": agg["employment_rate"],
        # 수도권 비율은 졸업생이 아니라 '대학별 입력 인원' 이 기준이다.
        "capital_area_ratio": _rate(capital, rec_total),
        "capital_area_basis": rec_total,
        "summary": agg,
    }


def _profile(db: Session, school: School, stype: str, recent: dict) -> dict:
    base = {"school_type": stype, "school_type_label": SCHOOL_TYPES[stype]}
    if not recent.get("available"):
        return {**base, "available": False, "message": "최근 3년 데이터를 확인할 수 없습니다."}
    s = recent["summary"]
    paths = [("4년제 대학", s["four_year_count"]), ("전문대", s["junior_college_count"]),
             ("기타 교육기관", s["other_higher_count"])]
    if stype == "VOCATIONAL_HIGH" or s["employment_count"]:
        paths.append(("취업", s["employment_count"]))
    paths = [p for p in sorted(paths, key=lambda p: -p[1]) if p[1] > 0]
    flt = RecordFilter(recent["years"])
    regions = _dist(_group(db, school.id, flt, AdmissionRecord.region), REGIONS)[:2]
    cats = _dist(_group(db, school.id, flt, AdmissionRecord.department_category),
                 DEPT_CATEGORIES)[:3]
    univs = _top(db, school.id, flt, AdmissionRecord.university_name, [], 0, limit=3)
    return {
        **base, "available": True, "years": recent["years"],
        "total_graduates": s["total_graduates"],
        "admission_rate": s["admission_rate"], "four_year_rate": s["four_year_rate"],
        "junior_college_rate": s["junior_college_rate"],
        "employment_rate": s["employment_rate"],
        "main_paths": [p[0] for p in paths[:3]],
        "main_regions": [r["label"] for r in regions],
        "main_categories": [c["label"] for c in cats],
        "main_universities": [u["name"] for u in univs],
    }


def _last_updated(db: Session, school_id: int, published_only: bool) -> Optional[str]:
    cands = []
    for model in (AdmissionStat, AdmissionRecord):
        q = db.query(func.max(model.updated_at)).filter(model.school_id == school_id)
        if published_only:
            q = q.filter(model.is_published.is_(True))
        cands.append(q.scalar())
    cands.append(db.query(func.max(AdmissionEmployment.updated_at)).filter(
        AdmissionEmployment.school_id == school_id).scalar())
    cands = [c for c in cands if c]
    return max(cands).isoformat() if cands else None


def build_public(db: Session, school: School, setting: AdmissionSetting, year: str = "",
                 university_type: str = "", region: str = "",
                 department_category: str = "") -> dict:
    stats = db.query(AdmissionStat).filter(
        AdmissionStat.school_id == school.id, AdmissionStat.is_published.is_(True),
    ).order_by(AdmissionStat.year.asc()).all()
    by_year = {s.year: s for s in stats}
    years_desc = sorted(by_year, reverse=True)
    stype = school_type_of(school, setting)
    threshold = setting.small_count_threshold or 0

    if year == "recent3":
        sel_years = years_desc[:3]
        summary = _sum_stats([by_year[y] for y in sel_years])
    else:
        y = _to_int(year)
        y = y if y in by_year else (years_desc[0] if years_desc else None)
        sel_years = [y] if y is not None else []
        summary = stat_out(by_year[y]) if y is not None else None
        year = str(y) if y is not None else ""

    flt = RecordFilter(sel_years, university_type, region, department_category)
    recent = _recent3(db, school, by_year)
    trend = [
        {k: stat_out(by_year[y])[k] for k in (
            "year", "total_graduates", "admission_rate", "four_year_rate",
            "junior_college_rate", "employment_rate")}
        for y in sorted(by_year)[-5:]
    ]
    return {
        "school": {"id": school.id, "name": school.name, "category": school.category,
                   "region": school.region},
        "school_type": stype, "school_type_label": SCHOOL_TYPES[stype],
        "visibility": setting.visibility,
        "indexable": setting.visibility == "PUBLIC" and bool(by_year),
        "years": years_desc,
        "selected_year": year,
        "selected_years": sorted(sel_years),
        "filters": {"university_type": flt.university_type, "region": flt.region,
                    "department_category": flt.department_category},
        "summary": summary,
        "path_distribution": _path_distribution(summary),
        "type_distribution": _type_distribution(summary),
        **(_record_block(db, school.id, flt, threshold) if sel_years else {
            "record_total": 0, "region_distribution": [], "record_type_distribution": [],
            "category_distribution": [], "top_universities": [], "top_departments": []}),
        "employment_fields": _employment(db, school.id, sel_years),
        "major_employers": employers_of(school),
        "trend": trend,
        "recent3": {k: v for k, v in recent.items() if k != "summary"},
        "profile": _profile(db, school, stype, recent),
        "small_count_threshold": threshold,
        "last_updated": _last_updated(db, school.id, True),
        "disclaimer": DISCLAIMER,
        "labels": labels_payload(),
    }


# ══════════════════════════════════════════════════════════════
#  공개 API
# ══════════════════════════════════════════════════════════════
@router.get("/schools/{school_id}/admission")
def public_admission(
    school_id: int,
    year: str = Query("", max_length=10),
    university_type: str = Query("", max_length=20),
    region: str = Query("", max_length=20),
    department_category: str = Query("", max_length=20),
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    school = db.get(School, school_id)
    if not school or (not school.is_visible and not (user and user.role == Role.admin)):
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")
    setting = get_setting(db, school.id)
    check_view(db, school, setting, user)
    data = build_public(db, school, setting, year, university_type, region, department_category)
    # 공개 범위가 아닌 사람이 미리보기로 보는 경우(학교 본인·관리자) 검색엔진
    # 표시는 실제 설정을 따른다.
    data["indexable"] = data["indexable"] and has_perk(db, school)
    return data


def _ids(ids: str) -> List[int]:
    try:
        out = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="id 형식이 올바르지 않습니다.")
    return list(dict.fromkeys(out))[:3]


@router.get("/admission/compare")
def compare_admission(
    ids: str = Query(..., max_length=60, description="쉼표로 구분한 학교 id (최대 3개)"),
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """학교 간 비교. 학교마다 기준 연도·졸업생 수가 다를 수 있어 함께 싣는다."""
    out = []
    for sid in _ids(ids):
        school = db.get(School, sid)
        if not school or not school.is_visible:
            continue
        setting = get_setting(db, sid)
        base = {"school": {"id": school.id, "name": school.name, "category": school.category}}
        if not can_view(db, school, setting, user):
            out.append({**base, "available": False,
                        "message": "진학정보를 볼 수 없는 학교입니다."})
            continue
        data = build_public(db, school, setting, "recent3")
        out.append({
            **base, "available": bool(data["years"]),
            "school_type_label": data["school_type_label"],
            "recent3": data["recent3"],
            "top_universities": data["top_universities"][:5],
            "top_departments": data["top_departments"][:5],
            "region_distribution": data["region_distribution"],
            "category_distribution": data["category_distribution"],
            "trend": data["trend"],
        })
    return out


@router.get("/admission/interest")
def interest_admission(
    category: str = Query(..., max_length=20),
    ids: str = Query(..., max_length=60),
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """희망 계열(예: IT/소프트웨어)로 최근 3개년 진학 사례를 학교별로 본다."""
    if category not in DEPT_CATEGORIES:
        raise HTTPException(status_code=422, detail="알 수 없는 학과 계열입니다.")
    out = []
    for sid in _ids(ids):
        school = db.get(School, sid)
        if not school or not school.is_visible:
            continue
        setting = get_setting(db, sid)
        if not can_view(db, school, setting, user):
            continue
        years = published_years(db, sid)[:3]
        flt = RecordFilter(years, department_category=category)
        n = flt.apply(db.query(func.coalesce(func.sum(AdmissionRecord.student_count), 0)),
                      sid).scalar() if years else 0
        tops = _top(db, sid, flt, AdmissionRecord.university_name, [],
                    setting.small_count_threshold or 0, limit=3) if years else []
        out.append({"school": {"id": school.id, "name": school.name},
                    "category": category, "category_label": DEPT_CATEGORIES[category],
                    "years": sorted(years), "count": int(n or 0),
                    "top_universities": tops})
    return out


# ══════════════════════════════════════════════════════════════
#  학교 관리 API
# ══════════════════════════════════════════════════════════════
@router.get("/school-admin/admission/access")
def admission_access(db: Session = Depends(get_db), user: User = Depends(require_school)):
    """탭을 열 때 안내 화면을 띄울지 정한다. 데이터는 싣지 않는다."""
    if not user.school_id:
        raise HTTPException(status_code=400, detail="계정에 연결된 학교가 없습니다.")
    school = db.get(School, user.school_id)
    if not school:
        raise HTTPException(status_code=404, detail="학교를 찾을 수 없습니다.")
    return {"allowed": has_perk(db, school), "plan": school.plan.value,
            "plan_paused": bool(school.plan_paused), "required_plan": Plan.platinum.value}


def _records_sum(db: Session, school_id: int, year: int, exclude_id: int = 0) -> int:
    q = db.query(func.coalesce(func.sum(AdmissionRecord.student_count), 0)).filter(
        AdmissionRecord.school_id == school_id, AdmissionRecord.year == year)
    if exclude_id:
        q = q.filter(AdmissionRecord.id != exclude_id)
    return int(q.scalar() or 0)


def _graduates(db: Session, school_id: int, year: int) -> Optional[int]:
    s = db.query(AdmissionStat.total_graduates).filter(
        AdmissionStat.school_id == school_id, AdmissionStat.year == year).first()
    return s[0] if s else None


def record_out(r: AdmissionRecord) -> dict:
    return {
        "id": r.id, "year": r.year, "university_name": r.university_name,
        "university_type": r.university_type,
        "university_type_label": UNIVERSITY_TYPES.get(r.university_type, r.university_type),
        "region": r.region, "region_label": REGIONS.get(r.region, r.region),
        "department_name": r.department_name,
        "department_category": r.department_category,
        "department_category_label": DEPT_CATEGORIES.get(r.department_category,
                                                         r.department_category),
        "admission_type": r.admission_type or "",
        "student_count": r.student_count, "is_published": bool(r.is_published),
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def settings_out(school: School, s: AdmissionSetting) -> dict:
    return {"visibility": s.visibility, "visibility_label": VISIBILITY.get(s.visibility, ""),
            "school_type": s.school_type or "",
            "effective_school_type": school_type_of(school, s),
            "small_count_threshold": s.small_count_threshold or 0,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None}


@router.get("/school-admin/admission")
def admission_dashboard(db: Session = Depends(get_db), user: User = Depends(require_school)):
    school = manage_school(db, user)
    setting = get_setting(db, school.id)
    stats = db.query(AdmissionStat).filter(AdmissionStat.school_id == school.id) \
        .order_by(AdmissionStat.year.desc()).all()
    per_year = {
        y: {"records": int(n or 0), "rows": int(c or 0), "universities": int(u or 0),
            "departments": int(d or 0)}
        for y, n, c, u, d in db.query(
            AdmissionRecord.year, func.sum(AdmissionRecord.student_count),
            func.count(AdmissionRecord.id),
            func.count(func.distinct(AdmissionRecord.university_name)),
            func.count(func.distinct(AdmissionRecord.department_name)),
        ).filter(AdmissionRecord.school_id == school.id).group_by(AdmissionRecord.year).all()
    }
    emp = {}
    for y, f, n in db.query(AdmissionEmployment.year, AdmissionEmployment.field,
                            AdmissionEmployment.count).filter(
            AdmissionEmployment.school_id == school.id).all():
        emp.setdefault(y, {})[f] = n

    years = sorted(set(per_year) | {s.year for s in stats}, reverse=True)
    rows = []
    by_year = {s.year: s for s in stats}
    for y in years:
        st = stat_out(by_year[y]) if y in by_year else None
        rec = per_year.get(y, {"records": 0, "rows": 0, "universities": 0, "departments": 0})
        warnings = []
        if st is None:
            warnings.append("졸업생 기본 통계가 없습니다. 비율을 계산할 수 없습니다.")
        elif rec["records"] > st["admission_count"]:
            # 주요대학만 적는 칸이라 합계가 진학자보다 적은 것은 정상이다(2026-09-28).
            # 더 많을 때만 알린다 — 그건 어딘가 잘못 적은 것이다.
            warnings.append(
                f"주요대학 입력 인원 합계({rec['records']}명)가 기본 통계의 대학 진학자"
                f"({st['admission_count']}명)보다 많습니다.")
        emp_sum = sum(emp.get(y, {}).values())
        if st is not None and emp_sum and emp_sum != st["employment_count"]:
            warnings.append(
                f"취업 분야 합계({emp_sum}명)와 기본 통계의 취업자({st['employment_count']}명)가 다릅니다.")
        rows.append({"year": y, "stat": st, **rec, "employment": emp.get(y, {}),
                     "warnings": warnings})
    return {
        "school": {"id": school.id, "name": school.name, "category": school.category},
        "settings": settings_out(school, setting),
        "major_employers": employers_of(school),
        "years": rows,
        "last_updated": _last_updated(db, school.id, False),
        "indexable": is_indexable(db, school),
        "labels": labels_payload(),
        "disclaimer": DISCLAIMER,
    }


@router.put("/school-admin/admission/settings")
def admission_save_settings(payload: SettingsIn, db: Session = Depends(get_db),
                            user: User = Depends(require_school)):
    school = manage_school(db, user)
    if payload.visibility not in VISIBILITY:
        raise HTTPException(status_code=422, detail="알 수 없는 공개 범위입니다.")
    if payload.school_type and payload.school_type not in SCHOOL_TYPES:
        raise HTTPException(status_code=422, detail="알 수 없는 학교 유형입니다.")
    row = db.get(AdmissionSetting, school.id)
    if row is None:
        row = AdmissionSetting(school_id=school.id)
        db.add(row)
    row.visibility = payload.visibility
    row.school_type = payload.school_type
    row.small_count_threshold = payload.small_count_threshold
    row.updated_at = datetime.utcnow()
    db.commit()
    return settings_out(school, row)


@router.put("/school-admin/admission/stats/{year}")
def admission_save_stat(year: int, payload: StatIn, db: Session = Depends(get_db),
                        user: User = Depends(require_school)):
    school = manage_school(db, user)
    if not _year_ok(year):
        raise HTTPException(status_code=422, detail=f"연도 형식 오류 ({MIN_YEAR}~{max_year()})")
    errs = stat_errors(payload)
    rec = _records_sum(db, school.id, year)
    if rec > payload.total_graduates:
        errs.append(f"이미 입력한 대학별 진학자 합계({rec}명) > 졸업생 수({payload.total_graduates})")
    emp_sum = int(db.query(func.coalesce(func.sum(AdmissionEmployment.count), 0)).filter(
        AdmissionEmployment.school_id == school.id, AdmissionEmployment.year == year,
    ).scalar() or 0)
    if emp_sum > payload.employment_count:
        errs.append(f"이미 입력한 취업 분야 합계({emp_sum}명) > 취업자 수({payload.employment_count})")
    if errs:
        raise HTTPException(status_code=422, detail=" / ".join(errs))
    row = db.query(AdmissionStat).filter(AdmissionStat.school_id == school.id,
                                         AdmissionStat.year == year).first()
    if row is None:
        row = AdmissionStat(school_id=school.id, year=year)
        db.add(row)
    for k, v in payload.model_dump().items():
        setattr(row, k, v)
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return stat_out(row)


@router.delete("/school-admin/admission/stats/{year}")
def admission_delete_stat(year: int, db: Session = Depends(get_db),
                          user: User = Depends(require_school)):
    """기본 통계만 지운다. 대학별 행·취업 분야는 남는다(따로 지운다)."""
    school = manage_school(db, user)
    n = db.query(AdmissionStat).filter(AdmissionStat.school_id == school.id,
                                       AdmissionStat.year == year).delete()
    db.commit()
    if not n:
        raise HTTPException(status_code=404, detail="해당 연도 통계가 없습니다.")
    return {"ok": True}


@router.get("/school-admin/admission/records")
def admission_records(year: Optional[int] = Query(None), db: Session = Depends(get_db),
                      user: User = Depends(require_school)):
    school = manage_school(db, user)
    q = db.query(AdmissionRecord).filter(AdmissionRecord.school_id == school.id)
    if year is not None:
        q = q.filter(AdmissionRecord.year == year)
    rows = q.order_by(AdmissionRecord.year.desc(), AdmissionRecord.student_count.desc(),
                      AdmissionRecord.university_name.asc()).all()
    return [record_out(r) for r in rows]


def _check_year_totals(db: Session, school_id: int, adds: Dict[int, int],
                       replace_years: Iterable[int] = ()) -> List[str]:
    """연도별로 '기존 + 새로 넣을' 인원이 졸업생 수를 넘는지."""
    replace_years = set(replace_years)
    errs = []
    for y, n in sorted(adds.items()):
        g = _graduates(db, school_id, y)
        if g is None:
            continue   # 기본 통계를 아직 안 넣은 해는 비교할 기준이 없다
        existing = 0 if y in replace_years else _records_sum(db, school_id, y)
        if existing + n > g:
            errs.append(f"{y}년: 진학자 수 합계({existing + n}명) > 졸업생 수({g}명)")
    return errs


@router.post("/school-admin/admission/records")
def admission_add_records(payload: RecordBatchIn, db: Session = Depends(get_db),
                          user: User = Depends(require_school)):
    """여러 줄을 한 번에 넣는다. 한 줄이라도 틀리면 아무것도 넣지 않는다."""
    school = manage_school(db, user)
    clean, errors, adds = [], [], {}
    for i, raw in enumerate(payload.rows, start=1):
        row, errs = clean_record(raw if isinstance(raw, dict) else {})
        if errs:
            errors.append({"row": i, "messages": errs})
        else:
            clean.append(row)
            adds[row["year"]] = adds.get(row["year"], 0) + row["student_count"]
    general = _check_year_totals(db, school.id, adds) if not errors else []
    if errors or general:
        msg = "; ".join([f"{e['row']}행: {', '.join(e['messages'])}" for e in errors] + general)
        raise HTTPException(status_code=422, detail=msg)
    made = [AdmissionRecord(school_id=school.id, **r) for r in clean]
    db.add_all(made)
    db.commit()
    return [record_out(r) for r in made]


def _own_record(db: Session, school: School, record_id: int) -> AdmissionRecord:
    r = db.query(AdmissionRecord).filter(AdmissionRecord.id == record_id,
                                         AdmissionRecord.school_id == school.id).first()
    if r is None:
        raise HTTPException(status_code=404, detail="진학 데이터를 찾을 수 없습니다.")
    return r


@router.put("/school-admin/admission/records/{record_id}")
def admission_update_record(record_id: int, payload: dict, db: Session = Depends(get_db),
                            user: User = Depends(require_school)):
    school = manage_school(db, user)
    r = _own_record(db, school, record_id)
    merged = {**record_out(r), **(payload or {})}
    row, errs = clean_record(merged)
    if errs:
        raise HTTPException(status_code=422, detail=", ".join(errs))
    g = _graduates(db, school.id, row["year"])
    if g is not None:
        total = _records_sum(db, school.id, row["year"], exclude_id=r.id) + row["student_count"]
        if total > g:
            raise HTTPException(status_code=422,
                                detail=f"{row['year']}년: 진학자 수 합계({total}명) > 졸업생 수({g}명)")
    for k, v in row.items():
        setattr(r, k, v)
    r.updated_at = datetime.utcnow()
    db.commit()
    return record_out(r)


@router.delete("/school-admin/admission/records/{record_id}")
def admission_delete_record(record_id: int, db: Session = Depends(get_db),
                            user: User = Depends(require_school)):
    school = manage_school(db, user)
    db.delete(_own_record(db, school, record_id))
    db.commit()
    return {"ok": True}


@router.put("/school-admin/admission/employment/{year}")
def admission_save_employment(year: int, payload: EmploymentIn, db: Session = Depends(get_db),
                              user: User = Depends(require_school)):
    """그 해의 취업 분야 인원을 통째로 바꾼다. 0 인 분야는 지운다."""
    school = manage_school(db, user)
    if not _year_ok(year):
        raise HTTPException(status_code=422, detail=f"연도 형식 오류 ({MIN_YEAR}~{max_year()})")
    items = {}
    for k, v in payload.items.items():
        if k not in EMPLOYMENT_FIELDS:
            raise HTTPException(status_code=422, detail=f"알 수 없는 취업 분야: {k}")
        n = _to_int(v)
        if n is None or n < 0 or n > MAX_COUNT:
            raise HTTPException(status_code=422, detail=f"{EMPLOYMENT_FIELDS[k]}: 인원은 0 이상 숫자")
        if n:
            items[k] = n
    st = db.query(AdmissionStat).filter(AdmissionStat.school_id == school.id,
                                        AdmissionStat.year == year).first()
    total = sum(items.values())
    if st is not None and total > st.employment_count:
        raise HTTPException(status_code=422,
                            detail=f"취업 분야 합계({total}명) > 취업자 수({st.employment_count}명)")
    db.query(AdmissionEmployment).filter(AdmissionEmployment.school_id == school.id,
                                         AdmissionEmployment.year == year).delete()
    for k, n in items.items():
        db.add(AdmissionEmployment(school_id=school.id, year=year, field=k, count=n))
    db.commit()
    return {"year": year, "items": items}


class EmployersIn(BaseModel):
    items: List[str] = Field(default_factory=list)


@router.put("/school-admin/admission/employers")
def admission_save_employers(payload: EmployersIn, db: Session = Depends(get_db),
                             user: User = Depends(require_school)):
    """주요 취업처 목록을 통째로 바꾼다. 순서는 적은 순서 그대로 보인다."""
    school = manage_school(db, user)
    items = clean_employers(payload.items)
    school.major_employers = join_employers(items)
    db.commit()
    return {"items": items}


# ══════════════════════════════════════════════════════════════
#  엑셀 / CSV
# ══════════════════════════════════════════════════════════════
TEMPLATE_HEADERS = ["연도", "대학명", "대학유형", "지역", "학과", "학과계열", "진학자수", "전형"]
HEADER_ALIAS = {
    "year": ["연도", "졸업연도", "학년도", "YEAR"],
    "university_name": ["대학명", "대학", "대학교", "학교명", "UNIVERSITYNAME"],
    "university_type": ["대학유형", "유형", "대학구분", "UNIVERSITYTYPE"],
    "region": ["지역", "권역", "대학권역", "소재지", "REGION"],
    "department_name": ["학과", "학과명", "모집단위", "DEPARTMENTNAME"],
    "department_category": ["학과계열", "계열", "DEPARTMENTCATEGORY"],
    "student_count": ["진학자수", "인원", "인원수", "진학인원", "STUDENTCOUNT"],
    "admission_type": ["전형", "전형유형", "ADMISSIONTYPE"],
}
REQUIRED_HEADERS = ("year", "university_name", "university_type", "region",
                    "department_name", "department_category", "student_count")
_HEADER_LOOKUP = {_squash(a): k for k, al in HEADER_ALIAS.items() for a in al}

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _col_index(ref: str) -> int:
    n = 0
    for ch in ref:
        if ch.isalpha():
            n = n * 26 + (ord(ch.upper()) - 64)
        else:
            break
    return max(n - 1, 0)


def read_xlsx(data: bytes) -> List[List[str]]:
    """첫 번째 시트를 글자 표로 읽는다. 수식은 계산된 값(캐시)을 쓴다."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("엑셀(.xlsx) 파일이 아닙니다.")
    with zf:
        if sum(i.file_size for i in zf.infolist()) > XLSX_MAX_UNZIPPED:
            raise ValueError("파일 내용이 너무 큽니다.")
        names = set(zf.namelist())
        shared: List[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.iter(f"{_NS}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{_NS}t")))
        sheet = None
        try:   # 워크북이 가리키는 첫 시트
            wb = ET.fromstring(zf.read("xl/workbook.xml"))
            first = next(wb.iter(f"{_NS}sheet"))
            rid = first.get(f"{_REL_NS}id")
            rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            for rel in rels:
                if rel.get("Id") == rid:
                    target = rel.get("Target", "").lstrip("/")
                    sheet = target if target.startswith("xl/") else "xl/" + target
        except (KeyError, StopIteration, ET.ParseError):
            sheet = None
        if not sheet or sheet not in names:
            cands = sorted(n for n in names if n.startswith("xl/worksheets/sheet"))
            if not cands:
                raise ValueError("시트를 찾을 수 없습니다.")
            sheet = cands[0]
        root = ET.fromstring(zf.read(sheet))
    table: List[List[str]] = []
    for row in root.iter(f"{_NS}row"):
        cells: Dict[int, str] = {}
        for i, c in enumerate(row.iter(f"{_NS}c")):
            idx = _col_index(c.get("r", "")) if c.get("r") else i
            t = c.get("t", "")
            if t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(f"{_NS}t"))
            else:
                v = c.find(f"{_NS}v")
                val = v.text if v is not None and v.text is not None else ""
                if t == "s" and val.isdigit() and int(val) < len(shared):
                    val = shared[int(val)]
            cells[idx] = val.strip()
        if cells:
            width = max(cells) + 1
            table.append([cells.get(i, "") for i in range(width)])
        if len(table) > IMPORT_MAX_ROWS + 20:
            break
    return table


def read_csv(data: bytes) -> List[List[str]]:
    # 한국어 엑셀이 "CSV로 저장" 하면 CP949 로 나온다. UTF-8 부터 해 본다.
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("CSV 글자 인코딩을 읽을 수 없습니다(UTF-8 또는 CP949).")
    return [[c.strip() for c in r] for r in csv.reader(io.StringIO(text))]


def parse_table(table: List[List[str]]) -> Tuple[List[Tuple[int, dict]], List[str]]:
    """머리글 줄을 찾아 각 줄을 필드 이름으로 바꾼다. (엑셀 행 번호, 값) 목록."""
    header_idx, mapping = None, {}
    for i, row in enumerate(table[:10]):
        m = {}
        for j, h in enumerate(row):
            key = _HEADER_LOOKUP.get(_squash(h))
            if key and key not in m:
                m[key] = j
        if "university_name" in m:
            header_idx, mapping = i, m
            break
    if header_idx is None:
        return [], ["머리글 줄(연도, 대학명, 대학유형 …)을 찾을 수 없습니다. 템플릿을 받아 쓰세요."]
    missing = [HEADER_ALIAS[k][0] for k in REQUIRED_HEADERS if k not in mapping]
    if missing:
        return [], [f"필수 열이 없습니다: {', '.join(missing)}"]
    out = []
    for i, row in enumerate(table[header_idx + 1:], start=header_idx + 2):
        if not any((c or "").strip() for c in row):
            continue
        out.append((i, {k: (row[j] if j < len(row) else "") for k, j in mapping.items()}))
    return out, []


def _excel_cell(v) -> str:
    """CSV 로 내보낼 때 = + - @ 로 시작하는 값은 엑셀이 수식으로 실행한다.
    학교가 적은 글자가 남의 PC 에서 수식이 되지 않게 앞에 ' 를 붙인다."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def write_csv(rows: List[List]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    for r in rows:
        w.writerow([_excel_cell(c) if isinstance(c, str) else c for c in r])
    return buf.getvalue().encode("utf-8-sig")   # BOM 이 있어야 엑셀이 한글을 안 깨뜨린다


def _sheet_xml(rows: List[List]) -> str:
    def ref(ci: int, ri: int) -> str:
        s, n = "", ci + 1
        while n:
            n, rem = divmod(n - 1, 26)
            s = chr(65 + rem) + s
        return f"{s}{ri}"

    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
           '<cols><col min="1" max="8" width="16" customWidth="1"/></cols><sheetData>']
    for ri, row in enumerate(rows, start=1):
        out.append(f'<row r="{ri}">')
        for ci, v in enumerate(row):
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append(f'<c r="{ref(ci, ri)}"><v>{v}</v></c>')
            else:
                out.append(f'<c r="{ref(ci, ri)}" t="inlineStr"><is><t>'
                           f'{xml_escape(str(v or ""))}</t></is></c>')
        out.append("</row>")
    out.append("</sheetData></worksheet>")
    return "".join(out)


def write_xlsx(sheets: List[Tuple[str, List[List]]]) -> bytes:
    """최소 구성의 .xlsx. 엑셀·한셀·구글 시트에서 열린다."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        overrides = "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/'
            f'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(sheets) + 1))
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   f'{overrides}</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   '</Relationships>')
        sheet_tags = "".join(
            f'<sheet name="{xml_escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
            for i, (name, _rows) in enumerate(sheets, start=1))
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   f'<sheets>{sheet_tags}</sheets></workbook>')
        rels = "".join(
            f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(sheets) + 1))
        n = len(sheets) + 1
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   f'{rels}<Relationship Id="rId{n}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   '</Relationships>')
        z.writestr("xl/styles.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<fonts count="1"><font><sz val="11"/><name val="맑은 고딕"/></font></fonts>'
                   '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
                   '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                   '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                   '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
                   '</styleSheet>')
        for i, (_name, rows) in enumerate(sheets, start=1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(rows))
    return buf.getvalue()


def _guide_rows() -> List[List]:
    rows = [["항목", "입력할 수 있는 값"],
            ["연도", f"졸업 연도 숫자 ({MIN_YEAR}~{max_year()})"],
            ["대학유형", " / ".join(UNIVERSITY_TYPES.values())],
            ["지역", " / ".join(REGIONS.values()) + " (시·도 이름도 됩니다: 경기, 부산 …)"],
            ["학과계열", " / ".join(DEPT_CATEGORIES.values())],
            ["진학자수", "1 이상의 정수"],
            ["전형(선택)", " / ".join(v for k, v in ADMISSION_TYPES.items() if k) + " 또는 비움"],
            ["", ""],
            ["주의", "학생 이름·학번·연락처는 적지 마세요. 대학·학과별 인원만 적습니다."]]
    return rows


def _download(data: bytes, filename: str, fmt: str) -> Response:
    media = ("text/csv; charset=utf-8" if fmt == "csv" else
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    from urllib.parse import quote
    return Response(content=data, media_type=media, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


@router.get("/school-admin/admission/template")
def admission_template(format: str = Query("xlsx", pattern="^(xlsx|csv)$"),
                       db: Session = Depends(get_db), user: User = Depends(require_school)):
    manage_school(db, user)
    y = max_year() - (1 if date.today().month < 3 else 0)
    sample = [TEMPLATE_HEADERS,
              [y, "○○대학교", "4년제", "서울", "컴퓨터공학과", "IT/소프트웨어", 5, "수시"],
              [y, "△△대학교", "4년제", "경기·인천", "경영학과", "경상계열", 3, ""],
              [y, "□□전문대학", "전문대", "경기·인천", "전기과", "공학", 7, "특별전형"]]
    if format == "csv":
        return _download(write_csv(sample), "진학정보_템플릿.csv", "csv")
    return _download(write_xlsx([("진학데이터", sample), ("입력 안내", _guide_rows())]),
                     "진학정보_템플릿.xlsx", "xlsx")


@router.get("/school-admin/admission/export")
def admission_export(format: str = Query("xlsx", pattern="^(xlsx|csv)$"),
                     db: Session = Depends(get_db), user: User = Depends(require_school)):
    school = manage_school(db, user)
    rows = [TEMPLATE_HEADERS + ["공개"]]
    for r in db.query(AdmissionRecord).filter(AdmissionRecord.school_id == school.id) \
            .order_by(AdmissionRecord.year.desc(), AdmissionRecord.university_name).all():
        rows.append([r.year, r.university_name, UNIVERSITY_TYPES.get(r.university_type, ""),
                     REGIONS.get(r.region, ""), r.department_name,
                     DEPT_CATEGORIES.get(r.department_category, ""), r.student_count,
                     ADMISSION_TYPES.get(r.admission_type or "", "") if r.admission_type else "",
                     "공개" if r.is_published else "비공개"])
    stamp = date.today().strftime("%Y%m%d")
    if format == "csv":
        return _download(write_csv(rows), f"진학정보_{stamp}.csv", "csv")
    return _download(write_xlsx([("진학데이터", rows)]), f"진학정보_{stamp}.xlsx", "xlsx")


@router.post("/school-admin/admission/import")
async def admission_import(
    file: UploadFile = File(...),
    commit: bool = Query(False, description="False 면 검사만 한다"),
    skip_errors: bool = Query(False, description="오류 행만 빼고 올린다"),
    replace: bool = Query(False, description="파일에 있는 연도의 기존 행을 지우고 올린다"),
    db: Session = Depends(get_db),
    user: User = Depends(require_school),
):
    """엑셀·CSV 일괄 업로드. 먼저 commit=false 로 검사 결과를 보여주고,
    학교가 확인한 뒤 같은 파일을 commit=true 로 다시 보낸다."""
    school = manage_school(db, user)
    data = await file.read(IMPORT_MAX_BYTES + 1)
    if len(data) > IMPORT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="파일은 2MB 까지 올릴 수 있습니다.")
    name = (file.filename or "").lower()
    try:
        if name.endswith(".csv"):
            table = read_csv(data)
        elif name.endswith(".xlsx"):
            table = read_xlsx(data)
        else:
            raise ValueError("엑셀(.xlsx) 또는 CSV(.csv) 파일만 올릴 수 있습니다. "
                             "(.xls 는 엑셀에서 .xlsx 로 다시 저장해 주세요)")
    except (ValueError, ET.ParseError) as exc:
        raise HTTPException(status_code=422, detail=str(exc) or "파일을 읽을 수 없습니다.")

    items, general = parse_table(table)
    if len(items) > IMPORT_MAX_ROWS:
        raise HTTPException(status_code=422,
                            detail=f"한 번에 {IMPORT_MAX_ROWS:,}행까지 올릴 수 있습니다.")
    valid, errors, adds = [], [], {}
    for rownum, raw in items:
        row, errs = clean_record(raw)
        if errs:
            errors.append({"row": rownum, "messages": errs, "values": raw})
        else:
            valid.append(row)
            adds[row["year"]] = adds.get(row["year"], 0) + row["student_count"]
    if not general:
        general = _check_year_totals(db, school.id, adds, adds.keys() if replace else ())

    report = {
        "total": len(items), "valid": len(valid), "error_count": len(errors),
        "errors": errors[:200], "general_errors": general,
        "years": {str(y): n for y, n in sorted(adds.items())},
        "preview": valid[:20], "committed": False, "inserted": 0, "replaced": 0,
    }
    if not commit:
        return report
    if general:
        raise HTTPException(status_code=422, detail=" / ".join(general))
    if errors and not skip_errors:
        raise HTTPException(status_code=422,
                            detail=f"오류가 있는 행이 {len(errors)}개 있습니다. 고치거나 '오류 행 제외'로 올려 주세요.")
    if not valid:
        raise HTTPException(status_code=422, detail="올릴 수 있는 행이 없습니다.")
    if replace:
        report["replaced"] = db.query(AdmissionRecord).filter(
            AdmissionRecord.school_id == school.id,
            AdmissionRecord.year.in_(list(adds.keys())),
        ).delete(synchronize_session=False)
    db.add_all([AdmissionRecord(school_id=school.id, **r) for r in valid])
    db.commit()
    report.update(committed=True, inserted=len(valid))
    return report
