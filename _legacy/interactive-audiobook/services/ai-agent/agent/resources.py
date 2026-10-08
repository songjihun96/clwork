"""Production adapters for the session's ports: the book's audio, the agent's voice, and its answers.

Nothing new is invented here. Narration reuses the Phase 3 sentence cache (so Talk mode and Listen mode
play the *same* audio and pay for synthesis once), and answering reuses the Phase 4 QuestionService (so the
spoiler window and the recorded provenance are identical whether the question was typed or spoken).
"""

import contextlib
import logging
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from story_core.audio.cache_keys import sentence_cache_key
from story_core.audio.pcm import PcmAudio, from_wav, silence
from story_core.models.audio import AudioAsset, AudioKind
from story_core.models.book import Sentence
from story_core.providers.tts.base import TTSProvider, TTSRequest, Voice
from story_core.rag.answering import AnswerEvent, QuestionService
from story_core.rag.retrieval import Retriever
from story_core.reading.sessions import ReadingSessionService
from story_core.reading.state_machine import Position
from story_core.storage.base import ObjectNotFound, StorageProvider

from agent.ports import SpokenSentence

logger = logging.getLogger("agent")

# Cues are short and reused every session; synthesised once per voice and kept in memory.
CUE_TEXT = {
    "PARDON": "잘 못 들었어요. 다시 말해줄래요?",
    "LISTENING": "응, 말해줘.",
    "ANSWER_FAILED": "지금은 답하기 어려워요.",
    "BRIDGE": "그럼 다시 이야기할게.",
}


@dataclass(frozen=True, slots=True)
class SentenceRow:
    paragraph_id: uuid.UUID
    sentence_index: int
    text: str
    global_seq: int


class CachedNarration:
    """Sentence audio from the Phase 3 cache, synthesising only what is missing."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        storage: StorageProvider,
        tts: TTSProvider,
        *,
        book_id: uuid.UUID,
        voice: Voice,
        language: str = "ko-KR",
    ) -> None:
        self._sessionmaker = sessionmaker
        self._storage = storage
        self._tts = tts
        self._book_id = book_id
        self._voice = voice
        self._language = language
        self.synthesised = 0
        self.cache_hits = 0

    async def sentences_from(
        self, *, paragraph_id: str, sentence_index: int, count: int
    ) -> Sequence[SpokenSentence]:
        # One row more than is voiced: it names the sentence that follows the batch, and costs no synthesis.
        rows = await self._next_sentences(uuid.UUID(paragraph_id), sentence_index, count + 1)
        spoken: list[SpokenSentence] = []
        for index, row in enumerate(rows[:count]):
            following = rows[index + 1] if index + 1 < len(rows) else None
            spoken.append(
                SpokenSentence(
                    paragraph_id=str(row.paragraph_id),
                    sentence_index=row.sentence_index,
                    audio=await self._audio_for(row.text),
                    following=Position(str(following.paragraph_id), following.sentence_index)
                    if following
                    else None,
                )
            )
        return spoken

    async def _next_sentences(
        self, paragraph_id: uuid.UUID, sentence_index: int, count: int
    ) -> list[SentenceRow]:
        """The next ``count`` sentences in reading order, crossing paragraph boundaries."""
        async with self._sessionmaker() as session:
            start = await session.scalar(
                select(Sentence.global_seq).where(
                    Sentence.paragraph_id == paragraph_id, Sentence.sentence_index == sentence_index
                )
            )
            if start is None:
                return []
            rows = (
                await session.execute(
                    select(Sentence.paragraph_id, Sentence.sentence_index, Sentence.text, Sentence.global_seq)
                    .where(Sentence.book_id == self._book_id, Sentence.global_seq >= start)
                    .order_by(Sentence.global_seq)
                    .limit(count)
                )
            ).all()
        return [
            SentenceRow(
                paragraph_id=row.paragraph_id,
                sentence_index=row.sentence_index,
                text=row.text,
                global_seq=row.global_seq,
            )
            for row in rows
        ]

    async def _audio_for(self, text: str) -> PcmAudio:
        # The exact key Phase 3 writes, so Talk mode reads the cache the Listen path filled.
        request = TTSRequest(text=text, voice=self._voice, language=self._language)
        key = sentence_cache_key(self._tts.info, request, self._tts.sample_rate)
        async with self._sessionmaker() as session:
            cached = await session.scalar(
                select(AudioAsset).where(AudioAsset.cache_key == key, AudioAsset.kind == AudioKind.SENTENCE)
            )
        if cached is not None:
            try:
                audio = from_wav(await self._storage.get_bytes(cached.storage_key))
                self.cache_hits += 1
                return audio
            except ObjectNotFound:
                logger.warning("sentence_audio_missing_in_storage", extra={"asset_id": str(cached.id)})

        result = await self._tts.synthesize(request)
        self.synthesised += 1
        return result.audio


class TtsSpeech:
    """The agent's own voice: answers and the short cached cues."""

    def __init__(self, tts: TTSProvider, *, voice: Voice, language: str = "ko-KR") -> None:
        self._tts = tts
        self._voice = voice
        self._language = language
        self._cues: dict[str, PcmAudio] = {}
        self.said: list[str] = []

    async def say(self, text: str) -> PcmAudio:
        self.said.append(text)
        result = await self._tts.synthesize(TTSRequest(text=text, voice=self._voice, language=self._language))
        return result.audio

    async def cue(self, name: str) -> PcmAudio | None:
        if name in self._cues:
            return self._cues[name]
        text = CUE_TEXT.get(name)
        if text is None:
            # An unknown cue must not stall the session; a beat of silence keeps the timing sane.
            return silence(200, self._tts.sample_rate)
        audio = await self.say(text)
        self._cues[name] = audio
        return audio


def question_asker(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    embedder: object,
    llm: object,
) -> Callable[[str], AsyncIterator[AnswerEvent]]:
    """``ask(text)`` for the session: the same path a typed question takes (Phase 4), streamed."""

    async def ask(question: str) -> AsyncIterator[AnswerEvent]:
        # One database session for the whole answer: the stream reads (guard) and writes (record) as it goes.
        async with sessionmaker() as session:
            view = await ReadingSessionService(session).get(user_id, session_id)
            service = QuestionService(
                session,
                retriever=Retriever(session, embedder),  # type: ignore[arg-type]
                llm=llm,  # type: ignore[arg-type]
            )
            # aclosing: when the session closes this generator early, the inner one (and with it the model's
            # stream) must be closed too; a nested generator is not closed by its parent's aclose.
            async with contextlib.aclosing(service.ask_stream(view, question)) as events:
                async for event in events:
                    yield event

    return ask
