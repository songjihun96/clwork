"""Reading sessions (Listen mode). In Talk mode the realtime agent becomes the single writer."""

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response, status
from story_core.reading.sessions import ReadingSessionService

from app.dependencies import CurrentUserDep, DbSession
from app.schemas.common import ERROR_RESPONSES, ErrorResponse
from app.schemas.reading import (
    OpenSessionRequest,
    PlaybackRequest,
    ReadingSessionListResponse,
    ReadingSessionResponse,
    UpdateSessionRequest,
)

router = APIRouter(prefix="/reading/sessions", tags=["reading"])

_ERRORS = {**ERROR_RESPONSES, 404: {"model": ErrorResponse}}
_DEVICE_ID = re.compile(r"^[A-Za-z0-9\-]{8,64}$")


def get_service(session: DbSession) -> ReadingSessionService:
    return ReadingSessionService(session)


ServiceDep = Annotated[ReadingSessionService, Depends(get_service)]


def _writer(device_id: str | None) -> str:
    return f"device:{device_id}" if device_id and _DEVICE_ID.match(device_id) else "api"


@router.post(
    "",
    response_model=ReadingSessionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={**_ERRORS, 200: {"model": ReadingSessionResponse, "description": "Existing active session"}},
)
async def open_session(
    body: OpenSessionRequest, current: CurrentUserDep, service: ServiceDep, response: Response
) -> ReadingSessionResponse:
    """Get-or-create the active session for a book (idempotent)."""
    view, created = await service.open(current.user.id, body.book_id)
    if not created:
        response.status_code = status.HTTP_200_OK
    return ReadingSessionResponse.from_view(view)


@router.get("", response_model=ReadingSessionListResponse, responses=ERROR_RESPONSES)
async def list_sessions(current: CurrentUserDep, service: ServiceDep) -> ReadingSessionListResponse:
    views = await service.list_active(current.user.id)
    return ReadingSessionListResponse(items=[ReadingSessionResponse.from_view(v) for v in views])


@router.get("/{session_id}", response_model=ReadingSessionResponse, responses=_ERRORS)
async def get_session(
    session_id: uuid.UUID, current: CurrentUserDep, service: ServiceDep
) -> ReadingSessionResponse:
    return ReadingSessionResponse.from_view(await service.get(current.user.id, session_id))


@router.patch(
    "/{session_id}",
    response_model=ReadingSessionResponse,
    responses={**_ERRORS, 409: {"model": ErrorResponse}},
)
async def update_session(
    session_id: uuid.UUID,
    body: UpdateSessionRequest,
    current: CurrentUserDep,
    service: ServiceDep,
    x_device_id: Annotated[str | None, Header(max_length=64)] = None,
) -> ReadingSessionResponse:
    user_id = current.user.id
    view = None
    if body.position is not None:
        view = await service.update_position(
            user_id,
            session_id,
            paragraph_id=body.position.paragraph_id,
            sentence_index=body.position.sentence_index,
            expected_version=body.position.expected_version,
            updated_by=_writer(x_device_id),
        )
    if body.spoiler_mode is not None or body.speed is not None:
        view = await service.update_settings(
            user_id, session_id, spoiler_mode=body.spoiler_mode, speed=body.speed
        )
    if view is None:  # unreachable: UpdateSessionRequest requires at least one field
        view = await service.get(user_id, session_id)
    return ReadingSessionResponse.from_view(view)


@router.post(
    "/{session_id}/playback",
    response_model=ReadingSessionResponse,
    responses={**_ERRORS, 409: {"model": ErrorResponse}},
)
async def playback(
    session_id: uuid.UUID, body: PlaybackRequest, current: CurrentUserDep, service: ServiceDep
) -> ReadingSessionResponse:
    return ReadingSessionResponse.from_view(
        await service.apply_playback(current.user.id, session_id, body.action)
    )
