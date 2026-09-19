"""순차분배 엔진. 이 파일이 사실상 콜센터의 심장이다.

무엇을, 왜 DB 에 두는가
------------------------
운영은 ``gunicorn --workers 3`` 이다(deploy/udt-backend.service). 전화가
울리는 동안의 상태(누구를 부르고 있는지, 언제 타임아웃되는지)를 파이썬
프로세스 메모리에 두면, 웹훅을 받은 워커와 상담원의 WebSocket 이 붙어 있는
워커가 다를 수 있어 화면에 전화가 뜨지 않는다.

그래서 진행 상태는 ``cs_call_sessions`` 테이블에, 화면으로 내보낼 사건은
``cs_call_events`` 아웃박스 테이블에 쓴다. 타임아웃을 넘기는 배경 작업은
워커마다 따로 돌아도 되는데, ``ring_step`` 을 조건으로 건 UPDATE 로
넘기기 때문에(낙관적 잠금) 세 워커가 동시에 깨어도 딱 한 번만 다음
상담원에게 넘어간다. Redis 없이도 정확하다. 대가는 최대 1초 남짓의 지연뿐이다.

흐름
----
전화 도착
  -> CsCallLog(RINGING) + CsCallSession(ring_step=0) 생성
  -> _advance() : 순서대로 다음 AVAILABLE 상담원을 찾아 벨을 울린다
     -> 없으면 QUEUED
상담원이 20초(설정값) 안에 응답 없음
  -> 배경 ticker 가 ring_step 을 낙관적으로 올리며 _advance() 를 다시 부른다
상담원이 받음/거절함
  -> answer()/reject() 가 직접 _advance() 를 부른다(타임아웃을 기다리지 않는다)
큐에서 기다리는 동안 누군가 AVAILABLE 이 됨
  -> set_availability() 가 큐를 다시 훑는다
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from .. import phone as phone_pkg
from ..models import (
    AVAILABILITY_STATUSES,
    CsCallEvent,
    CsCallLog,
    CsCallSession,
    CsCounselorProfile,
    CsCustomer,
    Role,
    Setting,
    User,
)
from .phones import normalize_phone

log = logging.getLogger("callcenter")

DEFAULT_RING_TIMEOUT = 20
SETTING_RING_TIMEOUT = "cs_phone_ring_timeout_seconds"
# 상담원을 무엇으로 부를지.
#   number : 상담원 휴대폰으로 건다. 사업자 부가서비스가 필요 없다.
#   sip    : 상담원 PC 로 SIP/WebRTC 연결. SIP 트렁크 부가서비스가 필요하다.
#   stream : 통화 음성을 우리 서버로 받아 브라우저로 중계한다. 부가서비스 없이
#            PC 로 받을 수 있지만, 대신 20초를 세는 일도 우리가 해야 한다.
SETTING_DIAL_MODE = "cs_phone_agent_dial_mode"
DIAL_MODES = ("number", "sip", "stream")
SETTING_SEQUENTIAL = "cs_phone_sequential_enabled"
SETTING_QUEUE = "cs_phone_queue_enabled"


# ── 설정 ────────────────────────────────────────────────────────


def _get_setting(db: Session, key: str, default: str) -> str:
    row = db.get(Setting, key)
    return row.value if row and row.value is not None else default


def get_ring_timeout(db: Session) -> int:
    try:
        return max(3, int(_get_setting(db, SETTING_RING_TIMEOUT, str(DEFAULT_RING_TIMEOUT))))
    except (TypeError, ValueError):
        return DEFAULT_RING_TIMEOUT


def sequential_enabled(db: Session) -> bool:
    return _get_setting(db, SETTING_SEQUENTIAL, "true").lower() != "false"


def queue_enabled(db: Session) -> bool:
    return _get_setting(db, SETTING_QUEUE, "true").lower() != "false"


def dial_mode(db: Session) -> str:
    value = _get_setting(db, SETTING_DIAL_MODE, "number")
    return value if value in DIAL_MODES else "number"


def external_ring_timer(db: Session, provider) -> bool:
    """20초를 세는 일을 사업자가 하는가, 우리가 하는가.

    <Dial timeout="20"> 을 쓰는 방식(number·sip)에서는 사업자가 센다. 우리
    ticker 까지 같이 세면 한 번 안 받았는데 두 사람을 건너뛴다.

    반면 stream 방식은 전화가 오자마자 음성이 붙어버려서 <Dial> 자체가 없다.
    그때는 우리가 세지 않으면 아무도 안 넘어간다.
    """
    if dial_mode(db) == "stream":
        return False
    try:
        return bool(provider.capabilities().get("external_ring_timeout"))
    except Exception:
        return False


# ── 이벤트 내보내기 ───────────────────────────────────────────


def emit_event(db: Session, event_type: str, call: Optional[CsCallLog] = None,
                target_user_id: Optional[int] = None, extra: Optional[dict] = None) -> None:
    """화면으로 나갈 사건을 아웃박스에 적는다. WebSocket 은 이걸 폴링한다."""
    payload = dict(extra or {})
    if call is not None:
        payload.setdefault("call_id", call.id)
        payload.setdefault("phone_number", call.phone_number)
        payload.setdefault("status", call.status)
        payload.setdefault("direction", call.direction)
    db.add(
        CsCallEvent(
            type=event_type,
            call_log_id=call.id if call else None,
            target_user_id=target_user_id,
            payload=json.dumps(payload, ensure_ascii=False, default=str),
        )
    )
    db.commit()


# ── 상담원 순서 ───────────────────────────────────────────────


def ring_order_list(db: Session) -> List[CsCounselorProfile]:
    """전화를 받을 수 있는 상담원을, 관리자가 정한 순서대로.

    admin 은 승인 업무 때문에 계정은 있지만 통화 큐에는 원칙적으로 넣지
    않는다(accepts_calls 로 상담원마다 정한다). 계정 자체는 users 를 쓰므로
    비활성 계정은 자동으로 빠진다.
    """
    rows = (
        db.query(CsCounselorProfile)
        .join(User, User.id == CsCounselorProfile.user_id)
        .filter(
            CsCounselorProfile.accepts_calls.is_(True),
            User.is_active.is_(True),
            User.role.in_([Role.cs, Role.admin]),
        )
        .order_by(CsCounselorProfile.ring_order.asc(), CsCounselorProfile.user_id.asc())
        .all()
    )
    return rows


def ensure_profile(db: Session, user: User) -> CsCounselorProfile:
    """상담원 프로필이 없으면 만든다. 기존 users 에 없는 컬럼이라 지연 생성한다."""
    profile = db.get(CsCounselorProfile, user.id)
    if profile is None:
        # 새 상담원은 맨 뒤로. 관리자가 나중에 순서를 조정한다.
        max_order = db.query(CsCounselorProfile.ring_order).order_by(
            CsCounselorProfile.ring_order.desc()
        ).first()
        next_order = (max_order[0] + 10) if max_order else 10
        profile = CsCounselorProfile(user_id=user.id, ring_order=next_order)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def set_availability(db: Session, user: User, status: str) -> CsCounselorProfile:
    if status not in AVAILABILITY_STATUSES:
        raise ValueError(f"모르는 상태: {status}")
    profile = ensure_profile(db, user)
    profile.availability_status = status
    profile.last_status_at = datetime.utcnow()
    db.commit()
    emit_event(db, "COUNSELOR_STATUS_CHANGED", extra={
        "counselor_id": user.id, "name": user.name, "status": status,
    })
    if status == "AVAILABLE":
        # 대기열에 기다리는 콜이 있으면 지금 바로 이어준다.
        _drain_queue(db)
    return profile


# ── 콜 진입 ──────────────────────────────────────────────────


def find_customer_id(db: Session, phone: str) -> Optional[int]:
    """번호로 고객을 찾는다. 없으면 None(신규 고객).

    통화 기록을 만들 때 바로 이어둔다. 나중에 잇겠다고 미루면, 통화 중에
    고객을 등록하지 않고 끊은 경우 그 통화가 어느 고객 이력에도 남지 않는다.
    """
    normalized = normalize_phone(phone)
    if not normalized:
        return None
    row = db.query(CsCustomer).filter(CsCustomer.phone_number == normalized).first()
    return row.id if row else None


def start_inbound_call(db: Session, from_number: str, to_number: str = "",
                        external_call_id: str = "", provider_name: str = "mock") -> CsCallLog:
    """전화가 도착했다. 기록을 만들고 첫 상담원에게 벨을 울린다."""
    call = CsCallLog(
        provider=provider_name,
        external_call_id=external_call_id,
        phone_number=normalize_phone(from_number),
        customer_id=find_customer_id(db, from_number),
        direction="INBOUND",
        status="RINGING",
        started_at=datetime.utcnow(),
    )
    db.add(call)
    db.commit()
    db.refresh(call)

    session = CsCallSession(call_log_id=call.id, state="RINGING", ring_step=0, tried_ids="")
    db.add(session)
    db.commit()
    db.refresh(session)

    emit_event(db, "INCOMING_CALL", call, extra={"from": call.phone_number})
    _advance(db, call, session)
    return call


# ── 순서 진행 ────────────────────────────────────────────────


def _tried_set(session: CsCallSession) -> set:
    return {int(x) for x in session.tried_ids.split(",") if x.strip().isdigit()}


def _advance(db: Session, call: CsCallLog, session: CsCallSession) -> None:
    """다음 순서로 넘긴다. 부를 사람이 없으면 큐로, 순차분배가 꺼져 있으면
    AVAILABLE 인 아무에게나 보낸다."""
    if session.state not in ("RINGING", "QUEUED"):
        return

    order = ring_order_list(db)
    if not order:
        _to_missed(db, call, session, reason="상담원이 없음")
        return

    tried = _tried_set(session)
    seq = sequential_enabled(db)

    # 지금 다른 전화 때문에 벨이 울리고 있는 사람은 빼야 한다. 상태값은 아직
    # AVAILABLE 이지만(받기 전이니까) 두 통을 동시에 울리면 어느 쪽을 받든
    # 다른 한 통은 반드시 놓친다.
    busy_ringing = {
        row.current_counselor_id
        for row in db.query(CsCallSession)
        .filter(
            CsCallSession.state == "RINGING",
            CsCallSession.id != session.id,
            CsCallSession.current_counselor_id.isnot(None),
        )
        .all()
    }

    candidates = [
        p for p in order
        if p.user_id not in tried
        and p.user_id not in busy_ringing
        and p.availability_status == "AVAILABLE"
    ]

    if not candidates:
        if queue_enabled(db):
            _to_queued(db, call, session)
        else:
            _to_missed(db, call, session, reason="응답 가능한 상담원 없음")
        return

    if seq:
        # 순차분배: 관리자가 정한 순서 그대로.
        target = candidates[0]
    else:
        # 순차분배를 끄면 가장 오래 쉬고 있던 상담원에게 보낸다.
        # 그래야 한 사람에게 전화가 몰리지 않는다.
        target = min(candidates, key=lambda p: p.last_status_at or datetime.min)

    provider = phone_pkg.get_provider()
    counselor = db.get(User, target.user_id)
    agent_key = target.extension or str(target.user_id)
    try:
        provider.ring_agent(call.external_call_id or f"call-{call.id}", agent_key)
    except Exception as exc:  # Provider 오류로 전체 분배가 멈추면 안 된다
        log.warning("ring_agent 실패(call=%s, agent=%s): %s", call.id, agent_key, exc)

    session.state = "RINGING"
    session.current_counselor_id = target.user_id
    session.ring_step += 1
    session.tried_ids = ",".join(str(i) for i in (tried | {target.user_id}))
    timeout = get_ring_timeout(db)
    # 사업자가 스스로 20초를 세는 방식(ClawOps 의 <Dial timeout>)이면 마감시각을
    # 비워 둔다. 두면 우리 배경 ticker 와 사업자가 같은 통화를 각각 넘겨서,
    # 한 번 안 받았는데 두 사람을 건너뛰는 일이 생긴다.
    external_timer = external_ring_timer(db, provider)
    session.ring_deadline = (
        None if external_timer else datetime.utcnow() + timedelta(seconds=timeout)
    )
    db.commit()

    emit_event(
        db, "CALL_RINGING", call,
        target_user_id=target.user_id,
        extra={"ring_timeout": timeout, "counselor_name": counselor.name if counselor else ""},
    )


def advance(db: Session, call: CsCallLog, session: CsCallSession) -> None:
    """다음 상담원으로 넘긴다.

    웹훅 방식 사업자(callcenter/voice.py)가 "이제 다음 사람"이라고 알릴 때
    부른다. 안에서 하는 일은 타임아웃으로 넘어갈 때와 똑같다.
    """
    _advance(db, call, session)


def _to_queued(db: Session, call: CsCallLog, session: CsCallSession) -> None:
    session.state = "QUEUED"
    session.current_counselor_id = None
    session.ring_deadline = None
    if session.queued_at is None:
        session.queued_at = datetime.utcnow()
    call.status = "QUEUED"
    db.commit()
    emit_event(db, "QUEUE_UPDATED", call, extra={"queued": True})


def _to_missed(db: Session, call: CsCallLog, session: CsCallSession, reason: str = "") -> None:
    call.status = "MISSED"
    call.ended_at = datetime.utcnow()
    if call.started_at:
        call.duration_seconds = int((call.ended_at - call.started_at).total_seconds())
    session.state = "ENDED"
    session.current_counselor_id = None
    session.ring_deadline = None
    db.commit()
    try:
        phone_pkg.get_provider().hangup_call(call.external_call_id or f"call-{call.id}")
    except Exception:
        pass
    emit_event(db, "CALL_MISSED", call, extra={"reason": reason})


def _drain_queue(db: Session) -> None:
    """대기열 중 가장 오래 기다린 콜부터 다시 시도한다."""
    sessions = (
        db.query(CsCallSession)
        .filter(CsCallSession.state == "QUEUED")
        .order_by(CsCallSession.queued_at.asc())
        .all()
    )
    for session in sessions:
        call = db.get(CsCallLog, session.call_log_id)
        if call is None or call.status not in ("RINGING", "QUEUED"):
            continue
        _advance(db, call, session)


# ── 상담원 조작 ──────────────────────────────────────────────


def answer_call(db: Session, call_id: int, counselor: User) -> CsCallLog:
    call = db.get(CsCallLog, call_id)
    if call is None:
        raise LookupError("통화를 찾을 수 없습니다.")
    session = db.query(CsCallSession).filter(CsCallSession.call_log_id == call_id).first()
    if session is None or session.state != "RINGING" or session.current_counselor_id != counselor.id:
        raise PermissionError("지금 이 상담원에게 온 전화가 아닙니다.")

    provider = phone_pkg.get_provider()
    provider.answer_call(call.external_call_id or f"call-{call.id}")

    call.status = "ANSWERED"
    call.counselor_id = counselor.id
    call.answered_at = datetime.utcnow()
    session.state = "ANSWERED"
    db.commit()

    set_availability(db, counselor, "BUSY")
    emit_event(db, "CALL_ANSWERED", call, extra={
        "counselor_id": counselor.id, "counselor_name": counselor.name,
    })
    return call


def reject_call(db: Session, call_id: int, counselor: User) -> CsCallLog:
    call = db.get(CsCallLog, call_id)
    if call is None:
        raise LookupError("통화를 찾을 수 없습니다.")
    session = db.query(CsCallSession).filter(CsCallSession.call_log_id == call_id).first()
    if session is None or session.current_counselor_id != counselor.id:
        raise PermissionError("지금 이 상담원에게 온 전화가 아닙니다.")

    provider = phone_pkg.get_provider()
    provider.reject_call(call.external_call_id or f"call-{call.id}", reason="상담원 거절")

    emit_event(db, "CALL_REJECTED", call, target_user_id=counselor.id)
    _advance(db, call, session)
    return call


def hangup_call(db: Session, call_id: int, actor: Optional[User] = None) -> CsCallLog:
    call = db.get(CsCallLog, call_id)
    if call is None:
        raise LookupError("통화를 찾을 수 없습니다.")
    session = db.query(CsCallSession).filter(CsCallSession.call_log_id == call_id).first()

    provider = phone_pkg.get_provider()
    try:
        provider.hangup_call(call.external_call_id or f"call-{call.id}")
    except Exception:
        pass

    was_answered = call.status == "ANSWERED"
    call.status = "COMPLETED" if was_answered else "MISSED"
    call.ended_at = datetime.utcnow()
    if call.started_at:
        call.duration_seconds = int((call.ended_at - call.started_at).total_seconds())
    if session is not None:
        session.state = "ENDED"
        session.current_counselor_id = None
        session.ring_deadline = None
    db.commit()

    if call.counselor_id:
        counselor = db.get(User, call.counselor_id)
        if counselor is not None:
            set_availability(db, counselor, "AVAILABLE")

    emit_event(db, "CALL_ENDED", call)
    return call


def make_outbound_call(db: Session, counselor: User, to_number: str) -> CsCallLog:
    """상담원이 고객에게 건다.

    발신에도 세션을 만든다. 세션이 없으면 /calls/active 에 뜨지 않아
    상담원이 자기가 건 전화를 화면에서 끊을 수 없다.

    다만 ring_deadline 은 비워 둔다. 배경 ticker 는 만료된 링만 넘기는데,
    발신 통화를 넘겼다가는 내가 건 전화가 옆자리 상담원에게 울린다.
    발신은 순차분배의 대상이 아니다.
    """
    provider = phone_pkg.get_provider()
    snap = provider.make_call(to_number)
    call = CsCallLog(
        provider=provider.name,
        external_call_id=snap.external_call_id,
        phone_number=normalize_phone(to_number),
        customer_id=find_customer_id(db, to_number),
        counselor_id=counselor.id,
        direction="OUTBOUND",
        status="RINGING",
        started_at=datetime.utcnow(),
    )
    db.add(call)
    db.commit()
    db.refresh(call)

    db.add(CsCallSession(
        call_log_id=call.id,
        state="RINGING",
        current_counselor_id=counselor.id,
        ring_step=1,
        ring_deadline=None,          # ticker 가 건드리지 않게 비워 둔다
        tried_ids=str(counselor.id),
    ))
    db.commit()

    set_availability(db, counselor, "BUSY")
    emit_event(db, "CALL_RINGING", call, target_user_id=counselor.id)
    return call


def mark_answered(db: Session, call: CsCallLog) -> CsCallLog:
    """상대가 받았다. 망에서 CALL_ANSWERED 가 올라왔을 때 부른다.

    수신 통화는 상담원이 [받기] 를 누르는 순간이 곧 응답이지만, 발신은
    상대가 받아야 응답이다. 그 시점을 여기서 한 곳으로 모은다.
    """
    if call.status == "ANSWERED":
        return call
    call.status = "ANSWERED"
    call.answered_at = datetime.utcnow()
    session = db.query(CsCallSession).filter(CsCallSession.call_log_id == call.id).first()
    if session is not None:
        session.state = "ANSWERED"
        session.ring_deadline = None
    db.commit()
    emit_event(db, "CALL_ANSWERED", call)
    return call


def transfer_call(db: Session, call_id: int, actor: User,
                  to_counselor_id: Optional[int] = None, to_number: str = "") -> CsCallLog:
    """통화 중인 전화를 다른 상담원(또는 외부 번호)에게 넘긴다.

    넘긴 사람은 곧바로 통화 가능 상태로 돌아간다. 넘겨받은 상담원이 제한
    시간 안에 받지 않으면 그 전화는 버려지지 않고 평소의 순차분배로 돌아가
    다음 사람을 찾는다. 넘기다가 사라지는 전화가 있으면 아무도 전환 기능을
    쓰지 않게 된다.
    """
    call = db.get(CsCallLog, call_id)
    if call is None:
        raise LookupError("통화를 찾을 수 없습니다.")
    if call.status != "ANSWERED":
        raise PermissionError("통화 중인 전화만 돌릴 수 있습니다.")
    if call.counselor_id != actor.id:
        raise PermissionError("내가 받고 있는 전화만 돌릴 수 있습니다.")

    session = db.query(CsCallSession).filter(CsCallSession.call_log_id == call.id).first()
    if session is None:
        raise LookupError("통화 상태를 찾을 수 없습니다.")

    provider = phone_pkg.get_provider()
    external = call.external_call_id or f"call-{call.id}"

    if to_counselor_id:
        target = db.get(User, to_counselor_id)
        if target is None or not target.is_active or target.role not in (Role.cs, Role.admin):
            raise ValueError("넘길 수 없는 상담원입니다.")
        if target.id == actor.id:
            raise ValueError("자기 자신에게는 돌릴 수 없습니다.")
        profile = ensure_profile(db, target)
        if profile.availability_status != "AVAILABLE":
            raise ValueError(f"{target.name} 님은 지금 받을 수 없는 상태입니다.")

        try:
            provider.transfer_call(external, profile.extension or str(target.id))
        except Exception as exc:
            log.warning("transfer_call 실패(call=%s): %s", call.id, exc)

        # 넘겨받는 사람에게 다시 벨을 울린다. 받기 전까지는 통화가 아니다.
        call.status = "RINGING"
        call.counselor_id = None
        call.answered_at = None
        session.state = "RINGING"
        session.current_counselor_id = target.id
        session.ring_step += 1
        # 넘긴 사람은 이 전화를 이미 받아봤으므로 다시 부르지 않는다.
        session.tried_ids = ",".join(str(i) for i in (_tried_set(session) | {actor.id, target.id}))
        session.ring_deadline = datetime.utcnow() + timedelta(seconds=get_ring_timeout(db))
        db.commit()

        emit_event(db, "CALL_RINGING", call, target_user_id=target.id,
                   extra={"transferred_from": actor.name})
        detail = target.name
    else:
        number = normalize_phone(to_number)
        if not number:
            raise ValueError("돌릴 번호가 올바르지 않습니다.")
        if not provider.capabilities().get("transfer"):
            raise ValueError("지금 전화 사업자는 통화 전환을 지원하지 않습니다.")
        if not provider.transfer_call(external, number):
            raise ValueError("통화를 돌리지 못했습니다.")
        # 외부로 넘어간 뒤에는 우리 쪽 통화가 끝난 것으로 본다.
        call.status = "COMPLETED"
        call.ended_at = datetime.utcnow()
        if call.started_at:
            call.duration_seconds = int((call.ended_at - call.started_at).total_seconds())
        session.state = "ENDED"
        session.current_counselor_id = None
        session.ring_deadline = None
        db.commit()
        emit_event(db, "CALL_ENDED", call, extra={"transferred_to_external": True})
        detail = number

    # 넘긴 사람은 바로 다음 전화를 받을 수 있어야 한다.
    set_availability(db, actor, "AVAILABLE")
    log.info("통화 전환 call=%s %s -> %s", call.id, actor.id, detail)
    return call


# ── 타임아웃 ticker ──────────────────────────────────────────


def tick_timeouts(db: Session) -> int:
    """만료된 링을 다음 상담원으로 넘긴다. 주기적으로(예: 1초) 호출한다.

    ring_step 을 조건에 걸어 낙관적으로 갱신한다. 워커 3개가 동시에 같은
    세션을 봐도, UPDATE 가 실제로 행에 반영되는 워커는 하나뿐이다.
    """
    now = datetime.utcnow()
    due = (
        db.query(CsCallSession)
        .filter(CsCallSession.state == "RINGING", CsCallSession.ring_deadline <= now)
        .all()
    )
    advanced = 0
    for session in due:
        current_step = session.ring_step
        result = (
            db.query(CsCallSession)
            .filter(
                CsCallSession.id == session.id,
                CsCallSession.ring_step == current_step,
                CsCallSession.state == "RINGING",
            )
            .update({"ring_deadline": None}, synchronize_session=False)
        )
        db.commit()
        if result == 0:
            continue  # 다른 워커가 이미 처리했다
        db.refresh(session)
        call = db.get(CsCallLog, session.call_log_id)
        if call is None:
            continue
        counselor = db.get(User, session.current_counselor_id) if session.current_counselor_id else None
        if counselor is not None:
            # 응답 못 한 상담원은 화면에서만 벨이 꺼지도록 알린다(상태는 그대로 둔다).
            emit_event(db, "CALL_MISSED", call, target_user_id=counselor.id, extra={
                "reason": "무응답", "step_only": True,
            })
        _advance(db, call, session)
        advanced += 1
    return advanced
