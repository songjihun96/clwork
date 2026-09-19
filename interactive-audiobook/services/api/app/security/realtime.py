"""LiveKit access tokens for Talk mode (docs/realtime.md §2.1).

A realtime token is a bearer credential for a media server, so it is minted with the **least privilege
that still works** and a short life. Three choices are deliberate:

* one room per reading session (``rs_{session_id}``) and ``max_participants`` of 2 — a leaked token cannot
  be used to join someone else's room, and cannot add a silent listener to your own;
* ``can_publish_sources`` is the microphone only. The app has no reason to publish camera or screen, and a
  compromised client must not be able to;
* the token carries **only the session id** as metadata. Nothing about the user, their plan or their
  position: the agent re-reads all of that from the database, where it can be re-authorised.

Agent dispatch is explicit (``RoomConfiguration.agents``) rather than automatic, so which agent — and which
version of it — handles a session is decided here, by the server.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from livekit.api import AccessToken, RoomAgentDispatch, RoomConfiguration, VideoGrants

# Only sources the reader legitimately publishes. LiveKit rejects anything else at the server.
MICROPHONE_ONLY = ["microphone"]
ROOM_PREFIX = "rs_"
IDENTITY_PREFIX = "u_"
# The data-channel contract the client must speak (docs/realtime.md §2.2).
PROTOCOL = "story.v1"


def room_name(session_id: uuid.UUID) -> str:
    return f"{ROOM_PREFIX}{session_id}"


def participant_identity(user_id: uuid.UUID) -> str:
    return f"{IDENTITY_PREFIX}{user_id}"


@dataclass(frozen=True, slots=True)
class RealtimeGrant:
    url: str
    token: str
    room: str
    identity: str
    expires_at: datetime
    agent_name: str
    protocol: str = PROTOCOL


@dataclass(frozen=True, slots=True)
class RealtimeConfig:
    url: str
    api_key: str
    api_secret: str
    agent_name: str
    ttl_seconds: int = 600
    # Reader + agent. Reconnecting reuses the same identity, which LiveKit swaps rather than adds.
    max_participants: int = 2
    # How long the room survives with nobody in it — the reconnection grace window.
    empty_timeout_seconds: int = 60


class RealtimeTokenIssuer:
    def __init__(self, config: RealtimeConfig) -> None:
        if not config.api_key or not config.api_secret:
            raise ValueError("LiveKit API key and secret are required to issue realtime tokens")
        self._config = config

    @property
    def agent_name(self) -> str:
        return self._config.agent_name

    def issue(
        self, *, user_id: uuid.UUID, session_id: uuid.UUID, now: datetime | None = None
    ) -> RealtimeGrant:
        config = self._config
        room = room_name(session_id)
        identity = participant_identity(user_id)
        issued_at = now or datetime.now(UTC)
        # Metadata is readable by every participant in the room: session id only.
        metadata = json.dumps({"session_id": str(session_id)}, separators=(",", ":"))

        token = (
            AccessToken(config.api_key, config.api_secret)
            .with_identity(identity)
            .with_metadata(metadata)
            .with_ttl(timedelta(seconds=config.ttl_seconds))
            .with_grants(
                VideoGrants(
                    room_join=True,
                    room=room,
                    can_publish=True,
                    can_subscribe=True,
                    can_publish_data=True,
                    can_publish_sources=MICROPHONE_ONLY,
                    can_update_own_metadata=False,
                    room_admin=False,
                    room_create=False,
                    room_list=False,
                    room_record=False,
                    recorder=False,
                    hidden=False,
                    agent=False,
                )
            )
            .with_room_config(
                RoomConfiguration(
                    max_participants=config.max_participants,
                    empty_timeout=config.empty_timeout_seconds,
                    agents=[RoomAgentDispatch(agent_name=config.agent_name, metadata=metadata)],
                )
            )
            .to_jwt()
        )
        return RealtimeGrant(
            url=config.url,
            token=token,
            room=room,
            identity=identity,
            expires_at=issued_at + timedelta(seconds=config.ttl_seconds),
            agent_name=config.agent_name,
        )
