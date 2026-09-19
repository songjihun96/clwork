"""문의 답변을 이메일로 보내는 SMTP 래퍼. 포털 계정 하나로만 보낸다.

법률 관련: 여기서 보내는 메일은 이용자가 직접 남긴 문의에 대한 '응답'이며
광고성 정보가 아니다(정보통신망법상 광고 표기 대상 아님). 마케팅 문구를 넣지 않는다.
"""

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr


# ---------- 발송 ----------
@dataclass
class MailConfig:
    host: str
    port: int
    username: str
    password: str  # 평문(복호화된 값)
    sender: str  # 보내는 주소
    use_ssl: bool = False

    def is_ready(self) -> bool:
        return bool(self.host and self.sender and self.password)


def system_config() -> MailConfig:
    """시스템 발송용(비밀번호 재설정 등) 계정. backend/.env 의 SMTP_* 값을 쓴다."""
    return MailConfig(
        host=os.getenv("SMTP_HOST", "").strip(),
        port=int(os.getenv("SMTP_PORT", "587") or 587),
        username=os.getenv("SMTP_USER", "").strip(),
        password=os.getenv("SMTP_PASSWORD", "").strip(),
        sender=(os.getenv("SMTP_FROM", "") or os.getenv("SMTP_USER", "")).strip(),
        use_ssl=os.getenv("SMTP_SSL", "").strip().lower() in ("1", "true", "yes"),
    )


def send_email(cfg: MailConfig, to_addr: str, subject: str, body: str, from_name: str = "", attachments=None, reply_to: str = None) -> tuple[bool, str]:
    """(성공여부, 오류메시지). 성공하면 오류메시지는 빈 문자열.

    attachments: [(filename, content_bytes, content_type), ...] 형태의 리스트(선택).
    """
    if not cfg.is_ready():
        return False, "메일 계정이 설정되지 않았습니다."

    msg = EmailMessage()
    msg["From"] = formataddr((from_name or cfg.sender, cfg.sender))
    msg["To"] = to_addr
    if reply_to:
        # 답장하면 학교 주소로 가도록 회신 주소를 지정한다
        msg["Reply-To"] = reply_to
    msg["Subject"] = subject
    msg.set_content(body)

    for att in attachments or []:
        filename, content, content_type = att
        ctype = content_type or "application/octet-stream"
        maintype, _, subtype = ctype.partition("/")
        if not subtype:
            maintype, subtype = "application", "octet-stream"
        msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)

    context = ssl.create_default_context()
    try:
        if cfg.use_ssl:
            with smtplib.SMTP_SSL(cfg.host, cfg.port, context=context, timeout=15) as server:
                server.login(cfg.username or cfg.sender, cfg.password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(cfg.host, cfg.port, timeout=15) as server:
                server.starttls(context=context)
                server.login(cfg.username or cfg.sender, cfg.password)
                server.send_message(msg)
        return True, ""
    except smtplib.SMTPAuthenticationError as exc:
        code = getattr(exc, "smtp_code", "")
        return False, (
            f"메일 계정 인증 실패({code}). 아이디·비밀번호를 확인하고, "
            "메일 서비스에서 SMTP 사용을 켰는지, 2단계 인증을 쓴다면 "
            "'앱 비밀번호'를 발급받아 넣었는지 확인하세요."
        )
    except Exception as exc:  # noqa: BLE001 - 어떤 실패든 상태로 남긴다
        return False, str(exc)[:280]
