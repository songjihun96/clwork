# Interactive Audiobook

AI가 소설을 낭독하고, 사용자가 언제든 음성으로 끼어들어 질문하면 책의 문맥으로 답한 뒤 읽던 위치로 돌아오는 iOS/Android 오디오북 플랫폼.

> **현재 상태: Phase 6 (Realtime Story Agent) 진행 중 — 대화 로직·어댑터 완료, Docker 스택 E2E와 실기기 확인이 남음.** 전체 설계와 단계별 계획은 [`docs/`](docs/)를 먼저 읽는다.

| 문서 | 내용 |
|---|---|
| [architecture.md](docs/architecture.md) | 현황 분석, 설계 검증(요구안에서 바꾼 부분), 기술 선택, 위험, 인프라, 핵심 질문 10개 답변 |
| [roadmap.md](docs/roadmap.md) | Phase 0~13 산출물과 종료 조건 |
| [realtime.md](docs/realtime.md) | LiveKit 연결, 상태 머신, barge-in, resume, 복구 |
| [ai-architecture.md](docs/ai-architecture.md) | Intent, RAG, 스포일러 방지, Scene Engine, 자체 LLM |
| [mobile-architecture.md](docs/mobile-architecture.md) | Expo CNG, 오디오 2경로, 백그라운드 정책 |
| [database.md](docs/database.md) | 테이블, 위치 모델, pgvector |
| [security.md](docs/security.md) | 인증, 음성 데이터 보호, 로그, 보관기간 |
| [provider-abstraction.md](docs/provider-abstraction.md) | AI provider 인터페이스, retry/timeout, 캐시 키 |

## 구조

```text
apps/mobile            Expo SDK 57 · React Native 0.86 · TypeScript strict
services/api           FastAPI control plane (auth, books, reading sessions, admin)
services/worker        Taskiq worker (인제스트, 임베딩 인덱싱, 문단 오디오 렌더; 이후 Scene·선생성)
services/ai-agent      LiveKit agent worker (Story agent: STT → intent → RAG → TTS, 상태 머신 경유)
packages/story-core    Python 공유 도메인: 모델, 상태 머신, 파서, 저장소, 작업 큐
packages/shared-types  OpenAPI → TypeScript 생성 타입 (npm run gen:api)
packages/api-client    타입 안전 API client (토큰 갱신 single-flight, timeout)
packages/config        공유 tsconfig
infrastructure/        postgres init 등
docs/                  설계 문서
```

Phase별 진행 상황은 [roadmap](docs/roadmap.md)에 있다.

## 요구 사항

- Python 3.13, Node.js 22+, npm 10+
- Docker (PostgreSQL·Redis를 로컬에서 띄울 때)
- 모바일 실행: Expo Go 앱(Phase 1) → Phase 5부터 개발 빌드(EAS Build 또는 Android Studio/Xcode)

> ⚠️ **경로에 한글 등 비ASCII 문자가 있으면 Android 네이티브 빌드(Gradle)가 실패할 수 있다.** 네이티브 빌드 전에 `C:\dev\interactive-audiobook` 같은 ASCII 경로로 옮긴다.

## 빠른 시작

### 1. 환경 변수

```bash
cp .env.example .env
```

개발 환경에서는 `JWT_SECRET`을 비워 두면 명시적으로 안전하지 않은 기본값이 쓰인다. 운영(`ENV=production`)에서는 기본값이면 서버가 기동을 거부한다.

### 2. Backend — Docker로 실행 (PostgreSQL + Redis + API + worker)

```bash
docker compose up --build
```

`migrate` 서비스가 `alembic upgrade head`를 실행한 뒤 API와 worker가 뜬다. API와 worker는 `book-storage` 볼륨을 공유한다(S3/R2는 Phase 3).

- http://localhost:8000/health/ready
- http://localhost:8000/docs (운영에서는 비활성)

컨테이너 안에서 스크립트 실행:

```bash
docker compose exec api python scripts/seed_sample_book.py
```

```bash
docker compose exec api python scripts/set_user_role.py --email you@example.com --role admin
```

PostgreSQL 대상 테스트 (개발 DB와 분리된 테스트 DB 사용):

```bash
docker compose exec postgres psql -U audiobook -c "CREATE DATABASE audiobook_test"
```

```bash
cd services/api && TEST_DATABASE_URL=postgresql+asyncpg://audiobook:audiobook@127.0.0.1:5432/audiobook_test .venv/Scripts/python -m pytest
```

> Windows: Docker Desktop은 WSL2가 필요하다. `wsl --install --no-distribution`(관리자) 후 재부팅.

### 3. Backend — 로컬 개발 (Docker 없이 테스트)

```bash
cd services/api
python -m venv .venv
.venv/Scripts/python -m pip install -e ../../packages/story-core[dev] -e ".[dev]" -e ../worker[dev] -e ../ai-agent[dev]   # macOS/Linux: .venv/bin/python
.venv/Scripts/python -m pytest                                   # api
.venv/Scripts/python -m pytest ../../packages/story-core         # 상태 머신·파서·파이프라인·RAG·프로토콜
.venv/Scripts/python -m pytest ../worker                         # 이름 기반 작업 실행
.venv/Scripts/python -m pytest ../ai-agent                       # echo 파이프라인
```

테스트는 기본적으로 SQLite + fakeredis로 돈다. **PostgreSQL 대상으로도 반드시 실행**한다 (CI 필수):

```bash
TEST_DATABASE_URL=postgresql+asyncpg://audiobook:audiobook@localhost:5432/audiobook_test .venv/Scripts/python -m pytest
```

서버만 직접 실행 (Redis가 없어도 API는 뜬다. 이때 책 처리 요청만 503):

```bash
.venv/Scripts/alembic upgrade head
.venv/Scripts/python scripts/seed_sample_book.py          # 샘플 책(자체 작성 텍스트) 등록·처리
.venv/Scripts/uvicorn app.main:create_app --factory --reload
```

관리자 권한 부여 (HTTP로는 불가, 감사 로그 기록):

```bash
.venv/Scripts/python scripts/set_user_role.py --email you@example.com --role admin
```

worker 실행 (Redis 필요):

```bash
cd ../worker && ../api/.venv/Scripts/taskiq worker worker.main:broker --workers 2
```

문장 분리기 평가:

```bash
.venv/Scripts/python ../../packages/story-core/scripts/eval_sentence_splitter.py
```

품질 검사:

```bash
.venv/Scripts/python -m ruff check app tests && .venv/Scripts/python -m ruff format --check app tests && .venv/Scripts/python -m mypy app tests
```

### 4. Mobile

```bash
npm install                 # 저장소 루트에서 (npm workspaces)
npm run mobile              # = expo start
```

- 실기기(Expo Go)에서는 `.env`의 `EXPO_PUBLIC_API_URL`을 PC의 LAN IP(`http://192.168.x.x:8000`)로 바꾼다. Android 에뮬레이터는 `http://10.0.2.2:8000`.
- 릴리스 빌드는 `https://` API URL이 아니면 실행을 거부한다.

```bash
npm --workspace @audiobook/mobile run typecheck
npm --workspace @audiobook/mobile run lint     # eslint-config-expo (react-hooks 규칙 포함)
npm --workspace @audiobook/mobile run test
npm --workspace @audiobook/mobile run doctor
```

`react-hooks` 규칙은 경고가 아니라 오류로 취급한다. 렌더 중 ref 쓰기나 이펙트 안의 `setState`는 동시 렌더링에서 깨지므로, 비동기로 도착하는 값은 상태로 두고 화면 값은 **파생**시킨다(`useReader`의 `target` → `location`).

### 5. API 타입 재생성

백엔드 스키마(Pydantic)를 바꾼 뒤:

```bash
npm run gen:api
```

`packages/shared-types/src/api.ts`는 생성 파일이므로 직접 수정하지 않는다.

### 6. 질문 (Phase 4)

기본 설정은 계정이 필요 없는 오프라인 provider다(`LLM_PROVIDER=fake`, `EMBEDDING_PROVIDER=fake`, 운영에서는 거부). 임베딩 fake는 난수가 아니라 문자 바이그램 해싱 모델이라 검색·스포일러 필터를 끝까지 검증할 수 있다. 실제 제공사는 `LLM_BASE_URL`/`EMBEDDING_BASE_URL`만 채우면 된다(OpenAI 호환 엔드포인트, vLLM 포함).

책을 처리하면 worker가 인제스트에 이어 `books.embed`를 실행해 검색 인덱스를 만든다. 그 다음:

```bash
curl -X POST http://localhost:8000/v1/reading/sessions/<session_id>/questions \
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" \
  -d '{"text": "하람은 누구야?"}'
```

답변은 **현재 읽은 위치까지의 내용만** 근거로 삼는다. 모바일 앱은 AI 제공사를 직접 호출하지 않고 이 엔드포인트만 부른다.

검색·스포일러·거절 평가:

```bash
.venv/Scripts/python ../../packages/story-core/scripts/eval_rag.py --verbose
```

`spoiler leaks`는 0이어야 하고, 0이 아니면 스크립트가 비정상 종료한다. 평가셋은 `infrastructure/eval/`에 있고 본문은 이 프로젝트에서 직접 쓴 원고다.

### 7. 대화 모드 (Phase 5)

로컬 LiveKit 서버로 클라우드 계정 없이 전 구간을 돌릴 수 있다:

```bash
docker compose --profile realtime up -d livekit ai-agent
```

`.env`의 `LIVEKIT_URL`은 **클라이언트가 접속할 주소**다(로컬은 `ws://127.0.0.1:7880`). agent 컨테이너는 내부 주소(`ws://livekit:7880`)로 자동 덮어쓴다. 키가 비어 있으면 `POST /v1/realtime/token`이 503을 주고 Listen 모드만 동작한다.

agent는 낭독 중 발화를 받아 intent를 정하고, 책 질문이면 Phase 4 경로로 답을 만들어 절 단위로 말한 뒤 끊긴 문장에서 다시 읽는다. 오프라인 STT는 인식하지 않고 **발화 감지 + 스크립트**로 동작하므로(`STT_FAKE_SCRIPT`), 계정 없이 전 흐름을 돌릴 수 있다.

전송 왕복 지연 측정 (앱 → LiveKit → agent → LiveKit → 앱):

```bash
cd services/ai-agent && ../api/.venv/Scripts/python scripts/measure_roundtrip.py --rounds 8 --verbose
```

- 모바일 Talk 모드는 **개발 빌드가 필요하다**(Expo Go 불가). Expo Go에서는 "대화 모드는 개발 빌드에서만 동작해요"가 표시된다.
- `react`·`react-dom`은 워크스페이스 루트에 고정돼 있다. LiveKit이 끌어오는 웹 패키지가 더 새 React를 설치하면 훅이 전부 깨지므로, **lockfile을 임의로 재생성하지 않는다**.

### 8. 낭독 오디오 (Phase 3)

기본 설정은 계정이 필요 없는 개발용 가짜 TTS(`TTS_PROVIDER=fake`)다. 들리는 톤을 만들어 캐시·재생·위치 동기화를 끝까지 확인할 수 있고, 운영 설정에서는 거부된다. 실제 제공사는 계약 후 `story_core/providers/tts/`에 어댑터 한 개를 추가하고 `TTS_PROVIDER`를 바꾸면 된다.

- `AUDIO_FORMAT=wav`(의존성 없음) 또는 `aac`(ffmpeg 필요, worker 이미지에 포함)
- **API와 worker는 `TTS_PROVIDER`·`TTS_DEFAULT_VOICE`·`AUDIO_FORMAT`이 같아야 한다** (오디오 캐시 키에 들어간다)
- S3 호환 저장소 계약 테스트:

```bash
docker compose --profile s3 up -d s3mock
```

```bash
cd packages/story-core && TEST_S3_ENDPOINT=http://127.0.0.1:9090 ../../services/api/.venv/Scripts/python -m pytest tests/test_storage_s3.py
```

## API (Phase 1–5)

| Method | Path | 설명 |
|---|---|---|
| POST | `/v1/auth/register` | 이메일 가입 → 토큰 |
| POST | `/v1/auth/login` | 이메일 로그인 (IP·계정별 rate limit) |
| POST | `/v1/auth/oauth/{apple\|google}` | 네이티브 SDK ID token 검증 로그인 |
| POST | `/v1/auth/refresh` | refresh token 회전 (재사용 탐지 시 family 폐기) |
| POST | `/v1/auth/logout` | refresh family 폐기 |
| GET | `/v1/users/me` | 내 정보 |
| DELETE | `/v1/users/me` | 계정 영구 삭제 (비밀번호 재확인) |
| GET | `/v1/books` | 읽을 수 있는 책 (처리 완료 + 유효한 권리) |
| GET | `/v1/books/{id}` | 책 상세 + 목차 |
| GET | `/v1/books/{id}/chapters/{chapter_id}` | 장 본문 (문단 → 문장) |
| POST | `/v1/reading/sessions` | 책의 활성 세션 열기 (멱등, 201/200) |
| GET | `/v1/reading/sessions` | 이어 듣기 목록 |
| GET/PATCH | `/v1/reading/sessions/{id}` | 조회 / 위치(`expected_version`, 충돌 시 409)·속도·스포일러 모드 |
| POST | `/v1/reading/sessions/{id}/playback` | `play`·`pause`·`stop` (상태 머신 경유) |
| POST | `/v1/reading/sessions/{id}/audio` | 문단 낭독 오디오: 준비됨(서명 URL + 문장 타임스탬프) / 준비 중(작업 등록) |
| POST | `/v1/reading/sessions/{id}/questions` | 책에 대한 질문 → 근거(인용) 있는 답변. **읽은 위치까지만** 검색, 계정당 분당 한도 |
| POST | `/v1/realtime/token` | Talk 모드 접속 토큰 (room 1개·마이크만·10분·명시적 agent dispatch). LiveKit 미설정이면 503 |
| GET | `/v1/media/{key}?exp=&sig=` | 서명된 미디어 스트리밍 (로컬 저장소, Range 지원) |
| POST | `/v1/admin/books` | (admin) EPUB/TXT 업로드 + 메타데이터·권리 |
| PUT | `/v1/admin/books/{id}/rights` | (admin) 권리 정보 수정 |
| POST | `/v1/admin/books/{id}/process` | (admin) 처리 요청 — 권리 부족 시 409 |
| GET | `/v1/admin/books`, `/v1/admin/books/{id}` | (admin) 처리 상태 |
| GET | `/health/live`, `/health/ready` | 프로세스 / 의존성 상태 |

모든 오류 응답: `{"error": {"code", "message", "request_id"}}`

## 주요 모듈

| 모듈 | 역할 |
|---|---|
| `services/api/app/config.py` | 환경변수 설정, 운영 안전성 검증 |
| `story_core/reading/state_machine.py` | ReadingSession 상태 머신 (순수 함수, 실행 가능한 명세) |
| `story_core/reading/sessions.py` | 세션 열기·위치 저장(버전 충돌)·재생 제어 |
| `story_core/ingestion/` | EPUB/TXT 파서, 한국어 문장 분리, 수집 파이프라인 |
| `story_core/audio/` | 문장 TTS 캐시 → 문단 오디오 + 타임스탬프, 캐시 키, WAV/AAC 인코딩 |
| `story_core/providers/tts/` | TTSProvider 인터페이스, 개발용 FakeTTSProvider |
| `story_core/providers/{llm,embedding}/` | LLM·임베딩 인터페이스, OpenAI 호환 구현, 오프라인 fake |
| `story_core/providers/resilience.py` | 타임아웃·재시도(스트림은 첫 청크 이전에만) |
| `story_core/rag/search.py` | 모든 검색이 거치는 스포일러 필터 기반 쿼리 (벡터·키워드·위치 창) |
| `story_core/rag/spoiler.py` | `allowed_seq` 계산 + 답변 출력 검사(SpoilerGuard) |
| `story_core/rag/{chunking,index}.py` | 문단 → 청크, 임베딩 인덱스 구축(내용 해시로 재임베딩 회피) |
| `story_core/rag/{context,answering}.py` | 토큰 예산 컨텍스트, 질문 → 답변 오케스트레이션·기록 |
| `story_core/realtime/protocol.py` | `story.v1` 데이터 채널 envelope (모르는 type은 무시) |
| `app/security/realtime.py` | LiveKit 최소 권한 토큰 발급 (room·마이크만·10분·명시적 dispatch) |
| `services/ai-agent/agent/` | LiveKit agent worker (Phase 5 echo, Phase 6 Story agent) |
| `apps/mobile/src/features/talk/` | TalkTransport 인터페이스·LiveKit 구현·연결 수명주기·story.v1 |
| `story_core/agent/intent.py`·`router.py` | 규칙 우선 IntentRouter (상태 의존, 분류기 폴백) |
| `story_core/agent/clauses.py` | LLM 스트림 → TTS 절 분할 (첫 음성을 빨리 내기 위한 경계) |
| `story_core/providers/stt/` | STTProvider 스트리밍 인터페이스, 오프라인 구현 |
| `services/ai-agent/agent/session.py` | TalkSession — 상태 머신이 상태를 소유, 세션은 I/O만 |
| `story_core/storage/` | 로컬(HMAC 서명 URL)·S3/R2 저장소 |
| `apps/mobile/src/features/narration` | NarrationController(오디오 준비 대기·문장 추적), expo-audio 플레이어 |
| `story_core/books/` | 권리 판정(파이썬·SQL 동기화 테스트), 독자용 조회 |
| `story_core/logging.py` | JSON 로그 + 민감 키 마스킹 |
| `app/core/middleware.py` | request id, 접근 로그(route 템플릿만), 보안 헤더 |
| `app/security/tokens.py` | access JWT / refresh token 발급·검증 |
| `app/security/identity.py` | Apple·Google ID token 검증 (`IdentityTokenVerifier`) |
| `app/security/ratelimit.py` | Redis fixed-window rate limiter |
| `app/services/auth_service.py` | 인증 유스케이스, 트랜잭션 경계 |
| `apps/mobile/src/features/auth` | 인증 스토어, SecureStore, 세션 복구 |
| `apps/mobile/src/features/reading` | 장 단위 이동 계산, 위치 저장기(latest-wins·충돌), Reader 훅 |
| `packages/api-client` | 401 → single-flight refresh → 재시도 |

## 보안 원칙 (요약)

- AI provider 키를 포함한 **모든 secret은 backend에만** 둔다. 앱 번들의 `EXPO_PUBLIC_*`는 공개 값이다.
- `.env`는 커밋하지 않는다.
- 로그에 요청 body·토큰·이메일·음성·원문을 남기지 않는다.

자세한 내용은 [docs/security.md](docs/security.md).
