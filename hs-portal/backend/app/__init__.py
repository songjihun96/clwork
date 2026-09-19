"""
앱 패키지를 불러올 때 backend/.env 를 먼저 읽는다.
이렇게 해두면 uvicorn이든 import_neis든 실행 방법과 상관없이 키가 적용된다.
"""

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
