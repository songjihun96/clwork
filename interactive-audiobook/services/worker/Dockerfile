# syntax=docker/dockerfile:1
# Build context: repository root.
#   docker build -f services/worker/Dockerfile .
FROM python:3.13-slim-trixie AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

FROM base AS deps
COPY packages/story-core /build/story-core
COPY services/worker /build/worker
RUN pip install /build/story-core /build/worker

FROM base AS runtime
# ffmpeg encodes paragraph narration to AAC (AUDIO_FORMAT=aac). Package lists are not kept in the image.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && apt-get clean \
 && find /var/lib/apt/lists -type f -delete
RUN groupadd --system app && useradd --system --gid app --home /app app \
 && mkdir -p /data/storage && chown app:app /data/storage
COPY --from=deps /usr/local /usr/local
USER app
ENV STORAGE_LOCAL_ROOT=/data/storage
CMD ["taskiq", "worker", "worker.main:broker", "--workers", "2"]
