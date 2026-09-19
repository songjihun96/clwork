"""토스페이먼츠 연동.

backend/.env 설정:
    TOSS_SECRET_KEY=live_sk_xxxxx      (테스트는 test_sk_xxxxx)
    TOSS_CLIENT_KEY=live_ck_xxxxx      (프런트에 내려보내는 공개 키)

결제 흐름
    1) 프런트가 주문을 만들고(서버에서 orderId·금액 확정)
    2) 토스 결제창을 띄운다
    3) 성공하면 paymentKey 를 받아 서버로 보낸다
    4) 서버가 토스 승인 API 를 호출해 최종 확정한다

3번에서 금액을 클라이언트가 보내주므로, 서버에 저장해 둔 금액과 반드시
대조해야 한다. 그러지 않으면 금액을 조작해 싸게 결제할 수 있다.
"""

import base64
import os
from typing import Optional, Tuple

import requests

API_BASE = "https://api.tosspayments.com/v1"
TIMEOUT = 15


def secret_key() -> str:
    return (os.getenv("TOSS_SECRET_KEY", "") or "").split("#", 1)[0].strip()


def client_key() -> str:
    return (os.getenv("TOSS_CLIENT_KEY", "") or "").split("#", 1)[0].strip()


def is_ready() -> bool:
    return bool(secret_key() and client_key())


def is_test_mode() -> bool:
    return secret_key().startswith("test_")


def _auth_header() -> dict:
    # 토스는 시크릿 키 뒤에 콜론을 붙여 base64 로 인코딩한 Basic 인증을 쓴다.
    token = base64.b64encode(f"{secret_key()}:".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def confirm(payment_key: str, order_id: str, amount: int) -> Tuple[bool, dict, str]:
    """결제를 최종 승인한다. (성공여부, 응답, 오류메시지)"""
    if not is_ready():
        return False, {}, "결제가 설정되지 않았습니다."
    try:
        res = requests.post(
            f"{API_BASE}/payments/confirm",
            json={"paymentKey": payment_key, "orderId": order_id, "amount": amount},
            headers=_auth_header(),
            timeout=TIMEOUT,
        )
        data = res.json()
        if res.status_code == 200:
            return True, data, ""
        # 토스는 실패 시 {code, message} 형태로 준다.
        return False, data, data.get("message") or f"승인 실패({res.status_code})"
    except (requests.RequestException, ValueError) as exc:
        return False, {}, f"결제 서버와 통신하지 못했습니다: {exc}"


def cancel(payment_key: str, reason: str, amount: Optional[int] = None) -> Tuple[bool, dict, str]:
    """결제를 취소(환불)한다. amount 를 주면 부분 취소."""
    if not is_ready():
        return False, {}, "결제가 설정되지 않았습니다."
    body = {"cancelReason": (reason or "고객 요청")[:200]}
    if amount is not None:
        body["cancelAmount"] = int(amount)
    try:
        res = requests.post(
            f"{API_BASE}/payments/{payment_key}/cancel",
            json=body,
            headers=_auth_header(),
            timeout=TIMEOUT,
        )
        data = res.json()
        if res.status_code == 200:
            return True, data, ""
        return False, data, data.get("message") or f"취소 실패({res.status_code})"
    except (requests.RequestException, ValueError) as exc:
        return False, {}, f"결제 서버와 통신하지 못했습니다: {exc}"


def lookup(payment_key: str) -> Tuple[bool, dict, str]:
    """결제 내역을 조회한다. 승인 결과가 불확실할 때 대조용으로 쓴다."""
    if not is_ready():
        return False, {}, "결제가 설정되지 않았습니다."
    try:
        res = requests.get(
            f"{API_BASE}/payments/{payment_key}",
            headers=_auth_header(),
            timeout=TIMEOUT,
        )
        data = res.json()
        if res.status_code == 200:
            return True, data, ""
        return False, data, data.get("message") or f"조회 실패({res.status_code})"
    except (requests.RequestException, ValueError) as exc:
        return False, {}, f"결제 서버와 통신하지 못했습니다: {exc}"
