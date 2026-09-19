"""SIP·웹훅 방식 전화 사업자용 골격.

아직 사업자를 고르지 않았다. 그래서 이 파일은 **동작하는 척하지 않는다.**
설정 없이 켜면 기동 때 바로 막고, 못 하는 일은 조용히 성공을 돌려주지 않는다.

사업자를 고른 뒤 채워야 할 것은 세 곳뿐이다.

  1. verify_webhook   그 사업자의 서명 방식대로 검증한다.
  2. parse_webhook    그 사업자의 이벤트 이름을 CallEventType 으로 옮긴다.
  3. 명령 메서드      answer/reject/hangup/transfer/make_call 을 그 사업자의
                      REST API(또는 SIP 제어)로 부른다.

엔진·API·화면은 손대지 않는다. 그러라고 이 계층을 뗀 것이다.

실제 연결 순서(스마텔 010 유지)
  ① 사업자에게서 DID 번호(070 등)를 받는다.
  ② 스마텔 착신전환 대상을 그 번호로 지정한다.
  ③ 그 번호로 들어온 콜을 사업자가 이 웹훅으로 넘기게 설정한다.
  ④ 상담원 브라우저의 음성 경로(WebRTC↔SIP)를 사업자 SDK/게이트웨이로 잇는다.
  ②와 ④는 사업자마다 되고 안 되고가 갈린다. 계약 전에 실제 통화로 확인한다.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Dict, List, Optional

from .base import (
    CallDirection,
    CallEvent,
    CallEventType,
    CallSnapshot,
    PhoneProvider,
)


class SipPhoneProvider(PhoneProvider):
    name = "sip"

    def __init__(self) -> None:
        super().__init__()
        self.base_url = ""
        self.api_key = ""
        self.webhook_secret = ""
        self.did_number = ""

    def initialize(self, config: Optional[Dict] = None) -> None:
        cfg = config or {}
        self.base_url = (cfg.get("base_url") or os.getenv("PHONE_API_BASE", "")).strip()
        self.api_key = (cfg.get("api_key") or os.getenv("PHONE_API_KEY", "")).strip()
        self.webhook_secret = (
            cfg.get("webhook_secret") or os.getenv("PHONE_WEBHOOK_SECRET", "")
        ).strip()
        # 착신전환을 받을 우리 대표번호(DID). 실제 번호는 코드가 아니라 .env 에만 둔다.
        self.did_number = (cfg.get("did_number") or os.getenv("PHONE_DID_NUMBER", "")).strip()

        missing = [
            key
            for key, val in (
                ("PHONE_API_BASE", self.base_url),
                ("PHONE_API_KEY", self.api_key),
                ("PHONE_WEBHOOK_SECRET", self.webhook_secret),
            )
            if not val
        ]
        if missing:
            # 반쯤 설정된 채로 뜨면 전화가 조용히 사라진다. 그럴 바엔 안 뜨는 게 낫다.
            raise RuntimeError(
                "SIP Provider 설정이 비어 있습니다: "
                + ", ".join(missing)
                + ". 사업자 확정 전에는 PHONE_PROVIDER=mock 으로 두세요."
            )

    def capabilities(self) -> Dict[str, bool]:
        # 사업자가 정해지기 전까지는 아무것도 약속하지 않는다.
        return {
            "inbound": True,
            "outbound": False,
            "transfer": False,
            "recording": False,
            "webrtc_audio": False,
        }

    # ── 웹훅 ────────────────────────────────────────────────

    def verify_webhook(self, headers: Dict[str, str], body: bytes) -> bool:
        """HMAC-SHA256 서명 검증(가장 흔한 방식으로 미리 깔아둔 기본형).

        사업자가 다른 방식(타임스탬프 포함, base64 등)을 쓰면 여기만 고친다.
        서명 헤더가 없으면 통과시키지 않는다.
        """
        if not self.webhook_secret:
            return False
        sent = (headers.get("x-signature") or headers.get("X-Signature") or "").strip()
        if not sent:
            return False
        calc = hmac.new(self.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        # 길이·내용 비교 시간이 새지 않도록 상수시간 비교를 쓴다.
        return hmac.compare_digest(calc, sent)

    def parse_webhook(self, data: Dict) -> Optional[CallEvent]:
        """사업자 이벤트 → 우리 CallEvent.

        사업자 확정 후 아래 표만 그 사업자의 이름으로 바꾸면 된다.
        모르는 이벤트는 무시한다. 억지로 해석하면 없는 전화가 화면에 뜬다.
        """
        mapping = {
            "incoming": CallEventType.CALL_INCOMING,
            "ringing": CallEventType.CALL_RINGING,
            "answered": CallEventType.CALL_ANSWERED,
            "rejected": CallEventType.CALL_REJECTED,
            "missed": CallEventType.CALL_MISSED,
            "completed": CallEventType.CALL_ENDED,
            "ended": CallEventType.CALL_ENDED,
            "failed": CallEventType.CALL_FAILED,
        }
        kind = mapping.get(str(data.get("event", "")).lower())
        call_id = str(data.get("call_id") or "").strip()
        if kind is None or not call_id:
            return None
        return CallEvent(
            type=kind,
            external_call_id=call_id,
            from_number=str(data.get("from") or ""),
            to_number=str(data.get("to") or ""),
            direction=(
                CallDirection.OUTBOUND
                if str(data.get("direction", "")).upper() == "OUTBOUND"
                else CallDirection.INBOUND
            ),
            raw=data,
        )

    # ── 아직 구현하지 않은 것들 ─────────────────────────────
    #
    # 사업자 API 를 모르는 상태에서 True 를 돌려주면, 상담원 화면에는 전화를
    # 받은 것으로 보이는데 실제로는 아무 일도 없는 상황이 된다. 그래서 전부
    # 명시적으로 막는다.

    def _todo(self, what: str):
        raise NotImplementedError(
            f"{what} 는 전화 사업자 확정 후 구현합니다. "
            "지금은 PHONE_PROVIDER=mock 으로 개발하세요."
        )

    def receive_call(
        self,
        from_number: str,
        to_number: str = "",
        external_call_id: Optional[str] = None,
    ) -> CallSnapshot:
        # 실제로는 웹훅이 이벤트를 올려주므로 이 경로는 쓰지 않는다.
        self._todo("receive_call")

    def ring_agent(self, external_call_id: str, agent_key: str) -> bool:
        self._todo("ring_agent")

    def answer_call(self, external_call_id: str) -> bool:
        self._todo("answer_call")

    def reject_call(self, external_call_id: str, reason: str = "") -> bool:
        self._todo("reject_call")

    def hangup_call(self, external_call_id: str) -> bool:
        self._todo("hangup_call")

    def get_call_status(self, external_call_id: str) -> Optional[CallSnapshot]:
        return None

    def get_active_calls(self) -> List[CallSnapshot]:
        return []
