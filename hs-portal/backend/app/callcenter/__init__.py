"""콜센터(전화 상담) 계층.

  phones.py   전화번호 정규화·표시·마스킹. 저장형은 하나뿐이어야 한다.
  engine.py   순차분배·대기열·상태 전이. 전화 사업자를 모른다.
  hub.py      상담원 브라우저로 나가는 실시간 통로(WebSocket).
  api.py      CS 콘솔이 부르는 HTTP 엔드포인트.
  voice.py    전화망이 우리에게 물어보는 자리(VoiceML 웹훅).
  audio.py    통화 음성을 전화망↔브라우저로 잇는 다리(워커 1개 전용).
  options.py  관리자가 바꾸는 상담 상태·우선순위.
  intake.py   전화가 아닌 경로(홈페이지 문의)로 들어온 상담.

전화망 자체는 ../phone/ 이 맡는다. 이 폴더는 그 위에서 업무만 본다.
"""

from .api import router, start_background, stop_background  # noqa: F401
from .voice import router as voice_router  # noqa: F401
from .audio import router as audio_router  # noqa: F401
