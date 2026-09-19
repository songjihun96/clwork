"""전화망 어댑터의 계약.

이 파일 아래에는 상담·고객·순차분배 이야기가 한 줄도 없다. 그게 요점이다.
전화 사업자가 바뀌어도 CS 시스템을 다시 만들지 않으려면, 사업자를 아는 코드가
여기(그리고 같은 폴더의 구현체들)에만 있어야 한다.

거꾸로, 여기서는 상담원이 몇 명인지·누가 먼저 받는지 알지 못한다. 그건
callcenter/engine.py 의 몫이다.

    [PSTN]  →  Provider 구현체  →  CallEvent  →  엔진  →  WebSocket  →  브라우저
              (사업자 API/SIP)                  (사업자 모름)

Provider 는 두 방향으로 말한다.

  들어오는 쪽   망에서 무슨 일이 생기면 CallEvent 를 만들어 sink 로 넘긴다.
  나가는 쪽     엔진이 answer/reject/hangup/transfer/make_call 을 부른다.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional


class CallEventType(str, enum.Enum):
    """망에서 올라오는 사건. 사업자마다 이름이 다르므로 여기로 번역해 받는다."""

    CALL_INCOMING = "CALL_INCOMING"   # 전화가 도착했다
    CALL_RINGING = "CALL_RINGING"     # 특정 단말에 벨이 울리기 시작했다
    CALL_ANSWERED = "CALL_ANSWERED"   # 누군가 받았다
    CALL_REJECTED = "CALL_REJECTED"   # 받는 쪽이 끊었다
    CALL_MISSED = "CALL_MISSED"       # 아무도 받지 않았다
    CALL_ENDED = "CALL_ENDED"         # 통화가 끝났다
    CALL_FAILED = "CALL_FAILED"       # 회선 오류


class CallDirection(str, enum.Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


@dataclass
class CallEvent:
    """망 → 우리. 사업자 고유 필드는 raw 에만 담고 위쪽으로 새지 않게 한다."""

    type: CallEventType
    external_call_id: str
    from_number: str = ""
    to_number: str = ""
    direction: CallDirection = CallDirection.INBOUND
    at: datetime = field(default_factory=datetime.utcnow)
    # 사업자별 원문. 로그·디버깅용이며 개인정보가 들어갈 수 있으므로
    # 그대로 저장하거나 출력하지 않는다.
    raw: Dict = field(default_factory=dict)


@dataclass
class CallSnapshot:
    """지금 이 통화가 어떤 상태인지에 대한 Provider 의 대답."""

    external_call_id: str
    from_number: str = ""
    to_number: str = ""
    direction: CallDirection = CallDirection.INBOUND
    # incoming / ringing / answered / ended / failed
    state: str = "incoming"
    started_at: Optional[datetime] = None
    answered_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None


# Provider 가 CallEvent 를 넘겨줄 함수의 모양.
EventSink = Callable[[CallEvent], None]


class PhoneProvider(ABC):
    """전화 사업자 어댑터.

    구현체는 이 메서드들만 채우면 된다. 지원하지 않는 기능은 capabilities 에서
    False 로 알린다. 못 하는 일을 조용히 성공한 척하면 상담원이 화면을 믿을 수
    없게 되므로, 그때는 예외를 던지거나 False 를 돌려준다.
    """

    #: 통화 기록에 남길 이름. DB 의 cs_call_logs.provider 에 그대로 들어간다.
    name: str = "base"

    def __init__(self) -> None:
        self._sink: Optional[EventSink] = None

    # ── 수명주기 ────────────────────────────────────────────

    @abstractmethod
    def initialize(self, config: Optional[Dict] = None) -> None:
        """설정을 받아 연결을 준비한다. 서버 기동 때 한 번 부른다."""

    def set_webhook(self, sink: EventSink) -> None:
        """망에서 사건이 생기면 부를 함수를 등록한다.

        실제 사업자에서는 HTTP 웹훅 핸들러가 이 sink 를 대신 부르게 된다.
        """
        self._sink = sink

    def emit(self, event: CallEvent) -> None:
        """구현체가 사건을 위로 올릴 때 쓰는 통로."""
        if self._sink is not None:
            self._sink(event)

    # ── 기능 신고 ───────────────────────────────────────────

    def capabilities(self) -> Dict[str, bool]:
        """이 사업자가 실제로 할 수 있는 일.

        화면은 이 값을 보고 버튼을 살리거나 죽인다. 눌러도 아무 일이 없는
        버튼을 두는 것보다, 없다고 말하는 편이 정직하다.
        """
        return {
            "inbound": True,
            "outbound": False,
            "transfer": False,
            "recording": False,
            "webrtc_audio": False,   # 브라우저로 실제 음성이 흐르는가
        }

    # ── 들어오는 통화 ───────────────────────────────────────

    @abstractmethod
    def receive_call(
        self,
        from_number: str,
        to_number: str = "",
        external_call_id: Optional[str] = None,
    ) -> CallSnapshot:
        """망에 전화가 도착했음을 Provider 에 알린다.

        실제 사업자에서는 웹훅 핸들러가 부른다. Mock 에서는 테스트 버튼이 부른다.
        """

    @abstractmethod
    def ring_agent(self, external_call_id: str, agent_key: str) -> bool:
        """이 통화를 특정 상담원 단말로 울린다.

        agent_key 는 상담원의 SIP 계정·내선 등 사업자가 아는 식별자다.
        누구를 먼저 부를지는 엔진이 정하고, 실제로 벨을 울리는 일만 여기서 한다.
        """

    @abstractmethod
    def answer_call(self, external_call_id: str) -> bool:
        """상담원이 받았다고 망에 알린다."""

    @abstractmethod
    def reject_call(self, external_call_id: str, reason: str = "") -> bool:
        """상담원이 거절했다고 망에 알린다. 통화 자체가 끊기는 것은 아니다."""

    @abstractmethod
    def hangup_call(self, external_call_id: str) -> bool:
        """통화를 끊는다."""

    def transfer_call(self, external_call_id: str, to: str) -> bool:
        """다른 번호·내선으로 돌린다. 지원하지 않으면 False."""
        return False

    # ── 나가는 통화 ─────────────────────────────────────────

    def make_call(self, to_number: str, from_display: str = "") -> CallSnapshot:
        """상담원이 고객에게 건다.

        from_display(발신번호 표시)는 사업자 설정을 따른다. CS 가 임의로
        바꿀 수 있다고 가정하지 않는다. 전기통신사업법상 발신번호 변작은
        금지이며, 표시 가능한 번호는 사업자에 사전 등록된 것뿐이다.
        """
        raise NotImplementedError("이 사업자는 발신을 지원하지 않습니다.")

    # ── 조회 ────────────────────────────────────────────────

    @abstractmethod
    def get_call_status(self, external_call_id: str) -> Optional[CallSnapshot]:
        """모르는 통화면 None."""

    @abstractmethod
    def get_active_calls(self) -> List[CallSnapshot]:
        """Provider 가 보기에 아직 살아 있는 통화들."""

    # ── 웹훅 검증 ───────────────────────────────────────────

    def verify_webhook(self, headers: Dict[str, str], body: bytes) -> bool:
        """사업자가 보낸 웹훅이 진짜인지 확인한다.

        기본은 거절이다. 검증 방법을 모르는 채로 열어두면 아무나 가짜 전화를
        밀어 넣을 수 있다. 구현체가 서명 방식을 알 때만 True 를 낼 수 있다.
        """
        return False


class RecordingProvider(ABC):
    """통화 녹취.

    지금은 인터페이스만 둔다. 실제로 켜기 전에 통화녹음 고지 의무와
    보관·파기 기준을 따로 검토해야 한다. 파일은 우리가 들고 있지 않고
    사업자가 준 주소(URL/파일 ID)만 기록에 남긴다.
    """

    name: str = "none"

    @abstractmethod
    def start(self, external_call_id: str) -> bool: ...

    @abstractmethod
    def stop(self, external_call_id: str) -> Optional[str]:
        """녹취를 멈추고 접근 주소를 돌려준다. 없으면 None."""

    @abstractmethod
    def get_url(self, external_call_id: str) -> Optional[str]: ...


class NullRecordingProvider(RecordingProvider):
    """녹취를 하지 않는다. 기본값.

    실패가 아니라 정책이므로 예외를 던지지 않고 아무것도 없다고 대답한다.
    """

    name = "none"

    def start(self, external_call_id: str) -> bool:
        return False

    def stop(self, external_call_id: str) -> Optional[str]:
        return None

    def get_url(self, external_call_id: str) -> Optional[str]:
        return None
