"""통화 음성을 전화망과 상담원 브라우저 사이에서 이어주는 다리.

    고객 ──PSTN──> ClawOps ──WebSocket──> 우리 ──WebSocket──> 상담원 브라우저
                   (G.711 μ-law 8kHz, base64)          (같은 프레임 그대로)

SIP 트렁크 부가서비스 없이 PC 로 통화하기 위한 길이다. 사업자가 통화 음성을
WebSocket 으로 직접 보내주므로(VoiceML 의 <Connect><Stream>), 우리가 그것을
브라우저로 넘기고 브라우저의 마이크 소리를 되돌려 보내면 통화가 된다.

**반드시 워커 1개짜리 프로세스에서 돌려야 한다.**
두 WebSocket 이 같은 프로세스에 있어야 소리를 이어붙일 수 있다. 워커가 3개면
사업자 쪽과 상담원 쪽이 서로 다른 워커에 붙어 소리가 흐르지 않는다. 앞서
전화 상태를 DB 로 넘긴 방법은 여기서 못 쓴다. 초당 50프레임짜리 음성을 DB 로
보낼 수는 없기 때문이다. 그래서 배포는 별도 서비스(udt-audio, 8010)로 한다.

우리는 음성을 해석하지 않는다. base64 문자열을 그대로 옮긴다. 그래야 빠르고,
사업자가 코덱을 바꿔도 이 파일은 그대로다. 다만 아무도 받기 전에 고객에게
들려줄 **통화연결음만은** 여기서 만들어야 해서, 그 부분만 μ-law 를 안다.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import math
import os
import struct
import time
from typing import Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt

from ..auth import ALGORITHM, SECRET_KEY
from ..database import SessionLocal
from ..models import CsCallLog, CsCallSession, Role, User
from . import sounds

log = logging.getLogger("callcenter.audio")

router = APIRouter(tags=["cs-phone-audio"])

SAMPLE_RATE = 8000
FRAME_BYTES = 160          # 20ms
FRAME_SECONDS = 0.02

# 이 주소로 아무나 붙어 남의 통화를 듣지 못하게, 통화마다 짧게 사는 표를 만든다.
STREAM_TOKEN_TTL = 60 * 60


# ══════════════════════════════════════════════════════════════
#  통화별 다리
# ══════════════════════════════════════════════════════════════


class Bridge:
    """통화 하나. 한쪽은 전화망, 한쪽은 상담원 브라우저."""

    def __init__(self, call_id: int) -> None:
        self.call_id = call_id
        self.network: Optional[WebSocket] = None    # ClawOps 쪽
        self.agent: Optional[WebSocket] = None      # 상담원 브라우저 쪽
        self.agent_user_id: Optional[int] = None
        self.created_at = time.time()
        self.closing = False

    async def to_network(self, payload_b64: str) -> None:
        """상담원 목소리를 고객에게."""
        ws = self.network
        if ws is None:
            return
        try:
            await ws.send_text(json.dumps(
                {"event": "media", "media": {"payload": payload_b64}}
            ))
        except Exception:
            self.network = None

    async def to_agent(self, payload_b64: str) -> None:
        """고객 목소리를 상담원에게."""
        ws = self.agent
        if ws is None:
            return
        try:
            await ws.send_text(json.dumps({"t": "audio", "p": payload_b64}))
        except Exception:
            self.agent = None


_bridges: Dict[int, Bridge] = {}


def _bridge(call_id: int) -> Bridge:
    b = _bridges.get(call_id)
    if b is None:
        b = Bridge(call_id)
        _bridges[call_id] = b
    return b


def _drop(call_id: int) -> None:
    _bridges.pop(call_id, None)


def active_bridge_count() -> int:
    return len(_bridges)


# ══════════════════════════════════════════════════════════════
#  통화연결음
# ══════════════════════════════════════════════════════════════


def _linear_to_ulaw(sample: int) -> int:
    """16비트 PCM 한 칸을 G.711 μ-law 한 바이트로."""
    BIAS, CLIP = 0x84, 32635
    sign = 0x80 if sample < 0 else 0
    if sign:
        sample = -sample
    if sample > CLIP:
        sample = CLIP
    sample += BIAS
    exponent = 7
    mask = 0x4000
    while exponent > 0 and not (sample & mask):
        exponent -= 1
        mask >>= 1
    mantissa = (sample >> (exponent + 3)) & 0x0F
    return (~(sign | (exponent << 4) | mantissa)) & 0xFF


def _build_ringback() -> list:
    """국내 통화연결음(440Hz+480Hz, 1초 울리고 2초 쉼)을 20ms 조각들로 만든다.

    아무 소리도 안 내면 고객은 전화가 끊긴 줄 안다. 파일을 두지 않고 계산으로
    만드는 이유는, 배포할 때 챙길 것이 하나라도 적어야 하기 때문이다.
    """
    frames = []
    total = int(3.0 / FRAME_SECONDS)          # 3초 한 바퀴
    on_frames = int(1.0 / FRAME_SECONDS)      # 앞 1초만 소리
    n = 0
    for f in range(total):
        buf = bytearray()
        for _ in range(FRAME_BYTES):
            if f < on_frames:
                v = (math.sin(2 * math.pi * 440 * n / SAMPLE_RATE)
                     + math.sin(2 * math.pi * 480 * n / SAMPLE_RATE))
                sample = int(v * 6000)        # 너무 크면 귀가 아프다
            else:
                sample = 0
            buf.append(_linear_to_ulaw(sample))
            n += 1
        frames.append(base64.b64encode(bytes(buf)).decode())
    return frames


_RINGBACK = _build_ringback()


async def _play_ringback(bridge: Bridge) -> None:
    """상담원이 받을 때까지 고객에게 연결음을 들려준다.

    관리자가 올린 대기음이 있으면 그것을, 없으면 기본 연결음을 쓴다.
    통화가 시작될 때 한 번만 고른다. 통화 도중에 바뀌면 소리가 튄다.
    """
    frames = sounds.hold_frames() or _RINGBACK
    i = 0
    try:
        while not bridge.closing and bridge.agent is None:
            await bridge.to_network(frames[i % len(frames)])
            i += 1
            await asyncio.sleep(FRAME_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("연결음 재생 중단(call=%s): %s", bridge.call_id, exc)


# ══════════════════════════════════════════════════════════════
#  주소 서명
# ══════════════════════════════════════════════════════════════


def _secret() -> str:
    return (os.getenv("PHONE_WEBHOOK_SECRET", "") or SECRET_KEY).strip()


def stream_token(call_id: int) -> str:
    """전화망이 붙을 주소에 실어 보낼 표.

    이 WebSocket 은 인증 없이 인터넷에 열려 있다. 표가 없으면 통화 번호만
    바꿔가며 남의 통화에 끼어들 수 있다.
    """
    exp = int(time.time()) + STREAM_TOKEN_TTL
    raw = f"{call_id}.{exp}"
    sig = hmac.new(_secret().encode(), raw.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{exp}.{sig}"


def _check_stream_token(call_id: int, token: str) -> bool:
    try:
        exp_s, sig = token.split(".", 1)
        exp = int(exp_s)
    except (ValueError, AttributeError):
        return False
    if exp < time.time():
        return False
    raw = f"{call_id}.{exp}"
    want = hmac.new(_secret().encode(), raw.encode(), hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(sig, want)


# ══════════════════════════════════════════════════════════════
#  전화망 쪽 WebSocket
# ══════════════════════════════════════════════════════════════


@router.websocket("/api/cs/phone/voice/stream/{call_id}")
async def network_stream(websocket: WebSocket, call_id: int, t: str = ""):
    """ClawOps 가 통화 음성을 보내오는 자리."""
    if not _check_stream_token(call_id, t):
        await websocket.close(code=4403)
        return

    await websocket.accept()
    bridge = _bridge(call_id)
    bridge.network = websocket
    print(f"[전화] 음성 연결됨 call={call_id}", flush=True)

    ring = asyncio.create_task(_play_ringback(bridge))
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if msg.get("event") != "media":
                continue
            payload = (msg.get("media") or {}).get("payload")
            if payload:
                await bridge.to_agent(payload)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("음성 연결 오류(call=%s): %s", call_id, exc)
    finally:
        bridge.closing = True
        ring.cancel()
        bridge.network = None
        agent = bridge.agent
        if agent is not None:
            try:
                await agent.send_text(json.dumps({"t": "ended"}))
                await agent.close()
            except Exception:
                pass
        _drop(call_id)
        print(f"[전화] 음성 연결 끊김 call={call_id}", flush=True)


# ══════════════════════════════════════════════════════════════
#  상담원 브라우저 쪽 WebSocket
# ══════════════════════════════════════════════════════════════


def _authenticate(token: str) -> Optional[int]:
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        return None


@router.websocket("/api/cs/ws/audio")
async def agent_stream(websocket: WebSocket, token: str = "", call_id: int = 0):
    """상담원 브라우저가 붙는 자리.

    자기에게 배정된 통화에만 붙을 수 있다. 통화 번호만 바꿔서 남의 통화를
    들을 수 없어야 한다.
    """
    user_id = _authenticate(token)
    if user_id is None or not call_id:
        await websocket.close(code=4401)
        return

    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None or not user.is_active or user.role not in (Role.cs, Role.admin):
            await websocket.close(code=4403)
            return
        call = db.get(CsCallLog, call_id)
        session = db.query(CsCallSession).filter(
            CsCallSession.call_log_id == call_id).first()
        mine = call is not None and (
            call.counselor_id == user_id
            or (session is not None and session.current_counselor_id == user_id)
        )
        if not mine:
            await websocket.close(code=4403)
            return
    finally:
        db.close()

    bridge = _bridges.get(call_id)
    if bridge is None or bridge.network is None:
        # 전화망 쪽이 아직 안 붙었거나 이미 끊겼다.
        await websocket.close(code=4404)
        return

    await websocket.accept()
    # 상담원이 붙는 순간 연결음이 멎고 진짜 통화가 시작된다.
    bridge.agent = websocket
    bridge.agent_user_id = user_id
    print(f"[전화] 상담원 음성 연결 call={call_id} user={user_id}", flush=True)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if msg.get("t") == "audio" and msg.get("p"):
                await bridge.to_network(msg["p"])
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("상담원 음성 오류(call=%s): %s", call_id, exc)
    finally:
        if bridge.agent is websocket:
            bridge.agent = None
            bridge.agent_user_id = None
        print(f"[전화] 상담원 음성 끊김 call={call_id}", flush=True)
