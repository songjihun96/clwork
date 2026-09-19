"""NEIS 시간표에서 학교·학과별 개설 과목을 모은다.

    python -m app.import_subjects                 전체 학교
    python -m app.import_subjects --school 12     한 학교만
    python -m app.import_subjects --school 12 --debug   응답 필드까지 확인

일지를 쓸 때 과목명을 직접 타이핑하지 않고 고를 수 있게 하려는 것이다.
시간표에는 학과(DDDEP_NM)와 학년(GRADE)이 함께 있어, 학생의 학과에 맞는
과목만 보여줄 수 있다.

수집 범위
  최근 학기의 한 주치 시간표를 받아 과목명(ITRT_CNTNT)을 추린다.
  한 주면 대부분의 과목이 한 번씩은 나온다. 더 넓게 받으면 느리기만 하다.
"""

import argparse
import os
import sys
import time
from datetime import date, timedelta
from typing import Dict, List

import requests

from .database import Base, SessionLocal, engine
from .import_neis import current_school_year
from .models import School, SchoolSubject

NEIS_TIMETABLE = "https://open.neis.go.kr/hub/hisTimetable"

# 과목명이 아닌 값들. 시간표에는 이런 것도 섞여 들어온다.
SKIP_NAMES = {
    "", "-", "없음", "자율", "동아리", "봉사", "진로", "창의적체험활동",
    "창체", "자율활동", "행사", "재량", "휴업일", "토요휴업일",
}


def probe_ranges(today: date = None) -> list:
    """시간표를 조회해 볼 기간 목록. 앞에서부터 시도한다.

    이번 주를 그대로 쓰면 방학에는 아무것도 안 나온다(NEIS 는 INFO-200 을 준다).
    그래서 수업이 확실히 있는 학기 중 한 주를 골라 물어본다.
      1학기 5월 둘째 주 / 2학기 10월 둘째 주
    올해 자료가 없으면 작년으로 한 번 더 시도한다.
    """
    today = today or date.today()
    ay = current_school_year(today)

    # (학년도, 학기, 시작일, 종료일)
    plans = []
    monday = today - timedelta(days=today.weekday())
    # 방학(7월 하순~8월, 12월 하순~2월)에는 이번 주를 물어봐야 헛수고다.
    md = (today.month, today.day)
    in_term = ((3, 2) <= md <= (7, 18)) or ((9, 1) <= md <= (12, 20))
    if in_term:
        # 학기 중이면 이번 주가 가장 정확하다.
        sem = 1 if today.month <= 8 else 2
        plans.append((ay, sem, monday.strftime("%Y%m%d"),
                      (monday + timedelta(days=4)).strftime("%Y%m%d")))

    plans.append((ay, 1, f"{ay}0511", f"{ay}0515"))     # 1학기 중간
    plans.append((ay, 2, f"{ay}1012", f"{ay}1016"))     # 2학기 중간
    plans.append((ay - 1, 2, f"{ay - 1}1012", f"{ay - 1}1016"))
    plans.append((ay - 1, 1, f"{ay - 1}0511", f"{ay - 1}0515"))
    return plans


def clean_subject(name: str) -> str:
    name = (name or "").strip()
    # 괄호 안 부연이나 뒤에 붙는 분반 표시를 떼어낸다. 예) '프로그래밍(1)' -> '프로그래밍'
    if "(" in name:
        name = name.split("(", 1)[0].strip()
    return name


def fetch_timetable(key: str, atpt: str, code: str, ay: int, sem: int,
                    frm: str, to: str, debug: bool = False) -> List[Dict]:
    params = {
        "KEY": key, "Type": "json", "pIndex": 1, "pSize": 1000,
        "ATPT_OFCDC_SC_CODE": atpt, "SD_SCHUL_CODE": code,
        "AY": str(ay), "SEM": str(sem),
        "TI_FROM_YMD": frm, "TI_TO_YMD": to,
    }
    try:
        res = requests.get(NEIS_TIMETABLE, params=params, timeout=25)
        res.raise_for_status()
        data = res.json()
        if "hisTimetable" not in data:
            if debug:
                print("   응답에 hisTimetable 없음:", str(data)[:200])
            return []
        rows = data["hisTimetable"][1].get("row", [])
        if debug and rows:
            print(f"   {len(rows)}행, 필드: {sorted(rows[0].keys())}")
        return rows
    except (requests.RequestException, ValueError, KeyError) as exc:
        if debug:
            print("   요청 실패:", exc)
        return []


def collect_for_school(db, key: str, school: School, debug: bool = False, opts=None) -> int:
    if not (school.atpt_code and school.school_code):
        return 0

    # 직접 기간을 준 경우 그것만 쓴다.
    plans = probe_ranges()
    if opts and opts.frm and opts.to:
        plans = [(opts.ay or current_school_year(), opts.sem or 1, opts.frm, opts.to)]

    rows = []
    for ay, sem, frm, to in plans:
        if debug:
            print(f"   시도: {ay}학년도 {sem}학기 {frm}~{to}")
        rows = fetch_timetable(key, school.atpt_code, school.school_code,
                               ay, sem, frm, to, debug)
        if rows:
            if debug:
                print(f"   → {ay}학년도 {sem}학기 자료 사용")
            break
        time.sleep(0.05)
    if not rows:
        if debug:
            print("   모든 기간에서 자료를 찾지 못했습니다.")
        return 0

    # (학과, 학년, 과목) 조합으로 모은다.
    seen = set()
    for r in rows:
        name = clean_subject(r.get("ITRT_CNTNT"))
        if not name or name in SKIP_NAMES:
            continue
        dept = (r.get("DDDEP_NM") or "").strip()
        try:
            grade = int(str(r.get("GRADE") or "").strip())
        except ValueError:
            grade = None
        seen.add((dept, grade, name[:80]))

    if debug:
        print(f"   과목 {len(seen)}종")

    # 이 학교의 기존 자료를 지우고 새로 넣는다(폐강 과목이 남지 않게).
    db.query(SchoolSubject).filter(
        SchoolSubject.school_id == school.id
    ).delete(synchronize_session=False)
    for dept, grade, name in sorted(seen):
        db.add(SchoolSubject(school_id=school.id, department=dept,
                             grade=grade, name=name))
    db.commit()
    return len(seen)


def main() -> int:
    parser = argparse.ArgumentParser(description="NEIS 시간표에서 과목 수집")
    parser.add_argument("--school", type=int, help="학교 ID (없으면 전체)")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--from", dest="frm", help="조회 시작일 YYYYMMDD (직접 지정)")
    parser.add_argument("--to", dest="to", help="조회 종료일 YYYYMMDD")
    parser.add_argument("--ay", type=int, help="학년도 (직접 지정)")
    parser.add_argument("--sem", type=int, choices=[1, 2], help="학기 (직접 지정)")
    args = parser.parse_args()

    key = os.getenv("NEIS_API_KEY", "").strip() or "sample"
    if key == "sample":
        print("경고: NEIS_API_KEY 가 없어 sample 키로 조회합니다(결과가 제한됩니다).\n")

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        q = db.query(School).filter(School.is_visible.is_(True))
        if args.school:
            q = q.filter(School.id == args.school)
        schools = q.all()
        print(f"대상 학교 {len(schools)}개\n")

        total, done = 0, 0
        for s in schools:
            if args.debug:
                print(f"[{s.id}] {s.name}")
            n = collect_for_school(db, key, s, args.debug, args)
            total += n
            if n:
                done += 1
                if not args.debug:
                    print(f"  {s.name}: {n}종")
            time.sleep(0.05)

        print(f"\n학교 {done}곳에서 과목 {total}종을 저장했습니다.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
