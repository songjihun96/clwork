"""기록해에서 나가는 메일.

우리동네 직업계고와 같은 SMTP 계정을 쓴다. diary-backend/.env 에
아래 값을 넣으면 동작하고, 비어 있으면 메일을 보내지 않는다.

    SMTP_HOST=smtp.naver.com
    SMTP_PORT=587
    SMTP_USER=계정@naver.com
    SMTP_PASSWORD=앱비밀번호        (로그인 비밀번호가 아니다)
    SMTP_FROM=계정@naver.com        (비우면 SMTP_USER 를 쓴다)
    SMTP_SSL=false

메일이 안 나가도 업무가 멈추면 안 된다. 호출하는 쪽에서 실패를 받아
화면에 알리고, 그때는 사람이 직접 연락하면 된다.
"""

import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from typing import Tuple

TIMEOUT = 20


@dataclass
class MailConfig:
    host: str
    port: int
    username: str
    password: str
    sender: str
    use_ssl: bool = False

    def is_ready(self) -> bool:
        return bool(self.host and self.sender and self.password)


def system_config() -> MailConfig:
    # 값 뒤에 #주석을 붙이는 실수가 잦아 잘라낸다.
    def env(key: str, default: str = "") -> str:
        return (os.getenv(key, default) or "").split("#", 1)[0].strip()

    return MailConfig(
        host=env("SMTP_HOST"),
        port=int(env("SMTP_PORT", "587") or 587),
        username=env("SMTP_USER"),
        password=env("SMTP_PASSWORD"),
        sender=env("SMTP_FROM") or env("SMTP_USER"),
        use_ssl=env("SMTP_SSL").lower() in ("1", "true", "yes"),
    )


def is_ready() -> bool:
    return system_config().is_ready()


def send(to_addr: str, subject: str, body: str,
         from_name: str = "기록해") -> Tuple[bool, str]:
    """(성공여부, 오류메시지). 성공하면 오류메시지는 빈 문자열."""
    cfg = system_config()
    if not cfg.is_ready():
        return False, "메일 계정이 설정되지 않았습니다."
    if not (to_addr or "").strip():
        return False, "받는 사람 주소가 없습니다."

    msg = EmailMessage()
    msg["From"] = formataddr((from_name, cfg.sender))
    msg["To"] = to_addr.strip()
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        if cfg.use_ssl:
            server = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=TIMEOUT)
        else:
            server = smtplib.SMTP(cfg.host, cfg.port, timeout=TIMEOUT)
            server.starttls()
        with server:
            server.login(cfg.username or cfg.sender, cfg.password)
            server.send_message(msg)
        return True, ""
    except Exception as exc:
        return False, str(exc)[:300]
