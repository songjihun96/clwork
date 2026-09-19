"""EmbeddingProvider for any OpenAI-compatible `/embeddings` endpoint (hosted or self-hosted vLLM/TEI)."""

import logging
from collections.abc import Sequence

import httpx

from story_core.providers.base import ProviderInfo, ProviderUnavailable, Usage
from story_core.providers.embedding.base import EmbeddingKind, EmbeddingResult
from story_core.providers.http import (
    HttpProviderConfig,
    build_client,
    decode_json,
    raise_for_status,
    wrap_transport_error,
)

logger = logging.getLogger(__name__)

# Asymmetric models need the query and the passage embedded differently. The prefixes are model-specific,
# so they are configuration, not code: a symmetric model gets empty ones.
DEFAULT_PREFIXES: dict[EmbeddingKind, str] = {"query": "", "document": ""}


class OpenAICompatibleEmbeddingProvider:
    def __init__(
        self,
        config: HttpProviderConfig,
        *,
        dimensions: int,
        prefixes: dict[EmbeddingKind, str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._client = client or build_client(config)
        self._owns_client = client is None
        self._prefixes = prefixes or DEFAULT_PREFIXES
        self.dimensions = dimensions
        self.info = ProviderInfo(
            provider="openai_compatible", model=config.model, capabilities=frozenset({"batch"})
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def embed(self, texts: Sequence[str], *, kind: EmbeddingKind, timeout_s: float) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(vectors=[])
        prefix = self._prefixes.get(kind, "")
        payload = {
            "model": self._config.model,
            "input": [f"{prefix}{text}" for text in texts],
            "encoding_format": "float",
        }
        try:
            response = await self._client.post(
                self._config.endpoint("embeddings"), json=payload, timeout=timeout_s
            )
            body = response.content
        except httpx.HTTPError as exc:
            raise wrap_transport_error(exc) from exc
        raise_for_status(response, body)
        data = decode_json(body)

        items = data.get("data")
        if not isinstance(items, list) or len(items) != len(texts):
            raise ProviderUnavailable("embedding response did not match the request size")
        vectors: list[list[float]] = [[] for _ in texts]
        for item in items:
            index = item.get("index", 0) if isinstance(item, dict) else 0
            embedding = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(embedding, list) or not isinstance(index, int) or not 0 <= index < len(texts):
                raise ProviderUnavailable("embedding response was malformed")
            if len(embedding) != self.dimensions:
                raise ProviderUnavailable(f"embedding width {len(embedding)} != configured {self.dimensions}")
            vectors[index] = [float(value) for value in embedding]
        if any(not vector for vector in vectors):
            raise ProviderUnavailable("embedding response was missing an item")

        raw_usage = data.get("usage")
        prompt_tokens = raw_usage.get("prompt_tokens") if isinstance(raw_usage, dict) else None
        return EmbeddingResult(
            vectors=vectors,
            usage=Usage(
                input_tokens=int(prompt_tokens) if isinstance(prompt_tokens, int | float | str) else 0,
                characters=sum(len(text) for text in texts),
            ),
        )
