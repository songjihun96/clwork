"""story.v1 envelope: numbering, forward compatibility, and what counts as malformed.

Forward compatibility is the point. An installed app and a deployed agent differ in version for as long as
app review takes, so an unknown message type or an extra field must be *ignored*, while a broken envelope
must be loud.
"""

import json

import pytest

from story_core.realtime.protocol import (
    MAX_MESSAGE_BYTES,
    VERSION,
    AgentMessage,
    ClientMessage,
    ControlCommand,
    MessageWriter,
    ProtocolError,
    decode,
)


def test_writer_numbers_messages_and_stamps_time() -> None:
    writer = MessageWriter(clock=lambda: 1_700_000_000.5)

    first = decode(writer.encode(AgentMessage.STATE, {"state": "READING"}))
    second = decode(writer.encode(AgentMessage.SENTENCE, {"sentence_index": 3}))

    assert (first.seq, second.seq) == (1, 2)
    assert first.ts == 1_700_000_000_500
    assert first.type == "state" and first.payload == {"state": "READING"}
    assert second.payload["sentence_index"] == 3


def test_every_known_type_round_trips() -> None:
    writer = MessageWriter()
    for message_type in (*AgentMessage, *ClientMessage):
        envelope = decode(writer.encode(message_type))
        assert envelope.type == message_type.value
        assert envelope.known


def test_unknown_type_decodes_and_is_marked_unknown() -> None:
    """A newer agent may send types this app has never heard of; they are ignored, not errors."""
    raw = json.dumps({"v": VERSION, "type": "scene.transition.v2", "seq": 9, "ts": 1, "extra": True})

    envelope = decode(raw)

    assert envelope.type == "scene.transition.v2"
    assert envelope.known is False
    assert envelope.payload["extra"] is True


def test_unknown_fields_in_a_known_type_are_kept_not_rejected() -> None:
    raw = json.dumps({"v": VERSION, "type": "state", "seq": 1, "ts": 1, "state": "READING", "mood": "x"})
    envelope = decode(raw)
    assert envelope.payload == {"state": "READING", "mood": "x"}


@pytest.mark.parametrize(
    "raw",
    [
        b"not json",
        json.dumps([1, 2, 3]),
        json.dumps({"type": "state", "seq": 1, "ts": 1}),  # no version
        json.dumps({"v": 99, "type": "state"}),  # future major version
        json.dumps({"v": VERSION, "seq": 1}),  # no type
        json.dumps({"v": VERSION, "type": "", "seq": 1}),
    ],
)
def test_malformed_envelopes_raise(raw: bytes | str) -> None:
    with pytest.raises(ProtocolError):
        decode(raw)


def test_missing_seq_or_ts_is_tolerated() -> None:
    envelope = decode(json.dumps({"v": VERSION, "type": "control", "command": "PAUSE"}))
    assert envelope.seq == 0 and envelope.ts == 0
    assert envelope.payload["command"] == ControlCommand.PAUSE


def test_oversized_messages_are_refused_before_sending() -> None:
    """A bug that tried to send book text down the data channel should fail here, not at the server."""
    writer = MessageWriter()
    with pytest.raises(ProtocolError, match="too large"):
        writer.encode(AgentMessage.ANSWER_DELTA, {"text": "가" * MAX_MESSAGE_BYTES})


def test_korean_text_is_not_escaped() -> None:
    data = MessageWriter().encode(AgentMessage.ANSWER_DELTA, {"text": "다시 읽어줄게"})
    assert "다시 읽어줄게".encode() in data  # ensure_ascii=False keeps messages small
