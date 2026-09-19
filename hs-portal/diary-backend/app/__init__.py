"""앱 패키지를 불러올 때 diary-backend/.env 를 먼저 읽는다."""

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
