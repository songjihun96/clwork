"""Agent settings: the shared names, and the list-parsing trap.

`.env.example` is loaded here on purpose — a setting the documented file cannot express is a setting nobody
will configure correctly.
"""

from pathlib import Path

import pytest

from agent.settings import AgentSettings

ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"


def test_documented_env_file_loads() -> None:
    settings = AgentSettings(_env_file=ENV_EXAMPLE)

    assert settings.agent_name == "story-agent"
    assert settings.stt_provider == "fake"
    # Pipe-separated, because a scripted utterance may contain a comma.
    assert settings.stt_fake_script == ("하람은 누구야", "멈춰")
    assert settings.intent_classifier_enabled is False


def test_script_is_read_as_a_plain_string_not_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without NoDecode, pydantic-settings JSON-parses tuple fields and this raises instead."""
    monkeypatch.setenv("STT_FAKE_SCRIPT", " 첫 질문 | 두 번째 질문 |")

    settings = AgentSettings(_env_file=None)

    assert settings.stt_fake_script == ("첫 질문", "두 번째 질문")


def test_provider_settings_are_shared_with_the_api_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mismatch would be silent: Talk mode would re-synthesise narration and miss the search index."""
    monkeypatch.setenv("TTS_PROVIDER", "azure")
    monkeypatch.setenv("TTS_DEFAULT_VOICE", "ko-KR-A")
    monkeypatch.setenv("EMBEDDING_MODEL", "bge-m3")
    monkeypatch.setenv("LLM_MODEL", "qwen3")

    settings = AgentSettings(_env_file=None)

    assert settings.tts_provider == "azure" and settings.tts_default_voice == "ko-KR-A"
    assert settings.embedding_config().model == "bge-m3"
    assert settings.llm_config().model == "qwen3"


def test_empty_optional_values_become_none(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SENTRY_DSN", "LLM_BASE_URL", "EMBEDDING_API_KEY", "S3_BUCKET"):
        monkeypatch.setenv(name, "")

    settings = AgentSettings(_env_file=None)

    assert settings.sentry_dsn is None
    assert settings.llm_config().base_url is None
    assert settings.embedding_config().api_key is None


def test_database_options_name_the_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """pg_stat_activity must show which service holds a connection."""
    options = AgentSettings(_env_file=None).database_options
    assert options.application_name == "audiobook-ai-agent"
    assert options.pool_size <= 4  # many short-lived jobs, one small pool each
