"""실제 전화 없이 콜센터 전체를 돌려보기 위한 Provider.

전화 사업자를 아직 고르지 않았다. 그렇다고 순차분배·대기열·상담기록을
못 만들 이유는 없다. Mock 은 망 대신 서서, 엔진 입장에서는 진짜와 구별되지
않는 사건을 만들어 준다.

Mock 이 하지 않는 일이 하나 있다. 음성이다.
마이크는 잡히고 통화 시간은 흐르지만 소리는 어디로도 가지 않는다.
그건 게이트웨이가 있어야 되는 일이고, 없는 것을 있는 척하지 않는다.

상태를 프로세스 메모리에 둔다. 운영은 워커 3개라 워커마다 기억이 다르지만,
콜의 진짜 상태는 DB(cs_call_sessions)에 있고 이 표는 거울일 뿐이라 괜찮다.
그래서 모르는 통화 ID 를 받아도 실패시키지 않고 그 자리에서 만들어 받는다.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Dict, List, Optional

from .base import (
    CallDirection,
    CallEvent,
    CallEventType,
    CallSnapshot,
    PhoneProvider,
)


class MockPhoneProvider(PhoneProvider):
    name = "mock"

    def __init__(self) -> None:
        super().__init__()
        self._calls: Dict[str, CallSnapshot] = {}

    def initialize(self, config: Optional[Dict] = None) -> None:
        # 붙을 곳이 없으므로 할 일이 없다.
        self._calls.clear()

    def capabilities(self) -> Dict[str, bool]:
        return {
            "inbound": True,
            "outbound": True,      # 거는 흉내는 낸다
            "transfer": True,
            "recording": False,
            "webrtc_audio": False,  # 소리는 흐르지 않는다. 이 값을 화면이 보고 알린다.
        }

    # ── 내부 ────────────────────────────────────────────────

    def _touch(self, external_call_id: str) -> CallSnapshot:
        """모르는 통화면 그 자리에서 만들어 둔다(워커가 갈릴 수 있어서)."""
        call = self._calls.get(external_call_id)
        if call is None:
            call = CallSnapshot(
                external_call_id=external_call_id,
                state="incoming",
                started_at=datetime.utcnow(),
            )
            self._calls[external_call_id] = call
        return call

    # ── 들어오는 통화 ───────────────────────────────────────

    def receive_call(
        self,
        from_number: str,
        to_number: str = "",
        external_call_id: Optional[str] = None,
    ) -> CallSnapshot:
        call_id = external_call_id or f"mock-{secrets.token_hex(6)}"
        call = CallSnapshot(
            external_call_id=call_id,
            from_number=from_number,
            to_number=to_number,
            direction=CallDirection.INBOUND,
            state="incoming",
            started_at=datetime.utcnow(),
        )
        self._calls[call_id] = call
        self.emit(
            CallEvent(
                type=CallEventType.CALL_INCOMING,
                external_call_id=call_id,
                from_number=from_number,
                to_number=to_number,
                direction=CallDirection.INBOUND,
            )
        )
        return call

    def ring_agent(self, external_call_id: str, agent_key: str) -> bool:
        call = self._touch(external_call_id)
        call.state = "ringing"
        self.emit(
            CallEvent(
                type=CallEventType.CALL_RINGING,
                external_call_id=external_call_id,
                from_number=call.from_number,
                to_number=call.to_number,
                direction=call.direction,
                raw={"agent": agent_key},
            )
        )
        return True

    def answer_call(self, external_call_id: str) -> bool:
        call = self._touch(external_call_id)
        if call.state == "ended":
            return False
        call.state = "answered"
        call.answered_at = datetime.utcnow()
        self.emit(
            CallEvent(
                type=CallEventType.CALL_ANSWERED,
                external_call_id=external_call_id,
                from_number=call.from_number,
                to_number=call.to_number,
                direction=call.direction,
            )
        )
        return True

    def reject_call(self, external_call_id: str, reason: str = "") -> bool:
        call = self._touch(external_call_id)
        # 거절은 통화를 끝내지 않는다. 다음 상담원에게 넘어가야 하기 때문이다.
        call.state = "incoming"
        self.emit(
            CallEvent(
                type=CallEventType.CALL_REJECTED,
                external_call_id=external_call_id,
                from_number=call.from_number,
                to_number=call.to_number,
                direction=call.direction,
                raw={"reason": reason},
            )
        )
        return True

    def hangup_call(self, external_call_id: str) -> bool:
        call = self._touch(external_call_id)
        if call.state == "ended":
            return True
        call.state = "ended"
        call.ended_at = datetime.utcnow()
        self.emit(
            CallEvent(
                type=CallEventType.CALL_ENDED,
                external_call_id=external_call_id,
                from_number=call.from_number,
                to_number=call.to_number,
                direction=call.direction,
            )
        )
        return True

    def transfer_call(self, external_call_id: str, to: str) -> bool:
        call = self._touch(external_call_id)
        call.state = "ringing"
        self.emit(
            CallEvent(
                type=CallEventType.CALL_RINGING,
                external_call_id=external_call_id,
                from_number=call.from_number,
                to_number=call.to_number,
                direction=call.direction,
                raw={"transferred_to": to},
            )
        )
        return True

    # ── 나가는 통화 ─────────────────────────────────────────

    def make_call(self, to_number: str, from_display: str = "") -> CallSnapshot:
        call_id = f"mock-out-{secrets.token_hex(5)}"
        call = CallSnapshot(
            external_call_id=call_id,
            from_number=from_display,
            to_number=to_number,
            direction=CallDirection.OUTBOUND,
            state="ringing",
            started_at=datetime.utcnow(),
        )
        self._calls[call_id] = call
        self.emit(
            CallEvent(
                type=CallEventType.CALL_RINGING,
                external_call_id=call_id,
                from_number=from_display,
                to_number=to_number,
                direction=CallDirection.OUTBOUND,
            )
        )
        return call

    # ── 조회 ────────────────────────────────────────────────

    def get_call_status(self, external_call_id: str) -> Optional[CallSnapshot]:
        return self._calls.get(external_call_id)

    def get_active_calls(self) -> List[CallSnapshot]:
        return [c for c in self._calls.values() if c.state != "ended"]

    def verify_webhook(self, headers: Dict[str, str], body: bytes) -> bool:
        # Mock 에는 바깥에서 들어올 웹훅이 없다.
        return False
