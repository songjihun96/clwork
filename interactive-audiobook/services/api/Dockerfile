# syntax=docker/dockerfile:1
# Build context: repository root (the API depends on packages/story-core).
#   docker build -f services/api/Dockerfile .
FROM python:3.13-slim-trixie AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

FROM base AS deps
COPY packages/story-core /build/story-core
COPY services/api/pyproject.toml /build/api/pyproject.toml
# Runtime dependencies only; the app code is copied later for better layer caching.
RUN pip install /build/story-core \
 && python - <<'EOF' > /build/requirements.txt
import tomllib
deps = tomllib.load(open("/build/api/pyproject.toml", "rb"))["project"]["dependencies"]
print("\n".join(d for d in deps if not d.startswith("story-core")))
EOF
RUN pip install -r /build/requirements.txt

FROM base AS runtime
RUN groupadd --system app && useradd --system --gid app --home /app app \
 && mkdir -p /data/storage && chown app:app /data/storage
COPY --from=deps /usr/local /usr/local
COPY services/api/alembic.ini ./
COPY services/api/migrations ./migrations
COPY services/api/app ./app
COPY services/api/scripts ./scripts
# Sample text for scripts/seed_sample_book.py (development only).
COPY infrastructure/seed ./seed
USER app
ENV STORAGE_LOCAL_ROOT=/data/storage
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2).status == 200 else 1)"
# Client IPs behind a load balancer are resolved by the app (TRUSTED_PROXY_COUNT), not by uvicorn,
# so X-Forwarded-For from untrusted clients can never bypass rate limits.
# Migrations run as a separate step (compose `migrate` service / deploy job), never on every replica start.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
