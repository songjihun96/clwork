"""영상 시연용 UDJ 백엔드 — 실제 backend/app 코드를 그대로 쓰되 DB 만 테스트 DB 로 바꿔 띄운다.

    .venv/Scripts/python.exe run_backend.py          # http://127.0.0.1:8800

- 운영 DB·운영 서버와 무관하다. DB 파일: video/school-demo/data/demo.db
- 기존 코드는 한 줄도 고치지 않는다. import 전에 app.database 의 engine 만 갈아 끼운다.
- 기사 크롤러는 끈다(ARTICLE_CRAWL_HOURS=0). 외부 사이트에 요청하지 않게.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1] / "backend"
DB_FILE = HERE / "data" / "demo.db"
PORT = int(os.getenv("DEMO_PORT", "8800"))

os.environ.setdefault("ARTICLE_CRAWL_HOURS", "0")
os.environ.setdefault("ENV", "development")
# 테스트 전용 서명 키(운영 키와 무관). 32자 이상이어야 경고가 안 뜬다.
os.environ.setdefault("SECRET_KEY", "udj-video-demo-only-secret-key-0000000000")
os.environ.setdefault("SITE_BASE_URL", "http://127.0.0.1:5190")
sys.path.insert(0, str(BACKEND))


def patch_engine():
    from sqlalchemy import create_engine
    import app.database as database

    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    database.engine = create_engine(f"sqlite:///{DB_FILE}", connect_args={"check_same_thread": False})
    database.SessionLocal.configure(bind=database.engine)
    return database


def patch_mailer():
    """메일을 실제로 보내지 않고 data/outbox/*.eml 로 저장한다(backend/app/full_test.py 와 같은 방식).

    화면에는 '발송됨'으로 보이지만 어떤 주소로도 나가지 않는다.
    """
    from email.message import EmailMessage
    from datetime import datetime
    import app.mailer as mailer

    for k, v in {"SMTP_HOST": "outbox.local", "SMTP_FROM": "noreply@example.com",
                 "SMTP_PASSWORD": "not-used"}.items():
        os.environ.setdefault(k, v)
    outbox = HERE / "data" / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)

    def save(cfg, to_addr, subject, body, from_name="", attachments=None, reply_to=None):
        if not cfg.is_ready():
            return False, "메일 계정이 설정되지 않았습니다."
        m = EmailMessage()
        m["From"], m["To"], m["Subject"] = f"{from_name} <{cfg.sender}>", to_addr, subject
        m.set_content(body)
        name = datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".eml"
        (outbox / name).write_bytes(bytes(m))
        return True, ""

    mailer.send_email = save


if __name__ == "__main__":
    patch_engine()
    patch_mailer()
    import uvicorn
    from app.main import app  # noqa: E402  (engine 교체 뒤에 불러야 한다)

    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
