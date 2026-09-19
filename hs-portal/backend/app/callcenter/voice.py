"""전화망이 우리에게 물어보는 자리 — VoiceML 웹훅.

ClawOps 같은 사업자는 명령을 받지 않는다. **전화가 올 때마다 우리에게 물어보고,
우리가 XML 로 답한 대로 움직인다.** 그래서 순차분배가 이렇게 돈다.

    ① 전화 도착
       ClawOps → POST /api/cs/phone/voice/incoming
       우리    → <Dial timeout="20" action="…/after-dial"><Number>김상담</Number></Dial>

    ② 20초 무응답 (ClawOps 가 시간을 센다)
       ClawOps → POST …/after-dial  (DialCallStatus=no-answer)
       우리    → 엔진에게 다음 사람을 묻고 <Dial>…이상담…</Dial>

    ③ 아무도 못 받음
       우리    → <Say>잠시만 기다려주세요</Say><Pause/><Redirect>…/queue</Redirect>
       대기열에서 10초마다 다시 물어본다.

    ④ 받음
       ClawOps → POST …/after-dial  (DialCallStatus=completed)
       우리    → <Hangup/>  (통화가 이미 끝난 뒤에 오는 콜백이다)

**20초를 세는 일은 사업자가 하고, 누구를 부를지는 우리가 정한다.**
그래서 Provider 가 external_ring_timeout 을 알리면 엔진은 ring_deadline 을
비워 둔다. 안 그러면 배경 ticker 와 사업자가 같은 통화를 두 번 넘긴다.

이 파일은 XML 을 만들 뿐, 누구를 부를지는 한 줄도 정하지 않는다. 그건 engine 의 몫이다.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Optional
from xml.sax.saxutils import escape

from fastapi import APIRouter, Request, Response
from sqlalchemy.orm import Session

from .. import phone as phone_pkg
from ..database import SessionLocal
from ..models import CsCallLog, CsCallSession, CsCounselorProfile, Setting, User
from . import audio, engine
from .phones import normalize_phone

log = logging.getLogger("callcenter.voice")

router = APIRouter(prefix="/api/cs/phone/voice", tags=["cs-phone-voice"])

# 연결 방식 설정은 엔진에 있다. 예전 이름으로 부르는 곳이 있어 그대로 내보낸다.
SETTING_DIAL_MODE = engine.SETTING_DIAL_MODE

QUEUE_WAIT_SECONDS = 10   # 대기열에서 다시 물어보기까지
MAX_QUEUE_ROUNDS = 18     # 10초 x 18 = 3분. 그 뒤에는 안내하고 끊는다.


def _xml(body: str) -> Response:
    doc = f'<?xml version="1.0" encoding="UTF-8"?>\n<Response>{body}</Response>'
    return Response(content=doc, media_type="application/xml")


def _say(text: str) -> str:
    return f'<Say language="ko">{escape(text)}</Say>'


def _voice_base() -> str:
    """콜백 주소의 앞부분. 사업자가 우리를 다시 부를 때 쓴다."""
    return (os.getenv("PHONE_VOICE_BASE", "") or "").rstrip("/")


def _cb(path: str) -> str:
    return f"{_voice_base()}/api/cs/phone/voice/{path}"


def _dial_mode(db: Session) -> str:
    return engine.dial_mode(db)


async def _params(request: Request) -> dict:
    """ClawOps 는 form 으로 보내지만 JSON 으로 보내는 사업자도 있다. 둘 다 받는다."""
    ctype = (request.headers.get("content-type") or "").lower()
    if "json" in ctype:
        try:
            data = await request.json()
            return {str(k): str(v) for k, v in (data or {}).items()}
        except Exception:
            return {}
    form = await request.form()
    return {str(k): str(v) for k, v in form.items()}


def _verify(request: Request, params: dict) -> bool:
    """서명 검증. 이 문은 인증 없이 인터넷에 열려 있어 이게 유일한 방어선이다.

    개발 중에는 PHONE_WEBHOOK_INSECURE=1 로 끌 수 있게 해두되, 운영에서 켜두면
    아무나 가짜 전화를 밀어 넣을 수 있으므로 경고를 남긴다.
    """
    if (os.getenv("PHONE_WEBHOOK_INSECURE", "") or "").strip() == "1":
        log.warning("웹훅 서명 검증이 꺼져 있습니다. 운영에서는 반드시 켜세요.")
        return True

    try:
        provider = phone_pkg.get_provider()
    except Exception as exc:
        print(f"[전화] 어댑터가 없어 웹훅을 받지 못했습니다: {exc}", flush=True)
        return False

    verify = getattr(provider, "verify_signature", None)
    if verify is None:
        print(f"[전화] {provider.name} 어댑터에 서명 검증이 없습니다.", flush=True)
        return False

    signature = request.headers.get("x-signature", "") or request.headers.get("X-Signature", "")
    # 서명은 사업자 대시보드에 등록한 URL 문자열 그대로를 대상으로 계산된다.
    # 프록시를 지나며 스킴이 바뀌므로 우리가 아는 공개 주소로 다시 만든다.
    url = _voice_base() + request.url.path
    if verify(url, params, signature):
        return True

    # 서명이 안 맞으면 전화가 조용히 사라진다. 무엇이 어긋났는지 남겨야
    # 고칠 수 있다. 비밀키와 서명값 자체는 절대 남기지 않는다.
    print("[전화] 웹훅 서명 불일치 — 아래 두 주소가 완전히 같아야 합니다.", flush=True)
    print(f"[전화]   우리가 계산에 쓴 주소 : {url}", flush=True)
    print("[전화]   ClawOps 대시보드 Webhook URL 칸의 값과 대조하세요.", flush=True)
    print(f"[전화]   서명 헤더 {'있음' if signature else '없음'} · "
          f"PHONE_VOICE_BASE={_voice_base() or '(비어 있음)'} · "
          f"파라미터 {sorted(params.keys())}", flush=True)
    return False


# ══════════════════════════════════════════════════════════════
#  ① 전화 도착
# ══════════════════════════════════════════════════════════════


@router.post("/incoming")
async def incoming(request: Request):
    params = await _params(request)
    # 전화가 우리까지 닿았다는 것부터 남긴다. gunicorn 은 접속 로그를 끄고
    # 돌기 때문에, 이 한 줄이 없으면 전화가 왔는지조차 알 수 없다.
    print(f"[전화] 인바운드 웹훅 도착 CallId={params.get('CallId', '?')}", flush=True)
    if not _verify(request, params):
        return Response(content="signature", status_code=401)

    from_number = params.get("From") or params.get("Caller") or ""
    to_number = params.get("To") or ""
    external_id = params.get("CallId") or params.get("CallSid") or ""

    db = SessionLocal()
    try:
        existing = db.query(CsCallLog).filter(
            CsCallLog.external_call_id == external_id).first() if external_id else None
        if existing is None:
            call = engine.start_inbound_call(
                db, from_number=from_number, to_number=to_number,
                external_call_id=external_id,
                provider_name=phone_pkg.get_provider().name,
            )
        else:
            call = existing
        return _next_step(db, call)
    except Exception as exc:
        # 여기서 예외가 나면 고객은 아무 소리도 못 듣고 끊긴다. 최소한 안내는 한다.
        log.exception("인바운드 처리 실패: %s", exc)
        return _xml(_say("지금은 연결이 어렵습니다. 잠시 후 다시 걸어주세요.") + "<Hangup/>")
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════
#  ② <Dial> 이 끝났다 — 받았거나, 안 받았거나
# ══════════════════════════════════════════════════════════════


@router.post("/after-dial")
async def after_dial(request: Request):
    params = await _params(request)
    if not _verify(request, params):
        return Response(content="signature", status_code=401)

    external_id = params.get("CallId") or params.get("CallSid") or ""
    status = (params.get("DialCallStatus") or "").lower()

    db = SessionLocal()
    try:
        call = db.query(CsCallLog).filter(
            CsCallLog.external_call_id == external_id).first()
        if call is None:
            return _xml("<Hangup/>")

        session = db.query(CsCallSession).filter(
            CsCallSession.call_log_id == call.id).first()

        if status == "completed":
            # 상담원이 받았고, 통화까지 끝난 뒤에 오는 콜백이다.
            engine.hangup_call(db, call.id)
            return _xml("<Hangup/>")

        # busy / no-answer / failed / canceled → 다음 사람에게 넘긴다.
        counselor = db.get(User, session.current_counselor_id) if (
            session and session.current_counselor_id) else None
        if counselor is not None:
            engine.emit_event(db, "CALL_MISSED", call, target_user_id=counselor.id,
                              extra={"reason": status or "무응답", "step_only": True})
        if session is not None:
            engine.advance(db, call, session)
        db.refresh(call)
        return _next_step(db, call)
    except Exception as exc:
        log.exception("after-dial 처리 실패: %s", exc)
        return _xml(_say("연결에 문제가 있었습니다. 잠시 후 다시 걸어주세요.") + "<Hangup/>")
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════
#  ③ 대기열 — 10초마다 다시 물어본다
# ══════════════════════════════════════════════════════════════


@router.post("/queue")
async def queue(request: Request):
    params = await _params(request)
    if not _verify(request, params):
        return Response(content="signature", status_code=401)

    external_id = params.get("CallId") or params.get("CallSid") or ""
    try:
        rounds = int(params.get("round") or request.query_params.get("round") or 0)
    except ValueError:
        rounds = 0

    db = SessionLocal()
    try:
        call = db.query(CsCallLog).filter(
            CsCallLog.external_call_id == external_id).first()
        if call is None or call.status in ("COMPLETED", "MISSED", "REJECTED", "FAILED"):
            return _xml("<Hangup/>")

        session = db.query(CsCallSession).filter(
            CsCallSession.call_log_id == call.id).first()
        if session is not None and session.state == "QUEUED":
            # 그 사이 누가 상담 가능이 됐을 수 있다. 다시 한 바퀴 돌려본다.
            session.tried_ids = ""
            db.commit()
            engine.advance(db, call, session)
            db.refresh(session)

        if session is not None and session.state == "RINGING":
            return _next_step(db, call)

        if rounds >= MAX_QUEUE_ROUNDS:
            engine.hangup_call(db, call.id)
            return _xml(
                _say("죄송합니다. 지금은 상담원 연결이 어렵습니다. "
                     "잠시 후 다시 걸어주시면 감사하겠습니다.") + "<Hangup/>"
            )

        return _xml(
            _say("상담원을 연결하고 있습니다. 잠시만 기다려 주세요.")
            + f'<Pause length="{QUEUE_WAIT_SECONDS}"/>'
            + f"<Redirect>{escape(_cb('queue') + f'?round={rounds + 1}')}</Redirect>"
        )
    except Exception as exc:
        log.exception("queue 처리 실패: %s", exc)
        return _xml("<Hangup/>")
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════
#  ④ 발신 통화에서 상대가 받았다
# ══════════════════════════════════════════════════════════════


@router.post("/outbound")
async def outbound(request: Request):
    params = await _params(request)
    if not _verify(request, params):
        return Response(content="signature", status_code=401)

    external_id = params.get("CallId") or params.get("CallSid") or ""
    print(f"[전화] 발신 응답 웹훅 도착 CallId={external_id}", flush=True)

    db = SessionLocal()
    try:
        call = db.query(CsCallLog).filter(
            CsCallLog.external_call_id == external_id).first()

        if call is None:
            # 발신을 걸 때 사업자 응답에서 통화 ID 를 못 잡았을 수 있다.
            # 그렇다고 전화를 끊으면, 상대가 받자마자 끊기는 것으로 보인다.
            # 방금 이 번호로 건 통화를 찾아 여기서 이어 붙인다.
            to_number = normalize_phone(params.get("To") or "")
            q = db.query(CsCallLog).filter(
                CsCallLog.direction == "OUTBOUND",
                CsCallLog.status == "RINGING",
                CsCallLog.started_at >= datetime.utcnow() - timedelta(minutes=3),
            )
            if to_number:
                q = q.filter(CsCallLog.phone_number == to_number)
            call = q.order_by(CsCallLog.started_at.desc()).first()
            if call is not None:
                call.external_call_id = external_id
                db.commit()
                print(f"[전화] 발신 통화를 뒤늦게 이어 붙였습니다 call={call.id}", flush=True)

        if call is None:
            print(f"[전화] 모르는 발신 통화입니다 CallId={external_id}", flush=True)
            return _xml("<Hangup/>")
        engine.mark_answered(db, call)

        mode = _dial_mode(db)
        if mode == "stream":
            # 음성 중계 모드에서는 상담원이 이미 브라우저 앞에 있다.
            # 휴대폰으로 다시 걸 이유가 없고, 걸 번호도 없다.
            # 상담원 브라우저는 이 통화가 ANSWERED 가 되는 것을 보고 붙는다.
            url = (_voice_base().replace("https://", "wss://").replace("http://", "ws://")
                   + f"/api/cs/phone/voice/stream/{call.id}"
                   + f"?t={audio.stream_token(call.id)}")
            print(f"[전화] 발신 음성 중계로 연결 call={call.id}", flush=True)
            return _xml(
                f'<Connect action="{escape(_cb("after-stream"))}">'
                f'<Stream url="{escape(url)}" track="inbound"/>'
                f"</Connect>"
            )

        # 휴대폰·SIP 방식이면 이 통화를 건 상담원에게 연결한다.
        counselor = db.get(User, call.counselor_id) if call.counselor_id else None
        target = _agent_endpoint(db, counselor)
        if target is None:
            # 여기서 끊기면 "받자마자 끊긴다"로 보인다. 이유를 남겨야 찾는다.
            print(
                f"[전화] 발신을 이을 상담원 연락처가 없습니다 "
                f"call={call.id} 상담원={counselor.id if counselor else '?'} 방식={mode}. "
                f"전화 설정에서 휴대폰 번호를 채우거나 음성 중계 모드로 바꾸세요.",
                flush=True,
            )
            return _xml(_say("연결할 상담원을 찾지 못했습니다.") + "<Hangup/>")
        return _xml(f'<Dial timeout="30" action="{escape(_cb("after-dial"))}">{target}</Dial>')
    finally:
        db.close()


@router.post("/after-stream")
async def after_stream(request: Request):
    """음성 중계가 끝났다. 통화를 정리한다."""
    params = await _params(request)
    if not _verify(request, params):
        return Response(content="signature", status_code=401)

    external_id = params.get("CallId") or params.get("CallSid") or ""
    db = SessionLocal()
    try:
        call = db.query(CsCallLog).filter(
            CsCallLog.external_call_id == external_id).first()
        if call is not None and call.status not in ("COMPLETED", "MISSED"):
            engine.hangup_call(db, call.id)
    finally:
        db.close()
    return _xml("<Hangup/>")


# ══════════════════════════════════════════════════════════════
#  다음에 할 일을 XML 로
# ══════════════════════════════════════════════════════════════


def _agent_endpoint(db: Session, counselor: Optional[User]) -> Optional[str]:
    """상담원을 부를 <Dial> 안쪽 태그를 만든다.

    number 모드는 상담원 휴대폰으로 건다. 사업자의 SIP 부가서비스 없이도
    오늘 당장 동작한다. 대신 상담원 화면이 아니라 휴대폰으로 통화한다.
    고객 정보와 상담 기록은 그대로 화면에서 본다.
    """
    if counselor is None:
        return None
    profile = db.get(CsCounselorProfile, counselor.id)
    if profile is None:
        return None

    mode = _dial_mode(db)
    if mode == "sip":
        # 브라우저가 등록하며 받은 임시 주소를 쓴다. 상담원이 적어 넣는 값이
        # 아니라 서버가 토큰을 발급할 때마다 덮어쓰는 값이다.
        uri = (profile.sip_uri or "").strip()
        fresh = bool(
            uri and profile.sip_uri_expires_at
            and profile.sip_uri_expires_at > datetime.utcnow()
        )
        if not fresh:
            # 만료된 주소로 돌리면 아무 데도 울리지 않고 20초를 버린다.
            # 고정 내선이 적혀 있으면 그걸로 대신한다(IP전화기 등).
            fallback = (profile.extension or "").strip()
            if not fallback:
                return None
            uri = fallback if fallback.startswith("sip:") else f"sip:{fallback}"
        return f"<Sip>{escape(uri)}</Sip>"

    number = normalize_phone(profile.phone_number or "")
    if not number:
        return None
    return f"<Number>{escape(number)}</Number>"


def _next_step(db: Session, call: CsCallLog) -> Response:
    """지금 이 통화를 어떻게 할지 엔진의 판단을 XML 로 옮긴다."""
    session = db.query(CsCallSession).filter(
        CsCallSession.call_log_id == call.id).first()

    if session is None or session.state == "ENDED" or call.status == "MISSED":
        return _xml(
            _say("죄송합니다. 지금은 상담원 연결이 어렵습니다. "
                 "잠시 후 다시 걸어주시면 감사하겠습니다.") + "<Hangup/>"
        )

    if session.state == "QUEUED":
        return _xml(
            _say("상담원을 연결하고 있습니다. 잠시만 기다려 주세요.")
            + f'<Pause length="{QUEUE_WAIT_SECONDS}"/>'
            + f"<Redirect>{escape(_cb('queue') + '?round=1')}</Redirect>"
        )

    if _dial_mode(db) == "stream":
        # 음성을 우리 서버로 직접 받아 브라우저로 중계한다.
        # <Dial> 이 아니므로 사업자가 20초를 세주지 않는다. 그 일은 우리
        # 배경 ticker 가 한다(engine.external_ring_timer 참고).
        # 이 응답은 통화당 한 번만 하면 되고, 다음 상담원으로 넘기는 일은
        # 오디오 다리를 유지한 채 화면에서 이뤄진다.
        url = (_voice_base().replace("https://", "wss://").replace("http://", "ws://")
               + f"/api/cs/phone/voice/stream/{call.id}"
               + f"?t={audio.stream_token(call.id)}")
        return _xml(
            f'<Connect action="{escape(_cb("after-stream"))}">'
            f'<Stream url="{escape(url)}" track="inbound"/>'
            f"</Connect>"
        )

    counselor = db.get(User, session.current_counselor_id) if session.current_counselor_id else None
    target = _agent_endpoint(db, counselor)
    if target is None:
        # 부를 사람은 정해졌는데 연락처가 비어 있다. 그 사람을 건너뛴다.
        # 여기서 멈추면 전화가 그대로 죽는다.
        log.warning("상담원 %s 의 연결 정보가 없습니다. 건너뜁니다.",
                    counselor.id if counselor else "?")
        engine.advance(db, call, session)
        db.refresh(session)
        counselor = db.get(User, session.current_counselor_id) if session.current_counselor_id else None
        target = _agent_endpoint(db, counselor)
        if target is None:
            return _xml(
                _say("죄송합니다. 지금은 상담원 연결이 어렵습니다.") + "<Hangup/>"
            )

    timeout = engine.get_ring_timeout(db)
    return _xml(
        f'<Dial timeout="{timeout}" action="{escape(_cb("after-dial"))}">{target}</Dial>'
    )
