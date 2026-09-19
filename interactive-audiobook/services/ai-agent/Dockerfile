# syntax=docker/dockerfile:1
# Build context: repository root.
#   docker build -f services/ai-agent/Dockerfile .
FROM python:3.13-slim-trixie AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

FROM base AS deps
COPY packages/story-core /build/story-core
COPY services/ai-agent /build/ai-agent
RUN pip install /build/story-core /build/ai-agent

FROM base AS runtime
RUN groupadd --system app && useradd --system --gid app --home /app app
COPY --from=deps /usr/local /usr/local
USER app
# The worker is not an HTTP service: it dials LiveKit and waits to be dispatched, so it exposes no port.
# `start` is the agents-framework production mode (`dev` adds file watching).
CMD ["python", "-m", "agent.main", "start"]
