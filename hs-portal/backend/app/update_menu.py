"""
update-schools.bat 이 부르는 대화형 메뉴.

배치 파일은 ASCII만 담을 수 있어서(한국어 Windows가 CP949로 읽는 탓에
UTF-8 한글이 깨진다) 한글 안내는 여기서 출력한다.
"""

import subprocess
import sys
from pathlib import Path

from .database import SessionLocal
from .models import School

BACKEND_DIR = Path(__file__).resolve().parent.parent

MENU = {
    "1": ("특성화고 / 마이스터고 / 특목고 갱신", ["--majors"]),
    "2": ("일반고까지 포함해 전체 갱신", ["--all", "--majors"]),
    "3": ("주소를 지도 좌표로 변환 (카카오 키 필요)", ["--geocode"]),
}


def current_count() -> int:
    db = SessionLocal()
    try:
        return db.query(School).count()
    except Exception:
        return 0
    finally:
        db.close()


def main() -> int:
    print()
    print("  나이스에서 학교 정보를 다시 받아옵니다.")
    print("  이미 있는 학교는 학교코드로 찾아 갱신하므로 중복되지 않습니다.")
    print()
    print(f"  지금 등록된 학교: {current_count()}개")
    print()
    for key, (label, _) in MENU.items():
        print(f"    {key}. {label}")
    print()

    try:
        choice = input("  번호를 고르세요 (1-3, 기본 1): ").strip() or "1"
    except (EOFError, KeyboardInterrupt):
        print()
        return 0

    if choice not in MENU:
        print("  1에서 3 사이로 골라주세요.")
        return 1

    label, args = MENU[choice]
    print()
    print(f"  실행: {label}")
    print()

    result = subprocess.run(
        [sys.executable, "-m", "app.import_neis", *args],
        cwd=BACKEND_DIR,
    )

    print()
    print(f"  등록된 학교: {current_count()}개")
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
