# Roadmap

> 순서는 요구사항 §45 "구현 우선순위"를 따른다. 요구안 Phase 목록(§37)은 RAG(3)가 Basic TTS(4)보다 앞이지만 §45는 Basic TTS(6)가 RAG(7)보다 앞이다. **§45가 "절대적 우선"이므로** Mobile Reader + Basic TTS를 Phase 3, RAG를 Phase 4로 두었다. 두 작업은 서로 의존하지 않아 순서를 바꿔도 설계는 같다.
>
> 각 Phase는 **종료 조건(테스트)**을 통과해야 다음으로 넘어간다.

| Phase | 이름 | §45 항목 | 상태 |
|---|---|---|---|
| 0 | Architecture | 1 | ✅ 완료 |
| 1 | Skeleton + Auth | 2 | ✅ 완료 (실기기 확인만 남음) |
| 2 | Book Engine + ReadingSession | 3, 4 | ✅ 완료 — Docker·PostgreSQL 검증 완료, 실기기 확인만 남음 |
| 3 | Mobile Reader + Basic TTS | 5, 6 | ✅ 완료 — Docker·S3Mock·PostgreSQL 검증 완료, 실기기 소리 확인만 남음 |
| 4 | RAG | 7 | ✅ 완료 — 스포일러 차단 검증 완료. 검색·거절 품질 수치는 실제 공급사 계정 후 측정 |
| 5 | LiveKit 연결 | 8 | 🚧 서버·에이전트·모바일 코드 완료, 왕복 지연 측정 완료 — **실기기 개발 빌드만 남음** |
| 6 | Realtime Story Agent | 9 | 🚧 로직·어댑터 완료(테스트 22개), **Docker 스택 E2E 보류 — C: 디스크 100%로 Docker 이미지 저장소 손상** |
| 7 | Barge-in + Resume | 10, 11 | |
| 8 | Scene Engine | 12 | |
| 9 | Scene Image | 13 | |
| 10 | Voice Clone | 14 | |
| 11 | Background Audio | 15 | |
| 12 | Subscription + Production Hardening | 16, 17 | |
| 13 | 자체 LLM 학습 파이프라인 | 18 | |

---

## Phase 0 — Architecture ✅
- 산출물: `docs/` 8개 문서
- 종료 조건: 핵심 질문 10개 답변, 위험 목록, 외부 서비스 목록 → [architecture.md §10](architecture.md#10-핵심-질문-10개에-대한-답)

## Phase 1 — Skeleton + Auth ✅
**Backend (`services/api`)**
- FastAPI app factory, 환경변수 설정(운영 안전성 검증), 구조화 로그 + 민감 키 마스킹, 에러 envelope, request id, 보안 헤더
- SQLAlchemy async + Alembic 첫 revision (users, auth_identities, refresh_tokens, audit_logs)
- 인증: 이메일 가입/로그인, access JWT + rotating refresh token + 재사용 탐지, 로그아웃, `GET /v1/users/me`, 계정 삭제
- Apple/Google ID token 검증 (`IdentityTokenVerifier`, JWKS)
- Redis rate limiter (+ 테스트용 in-memory)
- `/health/live`, `/health/ready`
- Dockerfile, docker-compose (postgres+pgvector, redis, api)

**Mobile (`apps/mobile`)**
- Expo SDK 57 TypeScript strict, React Navigation(auth stack / main tabs / reader), 테마 토큰 + 다크 모드
- 화면: Splash, Login, Register, Home, Library, Reader(UI), Settings(테마·로그아웃·계정 삭제)
- 인증 스토어(SecureStore), 타입 생성 API client(single-flight refresh)

**Packages:** `shared-types`(OpenAPI 생성), `api-client`, `config`

**종료 조건**
- [x] backend pytest 46개 통과 (SQLite + fakeredis), ruff·mypy strict 통과
- [x] Alembic migration ↔ ORM 메타데이터 일치 테스트 (upgrade → diff 없음 → downgrade)
- [x] 실제 uvicorn 기동 스모크: migrate → register → me → refresh 회전, Redis 없을 때 ready 503
- [x] mobile·packages `tsc --noEmit`, Jest 17개 통과, `expo-doctor` 21/21, Metro Android 번들 생성 성공
- [x] Docker 환경 `docker compose up` + PostgreSQL 대상 pytest (2026-09-16, Phase 2 항목에서 함께 검증)
- [ ] **남은 검증:** Expo Go로 실기기 로그인 흐름 확인

## Phase 2 — Book Engine + ReadingSession ✅
**구현됨**
- `packages/story-core` (Python 공유 패키지): 모델, DB 세션, 상태 머신, 수집 파이프라인, 저장소·작업 큐 추상화, JSON 로깅
- 작업 큐: **Taskiq + Redis Streams** (`services/worker`, task `books.ingest`) — 선택 이유는 아래 "결정 기록"
- 테이블: `books`, `book_rights`, `chapters`, `sections`, `paragraphs`, `sentences`, `reading_sessions`, `reading_positions`, `users.role` (Alembic `0002`)
- EPUB 파서(표준 라이브러리 + defusedxml, zip bomb·경로·XXE 방어), TXT 파서, 한국어 문장 분리기(규칙 기반, 평가 스크립트 포함)
- 관리자 API: 업로드(내용 기반 형식 판별·크기 제한·스캐너 훅) / 권리 수정 / 처리 요청 / 조회
- 독자 API: 책 목록·상세(목차)·장 본문 — **처리 완료 + 현재 유효한 권리**인 책만 노출
- 독서 세션 API: 열기(멱등) / 목록 / 조회 / 위치 저장(`position_version` 낙관적 동시성) / 재생 제어(상태 머신 경유)
- **ReadingStateMachine** (순수 함수, 전이표 전 경로 + hypothesis 불변식 테스트 400 시퀀스)
- 재처리 시 독서 위치를 `global_seq`로 재연결
- Mobile: 서재·책 상세·Reader를 API에 연결, 장 단위 로드, 위치 저장(직렬화·latest-wins), 다기기 충돌 확인 다이얼로그, 이어 듣기

**종료 조건**
- [x] epub/txt 업로드 → 문단/문장 저장 (API 테스트 + 실제 서버 스모크)
- [x] 권리 필드 부족 시 처리 거부 (API에서 409, worker에서 재검사)
- [x] 앱 재시작 후 같은 문장 복구 — API 테스트(새 클라이언트 로그인), 실제 uvicorn 프로세스 재시작 스모크, 모바일 Reader 통합 테스트(가짜 HTTP 서버)
- [x] story-core 66 · api 55 · worker 1 · mobile 29 테스트, ruff·mypy strict·tsc, expo-doctor, Metro 번들
- [x] **Docker + PostgreSQL 18 검증 (2026-09-16):** `docker compose up --build` → migrate(0001→0002) → api·worker 기동, pgvector 0.8.6·pg_trgm 설치 확인
- [x] PostgreSQL 대상 테스트: story-core 67 · api 54 통과 (SQLite 전용 마이그레이션 테스트 1개 skip)
- [x] PostgreSQL에서 ORM 모델 ↔ 마이그레이션 스키마 diff 없음, upgrade → downgrade base 후 잔여 테이블 없음
- [x] **실제 큐 E2E:** 관리자 업로드 → 처리 요청 → Redis Streams → worker 처리(0.5초) → 독자 목록·세션·위치 저장·409
- [ ] 남은 검증: 실기기(Expo Go) 앱 흐름

**PostgreSQL 검증에서 발견해 고친 버그:** 라이선스 날짜를 UTC 날짜로 판정하고 있었다. 한국 시간으로 계약이 끝난 뒤에도 최대 9시간 동안 책이 노출되는 문제다 (SQLite 테스트는 우연히 같은 날짜라 통과했다). 권리 판정 "오늘"을 계약 시간대(`RIGHTS_TIMEZONE`, 기본 `Asia/Seoul`)로 계산하도록 바꾸고 경계 테스트를 추가했다. Windows와 slim 컨테이너에는 시간대 DB가 없어 `tzdata`를 의존성에 넣었다.

**결정 기록**
| 결정 | 이유 | 기각한 대안 |
|---|---|---|
| Taskiq 0.12 + taskiq-redis `RedisStreamBroker` | asyncio 네이티브, MIT, 2026-08 릴리스, redis-py 8과 호환, 스트림 ack로 at-least-once | **arq**: README에 "maintenance only", `redis<6` 요구 → 기존 redis 8.1과 충돌 / **SAQ**: redis extra가 `redis<8` / **Celery**: async I/O 작업과 모델 불일치 / **procrastinate**: psycopg 별도 풀 필요 |
| EPUB 파서 직접 구현 | EbookLib은 AGPL → 폐쇄형 네트워크 서비스에 부적합 | EbookLib |
| 규칙 기반 문장 분리 (우선) | 자체 gold set 20/20, 0.6ms, 인용부호 규칙 일관성, 의존성 없음 | kiwipiepy(LGPL-3.0): 15/20, 약 2초(모델 로드 포함). 단 gold set이 작고 자체 작성이라 **편향 가능** — 띄어쓰기 없는 문장("웃었다.그리고")은 kiwi가 더 낫다. 권리 확보된 실제 책으로 재평가 필요 |
| 위치는 `paragraph_id + sentence_index` + `sentence_global_seq` 이중 저장 | 재처리로 행 ID가 바뀌어도 순번으로 복구 | ID만 저장 |
| 한 사용자·책당 활성 세션 1개 (부분 유니크 인덱스) | 동시 열기 경쟁 조건 방지 | 애플리케이션 검사만 |

## Phase 3 — Mobile Reader + Basic TTS ✅
**구현됨 (2026-09-16)**
- `TTSProvider` 인터페이스 + `FakeTTSProvider`(계정 없이 들리는 톤 생성, 운영 설정에서는 거부) + 레지스트리. 실제 제공사 어댑터는 계정 확보 후 추가
- 문장 단위 PCM 캐시 → 문단 파일 연결 + **정확한 문장 타임스탬프**(제공사 타이밍 기능 불필요), 전달 형식 `wav`/`aac`(ffmpeg, worker 이미지)
- 캐시 키: provider·model·voice@version·언어·텍스트(정규화)·형식 — 속도는 합성하지 않고 플레이어에서 적용(캐시가 속도별로 쪼개지지 않음)
- `audio_assets` 테이블(Alembic `0003`), 동시 렌더링 안전(ON CONFLICT DO NOTHING, 콘텐츠 주소 저장 키)
- `StorageProvider.signed_get_url`: 로컬은 HMAC 서명 URL + `/v1/media/*`(Range 지원), `S3CompatibleStorage`(S3/R2, boto3, presigned)
- API `POST /v1/reading/sessions/{id}/audio`: 준비된 문단은 서명 URL+타이밍, 없으면 worker 작업 등록(Redis로 1분 중복 방지), 권리(audio_rights)·세션 소유·책 범위 검사
- worker task `audio.render_paragraph`
- 운영 안전 검사: `MEDIA_SIGNING_SECRET`(JWT와 달라야 함), `TTS_PROVIDER=fake` 금지, `PUBLIC_BASE_URL` https
- Mobile: `NarrationPlayer` 인터페이스 + expo-audio 구현, `NarrationController`(렌더 대기·문장 추적·URL 만료 갱신·취소), Reader 연동(들리는 문장 = 하이라이트·저장 위치, 문단·장 자동 이어 재생, 재생 중 이동 시 탐색)
- expo-audio config plugin의 기본값(마이크 권한·백그라운드 재생)을 명시적으로 끔 — Phase 5/11에서 필요할 때 켠다

**검증됨:** story-core 80 · api 64 · worker 2 · mobile 39 테스트(PostgreSQL + S3Mock 포함), ruff·mypy strict(테스트 포함)·tsc·ESLint, expo-doctor 21/21, Metro Android 번들

**종료 조건**
- [x] 같은 문단 2회 재생 시 TTS 호출 1회 — story-core·API 테스트 + Docker 스택에서 `characters_billed` 불변으로 재확인
- [x] 재생 위치가 서버에 저장·복구 (들리는 문장 → 위치 저장, Reader 통합 테스트)
- [x] **실제 큐 오디오 E2E (Docker):** 첫 요청 `pending` → worker AAC 렌더 1.2초 → `ready`, 다운로드 60KB(`ftyp`, `moov` 오프셋 32 = faststart), Range 요청 206, 위조 서명·미서명 URL 거부, 다른 키에 서명 재사용 거부, 2회차 캐시 적중(같은 저장 객체·신규 행 없음), 타 책 문단 `unavailable`
- [x] S3Mock 계약 테스트(put/get/exists/delete, presigned GET 실제 다운로드), PostgreSQL 테스트 + 마이그레이션 `0003` 포함 diff 없음·downgrade 청결
- [x] expo-doctor 21/21 (Expo 57.0.23)
- [ ] 실기기에서 실제 소리 재생 확인 — 하드웨어 필요, Phase 5 전에 함께 확인

**Phase 3 검증에서 발견해 고친 버그**
| 문제 | 원인 | 조치 |
|---|---|---|
| AAC 렌더가 매번 실패(`ffmpeg failed (234)`) → 오디오가 영원히 `pending` | `-movflags +faststart`는 되감을 수 있는 출력이 필요한데 `pipe:1`로 내보냈다. 컨테이너에서만 재현(로컬 테스트는 ffmpeg 없어 skip) | 임시 파일로 출력. 테스트를 "`moov`가 파일 앞 4KB 안" + "WAV의 절반 미만 크기"로 강화 |
| 비용 집계가 2배 | 문단 행과 문장 행에 `characters_billed`를 모두 기록 → `SUM()`이 이중 계산 | 과금은 공급자 호출 단위(문장)에만 기록, 문단은 0 |
| 컨테이너에서 샘플 시드 스크립트가 `IndexError` | 저장소 레이아웃(`parents[3]`)을 가정. 이미지에는 샘플 텍스트도 없었다 | 후보 경로 탐색 + 이미지에 `infrastructure/seed` 포함 |
| PostgreSQL에서 모델↔마이그레이션 diff 검사가 건너뛰어짐 | 해당 테스트가 SQLite 전용이었다 — JSONB·enum·timestamptz는 검증되지 않았다 | 전용 DB를 만들어 upgrade → diff → downgrade까지 검사하는 PostgreSQL 변형 추가 |
| 리더 훅이 렌더 중 ref를 쓰고 이펙트에서 `setState` | React 19 동시 렌더링에서 버려진 렌더의 값이 새어나가고, 렌더가 한 번 더 돈다 | 목표 위치(`target`)만 상태로 두고 `location`을 파생. ESLint `react-hooks` 규칙을 오류로 도입 |

## Phase 4 — RAG ✅
**구현됨 (2026-09-16)**
- `LLMProvider`·`EmbeddingProvider` 인터페이스 + `OpenAICompatible*`(hosted/vLLM 공용) + 오프라인 fake. 공용 `ProviderError` 계층(재시도 가능 여부가 타입에 있음), `ResilientLLMProvider`/`ResilientEmbeddingProvider`(타임아웃 필수, 지수 백오프+지터, **스트림은 첫 청크 이전에만 재시도**)
- `FakeEmbeddingProvider`는 난수가 아니라 **문자 바이그램 해싱** 모델이다. 결정적이고 계정이 필요 없으면서 유사도가 실제로 의미를 가져서, 검색·RRF·스포일러 필터를 공급사 없이 끝까지 검증할 수 있다(의미 검색 품질은 실제 모델이 필요).
- 청킹: 1문단 기준, 짧은 문단은 **같은 장·장면 안에서만** 병합, 긴 문단은 문장 경계로 분할. 임베딩 입력에만 `[장 제목]` 접두사(contextual chunk), 저장 텍스트는 원문
- `paragraph_embeddings`(Alembic `0004`): pgvector `vector(1024)` + HNSW(`vector_cosine_ops`), `(book_id, end_global_seq)` 인덱스, `(model_id, content_hash)`로 재임베딩 회피, trigram GIN(청크 텍스트·문장 텍스트)
- 검색 3경로(위치 창 / 벡터 / 키워드) + RRF 병합. **벡터 검색만 방언별**: PostgreSQL은 `<=>`+HNSW, SQLite는 같은 행을 정확 스캔(문서에 있던 exact-scan fallback과 같은 코드)
- 스포일러 방어 4계층: ① 모든 검색이 하나의 기반 쿼리(`end_global_seq <= allowed_seq`)를 거치고 "필터 끄기" 분기가 없다(FULL_SPOILER도 `allowed_seq`만 키운다) ② `allowed_seq`는 `max(현재 위치, max_read_seq)` ③ 프롬프트 규칙 ④ 출력 검사(`SpoilerGuard`)
- `ContextBuilder`: 문서의 토큰 예산(§3.4)을 강제하고, 초과 시 **검색 chunk → 대화 기록** 순으로 자른다. 위치 창과 질문은 자르지 않는다. 프롬프트는 버전 파일(`story_answer.v1.txt`)
- `QuestionService` + `POST /v1/reading/sessions/{id}/questions`: 위치 → 스포일러 창 → 검색 → 예산 컨텍스트 → LLM → 출력 검사 → `conversations`/`conversation_messages` 기록(근거 chunk id, 구간별 지연, prompt 버전). 계정당 분당 한도(비용이 계정에 붙으므로 IP가 아니라 계정 기준)
- worker `books.embed`: 인제스트 성공이 임베딩 작업을 이어서 넣는다. 공급사 장애가 파싱을 되돌리지 않고, 모델 교체 시 재파싱 없이 재임베딩할 수 있다
- 평가 하네스 `scripts/eval_rag.py` + 자체 창작 원고(`moonlight-post-office.txt`, 권리 owned) + 골드셋 58문항(근거 44 / 스포일러 탐침 8 / 답할 수 없는 질문 6). 위치를 문장 번호가 아니라 **인용 문구**로 지정해 청킹·문장 분리기를 바꿔도 평가셋이 조용히 무효화되지 않는다

**검증됨:** story-core 130(+PostgreSQL에서 132) · api 76 · worker 2 · mobile 39 테스트, ruff·mypy strict(테스트 포함)·ESLint·tsc, PostgreSQL 18 + pgvector 0.8.6 스택 E2E

**종료 조건**
- [x] **현재 위치 이후 chunk가 어떤 경로로도 검색되지 않음** — 경로별 검사(위치 창·벡터·키워드)를 `allowed_seq` 0…N 전 구간에 대해 수행 + 골드셋 스포일러 탐침 8개(누설 0) + 청크가 문장의 연속 덮개임을 hypothesis 속성 테스트로 보장(= `end_global_seq`가 그 청크의 최대 문장 번호)
- [x] 스포일러 누설 테스트를 일반 테스트 스위트에 포함(평가 스크립트에만 두지 않음)
- [x] Docker 스택 E2E: 실제 Redis 큐로 `books.ingest` → `books.embed`(0.65초, 4청크) → 질문 2회. 위치 0에서는 `allowed=0`·인용 1개·미래 문장 없음, 끝까지 들은 뒤 같은 질문은 인용 3개로 답변. 타 계정은 404. 총 1.7초
- [x] HNSW 인덱스가 실제로 사용 가능함을 확인(`Index Scan using ix_paragraph_embeddings_hnsw`), trigram GIN이 `LIKE '%…%'`에 사용됨을 확인
- [~] **근거 없는 질문에 "모른다" 비율 측정** — 하네스는 완성했으나 스텁 LLM은 주어진 컨텍스트로 답하도록 만들어져 구조상 0%가 나온다. 실제 수치는 `--llm openai_compatible`로 엔드포인트를 붙인 뒤 측정한다(공급사 계정 확보가 선행 조건)
- [~] 검색 적중률 44/44(100%)이지만 **selectivity 68%** — 평가용 원고가 4,600자·8청크라 top-k가 책의 대부분을 덮는다. 이 수치는 배관 검증일 뿐이며, 권리 확보된 실제 분량의 책으로 다시 측정해야 한다

**Phase 4 검증에서 발견해 고친 버그**
| 문제 | 원인 | 조치 |
|---|---|---|
| 잘못된 요청(지원하지 않는 파라미터)이 공급사에 3번 재시도됨 | 요청 본문을 만드는 코드가 `try` 안에 있어 `ProviderBadRequest`가 재시도 가능한 `ProviderUnavailable`로 재포장됐다 | 본문 생성을 `try` 밖으로 옮기고 전송 예외만 매핑. 상태코드→에러 타입 매핑을 표로 테스트 |
| 컨테이너에서 첫 질문이 500 | 프롬프트 템플릿이 wheel에 포함되지 않았다(`package-data`에 `.txt` 누락) | 패키지 데이터에 추가하고, **기동 시점에 템플릿을 읽어** 패키징 실수가 부팅 실패로 드러나게 함 |
| 지금 듣고 있는 문단이 컨텍스트에서 통째로 빠짐 | 위치 창도 `end_global_seq <= allowed_seq`로 걸러서, 진행 중인 청크(끝이 아직 안 들린 청크)가 제외됐다 — 질문 대상이 될 가능성이 가장 큰 문단이다 | 걸친 청크는 **들은 문장까지만 잘라서** 포함하고 `end_global_seq`를 `allowed_seq`로 보고. 안 들은 문장은 여전히 한 문장도 보이지 않음 |
| 프롬프트를 파싱하는 코드가 규칙 문구에 걸림 | 규칙 1·4가 `<context>`를 문자로 언급해 구분자 태그가 두 번 나왔다 | 규칙에서는 "context 블록"으로 표기해 태그는 구분자로만 한 번 등장 |
| PostgreSQL 전용 인덱스 3개가 모델↔마이그레이션 diff에 걸림 | 인덱스를 마이그레이션에만 만들고 ORM에 선언하지 않았다 | 모델에 방언 옵션째로 선언(SQLite는 옵션을 무시하고 일반 인덱스를 만든다) |
| PostgreSQL 대상 테스트가 33개 에러 | 테스트 픽스처는 `create_all`을 쓰므로 마이그레이션이 설치하는 확장(`vector`, `pg_trgm`)이 없다 — README대로 빈 테스트 DB를 만들면 바로 걸린다 | `ensure_extensions()`를 픽스처에 추가(권한이 없으면 무엇을 해야 하는지 알려주는 메시지로 실패) |
| 임베딩 차원 불일치가 SQLite에서 숨겨짐 | 테스트가 256차원 fake를 쓰는데 컬럼은 `vector(1024)`. SQLite(JSON)는 무엇이든 받아들여 통과하고, PostgreSQL에서만 배치 insert 도중 터졌다 | `ChunkIndexer`가 생성 시점에 컬럼 폭과 비교해 거부. 두 방언 모두에서 즉시, 이유가 담긴 오류로 실패한다 |

**결정 기록**
| 결정 | 이유 | 기각한 대안 |
|---|---|---|
| 임베딩 테이블 1개 + `model_id` 컬럼 (문서의 `paragraph_embeddings_{model_key}` 대신) | 차원이 다른 모델로 바꾸는 것은 **새 테이블 + 백필 + 전환**이라는 점은 그대로 유지하되(컬럼 폭은 마이그레이션에 고정), 동적 테이블명을 ORM에 넣지 않아 모델↔마이그레이션 diff 검사를 유지할 수 있다 | 모델별 테이블 자동 생성: 스키마 검사와 타입 검사를 모두 포기해야 한다 |
| 키워드 검색 = 용어 포함(LIKE) 가중 합, trigram GIN으로 가속 | PostgreSQL에 한국어 형태소 분석기가 없다. 사용자가 묻는 건 대부분 인물·장소 고유명사이고, 같은 SQL이 두 방언에서 동작한다 | pg_trgm similarity 정렬: 질문 전체와 청크의 trigram 유사도는 낮게 깔려 순위가 무의미 / BM25: 형태소 분석 도입 후 (Phase 8+) |
| 토큰 수는 추정(한글 1자≈1토큰, ASCII 4자≈1토큰) | 토크나이저는 모델마다 다르다. 특정 공급사의 BPE를 넣으면 다른 모델에 대해 거짓말을 하고 의존성도 무거워진다. 실제 수치는 공급사 usage로 돌아온다 | tiktoken: OpenAI 전용이라 한국어·Qwen 계열에 부정확 |
| 출력 검사는 "답변이 근거 밖에서 새로 꺼낸 용어"만 조회 | 컨텍스트에 있는 말은 정의상 허용된 말이다. 검사 대상이 보통 몇 개로 줄어 한 번의 DB 왕복으로 끝난다 | 답변 전체 토큰 조회: 매 질문마다 책 전체 스캔 |
| `LIGHT_SPOILER` = 듣고 있는 장의 끝까지 (잠정) | 문서가 "다음 장까지 요약 수준"을 제품 결정으로 남겼다. 코드는 보수적인 해석을 택하고 정의가 확정되면 한 함수만 바꾼다 | 다음 장 전체 허용: 제품 결정 없이 스포일러 범위를 넓히는 것 |
| 재시도·타임아웃만 래퍼로 구현, circuit breaker·metering은 Phase 12 | 지금 호출하는 코드가 없는 계층을 만들면 검증할 수 없다. `Usage`와 에러 타입은 이미 있어 sink만 붙이면 된다 | 지금 전부 구현: 실행·검증되지 않는 코드가 된다 |

**남은 확인** (공급사 계정 또는 실제 분량의 책이 필요)
- 실제 임베딩 모델로 의미 검색(패러프레이즈) recall 측정, `hnsw.iterative_scan` 필요 여부 실측 — 현재는 행이 적어 플래너가 필터 인덱스+정렬을 택한다
- 실제 LLM으로 "모른다" 비율과 답변 품질 측정, 프롬프트 v2 조정

## Phase 5 — LiveKit 🚧
**구현됨 (2026-09-16)**
- **로컬 LiveKit 서버**(`docker compose --profile realtime up -d livekit ai-agent`, `livekit/livekit-server:v1.13.7`). 클라우드 계정 없이 Talk 모드 전 구간을 검증할 수 있다 — 계정은 운영 배포 시점에 필요하다
- `POST /v1/realtime/token`: 세션 소유 확인 → 권리 재확인 → 최소 권한 토큰. room `rs_<session_id>` · identity `u_<user_id>` · TTL 10분 · **마이크 소스만** · metadata는 session_id만 · `max_participants=2` · explicit agent dispatch. 계정당 분당 한도
- LiveKit 키가 없으면 엔드포인트는 503 `realtime_unavailable`을 주고 **Listen 모드는 그대로 동작한다**. 운영에서는 개발 키(`devkey`)와 `ws://`를 거부
- `services/ai-agent` (신규 서비스): `livekit-agents` 1.8.2 워커, `agent_name="story-agent"`로 등록해 **명시적 dispatch만** 받는다. Phase 5 범위는 echo agent(받은 오디오를 그대로 돌려줌)이고 Phase 6에서 Story agent로 대체된다. 배포 시 drain 설정
- `story.v1` 데이터 채널 프로토콜을 **양쪽에 구현**: `story_core/realtime/protocol.py`와 `apps/mobile/src/features/talk/protocol.ts`. 알 수 없는 `type`과 알 수 없는 필드는 **무시**(앱 심사 지연 때문에 구버전 앱과 신버전 agent가 몇 주씩 공존한다), 깨진 envelope만 오류
- Mobile: `TalkTransport` 인터페이스 + LiveKit 구현(`livekit-client` + `@livekit/react-native-webrtc`) + `TalkController`(연결마다 새 토큰, 밀려난 시도 정리, 알 수 없는 메시지 무시) + 연결 상태 UI(`TalkControls`) + `expo-dev-client`. 마이크 권한 문구를 app.json에 선언
- 왕복 지연 측정 스크립트 `services/ai-agent/scripts/measure_roundtrip.py`

**검증됨:** story-core 143 · api 89 · worker 2 · ai-agent 6 · mobile 70 테스트, ruff·mypy strict·ESLint·tsc, expo-doctor 21/21, Metro 번들(1,186 모듈)
- [x] 실제 LiveKit 서버에 토큰으로 접속, room·identity·metadata 확인, **마이크 publish 성공 / 카메라 publish 서버 거부**
- [x] 명시적 dispatch 동작: 토큰 요청만으로 `story-agent` 워커에 job이 배정되고 agent가 room에 참가
- [x] **전송 왕복 p50 107 ms · p95 157 ms** (8/8회, 로컬 Docker). 측정 방법의 함정(클라이언트 큐 200 ms가 지연으로 잡혀 303 ms로 보임)은 [realtime.md §4.4](realtime.md#44-목표-지연-가설-실측-후-확정)에 기록
- [ ] **ASCII 경로로 repo 이전 후 Android/iOS 개발 빌드** — 한글 경로에서 Gradle이 실패하고, 이 환경에 Android SDK·Xcode가 없다
- [ ] iOS·Android 실기기에서 마이크 publish / agent audio 수신, 네트워크 전환(Wi-Fi↔LTE) 후 재연결

**Phase 5에서 발견한 것**
| 문제 | 원인 | 조치 |
|---|---|---|
| **모바일 훅 전체가 깨짐**(`Cannot read properties of null (reading 'useContext')`) | `@livekit/react-native`가 웹 패키지(`@livekit/components-react`)를 끌고 오고, 그 peer `react-dom: >=18`이 최신 react-dom을 설치한다. 그 react-dom의 peer가 `react ^19.3`이라 **React 사본 2개**가 생긴다(Expo는 19.2.3) | `react`·`react-dom`을 **워크스페이스 루트에 19.2.3으로 고정**. `overrides`로는 해결되지 않았다 — peer로 들어오는 의존성이라 npm이 무시한다. lockfile을 지우면 재현되므로 lock을 함부로 재생성하지 않는다 |
| agent worker 등록이 `unknown enum label "microphone"`으로 실패 | worker 권한은 protobuf enum(`TrackSource.MICROPHONE`)을 받는데, 토큰 grant는 소문자 문자열(`"microphone"`)을 받는다. 같은 개념에 어휘가 둘 | enum 값을 그대로 넘기고, 두 곳의 차이를 코드 주석·문서에 남김 |
| 오디오가 한 프레임도 흐르지 않는데 job은 살아 있음 | `JobContext.create_task`는 없다(AttributeError). LiveKit 이벤트 emitter가 핸들러 예외를 **로그만 남기고 삼켜서**, 오디오 경로 없이 job이 계속 돌았다 | `asyncio.create_task` + 강한 참조 유지, 핸들러 실패 시 job을 종료. 태스크 예외는 done 콜백으로 반드시 보고 |
| 로그가 모두 두 번 출력 | agents CLI가 루트 로거를 직접 설정하는데 우리도 루트를 교체했다 | `configure_logger(name, level)` 추가 — 우리 로거만 소유하고 propagate를 끊는다 |
| 공식 Expo 설정 플러그인을 못 씀 | `@livekit/react-native-expo-plugin` 1.0.2가 SDK **2.x**를 peer로 요구 (우리는 3.0.0) | 플러그인 없이 권한을 app.json에 직접 선언. 네이티브 빌드 단계에서 플러그인 버전 또는 SDK 버전을 다시 판단한다 |

**결정 기록**
| 결정 | 이유 | 기각한 대안 |
|---|---|---|
| 로컬 LiveKit 서버를 compose에 추가 | 클라우드 계정 없이 토큰·dispatch·왕복 지연을 **실제로** 검증할 수 있다. 계정은 배포 시점 문제로 미룬다 | 계정 발급까지 Phase 5 보류: 검증 없는 코드가 쌓인다 |
| `@livekit/react-native` 대신 `livekit-client` + `@livekit/react-native-webrtc` | 래퍼가 웹 React 트리를 끌고 와 Expo의 React와 충돌한다. 필요한 건 `registerGlobals`(webrtc 패키지에 있음)와 오디오 세션 설정(expo-audio의 `setAudioModeAsync`가 이미 이 프로젝트의 오디오 모드 담당) | 래퍼 유지 + React 이중 설치: 훅이 깨진다 / 2.x 다운그레이드: 같은 웹 패키지를 끌고 온다 |
| 토큰은 연결마다 새로 발급 | TTL 10분이라 재연결 시 죽은 토큰을 재사용하면 실패한다. 서버가 매번 권리·소유를 재확인하는 지점이기도 하다 | 토큰 캐시·갱신: 만료 경계에서 실패하고, 권리 취소가 즉시 반영되지 않는다 |
| echo agent를 `story.v1` 밖의 타입(`echo.ready`)으로 말하게 함 | echo agent는 낭독하지 않으므로 `state: READING`을 보내면 거짓이다. 동시에 "모르는 타입은 무시" 규칙을 실제로 검증한다 | 가짜 상태 전송: 클라이언트가 잘못된 상태를 믿게 된다 |

## Phase 6 — Realtime Story Agent 🚧
**구현됨 (2026-09-16)**
- `STTProvider`·`STTStream` 인터페이스(20ms PCM16 프레임, partial/final/speech_start) + 오프라인 구현. 오프라인 STT는 **말을 알아듣지 않고 "말하고 있음"만 감지**해서 스크립트를 순서대로 내보낸다 — 계정 없이 barge-in 트리거·partial 타이밍·에이전트 반응을 전부 돌릴 수 있다(운영에서는 거부)
- **IntentRouter**: 규칙(0ms) → 소형 분류기(150ms 예산, guided decoding) → 안전한 기본값. 규칙은 **짧은 발화만** 판단하고 애매하면 판단하지 않는다. "멈춰"가 들어간 긴 질문은 규칙이 손대지 않고, 분류기가 실패하면 `BOOK_QUESTION`으로 떨어진다(잘못 멈춘 낭독은 복구가 어렵고, 책에서 답한 질문은 복구가 쉽다). 같은 말도 상태에 따라 다르게 해석한다("응"은 `AWAITING_FOLLOWUP`에서만 ACK)
- **ClauseChunker**: LLM 토큰 스트림 → TTS가 말할 수 있는 절. 첫 절은 짧게 끊어 첫 음성을 빨리 내고, 이후는 길게 잡아 억양을 살린다. 한국어 종결부호와 연결어미(`~고`, `~지만`, `~는데`, `~해서`)를 경계로 쓰고, 경계가 없으면 문자 수 상한으로 지연을 묶는다
- **TalkSession**: 상태 머신이 상태를 소유하고 세션은 I/O만 한다. 사용자 이벤트 → `transition()` → effect 실행. LLM은 텍스트만 만들고 **재생을 건드리지 않는다**. 답변은 태스크라서 언제든 취소할 수 있고, 실제로 재생된 부분만 기록된다
- `story.v1` 메시지 송신(state·sentence·answer.delta·answer.done·error), 문장 단위 `SENTENCE_DONE` 보고(재개 위치가 들은 지점보다 뒤처지지 않게)
- 포트 4개(`Room`·`Narration`·`Speech`·STT)로 LiveKit·DB·시계를 분리 → 기기 없이 전체 흐름 테스트
- 어댑터: `LiveKitRoom`(20ms 프레임 공급, 큐 500ms로 제한, 마이크 리샘플링), `CachedNarration`(Phase 3 문장 캐시 재사용 — Talk와 Listen이 **같은 오디오**를 쓰고 합성비를 한 번만 낸다), `TtsSpeech`(cue 캐시), `question_asker`(Phase 4 QuestionService 재사용 → 스포일러 창·기록이 텍스트 질문과 동일)
- agent 엔트리포인트를 echo에서 Story agent로 교체. job은 **토큰을 신뢰하지 않는다**: metadata의 session_id로 세션을 DB에서 찾아 소유·처리 상태·권리를 다시 확인한다(만료된 라이선스로는 낭독할 수 없다)

**검증됨:** story-core 194 · api 89 · worker 2 · ai-agent 22 테스트, ruff·mypy strict 전부 통과
- [x] **질문 → 음성 답변 → 재개** 흐름을 가짜 포트로 검증: 낭독 중 발화 → USER_SPEAKING → 답변(절 단위 TTS, `answer.delta`) → READING 복귀
- [x] **재개 정확도**: 답변 후 첫 문장이 끊긴 그 문장이다(건너뛰지도, 반복하지도 않는다)
- [x] 재생 명령은 질문 경로에 도달하지 않는다("멈춰" → LLM·검색 호출 0회)
- [x] 답변 실패·알아듣지 못한 발화는 침묵이 아니라 cue(`ANSWER_FAILED`·`PARDON`)로 처리
- [x] 지연 마크 수집(speech_start → stt_final → intent_decided → answer_first_voice)
- [ ] **Docker 스택 E2E (질문 → 실제 음성 왕복)** — 아래 "환경 블로커"
- [ ] OTel span + trace 대시보드에서 구간별 p50/p95 — 마크는 수집·로그에 남지만 exporter와 대시보드는 아직 없다
- [ ] barge-in 2단계(duck → 확정), 오탐 처리 — Phase 7 범위

**환경 블로커 (사용자 조치 필요)**
Docker 스택 E2E를 실행하지 못했다. **C: 드라이브가 100% 찼고(0바이트)**, 그 상태에서 Docker의 이미지 저장소가 손상됐다:
`write /var/lib/docker/buildkit/.../metadata_v2.db: input/output error`, `blob ... input/output error`.
빌드·pull·prune이 모두 실패하고 기존 이미지(livekit)도 시작되지 않는다. npm·pip 캐시를 지워 2.2GB를 확보했지만 Docker 내부 저장소는 이미 깨져 있다. 복구는 Docker Desktop 수준의 조치가 필요하다 — 디스크 이미지를 D:로 옮기거나(이전에 한 번 했다), Docker Desktop의 데이터 정리 후 재-pull. 정리하면 개발 DB 볼륨이 사라지지만 `seed_sample_book.py`로 다시 만들 수 있다.

**Phase 6에서 발견해 고친 것**
| 문제 | 원인 | 조치 |
|---|---|---|
| 재개 위치가 최대 2문장 뒤처짐 | 낭독 루프가 lookahead 배치 단위로 `SENTENCE_DONE`을 보냈다 | 문장 단위로 보고. 남은 오차(전달했지만 아직 안 들린 오디오)는 Phase 7의 `client.playout`으로 보정 |
| 절 경계를 놓쳐 첫 음성이 늦어짐 | ClauseChunker가 버퍼 **끝**만 검사했다 — 한 번에 긴 델타가 오면 중간 경계를 못 본다 | 버퍼 전체에서 최소 길이 이후 첫 경계를 찾는다 |
| 필러 음절("음")이 분류기 호출을 유발 | 규칙 사전에 없어 LLM으로 떨어졌다 | 필러 집합을 규칙에 추가(UNCLEAR). 마이크가 가장 자주 잡는 소리에 모델 호출을 쓰지 않는다 |
| `STT_FAKE_SCRIPT`를 `.env`로 설정할 수 없음 | pydantic-settings가 tuple 필드를 JSON으로 먼저 파싱한다 | `NoDecode`(API가 같은 함정을 이미 그렇게 해결했다) + `.env.example`을 실제로 읽는 회귀 테스트 |

**결정 기록**
| 결정 | 이유 | 기각한 대안 |
|---|---|---|
| 세션은 포트 4개 뒤에서 동작 | 이 파일이 "언제 말하고, 언제 멈추고, 어디서 재개하는지"를 정한다. 기기·DB·시계 없이 전 경로를 테스트할 수 있어야 한다 | LiveKit·DB를 직접 호출: 실기기 없이는 검증 불가 |
| Talk 모드 낭독도 Phase 3 문장 캐시를 읽는다 | 같은 목소리·같은 문장이면 오디오도 같아야 하고, 합성비를 두 번 낼 이유가 없다 | agent가 따로 합성: 비용 2배 + 두 모드의 소리가 달라진다 |
| 음성 질문도 Phase 4 `QuestionService`를 그대로 쓴다 | 스포일러 창·근거 기록·권리 검사가 입력 방식에 따라 달라지면 안 된다 | agent용 별도 RAG 경로: 보안 규칙이 두 곳으로 갈라진다 |
| 오프라인 STT는 "말하고 있음"만 감지 | 계정 없이 barge-in 트리거와 타이밍을 검증할 수 있다. 인식 품질은 실제 제공사만 낼 수 있다 | 음성 인식 모델 내장: 무거운 의존성 + 한국어 품질 미지 |
| 분류기 실패 시 `BOOK_QUESTION` | 잘못 멈춘 낭독은 사용자가 고치기 어렵고, 책에서 답한 질문은 다시 물으면 된다 | UNCLEAR로 되묻기: 실제 질문에 "다시 말해줄래요?"를 반복하면 대화가 끊긴다 |

## Phase 7 — Barge-in + Resume ⭐ 핵심 UX
- InterruptionManager (duck → 확정 → 정지, false interruption 복귀, 버튼 인터럽트)
- AWAITING_FOLLOWUP, ResumeManager, 연결 멘트 캐시
- Python 봇 클라이언트 E2E (녹음된 질문을 임의 시점에 주입)
- 오탐 코퍼스 테스트
- 종료 조건 (실측): 인터럽트 정지 p95, 재개 위치 정확도 100%(문장 단위), false interruption 비율 목표치 — 첫 측정 후 수치 확정

## Phase 8 — Scene Engine
- SceneAnalyzer(구조화 LLM 출력), SceneDetector(점수 규칙), Character Bible(+revealed_at_seq), PromptBuilder
- 관리자 검수 도구(최소: scene 경계·bible 수정)
- 종료 조건: 라벨링된 책 기준 boundary F1 측정, scene 전환 이벤트가 앱으로 전달

## Phase 9 — Scene Image
- `ImageProvider` + reference image, `CachedImage`, 안전 필터, CDN signed URL
- 선생성 작업 + 첫 사용 시 생성 fallback
- Mobile: scene 이미지 cross-fade, prefetch
- 종료 조건: 낭독 중 이미지 생성 API 호출 0회(선생성 책), 캐시 키 무효화 테스트

## Phase 10 — Voice Clone
- 동의 화면·버전 관리, 본인 확인 스크립트, 녹음·품질 검사, `VoiceProvider`
- 개인 목소리 lookahead TTS, 삭제 파이프라인(provider·샘플·파생 오디오)
- ⚖️ 법률 검토 완료가 선행 조건
- 종료 조건: 등록 → 내 목소리 낭독 → 삭제 후 provider·스토리지·캐시에 흔적 없음(통합 테스트)

## Phase 11 — Background Audio
- iOS background audio + lock screen, Android foreground service + MediaSession
- 백그라운드 진입 시 Talk → Listen 자동 전환
- 실기기 매트릭스 테스트 ([mobile-architecture.md §8](mobile-architecture.md#testing))
- 종료 조건: 화면 꺼짐 30분 연속 낭독, 전화 수신·블루투스 해제 후 정상 복귀

## Phase 12 — Subscription + Production Hardening
- IAP / Google Play Billing + 서버 영수증 검증, plan_limits, 사용량 한도(Redis 카운터)
- usage_records 비용 대시보드, RoutedLLMProvider(대체 provider)
- Sentry + OTel collector, 알림, rate limit 조정, JWT `kid` 회전, secret scan CI
- 백업 복원 리허설, 보관기간 배치, 이메일 인증, 계정 연결, Push(FCM/APNs)
- IaC(Terraform 등), staging 환경, 부하 테스트(동시 Talk 세션)
- 종료 조건: 보안 체크리스트([security.md](security.md)) 전 항목 완료, 스토어 심사 제출 가능

## Phase 13 — 자체 LLM 학습 파이프라인
- `training_examples` + 라벨링 도구, `scripts/export_training_data.py`
- `models/llm/`: SFT/LoRA/QLoRA 설정 (학습 프레임워크는 이 시점에 최신 안정판 확인 후 선택)
- vLLM 배포 설정 (LoRA adapter serving), 오프라인 평가 → shadow → 롤아웃
- 종료 조건: 동의 없는 대화가 export되지 않음(테스트), 파인튜닝 모델이 평가셋에서 기준 모델 대비 개선
