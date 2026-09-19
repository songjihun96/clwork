"""전화 사업자 어댑터 고르기.

바깥에서는 get_provider() 하나만 부른다. 어떤 구현체가 붙어 있는지는
여기서만 안다. 사업자를 바꿀 때 고칠 곳을 한 군데로 묶어두기 위해서다.

  .env
    PHONE_PROVIDER=mock     (기본) 실제 전화 없이 전 과정을 돌린다
    PHONE_PROVIDER=clawops  ClawOps 070 회선. 키가 비면 기동 때 막힌다.
    PHONE_PROVIDER=sip      그 밖의 SIP 사업자용 골격
"""

from __future__ import annotations

import os
import threading
from typing import Dict, Optional

from .base import (
    CallDirection,
    CallEvent,
    CallEventType,
    CallSnapshot,
    NullRecordingProvider,
    PhoneProvider,
    RecordingProvider,
)
from .clawops import ClawOpsProvider
from .mock import MockPhoneProvider
from .sip import SipPhoneProvider

PROVIDERS = {
    "mock": MockPhoneProvider,
    "clawops": ClawOpsProvider,   # 070 회선(팀러너스). VoiceML 웹훅 방식
    "sip": SipPhoneProvider,      # 일반 SIP 사업자용 골격
}

_lock = threading.Lock()
_provider: Optional[PhoneProvider] = None
_recorder: Optional[RecordingProvider] = None


def provider_name() -> str:
    return (os.getenv("PHONE_PROVIDER", "mock") or "mock").strip().lower()


def get_provider(config: Optional[Dict] = None) -> PhoneProvider:
    """지금 쓰는 어댑터. 프로세스마다 하나만 만든다."""
    global _provider
    if _provider is not None:
        return _provider
    with _lock:
        if _provider is None:
            name = provider_name()
            cls = PROVIDERS.get(name)
            if cls is None:
                raise RuntimeError(
                    f"모르는 PHONE_PROVIDER: {name}. "
                    f"쓸 수 있는 값: {', '.join(PROVIDERS)}"
                )
            inst = cls()
            inst.initialize(config or {})
            _provider = inst
    return _provider


def reset_provider() -> None:
    """테스트에서 어댑터를 갈아끼울 때만 쓴다."""
    global _provider
    with _lock:
        _provider = None


def get_recorder() -> RecordingProvider:
    """녹취 어댑터. 기본은 녹취하지 않음.

    실제 녹취를 켜기 전에 통화녹음 고지 의무와 보관·파기 기준을 따로
    검토해야 한다. 그래서 환경변수 하나로 켜지지 않게 두었다.
    """
    global _recorder
    if _recorder is None:
        _recorder = NullRecordingProvider()
    return _recorder


__all__ = [
    "CallDirection",
    "ClawOpsProvider",
    "CallEvent",
    "CallEventType",
    "CallSnapshot",
    "PhoneProvider",
    "RecordingProvider",
    "get_provider",
    "get_recorder",
    "provider_name",
    "reset_provider",
    "PROVIDERS",
]
