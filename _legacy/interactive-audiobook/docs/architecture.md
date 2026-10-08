# Architecture — AI Interactive Audiobook

> 작성일: 2026-09-15 · 상태: Phase 0 확정안 (Phase 1 구현 반영)
> 관련 문서: [roadmap](roadmap.md) · [database](database.md) · [realtime](realtime.md) · [ai-architecture](ai-architecture.md) · [mobile-architecture](mobile-architecture.md) · [security](security.md) · [provider-abstraction](provider-abstraction.md)

이 문서는 "상용 서비스로 확장 가능한 구조인가"를 검증하는 것이 목적이다. 요구사항을 그대로 옮기지 않고, 요구사항에 있던 구조 중 **실제로 동작하지 않거나 비용·정책상 위험한 부분을 수정**했다. 수정 사항은 §3에 모았다.

---

## 1. 현재 상태 분석

### 1.1 Repository

| 위치 | 내용 | 이 프로젝트와의 관계 |
|---|---|---|
| `Desktop/클로드작업/` | hs-portal, edu_shorts_generator 등 | **무관**. 오디오북 코드 없음 |
| `Desktop/봇/main.py` (163줄) | 기존 Python 프로토타입 | 개념 참고용 |
| `Desktop/봇/aa.py` | base64로 테스트용 epub 생성 | 폐기 |
| `Desktop/봇/self_intro.epub` | 1장짜리 샘플 epub | 테스트 fixture로 쓰지 않음 (개인 소개글) |

따라서 새 monorepo `interactive-audiobook/`을 새로 만든다. git 이력, 의존성, 실행 방법으로 이어받을 것은 없다.

### 1.2 개발 환경 (2026-09-15 확인)

| 항목 | 상태 | 영향 |
|---|---|---|
| Python | 3.13.3 | backend 기준 버전 3.13 |
| Node / npm | 22.17.1 / 10.9.2 | npm workspaces 사용 (pnpm 미설치) |
| Docker | **없음** | `docker-compose.yml`은 작성하지만 로컬 검증 불가 → PostgreSQL 통합 테스트는 Docker 있는 환경/CI에서 실행 |
| PostgreSQL / Redis | 없음 | 로컬 단위·API 테스트는 SQLite(aiosqlite) + fakeredis로 실행, PG 전용 기능(pgvector)은 PG 테스트로 분리 |
| GPU | 없음 | vLLM 자체 추론은 원격 GPU 전제. 초기에는 OpenAI-compatible 원격 endpoint |
| macOS | 없음 | iOS 빌드는 EAS Build(클라우드) 또는 별도 Mac 필요 |
| 경로 | `클로드작업` (비ASCII) | **Android Gradle은 Windows 비ASCII 경로에서 빌드 실패 사례가 많다.** 네이티브 빌드(Phase 5~) 전에 ASCII 경로(예: `C:\dev\interactive-audiobook`)로 옮길 것 |

### 1.3 기존 프로토타입 (`봇/main.py`) 분석

요구사항 문서는 프로토타입이 `Bard / pygame / gTTS`를 쓴다고 했지만, **실제 코드는** `huggingface_hub.InferenceClient`(Command R+), `RealtimeSTT`(Whisper + pvporcupine wake word), `RealtimeTTS`(`SystemEngine`)를 쓴다. 두 가지 모두 대응표에 넣었다.

| 프로토타입 요소 | 실제 동작 | 문제 | 새 시스템 대응 |
|---|---|---|---|
| `RecognizeThread` + `AudioToTextRecorder` | 로컬 마이크, Whisper `base`, 문장 끝 콜백 | 문장마다 recorder(모델 로드)를 새로 만든다 → 수 초 지연. 로컬 PC 전용 | `STTProvider.stream()` (streaming) + LiveKit 마이크 트랙 |
| wake word `"파이리"` (pvporcupine) | Picovoice AccessKey·한국어 커스텀 키워드 필요한데 코드에 없음 → 사실상 동작 불가 | 필수 wake word는 UX 장벽 | `WakeWordEngine` 인터페이스(옵션). 기본은 VAD barge-in + 버튼 + "잠깐" 키워드 |
| `play_text` (`SystemEngine`) | OS 기본 TTS, 폴링 루프로 중단 | 품질 낮음, 중단 지연 100ms 폴링, 캐시 없음 | `TTSProvider` + 오디오 캐시 + `NarrationPlayer`(모바일) / LiveKit 오디오 트랙 |
| `conversation()` | 스레드 2개 + 전역변수 + `stop_flag` | 상태가 전역변수에 흩어져 있어 재개 위치 추적 불가 | `StoryAgent` + `ReadingStateMachine` + `RealtimeSession` |
| `break_sentence` | `. ! ?` 기준 분리 + 50자 공백 분할 | 한국어 문장 경계(따옴표, 말줄임표, `다.` 등) 미흡 | `SentenceSplitter`(규칙 + kss/kiwi 계열 평가 후 선택) — Phase 2 |
| `read_ebook` | `html2text`로 전체를 한 문자열로 | Chapter/Paragraph 구조 소실 | `EpubParser` → Book/Chapter/Section/Paragraph/Sentence |
| `client.chat.completions.create(...)` | **책 원문을 읽지 않고 LLM이 만든 "요약 소개글"을 낭독** | 핵심 요구(원문 낭독)와 다르다. `raw_text[:100000]`로 책 전체를 context에 넣는다 | 원문은 DB에서 낭독, LLM은 질문 답변에만 사용. RAG로 필요한 부분만 context에 넣는다 |
| 답변 프롬프트 `"{user_input}? 아주 간단히 한줄로"` | 책 문맥 없이 질문만 전달 | 책 기반 답변이 아니다 | `ContextBuilder`(현재 위치 + RAG + 대화 기록) |
| `re.sub(r'[^\w\s]', '', ...)` | 문장부호 제거 | TTS 억양(의문·감탄·쉼)이 망가진다 | 원문 그대로 TTS에 보내고, SSML 정규화는 provider 어댑터가 담당 |
| 답변 후 `"아까 이야기 하던 것을..."` 후 같은 문장 재낭독 | 문장 단위 재개 | **이 UX 방향은 맞다** → 유지 | `ResumeManager`: 끊긴 문장 처음부터 재개 + 캐시된 연결 멘트 |
| `InferenceClient(api_key='hf_...')` | **API 토큰이 코드에 하드코딩됨** | 보안 사고. 새 repo로 옮기지 않았다 | 모든 secret은 backend 환경변수/secret manager |
| Command R+ | CC-BY-NC 계열 라이선스 (비상업) | **상용 서비스에 사용 불가** | 상용 허용 라이선스 모델만 후보 (§5) |
| Bard / pygame / gTTS (요구서 기준) | — | Bard API는 폐지, gTTS는 비공식 엔드포인트 | `LLMProvider` / RN 오디오·LiveKit / `TTSProvider` |

**재사용하는 것:** 개념 흐름(낭독 → 끼어듦 → 답변 → 같은 문장부터 재개), 연결 멘트 UX.
**폐기하는 것:** 코드 전부 (스레드 모델, 전역 상태, 로컬 오디오, 하드코딩 키, 비상업 모델).

> ⚠️ **즉시 조치 필요:** `봇/main.py` 108줄의 Hugging Face 토큰은 이미 노출된 것으로 보고 huggingface.co → Settings → Access Tokens에서 **폐기(revoke)** 해야 한다.

---

## 2. 요구사항 대비 차이 (Gap)

기존 코드에는 서버, DB, 인증, 모바일, 실시간 미디어, RAG, Scene, 캐시, 관측성이 **하나도 없다**. 모든 기능이 신규 구현 대상이고, 실행 순서는 [roadmap.md](roadmap.md)에 있다.

---

## 3. 설계 검증 — 요구사항 구조에서 바꾼 부분

요구 문서의 다이어그램을 그대로 구현하면 문제가 되는 지점들이다.

### 3.1 "AI Story Agent = FastAPI"는 맞지 않다 → **Agent는 별도 worker 프로세스**

실시간 음성 agent는 HTTP 요청-응답이 아니라 **LiveKit room에 참가자로 붙어서 수십 분 동안 오디오 스트림을 처리하는 장기 실행 프로세스**다. FastAPI 요청 핸들러 안에 두면 배포(롤링 재시작 시 대화 끊김), 스케일링(요청 수가 아니라 동시 세션 수 기준), 타임아웃 모델이 모두 맞지 않는다.

- `services/api` (FastAPI): **control plane** — 인증, 책/세션 CRUD, LiveKit 토큰 발급, 업로드, 구독.
- `services/ai-agent` (LiveKit Agents worker): **media plane** — room 참가, VAD/STT/Intent/RAG/LLM/TTS, 상태 머신. health 확인용 HTTP만 연다.
- `services/worker` (작업 큐): 책 파싱, 임베딩, Scene 분석, 이미지·TTS 선생성, 삭제 작업.
- 세 서비스가 공유하는 도메인 코드(ORM 모델, repository, provider, 상태 머신)는 Python 패키지 `packages/story-core`로 뽑는다 (Phase 2에서 worker가 생길 때 분리. Phase 1에는 api만 존재).
- `services/realtime`에는 코드를 두지 않는다. LiveKit 서버 설정은 `infrastructure/livekit`에 둔다.

### 3.2 모든 낭독을 LiveKit으로 흘리면 안 된다 → **재생 모드 2개**

| | **Listen 모드** (기본) | **Talk 모드** (대화형) |
|---|---|---|
| 낭독 오디오 | 캐시된 문장/문단 오디오 파일을 기기에서 재생 (`expo-audio`) | agent가 LiveKit 오디오 트랙으로 송출 |
| 질문 방법 | 🎙 버튼 / 잠금화면 버튼 → Talk 모드로 전환 | 음성으로 바로 끼어들기 (VAD barge-in) + 버튼 |
| 백그라운드·화면 꺼짐 | ✅ 지원 (iOS Background Audio, Android Foreground Service) | 포그라운드 기준. 백그라운드는 정책 제약 (§[mobile](mobile-architecture.md#background)) |
| 서버 비용 | 캐시 적중 시 CDN 비용만 | 청취 시간 내내 agent + LiveKit 분 단위 비용 |
| 오프라인 | 다운로드한 오디오로 가능 (향후) | 불가 |

**이유:**
1. **에코 제거(AEC):** 음성 barge-in은 마이크가 계속 열려 있어야 한다. 낭독을 별도 플레이어로 재생하면 OS의 음성 처리 AEC가 그 소리를 기준 신호로 모른다. 스피커의 낭독 소리가 마이크로 들어가 **AI가 자기 목소리에 끊기는** 문제가 생긴다. WebRTC 오디오 경로로 재생해야 AEC가 동작한다.
2. **비용:** 오디오북은 청취 시간이 길다. 모든 청취 분을 실시간 agent가 처리하면 원가가 청취 시간에 비례해 커진다.
3. **OS 정책:** 화면이 꺼진 상태에서 마이크를 계속 열어 두는 것은 iOS/Android 심사와 배터리 면에서 위험하다.

사용자 입장에서는 하나의 플레이어로 보이게 한다. 두 모드 모두 **같은 ReadingPosition**을 공유하고, 모드 전환 시 위치를 넘겨받는다.

### 3.3 Scene Engine은 실시간 경로가 아니다 → **오프라인 파이프라인 + 위치 조회**

요구 다이어그램은 Scene Engine이 LLM 아래 실시간 흐름에 있다. 실제로는:
- 책 등록 시 worker가 Scene을 분석·분할하고 이미지를 선생성한다.
- 낭독 중에는 `paragraph → scene_id` **조회만** 한다 (DB/Redis). 이미지는 CDN URL이다.
- 실시간으로 LLM을 호출하는 것은 "이 장면 설명해줘" 같은 **장면 질문**뿐이다.

### 3.4 스포일러 방지는 프롬프트가 아니라 **쿼리에서 강제**한다

- 모든 원문 단위에 전역 순번 `global_seq`를 둔다. 검색 쿼리에 `WHERE global_seq <= :reader_seq`를 **repository 계층에서 강제**한다. LLM에게 "스포일러하지 마"라고 부탁하는 방식에 의존하지 않는다.
- **파생 데이터도 스포일러를 품는다.** 책 전체를 보고 만든 Character Bible("나중에 왕이 된다")이나 요약이 그렇다. 캐릭터 사실·요약에 `revealed_at_seq`를 저장해 같은 필터를 적용한다.
- LLM이 **사전학습으로 이미 아는 유명 작품의 결말**은 쿼리로 막을 수 없다 → 출력 검사(현재 위치 이후에 처음 등장하는 고유명사가 답변에 있으면 재생성/차단)를 둔다. 완벽하지 않으므로 잔여 위험으로 기록한다 (§6).

### 3.5 세션 상태는 **단일 작성자(single writer)**

Talk 모드 중에는 agent가 세션 상태의 유일한 작성자다. 모바일의 REST `PATCH /reading/sessions/{id}`(일시정지 등)가 DB를 직접 바꾸면 agent의 메모리 상태와 어긋난다(split-brain).
- agent가 연결된 세션: 제어 명령은 LiveKit data channel(또는 Redis pub/sub)로 agent에 전달하고, **agent가 상태 머신을 통해** 반영한다.
- agent가 없는 세션(Listen 모드): API가 작성자다.
- 위치 갱신에는 `position_version`(단조 증가)을 넣어 낙관적 동시성 제어를 한다 → 다기기 충돌을 감지한다.

### 3.6 TTS 캐시 키에 **텍스트 해시와 모델 버전**이 필요하다

요구안 키 `book_id + paragraph_id + voice_id + speed + emotion`만 쓰면, 원문 교정이나 TTS 모델 업그레이드 후 **옛 오디오가 계속 재생**된다.
→ `sha256(provider | model_version | voice_id@voice_version | normalized_text | speed | emotion | format)`. `book_id/paragraph_id`는 조회·삭제용 인덱스로만 쓴다. ([provider-abstraction.md](provider-abstraction.md#cache))

Scene 이미지 키도 같은 원칙이다: `book_id + scene_id + style + character_bible_version + prompt_hash + model_version`.

### 3.7 개인 목소리 낭독은 **비용 구조가 다르다**

기본 목소리 오디오는 책당 1회 생성하면 모든 사용자가 캐시를 공유한다. 사용자 목소리는 **사용자 × 책**마다 생성해야 해서 캐시 공유가 안 된다. 따라서:
- 책 전체 선생성 금지. 재생 위치 앞 N문장만 lookahead 생성한다.
- 사용량 한도와 플랜으로 묶는다 (Premium).
- 목소리 삭제 시 파생 오디오 캐시도 함께 삭제한다 (목소리에서 파생된 개인 데이터).

### 3.8 LLM은 재생 상태를 바꾸지 못한다

Intent Router의 출력은 **enum 명령**(`PAUSE`, `RESUME`, `SEEK_BACK_SENTENCE` 등)이다. 상태 머신이 이를 검증한 뒤 전이한다. LLM이 자유 텍스트나 tool call로 위치를 조작하는 경로는 두지 않는다.

---

## 4. 시스템 구조

```mermaid
flowchart TB
  subgraph Client["React Native App (iOS/Android)"]
    UI[Screens / Zustand / React Query]
    NP[NarrationPlayer<br/>expo-audio · background]
    RT[RealtimeClient<br/>@livekit/react-native]
  end

  subgraph Edge
    CDN[(CDN<br/>signed URLs)]
    LK[LiveKit<br/>SFU / TURN]
  end

  subgraph ControlPlane["services/api (FastAPI)"]
    AUTH[Auth / Users]
    BOOKS[Books / Reading Sessions]
    TOKEN[Realtime token]
    VOICE[Voice profiles / consent]
    USAGE[Usage / Subscriptions]
  end

  subgraph MediaPlane["services/ai-agent (LiveKit Agents worker)"]
    SM[ReadingStateMachine]
    IM[InterruptionManager<br/>VAD · ducking]
    IR[IntentRouter]
    CB[ContextBuilder + Retriever]
    RM[ResumeManager]
  end

  subgraph Async["services/worker (queue)"]
    ING[Ingestion<br/>parse · split · embed]
    SCN[Scene Engine<br/>detect · bible · prompt]
    PRE[Pre-render<br/>TTS · images]
    DEL[Deletion jobs]
  end

  subgraph Providers["providers (interfaces)"]
    STT[STTProvider]
    LLM[LLMProvider]
    EMB[EmbeddingProvider]
    TTS[TTSProvider]
    VP[VoiceProvider]
    IMG[ImageProvider]
    ST[StorageProvider]
  end

  PG[(PostgreSQL + pgvector)]
  RD[(Redis<br/>hot state · rate limit · queue)]
  OBJ[(S3 / R2<br/>private buckets)]

  UI -->|HTTPS REST| ControlPlane
  NP -->|HTTPS| CDN
  RT <-->|WebRTC audio + data| LK
  LK <--> MediaPlane
  TOKEN -.->|JWT grant + agent dispatch| LK
  ControlPlane --> PG & RD
  ControlPlane -->|enqueue| RD
  RD --> Async
  MediaPlane --> PG & RD
  MediaPlane --> STT & LLM & TTS & EMB
  Async --> LLM & EMB & TTS & IMG & ST & PG
  VOICE --> VP & ST
  ST --> OBJ
  CDN --> OBJ
```

### 4.1 서비스 책임

| 서비스 | 책임 | 스케일 단위 | 상태 |
|---|---|---|---|
| `apps/mobile` | UI, 로컬 재생, 토큰 보관, LiveKit 클라이언트 | — | 서버 상태 사본만 보유 |
| `services/api` | REST, 인증, 권한, 토큰 발급, 큐 등록 | RPS | stateless |
| `services/ai-agent` | 실시간 대화 세션 (room당 1 agent job) | 동시 Talk 세션 수 | 세션 메모리 + Redis 체크포인트 |
| `services/worker` | 무거운 비동기 작업 | 큐 길이 | stateless |
| PostgreSQL | 원본 데이터, 벡터, 위치 영속화 | — | 백업 대상 |
| Redis | 세션 hot state, rate limit, 작업 큐, 분산 락 | — | 유실 허용 (PG에서 복구) |
| S3/R2 | 원본 epub, 오디오, 이미지, 음성 샘플 | — | private bucket, lifecycle 정책 |

### 4.2 Monorepo

```text
interactive-audiobook/
├── apps/mobile/                 # Expo (CNG) React Native app
├── services/
│   ├── api/                     # FastAPI control plane          [Phase 1 ✅]
│   ├── ai-agent/                # LiveKit Agents worker          [Phase 6]
│   └── worker/                  # ingestion / scene / pre-render [Phase 2 ✅]
├── packages/
│   ├── shared-types/            # OpenAPI → TypeScript 생성 타입   [Phase 1 ✅]
│   ├── api-client/              # 타입 안전 fetch client + refresh [Phase 1 ✅]
│   ├── config/                  # 공유 tsconfig                   [Phase 1 ✅]
│   └── story-core/              # Python 공유 도메인·provider      [Phase 2 ✅]
├── infrastructure/{docker,postgres,redis,livekit}/
├── models/{llm,embeddings,voice}/   # 학습 설정·평가셋 (가중치는 git 밖) [Phase 10+]
├── scripts/ · tests/ (cross-service e2e) · docs/
├── .env.example · docker-compose.yml · README.md
```

요구안의 `services/realtime`은 코드가 없는 서비스라 만들지 않았다 (§3.1).

---

## 5. 기술 선택과 이유

버전은 **2026-09-15에 npm registry / PyPI / Docker Hub에서 직접 확인한 최신 안정 버전**이다. 모바일은 Expo SDK 57이 고정하는 호환 버전을 따른다 (`npx expo install`).

### 5.1 Mobile

| 선택 | 버전 | 이유 | Trade-off / 대안 |
|---|---|---|---|
| Expo SDK (CNG, prebuild) | 57 (RN 0.86.3, React 19.2.3) | iOS/Android 단일 코드, config plugin으로 네이티브 설정(권한·백그라운드 모드)을 코드로 관리, EAS Build로 Mac 없이 iOS 빌드 | Expo Go에서는 LiveKit 불가 → Phase 5부터 `expo-dev-client` 개발 빌드 사용. RN CLI 대비 네이티브 수정은 config plugin으로만 해야 한다 |
| TypeScript | 6.0 (SDK 57 템플릿 기준) | strict 모드 | npm 최신 7.0(Go 네이티브 컴파일러)은 Expo/Babel 도구체인 호환이 검증되지 않아 사용하지 않음 |
| React Navigation | 7.x | 요구사항, 네이티브 스택 성능 | Expo Router(파일 기반)도 가능하지만 요구사항 우선 |
| Zustand | 5.x | 클라이언트 UI 상태, 보일러플레이트 적음 | 서버 상태는 넣지 않는다 |
| TanStack Query | 5.x | 서버 상태 캐시·재시도·무효화 | — |
| 스타일 | **StyleSheet + 타입 있는 theme token** | NativeWind 최신 안정판 4.2.7은 Tailwind v3에 묶여 있고, v5는 아직 RC(`5.0.0-rc.0`). 상용 앱 초기에 babel/metro 변환 계층을 추가하는 위험보다 의존성 0의 토큰 시스템이 낫다 | 클래스 문법 생산성 포기. NativeWind 5 안정화 후 도입 재검토 (토큰은 그대로 Tailwind theme으로 옮길 수 있다) |
| 낭독 재생 | `expo-audio` | SDK 57 문서 기준 background playback, lock screen(`setActiveForLockScreen`), playlist, Android foreground service를 config plugin으로 지원. SDK와 함께 유지보수된다 | `react-native-track-player` 4.1.2는 더 성숙한 큐·미디어세션 기능이 있지만 New Architecture 지원 이력이 불안정. `NarrationPlayer` 인터페이스 뒤에 두고 Phase 3에서 `expo-audio`로 확정 ✅ (인터페이스가 있어 교체 비용은 작다) |
| 실시간 | `@livekit/react-native` 3.0.0 + expo plugin 1.0.2 | WebRTC AEC/NS/AGC, 재연결, TURN | 개발 빌드 필수 |
| 토큰 저장 | `expo-secure-store` | Keychain / Android Keystore | 값 크기 제한(iOS ~2KB) → refresh token은 짧은 opaque 문자열로 설계 |

### 5.2 Backend

| 선택 | 버전 | 이유 |
|---|---|---|
| FastAPI | 0.141.1 | async, Pydantic 통합, OpenAPI 자동 생성 → 모바일 타입 생성 |
| Pydantic / pydantic-settings | 2.13 / 2.15 | 검증, 환경변수 설정 |
| SQLAlchemy (async) + asyncpg | 2.0.53 / 0.31 | 파라미터 바인딩(SQL injection 방지), 마이그레이션 생태계 |
| Alembic | 1.20 | 스키마 버전 관리 |
| PostgreSQL + pgvector | `pgvector/pgvector:0.8.6-pg18-trixie` | 원문·메타·벡터를 한 DB에 → 스포일러 필터(`global_seq`)와 벡터 검색을 **한 쿼리**로. 별도 벡터 DB는 동기화 문제만 늘린다 |
| Redis | 8.8.2 | rate limit, 세션 hot state, 큐 |
| 작업 큐 | **Taskiq 0.12 + Redis Streams** (Phase 2 확정) | asyncio 네이티브, ack 기반 at-least-once. arq(maintenance-only, `redis<6`)·SAQ(`redis<8`)는 redis-py 8과 충돌해 기각 ([roadmap 결정 기록](roadmap.md#phase-2--book-engine--readingsession-)) |
| 인증 | 자체 JWT(access 15분) + opaque rotating refresh token, argon2id | Apple/Google은 ID token 검증 방식으로 붙인다. 외부 IdP SaaS 없이 시작하되 `IdentityTokenVerifier`로 교체 가능 |
| LiveKit server | `livekit/livekit-server:v1.13.7` / LiveKit Cloud | 개발·초기는 Cloud(TURN·글로벌 엣지 운영 부담 제거), 규모 확인 후 self-host 검토 |
| LiveKit Agents (Python) | 1.8.1 | VAD(Silero), turn detection, 인터럽션 옵션(`min_duration`, `false_interruption_timeout`, `resume_false_interruption`), `session.interrupt()` 제공. **단 낭독은 LLM 턴이 아니므로 오케스트레이션은 자체 `StoryAgent`가 담당**하고 프레임워크는 전송·VAD·worker 수명주기에 쓴다 ([realtime.md](realtime.md)) |
| 관측성 | Sentry (sentry-sdk 2.x) + OpenTelemetry 확장 | 에러는 Sentry, 지연 추적은 OTel span. PII 전송 끔 |

### 5.3 AI (전부 provider 인터페이스 뒤)

| 역할 | 초기 후보 | 비고 |
|---|---|---|
| LLM | Qwen3 계열 (Apache-2.0) via OpenAI-compatible endpoint → 자체 vLLM | 한국어 품질·라이선스 균형. Llama(커뮤니티 라이선스·AUP), Gemma(Gemma Terms)는 조건 검토 후. 국내 공개 모델은 **라이선스별 상용 허용 여부 재확인 필요** |
| Embedding | BGE-M3 (MIT), Qwen3-Embedding (Apache-2.0) | 한국어 다국어 성능. 모델별 차원이 달라 임베딩 테이블은 모델별로 분리 ([database.md](database.md)) |
| STT (streaming, ko-KR) | Azure Speech, Google Cloud STT, Deepgram, RTZR(리턴제로), self-hosted Whisper 계열 | Whisper는 원래 streaming 모델이 아니므로 streaming wrapper의 지연·정확도를 측정해야 한다. **한국어 partial 결과 지연**이 선택 기준 |
| TTS (streaming) | Azure Speech ko-KR neural, ElevenLabs, Google, 국내 TTS | 기준: 한국어 자연스러움, 첫 오디오 지연, 문장 단위 캐시 허용 약관 |
| Voice clone | ElevenLabs 등 (동의 절차가 있는 provider 우선) | 캐시·재배포 허용 범위, 목소리 삭제 API, 동의 증빙 요구사항을 계약 전에 확인 |
| Image | 레퍼런스 이미지 입력을 지원하는 모델/API | 캐릭터 일관성은 프롬프트만으로는 약하다 → `reference_images` 필수 지원. FLUX.1-dev 등 **비상업 가중치는 제외** |

---

## 6. 위험 요소와 기술적 한계

| # | 위험 | 영향 | 대응 | 잔여 위험 |
|---|---|---|---|---|
| R1 | **콘텐츠 권리.** 전자책 판매 계약에는 보통 오디오화(2차적 저작물)·AI 처리 권리가 없다. 외부 LLM/TTS에 원문을 보내는 것도 라이선스 조건에 걸릴 수 있다. 예시의 『모모』(미하엘 엔데, 1995년 사망)도 보호기간 내 저작물이다 | 서비스 불가 | `book_rights` 필수 입력, 권리 없으면 처리 파이프라인 차단. 초기 콘텐츠는 저작권 만료작 또는 오디오·AI 처리 권리를 명시한 계약작 | 법률 검토 필요 |
| R2 | **목소리 데이터 규제.** 음성 복제용 음성은 개인정보보호법상 민감정보(생체인식정보)로 볼 여지가 있다. 타인 목소리 도용 시 퍼블리시티권·사칭 문제 | 규제·평판 | 별도 동의, 본인 확인 스크립트 낭독, 원본 암호화·보관기한, 삭제 전파 ([security.md](security.md)) | 법률 검토 필요 |
| R3 | **AI 생성물 표시 의무.** 「인공지능 기본법」(2026년 시행)의 생성형 AI 고지·표시 의무 적용 범위 | 규제 | 앱 내 AI 생성 고지, 이미지 메타데이터 표기 준비 | 시행령 확인 필요 |
| R4 | **Barge-in 오탐/미탐.** 맞장구("응"), TV 소리, 에코로 낭독이 끊기거나, 작은 목소리를 놓친다 | 핵심 UX 붕괴 | Talk 모드는 WebRTC AEC 경로, 즉시 ducking 후 확정 시 정지, false-interruption 복귀, 버튼 fallback | 소음 환경 한계. 실측으로 임계값 조정 |
| R5 | **왕복 지연.** 발화 종료 → 답변 첫 음성 = endpointing + STT + RAG + LLM TTFT + TTS 첫 오디오 + 네트워크 | 대화감 저하 | 모든 구간 trace, 연결 멘트 캐시 오디오, 짧은 답변 우선, 가까운 리전 | 한국 리전 GPU/provider 가용성에 의존 |
| R6 | 한국어 문장 분리·형태소 처리 품질 | 재개 위치·검색 품질 | 평가셋 기반 선택, 규칙+라이브러리 조합 | — |
| R7 | LLM 사전지식에 의한 스포일러 | 신뢰 | 쿼리 필터 + 출력 고유명사 검사 | 완전 차단 불가 |
| R8 | 캐릭터 이미지 일관성 | 몰입 저하 | Character Bible + reference image + 스타일 고정 + 사람 검수 | 모델 한계 |
| R9 | Talk 모드 원가 (청취 분 × agent/LiveKit/STT) | 수익성 | Listen 기본, 대화 시에만 Talk 전환 옵션, 유휴 시 room 종료, 플랜별 한도 | 사용 패턴 측정 필요 |
| R10 | 개인 목소리 TTS 원가 (§3.7) | 수익성 | lookahead 생성, Premium 한정, 자체 TTS 전환 경로 | — |
| R11 | iOS 백그라운드 마이크 / 심사 | 리젝 | 백그라운드에서는 Talk 모드 음성 감지 비활성, 잠금화면 버튼으로만 질문 시작 | — |
| R12 | Windows 비ASCII 경로 Android 빌드 실패 | 개발 지연 | ASCII 경로 이전 | — |
| R13 | 로컬에 Docker·PG 없음 → PG 전용 동작 미검증 | 운영 버그 | PG 통합 테스트 CI 필수, Phase 2 전 Docker 환경 확보 | Phase 1은 SQLite로 검증 |

---

## 7. 외부 API / 서비스 목록

| 분류 | 서비스 | 필요 시점 | 비고 |
|---|---|---|---|
| 앱 배포 | Apple Developer Program, Google Play Console | Phase 5 (개발 빌드 기기 설치) | Apple Sign In, APNs, IAP 포함 |
| 빌드 | Expo EAS Build | Phase 5 | Mac 없이 iOS 빌드 |
| 인증 | Sign in with Apple, Google Identity (OAuth client IDs) | Phase 1 코드 준비, 키는 배포 전 | backend는 ID token만 검증 |
| 실시간 | LiveKit Cloud (또는 self-host + TURN) | Phase 5 | |
| LLM | OpenAI-compatible hosted open model endpoint → GPU 클라우드 vLLM | Phase 4 | 어댑터·재시도·오프라인 fake 구현 완료 ✅, 계정만 남았다 |
| Embedding | 동일 endpoint 또는 self-host | Phase 4 | 어댑터 구현 완료 ✅. 차원은 `EMBEDDING_DIMENSIONS`(1024)에 고정되고, 다른 차원의 모델은 새 테이블 + 백필 |
| STT | 한국어 streaming STT 1곳 + 대체 1곳 | Phase 6 | |
| TTS | 한국어 streaming TTS 1곳 | Phase 3 (Basic TTS) | |
| Voice clone | 동의 절차 있는 provider 1곳 | Phase 10 | |
| Image | reference image 지원 API 1곳 | Phase 9 | |
| Storage/CDN | Cloudflare R2(+CDN) 또는 AWS S3 + CloudFront | Phase 3 | egress 비용 때문에 오디오 대량 서빙은 R2가 유리 |
| Realtime | LiveKit Cloud (또는 self-host) | Phase 5 | 로컬 개발은 `livekit/livekit-server` 컨테이너로 계정 없이 가능 ✅. 운영은 TURN·리전 때문에 Cloud가 유리 |
| Push | FCM, APNs | Phase 12 | |
| 결제 | App Store IAP, Google Play Billing (+ 영수증 검증) | Phase 12 | 디지털 콘텐츠는 인앱결제 정책 적용 |
| 모니터링 | Sentry, OTel collector(Grafana/Tempo 등) | Phase 1(Sentry 옵션) / Phase 12 | |
| Secret | AWS Secrets Manager / GCP Secret Manager / Doppler 등 | 운영 배포 | |

---

## 8. 예상 인프라 구성

### 8.1 개발
`docker compose up` → postgres(pgvector) + redis + api. mobile은 `npx expo start`, Phase 5부터 개발 빌드 + LiveKit Cloud 개발 프로젝트.

### 8.2 초기 운영 (MAU 수천 규모 가정)

```text
Cloudflare (DNS · WAF · R2 · CDN)
        │
Load Balancer (TLS)
        │
┌───────────────┬──────────────────┬─────────────────┐
│ api  ×2       │ ai-agent ×N      │ worker ×2        │   ← 컨테이너 (ECS/Cloud Run/K8s 중 택1)
│ (autoscale    │ (동시 세션 기준  │ (큐 길이 기준)   │
│  on CPU/RPS)  │  autoscale)      │                  │
└──────┬────────┴────────┬─────────┴────────┬────────┘
       │                 │                  │
 Managed PostgreSQL (pgvector, PITR 백업)   Managed Redis
       │
 LiveKit Cloud ── ai-agent (한국/일본 리전)
 GPU 클라우드 vLLM (LLM·임베딩, Phase 4 이후 자체 호스팅)
```

- ai-agent는 **배포 시 drain**(새 job 받지 않고 진행 세션 종료까지 대기)을 지원해야 한다.
- 리전: 사용자 한국 → LiveKit·agent·STT/TTS·LLM을 가능한 한 동일/인접 리전에 둔다.

---

## 9. 구현 우선순위

요구사항 §45 순서를 따른다. Phase 번호와 산출물은 [roadmap.md](roadmap.md)에 있다.

1 Architecture → 2 Auth → 3 Book/Chapter/Paragraph → 4 ReadingSession → 5 Mobile Reader → 6 Basic TTS → 7 RAG → 8 LiveKit → 9 Realtime Story Agent → 10 Barge-in → 11 Resume → 12 Scene Engine → 13 Scene Image → 14 Voice Clone → 15 Background Audio → 16 Subscription → 17 Production infra → 18 자체 LLM 학습 파이프라인

---

## 10. 핵심 질문 10개에 대한 답

| # | 질문 | 결정 (요약) | 상세 |
|---|---|---|---|
| 1 | RN 오디오 구조 | **2경로.** Listen 모드는 `expo-audio`로 캐시 오디오 재생(백그라운드·잠금화면). Talk 모드는 LiveKit 오디오 트랙(AEC 적용). 둘 다 `NarrationPlayer` / `RealtimeClient` 인터페이스 뒤에 두고, 전환 시 ReadingPosition을 넘겨준다 | [mobile](mobile-architecture.md#audio) |
| 2 | LiveKit 연결 | API가 `POST /v1/realtime/token`에서 세션 소유권 확인 후 room `rs_{session_id}` 전용 단기 토큰(마이크·data만 publish) + agent dispatch 발급. 클라이언트는 audio track + data topic `story.v1`로 통신 | [realtime](realtime.md#connection) |
| 3 | 백그라운드 허용 범위 | 낭독·재생 제어·위치 저장은 백그라운드 허용. 음성 barge-in은 포그라운드 한정. 백그라운드 질문은 잠금화면/이어폰 버튼 → 앱 복귀 후 Talk | [mobile](mobile-architecture.md#background) |
| 4 | STT/TTS streaming | STT: 20ms PCM 프레임을 provider 스트림에 전달하고 partial/final 이벤트를 받는다. TTS: LLM 토큰을 **절(clause) 단위로 끊어** TTS 스트림에 넣고 첫 청크를 바로 트랙에 publish한다. 모든 스트림은 취소 가능해야 한다 (barge-in) | [realtime](realtime.md#streaming) |
| 5 | ReadingSession 복구 | 문장 경계마다 Redis 체크포인트, PG에는 debounce 저장 + 상태 전이·연결 해제 시 강제 저장. `position_version`으로 충돌을 감지한다. 크래시 후에는 항상 `PAUSED @ 마지막 확정 문장`으로 복구한다 (답변 도중으로 복귀하지 않음) | [realtime](realtime.md#recovery), [database](database.md#positions) |
| 6 | 스포일러 방지 | `global_seq <= reader_seq` 필터를 repository에서 강제, 파생 데이터에 `revealed_at_seq`, 출력 고유명사 검사 | [ai](ai-architecture.md#spoiler) |
| 7 | Scene 전환 판단 | 오프라인. 문단별 구조화 추출(장소·시간·인물·행동·분위기) + 결정적 신호(장 경계, `***`, "다음 날") 가중 점수, 최소/최대 길이와 이력현상(hysteresis) 적용. 사람 라벨 평가셋으로 임계값 튜닝 | [ai](ai-architecture.md#scene) |
| 8 | Voice Clone 데이터 보호 | 별도 동의(버전·스크립트·해시 기록), private bucket + 서버측 암호화, 짧은 signed URL, provider 등록 후 원본 보관기한, 삭제 시 provider·원본·파생 오디오 캐시까지 삭제 작업 전파, 감사 로그 | [security](security.md#voice) |
| 9 | AI provider 교체 | 역할별 Protocol + registry. 설정(`LLM_PROVIDER=openai_compatible`, `LLM_MODEL=...`)으로 선택. 모든 구현이 같은 contract test를 통과해야 등록 | [provider](provider-abstraction.md) |
| 10 | 자체 LLM 연결 | vLLM이 OpenAI-compatible API를 제공하므로 **1단계는 base_url만 바꾸면 된다.** 전용 프롬프트 포맷·LoRA adapter 선택이 필요해지면 `FineTunedStoryLLMProvider`를 추가한다. 학습 데이터는 `training_examples` 테이블 → JSONL export | [ai](ai-architecture.md#self-llm) |
