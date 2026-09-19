"""
NEIS(나이스 교육정보 개방 포털) 오픈 API에서 실제 고등학교 정보를 수집한다.

실행:
    cd backend
    python -m app.import_neis                 # 전체 시도교육청 수집
    python -m app.import_neis --only 특성화고 마이스터고
    python -m app.import_neis --geocode       # 카카오 API로 좌표까지 채우기
    python -m app.import_neis --recategorize --dry-run   # 종합고 재분류 미리보기

인증키는 환경변수로 넣는다. 코드나 채팅에 키를 직접 적지 말 것.
    NEIS_API_KEY=발급받은키        (https://open.neis.go.kr → 인증키 신청)
    KAKAO_REST_KEY=카카오키        (좌표 변환용, 없으면 생략됨)

키가 없으면 샘플키로 동작한다. 샘플키는 교육청당 5건만 내려주므로
화면 확인용으로만 쓰고, 실제 운영에는 발급키를 넣어야 한다.
"""

import argparse
import os
import re
import sys
import time
from typing import Dict, Iterator, List, Optional

import requests
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine
from . import dept_fields
from .models import Coed, School, User

NEIS_ENDPOINT = "https://open.neis.go.kr/hub/schoolInfo"
NEIS_MAJOR_ENDPOINT = "https://open.neis.go.kr/hub/schoolMajorinfo"
# 학급정보. 학년도(AY)가 있어 "올해 실제로 운영 중인 학과"를 알 수 있다.
NEIS_CLASS_ENDPOINT = "https://open.neis.go.kr/hub/classInfo"
KAKAO_GEOCODE = "https://dapi.kakao.com/v2/local/search/address.json"
# 장소 검색. 군 시설 등 주소 DB에 없는 곳은 이름으로 찾아야 한다.
KAKAO_KEYWORD = "https://dapi.kakao.com/v2/local/search/keyword.json"

# 17개 시도교육청 코드
OFFICES = {
    "B10": "서울", "C10": "부산", "D10": "대구", "E10": "인천", "F10": "광주",
    "G10": "대전", "H10": "울산", "I10": "세종", "J10": "경기", "K10": "강원",
    "M10": "충북", "N10": "충남", "P10": "전북", "Q10": "전남", "R10": "경북",
    "S10": "경남", "T10": "제주",
}

# LCTN_SC_NM("서울특별시")을 화면용 짧은 이름으로 줄인다.
REGION_SHORT = [
    ("서울", "서울"), ("부산", "부산"), ("대구", "대구"), ("인천", "인천"),
    ("광주", "광주"), ("대전", "대전"), ("울산", "울산"), ("세종", "세종"),
    ("경기", "경기"), ("강원", "강원"), ("충청북도", "충북"), ("충청남도", "충남"),
    ("전라북도", "전북"), ("전북특별자치도", "전북"), ("전라남도", "전남"),
    ("경상북도", "경북"), ("경상남도", "경남"), ("제주", "제주"),
]

# SPCLY_PURPS_HS_ORD_NM(특목고 계열명)을 계열 이름으로 바꾼다.
PURPOSE_TO_CATEGORY = [
    ("과학", "과학고"),
    ("외국어", "외국어고"),
    ("국제", "국제고"),
    ("예술", "예술고"),
    ("체육", "체육고"),
    ("산업수요", "마이스터고"),
]


def short_region(lctn: str) -> str:
    lctn = (lctn or "").strip()
    for prefix, short in REGION_SHORT:
        if lctn.startswith(prefix):
            return short
    return lctn or "기타"


# 이 포털이 다루는 범위.
# 종합고는 일반계와 전문계 과정을 함께 운영하는 학교다. 전문계 학과가 실제로
# 있으니 학생에게 보여줄 이유가 있어 여기에 넣는다 — 계열 이름만 따로 둔다.
VOCATIONAL_CATEGORIES = ("특성화고", "마이스터고", "종합고")


def derive_category(row: Dict) -> str:
    """HS_SC_NM과 특목고 계열명을 합쳐 검색용 계열 하나로 정리한다.

    종합고는 나이스가 따로 이름 붙여 주지 않는다. HS_SC_NM 은 '일반고'로
    오고, 이름에도 '종합'이 안 들어간다(전국 2408곳 중 0곳). 갈라내는 값은
    HS_GNRL_BUSNS_SC_NM(일반계/전문계)이다 — 일반고인데 전문계 과정을 함께
    운영하는 학교가 종합고다(경기만 35곳, 예: 가온고등학교).
    """
    purpose = (row.get("SPCLY_PURPS_HS_ORD_NM") or "").strip()
    if purpose:
        for keyword, category in PURPOSE_TO_CATEGORY:
            if purpose.startswith(keyword):
                return category
        return purpose.replace("계열", "고")
    hs = (row.get("HS_SC_NM") or "").strip()
    if hs == "일반고" and (row.get("HS_GNRL_BUSNS_SC_NM") or "").strip() == "전문계":
        return "종합고"
    return hs or "기타"


def derive_coed(value: Optional[str]) -> Coed:
    v = (value or "").strip()
    if v.startswith("남여") or v.startswith("남녀"):
        return Coed.coed
    if v == "남":
        return Coed.boys
    if v == "여":
        return Coed.girls
    return Coed.coed


def clean_url(url: Optional[str]) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if not u.startswith(("http://", "https://")):
        u = "http://" + u
    return u


def fetch_page(key: str, office: str, index: int, size: int) -> List[Dict]:
    params = {
        "KEY": key,
        "Type": "json",
        "pIndex": index,
        "pSize": size,
        "ATPT_OFCDC_SC_CODE": office,
        "SCHUL_KND_SC_NM": "고등학교",
    }
    res = requests.get(NEIS_ENDPOINT, params=params, timeout=20)
    res.raise_for_status()
    data = res.json()

    if "schoolInfo" not in data:
        # 결과 없음(INFO-200)이나 인증 오류는 여기로 들어온다.
        result = data.get("RESULT", {})
        code = result.get("CODE", "")
        if code and code != "INFO-200":
            print(f"  [{OFFICES.get(office, office)}] NEIS 응답: {code} {result.get('MESSAGE', '')}")
        return []
    return data["schoolInfo"][1].get("row", [])


def iter_schools(key: str, offices: List[str]) -> Iterator[Dict]:
    sample_mode = key == "sample"
    page_size = 5 if sample_mode else 1000

    for office in offices:
        index = 1
        while True:
            rows = fetch_page(key, office, index, page_size)
            if not rows:
                break
            for row in rows:
                yield row
            if sample_mode or len(rows) < page_size:
                break
            index += 1
            time.sleep(0.2)


def current_school_year(today=None) -> int:
    """학년도. 3월에 새 학년도가 시작하므로 1~2월은 전년도로 본다."""
    from datetime import date as _date
    today = today or _date.today()
    return today.year if today.month >= 3 else today.year - 1


def fetch_departments_by_classes(
    key: str, atpt: str, code: str, year: int, grade: Optional[str] = None,
    debug: bool = False,
) -> List[str]:
    """학급정보에서 해당 학년도에 학급이 편성된 학과를 뽑는다.

    학과정보(schoolMajorinfo)는 폐과·개명된 옛 학과까지 전부 내려주고 연도 정보가
    없어 걸러낼 수 없다. 반면 학급정보에는 학년도가 있다.

    grade="1" 이면 1학년 학급만 본다. 학과 이름이 바뀌면 상급생은 옛 이름으로
    남기 때문에(예: 3학년 앱서비스과 / 1·2학년 미디어소프트웨어과) 전 학년을 보면
    옛 이름이 계속 따라온다. 신입생을 받는 학과가 곧 현재 학과이고, 진학을 앞둔
    중학생에게 필요한 정보도 그것이다.
    """
    params = {
        "KEY": key,
        "Type": "json",
        "pIndex": 1,
        "pSize": 1000,
        "ATPT_OFCDC_SC_CODE": atpt,
        "SD_SCHUL_CODE": code,
        "AY": str(year),
    }
    if grade:
        params["GRADE"] = grade
    try:
        res = requests.get(NEIS_CLASS_ENDPOINT, params=params, timeout=20)
        res.raise_for_status()
        data = res.json()
        if "classInfo" not in data:
            if debug:
                print(f"  [학급정보 {year}] 응답 없음:", str(data)[:200])
            return []
        rows = data["classInfo"][1].get("row", [])
        if debug and rows:
            label = f"{year}학년도" + (f" {grade}학년" if grade else " 전학년")
            print(f"  [학급정보 {label}] {len(rows)}행, 필드: {sorted(rows[0].keys())}")
        names = []
        for r in rows:
            name = (r.get("DDDEP_NM") or "").strip()
            if name and name not in names:
                names.append(name)
        return names
    except (requests.RequestException, ValueError, KeyError) as exc:
        if debug:
            print(f"  [학급정보 {year}] 요청 실패:", exc)
        return []


def fetch_all_majors(key: str, atpt: str, code: str, debug: bool = False) -> List[str]:
    """학과정보 API 전체 목록. 폐과가 섞여 있으므로 보조 수단으로만 쓴다."""
    params = {
        "KEY": key,
        "Type": "json",
        "pIndex": 1,
        "pSize": 100,
        "ATPT_OFCDC_SC_CODE": atpt,
        "SD_SCHUL_CODE": code,
    }
    try:
        res = requests.get(NEIS_MAJOR_ENDPOINT, params=params, timeout=20)
        res.raise_for_status()
        data = res.json()
        if "schoolMajorinfo" not in data:
            return []
        rows = data["schoolMajorinfo"][1].get("row", [])
        if debug and rows:
            print(f"  [학과정보] {len(rows)}행 (폐과 포함 가능)")
        names = []
        for r in rows:
            name = (r.get("DDDEP_NM") or "").strip()
            if name and name not in names:
                names.append(name)
        return names
    except (requests.RequestException, ValueError, KeyError):
        return []


def fetch_majors(key: str, atpt: str, code: str, debug: bool = False) -> str:
    """개설 학과를 가져온다.

    1순위: 학급정보(올해 -> 작년) — 실제 운영 중인 학과
    2순위: 학과정보 — 학급 자료가 없을 때만. 폐과가 섞일 수 있다.
    """
    year = current_school_year()

    # 1순위: 신입생(1학년)을 받는 학과. 개명 전 이름은 상급생에만 남으므로 빠진다.
    for ay in (year, year - 1):
        names = fetch_departments_by_classes(key, atpt, code, ay, grade="1", debug=debug)
        if names:
            if debug:
                print(f"  -> {ay}학년도 1학년 기준 {len(names)}개 학과 사용")
            return "\n".join(names)

    # 2순위: 1학년 자료가 없으면 전 학년(옛 이름이 섞일 수 있다)
    for ay in (year, year - 1):
        names = fetch_departments_by_classes(key, atpt, code, ay, debug=debug)
        if names:
            if debug:
                print(f"  -> {ay}학년도 전학년 기준 {len(names)}개 학과 사용")
            return "\n".join(names)

    # 3순위: 학급 자료가 아예 없을 때만 학과정보
    names = fetch_all_majors(key, atpt, code, debug)
    if debug and names:
        print(f"  -> 학급 자료가 없어 학과정보로 대체 ({len(names)}개, 폐과 포함 가능)")
    return "\n".join(names)


def address_variants(address: str) -> List[str]:
    """지오코딩에 실패하기 쉬운 주소를 단계적으로 단순화한 후보들.

    NEIS 주소에는 '경상남도 진주시 금산면 송백로 46 , 사서함 306-3호 (금산면)'
    처럼 쉼표 뒤에 사서함·건물번호·우편번호가 붙는 경우가 있다. 카카오는 이런
    형태를 못 찾으므로, 뒤쪽 군더더기를 하나씩 떼며 다시 시도한다.
    """
    raw = (address or "").strip()
    if not raw:
        return []

    seen = []

    def add(v: str) -> None:
        v = " ".join(v.split()).strip(" ,")
        if v and v not in seen:
            seen.append(v)

    add(raw)
    # 1) 괄호 부분 제거: '... (금산면)'
    add(re.sub(r"\([^)]*\)", "", raw))
    # 2) 첫 쉼표 뒤 제거: '... 송백로 46 , 사서함 306-3호' -> '... 송백로 46'
    add(raw.split(",")[0])
    # 3) 괄호와 쉼표 뒤를 모두 제거
    add(re.sub(r"\([^)]*\)", "", raw).split(",")[0])
    return seen


def geocode_once(address: str, kakao_key: str) -> Optional[tuple]:
    try:
        res = requests.get(
            KAKAO_GEOCODE,
            params={"query": address},
            headers={"Authorization": f"KakaoAK {kakao_key}"},
            timeout=10,
        )
        res.raise_for_status()
        docs = res.json().get("documents", [])
        if not docs:
            return None
        return float(docs[0]["y"]), float(docs[0]["x"])
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return None


def geocode_by_name(name: str, region: str, kakao_key: str) -> Optional[tuple]:
    """학교 이름으로 좌표를 찾는다(장소 검색).

    군 시설 안에 있는 학교처럼 도로명주소가 주소 DB에 없는 경우가 있다.
    그런 곳도 장소(POI)로는 등록돼 있어 이름으로 찾을 수 있다.
    """
    queries = [q for q in (f"{region} {name}".strip(), name) if q.strip()]
    for query in queries:
        try:
            res = requests.get(
                KAKAO_KEYWORD,
                params={"query": query, "size": 1},
                headers={"Authorization": f"KakaoAK {kakao_key}"},
                timeout=10,
            )
            res.raise_for_status()
            docs = res.json().get("documents", [])
            if docs:
                return float(docs[0]["y"]), float(docs[0]["x"])
        except (requests.RequestException, ValueError, KeyError, IndexError):
            pass
        time.sleep(0.05)
    return None


def geocode(address: str, kakao_key: str) -> Optional[tuple]:
    """주소를 좌표로. 실패하면 주소를 단순화해 다시 시도한다."""
    for candidate in address_variants(address):
        coords = geocode_once(candidate, kakao_key)
        if coords:
            return coords
        time.sleep(0.05)
    return None


def upsert(db: Session, row: Dict, key: str, with_majors: bool,
           refresh_majors: bool = False, refresh_contact: bool = False) -> str:
    atpt = row.get("ATPT_OFCDC_SC_CODE")
    code = row.get("SD_SCHUL_CODE")
    if not atpt or not code:
        return "skip"

    school = (
        db.query(School)
        .filter(School.atpt_code == atpt, School.school_code == code)
        .first()
    )
    is_new = school is None
    if is_new:
        school = School(atpt_code=atpt, school_code=code)
        db.add(school)

    address = (row.get("ORG_RDNMA") or "").strip()
    detail = (row.get("ORG_RDNDA") or "").strip()
    full_address = f"{address} {detail}".strip()

    school.name = (row.get("SCHUL_NM") or "").strip()
    school.category = derive_category(row)
    school.region = short_region(row.get("LCTN_SC_NM"))
    school.address = full_address
    school.coed = derive_coed(row.get("COEDU_SC_NM"))
    school.foundation = (row.get("FOND_SC_NM") or "").strip()

    # 전화번호·홈페이지는 학교 계정이 '학교 정보' 화면에서 직접 고칠 수 있는
    # 칸이다. 다시 수집할 때마다 나이스 값으로 덮으면 학교가 고쳐 둔 대표번호나
    # 새 홈페이지 주소가 소리 없이 사라진다. 그래서 비어 있을 때만 채운다.
    # (이름·주소·계열은 학교가 못 고치는 나이스 값이라 계속 갱신한다.)
    if refresh_contact or is_new or not (school.phone or "").strip():
        school.phone = (row.get("ORG_TELNO") or "").strip()
    if refresh_contact or is_new or not (school.website or "").strip():
        school.website = clean_url(row.get("HMPG_ADRES"))

    founded = (row.get("FOND_YMD") or "").strip()
    if len(founded) >= 4 and founded[:4].isdigit():
        school.established_year = int(founded[:4])

    # 학교 계정이 이미 학과를 직접 손봤다면 덮어쓰지 않는다.
    # 다만 비어 있는 학교는 나중에 --majors 로 다시 돌려 채울 수 있어야 한다.
    # refresh_majors 면 이미 채워진 학교도 다시 받아 덮어쓴다.
    # (연도 필터가 없던 시절에 옛 학과가 섞여 들어간 것을 정리할 때 쓴다)
    if with_majors and (refresh_majors or is_new or not (school.departments or "").strip()):
        majors = fetch_majors(key, atpt, code)
        if majors:
            school.departments = majors
            school.dept_fields = dept_fields.to_storage(majors)
        time.sleep(0.1)

    return "new" if is_new else "updated"


def main() -> int:
    parser = argparse.ArgumentParser(description="NEIS에서 고등학교 정보를 수집한다.")
    parser.add_argument(
        "--only",
        nargs="*",
        default=list(VOCATIONAL_CATEGORIES),
        help="수집할 계열. 기본은 직업계고(특성화고·마이스터고)만. "
             "다른 계열도 받으려면 직접 지정하거나 --all 을 쓴다.",
    )
    parser.add_argument("--all", action="store_true", help="일반고까지 전부 수집")
    parser.add_argument(
        "--hide-others",
        action="store_true",
        help="이미 들어와 있는 비직업계고(과학고·외국어고 등)를 검색에서 숨긴다.",
    )
    parser.add_argument(
        "--delete-others",
        action="store_true",
        help="이미 들어와 있는 비직업계고를 아예 삭제한다. (되돌릴 수 없음)",
    )
    parser.add_argument("--geocode", action="store_true", help="카카오 API로 좌표 채우기")
    parser.add_argument(
        "--refresh-contact", action="store_true",
        help="전화번호·홈페이지도 나이스 값으로 덮어쓴다. 기본은 비어 있을 때만 "
             "채운다 — 학교가 직접 고친 값을 지우지 않기 위해서다.",
    )
    parser.add_argument("--majors", action="store_true", help="학과 정보도 함께 수집(느림)")
    parser.add_argument(
        "--refresh-majors", action="store_true",
        help="이미 학과가 있는 학교도 다시 받아 덮어쓴다(옛 학과 정리용). --majors 와 함께 쓴다.",
    )
    parser.add_argument(
        "--recategorize", action="store_true",
        help="이미 저장된 학교의 계열을 나이스 값으로 다시 매긴다(종합고 정리용). "
             "계열만 고치고 다른 칸은 건드리지 않는다. --dry-run 으로 먼저 확인할 것.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="--recategorize 에서 바꾸지 않고 무엇이 바뀔지만 본다")
    parser.add_argument("--office", nargs="*", help="특정 교육청만 (예: B10 J10)")
    parser.add_argument(
        "--if-empty",
        action="store_true",
        help="학교가 하나라도 있으면 아무것도 하지 않고 끝낸다. 첫 실행 자동화용.",
    )
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)

    # 이미 저장된 학교의 계열 다시 매기기 (수집과 별개로 단독 실행 가능)
    # 종합고 계열을 새로 만들면서, 예전에 일반고·특성화고로 들어와 있던
    # '~종합고등학교'들을 옮기려고 만들었다.
    if args.recategorize:
        # 계열은 나이스 필드(HS_SC_NM + HS_GNRL_BUSNS_SC_NM)로만 알 수 있어
        # 나이스를 다시 훑는다. 다만 **이미 저장된 학교의 계열만** 고친다 —
        # 새 학교를 만들지 않고, 전화번호·홈페이지처럼 학교가 직접 고쳤을
        # 수 있는 칸도 건드리지 않는다.
        rc_key = os.getenv("NEIS_API_KEY", "").strip() or "sample"
        rc_offices = args.office or list(OFFICES.keys())
        db = SessionLocal()
        try:
            known = {
                (s.atpt_code, s.school_code): s
                for s in db.query(School).all()
                if s.atpt_code and s.school_code
            }
            changed, unhidden, seen = [], [], 0
            for row in iter_schools(rc_key, rc_offices):
                seen += 1
                school = known.get((
                    (row.get("ATPT_OFCDC_SC_CODE") or "").strip(),
                    (row.get("SD_SCHUL_CODE") or "").strip(),
                ))
                if school is None:
                    continue
                want = derive_category(row)
                if want and want != school.category:
                    changed.append((school.name, school.category, want))
                    if not args.dry_run:
                        school.category = want
                # 이 포털이 다루는 계열로 옮겨왔는데 숨겨져 있으면 꺼내 준다.
                # (예전 --hide-others 로 일반고와 함께 숨겨졌던 종합고들)
                if want in VOCATIONAL_CATEGORIES and not school.is_visible:
                    unhidden.append(school.name)
                    if not args.dry_run:
                        school.is_visible = True
            print(f"나이스에서 {seen}곳을 훑어 저장된 학교 {len(known)}곳과 맞춰봤습니다.")
            if not changed and not unhidden:
                print("계열을 바꿀 학교가 없습니다.")
                return 0
            if changed:
                print(f"계열이 바뀌는 학교 {len(changed)}곳:")
                for name, before, after in changed[:40]:
                    print(f"  {name}  {before} → {after}")
                if len(changed) > 40:
                    print(f"  … 외 {len(changed) - 40}곳")
            if unhidden:
                print(f"숨김이 풀리는 학교 {len(unhidden)}곳: "
                      f"{', '.join(unhidden[:8])}{' …' if len(unhidden) > 8 else ''}")
            if args.dry_run:
                db.rollback()
                print()
                print("--dry-run 이라 바꾸지 않았습니다.")
            else:
                db.commit()
                print()
                print(f"계열 {len(changed)}곳, 숨김 해제 {len(unhidden)}곳을 반영했습니다.")
            return 0
        except requests.RequestException as exc:
            db.rollback()
            print(f"NEIS 요청이 실패했습니다: {exc}")
            return 1
        finally:
            db.close()

    # 이미 들어와 있는 비직업계고 정리 (수집과 별개로 단독 실행 가능)
    if args.hide_others or args.delete_others:
        db = SessionLocal()
        try:
            targets = (
                db.query(School)
                .filter(~School.category.in_(VOCATIONAL_CATEGORIES))
                .all()
            )
            if not targets:
                print("정리할 비직업계고가 없습니다.")
                return 0
            by_cat = {}
            for t in targets:
                by_cat[t.category] = by_cat.get(t.category, 0) + 1
            print(f"대상 {len(targets)}곳:")
            for cat, cnt in sorted(by_cat.items(), key=lambda x: -x[1]):
                print(f"  {cat}: {cnt}곳")

            if args.delete_others:
                # 학교를 참조하는 자식 행을 먼저 정리한다
                from .models import (
                    AdmissionEvent, Article, Favorite, Inquiry, PlanOrder,
                    SchoolVerification, SchoolView,
                )
                ids = [t.id for t in targets]
                db.query(Article).filter(Article.school_id.in_(ids)).update(
                    {Article.school_id: None}, synchronize_session=False)
                db.query(User).filter(User.school_id.in_(ids)).update(
                    {User.school_id: None}, synchronize_session=False)
                for model in (Favorite, AdmissionEvent, SchoolVerification,
                              PlanOrder, Inquiry, SchoolView):
                    db.query(model).filter(model.school_id.in_(ids)).delete(
                        synchronize_session=False)
                db.query(School).filter(School.id.in_(ids)).delete(
                    synchronize_session=False)
                db.commit()
                print(f"[삭제 완료] {len(targets)}곳을 지웠습니다.")
            else:
                db.query(School).filter(School.id.in_([t.id for t in targets])).update(
                    {School.is_visible: False}, synchronize_session=False)
                db.commit()
                print(f"[숨김 완료] {len(targets)}곳을 검색에서 제외했습니다.")
                print("검색 필터의 계열 목록에서도 자동으로 사라집니다.")
        finally:
            db.close()
        return 0

    if args.if_empty:
        db = SessionLocal()
        try:
            existing = db.query(School).count()
        finally:
            db.close()
        if existing > 0:
            print(f"이미 학교 {existing}개가 있어 수집을 건너뜁니다.")
            return 0

    key = os.getenv("NEIS_API_KEY", "").strip() or "sample"
    if key == "sample":
        print("NEIS_API_KEY가 없어 샘플키로 실행합니다. 교육청당 5건만 들어옵니다.")
        print("전체 데이터를 받으려면 https://open.neis.go.kr 에서 인증키를 발급하세요.\n")

    offices = args.office or list(OFFICES.keys())
    wanted = None if args.all else set(args.only)

    db = SessionLocal()
    counts = {"new": 0, "updated": 0, "skip": 0, "filtered": 0}
    try:
        for row in iter_schools(key, offices):
            category = derive_category(row)
            if wanted is not None and category not in wanted:
                counts["filtered"] += 1
                continue
            result = upsert(db, row, key, args.majors, args.refresh_majors,
                            args.refresh_contact)
            counts[result] += 1
            if (counts["new"] + counts["updated"]) % 50 == 0:
                db.commit()
        db.commit()
    except requests.RequestException as exc:
        db.rollback()
        print(f"NEIS 요청이 실패했습니다: {exc}")
        return 1
    finally:
        db.close()

    print(
        f"수집 완료 — 신규 {counts['new']}개, 갱신 {counts['updated']}개, "
        f"계열 불일치로 제외 {counts['filtered']}개"
    )

    if args.geocode:
        kakao_key = os.getenv("KAKAO_REST_KEY", "").strip()
        if not kakao_key:
            print("KAKAO_REST_KEY가 없어 좌표 변환을 건너뜁니다.")
            return 0
        db = SessionLocal()
        try:
            targets = (
                db.query(School)
                .filter(School.latitude.is_(None))
                .all()
            )
            print(f"좌표를 채울 학교 {len(targets)}개")
            done = 0
            for school in targets:
                coords = geocode(school.address, kakao_key)
                if not coords:
                    # 주소로 못 찾으면 학교 이름으로 장소 검색을 시도한다.
                    coords = geocode_by_name(school.name, school.region or "", kakao_key)
                    if coords:
                        print(f"  이름으로 찾음: {school.name}")
                if coords:
                    school.latitude, school.longitude = coords
                    done += 1
                if done and done % 30 == 0:
                    db.commit()
                time.sleep(0.05)
            db.commit()
            print(f"좌표 {done}개 저장")
        finally:
            db.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
