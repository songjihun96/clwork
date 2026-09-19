"""상담원 화면으로 실시간 사건을 밀어주는 통로.

왜 방송을 메모리로 하지 않는가
------------------------------
WebSocket 연결은 그 연결을 받은 워커 프로세스에만 있다. 운영은 워커가 3개다.
1번 워커가 웹훅으로 전화를 받았는데 상담원이 2번 워커에 붙어 있으면, 메모리
방송으로는 그 전화가 화면에 뜨지 않는다. 조용히 못 받는 전화가 생긴다.

그래서 사건은 ``cs_call_events`` 표에 쌓고, 각 연결은 자기가 마지막으로 보낸
id 뒤부터 짧은 간격으로 읽어 간다. 워커가 몇 개든 모든 상담원이 같은 사건을
본다. 대가는 최대 ``POLL_SECONDS`` 만큼의 지연이다.

연결 주소
    /api/cs/ws/calls?token=<JWT>&device=<기기토큰>

브라우저 WebSocket 은 헤더를 못 붙이므로 토큰을 쿼리로 받는다. 대신 HTTP
쪽과 똑같이 권한·기기승인을 다시 확인한다. 여기만 느슨하면 관문을 우회하는
뒷문이 된다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from ..auth import ALGORITHM, SECRET_KEY
from ..database import SessionLocal
from ..models import CsCallEvent, Role, User

log = logging.getLogger("callcenter.hub")

# 사건을 얼마나 자주 확인할지. 짧을수록 즉각적이지만 DB 를 자주 두드린다.
# 상담원 3명 기준으로 0.7초면 사람 눈에는 즉시로 보이고 부하도 없다.
POLL_SECONDS = 0.7

# 아웃박스에 개인정보가 오래 남지 않도록 지운다.
EVENT_TTL_MINUTES = 60


def _authenticate(db: Session, token: str) -> Optional[User]:
    """WebSocket 은 Depends 를 못 쓰므로 직접 확인한다."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        return None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    if user.role not in (Role.cs, Role.admin):
        return None
    return user


async def calls_socket(ws: WebSocket, token: str = "", device: str = "") -> None:
    """상담원 한 명의 실시간 연결을 끝까지 돌본다."""
    # cs.py 의 관문을 그대로 다시 태운다. 순환 import 를 피하려고 여기서 부른다.
    from ..cs import client_ip, gate

    db = SessionLocal()
    try:
        user = _authenticate(db, token)
        if user is None:
            await ws.close(code=4401)  # 인증 실패
            return

        # 사무실 IP 인지, 승인된 기기인지. HTTP 요청과 같은 기준으로 본다.
        try:
            verdict = gate(db, ws, user, device)
        except Exception:
            verdict = {"how": "none"}
        if verdict.get("how") in ("none", "pending", "revoked"):
            await ws.close(code=4403)  # 기기 미승인
            return

        await ws.accept()

        # 접속한 순간 이전의 사건은 흘려보낸다. 지나간 전화를 뒤늦게 울리면
        # 상담원이 없는 전화를 받으려 한다.
        last_row = db.query(CsCallEvent.id).order_by(CsCallEvent.id.desc()).first()
        last_id = last_row[0] if last_row else 0

        await ws.send_text(json.dumps({
            "type": "CONNECTED",
            "counselor_id": user.id,
            "name": user.name,
            "ip": client_ip(ws),
        }, ensure_ascii=False))

        while True:
            # 브라우저가 보낸 것이 있으면 먼저 치운다(핑 정도만 온다).
            try:
                incoming = await asyncio.wait_for(ws.receive_text(), timeout=POLL_SECONDS)
                if incoming and incoming.strip() == "ping":
                    await ws.send_text(json.dumps({"type": "PONG"}))
            except asyncio.TimeoutError:
                pass

            rows = (
                db.query(CsCallEvent)
                .filter(CsCallEvent.id > last_id)
                .order_by(CsCallEvent.id.asc())
                .limit(50)
                .all()
            )
            for row in rows:
                last_id = row.id
                # 특정 상담원 앞으로 온 사건은 그 사람에게만 간다.
                if row.target_user_id and row.target_user_id != user.id:
                    continue
                try:
                    payload = json.loads(row.payload or "{}")
                except ValueError:
                    payload = {}
                payload["type"] = row.type
                payload["event_id"] = row.id
                # UTC 임을 밝혀 보낸다. 표시가 없으면 브라우저가 현지시각으로 읽어
                # 한국에서는 9시간 어긋난다(api.py 의 iso_utc 참고).
                payload["at"] = (row.created_at or datetime.utcnow()).isoformat() + "Z"
                await ws.send_text(json.dumps(payload, ensure_ascii=False, default=str))

            # 세션이 오래 열려 있으면 DB 가 옛 스냅숏을 붙들고 있어 새 행을
            # 못 본다. 매 회전마다 트랜잭션을 끊어준다.
            db.rollback()

    except WebSocketDisconnect:
        pass
    except Exception as exc:  # 한 연결의 사고가 서버를 흔들지 않게
        log.warning("WebSocket 종료: %s", exc)
        try:
            await ws.close()
        except Exception:
            pass
    finally:
        db.close()


def purge_old_events(db: Session) -> int:
    """오래된 아웃박스 행을 지운다. 사건은 흘러가는 것이라 보관 대상이 아니다.
    통화 기록은 cs_call_logs 에 따로 남는다."""
    cutoff = datetime.utcnow() - timedelta(minutes=EVENT_TTL_MINUTES)
    try:
        n = db.query(CsCallEvent).filter(CsCallEvent.created_at < cutoff).delete(
            synchronize_session=False
        )
        db.commit()
        return n
    except Exception:
        db.rollback()
        return 0
