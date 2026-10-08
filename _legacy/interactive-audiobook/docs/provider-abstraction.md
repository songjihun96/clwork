# Provider Abstraction

> 목표: 외부 AI vendor를 바꾸거나 자체 모델로 옮길 때 **provider 구현 파일 1개 + 설정값**만 바뀌고, StoryAgent·RAG·Scene Engine 코드는 바뀌지 않는다.
> 위치: `packages/story-core/story_core/providers/` (Phase 2에서 공유 패키지 생성. api·worker·ai-agent가 함께 사용)

## 1. 인터페이스 목록

| Interface | 핵심 메서드 | 첫 구현 | 도입 Phase |
|---|---|---|---|
| `LLMProvider` ✅ | `generate`, `stream` | `OpenAICompatibleLLMProvider` (hosted, vLLM 공용) + `FakeLLMProvider` | 4 |
| `EmbeddingProvider` ✅ | `embed(texts, kind)` | `OpenAICompatibleEmbeddingProvider` + 해싱 기반 fake | 4 |
| `STTProvider` | `stream()` → `STTStream` | 한국어 streaming 1곳 | 6 |
| `TTSProvider` ✅ | `synthesize`, `synthesize_stream` | `FakeTTSProvider`(개발용) — 실제 제공사는 계정 확보 후 | 3 |
| `VoiceProvider` | `create_voice`, `get_voice`, `delete_voice`, `synthesize` | voice clone 1곳 | 10 |
| `ImageProvider` | `generate_scene(prompt, reference_images)` | reference 지원 API 1곳 | 9 |
| `StorageProvider` ✅ | `put_bytes`, `get_bytes`, `delete`, `exists`, `signed_get_url` | `LocalFileStorage`(HMAC 서명 URL) · `S3CompatibleStorage`(S3·R2) | 3 |
| `WakeWordEngine` (옵션) | `process(frame) -> bool` | 없음 (인터페이스만) | 7+ |
| `IdentityTokenVerifier` ✅ | `verify(id_token, nonce)` | `AppleIdTokenVerifier`, `GoogleIdTokenVerifier` | 1 |

모든 fake 구현(`FakeLLMProvider` 등)은 테스트용으로 **실제 코드와 같은 패키지에** 둔다. 통합 테스트는 외부 API 없이 fake로 전체 파이프라인을 돈다.

Phase 1에서는 AI provider 코드를 만들지 않았다. 호출하는 기능이 아직 없어 실행·검증할 수 없는 코드가 되기 때문이다. `IdentityTokenVerifier`만 인증에 필요해서 구현·테스트했다.

**Phase 4 (LLM·임베딩) 구현 상태.** 계정 없이 검증 가능한 범위까지 만들었다.
- `OpenAICompatibleLLMProvider`: `/chat/completions`(비스트리밍·SSE 스트리밍), `max_tokens`를 보낸다(vLLM과 대부분의 호환 서버가 받는 이름. 새 이름만 받는 공급사는 얇은 어댑터를 따로 둔다 — 인터페이스가 있는 이유다). `json_schema`는 **capability로 선언된 배포에서만** 허용하고, 아니면 `ProviderBadRequest`로 즉시 거절한다(재시도하지 않는다).
- `FakeEmbeddingProvider`는 난수 벡터가 아니라 **문자 바이그램 해싱** 모델이다. 결정적이고 계정이 필요 없으면서 유사도가 실제로 의미를 가지므로, 검색·RRF·스포일러 필터·컨텍스트 예산을 공급사 없이 끝까지 검증할 수 있다. 다만 글자가 겹치지 않는 패러프레이즈는 못 잡는다 — 그게 실제 모델을 사는 이유이므로, 검색 품질 수치는 실제 모델로만 낸다.
- `FakeLLMProvider`는 주어진 `<context>`로 답하고 비어 있으면 "찾지 못했다"고 답하는 **스텁**이다. 근거 기반 답변의 *배관*(검색→예산→출력 검사→기록)은 이것으로 전부 테스트되지만, 답변 품질과 "모른다" 비율은 실제 모델로만 측정된다.
- 두 fake는 운영 설정에서 거부된다(`LLM_PROVIDER=fake`, `EMBEDDING_PROVIDER=fake`).
- **계약 전 확인할 것:** ① 임베딩 차원과 `query`/`document` 지시 접두사 ② 스트리밍 시 `usage` 제공 여부(`stream_options.include_usage`) ③ 429의 `Retry-After` 형식 ④ 구조화 출력(guided decoding) 지원 여부 ⑤ 입력 텍스트의 학습 사용 여부(책 원문이 나간다).

**Phase 3 (TTS) 구현 상태.** 계정 없이 검증 가능한 범위까지 만들었다.
- `FakeTTSProvider`: 결정적이고 들리는 톤을 생성한다(음성은 아니다). 캐시·저장소·서명 URL·모바일 재생·문장 하이라이트를 계정 없이 끝까지 검증하기 위한 것이며, 운영 설정에서는 `TTS_PROVIDER=fake`를 거부한다.
- 실제 제공사 어댑터는 계약 후 추가한다. 추가 시 필요한 것은 `synthesize`(PCM16 mono 반환) 하나이며, 문장 타이밍 기능은 요구하지 않는다 — 문단 오디오는 문장 클립을 이어 붙여 만들기 때문에 타임스탬프가 정확하다.
- **계약 전 확인할 것:** ① 생성 오디오의 저장·재사용 허용 여부(불가하면 캐시 전략과 원가 모델이 달라진다) ② PCM/WAV 출력 지원 ③ 한국어 음성 목록과 첫 오디오 지연 ④ 문자 수 과금 단위.

## 2. 공통 타입 (Python)

```python
from typing import AsyncIterator, Protocol, Sequence
from pydantic import BaseModel

class ProviderInfo(BaseModel):
    provider: str            # "openai_compatible", "azure_speech", ...
    model: str               # 실제 모델/voice 모델 버전 — 캐시 키·비용·학습 데이터에 기록
    capabilities: frozenset[str]   # {"streaming", "json_schema", "reference_images", "ssml", ...}

class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    characters: int = 0
    audio_ms: int = 0
    images: int = 0

class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str

class LLMRequest(BaseModel):
    messages: list[ChatMessage]
    max_tokens: int
    temperature: float = 0.3
    stop: list[str] = []
    json_schema: dict | None = None      # capability "json_schema" 필요
    request_tag: str                     # "story_answer" | "intent" | "scene_analysis" (비용 집계용)

class LLMChunk(BaseModel):
    delta: str
    finish_reason: str | None = None
    usage: Usage | None = None           # 마지막 청크에만

class LLMProvider(Protocol):
    info: ProviderInfo
    async def generate(self, req: LLMRequest, *, timeout_s: float) -> tuple[str, Usage]: ...
    def stream(self, req: LLMRequest, *, timeout_s: float) -> AsyncIterator[LLMChunk]: ...

class EmbeddingProvider(Protocol):
    info: ProviderInfo
    dimensions: int
    async def embed(self, texts: Sequence[str], *, kind: Literal["query", "document"]) -> list[list[float]]: ...

# 구현된 형태 (story_core/providers/tts/base.py) — dataclass, PCM16 mono 고정
@dataclass(frozen=True)
class Voice:
    voice_id: str
    version: str = "1"          # 개인 목소리 재학습 시 증가 → 캐시 자동 무효화

@dataclass(frozen=True)
class TTSRequest:
    text: str
    voice: Voice
    language: str = "ko-KR"
    speed: float = 1.0          # 1.0으로만 합성한다 (속도는 플레이어가 적용)
    emotion: str | None = None

@dataclass(frozen=True)
class SynthesisResult:
    audio: PcmAudio             # PCM16 mono + sample_rate
    characters_billed: int

class TTSProvider(Protocol):
    info: ProviderInfo
    sample_rate: int
    async def synthesize(self, request: TTSRequest) -> SynthesisResult: ...
    def synthesize_stream(self, request: TTSRequest) -> AsyncIterator[bytes]: ...  # Phase 6 (Talk 모드)

class ImageProvider(Protocol):
    info: ProviderInfo
    async def generate_scene(self, prompt: str, reference_images: list[str] | None = None,
                             *, negative_prompt: str | None = None, seed: int | None = None,
                             size: tuple[int, int] = (1024, 768)) -> GeneratedImage: ...
```

요구안 시그니처(`options: dict | None`)는 **타입 있는 요청 객체**로 바꿨다. dict는 provider마다 키가 달라지면서 조용히 무시되는 옵션이 생기기 때문이다. 오디오 포맷도 옵션이 아니라 **PCM16 mono 고정**이다 — 문장 클립을 샘플 단위로 이어 붙여야 문장 타임스탬프가 정확하고, 전달용 인코딩(WAV/AAC)은 저장 직전에 한 번만 한다.

## 3. 선택과 조립 (registry)

```python
# settings (.env)
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://...        # hosted endpoint 또는 http://vllm:8000/v1
LLM_MODEL=Qwen/Qwen3-...
LLM_API_KEY=...                 # SecretStr

# registry
PROVIDERS: dict[str, Callable[[Settings], LLMProvider]] = {
    "openai_compatible": OpenAICompatibleLLMProvider.from_settings,
    "fake": FakeLLMProvider.from_settings,
}
```

- 역할별로 설정을 나눈다: `STORY_LLM_*`, `INTENT_LLM_*`, `SCENE_LLM_*`. 같은 provider라도 모델이 다를 수 있다.
- 조립은 애플리케이션 시작 시 한 번 한다 (FastAPI lifespan / agent worker entrypoint). 도메인 코드는 인터페이스 타입만 주입받는다.
- **라우팅 계층 `RoutedLLMProvider`** (Phase 12): 기본 provider 장애 시 대체 provider, 사용자 플랜별 모델, A/B 비율. 인터페이스가 같으므로 도메인 코드는 모른다.

## 4. 공통 동작: timeout · retry · circuit breaker · metering

모든 provider 호출은 decorator/wrapper 체인을 거친다. provider 구현은 "요청 1회"만 책임진다.

```text
MeteredProvider ─► CircuitBreaker ─► Retry(backoff) ─► Timeout ─► ConcreteProvider
   │ usage_records 기록       │ 연속 실패 시 open    │ 재시도 가능 오류만     │ 필수
   │ OTel span (latency)
```

Phase 4 구현 범위: **Timeout + Retry**(`story_core/providers/resilience.py`). Circuit breaker와 metering sink는 Phase 12다 — 지금 호출할 코드가 없는 계층을 만들면 검증할 수 없고, `Usage`와 오류 타입은 이미 있어서 sink만 붙이면 된다. 대신 Phase 4 시점의 사용량은 `conversation_messages`(provider·model·구간별 지연·근거 chunk)에 남는다.

재시도 규칙에서 실제로 걸린 버그: 요청 본문을 만드는 코드를 `try` 안에 둔 탓에 `ProviderBadRequest`(재시도 불가)가 전송 오류로 재포장되어 **잘못된 요청이 3번 재시도**됐다. 요청 생성은 `try` 밖에 두고 전송 예외만 매핑한다. 상태코드 → 오류 타입 매핑은 표로 테스트한다(401/403→Auth, 400→BadRequest, 429→RateLimited(+Retry-After), 5xx→Unavailable, 408/504→Timeout).

| 항목 | 규칙 |
|---|---|
| Timeout | **모든 호출에 필수.** 기본: LLM 첫 토큰 5s / 전체 30s, 임베딩 10s, TTS 첫 오디오 3s, 이미지 120s, storage 10s. 설정 가능 |
| Retry | 재시도 가능 오류(연결 실패, 429, 5xx, timeout)만. exponential backoff + full jitter, 최대 3회. 429의 `Retry-After`를 존중한다. **스트리밍은 첫 청크를 받기 전에만 재시도**한다 (중간부터 재시도하면 사용자에게 중복 음성이 나간다) |
| 실시간 경로 | ai-agent의 retry는 최대 1회. 지연 예산이 작으므로 대체 provider나 안내 멘트로 넘어간다 |
| Circuit breaker | 30초 창에서 실패율 50% 이상이면 open(30s) → half-open |
| 오류 분류 | `ProviderError` 하위: `ProviderTimeout`, `ProviderRateLimited(retry_after)`, `ProviderUnavailable`, `ProviderBadRequest`(재시도 불가), `ProviderAuthError`(재시도 불가, 알림), `ProviderContentRejected`(안전 필터) |
| Metering | 호출 종료 시 `Usage` → `usage_records` (비동기 배치 insert). 비용은 `provider_prices` 테이블로 계산하고 코드에 가격을 넣지 않는다 |
| 로그 | provider, model, request_tag, latency, status, usage만. 프롬프트·원문·오디오는 기록 안 함 |

## 5. 취소 의미론 <a id="cancellation"></a>

Barge-in 때문에 **취소는 정상 경로**다.

- `stream()`/`synthesize_stream()` 소비 중 `asyncio.CancelledError`가 발생하면 구현체는 즉시 upstream 연결(HTTP 스트림, WebSocket)을 닫아야 한다. provider가 계속 생성하면 비용이 나간다.
- `aclose()` 호출 후 추가 청크를 내보내지 않는다.
- 취소된 호출도 **그 시점까지의 usage**를 기록한다.
- Contract test: "첫 청크 수신 후 cancel → 200ms 안에 연결 종료 & 추가 yield 없음".

## 6. 캐시 <a id="cache"></a>

캐시는 provider 바깥의 `CachedTTS`, `CachedEmbedding`, `CachedImage` wrapper가 담당한다. provider 구현은 캐시를 모른다.

| 대상 | 키 (sha256 입력) | 저장 |
|---|---|---|
| TTS 문장 오디오 ✅ | `sentence \| provider \| model \| voice_id@voice_version \| language \| speed \| emotion \| pcm16@rate \| normalize(text)` | 객체 저장소(WAV) + `audio_assets` (book_id·paragraph_id·voice_profile_id는 인덱스 컬럼) |
| TTS 문단 오디오 ✅ | `paragraph \| format \| 문장 캐시 키들` — 내용이 같으면 책·재처리와 무관하게 재사용 | 객체 저장소 + `audio_assets.timings`(문장 타임스탬프) |
| 임베딩 | `model \| kind \| text` | pgvector 테이블 자체 + Redis(질문 임베딩 단기) |
| Scene 이미지 | `book_id \| scene_id \| style \| character_bible_version \| prompt_hash \| model` | 객체 저장소 + `image_assets` |
| Scene/책 분석 | `book_id \| text_hash \| analysis_version \| model` | PG |

- 요구안 키(`book_id, paragraph_id, voice_id, speed, emotion`)에 **text hash와 model/voice version을 더한 이유**: 원문 교정·모델 업그레이드 후 오래된 결과가 나오는 것을 막는다.
- 캐시 쓰기는 `cache_key UNIQUE` + `INSERT ... ON CONFLICT DO NOTHING`이고, 저장 키는 콘텐츠 주소(cache_key)라 동시 렌더링이 서로를 덮어써도 내용이 같다. API는 폴링 중 같은 문단 작업을 반복 등록하지 않도록 Redis `SET NX`(1분)로 막는다. 중복 합성이 비싼 실제 provider에서는 렌더 시작 시 Redis 락을 추가한다 (Phase 12).
- **재생 속도는 캐시 키에 넣지 않는다.** 1.0배로만 합성하고 속도는 플레이어가 적용한다(속도마다 캐시가 쪼개지면 비용이 배로 늘고, 사용자가 속도를 바꿀 때마다 기다려야 한다).
- TTS provider 약관이 **생성 오디오의 저장·재사용을 허용하는지** 계약 전에 확인한다. 허용하지 않는 provider는 캐시가 불가능해 원가 모델이 달라진다.

## 7. Contract test

`tests/contract/`에 인터페이스별 테스트 suite를 두고, 모든 구현이 통과해야 registry에 등록한다.

| Interface | 검사 |
|---|---|
| LLM | generate가 문자열 반환, stream 청크 순서, 마지막 청크 usage, json_schema capability 시 유효 JSON, timeout 준수, cancel 시 연결 종료 |
| Embedding | 입력 수 = 출력 수, 차원 = `dimensions`, 빈 문자열 처리, 배치 크기 상한 분할 |
| TTS | 빈 텍스트 거부, 포맷 헤더, 스트림 첫 청크 지연 측정, cancel |
| STT | 무음 → final 없음, 샘플 wav → 기대 텍스트 CER 임계값 이하 |
| Voice | create → get(ready) → synthesize → delete → get(not found) |
| Image | reference_images 미지원 capability면 명시적 오류(조용히 무시 금지) |
| Storage | put/get/delete, signed URL 만료, 존재하지 않는 키 |

실제 provider contract test는 비용이 들므로 CI에서 야간 1회 + 수동 실행한다. fake 구현은 매 커밋 실행한다.

## 8. 자체 모델로 교체

| 시나리오 | 바뀌는 것 |
|---|---|
| hosted Qwen → 자체 vLLM (같은 모델) | `LLM_BASE_URL`만 |
| LoRA 파인튜닝 모델 (vLLM adapter) | `LLM_MODEL=story-lora-v3` (vLLM은 adapter 이름을 model로 지정) |
| 프롬프트 포맷·특수 토큰이 다른 자체 모델 | `CustomStoryLLMProvider` 추가 (메시지 → 모델 포맷 변환만 구현) + 설정 |
| 자체 TTS / voice model | `SelfHostedTTSProvider` 추가. **캐시 키의 provider·model이 달라지므로** 기존 캐시와 섞이지 않는다 |
| 임베딩 모델 교체 | 새 임베딩 테이블 재생성 → 평가 → 전환 ([database.md](database.md)) |

교체 절차: contract test 통과 → 오프라인 평가셋 비교 → shadow traffic(응답 저장만) → 비율 롤아웃 → 전환.
