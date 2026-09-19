import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import StrictRequest
from app.security.realtime import RealtimeGrant


class RealtimeTokenRequest(StrictRequest):
    session_id: uuid.UUID


class RealtimeTokenResponse(BaseModel):
    url: str
    # Short-lived LiveKit access token. The client connects with it and asks for a new one to reconnect.
    token: str
    room: str
    identity: str
    expires_at: datetime
    # Which agent the server dispatched, and the data-channel contract it speaks.
    agent_name: str
    protocol: str

    @classmethod
    def from_grant(cls, grant: RealtimeGrant) -> "RealtimeTokenResponse":
        return cls(
            url=grant.url,
            token=grant.token,
            room=grant.room,
            identity=grant.identity,
            expires_at=grant.expires_at,
            agent_name=grant.agent_name,
            protocol=grant.protocol,
        )
