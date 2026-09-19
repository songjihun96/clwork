# Security & Privacy

> ✅ Phase 1 구현 · 🔜 설계만 (구현 Phase 표시)
> ⚖️ 표시 항목은 **법률 검토가 필요**하다. 이 문서는 법률 자문이 아니다.

## 1. 위협 모델 (요약)

| 자산 | 위협 | 대응 |
|---|---|---|
| 계정 | credential stuffing, 토큰 탈취 | argon2id, rate limit, 짧은 access token, refresh 회전 + 재사용 탐지 |
| 사용자 음성 샘플·voice id | 유출 → 목소리 도용 | private bucket, 암호화, 짧은 signed URL, 보관기한, 접근 감사 |
| 타인 목소리 무단 등록 | 사칭·사기 | 본인 확인 스크립트 낭독, 동의 기록, (향후) 화자 검증·유명인 목소리 차단 |
| 책 원문 | 대량 추출 (RAG 답변으로 원문 복원) | 답변 길이 제한, 연속 인용 탐지, 사용자별 rate limit |
| AI provider 키 | 앱 역공학 | 키는 서버에만. 앱 번들에는 공개 설정만 |
| LLM | 프롬프트 인젝션 (책 본문·사용자 발화에 지시문) | LLM에 도구·상태 변경 권한 없음. 출력은 텍스트로만 사용 |
| 업로드 파일 | 악성 epub (zip bomb, XXE) | 크기·압축 비율 제한, XML 파서 외부 엔티티 비활성, 격리 worker |
| 인프라 | secret 유출 | secret manager, 최소 권한 IAM, 로그 마스킹 |

## 2. 인증 ✅

| 항목 | 결정 |
|---|---|
| 비밀번호 | argon2id (`argon2-cffi` 기본 파라미터), 8~128자. 존재하지 않는 이메일로 로그인해도 더미 해시를 검증해 **응답 시간 차이로 가입 여부를 알 수 없게** 한다 |
| Access token | JWT HS256, 15분, claims: `sub`, `iat`, `exp`, `jti`, `typ=access`, `iss`, `aud`. secret은 32바이트 이상, 운영에서 기본값이면 **기동 거부** |
| Refresh token | 256bit 랜덤 opaque 문자열. DB에는 SHA-256만 저장. 30일. **사용할 때마다 회전**하고, 이미 회전된 토큰이 다시 오면 탈취로 보고 family 전체를 폐기 + 감사 로그 |
| 로그아웃 | 해당 refresh family 폐기 |
| 계정 삭제 | 비밀번호 재확인(소셜 계정은 최근 로그인) → 사용자 행 삭제(cascade) → 외부 리소스 삭제 작업 큐 등록(Phase 10~) → 감사 로그 |
| Apple / Google | 앱이 네이티브 SDK로 받은 **ID token**을 서버가 JWKS로 검증 (`iss`, `aud`=등록된 client id, `exp`, Apple은 `nonce`). client id 미설정 시 503 |
| 계정 연결 | `(provider, subject)`로 식별한다. 소셜 이메일이 기존 이메일 계정과 같아도 **자동으로 합치지 않는다** (이메일 소유 검증 수준이 provider마다 달라 계정 탈취 경로가 된다) → 409 반환, 로그인 후 연결 기능 제공(Phase 12) |
| 서버 JWT 대안 | 외부 IdP(Auth0, Cognito 등)로 이전할 수 있게 토큰 발급·검증을 `security/tokens.py`에 격리했다 |

## 3. API 보안

| 항목 | 상태 |
|---|---|
| HTTPS | 로드밸런서/Cloudflare에서 TLS 종료, HSTS. 앱은 `https://` 외 거부 (개발 빌드 제외) 🔜 |
| Rate limit ✅ | Redis fixed-window. 로그인: IP당 + 이메일당, 가입: IP당. 초과 시 429 + `Retry-After`. 프록시 뒤에서는 `TRUSTED_PROXY_COUNT`만큼만 `X-Forwarded-For`를 신뢰 |
| Validation ✅ | 모든 요청 body Pydantic 모델, `extra="forbid"`, 문자열 길이 상한 |
| 에러 ✅ | 내부 예외 메시지·스택을 응답에 노출하지 않는다. `{"error": {"code", "message", "request_id"}}` |
| CORS ✅ | 네이티브 앱은 CORS 대상이 아니다. 기본 허용 origin 없음, 관리 웹이 생기면 명시 origin만 |
| 보안 헤더 ✅ | `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`(인증 응답) |
| SQL injection ✅ | ORM 바인딩만 사용, raw SQL 금지 (예외 시 `text()` + bind param, 리뷰 필수) |
| XSS | API는 JSON만 반환. 사용자 입력을 HTML로 렌더링하는 관리자 웹이 생기면 출력 인코딩 🔜 |
| OpenAPI 문서 | 운영에서는 `/docs` 비활성 ✅ |

## 4. 파일 업로드 (책: Phase 2 ✅ / 음성: Phase 10 🔜)

1. 크기 상한 (epub 50MB, 음성 샘플 10MB) — 스트리밍 중 초과하면 즉시 중단
2. 확장자 + **매직 바이트** 검사 (클라이언트 MIME은 신뢰하지 않음)
3. epub: zip 엔트리 수·총 해제 크기·압축비 상한, 경로 순회(`../`) 거부, `defusedxml`로 파싱
4. 음성: 서버에서 디코딩 가능 여부·길이·샘플레이트 확인 후 표준 포맷(16/24kHz mono)으로 재인코딩. 원본 파일을 그대로 provider에 넘기지 않음
5. 격리된 worker에서 처리. 악성코드 검사(ClamAV 사이드카 등)는 `MalwareScanner` 인터페이스로 둔다
6. 업로드는 presigned PUT → 검사 완료 전까지 `quarantine/` prefix → 통과 시 이동 🔜 (Phase 3, S3/R2 도입 시)

**Phase 2 구현 상태 (책 업로드, 관리자 전용):** ✅ 스트리밍 크기 제한(`BOOK_UPLOAD_MAX_BYTES`, Content-Length 선검사) · ✅ 매직 바이트/내용 기반 형식 판별(파일명·MIME 무시) · ✅ UTF-8 엄격 디코딩·NUL 거부 · ✅ zip 엔트리 수·해제 크기·압축비·경로 순회 제한 · ✅ defusedxml(엔티티 확장 차단 테스트) · ✅ `UploadScanner` 훅(현재 no-op, 운영 전 실제 스캐너 필수) · ✅ 저장 키는 `books/<uuid>/source/<sha256>.<ext>`(사용자 파일명 미사용) · ✅ DB 실패 시 저장된 원본 삭제 · ✅ 업로드·권리 변경·처리 요청 감사 로그. 리버스 프록시에서도 요청 본문 크기를 제한해야 한다(chunked 업로드는 앱에 도달하기 전에 버퍼링될 수 있음).

## 5. 저장소

**미디어 링크 (Phase 3 ✅)** — 오디오 플레이어는 Authorization 헤더를 붙일 수 없어 서명 URL이 자격증명이다.
- 로컬 저장소: `/v1/media/*`가 HMAC-SHA256 서명(객체 키 + 만료시각)을 검증한 뒤에만 파일을 스트리밍한다. 서명을 위조하거나 만료를 늘리거나 다른 객체로 바꾸면 403이다(테스트 있음). 기본 TTL 1시간.
- S3/R2: presigned GET URL.
- 서명 비밀키(`MEDIA_SIGNING_SECRET`)는 JWT secret과 **달라야** 하며, 운영에서 기본값이면 기동을 거부한다.
- 오디오 요청은 세션 소유자 확인 + 책 권리(`audio_rights`) 확인을 통과해야 발급된다. 권리가 사라지면 즉시 `unavailable`이 된다.


- 버킷은 전부 **private**이다. 공개 CDN으로 서빙하는 것은 권리 확인된 **책 표지·scene 이미지·기본 목소리 오디오**뿐이며, 이것도 signed URL(또는 signed cookie)로 제공한다.
- 목소리 샘플, 사용자 목소리 파생 오디오: 별도 버킷, SSE-KMS, signed URL TTL ≤ 5분, CDN 캐시 금지.
- 객체 키에 이메일·이름 같은 개인정보를 넣지 않는다 (UUID만).

## 6. 음성 데이터 보호 <a id="voice"></a> 🔜 (Phase 10)

### 6.1 등록 흐름

```text
1. 마이크 권한 요청 (OS)
2. 동의 화면 — 목적(본인 목소리로 낭독), 처리 위탁 provider, 보관기간, 삭제 방법, 금지 행위(타인 목소리 등록)
   → 명시적 체크 + consent_text_version / hash 기록                                   ⚖️ 민감정보 별도 동의 필요 여부
3. 본인 확인 스크립트 낭독 (서버가 무작위 문장 제시 → 녹음 → STT로 일치 확인)
   → 녹음 파일 재생·이어붙이기로 타인 목소리를 등록하는 것을 어렵게 한다
4. 품질 검사: 길이, 무음 비율, 클리핑, SNR 추정, 화자 1명 여부
5. provider에 voice 생성 → provider_voice_id 암호화 저장
6. VoiceProfile ready
```

### 6.2 규칙

- 원본 샘플은 voice 생성 후 **N일(기본 30일, 재생성용) 경과 시 자동 삭제**한다 (`purge_after`).
- provider 계약에서 확인할 것: 학습 재사용 금지 옵션, 삭제 API와 삭제 완료 보장, 데이터 저장 리전.
- 목소리 삭제 요청 → `voice_profiles.status=deleting` → 작업: provider voice 삭제 → 샘플 삭제 → `audio_assets WHERE voice_profile_id` 삭제 → `deleted` + 감사 로그. 단계별로 재시도하고, 실패는 알림을 보낸다.
- 사용자 목소리로 만든 오디오는 **그 사용자에게만** 제공한다 (캐시 공유 금지, URL 추측 불가).
- 향후 정책 계층 `VoicePolicy`: 화자 검증(등록 음성 ↔ 계정 소유자), 유명인·공인 목소리 유사도 차단 목록, 신고 처리.
- ⚖️ 음성 복제용 음성의 개인정보보호법상 성격(생체인식정보·민감정보), 퍼블리시티권, 「인공지능 기본법」 생성물 고지 의무.

## 7. 로그와 개인정보 ✅ (기반) / 🔜

- 로그는 JSON 구조화 로그다. **요청·응답 body를 기록하지 않는다.** 기록하는 것: route 템플릿, status, latency, request_id, user_id(내부 UUID).
- 로그 formatter가 `password`, `token`, `authorization`, `refresh_token`, `id_token`, `audio`, `text`, `prompt`, `transcript`, `email` 키를 마스킹한다 ✅ (테스트 있음).
- Sentry: `send_default_pii=False`, request body 수집 끔 ✅.
- 사용자 발화 원문·책 원문·오디오는 일반 로그/트레이스에 넣지 않는다. 디버깅용 오디오 녹음은 운영에서 **코드 경로 자체가 비활성**이다.
- Phase 4에서 추가된 경로도 같은 규칙을 따른다: 질문·답변 원문은 `conversation_messages`에만 저장하고 로그에는 근거 개수·구간별 지연·`guard_action`만 남긴다 ✅. AI 공급사 오류 메시지는 **오류 코드만** 뽑아 기록한다 — 응답 본문을 그대로 로그에 넣으면 프롬프트(책 원문)가 함께 새기 때문이다(테스트로 고정).

## 8. 보관기간·삭제 <a id="retention"></a> 🔜

| 데이터 | 기본 보관 | 비고 |
|---|---|---|
| 계정 | 탈퇴 시 즉시 삭제 | 법정 보관 의무 데이터(결제 기록 등)는 분리 보관 ⚖️ |
| refresh token | 만료 + 7일 후 삭제 | 배치 |
| 대화 기록 | 90일 (설정에서 끄기·삭제 가능) | 학습 활용은 별도 동의. Phase 4에서 테이블은 생겼고(`conversations`/`conversation_messages`, 세션·계정에 `ON DELETE CASCADE`) **90일 삭제 배치와 사용자 설정은 Phase 12** 🔜 |
| 음성 샘플 | voice 생성 후 30일 | |
| 사용자 목소리 파생 오디오 | 마지막 접근 후 30일 | |
| 감사 로그 | 1년 | user_id는 탈퇴 후 가명화 |
| 애플리케이션 로그 | 30일 | |
| 백업 | PITR 기간 | 삭제된 데이터는 백업 만료로 자연 소멸. 처리방침에 명시 |

## 9. Secret 관리

- 개발: `.env` (git 제외, `.env.example`만 커밋) ✅
- 운영: secret manager → 컨테이너 환경변수 주입. 이미지에 secret을 굽지 않는다.
- 회전: JWT secret은 `kid` 기반 다중 키 검증 구조로 확장 (Phase 12). provider 키는 분기마다 회전.
- 커밋 전 secret 스캔(gitleaks 등)을 pre-commit/CI에 넣는다 (Phase 12). **기존 프로토타입의 하드코딩 토큰 사고 재발 방지.**

## 10. 감사 로그 ✅ (기반)

기록 대상: 로그인 성공/실패(이메일은 저장 안 함), refresh 재사용 탐지, 로그아웃, 계정 삭제, (향후) 목소리 등록·삭제·동의 철회, 책 권리 정보 변경, 관리자 행위.
