import uuid
from typing import Literal

from pydantic import BaseModel, Field
from story_core.rag.answering import MAX_QUESTION_CHARS, Answer

from app.schemas.common import StrictRequest


class QuestionRequest(StrictRequest):
    text: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)


class Citation(BaseModel):
    """Where the answer came from, by reading position — the client can jump there or show it."""

    paragraph_id: uuid.UUID
    start_global_seq: int
    end_global_seq: int


class QuestionResponse(BaseModel):
    answer: str
    # False when nothing was retrieved or the guard replaced the answer: the client can say so.
    grounded: bool
    citations: list[Citation]
    # The spoiler window that applied, so a client bug can never look wider than the server allowed.
    allowed_global_seq: int
    spoiler_mode: Literal["NO_SPOILER", "LIGHT_SPOILER", "FULL_SPOILER"]
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    latency_ms: dict[str, int]

    @classmethod
    def from_answer(cls, answer: Answer) -> "QuestionResponse":
        return cls(
            answer=answer.text,
            grounded=answer.grounded,
            citations=[
                Citation(
                    paragraph_id=citation.paragraph_id,
                    start_global_seq=citation.start_global_seq,
                    end_global_seq=citation.end_global_seq,
                )
                for citation in answer.citations
            ],
            allowed_global_seq=answer.allowed_seq,
            spoiler_mode=answer.spoiler_mode.value,
            conversation_id=answer.conversation_id,
            message_id=answer.message_id,
            latency_ms=answer.latency_ms,
        )
