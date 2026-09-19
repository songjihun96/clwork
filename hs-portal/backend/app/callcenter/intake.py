"""전화가 아닌 경로로 들어온 상담을 받는 곳.

지금은 홈페이지 문의 하나다. 앞으로 이메일·카카오 같은 게 늘어도 여기로 모은다.

왜 상담을 따로 만드는가
-----------------------
홈페이지 문의(Inquiry)는 **학교가 답한다.** 상담원이 아니라 그 학교 계정이
답변을 쓰고 메일이 나간다. 그 흐름은 건드리지 않는다.

그런데 상담원 입장에서는 "오늘 우리한테 들어온 일"이 전화와 홈페이지로 갈라져
두 화면에 흩어져 있으면 안 된다. 놓치는 건은 늘 두 목록 사이에서 생긴다.
그래서 문의가 들어오면 **읽기 위한 상담 기록을 하나 더 만든다.**

  Inquiry        학교가 답변하는 원본. 기존 그대로.
  CsConsultation 상담원이 보는 사본. 채널 HOMEPAGE.

같은 문의로 상담이 두 개 생기지 않도록, 이미 만든 문의는 다시 만들지 않는다.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..models import CUSTOMER_TYPES, CsConsultation, CsCustomer
from .engine import emit_event
from .phones import normalize_phone

log = logging.getLogger("callcenter.intake")

# 원본 문의와 상담을 잇는 표식. subject 뒤에 붙이지 않고 content 앞에 둔다.
# 상담원이 눈으로도 어디서 온 건인지 알 수 있어야 하기 때문이다.
INQUIRY_TAG = "[홈페이지 문의 #%s]"


def find_or_create_customer(
    db: Session,
    phone: str = "",
    name: str = "",
    email: str = "",
    school_name: str = "",
    customer_type: str = "OTHER",
) -> Optional[CsCustomer]:
    """번호로 고객을 찾고, 없으면 만든다.

    번호가 없으면 고객을 만들지 않는다. 전화번호 없는 고객은 다음 전화 때
    찾을 수가 없어서, 명부만 지저분해지고 쓸모가 없다.
    """
    normalized = normalize_phone(phone)
    if not normalized:
        return None

    row = db.query(CsCustomer).filter(CsCustomer.phone_number == normalized).first()
    if row is not None:
        # 이미 있는 고객의 정보를 덮어쓰지 않는다. 상담원이 통화하며 고쳐 넣은
        # 값이 익명 문의 폼의 빈칸으로 지워지면 안 된다. 비어 있던 칸만 채운다.
        if not row.name and name:
            row.name = name.strip()[:60]
        if not row.email and email:
            row.email = email.strip()[:120]
        if not row.school_name and school_name:
            row.school_name = school_name.strip()[:120]
        db.commit()
        return row

    row = CsCustomer(
        name=(name or "").strip()[:60],
        phone_number=normalized,
        email=(email or "").strip()[:120],
        customer_type=customer_type if customer_type in CUSTOMER_TYPES else "OTHER",
        school_name=(school_name or "").strip()[:120],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def record_homepage_inquiry(
    db: Session,
    question: str,
    name: str = "",
    phone: str = "",
    email: str = "",
    school_name: str = "",
    subject: str = "",
    customer_type: str = "OTHER",
    inquiry_id: Optional[int] = None,
) -> Optional[CsConsultation]:
    """홈페이지 문의를 상담 목록에 올린다.

    실패해도 예외를 밖으로 내보내지 않는다. 이 기능이 고장 나서 방문자의
    문의 접수 자체가 실패하면, 얻는 것보다 잃는 것이 훨씬 크다.
    """
    try:
        if inquiry_id is not None:
            # 같은 문의로 두 번 만들지 않는다.
            tag = INQUIRY_TAG % inquiry_id
            exists = (
                db.query(CsConsultation)
                .filter(CsConsultation.channel == "HOMEPAGE",
                        CsConsultation.content.like(f"{tag}%"))
                .first()
            )
            if exists is not None:
                return exists

        customer = find_or_create_customer(
            db, phone=phone, name=name, email=email,
            school_name=school_name, customer_type=customer_type,
        )

        body = (question or "").strip()
        if inquiry_id is not None:
            body = f"{INQUIRY_TAG % inquiry_id}\n{body}"

        row = CsConsultation(
            customer_id=customer.id if customer else None,
            channel="HOMEPAGE",
            subject=(subject or "").strip()[:200] or "홈페이지 문의",
            content=body,
            status="NEW",
            priority="NORMAL",
            started_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        emit_event(db, "QUEUE_UPDATED", extra={
            "consultation_id": row.id, "channel": "HOMEPAGE",
            "subject": row.subject,
        })
        return row
    except Exception as exc:
        db.rollback()
        # 개인정보가 로그에 남지 않도록 내용은 적지 않는다.
        log.warning("홈페이지 문의를 상담으로 옮기지 못했습니다: %s", exc)
        return None
