"""The ``story.v1`` data-channel contract (docs/realtime.md §2.2).

Shared by the agent and mirrored in the app (``apps/mobile/src/features/talk/protocol.ts``), because both
ends must agree on the envelope: ``{v, type, seq, ts}`` plus a type-specific payload.

Two rules make the protocol survivable across app-store release lag, where an old app and a new agent talk
to each other for months:

* **an unknown ``type`` is ignored, not an error** — a new agent may send message types an installed app has
  never heard of;
* **an unknown field is ignored** — payloads may grow.

So decoding never raises on well-formed JSON it does not understand; it returns ``None`` and the caller
logs it. Only a malformed envelope (not JSON, wrong version, missing type) is a protocol violation.
"""

import json
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

PROTOCOL: Final = "story.v1"
VERSION: Final = 1
# Reliable data messages are capped by LiveKit; ours are tiny, and this keeps a bug from sending a book.
MAX_MESSAGE_BYTES: Final = 15_000


class AgentMessage(StrEnum):
    """Agent → app."""

    STATE = "state"
    SENTENCE = "sentence"
    SCENE = "scene"
    TRANSCRIPT_PARTIAL = "transcript.partial"
    TRANSCRIPT_FINAL = "transcript.final"
    ANSWER_DELTA = "answer.delta"
    ANSWER_DONE = "answer.done"
    ERROR = "error"


class ClientMessage(StrEnum):
    """App → agent."""

    CONTROL = "control"
    SETTINGS = "settings"
    CLIENT_PLAYOUT = "client.playout"


class ControlCommand(StrEnum):
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    ASK = "ASK"
    SEEK_SENTENCE = "SEEK_SENTENCE"
    SEEK_PARAGRAPH = "SEEK_PARAGRAPH"
    STOP = "STOP"


KNOWN_TYPES: Final = frozenset({*AgentMessage, *ClientMessage})


class ProtocolError(Exception):
    """The envelope itself is malformed — not simply an unrecognised message type."""


@dataclass(frozen=True, slots=True)
class Envelope:
    type: str
    seq: int
    ts: int
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def known(self) -> bool:
        return self.type in KNOWN_TYPES


class MessageWriter:
    """Numbers messages for one connection so the app can spot gaps and reordering."""

    def __init__(self, *, clock: Any = time.time) -> None:
        self._seq = 0
        self._clock = clock

    def encode(self, message_type: str, payload: dict[str, Any] | None = None) -> bytes:
        self._seq += 1
        body: dict[str, Any] = {
            "v": VERSION,
            "type": str(message_type),
            "seq": self._seq,
            "ts": int(self._clock() * 1000),
            **(payload or {}),
        }
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        if len(data) > MAX_MESSAGE_BYTES:
            raise ProtocolError(f"message too large ({len(data)} bytes)")
        return data


def decode(data: bytes | str) -> Envelope:
    """Parse an envelope. Raises only when the envelope is unusable."""
    try:
        parsed = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProtocolError("message is not JSON") from exc
    if not isinstance(parsed, dict):
        raise ProtocolError("message is not an object")
    if parsed.get("v") != VERSION:
        raise ProtocolError(f"unsupported protocol version {parsed.get('v')!r}")
    message_type = parsed.get("type")
    if not isinstance(message_type, str) or not message_type:
        raise ProtocolError("message has no type")
    seq = parsed.get("seq")
    ts = parsed.get("ts")
    payload = {k: v for k, v in parsed.items() if k not in {"v", "type", "seq", "ts"}}
    return Envelope(
        type=message_type,
        seq=seq if isinstance(seq, int) else 0,
        ts=ts if isinstance(ts, int) else 0,
        payload=payload,
    )
