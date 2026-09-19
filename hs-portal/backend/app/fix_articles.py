"""이미 저장된 기사의 주소를 데스크톱으로 바꾸고, 빈 썸네일을 다시 채운다.

    python -m app.fix_articles --dry-run     무엇이 바뀌는지만 본다
    python -m app.fix_articles               실제로 고친다
    python -m app.fix_articles --limit 50    앞의 50건만 (먼저 확인용)

모바일 페이지(/m/)는 목록 썸네일을 지연 로딩으로 처리해 HTML 에 실제 이미지
주소가 없다. 그래서 예전에 모바일 주소로 수집한 기사는 썸네일이 비어 있다.
이 스크립트는 주소를 데스크톱으로 바꾸고, 상세 페이지에서 이미지를 다시 찾는다.
"""

import argparse
import sys
import time

from .articles import BASE, NEW_PATH, OLD_PATH, _clean, fetch_article_detail, to_new_url
from .database import SessionLocal
from .models import Article


def main() -> int:
    parser = argparse.ArgumentParser(description="기사 주소·썸네일 정리")
    parser.add_argument("--dry-run", action="store_true", help="바꾸지 않고 보기만 한다")
    parser.add_argument("--limit", type=int, help="처리할 최대 건수")
    parser.add_argument("--all", action="store_true",
                        help="썸네일이 있는 기사도 다시 확인한다(느림)")
    parser.add_argument("--url-only", action="store_true",
                        help="주소만 새 체계로 바꾼다(원문 요청 없이 빠르게)")
    parser.add_argument("--clean-text", action="store_true",
                        help="이미 저장된 제목·요약의 &nbsp; &lt; 같은 찌꺼기를 푼다"
                             "(원문 요청 없이 빠르게)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        # 2026년 8월 개편으로 /content/view.html 이 /news/view.html 로 바뀌었다.
        # no·category 값은 그대로라 경로만 갈아끼우면 된다.
        if args.url_only:
            rows = db.query(Article).filter(Article.url.contains(OLD_PATH)).all()
            print(f"옛 주소를 쓰는 기사 {len(rows)}건")
            for a_row in rows[:5]:
                print(f"  {a_row.url}\n   → {to_new_url(a_row.url)}")
            if args.dry_run:
                print("\n[미리보기] 아무것도 바꾸지 않았습니다.")
                return 0
            for a_row in rows:
                a_row.url = to_new_url(a_row.url)
            db.commit()
            print(f"\n{len(rows)}건의 주소를 새 체계로 바꿨습니다.")
            return 0

        # 예전 _clean 은 &nbsp; &amp; &quot; 넷만 바꿔서, &lt; &#8211;
        # &#8203; 같은 건 화면에 그대로 나왔다. 이미 저장된 기사는 다시
        # 수집하지 않으므로 여기서 한 번 씻어준다(원문 요청 없음).
        if args.clean_text:
            rows = db.query(Article).order_by(Article.id.desc()).all()
            if args.limit:
                rows = rows[: args.limit]
            fixed = 0
            for a_row in rows:
                new_title = _clean(a_row.title or "")[:300]
                new_summary = _clean(a_row.summary or "")
                if new_title == (a_row.title or "") and new_summary == (a_row.summary or ""):
                    continue
                if fixed < 10:
                    print(f"  {(a_row.title or '')[:46]}")
                    print(f"   → {new_title[:46]}")
                if not args.dry_run:
                    a_row.title = new_title
                    a_row.summary = new_summary
                fixed += 1
            if args.dry_run:
                db.rollback()
                print(f"\n[미리보기] 제목·요약 {fixed}건이 바뀝니다.")
            else:
                db.commit()
                print(f"\n제목·요약 {fixed}건을 고쳤습니다.")
            return 0

        q = db.query(Article)
        if not args.all:
            # 주소가 모바일이거나 썸네일이 비어 있는 것만 손본다.
            q = q.filter(
                (Article.url.contains("/m/")) | (Article.url.contains(OLD_PATH)) |
                (Article.thumbnail == "") | (Article.thumbnail.is_(None))
            )
        rows = q.order_by(Article.id.desc()).all()
        if args.limit:
            rows = rows[: args.limit]

        print(f"대상 기사 {len(rows)}건\n")
        url_fixed = thumb_fixed = 0

        for i, a in enumerate(rows, 1):
            changed = []

            new_url = to_new_url((a.url or "").replace(f"{BASE}/m/", f"{BASE}/"))
            if new_url != a.url:
                changed.append(f"주소 → 데스크톱")
                if not args.dry_run:
                    a.url = new_url
                url_fixed += 1

            if not (a.thumbnail or "").strip():
                detail = fetch_article_detail(new_url)
                thumb = (detail or {}).get("thumbnail", "")
                if thumb:
                    changed.append(f"썸네일 찾음")
                    if not args.dry_run:
                        a.thumbnail = thumb[:500]
                    thumb_fixed += 1
                time.sleep(0.3)      # 원문 서버 부담을 줄인다

            if changed:
                print(f"  [{i}/{len(rows)}] {(a.title or '')[:34]} — {', '.join(changed)}")

            if not args.dry_run and i % 20 == 0:
                db.commit()

        if args.dry_run:
            db.rollback()
            print(f"\n[미리보기] 주소 {url_fixed}건 · 썸네일 {thumb_fixed}건이 바뀝니다.")
            print("실제로 고치려면 --dry-run 을 빼고 실행하세요.")
        else:
            db.commit()
            print(f"\n주소 {url_fixed}건, 썸네일 {thumb_fixed}건을 고쳤습니다.")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"실패: {exc}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
