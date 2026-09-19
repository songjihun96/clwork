"""진로 테스트에서 학교가 안 나올 때 원인을 찾는다.

추천이 비어 있으면 셋 중 하나다.
  1) 학과가 등록된 학교가 없다        → 학과 글이 비어 있음
  2) 학과 이름이 키워드와 안 맞는다   → '스마트팩토리과' 같은 새 이름
  3) 좌표가 없어 거리 계산에서 빠진다 → 통학권 거르기에서 전부 탈락

어디서 막히는지 숫자로 보여준다.

    python -m app.diagnose_quiz
    python -m app.diagnose_quiz --lat 37.79 --lng 127.06 --km 25
"""

import argparse

# 학과 이름이 아니라 자리를 채우는 말들. NEIS 에 이렇게 들어온 학교가 있다.
# 무엇을 배우는지 알 수 없어 계열로 나눌 수 없고, 키워드를 더해도 소용없다.
# 추천에서 빠지는 것이 맞다.
PLACEHOLDERS = ("일반", "보통", "공통", "인문", "전문계", "계열", "과정")


def is_placeholder(name: str) -> bool:
    body = name.replace("과", "").replace("학", "").strip()
    return bool(body) and all(
        any(w in part for w in PLACEHOLDERS)
        for part in [body]
    )

from .database import SessionLocal
from .models import School
from . import geo, quiz as ql
from .import_neis import VOCATIONAL_CATEGORIES


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float, help="기준 위도 (없으면 거리 검사 생략)")
    ap.add_argument("--lng", type=float, help="기준 경도")
    ap.add_argument("--km", type=float, default=25, help="통학 거리 (기본 25km)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        # 추천 대상과 같은 기준으로 센다. 기준이 다르면 진단 숫자와
        # 실제 추천이 어긋나 원인을 못 찾는다.
        schools = (db.query(School)
                   .filter(School.category.in_(VOCATIONAL_CATEGORIES)).all())
        total = len(schools)

        with_dept = [s for s in schools
                     if [d for d in (s.departments or "").splitlines() if d.strip()]]
        with_geo = [s for s in schools if s.latitude and s.longitude]

        print("─" * 56)
        print(f"  직업계고 학교         {total:>6}곳"
              f"   ({' + '.join(VOCATIONAL_CATEGORIES)})")
        print(f"  └ 학과가 등록된 곳    {len(with_dept):>6}곳"
              f"   ({total - len(with_dept)}곳 비어 있음)")
        print(f"  └ 좌표가 있는 곳      {len(with_geo):>6}곳"
              f"   ({total - len(with_geo)}곳 없음)")
        print("─" * 56)

        if not with_dept:
            print("\n  학과가 등록된 학교가 없습니다.")
            print("  진로 테스트는 학과 이름으로 학교를 찾으므로, 학과가 없으면")
            print("  추천이 한 곳도 나오지 않습니다.")
            print()
            print("  NEIS 에서 학과를 받아오세요. 시간이 걸립니다(학교당 한 번씩 조회).")
            print("    cd /root/hs-portal/backend")
            print("    .venv/bin/python -m app.import_neis --majors")
            print()
            print("  이미 학과가 있는 학교까지 새로 받으려면 --refresh-majors 를 함께 씁니다.")
            return 1

        # 계열마다 몇 곳이 걸리는지 본다. 특정 계열만 0곳이면 키워드 문제다.
        print("\n  계열별로 걸리는 학교 수")
        unmatched = set(s.id for s in with_dept)
        for axis, label in ql.AXIS_LABEL.items():
            kw = []
            for g in ql.DEPARTMENT_GROUPS.get(axis, []):
                kw.extend(g["keywords"])
            hit = [s for s in with_dept
                   if ql.department_matches(
                       [d.strip() for d in s.departments.splitlines() if d.strip()], kw)]
            unmatched -= {s.id for s in hit}
            mark = "  ←  0곳" if not hit else ""
            print(f"    {label:14s} {len(hit):>5}곳{mark}")

        if unmatched:
            # 두 가지를 갈라 본다. 손댈 수 있는 것과 없는 것이 다르다.
            fixable, placeholder = [], []
            for s in with_dept:
                if s.id not in unmatched:
                    continue
                depts = [d.strip() for d in s.departments.splitlines() if d.strip()]
                (placeholder if all(is_placeholder(d) for d in depts)
                 else fixable).append((s, depts))

            print(f"\n  어느 계열에도 안 걸리는 학교 {len(unmatched)}곳")
            print(f"    · 학과 이름이 아닌 곳  {len(placeholder):>3}곳"
                  f"  ('일반학과', '공통과정' 등 — 손댈 수 없음)")
            print(f"    · 키워드를 더하면 될 곳 {len(fixable):>3}곳")

            if fixable:
                print("\n  키워드를 더하면 걸릴 학교")
                for s, depts in fixable[:15]:
                    print(f"    {s.name} — {', '.join(depts[:4])}")
                if len(fixable) > 15:
                    print(f"    … 외 {len(fixable) - 15}곳")
            # 어떤 낱말이 자주 나오는지 보면 키워드에 무엇을 더할지 알 수 있다.
            from collections import Counter
            words = Counter()
            for s, depts in fixable:
                for d in depts:
                    name = d.replace("과", "").replace("학", "")
                    if len(name) >= 2 and not is_placeholder(d):
                        words[name] += 1
            if words:
                print("\n  자주 나오는 학과 이름 (키워드 후보)")
                for name, n in words.most_common(20):
                    print(f"    {n:>3}회  {name}")

        if args.lat is None or args.lng is None:
            print("\n  거리 검사는 --lat --lng 를 주면 함께 봅니다.")
            return 0

        print(f"\n  ({args.lat}, {args.lng}) 에서 {args.km}km 안")
        near = [s for s in with_geo
                if geo.within_commute(args.lat, args.lng, s, args.km)]
        print(f"    좌표 있는 곳 중 {len(near)}곳")

        both = [s for s in near
                if [d for d in (s.departments or "").splitlines() if d.strip()]]
        print(f"    그중 학과도 있는 곳 {len(both)}곳")

        if not both:
            print("\n  추천이 비는 이유가 여기 있습니다.")
            if not near:
                print("  이 거리 안에 좌표가 등록된 학교가 없습니다.")
                print("  거리를 늘려보거나, 학교 좌표를 채워주세요.")
            else:
                print("  가까운 학교는 있는데 학과가 등록되지 않았습니다.")
        else:
            print("\n  가까운 곳 몇 개:")
            rows = sorted(both, key=lambda s: geo.school_distance_km(
                args.lat, args.lng, s))[:8]
            for s in rows:
                d = geo.school_distance_km(args.lat, args.lng, s)
                depts = [x.strip() for x in s.departments.splitlines() if x.strip()]
                print(f"    {d:5.1f}km  {s.name}  ({', '.join(depts[:3])})")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
