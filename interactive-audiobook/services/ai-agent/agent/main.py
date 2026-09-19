"""Agent worker entrypoint.

    python -m agent.main start          # connects to LiveKit and waits for dispatched jobs

Registered under an explicit ``agent_name``, so only sessions whose token asks for this agent (by name)
reach it — the API decides which agent version serves a session, not the media server (docs/realtime.md
§2.1). Worker permissions are the agent's half of least privilege: publish the narration track, subscribe
to the reader, send data messages. Nothing else.

The job's own authority is deliberately thin. The token's metadata names a session id and nothing else, so
the first thing a job does is load that session from the database and **re-check that it is readable** —
ownership, processing state and rights. A token that outlived a licence cannot be used to narrate.
"""

import json
import logging
import uuid

import sentry_sdk
from livekit import agents
from livekit.protocol import models
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from story_core.agent.router import IntentRouter
from story_core.books.rights import rights_problems, rights_today
from story_core.db.session import create_engine, create_sessionmaker
from story_core.ingestion.pipeline import rights_terms
from story_core.logging import configure_logger
from story_core.models.book import BookRights, BookStatus
from story_core.providers.registry import build_resilient_embedding, build_resilient_llm
from story_core.providers.stt.registry import build_stt_provider
from story_core.providers.tts.base import Voice
from story_core.providers.tts.registry import build_tts_provider
from story_core.reading.sessions import ReadingSessionService
from story_core.reading.state_machine import Position
from story_core.storage.factory import build_storage

from agent.livekit_room import LiveKitRoom
from agent.resources import CachedNarration, TtsSpeech, question_asker
from agent.session import SessionContext, TalkSession
from agent.settings import AgentSettings

logger = logging.getLogger("agent")
settings = AgentSettings()


class SessionUnavailableError(Exception):
    """The job cannot run: no such session, not this user's, or the book may no longer be used."""


async def entrypoint(ctx: agents.JobContext) -> None:
    """One dispatched job = one reading session's room."""
    session_id = _session_id_from(ctx)
    engine = create_engine(settings.database_options)
    sessionmaker = create_sessionmaker(engine)
    try:
        await ctx.connect(auto_subscribe=agents.AutoSubscribe.AUDIO_ONLY)
        context = await _load_session(sessionmaker, session_id)
        logger.info(
            "job_started",
            extra={
                "room": ctx.room.name,
                "job_id": ctx.job.id,
                "session_id": str(context.session_id),
                "agent": settings.agent_name,
            },
        )

        storage = build_storage(settings.storage_config())
        tts = build_tts_provider(settings.tts_provider)
        voice = Voice(settings.tts_default_voice)
        room = LiveKitRoom(ctx.room, sample_rate=tts.sample_rate, stt_sample_rate=tts.sample_rate)
        await room.publish()

        llm = build_resilient_llm(settings.llm_config())
        session = TalkSession(
            context,
            room=room,
            narration=CachedNarration(sessionmaker, storage, tts, book_id=context.book_id, voice=voice),
            speech=TtsSpeech(tts, voice=voice),
            stt=build_stt_provider(settings.stt_provider, script=settings.stt_fake_script),
            router=IntentRouter(llm if settings.intent_classifier_enabled else None),
            ask=question_asker(
                sessionmaker,
                user_id=context.user_id,
                session_id=context.session_id,
                embedder=build_resilient_embedding(settings.embedding_config()),
                llm=llm,
            ),
        )

        async def report() -> None:
            logger.info(
                "job_finished",
                extra={
                    "room": ctx.room.name,
                    "state": session.state,
                    "answers": len(session.answers),
                    "sentences": len(session.spoken_sentences),
                    "latency_ms": session.timings.marks,
                },
            )

        ctx.add_shutdown_callback(report)
        await session.run()
        # The session only returns when the reader has gone or asked to stop; nothing is left to serve.
        ctx.shutdown(reason="session ended")
    except SessionUnavailableError as exc:
        logger.warning("job_rejected", extra={"room": ctx.room.name, "reason": str(exc)})
        ctx.shutdown(reason="session unavailable")
    finally:
        await engine.dispose()


def _session_id_from(ctx: agents.JobContext) -> uuid.UUID:
    """The API puts the session id in the dispatch metadata; the room name is the fallback."""
    raw = ctx.job.metadata or "{}"
    try:
        parsed = json.loads(raw)
        value = parsed.get("session_id") if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        value = None
    if value is None and ctx.room.name.startswith("rs_"):
        value = ctx.room.name[len("rs_") :]
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise SessionUnavailableError("dispatch metadata has no session id") from exc


async def _load_session(
    sessionmaker: async_sessionmaker[AsyncSession], session_id: uuid.UUID
) -> SessionContext:
    """Re-authorise before speaking: the token only proves *which* session was asked for."""
    async with sessionmaker() as db:
        view = await ReadingSessionService(db).for_agent(session_id)
        if view is None:
            raise SessionUnavailableError("session not found or already ended")
        if view.book.status != BookStatus.READY:
            raise SessionUnavailableError("book is not ready")
        rights = await db.get(BookRights, view.book.id)
        if rights is None or rights_problems(rights_terms(rights), rights_today()):
            raise SessionUnavailableError("book rights do not allow talk mode")
        if view.position.paragraph_id is None:
            raise SessionUnavailableError("session has no position")
        return SessionContext(
            session_id=session_id,
            user_id=view.session.user_id,
            book_id=view.book.id,
            start=Position(str(view.position.paragraph_id), view.position.sentence_index),
        )


def main() -> None:
    # The agents CLI configures the root logger itself, so we only own our own loggers (see
    # story_core.logging.configure_logger) — otherwise every line is printed twice.
    for name in ("agent", "story_core"):
        configure_logger(name, settings.log_level)
    if settings.sentry_dsn is not None:
        sentry_sdk.init(
            dsn=settings.sentry_dsn.get_secret_value(),
            environment=settings.env,
            send_default_pii=False,
            include_local_variables=False,
        )
    agents.cli.run_app(
        agents.WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name=settings.agent_name,
            ws_url=settings.livekit_url,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret.get_secret_value(),
            permissions=agents.WorkerPermissions(
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
                can_update_metadata=False,
                # Worker permissions take the protobuf enum *value*; the token grant (app/security/
                # realtime.py) takes the lowercase source name. Passing the wrong one of the two fails at
                # worker registration with "unknown enum label", not at publish time.
                can_publish_sources=[models.TrackSource.MICROPHONE],
                hidden=False,
            ),
            # Deploys drain: finish live sessions, take no new jobs (docs/architecture.md deployment).
            drain_timeout=settings.drain_timeout_seconds,
        )
    )


if __name__ == "__main__":
    main()
