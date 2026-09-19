"""관리자가 바꿀 수 있는 상담 상태·우선순위.

무엇을 바꿀 수 있고, 무엇은 못 바꾸는가
---------------------------------------
**코드값(NEW, COMPLETED …)은 고정이다.** 엔진과 통계가 이 값을 보고 판단하기
때문이다. 관리자가 상태를 마음대로 새로 만들 수 있게 하면, 그 상태를 모르는
코드가 그 상담을 세지 못하거나 영영 닫히지 않는 상담이 생긴다.

**바꿀 수 있는 것은 세 가지다.**

  이름(label)     화면에 뭐라고 보일지. "접수" 를 "1차 확인" 이라 부르고 싶을 때.
  사용 여부       드롭다운에 띄울지. 안 쓰는 상태를 감춰 실수를 줄인다.
  미처리 포함     그 상태를 '아직 손이 더 가야 하는 건'으로 셀지.
                  HOLD(보류)를 미처리로 볼지 말지는 조직마다 다르다.

이미 그 상태로 저장된 상담은 감춰도 그대로 남는다. 문의 유형과 같은 원칙이다.
지우는 게 아니라 가리는 것이다.

저장은 settings 표에 JSON 한 줄로 한다. 행이 열 몇 개뿐이라 표를 따로 만들
값어치가 없고, 코드값이 고정이라 관계형으로 풀 것도 없다.
"""

from __future__ import annotations

import json
from typing import Dict, List, Tuple

from sqlalchemy.orm import Session

from ..models import (
    CONSULTATION_PRIORITIES,
    CONSULTATION_STATUSES,
    Setting,
)

SETTING_STATUS = "cs_consultation_status_config"
SETTING_PRIORITY = "cs_consultation_priority_config"

# 기본 이름과 기본 성질. 관리자가 아무것도 손대지 않았을 때 쓰인다.
#   code: (기본 이름, 기본 사용 여부, 기본 미처리 포함)
DEFAULT_STATUS: Dict[str, Tuple[str, bool, bool]] = {
    "NEW": ("신규", True, True),
    "RECEIVED": ("접수", True, True),
    "IN_PROGRESS": ("진행중", True, True),
    "WAITING": ("대기", True, True),
    "PROCESSING": ("처리중", True, True),
    "COMPLETED": ("완료", True, False),
    "HOLD": ("보류", True, True),
}

DEFAULT_PRIORITY: Dict[str, Tuple[str, bool]] = {
    "LOW": ("낮음", True),
    "NORMAL": ("보통", True),
    "HIGH": ("높음", True),
    "URGENT": ("긴급", True),
}

# 완료는 언제나 '처리된 것'이다. 이걸 미처리로 돌릴 수 있게 하면 끝난 상담이
# 영원히 대기 목록에 남는다.
FORCED_CLOSED = ("COMPLETED",)

# 최소한 하나는 드롭다운에 남아 있어야 한다. 전부 감추면 상담을 저장할 수 없다.
ALWAYS_ACTIVE_STATUS = ("RECEIVED", "COMPLETED")
ALWAYS_ACTIVE_PRIORITY = ("NORMAL",)


def _load(db: Session, key: str) -> dict:
    row = db.get(Setting, key)
    if row is None or not row.value:
        return {}
    try:
        data = json.loads(row.value)
        return data if isinstance(data, dict) else {}
    except ValueError:
        # 설정이 깨졌다고 상담 화면 전체가 죽으면 안 된다. 기본값으로 돈다.
        return {}


def _save(db: Session, key: str, data: dict) -> None:
    row = db.get(Setting, key)
    text = json.dumps(data, ensure_ascii=False)
    if row is None:
        db.add(Setting(key=key, value=text))
    else:
        row.value = text
    db.commit()


def status_options(db: Session) -> List[dict]:
    """상태 목록. 순서는 코드에 박힌 순서 그대로 — 업무 흐름의 순서이기 때문이다."""
    saved = _load(db, SETTING_STATUS)
    out = []
    for code in CONSULTATION_STATUSES:
        label, active, is_open = DEFAULT_STATUS.get(code, (code, True, True))
        row = saved.get(code) or {}
        out.append({
            "code": code,
            "label": (row.get("label") or label).strip() or label,
            "is_active": bool(row.get("is_active", active)) or code in ALWAYS_ACTIVE_STATUS,
            "is_open": False if code in FORCED_CLOSED else bool(row.get("is_open", is_open)),
            "locked": code in FORCED_CLOSED or code in ALWAYS_ACTIVE_STATUS,
        })
    return out


def priority_options(db: Session) -> List[dict]:
    saved = _load(db, SETTING_PRIORITY)
    out = []
    for code in CONSULTATION_PRIORITIES:
        label, active = DEFAULT_PRIORITY.get(code, (code, True))
        row = saved.get(code) or {}
        out.append({
            "code": code,
            "label": (row.get("label") or label).strip() or label,
            "is_active": bool(row.get("is_active", active)) or code in ALWAYS_ACTIVE_PRIORITY,
            "locked": code in ALWAYS_ACTIVE_PRIORITY,
        })
    return out


def open_statuses(db: Session) -> tuple:
    """'미처리'로 셀 상태들. 대시보드·통계·목록 필터가 모두 이걸 쓴다.

    관리자가 전부 꺼버려도 최소한 NEW 는 남긴다. 미처리가 언제나 0 이면
    아무도 그 숫자를 보지 않게 된다.
    """
    codes = tuple(o["code"] for o in status_options(db) if o["is_open"])
    return codes or ("NEW",)


def save_status_options(db: Session, items: List[dict]) -> List[dict]:
    saved = _load(db, SETTING_STATUS)
    known = set(CONSULTATION_STATUSES)
    for item in items:
        code = str(item.get("code", "")).strip()
        if code not in known:
            continue  # 모르는 코드는 조용히 버린다. 만들 수 있는 값이 아니다.
        entry = saved.get(code, {})
        if item.get("label") is not None:
            entry["label"] = str(item["label"]).strip()[:20]
        if item.get("is_active") is not None:
            entry["is_active"] = bool(item["is_active"])
        if item.get("is_open") is not None and code not in FORCED_CLOSED:
            entry["is_open"] = bool(item["is_open"])
        saved[code] = entry
    _save(db, SETTING_STATUS, saved)
    return status_options(db)


def save_priority_options(db: Session, items: List[dict]) -> List[dict]:
    saved = _load(db, SETTING_PRIORITY)
    known = set(CONSULTATION_PRIORITIES)
    for item in items:
        code = str(item.get("code", "")).strip()
        if code not in known:
            continue
        entry = saved.get(code, {})
        if item.get("label") is not None:
            entry["label"] = str(item["label"]).strip()[:20]
        if item.get("is_active") is not None:
            entry["is_active"] = bool(item["is_active"])
        saved[code] = entry
    _save(db, SETTING_PRIORITY, saved)
    return priority_options(db)
