"""휴대폰 본인확인용 SMS 발송 래퍼.

업체에 묶이지 않도록 두 곳을 지원한다. backend/.env 의 SMS_PROVIDER 로 고른다.

  SMS_PROVIDER=sens    네이버 클라우드 SENS (서버가 네이버 클라우드면 이쪽이 자연스럽다)
    SENS_SERVICE_ID, SENS_ACCESS_KEY, SENS_SECRET_KEY, SENS_SEND_NUMBER

  SMS_PROVIDER=aligo   알리고
    ALIGO_API_KEY, ALIGO_USER_ID, ALIGO_SEND_NUMBER

  SMS_PROVIDER=solapi  솔라피(구 CoolSMS)
    SOLAPI_API_KEY, SOLAPI_API_SECRET, SOLAPI_SEND_NUMBER
    개인 계정도 010 번호를 문자 본인인증만으로 발신번호 등록할 수 있어,
    사업자등록증 없이 시작할 수 있다.

  SMS_PROVIDER=none    (기본값) 실제로 보내지 않고 서버 로그에만 남긴다.
                       개발·테스트용이며 운영에서는 반드시 실제 업체를 지정해야 한다.

법률 관련: 여기서 보내는 문자는 이용자가 직접 요청한 본인확인 수단이며
광고성 정보가 아니다. 정보통신망법 제50조의 '(광고)' 표기 대상이 아니므로
마케팅 문구를 절대 넣지 않는다.
"""

import base64
import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timezone

import requests

TIMEOUT = 10


def _env_number(name: str) -> str:
    """환경변수에서 발신번호를 읽어 숫자만 남긴다.

    systemd 의 EnvironmentFile 은 값 뒤의 인라인 주석(# ...)을 잘라내지 않아
    "01012345678  # 메모" 같은 값이 그대로 들어오는 일이 있다. 하이픈·공백·주석을
    모두 털어내고 숫자만 쓴다.
    """
    raw = os.getenv(name, "") or ""
    raw = raw.split("#", 1)[0]
    return "".join(ch for ch in raw if ch.isdigit())


def channel() -> str:
    """인증번호를 어디로 보낼지 정한다.

    VERIFY_CHANNEL=sms | email 로 직접 지정할 수 있고, 비워두면 SMS 설정이
    갖춰졌는지 보고 자동으로 고른다. 덕분에 문자 계약 전에는 이메일로 열고,
    계약이 끝나면 .env 만 고쳐 전환할 수 있다.
    """
    ch = (os.getenv("VERIFY_CHANNEL", "") or "").strip().lower()
    if ch in ("sms", "email"):
        return ch
    return "sms" if is_ready() else "email"


def provider() -> str:
    return (os.getenv("SMS_PROVIDER", "") or "none").strip().lower()


def is_ready() -> bool:
    """실제 발송이 가능한 상태인지."""
    p = provider()
    if p == "sens":
        return all(
            os.getenv(k, "").strip()
            for k in ("SENS_SERVICE_ID", "SENS_ACCESS_KEY", "SENS_SECRET_KEY", "SENS_SEND_NUMBER")
        )
    if p == "aligo":
        return all(
            os.getenv(k, "").strip()
            for k in ("ALIGO_API_KEY", "ALIGO_USER_ID", "ALIGO_SEND_NUMBER")
        )
    if p == "solapi":
        return bool(
            os.getenv("SOLAPI_API_KEY", "").strip()
            and os.getenv("SOLAPI_API_SECRET", "").strip()
            and _env_number("SOLAPI_SEND_NUMBER")
        )
    return False


def _send_sens(phone: str, text: str) -> tuple[bool, str]:
    service_id = os.getenv("SENS_SERVICE_ID", "").strip()
    access_key = os.getenv("SENS_ACCESS_KEY", "").strip()
    secret_key = os.getenv("SENS_SECRET_KEY", "").strip()
    send_number = _env_number("SENS_SEND_NUMBER")

    uri = f"/sms/v2/services/{service_id}/messages"
    url = f"https://sens.apigw.ntruss.com{uri}"
    timestamp = str(int(time.time() * 1000))

    # SENS 서명 규칙: METHOD + 공백 + URI + 개행 + timestamp + 개행 + accessKey
    message = f"POST {uri}\n{timestamp}\n{access_key}"
    signature = base64.b64encode(
        hmac.new(secret_key.encode(), message.encode(), hashlib.sha256).digest()
    ).decode()

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "x-ncp-apigw-timestamp": timestamp,
        "x-ncp-iam-access-key": access_key,
        "x-ncp-apigw-signature-v2": signature,
    }
    body = {
        "type": "SMS",
        "from": send_number,
        "content": text,
        "messages": [{"to": phone}],
    }
    try:
        res = requests.post(url, json=body, headers=headers, timeout=TIMEOUT)
        if res.status_code in (200, 202):
            return True, ""
        return False, f"SENS 응답 {res.status_code}: {res.text[:200]}"
    except requests.RequestException as exc:
        return False, f"SENS 요청 실패: {exc}"


def _send_aligo(phone: str, text: str) -> tuple[bool, str]:
    data = {
        "key": os.getenv("ALIGO_API_KEY", "").strip(),
        "user_id": os.getenv("ALIGO_USER_ID", "").strip(),
        "sender": _env_number("ALIGO_SEND_NUMBER"),
        "receiver": phone,
        "msg": text,
    }
    try:
        res = requests.post("https://apis.aligo.in/send/", data=data, timeout=TIMEOUT)
        payload = res.json()
        # 알리고는 result_code 가 1 이상이면 성공
        if str(payload.get("result_code", "")).lstrip("-").isdigit() and int(payload["result_code"]) > 0:
            return True, ""
        return False, f"알리고 실패: {payload.get('message', '')[:200]}"
    except (requests.RequestException, ValueError) as exc:
        return False, f"알리고 요청 실패: {exc}"


def _send_solapi(phone: str, text: str) -> tuple[bool, str]:
    """솔라피 Messages v4.

    인증 헤더 형식:
      Authorization: HMAC-SHA256 apiKey=..., date=..., salt=..., signature=...
      signature = HMAC-SHA256(date + salt, apiSecret) 의 hex 값
    """
    api_key = os.getenv("SOLAPI_API_KEY", "").strip()
    api_secret = os.getenv("SOLAPI_API_SECRET", "").strip()
    sender = _env_number("SOLAPI_SEND_NUMBER")

    date = datetime.now(timezone.utc).isoformat()
    salt = secrets.token_hex(16)
    signature = hmac.new(
        api_secret.encode(), (date + salt).encode(), hashlib.sha256
    ).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "Authorization": (
            f"HMAC-SHA256 apiKey={api_key}, date={date}, "
            f"salt={salt}, signature={signature}"
        ),
    }
    body = {"message": {"to": phone, "from": sender, "text": text}}
    try:
        res = requests.post(
            "https://api.solapi.com/messages/v4/send",
            json=body, headers=headers, timeout=TIMEOUT,
        )
        if res.status_code in (200, 201):
            payload = res.json()
            # 실패 건은 statusCode 가 2000(성공) 이외의 값으로 온다.
            status = str(payload.get("statusCode", ""))
            if status and not status.startswith("2"):
                return False, f"솔라피 실패({status}): {payload.get('statusMessage', '')[:150]}"
            return True, ""
        return False, f"솔라피 응답 {res.status_code}: {res.text[:200]}"
    except (requests.RequestException, ValueError) as exc:
        return False, f"솔라피 요청 실패: {exc}"


def send_sms(phone: str, text: str) -> tuple[bool, str]:
    """문자를 보낸다. (성공여부, 오류메시지)를 돌려준다."""
    phone = (phone or "").replace("-", "").strip()
    if not phone:
        return False, "받는 번호가 없습니다."

    p = provider()
    if p == "sens":
        return _send_sens(phone, text)
    if p == "aligo":
        return _send_aligo(phone, text)
    if p == "solapi":
        return _send_solapi(phone, text)

    # 미설정: 운영자가 서버 로그로 확인할 수 있게만 남긴다.
    print(f"[SMS 미설정] {phone} 로 보낼 내용: {text}", flush=True)
    return False, "SMS 발송이 설정되지 않았습니다."
