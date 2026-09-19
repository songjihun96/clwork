"""로컬 API 키 저장.

환경변수 ANTHROPIC_API_KEY가 있으면 그것을 우선 쓰고, 없으면 사용자가 GUI
설정 창에서 입력한 키를 이 파일 옆의 secrets.json에 저장해 재사용한다.
이 프로그램은 서버가 없는 완전 로컬 앱이므로 키는 실행 PC에만 저장된다.
"""

from __future__ import annotations

import json
import os

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRETS_PATH = os.path.join(APP_DIR, "secrets.json")


def get_api_key() -> str | None:
    if not os.path.exists(SECRETS_PATH):
        return None
    try:
        with open(SECRETS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("anthropic_api_key") or None
    except (json.JSONDecodeError, OSError):
        return None


def save_api_key(key: str) -> None:
    with open(SECRETS_PATH, "w", encoding="utf-8") as f:
        json.dump({"anthropic_api_key": key.strip()}, f, ensure_ascii=False, indent=2)
