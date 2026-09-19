"""ClawOps(팀러너스) 070 회선 어댑터.

ClawOps 는 Twilio 와 같은 방식으로 움직인다. 우리가 명령을 밀어 넣는 게 아니라,
**전화가 올 때마다 우리에게 물어보고 우리가 XML(VoiceML)로 답한다.**

    전화 도착 → ClawOps 가 우리 웹훅 POST → 우리가 <Dial timeout="20"> 응답
             → 20초 무응답 → ClawOps 가 action URL 을 다시 POST
             → 우리가 다음 상담원으로 <Dial> 응답  … 반복

이 되물어보는 구조가 우리 순차분배 엔진과 정확히 맞물린다. 20초를 세는 일은
ClawOps 가 하고, **누구를 부를지는 우리가 정한다.**

그래서 이 어댑터의 ring_agent 는 아무 일도 하지 않는다. 벨을 울리는 것은
명령이 아니라 웹훅 응답이기 때문이다(callcenter/voice.py). 인터페이스를 깨지
않으려고 자리만 지킨다.

설정(.env)
    PHONE_PROVIDER=clawops
    PHONE_API_KEY=            대시보드 > 개발자 > API 키
    PHONE_ACCOUNT_ID=         계정 ID
    PHONE_WEBHOOK_SECRET=     대시보드 > 개발자 > Webhook Signing Secret
    PHONE_DID_NUMBER=         발급받은 070 번호 (숫자만)

실제 번호와 키는 코드에 넣지 않는다. .env 에만 둔다.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

import requests

from .base import (
    CallDirection,
    CallSnapshot,
    PhoneProvider,
)

log = logging.getLogger("phone.clawops")

DEFAULT_BASE = "https://api.claw-ops.com"
TIMEOUT = 10  # 초. 전화가 울리는 동안 부르는 API 라 오래 기다릴 수 없다.


def _find_call_id(data) -> str:
    """응답 어디에 통화 ID 가 들어 있든 찾아낸다.

    사업자마다 CallId / call_id / sid / id 로 이름이 갈리고, 한 겹 감싸서
    주기도 한다. 이름 하나만 보고 있다가 못 잡으면, 상대가 받은 뒤에야
    "모르는 통화"가 되어 전화가 끊긴다. 실제로 그렇게 한 번 놓쳤다.
    """
    if not isinstance(data, dict):
        return ""
    for key in ("CallId", "call_id", "CallSid", "call_sid", "sid", "id"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    # 한 겹 감싸 주는 경우까지만 본다. 더 깊이 뒤지면 엉뚱한 값을 집는다.
    for key in ("call", "data", "result"):
        inner = data.get(key)
        if isinstance(inner, dict):
            found = _find_call_id(inner)
            if found:
                return found
    return ""


class ClawOpsProvider(PhoneProvider):
    name = "clawops"

    def __init__(self) -> None:
        super().__init__()
        self.base_url = DEFAULT_BASE
        self.api_key = ""
        self.account_id = ""
        self.webhook_secret = ""
        self.did_number = ""

    # ── 수명주기 ────────────────────────────────────────────

    def initialize(self, config: Optional[Dict] = None) -> None:
        cfg = config or {}
        self.base_url = (cfg.get("base_url") or os.getenv("PHONE_API_BASE", "")
                         or DEFAULT_BASE).rstrip("/")
        self.api_key = (cfg.get("api_key") or os.getenv("PHONE_API_KEY", "")).strip()
        self.account_id = (cfg.get("account_id") or os.getenv("PHONE_ACCOUNT_ID", "")).strip()
        self.webhook_secret = (
            cfg.get("webhook_secret") or os.getenv("PHONE_WEBHOOK_SECRET", "")
        ).strip()
        self.did_number = (cfg.get("did_number") or os.getenv("PHONE_DID_NUMBER", "")).strip()
        # SIP 트렁크 부가서비스를 켜고 만든 자격증명 ID.
        # 이 값이 있어야 브라우저로 전화를 받을 수 있다(없으면 휴대폰으로 돌린다).
        self.sip_credential_id = (
            cfg.get("sip_credential_id") or os.getenv("PHONE_SIP_CREDENTIAL_ID", "")
        ).strip()

        missing = [
            key for key, val in (
                ("PHONE_API_KEY", self.api_key),
                ("PHONE_ACCOUNT_ID", self.account_id),
                ("PHONE_WEBHOOK_SECRET", self.webhook_secret),
            ) if not val
        ]
        if missing:
            # 반쯤 설정된 채로 뜨면 전화가 조용히 사라진다. 그럴 바엔 안 뜨는 게 낫다.
            raise RuntimeError(
                "ClawOps 설정이 비어 있습니다: " + ", ".join(missing)
                + ". 값을 채우기 전에는 PHONE_PROVIDER=mock 으로 두세요."
            )

    def capabilities(self) -> Dict[str, bool]:
        return {
            "inbound": True,
            "outbound": True,
            "transfer": True,
            "recording": True,
            # 브라우저로 음성이 흐르려면 SIP 트렁크 부가서비스를 켜고 자격증명을
            # 만들어야 한다. 그 ID 가 설정돼 있을 때만 가능하다고 말한다.
            # 없으면 화면이 상담원 휴대폰으로 돌리는 방식만 권한다.
            "webrtc_audio": bool(self.sip_credential_id),
            # 20초를 세는 일은 ClawOps 의 <Dial timeout> 이 한다.
            # 우리 배경 ticker 가 같은 통화를 또 넘기면 이중으로 넘어간다.
            "external_ring_timeout": True,
        }

    # ── 웹훅 서명 ───────────────────────────────────────────

    def verify_webhook(self, headers: Dict[str, str], body: bytes) -> bool:
        """이 어댑터는 URL 과 파라미터가 필요해서 별도 메서드를 쓴다.

        base 의 서명(raw body 기준)과 계산 방식이 달라 여기서는 항상 False 를
        돌려준다. 실제 검증은 verify_signature() 가 한다. 잘못 불러도 통과되지
        않게 막아 두는 것이다.
        """
        return False

    def verify_signature(self, url: str, params: Dict[str, str], signature: str) -> bool:
        """ClawOps 서명 검증.

        서명 대상은 `웹훅 URL + (키를 사전순으로 정렬한 key+value 이어붙임)` 이고,
        HMAC-SHA256 결과를 Base64 로 비교한다. 헤더는 X-Signature.

        URL 이 한 글자만 달라도(끝의 / 유무, http/https) 서명이 어긋난다.
        대시보드에 등록한 주소와 완전히 같은 문자열을 넘겨야 한다.
        """
        if not self.webhook_secret or not signature:
            return False
        data = url + "".join(f"{k}{v}" for k, v in sorted(params.items()))
        expected = base64.b64encode(
            hmac.new(self.webhook_secret.encode(), data.encode(), hashlib.sha256).digest()
        ).decode()
        # 길이·내용 비교 시간이 새지 않도록 상수시간 비교를 쓴다.
        return hmac.compare_digest(signature, expected)

    # ── REST ────────────────────────────────────────────────

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _calls_url(self, call_id: str = "") -> str:
        base = f"{self.base_url}/v1/accounts/{self.account_id}/calls"
        return f"{base}/{call_id}" if call_id else base

    # ── 들어오는 통화 ───────────────────────────────────────

    def receive_call(
        self,
        from_number: str,
        to_number: str = "",
        external_call_id: Optional[str] = None,
    ) -> CallSnapshot:
        """실제로는 웹훅이 알려주므로 이 경로는 쓰지 않는다."""
        return CallSnapshot(
            external_call_id=external_call_id or "",
            from_number=from_number,
            to_number=to_number or self.did_number,
            direction=CallDirection.INBOUND,
            state="incoming",
            started_at=datetime.utcnow(),
        )

    def ring_agent(self, external_call_id: str, agent_key: str) -> bool:
        """여기서는 아무 일도 하지 않는다.

        ClawOps 에서 벨을 울리는 것은 명령이 아니라 **웹훅 응답**이다.
        누구에게 울릴지는 엔진이 세션에 적어두고, callcenter/voice.py 가
        그 값을 읽어 <Dial> XML 로 만들어 돌려준다.
        """
        return True

    def answer_call(self, external_call_id: str) -> bool:
        """상담원이 받는 순간도 망이 알려준다(DialCallStatus=completed).

        우리가 따로 할 일이 없다. 화면 상태는 엔진이 이미 바꿔 두었다.
        """
        return True

    def reject_call(self, external_call_id: str, reason: str = "") -> bool:
        """거절은 통화를 끊는 게 아니라 다음 사람으로 넘기는 일이다.

        넘기는 것은 웹훅 응답으로 하므로 여기서는 할 일이 없다.
        """
        return True

    def hangup_call(self, external_call_id: str) -> bool:
        if not external_call_id:
            return False
        try:
            r = requests.post(
                self._calls_url(external_call_id),
                headers=self._headers(),
                json={"Status": "completed"},
                timeout=TIMEOUT,
            )
            return r.status_code < 400
        except requests.RequestException as exc:
            log.warning("hangup 실패(call=%s): %s", external_call_id, exc)
            return False

    def transfer_call(self, external_call_id: str, to: str) -> bool:
        """호전환은 <Transfer>/<Dial> verb 로 한다.

        우리 화면의 '돌리기'는 이미 엔진이 다음 상담원을 세션에 적어두고,
        진행 중인 <Dial> 이 끝나면 action 콜백에서 그 사람에게 다시 건다.
        그래서 여기서 따로 부를 REST 가 없다.
        """
        return True

    # ── 나가는 통화 ─────────────────────────────────────────

    def make_call(self, to_number: str, from_display: str = "") -> CallSnapshot:
        """상담원이 고객에게 건다.

        발신번호(From)는 계정이 보유한 번호만 쓸 수 있다. 임의로 바꿀 수 없고
        바꿔서도 안 된다(전기통신사업법상 발신번호 변작 금지).

        Url 은 상대가 받은 뒤 통화를 어떻게 이어갈지 물어볼 우리 주소다.
        """
        callback = (os.getenv("PHONE_VOICE_BASE", "") or "").rstrip("/")
        payload = {
            "To": to_number,
            "From": from_display or self.did_number,
        }
        if callback:
            payload["Url"] = f"{callback}/api/cs/phone/voice/outbound"

        r = requests.post(self._calls_url(), headers=self._headers(),
                          json=payload, timeout=TIMEOUT)
        if r.status_code >= 400:
            raise RuntimeError(f"발신에 실패했습니다({r.status_code}): {r.text[:200]}")
        data = r.json() if r.content else {}
        call_id = _find_call_id(data)
        if not call_id:
            # 이 값을 못 잡으면 상대가 받았을 때 우리 기록을 찾지 못한다.
            # 사업자가 어떤 이름으로 주는지 알 수 있게 열쇠만 남긴다
            # (값에는 전화번호가 들어 있을 수 있어 적지 않는다).
            log.warning("발신 응답에서 통화 ID 를 못 찾았습니다. 응답 항목: %s",
                        sorted(data.keys()) if isinstance(data, dict) else type(data).__name__)
        return CallSnapshot(
            external_call_id=call_id,
            from_number=payload["From"],
            to_number=to_number,
            direction=CallDirection.OUTBOUND,
            state="ringing",
            started_at=datetime.utcnow(),
        )

    # ── 브라우저 전화기(WebRTC) ─────────────────────────────

    def issue_webrtc_token(self) -> Dict:
        """상담원 브라우저가 SIP 게이트웨이에 등록할 때 쓸 단기 토큰.

        토큰 수명이 5~7분이라 브라우저는 만료 전에 다시 받아 재등록해야 한다.
        받을 때마다 SIP 사용자명이 바뀌므로, 이 통화를 어디로 돌릴지도 함께 바뀐다.
        그래서 발급한 쪽(서버)이 그 주소를 기록해 둔다. 브라우저가 스스로
        신고하게 두면 남의 전화를 자기에게 돌리게 만들 수 있다.

        API 키는 절대 브라우저로 내려보내지 않는다. 이 함수만 키를 안다.
        """
        if not self.sip_credential_id:
            raise RuntimeError(
                "SIP 트렁크 부가서비스가 설정되지 않았습니다. "
                "PHONE_SIP_CREDENTIAL_ID 를 채우거나 상담원 휴대폰으로 받으세요."
            )
        url = (f"{self.base_url}/v1/accounts/{self.account_id}"
               f"/sip-credentials/{self.sip_credential_id}/tokens")
        r = requests.post(url, headers=self._headers(), timeout=TIMEOUT)
        if r.status_code >= 400:
            raise RuntimeError(f"SIP 토큰 발급 실패({r.status_code}): {r.text[:200]}")
        data = r.json() or {}

        token = data.get("token") or ""
        claims = {}
        if token:
            try:
                # 우리가 방금 TLS 로 받아온 값이라 서명을 다시 검증할 이유가 없다.
                # 안에 든 접속 정보만 꺼내 쓴다.
                from jose import jwt as _jwt
                claims = _jwt.get_unverified_claims(token) or {}
            except Exception as exc:
                raise RuntimeError(f"SIP 토큰을 읽지 못했습니다: {exc}")

        ice = data.get("ice_servers")
        if not ice:
            try:
                ir = requests.get(
                    f"{self.base_url}/v1/accounts/{self.account_id}/ice-servers",
                    headers=self._headers(), timeout=TIMEOUT)
                if ir.status_code < 400:
                    body = ir.json() or {}
                    ice = body.get("ice_servers") or body
            except (requests.RequestException, ValueError):
                ice = []

        username = str(claims.get("sip_username") or "")
        realm = str(claims.get("realm") or "")
        return {
            "sip_username": username,
            "sip_password": str(claims.get("sip_password") or ""),
            "ws_url": str(claims.get("ws_url") or ""),
            "realm": realm,
            "ice_servers": ice or [],
            # 이 통화를 어디로 돌릴지. VoiceML 의 <Sip> 안에 그대로 들어간다.
            "sip_uri": f"sip:{username}@{realm}" if username and realm else "",
            "expires_at": claims.get("exp"),
        }

    # ── 조회 ────────────────────────────────────────────────

    def get_call_status(self, external_call_id: str) -> Optional[CallSnapshot]:
        if not external_call_id:
            return None
        try:
            r = requests.get(self._calls_url(external_call_id),
                             headers=self._headers(), timeout=TIMEOUT)
            if r.status_code >= 400:
                return None
            d = r.json()
        except (requests.RequestException, ValueError):
            return None
        return CallSnapshot(
            external_call_id=external_call_id,
            from_number=str(d.get("From") or ""),
            to_number=str(d.get("To") or ""),
            direction=(CallDirection.OUTBOUND
                       if str(d.get("Direction", "")).lower() == "outbound"
                       else CallDirection.INBOUND),
            state=str(d.get("CallStatus") or "unknown"),
        )

    def get_active_calls(self) -> List[CallSnapshot]:
        """진행 중인 통화의 진짜 목록은 우리 DB(cs_call_sessions)에 있다.

        망에 다시 물어볼 이유가 없고, 전화가 울리는 동안 외부 API 를 도는 것은
        느리기만 하다.
        """
        return []
