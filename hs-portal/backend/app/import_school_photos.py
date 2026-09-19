"""Google Places API로 특성화고·마이스터고 대표 이미지(hero_image)를 자동으로 채운다.

방식: 학교 이름+지역으로 Text Search를 불러 그 결과에 딸려오는 photos[0]의
photo_reference로 실제 이미지를 내려받아 우리 서버(UPLOAD_DIR)에 저장하고,
School.hero_image 를 "/api/uploads/{파일명}" 으로 채운다.
(Google Photo API URL을 그대로 저장하지 않는다 — API 키가 노출되고, 트래픽이
매번 구글에 과금되며, 참조가 만료될 수 있다.)

이미 hero_image가 있는 학교는 건드리지 않는다(--force로 덮어쓸 수 있음).
대상은 기본적으로 특성화고·마이스터고만(--category로 바꿀 수 있음) — 다른
카테고리까지 다 돌리면 비용이 커진다.

비용: Text Search에 photos 필드가 딸려오면 Enterprise+Atmosphere 요금
($40/1000, 월 1000건 무료)이 적용되고, 실제 이미지를 받는 Place Photo
호출은 별도 요금($7/1000, 월 1000건 무료)이 붙는다. 학교 수가 1000곳
미만이면 사실상 무료 한도 안에서 끝날 가능성이 높다 — 하지만 계정의
다른 사용량과 합산되므로 실행 전 Google Cloud 콘솔에서 예산 알림을 걸어두는
걸 권장한다.

사용 예:
    # 미리보기만(사진 존재 여부만 확인, 실제 다운로드/저장/커밋 없음 — 비용 최소화)
    python -m app.import_school_photos --dry-run

    # 학교 10곳만 테스트로 실제 반영
    python -m app.import_school_photos --limit 10

    # 전체 반영
    python -m app.import_school_photos

    # 이미 이미지가 있는 학교도 덮어쓰기
    python -m app.import_school_photos --force

API 키 발급: https://console.cloud.google.com → 프로젝트 생성 → 결제 계정 연결
    → "API 및 서비스" → "Places API" 사용 설정 → "사용자 인증 정보"에서 API 키 발급
    → .env 에 GOOGLE_PLACES_API_KEY=발급받은키 추가
"""
import argparse
import os
import secrets
import sys
import time
from typing import Optional

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models import School

TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
PHOTO_URL = "https://maps.googleapis.com/maps/api/place/photo"
DEFAULT_CATEGORIES = ["특성화고", "마이스터고", "종합고"]
MAX_PHOTO_BYTES = 5 * 1024 * 1024
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")


def find_photo_reference(api_key: str, school_name: str, region: str) -> Optional[str]:
    """학교 이름+지역으로 검색해 첫 결과의 첫 사진 photo_reference를 돌려준다. 없으면 None."""
    params = {
        "query": f"{school_name} {region}",
        "language": "ko",
        "region": "kr",
        "key": api_key,
    }
    try:
        resp = requests.get(TEXT_SEARCH_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        print(f"    검색 실패: {exc}")
        return None
    status = data.get("status")
    if status != "OK":
        if status != "ZERO_RESULTS":
            print(f"    구글 응답: {status} {data.get('error_message', '')}")
        return None
    results = data.get("results") or []
    if not results:
        return None
    photos = results[0].get("photos") or []
    if not photos:
        return None
    return photos[0].get("photo_reference")


def download_photo(api_key: str, photo_reference: str) -> Optional[bytes]:
    """photo_reference로 실제 이미지 바이트를 내려받는다."""
    params = {"maxwidth": 1200, "photoreference": photo_reference, "key": api_key}
    try:
        resp = requests.get(PHOTO_URL, params=params, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"    이미지 다운로드 실패: {exc}")
        return None
    data = resp.content
    if not data or len(data) > MAX_PHOTO_BYTES:
        return None
    return data


def save_photo(data: bytes, school_id: int) -> str:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    name = f"hero_{school_id}_{secrets.token_hex(6)}.jpg"
    with open(os.path.join(UPLOAD_DIR, name), "wb") as f:
        f.write(data)
    return f"/api/uploads/{name}"


def main() -> int:
    parser = argparse.ArgumentParser(description="특성화고·마이스터고 대표 이미지 자동 수집")
    parser.add_argument("--category", default=",".join(DEFAULT_CATEGORIES),
                         help="쉼표로 구분한 대상 카테고리 (기본: 특성화고,마이스터고)")
    parser.add_argument("--force", action="store_true", help="이미 이미지가 있어도 덮어쓴다")
    parser.add_argument("--dry-run", action="store_true",
                         help="사진 존재 여부만 확인하고 저장하지 않는다(다운로드/커밋 없음 — 비용 최소화)")
    parser.add_argument("--limit", type=int, default=None, help="테스트용: 앞에서 N곳만 처리")
    args = parser.parse_args()

    api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not api_key:
        print("GOOGLE_PLACES_API_KEY 환경변수가 없습니다. .env에 추가해주세요.")
        print("발급: https://console.cloud.google.com → Places API 사용 설정 → API 키 발급")
        return 1

    categories = [c.strip() for c in args.category.split(",") if c.strip()]

    db = SessionLocal()
    query = (
        db.query(School)
        .filter(School.category.in_(categories))
        .filter(School.is_visible == True)  # noqa: E712
        .order_by(School.id)
    )
    if args.limit:
        query = query.limit(args.limit)
    schools = query.all()
    db.close()

    print(f"대상: {', '.join(categories)} — {len(schools)}곳")
    if args.dry_run:
        print("(--dry-run: 사진 존재 여부만 확인하고 실제 다운로드/저장은 하지 않습니다)")

    matched = 0
    updated = 0
    skipped_existing = 0
    unmatched = []

    for i, school in enumerate(schools, 1):
        if school.hero_image and not args.force:
            skipped_existing += 1
            continue

        photo_ref = find_photo_reference(api_key, school.name, school.region)
        time.sleep(0.1)
        if not photo_ref:
            unmatched.append(f"{school.name} ({school.region})")
            continue
        matched += 1

        if args.dry_run:
            print(f"  [{i}/{len(schools)}] {school.name} ({school.region}): 사진 있음")
            continue

        data = download_photo(api_key, photo_ref)
        time.sleep(0.1)
        if not data:
            unmatched.append(f"{school.name} ({school.region}) - 다운로드 실패")
            continue

        db = SessionLocal()
        fresh = db.get(School, school.id)
        url = save_photo(data, fresh.id)
        fresh.hero_image = url
        db.commit()
        db.close()
        updated += 1
        print(f"  [{i}/{len(schools)}] {school.name} ({school.region}): {url}")

    print()
    print(f"완료 — 대상 {len(schools)}곳 중 사진 찾음 {matched}곳, "
          f"{'(dry-run, 저장 안 함)' if args.dry_run else f'실제로 반영 {updated}곳'}, "
          f"이미 이미지 있어 건너뜀 {skipped_existing}곳")
    if unmatched:
        print(f"사진을 못 찾은 곳 {len(unmatched)}곳:")
        for name in unmatched[:30]:
            print(f"  - {name}")
        if len(unmatched) > 30:
            print(f"  ... 외 {len(unmatched) - 30}곳")

    return 0


if __name__ == "__main__":
    sys.exit(main())
