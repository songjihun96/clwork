"""Talk mode connection tokens (docs/realtime.md §2).

The app asks for a token per connection; the server decides the room, the identity, what may be published
and which agent is dispatched. LiveKit keys never leave this service. Rate limited per account because a
connection starts an agent and burns realtime minutes.
"""

import logging
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request
from story_core.books.rights import rights_problems, rights_today
from story_core.ingestion.pipeline import rights_terms
from story_core.models.book import BookRights
from story_core.reading.sessions import ReadingSessionService

from app.core.errors import Forbidden, ServiceUnavailable
from app.dependencies import CurrentUserDep, DbSession, user_rate_limit
from app.schemas.common import ERROR_RESPONSES, ErrorResponse
from app.schemas.realtime import RealtimeTokenRequest, RealtimeTokenResponse
from app.security.realtime import RealtimeTokenIssuer

router = APIRouter(prefix="/realtime", tags=["realtime"])
logger = logging.getLogger(__name__)


def get_issuer(request: Request) -> RealtimeTokenIssuer | None:
    return cast(RealtimeTokenIssuer | None, request.app.state.realtime_issuer)


@router.post(
    "/token",
    response_model=RealtimeTokenResponse,
    responses={
        **ERROR_RESPONSES,
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    dependencies=[user_rate_limit("realtime", "realtime_rate_limit_per_minute")],
)
async def realtime_token(
    body: RealtimeTokenRequest,
    current: CurrentUserDep,
    session: DbSession,
    issuer: Annotated[RealtimeTokenIssuer | None, Depends(get_issuer)],
) -> RealtimeTokenResponse:
    if issuer is None:
        # Talk mode is optional: Listen mode keeps working without LiveKit configured.
        raise ServiceUnavailable("Talk mode is not available.", code="realtime_unavailable")

    view = await ReadingSessionService(session).get(current.user.id, body.session_id)

    # Talk mode narrates the book and sends its text to AI providers; both rights are re-checked here so
    # an expired licence ends live sessions too, not just new downloads.
    rights = await session.get(BookRights, view.book.id)
    if rights is None or rights_problems(rights_terms(rights), rights_today()):
        raise Forbidden("This book cannot be used in Talk mode.", code="book_unavailable")

    grant = issuer.issue(user_id=current.user.id, session_id=body.session_id)
    # The token itself is never logged — it is a bearer credential for the media server.
    logger.info(
        "realtime_token_issued",
        extra={
            "session_id": str(body.session_id),
            "room": grant.room,
            "agent_name": grant.agent_name,
        },
    )
    return RealtimeTokenResponse.from_grant(grant)
