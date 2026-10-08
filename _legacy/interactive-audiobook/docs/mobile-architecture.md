# Mobile Architecture — React Native (Expo SDK 57)

## 1. 앱 형태: Expo CNG (Continuous Native Generation)

| 선택지 | 판단 |
|---|---|
| Expo Go만 사용 | ❌ LiveKit(WebRTC) 네이티브 모듈을 쓸 수 없다 (LiveKit 공식 문서) |
| **Expo + prebuild + `expo-dev-client`** | ✅ 채택. `ios/` `android/`를 커밋하지 않고 `app.json` + config plugin에서 생성한다. 권한 문구, 백그라운드 모드, foreground service가 코드 리뷰 대상이 된다 |
| React Native CLI (bare) | 네이티브를 직접 고쳐야 할 때만. config plugin으로 안 되는 요구가 생기면 그 모듈만 local Expo module로 작성한다 |

- **Phase 1:** 네이티브 모듈이 `expo-secure-store`뿐이라 Expo Go로 실행할 수 있다.
- **Phase 5부터:** `expo-dev-client` 개발 빌드가 필수다. iOS는 EAS Build(Mac 없이 가능)나 Mac 로컬 빌드를 쓴다.
- `ios/`, `android/` 폴더는 생성물이므로 `.gitignore`에 넣는다. 요구안 폴더 구조에 있던 `ios/ android/`는 prebuild 후에만 존재한다.
- ⚠️ Windows 비ASCII 경로(`클로드작업`)에서는 Android Gradle 빌드가 실패할 수 있다 → 네이티브 빌드 전에 ASCII 경로로 옮긴다.

## 2. 폴더 구조

```text
apps/mobile/
├── index.ts                      # registerRootComponent
├── app.json                      # Expo config (권한·플러그인)
└── src/
    ├── app/                      # App 루트, providers(QueryClient·Theme·SafeArea)
    ├── navigation/               # RootNavigator, 타입 있는 route params
    ├── screens/{auth,home,library,reader,player,voice,settings,profile}/
    ├── components/{common,reader,player,scene,voice}/
    ├── features/                 # 도메인별 로직 (화면에 의존하지 않음)
    │   ├── auth/                 # authStore, tokenStorage, useBootstrapAuth
    │   ├── books/                # (Phase 2) queries
    │   ├── reading/              # playback 상태 표시 매핑, (Phase 3) NarrationPlayer
    │   ├── realtime/             # (Phase 5) RealtimeClient
    │   ├── voice/                # (Phase 10)
    │   └── scenes/               # (Phase 9)
    ├── services/api.ts           # api-client 인스턴스 (baseUrl, 토큰 연결)
    ├── stores/                   # 앱 전역 UI 상태 (settings)
    ├── theme/                    # tokens, ThemeProvider, useTheme
    ├── lib/                      # config(env), queryClient
    └── types/
```

규칙: `screens`는 `features`를 import할 수 있지만 반대 방향은 금지한다. `features`는 React Native UI에 의존하지 않는 로직을 우선한다 (테스트 용이).

## 3. 상태 관리 계층

"모든 상태를 React state 하나로 관리하지 않는다"를 다음 표로 구체화한다.

| 상태 종류 | 소유자 | 도구 | 예 |
|---|---|---|---|
| 서버 데이터 | 서버 | TanStack Query (캐시·재시도·무효화) | 책 목록, 책 상세, 세션 |
| 인증 | SecureStore ↔ 메모리 | Zustand `authStore` | 토큰, 로그인 여부 |
| 앱 설정 | 기기 | Zustand `settingsStore` | 테마, 재생 속도 기본값 |
| **재생 상태** | **네이티브 플레이어 또는 agent** | Zustand `playbackStore`(읽기 전용 사본) | 재생 중 여부, 현재 문장, ReadingState |
| 화면 로컬 | 컴포넌트 | `useState` | 입력값, 모달 열림 |

재생 상태는 JS가 "진실"을 갖지 않는다. Listen 모드에서는 네이티브 플레이어 이벤트가, Talk 모드에서는 agent의 `state` 메시지가 원천이다. 스토어는 그 이벤트를 **반영만** 한다. JS 스레드가 멈추거나 백그라운드에 있어도 네이티브 재생은 계속되고, 복귀 시 네이티브 상태로 다시 동기화한다.

### 3.0 낭독 재생 (Phase 3 ✅)

```text
Reader ─ play ─► NarrationController ─ POST /reading/sessions/{id}/audio (현재 문단 + 앞 2문단)
                      │                      ready → 서명 URL + 문장 타임스탬프
                      │                      pending → 1초 간격 재요청(최대 30초)
                      ├─► NarrationPlayer.load(url) → seekTo(문장 시작) → play
                      └─◄ playbackStatusUpdate(200ms) ─► 들리는 문장 계산
                                │
                    문장 변경 → Reader 하이라이트 + 위치 저장(PositionSaver)
                    문단 종료 → 다음 문단(장 경계면 다음 장 로드) 자동 재생
```

- 서명 URL은 만료 60초 전이면 재발급받는다. 사용자가 다른 문장으로 이동하면 진행 중인 준비 작업은 취소된다(`generation` 카운터).
- 오류는 코드별 한국어 메시지로 바꿔 보여준다: 준비 지연·권리 없음·재생 실패·네트워크.
- 백그라운드 재생과 잠금화면 컨트롤은 Phase 11이다. 지금은 화면이 꺼지면 재생이 멈춘다.

### 3.0b Talk 모드 연결 (Phase 5 ✅)

```text
Reader ─ 대화 시작 ─► TalkController
                       ├─ POST /v1/realtime/token        (연결마다 새 토큰: TTL 10분)
                       ├─ TalkTransport.connect(url, token)
                       ├─ publishMicrophone()            (권한 거부 → 즉시 연결 해제)
                       └─◄ data channel story.v1 ─► 모르는 type은 무시
```

- **`TalkTransport` 인터페이스 뒤에 LiveKit을 둔다.** 구현체는 네이티브 모듈이 필요해 개발 빌드에서만 돌아가므로, 연결 로직(토큰 재발급·밀려난 시도 정리·프로토콜 처리)은 가짜 transport로 기기 없이 테스트한다. 낭독 재생(`NarrationPlayer`)과 같은 규칙이다.
- `NativeModules.WebRTCModule` 유무로 **가용성을 먼저 판정**한다. Expo Go에서는 "대화 모드는 개발 빌드에서만 동작해요"를 보여주고, 사용자가 버튼을 눌렀을 때 실패하지 않는다.
- 연결마다 토큰을 새로 받는다. 10분 만료라 재연결 때 죽은 토큰을 재사용하면 실패하고, 서버가 권리·소유를 다시 확인하는 지점이기도 하다.
- 화면을 떠나면 room을 끊는다 — 아무도 듣지 않는데 agent가 붙어 있으면 실시간 비용이 계속 나간다.
- 마이크는 **에코 제거·노이즈 억제·자동 게인**을 켜고 publish한다(스피커로 나가는 낭독이 사용자 발화로 잡히면 barge-in이 오작동한다).
- **패키지 선택:** `@livekit/react-native` 래퍼 대신 `livekit-client` + `@livekit/react-native-webrtc`를 직접 쓴다. 래퍼가 웹용 `@livekit/components-react`를 끌고 오고, 그 peer `react-dom`이 Expo의 React(19.2.3)보다 새 React를 설치해 **React 사본이 2개**가 된다(모든 훅이 깨진다). 래퍼에서 실제로 필요한 건 `registerGlobals`(webrtc 패키지에 있음)와 오디오 세션 설정(expo-audio `setAudioModeAsync`가 이미 이 프로젝트의 오디오 모드 담당)이었다.
- 그래서 `react`·`react-dom`을 **워크스페이스 루트에 고정**한다. lockfile을 지우고 재설치하면 `expo`의 `peerOptional react-dom: "*"`가 최신 버전을 끌어와 같은 문제가 재발한다.
- 마이크 권한 문구는 `app.json`의 expo-audio 플러그인에 선언한다(OS 권한은 라이브러리별이 아니므로 한 곳에서 관리). Android는 `MODIFY_AUDIO_SETTINGS`도 필요하다 — WebRTC가 통화 중 오디오 경로를 바꾼다.
- ⚠️ 공식 `@livekit/react-native-expo-plugin`(1.0.2)은 SDK 2.x를 peer로 요구해 지금은 쓰지 않는다. 네이티브 빌드 때 플러그인이 하던 설정(iOS 백그라운드 오디오 모드 등)이 더 필요한지 확인한다.

### 3.1 Reader 데이터 흐름 (Phase 2 ✅)

- 책 전체를 받지 않는다: 목차(`GET /v1/books/{id}`) + 현재 장 본문(`GET .../chapters/{id}`, 10분 캐시)만 로드한다.
- 이동 계산은 순수 함수(`features/reading/navigation.ts`)가 하며, 장 경계를 넘으면 해당 장을 불러온 뒤 위치를 확정한다.
- **위치는 저장하지 않고 파생한다.** 상태는 "가고 싶은 위치"(`target`: 복구된 서버 위치, 장 넘김, 충돌 해결)와 "마지막으로 확정한 위치"(`committed`) 둘뿐이고, 화면에 쓰는 `location`은 `target`을 방금 도착한 장 본문에 대입해 렌더 중 계산한다. 장 본문이 늦게 도착한다고 이펙트에서 `setState`를 부르면 렌더가 한 번 더 돌고, React 19 동시 렌더링에서는 버려진 렌더의 값이 새어나간다. 도착 후의 부수효과(위치 저장, 장 넘김 자동 재생)만 이펙트에 남긴다 — `setState` 없이.
- 낭독 콜백은 렌더 주기 밖에서 실행되므로 최신 값을 ref로 읽지만, ref 쓰기는 **커밋 후 이펙트에서만** 한다. `react-hooks` ESLint 규칙(오류 수준)이 이 두 가지를 강제한다.
- 위치 저장은 `PositionSaver`가 직렬화한다: 요청 중에는 최신 위치 하나만 유지(latest-wins), `expected_version`으로 409를 받으면 멈추고 사용자에게 "이 기기 위치 / 다른 기기 위치"를 묻는다. 네트워크 실패 시 앱 포그라운드 복귀 때 재시도한다.
- 복구(세션 열기)는 저장 요청을 보내지 않는다.

## 4. 오디오 아키텍처 <a id="audio"></a>

### 4.1 두 경로

```text
                ┌──────────── PlayerFacade (UI가 쓰는 유일한 API) ───────────┐
                │ play() pause() seekSentence(±n) ask() state$ position$     │
                └───────────────┬──────────────────────────────┬─────────────┘
                                │                              │
                 ListenMode: NarrationPlayer          TalkMode: RealtimeClient
                 (expo-audio playlist)                (@livekit/react-native)
                 - 문장/문단 오디오 URL 큐            - mic publish (AEC)
                 - lock screen / remote command       - agent audio subscribe
                 - background playback                - data story.v1
                                │                              │
                                └──── ReadingPosition 동기화 ──┘
```

- **Listen → Talk (🎙 버튼):** 로컬 재생을 멈추고 현재 `(paragraph_id, sentence_index)`를 토큰 요청에 넣는다. agent가 그 위치에서 이어받는다. 연결되는 동안에는 "듣는 중" 상태를 먼저 보여 체감 지연을 줄인다.
- **Talk → Listen:** agent가 마지막 확정 위치를 보내면 room을 떠나고 로컬 큐를 그 위치부터 구성한다.
- 두 경로가 **동시에 소리를 내는 순간이 없어야 한다.** PlayerFacade가 전환을 직렬화한다 (전환 중 명령은 큐잉).

### 4.2 오디오 세션 설정

| | Listen 모드 | Talk 모드 |
|---|---|---|
| iOS category | playback (`interruptionMode: 'doNotMix'`, `shouldPlayInBackground: true`) | playAndRecord + voiceChat (LiveKit `AudioSession` 설정) |
| Android | media usage, audio focus GAIN | voice communication |
| 마이크 | 사용 안 함 | 사용 |

모드 전환은 오디오 세션 카테고리 전환을 동반한다. iOS에서는 전환 시 짧은 끊김·라우팅 변경(스피커↔수화부)이 생길 수 있으므로 Phase 5 실기기 검증 항목이다.

### 4.3 NarrationPlayer 선택

`expo-audio`(SDK 57)는 `useAudioPlaylist`, `setActiveForLockScreen`, background playback config plugin을 제공한다. Phase 3 spike에서 아래 기준으로 `react-native-track-player`와 비교해 확정한다.

**Phase 3 결정 (2026-09-16):** `expo-audio`를 채택했다. SDK와 함께 유지보수되고, 백그라운드 재생·잠금화면·플레이리스트를 config plugin으로 지원하며, 컴포넌트 밖에서도 `createAudioPlayer`/`addListener('playbackStatusUpdate')`로 제어할 수 있다. `NarrationPlayer` 인터페이스 뒤에 있으므로 실기기 테스트(Phase 11)에서 아래 기준에 미달하면 `react-native-track-player`로 교체한다. 또한 config plugin의 기본값(마이크 권한, 백그라운드 재생 foreground service)은 **끄고** 시작한다 — 마이크는 Phase 5, 백그라운드는 Phase 11에서 의도적으로 켠다.

| 기준 | 합격선 |
|---|---|
| 문장 단위 짧은 파일 수백 개 연속 재생 시 gap | 체감 불가 (< 50ms) → 부족하면 문단 단위 파일 + 문장 타임스탬프 방식 |
| 화면 꺼짐 30분 연속 재생 | 중단 없음 (iOS/Android) |
| 잠금화면·이어폰 버튼 | 재생/일시정지/±문장 |
| 전화 수신·다른 앱 오디오 인터럽션 | 일시정지 후 복귀 가능 |
| 블루투스 연결 해제 | 자동 일시정지 |

**Phase 3에서 선택한 방식: 문단 파일 + 문장 타임스탬프.** 서버가 문장 오디오를 이어 붙여 문단 파일 하나를 만들고 `[{sentence_index, start_ms, end_ms}]`를 함께 준다. 재생 중 이음새가 없고, 들리는 문장은 재생 위치로 계산한다(`features/narration/timeline.ts`).

**문장 단위 vs 문단 단위 파일:** 문장 단위는 캐시·재개 정밀도가 좋지만 파일 수가 많다. 문단 단위 파일 + 서버가 제공하는 문장 타임스탬프(`[{sentence_index, start_ms, end_ms}]`)는 gap이 없다. **기본안은 문단 파일 + 타임스탬프**이고, spike 결과로 확정한다.

## 5. 백그라운드 정책 <a id="background"></a>

| 기능 | 포그라운드 | 백그라운드/화면 꺼짐 | 근거 |
|---|---|---|---|
| 낭독 재생 | ✅ | ✅ | iOS `audio` background mode, Android foreground service (expo-audio plugin `enableBackgroundPlayback`) |
| 재생 제어 (잠금화면·알림·이어폰) | ✅ | ✅ | lock screen / MediaSession |
| 위치 저장 | ✅ | ✅ (네트워크 가능 시, 실패하면 로컬 저장 후 복귀 시 동기화) | |
| 다음 오디오 prefetch | ✅ | 제한적 | OS가 네트워크를 지연시킬 수 있음 → 앞 N개를 포그라운드에서 미리 받는다 |
| **음성 barge-in (Talk)** | ✅ | ❌ **비활성** | 화면 꺼진 상태에서 상시 마이크는 심사·배터리·프라이버시 위험. 백그라운드 전환 시 Talk → Listen으로 자동 전환 |
| 버튼으로 질문 시작 | ✅ | 잠금화면 버튼 → 앱 열림 후 Talk | iOS는 백그라운드에서 마이크 세션을 새로 시작할 수 없다 |
| Scene 이미지 | ✅ | — | 표시할 화면 없음 |

## 6. 인증·네트워크

- Access token(15분)은 메모리에만, refresh token은 `expo-secure-store`에 저장한다 (`keychainAccessible: AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY` — 잠금 상태 백그라운드 재생 중 토큰 갱신이 가능해야 하고, iCloud 백업으로 다른 기기에 옮겨지면 안 된다).
- API client는 401을 받으면 **single-flight refresh**(동시에 여러 요청이 401을 받아도 refresh 1회)를 한 뒤 원래 요청을 1회 재시도한다. refresh가 실패하면 로그아웃한다.
- 앱에는 **어떤 provider key도 없다.** `EXPO_PUBLIC_*` 환경변수는 앱 번들에 그대로 들어가므로 공개 가능한 값(API URL)만 둔다.
- API 타입은 FastAPI OpenAPI → `packages/shared-types` 자동 생성 (`npm run gen:api`). 손으로 쓴 요청/응답 타입이 서버와 어긋나는 것을 막는다.
- API 버전 prefix `/v1`: 모바일은 강제 업데이트가 어렵기 때문에 구 버전 앱이 계속 호출할 수 있어야 한다.

## 7. UI

### 7.1 화면 (Phase 1 구현 범위 ✅)

| 화면 | Phase | 비고 |
|---|---|---|
| Splash ✅ | 1 | 토큰 복구 중 표시 |
| Login / Register ✅ | 1 | 이메일. Apple/Google 버튼은 네이티브 SDK 연동 시(Phase 5 개발 빌드) 활성화 |
| Home ✅ | 1 | 이어 듣기 카드 (Phase 2에서 실데이터) |
| Library ✅ | 1 | 빈 상태 + 목록 UI (Phase 2 API 연동) |
| BookDetail ✅ | 2 | 목차, 진행률, 읽기 시작/이어 읽기 |
| Reader ✅ | 1 → 2 → 3 | Phase 2: 서버 세션 복구, 장 단위 로드, 위치 저장·충돌 처리, 재생 상태(서버 상태 머신). 오디오는 Phase 3 |
| Player | 3 | 전체화면 플레이어 |
| Conversation | 6 | 질문·답변 자막 |
| VoiceProfile / VoiceRecording | 10 | |
| Settings ✅ | 1 | 테마(시스템/라이트/다크), 로그아웃, 계정 삭제 |
| Profile | 2 | |

### 7.2 Reader 상태 표시

| ReadingState | 표시 |
|---|---|
| READING | ● 읽는 중 |
| USER_SPEAKING, AWAITING_FOLLOWUP | ● 듣는 중 |
| PROCESSING_QUESTION | ● 생각 중 |
| ANSWERING | ● 답변 중 |
| RESUMING | ● 다시 읽는 중 |
| PAUSED | 일시정지 |
| PREPARING | 준비 중 |
| ERROR | 연결 문제 |

Scene 이미지 전환은 cross-fade(300~500ms)로 하고, 다음 scene 이미지는 문장 진행에 맞춰 미리 prefetch한다.

### 7.3 테마

`src/theme/tokens.ts`에 light/dark 색상·간격·타이포 토큰을 정의하고 `useTheme()`으로 쓴다. 기본값은 시스템 설정을 따르고, 설정 화면에서 바꿀 수 있다. 토큰 구조는 NativeWind 도입 시 Tailwind theme으로 옮길 수 있게 평평하게 유지한다.

### 7.4 접근성

모든 버튼에 `accessibilityLabel`을 단다. 상태 표시는 `accessibilityLiveRegion`(Android) / announcement(iOS)로 알린다. 오디오 앱이므로 시각 장애 사용자에게 특히 중요하다.

## 8. 테스트 <a id="testing"></a>

| 레벨 | 도구 | 대상 |
|---|---|---|
| 단위 | Jest (`jest-expo`) | 스토어, API client refresh, 상태 라벨 매핑, 폼 검증 |
| 컴포넌트 | React Native Testing Library | 화면 렌더·상호작용 |
| E2E | Maestro (Phase 3~) | 로그인 → 책 → 재생 → 일시정지 |
| 실기기 매트릭스 (Phase 11) | 수동 + 체크리스트 | iPhone(구형/신형) × Android(삼성/픽셀) × 스피커/유선/블루투스 × 화면꺼짐/전화수신/다른 앱 오디오/앱 강제종료 후 복귀 |

## 9. 스토어 대응

| 항목 | iOS | Android |
|---|---|---|
| 마이크 권한 문구 | `NSMicrophoneUsageDescription` (config plugin) | `RECORD_AUDIO` |
| 백그라운드 | `UIBackgroundModes: audio` | foreground service `mediaPlayback` 타입 선언 + Play Console 신고 |
| 계정 삭제 | 앱 내 삭제 제공 필수 → Settings에 구현 ✅ | Play 데이터 삭제 정책 + 웹 삭제 요청 URL |
| 로그인 | 제3자 로그인 제공 시 Sign in with Apple 필요 | — |
| 결제 | 디지털 콘텐츠 IAP | Google Play Billing |
| 개인정보 | Privacy Nutrition Label, Privacy Manifest | Data safety form |
