"""Chooses LLM and embedding implementations from configuration (docs/provider-abstraction.md §3).

Assembly happens once at start-up (API lifespan, worker entrypoint). Domain code receives interfaces, so
switching vendor or moving to a self-hosted model changes settings and one file here — nothing else.
"""

from dataclasses import dataclass

from story_core.providers.embedding.base import EmbeddingProvider
from story_core.providers.embedding.fake import FakeEmbeddingProvider
from story_core.providers.embedding.openai_compatible import OpenAICompatibleEmbeddingProvider
from story_core.providers.http import HttpProviderConfig
from story_core.providers.llm.base import LLMProvider
from story_core.providers.llm.fake import FakeLLMProvider
from story_core.providers.llm.openai_compatible import OpenAICompatibleLLMProvider
from story_core.providers.resilience import (
    ResilientEmbeddingProvider,
    ResilientLLMProvider,
    RetryPolicy,
    Timeouts,
)

SUPPORTED_LLM_PROVIDERS = ("fake", "openai_compatible")
SUPPORTED_EMBEDDING_PROVIDERS = ("fake", "openai_compatible")


@dataclass(frozen=True, slots=True)
class LLMConfig:
    provider: str
    model: str = "fake-story-v1"
    base_url: str | None = None
    api_key: str | None = None
    # Declared per deployment: a self-hosted server may or may not support guided decoding.
    supports_json_schema: bool = False


@dataclass(frozen=True, slots=True)
class EmbeddingConfig:
    provider: str
    dimensions: int
    model: str = "hashing-bigram-v1"
    base_url: str | None = None
    api_key: str | None = None
    query_prefix: str = ""
    document_prefix: str = ""


def build_llm_provider(config: LLMConfig) -> LLMProvider:
    if config.provider == "fake":
        return FakeLLMProvider(model=config.model)
    if config.provider == "openai_compatible":
        if not config.base_url:
            raise ValueError("LLM_BASE_URL is required for the openai_compatible provider")
        capabilities = {"streaming"} | ({"json_schema"} if config.supports_json_schema else set())
        return OpenAICompatibleLLMProvider(
            HttpProviderConfig(base_url=config.base_url, model=config.model, api_key=config.api_key),
            capabilities=frozenset(capabilities),
        )
    raise ValueError(f"Unknown LLM provider '{config.provider}'. Supported: {SUPPORTED_LLM_PROVIDERS}")


def build_embedding_provider(config: EmbeddingConfig) -> EmbeddingProvider:
    if config.provider == "fake":
        return FakeEmbeddingProvider(dimensions=config.dimensions, model=config.model)
    if config.provider == "openai_compatible":
        if not config.base_url:
            raise ValueError("EMBEDDING_BASE_URL is required for the openai_compatible provider")
        return OpenAICompatibleEmbeddingProvider(
            HttpProviderConfig(base_url=config.base_url, model=config.model, api_key=config.api_key),
            dimensions=config.dimensions,
            prefixes={"query": config.query_prefix, "document": config.document_prefix},
        )
    raise ValueError(
        f"Unknown embedding provider '{config.provider}'. Supported: {SUPPORTED_EMBEDDING_PROVIDERS}"
    )


def build_resilient_llm(
    config: LLMConfig, *, policy: RetryPolicy | None = None, timeouts: Timeouts | None = None
) -> ResilientLLMProvider:
    return ResilientLLMProvider(build_llm_provider(config), policy=policy, timeouts=timeouts)


def build_resilient_embedding(
    config: EmbeddingConfig, *, policy: RetryPolicy | None = None, timeouts: Timeouts | None = None
) -> ResilientEmbeddingProvider:
    return ResilientEmbeddingProvider(build_embedding_provider(config), policy=policy, timeouts=timeouts)
