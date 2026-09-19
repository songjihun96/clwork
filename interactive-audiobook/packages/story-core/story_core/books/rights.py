"""Content rights gate (docs/architecture.md R1, docs/database.md §3.2).

A book may be processed (sent to parsing, TTS, LLMs) and shown to readers only when this returns
no problems. The check runs in the API before enqueueing, again in the worker before processing,
and on every reader-facing query, so an expired licence hides the book immediately.
"""

import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

# Licence dates are contract dates, evaluated in the contract's time zone (not UTC): a licence ending on
# 2026-09-15 must stop at midnight KST, not at 09:00 KST the next day. Override with RIGHTS_TIMEZONE.
DEFAULT_RIGHTS_TIMEZONE = "Asia/Seoul"


def rights_today(now: datetime | None = None, timezone: str | None = None) -> date:
    zone = ZoneInfo(timezone or os.environ.get("RIGHTS_TIMEZONE") or DEFAULT_RIGHTS_TIMEZONE)
    return (now or datetime.now(UTC)).astimezone(zone).date()


class RightsType(StrEnum):
    PUBLIC_DOMAIN = "public_domain"
    LICENSED = "licensed"
    OWNED = "owned"


class RightsProblem(StrEnum):
    COMMERCIAL_USE_NOT_GRANTED = "commercial_use_not_granted"
    AUDIO_RIGHTS_MISSING = "audio_rights_missing"
    AI_PROCESSING_RIGHTS_MISSING = "ai_processing_rights_missing"
    RIGHTS_HOLDER_MISSING = "rights_holder_missing"
    LICENSE_NOT_STARTED = "license_not_started"
    LICENSE_EXPIRED = "license_expired"
    LICENSE_PERIOD_REQUIRED = "license_period_required"


@dataclass(frozen=True, slots=True)
class RightsTerms:
    rights_type: RightsType
    rights_holder: str | None
    license_start: date | None
    license_end: date | None
    commercial_use: bool
    audio_rights: bool
    ai_processing_rights: bool


def rights_problems(terms: RightsTerms, today: date) -> list[RightsProblem]:
    problems: list[RightsProblem] = []
    if not terms.commercial_use:
        problems.append(RightsProblem.COMMERCIAL_USE_NOT_GRANTED)
    if not terms.audio_rights:
        problems.append(RightsProblem.AUDIO_RIGHTS_MISSING)
    if not terms.ai_processing_rights:
        problems.append(RightsProblem.AI_PROCESSING_RIGHTS_MISSING)
    if terms.rights_type is not RightsType.PUBLIC_DOMAIN and not (terms.rights_holder or "").strip():
        problems.append(RightsProblem.RIGHTS_HOLDER_MISSING)
    if terms.rights_type is RightsType.LICENSED and terms.license_start is None:
        problems.append(RightsProblem.LICENSE_PERIOD_REQUIRED)
    if terms.license_start is not None and today < terms.license_start:
        problems.append(RightsProblem.LICENSE_NOT_STARTED)
    if terms.license_end is not None and today > terms.license_end:
        problems.append(RightsProblem.LICENSE_EXPIRED)
    return problems
