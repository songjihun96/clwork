"""NEIS 학과정보 API가 실제로 무엇을 주는지 눈으로 확인한다.

    python -m app.check_majors 부산기계공업고등학교

학과가 이상하게 쌓이는 원인을 찾을 때 쓴다. 응답의 필드 이름과 연도 값을
그대로 찍어주므로, 연도 필터가 제대로 걸리는지 바로 알 수 있다.
"""

import os
import sys

from .database import SessionLocal
from .import_neis import (
    NEIS_CLASS_ENDPOINT,
    NEIS_MAJOR_ENDPOINT,
    current_school_year,
    fetch_all_majors,
    fetch_departments_by_classes,
    fetch_majors,
)
from .models import School


def main() -> int:
    if len(sys.argv) < 2:
        print("사용법: python -m app.check_majors <학교이름 일부>")
        return 1

    keyword = sys.argv[1]
    key = os.getenv("NEIS_API_KEY", "").strip() or "sample"
    if key == "sample":
        print("경고: NEIS_API_KEY 가 없어 sample 키로 조회합니다(결과가 제한됩니다).\n")

    db = SessionLocal()
    try:
        schools = db.query(School).filter(School.name.contains(keyword)).limit(3).all()
        if not schools:
            print(f"'{keyword}' 로 찾은 학교가 없습니다.")
            return 1

        for s in schools:
            print("=" * 60)
            print(f"{s.name}  (교육청 {s.atpt_code} / 학교코드 {s.school_code})")
            print(f"엔드포인트: {NEIS_MAJOR_ENDPOINT}")
            print()
            print("[현재 DB에 저장된 학과]")
            saved = [d for d in (s.departments or "").splitlines() if d.strip()]
            for d in saved:
                print("   -", d)
            if not saved:
                print("   (없음)")
            print()
            if not (s.atpt_code and s.school_code):
                print("   교육청/학교코드가 없어 조회할 수 없습니다.")
                continue

            ay = current_school_year()
            print(f"[학급정보 {ay}학년도 1학년] {NEIS_CLASS_ENDPOINT}")
            print("  (신입생을 받는 = 현재 학과. 개명 전 이름은 여기서 빠진다)")
            by_class = fetch_departments_by_classes(
                key, s.atpt_code, s.school_code, ay, grade="1", debug=True
            )
            for d in by_class:
                print("   -", d)
            if not by_class:
                print("   (없음 — 전학년/작년 자료로 대체됩니다)")
            print()

            print(f"[학급정보 {ay}학년도 전학년]")
            print("  (상급생이 쓰는 옛 학과명까지 포함)")
            all_grades = fetch_departments_by_classes(
                key, s.atpt_code, s.school_code, ay, debug=True
            )
            for d in all_grades:
                mark = "   -" if d in by_class else "   ^"   # ^ = 상급생만(개명 전 이름 의심)
                print(mark, d)
            if not all_grades:
                print("   (없음)")
            print()

            print(f"[학과정보 전체] {NEIS_MAJOR_ENDPOINT}")
            print("  (폐과·개명된 옛 학과까지 모두 포함)")
            all_majors = fetch_all_majors(key, s.atpt_code, s.school_code, debug=True)
            for d in all_majors:
                mark = "   -" if d in by_class else "   x"   # x = 학급 없음(폐과 의심)
                print(mark, d)
            print()

            result = fetch_majors(key, s.atpt_code, s.school_code)
            print("[실제로 저장될 학과]")
            for d in result.splitlines():
                print("   -", d)
            if not result:
                print("   (없음)")
            print()
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
