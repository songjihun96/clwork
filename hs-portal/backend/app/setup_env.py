"""
첫 실행 때 backend/.env 를 만든다. 이미 있으면 손대지 않는다.

    python -m app.setup_env

배치 파일에서 이걸 부르는 이유: 배치 파일 안에서 키를 만들고 사용자 입력을 받는
코드는 괄호와 특수문자 때문에 잘 깨진다. 파이썬으로 옮기면 검증도 쉽다.
"""

import secrets
import sys
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

TEMPLATE = """# 이 파일에는 키가 들어 있습니다. 다른 사람에게 보내거나 커밋하지 마세요.

# JWT 서명 키. 이 값이 바뀌면 기존 로그인이 모두 풀립니다.
SECRET_KEY={secret_key}

# 나이스 교육정보 개방 포털 인증키 (https://open.neis.go.kr)
# 비워두면 교육청당 5곳씩만 들어옵니다.
NEIS_API_KEY={neis_key}

# 카카오 REST API 키. 지도에 학교를 표시하려면 필요합니다.
# https://developers.kakao.com 에서 앱을 만들고 REST API 키를 넣으세요.
KAKAO_REST_KEY={kakao_key}

# 첫 관리자 계정
ADMIN_EMAIL={admin_email}
ADMIN_PASSWORD={admin_password}
"""


def ask(prompt: str, default: str = "") -> str:
    try:
        value = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return default
    return value or default


def main() -> int:
    if ENV_PATH.exists():
        print("설정 파일이 이미 있습니다. 그대로 씁니다.")
        return 0

    print()
    print("  처음 실행이라 설정 파일을 만듭니다.")
    print()
    print("  나이스(NEIS) 인증키를 넣으면 전국 고등학교를 모두 받아옵니다.")
    print("  없으면 그냥 Enter를 누르세요. 교육청당 5곳씩만 들어옵니다.")
    print("  키 발급: https://open.neis.go.kr  (로그인 후 인증키 신청, 무료)")
    print()

    neis_key = ask("  NEIS 인증키: ")

    print()
    print("  관리자 계정 비밀번호를 정하세요. 8자 이상이어야 합니다.")
    while True:
        admin_password = ask("  관리자 비밀번호 (Enter 시 admin12345): ", "admin12345")
        if len(admin_password) >= 8:
            break
        print("  8자 이상으로 다시 입력하세요.")

    ENV_PATH.write_text(
        TEMPLATE.format(
            secret_key=secrets.token_hex(32),
            neis_key=neis_key,
            kakao_key="",
            admin_email="admin@school-portal.kr",
            admin_password=admin_password,
        ),
        encoding="utf-8",
    )

    print()
    print(f"  설정 파일을 만들었습니다: {ENV_PATH}")
    if not neis_key:
        print("  나중에 인증키를 넣으려면 이 파일의 NEIS_API_KEY 줄을 고치고")
        print("  update-schools.bat 을 실행하세요.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
