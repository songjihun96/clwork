"""Text questions about the book being read (Phase 4; the realtime voice path reuses this in Phase 6).

The mobile app never talks to an AI provider: it posts a question here and the server holds every key,
decides how far the spoiler window reaches, and pays for the call. Rate limiting is per account because
the cost is per account.
"""

import logging
import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request
from story_core.books.rights import rights_problems, rights_today
from story_core.ingestion.pipeline import rights_terms
from story_core.models.book import BookRights
from story_core.providers.embedding.base import EmbeddingProvider
from story_core.providers.llm.base import LLMProvider
from story_core.rag.answering import QuestionRejected, QuestionService
from story_core.rag.retrieval import Retriever
from story_core.reading.sessions import ReadingSessionService

from app.core.errors import AppError, Forbidden
from app.dependencies import CurrentUserDep, DbSession, user_rate_limit
from app.schemas.common import ERROR_RESPONSES, ErrorResponse
from app.schemas.questions import QuestionRequest, QuestionResponse

router = APIRouter(prefix="/reading/sessions", tags=["questions"])
logger = logging.getLogger(__name__)


def get_llm(request: Request) -> LLMProvider:
    return cast(LLMProvider, request.app.state.llm)


def get_embedder(request: Request) -> EmbeddingProvider:
    return cast(EmbeddingProvider, request.app.state.embedder)


@router.post(
    "/{session_id}/questions",
    response_model=QuestionResponse,
    responses={**ERROR_RESPONSES, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    dependencies=[user_rate_limit("questions", "question_rate_limit_per_minute")],
)
async def ask_question(
    session_id: uuid.UUID,
    body: QuestionRequest,
    current: CurrentUserDep,
    session: DbSession,
    llm: Annotated[LLMProvider, Depends(get_llm)],
    embedder: Annotated[EmbeddingProvider, Depends(get_embedder)],
) -> QuestionResponse:
    view = await ReadingSessionService(session).get(current.user.id, session_id)

    # Sending book text to an LLM is AI processing: the licence is re-checked at question time, not only
    # at ingestion, so an expired contract stops answering immediately.
    rights = await session.get(BookRights, view.book.id)
    if rights is None or rights_problems(rights_terms(rights), rights_today()):
        raise Forbidden("This book cannot be used for questions.", code="book_unavailable")

    service = QuestionService(session, retriever=Retriever(session, embedder), llm=llm)
    try:
        answer = await service.ask(view, body.text)
    except QuestionRejected as exc:
        raise AppError("The question could not be processed.", code=exc.code) from exc
    logger.info(
        "question_answered",
        extra={
            "session_id": str(session_id),
            "grounded": answer.grounded,
            "guard_action": answer.guard_action,
            "citations": len(answer.citations),
            "latency_ms": answer.latency_ms.get("total"),
        },
    )
    return QuestionResponse.from_answer(answer)
