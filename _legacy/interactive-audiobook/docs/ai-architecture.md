# AI Architecture — Intent, RAG, Story LLM, Scene Engine, 자체 모델

> 원칙: LLM 하나가 모든 일을 하지 않는다. 각 컴포넌트는 입력·출력 타입이 정해진 인터페이스이며, LLM은 **자연어 이해·생성만** 담당한다.

## 1. 컴포넌트와 경계

```text
                 ┌──────────── realtime (ai-agent) ─────────────┐
 STT final ──►   IntentRouter ──► PlaybackController (enum 명령만)
                      │
                      ├─ BOOK_QUESTION ──► Retriever ─► ContextBuilder ─► StoryLLM ─► SpoilerGuard ─► TTS
                      ├─ SCENE_QUESTION ─► SceneContext ─┘
                      ├─ GENERAL ────────► ContextBuilder(책 없음, 짧게) ─► LLM
                      ├─ ACK / RESUME ───► ReadingStateMachine
                      └─ INTERRUPT_ONLY / UNCLEAR ─► "응, 말해줘" 캐시 오디오
                 └──────────────────────────────────────────────┘

                 ┌──────────── offline (worker) ────────────────┐
 epub ──► Parser ─► SentenceSplitter ─► Chunker ─► Embedder ─► pgvector
                                   └─► SceneAnalyzer ─► SceneDetector ─► CharacterBible ─► PromptBuilder ─► ImageProvider
                 └──────────────────────────────────────────────┘
```

| 컴포넌트 | 입력 | 출력 | LLM 사용 |
|---|---|---|---|
| IntentRouter | transcript, 현재 state | `Intent` enum + slots | 규칙 우선, 애매할 때만 소형 LLM 분류 |
| PlaybackController | `PlaybackCommand` | 상태 머신 이벤트 | ❌ |
| Retriever | question, reader position, spoiler_mode | `RetrievedChunk[]` | ❌ (임베딩만) |
| ContextBuilder | chunks, 현재 문단/장면, 대화 요약 | `LLMRequest` (토큰 예산 내) | ❌ |
| StoryLLM | `LLMRequest` | 텍스트 스트림 | ✅ |
| SpoilerGuard | 답변 텍스트, reader_seq | pass / rewrite 요청 | ❌ (엔티티 인덱스) |
| SceneAnalyzer | 문단 텍스트 윈도우 | 구조화 JSON | ✅ (오프라인) |
| SceneDetector | 문단별 특징 | scene 경계 | ❌ (점수 규칙) |

## 2. Intent Router (Phase 6 ✅)

### 2.1 Intent

| Intent | 예 | 처리 |
|---|---|---|
| `INTERRUPT_ONLY` | "잠깐", "잠깐만", "저기", "질문 있어" | 낭독 정지 후 대기 |
| `PLAYBACK_COMMAND` | "멈춰", "계속 읽어", "다시 읽어줘", "빨리", "앞 문단" | 명령 enum |
| `ACK` | "응", "알겠어", "그래", "오케이" | `AWAITING_FOLLOWUP`에서 재개 |
| `BOOK_QUESTION` | "모모가 왜 거기 있었어?" | RAG |
| `SCENE_QUESTION` | "지금 어디야?", "이 장면 설명해줘" | Scene context |
| `SUMMARY` | "지금까지 줄거리 알려줘" | 위치 기준 요약 |
| `GENERAL` | "원형극장이 뭐야?" (책 밖 지식) | 일반 LLM, 짧게 |
| `UNCLEAR` | 인식 실패, 소음 | 되묻기 |

"원형극장이 뭐야"는 책 질문일 수도, 일반 지식일 수도 있다 → `BOOK_QUESTION`으로 먼저 검색하고, 근거가 없으면 일반 지식으로 답하되 **"책에 나온 설명은 아니지만"** 이라고 구분한다.

### 2.2 방식

1. **규칙 (0ms):** 정규화(공백·문장부호·어미 변형) 후 한국어 사전 매칭. 짧은 발화(≤ 4어절)의 명령/맞장구 대부분을 처리한다.
2. **소형 분류기 (≤ 150ms):** 규칙이 판단하지 못하면 작은 LLM에 JSON schema 출력(guided decoding)을 요청하거나, 이후 파인튜닝한 분류기를 쓴다.
3. 같은 발화도 **상태에 따라 다르게 해석**한다. "응"은 `AWAITING_FOLLOWUP`에서는 `ACK`, `READING` 중에는 맞장구(무시)다.

평가: 라벨링한 발화 셋(초기 500+)으로 intent별 precision/recall을 측정한다. `PLAYBACK_COMMAND` 오분류는 UX 피해가 크므로 precision을 우선한다. **현재는 규칙 사전과 상태 의존 규칙을 36개 테스트로 고정했고, 500+ 발화 셋은 실제 사용자 발화가 필요하다.**

구현 메모:
- 규칙은 **짧은 발화(≤4어절)만** 판단한다. "멈춰 있는 시계가 무슨 의미야?"처럼 명령어가 포함된 질문은 규칙이 손대지 않는다.
- 분류기는 6개 intent만 고를 수 있고(재생 제어는 이미 규칙이 처리했다), enum 밖의 답·JSON 파싱 실패·타임아웃은 모두 **`BOOK_QUESTION`으로 폴백**한다. 잘못 멈춘 낭독은 사용자가 고치기 어렵고, 책에서 답한 질문은 다시 물으면 된다.
- 필러("음", "흠")는 규칙에서 UNCLEAR로 끝낸다 — 마이크가 가장 자주 잡는 소리에 모델 호출을 쓰지 않는다.

## 3. RAG

### 3.0 문장 분리 (Phase 2 ✅)

문장은 낭독·하이라이트·재개의 단위다. `RuleBasedKoreanSplitter`(`story_core/ingestion/sentences.py`) 규칙:
종결부호(`. ? ! …` 전각 포함) 연속 + 닫는 따옴표/괄호 뒤 공백에서 분리 · 인용부호 안에서는 분리하지 않음(닫는 따옴표가 단위 끝) · 따옴표가 문단 안에서 짝이 안 맞으면 인용 무시 · 소수점·목록 번호·짧은 라틴 약어 제외 · 300자 초과 단위는 쉼표/공백에서 추가 분할(TTS 입력 한계).

평가(`packages/story-core/scripts/eval_sentence_splitter.py --kiwi`, 2026-09-15): 규칙 기반 exact 20/20, kiwipiepy 15/20 (F1 0.894). kiwi 불일치의 대부분은 인용 규칙 차이이고, 띄어쓰기 없는 경계는 kiwi가 더 정확했다. **gold set이 20문장이고 규칙과 함께 작성돼 편향 가능성이 크다** → 권리 확보된 실제 책 3권에서 사람 라벨 후 재평가(Phase 4 평가셋 구축 시). 인터페이스(`SentenceSplitter`)가 있어 교체 비용은 작다.

### 3.1 인덱싱 (Phase 4 ✅)

- Chunk = 1문단 (긴 문단은 문장 경계로 분할, 짧은 문단은 **같은 scene 안에서만** 병합). chunk는 `start/end_global_seq`를 가진다.
- 구현 시 확정한 불변조건: chunk는 **문장의 연속 구간**이고 `end_global_seq`는 그 chunk가 가진 가장 큰 문장 번호다. 병합은 같은 장·장면 안에서만 하므로 이 불변조건이 유지되며, 스포일러 필터가 `end_global_seq` 하나만 비교해도 정확하다(hypothesis 속성 테스트로 보장). Scene은 Phase 8이므로 지금 경계 신호는 `scene_break_before`와 장 경계다.
- 임베딩 입력에는 chunk 앞에 `[장 제목] [장소]` 같은 짧은 메타를 붙인다 (contextual chunk). 원문 저장은 붙이지 않은 텍스트로 한다.
- 임베딩 캐시 키: `sha256(model_id | input_text)` — 재처리 시 재호출 방지.

### 3.2 검색 (질문 1회) — Phase 4 ✅

```text
1. query 재작성 (대화 기록에서 대명사 해소: "걔가 왜 그랬어?" → "모모가 왜 ...")  ← 소형 LLM, 생략 가능
2. 후보 수집 (전부 global_seq 필터 적용)
   a. 현재 위치 창: 현재 문장 앞 N문단 (항상 포함, 검색 없이)
   b. 벡터 top-k (k=8)
   c. 키워드/인물명 trigram top-k
   d. 현재 scene 요약 + 등장인물 bible (revealed_at_seq 필터)
3. RRF 병합 → 거리 임계값 미달 제거 → (선택) reranker
4. 위치 가까운 순 가중치
```

구현 메모:
- **1번(쿼리 재작성)은 아직 없다.** 대화 기록을 프롬프트에 넣어 대명사를 모델이 풀게 하고, 별도 LLM 호출을 늘리지 않았다. Talk 모드의 지연 예산을 보고 Phase 6에서 다시 판단한다.
- **2-a(위치 창)는 청크를 쓰되 걸친 청크를 자른다.** 지금 듣고 있는 문단은 끝 문장이 아직 안 들려서 `end_global_seq <= allowed_seq`에 걸리는데, 질문 대상이 될 가능성이 가장 큰 문단이다. 그래서 `start_global_seq <= allowed_seq`로 뽑고 **들은 문장까지만** 텍스트를 잘라 넣는다(안 들은 문장은 한 문장도 노출되지 않음).
- 2-d(scene 요약·인물 bible)는 Phase 8에서 붙는다.
- 벡터 검색만 방언별로 갈린다: PostgreSQL은 `<=>` + HNSW, SQLite(로컬 테스트)는 같은 필터 조건으로 뽑은 행을 파이썬에서 코사인 계산한다 — 문서에 있던 exact-scan fallback과 동일한 코드 경로다. 덕분에 안전이 걸린 쿼리를 DB 서비스 없이도 테스트한다.
- RRF 가중치 초기값: 위치 창 1.3 · 벡터 1.0 · 키워드 0.8. 위치 창 청크는 예산이 허락하는 한 **무조건 포함**한다.

### 3.3 스포일러 방지 (Phase 4 ✅) <a id="spoiler"></a>

| 계층 | 방법 | 막는 것 |
|---|---|---|
| 1. 쿼리 | `end_global_seq <= allowed_seq` (repository가 강제, 호출자가 끌 수 없음) | 미래 원문 검색 |
| 2. 파생 데이터 | 요약·character_facts·scene 요약에 `revealed_at_seq` | 책 전체를 보고 만든 분석 |
| 3. 프롬프트 | 규칙 4 (아래) | 추론 과정의 누설 |
| 4. 출력 검사 | 답변의 고유명사/인물명 중 `first_appearance_seq > allowed_seq`인 것이 있으면 재생성 1회 → 실패 시 안전 응답 | LLM 사전지식(유명작 결말) |

`allowed_seq` 계산:
- `NO_SPOILER`: `max(reader_seq, max_read_seq)`
- `LIGHT_SPOILER`: 위와 같되, 사용자가 명시적으로 물으면 **다음 장까지 요약 수준** 허용 (정의는 제품 결정 후)
- `FULL_SPOILER`: 필터 해제 (사용자 명시 설정 + 확인 다이얼로그)

구현에서 바꾼 것:
- **`FULL_SPOILER`도 필터를 끄지 않는다.** `allowed_seq`를 마지막 문장 번호로 올릴 뿐이다. "필터 없음" 분기가 존재하지 않으므로 잘못된 조건으로 그 분기에 들어갈 경로도 없다.
- `LIGHT_SPOILER`는 잠정적으로 **듣고 있는 장의 끝까지**로 구현했다. 문서가 정의를 제품 결정으로 남겼기 때문에 코드는 보수적인 해석을 택했고, 확정되면 `allowed_seq()` 한 함수만 바뀐다.
- 4계층(출력 검사)은 Phase 8의 엔티티 인덱스가 없으므로, 답변이 **근거(<context>) 밖에서 새로 꺼낸 용어**만 골라 "책에서 처음 등장하는 문장 번호 > allowed_seq"인지 한 번의 쿼리로 확인한다(조사 제거 변형 포함, `sentences.text`의 trigram 인덱스 사용). 걸리면 재생성 대신 안전 응답으로 대체하고 `conversation_messages.guard_action='blocked'`로 남긴다 — 재생성은 두 번째 호출과 더 강한 프롬프트가 필요해 Phase 8의 엔티티 인덱스와 함께 도입한다.
- 검색 결과에 대해 `end_global_seq <= allowed_seq`를 **한 번 더** 확인한다(SQL 필터가 본 방어선이고, 그것이 뚫린 적이 있으면 결말이 새므로 값싼 재확인은 남긴다). 위반 시 `retrieval_spoiler_filter_violation`을 error로 기록하고 그 chunk를 버린다.

### 3.4 Context 예산 (Phase 4 ✅)

음성 답변은 짧아야 하므로 context도 작게 잡는다 (TTFT 감소).

| 블록 | 예산 (토큰, 초기값) |
|---|---|
| system + 규칙 | 400 |
| 책 메타·현재 장·scene | 150 |
| 현재 위치 창 | 600 |
| 검색 chunk | 1,200 |
| 인물 bible | 200 |
| 대화 기록 (최근 4턴 원문 + 이전 요약) | 500 |
| 질문 | 100 |

책 전체를 context에 넣는 경로는 코드에 없다. ContextBuilder는 예산 초과 시 **검색 chunk → 대화 기록 순**으로 자른다. 위치 창과 질문은 자르지 않는다 — 근거가 적은 답변보다 엉뚱한 위치의 답변이 더 나쁘다.

토큰 수는 토크나이저 대신 **추정**한다(한글 1자 ≈ 1토큰, 그 외 4자 ≈ 1토큰). 토크나이저는 모델마다 다르므로 특정 공급사의 BPE를 넣으면 다른 모델에 대해 틀린 값을 주고 의존성도 무거워진다. 실제 소비량은 공급사 `usage`로 돌아와 `conversation_messages`에 남는다.

## 4. Story LLM 프롬프트

```text
당신은 책을 읽어주는 AI Story Agent다. 지금 사용자는 『{title}』 {chapter_title}을(를) 듣고 있다.

규칙:
1. 책의 원문과 검색된 문맥(<context>)을 우선한다.
2. 근거가 없는 사실을 사실처럼 말하지 않는다.
3. 책에 명시되지 않은 경우 추측이라고 명확하게 말한다.
4. 사용자가 읽지 않은 이후의 내용을 스포일러하지 않는다. <context>에 없는 앞으로의 전개는 모른다고 답한다.
5. 현재 독서 위치를 기준으로 답한다.
6. 음성으로 전달되므로 1~3문장으로 짧게 답한다. 사용자가 자세히 요청하면 늘린다.
7. 목록·표·마크다운·이모지를 쓰지 않는다. 소리 내어 읽기 자연스러운 구어체로 답한다.
8. 답변이 끝나면 멈춘다. "다시 읽어줄게" 같은 재개 멘트는 시스템이 하므로 말하지 않는다.
```

요구안 규칙 7·8("독서 상태를 유지한다", "복귀할 수 있어야 한다")은 **LLM의 책임이 아니라 상태 머신의 책임**이므로, 프롬프트에서는 "재개 멘트를 말하지 않는다"로 바꿨다. LLM에게 상태 유지를 맡기면 원칙 §3.8 위반이다.

프롬프트는 코드 문자열이 아니라 **버전 관리되는 템플릿 파일**(`prompts/story_answer.v1.txt`)로 둔다. `conversation_messages`에 prompt 버전을 기록해 평가·학습 데이터와 연결한다.

## 5. Scene Engine <a id="scene"></a>

### 5.1 파이프라인 (worker, 책 등록 시 1회)

1. **문단 특징 추출 (LLM, 구조화 출력):** 슬라이딩 윈도우(앞 2 + 현재 + 뒤 1문단)로 `{location, time_of_day, weather, characters_present[], main_action, mood, emotion, explicit_time_jump}` 추출. JSON schema 강제, 실패 시 재시도 후 `unknown`.
2. **경계 점수:**

| 신호 | 가중치(초기값) | 비고 |
|---|---|---|
| 장(Chapter) 경계 | 확정 경계 | |
| 명시적 구분자 (`***`, 빈 줄 3개 등) | 0.9 | 파서 단계 |
| 시간 점프 표현 ("다음 날", "몇 년 후") | 0.6 | 규칙 + LLM 필드 |
| location 변경 | 0.5 | 동의어 정규화 후 비교 |
| 주요 인물 집합 Jaccard < 0.5 | 0.3 | |
| main_action 유형 변경 | 0.2 | |
| mood 변경 | 0.15 | |

3. **결정:** `score ≥ 0.6`이면 경계. 단 **최소 길이**(예: 6문장 또는 낭독 45초) 미만이면 병합, **최대 길이**(예: 낭독 5분) 초과면 가장 높은 점수 지점에서 분할. 경계 직후 2문단은 점수를 감쇠시켜(hysteresis) 경계가 연달아 생기는 것을 막는다.
4. **Scene 요약:** scene 범위 텍스트 → `description`, `mood`, `visual_style` (책 단위 스타일 상속).
5. **평가:** 사람이 경계를 표시한 책 3~5권 기준 boundary F1 (±1문단 허용), 책당 scene 수 분포 확인. 가중치·임계값은 여기서 조정한다.

### 5.2 Character Bible

- NER + LLM으로 인물 후보와 별칭("모모", "그 아이")을 모으고 사람이 병합한다. 초기에는 편집 도구가 필요하다.
- 외형 fact는 원문 근거 문장(`source_sentence_id`)을 반드시 가진다. 근거 없는 fact는 `inferred`로 표시하고 기본 이미지 프롬프트에만 쓴다.
- `bible_version`이 바뀌면 관련 scene 이미지 캐시가 무효화된다 (캐시 키에 포함).

### 5.3 이미지 프롬프트

```text
[style preset: book-level, 고정]  +  [scene: location, time, weather, mood, camera]
+ [characters present: bible 요약 문장, 최대 3명]  +  [negative: 텍스트·워터마크·과도한 노출]
+ reference_images: 캐릭터 기준 이미지 (bible 확정 시 1회 생성 후 사람 승인)
```

- 생성 시점: 책 등록 후 선생성(권장) 또는 scene 첫 사용 시 생성 후 캐시. **낭독 중 문장마다 생성하는 경로는 없다.**
- 안전 필터: provider 필터 + 자체 분류 결과를 `image_assets.safety_status`에 기록, 미승인 이미지는 노출하지 않는다.

## 6. 모델 선택·평가

| 용도 | 크기 방향 | 기준 |
|---|---|---|
| Story 답변 | 중형 (지연·품질 균형) | 근거 충실도, 한국어 구어체, TTFT |
| Intent 분류·query 재작성 | 소형 | 지연 ≤ 150ms |
| Scene 분석 (오프라인) | 중·대형 가능 | 구조화 출력 정확도, 비용 |
| Embedding | 다국어 | 한국어 검색 recall@k |

"아직 필요하지 않은 초대형 LLM"은 도입하지 않는다. 오프라인 분석에만 큰 모델을 허용한다.

**평가 세트 (Phase 4에서 구축):** 권리 확보된 책 3권 × 위치별 질문 150개. 각 질문에 정답 근거 chunk와 "스포일러 금지 위치"를 붙인다.
지표: 근거 충실도(LLM-judge + 사람 샘플링), 스포일러 누설률(0 목표), 모른다고 해야 할 때 모른다고 한 비율, 답변 길이, TTFT.

## 7. 자체 LLM 로드맵 <a id="self-llm"></a>

| 단계 | 내용 | 코드 영향 |
|---|---|---|
| 1 | Open-source LLM + RAG + StoryAgent (hosted OpenAI-compatible) | `OpenAICompatibleLLMProvider` |
| 2 | 대화 로그 수집 (동의 사용자만), 평가·라벨링 도구, 좋은 응답 데이터셋 | `training_examples` |
| 3 | SFT / LoRA / QLoRA (Story 답변, intent 분류 각각) | `models/llm/` 학습 설정 |
| 4 | vLLM 자체 inference (LoRA adapter serving) | **base_url만 변경** (vLLM OpenAI-compatible server) |
| 5 | Preference Optimization (DPO 등) — 사용자 피드백·사람 비교 라벨 | 데이터만 추가 |
| 6 | 검증되면 continued pretraining / 더 큰 자체 모델 | `CustomStoryLLMProvider` (프롬프트 포맷이 다를 때만) |

### 7.1 학습 데이터 schema (`training_examples` → JSONL)

```json
{
  "id": "uuid",
  "instruction": "system prompt version id 또는 지시문",
  "context": "검색된 원문 chunk (권리 확인된 책만)",
  "question": "사용자 질문 (정규화)",
  "answer": "좋은 답변 (사람 검수/수정본)",
  "book_type": "novel | children | essay ...",
  "scene": "scene description",
  "intent": "BOOK_QUESTION",
  "spoiler_boundary_seq": 1234,
  "quality": 5,
  "source": "production_log | synthetic | human_written",
  "prompt_version": "story_answer.v1"
}
```

**export 규칙 (`scripts/export_training_data.py`, Phase 13):**
- `quality >= 4`, `book_rights_ok = true`, `consent_basis`가 있는 행만 내보낸다.
- user_id·세션 id는 내보내지 않는다. 질문 텍스트의 개인정보는 패턴 기반으로 가린다.
- split은 **책 단위**로 나눈다 (같은 책이 train/eval에 섞이면 평가가 부풀려진다).
- 출력 포맷: chat-messages JSONL (SFT), `{prompt, chosen, rejected}` (preference).

학습 데이터 활용에 동의하지 않은 사용자의 대화는 절대 export되지 않아야 한다. 이는 테스트로 강제한다.
