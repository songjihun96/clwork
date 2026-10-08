# UDJ 소개영상 에셋 목록

모든 에셋은 `hs-portal/video/` 아래에 있다. 기존 서비스 코드(frontend/backend)는 수정하지 않았고,
`scripts/build_deploy_zip.py` 는 경로를 지정해 담기 때문에 `video/` 는 배포 zip 에 섞이지 않는다.

## 1. 실제 화면 캡처 — `video/assets/screenshots/`

- 캡처 도구: Playwright(`playwright-core`) + 설치된 Microsoft Edge, 뷰포트 1440×900, deviceScaleFactor 2 → 가로 2880px PNG
- 캡처 일시: 2026-10-02, 대상 https://udjschool.ggm.kr/ (비로그인)
- 스크립트: `video/src/capture/capture.mjs` (`npm run capture` 로 언제든 다시 찍을 수 있다)
- 요소 좌표(하이라이트·커서 위치용): `rects.json`

| 파일 | 실제 URL | 상태 | 영상 사용 |
|---|---|---|---|
| home_viewport.png | / | 첫 화면 | 소개·엔딩·홈 |
| home_full.png | / | 전체 페이지 | 홈 |
| search_top.png | /search | 초기 | 학교 검색 |
| search_typed.png | /search | 이름 "공업", 지역 "경기" 입력 | 학교 검색 |
| search_result_full.png | /search | 검색 결과 7개 | 학교 검색·정리·몽타주 |
| search_dept_select.png | /search | 학과 계열 "IT·소프트웨어" 선택 | 60s 학교 검색 |
| search_dept_full.png | /search | 학과 계열 결과 136개 | 60s 학교 검색 |
| search_compare_tray.png | /search | 비교 담기 3곳 | 학교 비교 |
| search_compare_modal.png | /search | 나란히 비교 | 학교 비교·정리 |
| search_map.png | /search | 지역 "서울" 72개교 지도 | 지도·정리 |
| school_25_viewport.png / school_25_full.png | /schools/25 | 서울공업고등학교 | 학교 정보·정리·몽타주 |
| school_262_viewport.png / school_262_full.png | /schools/262 | 근명고등학교(빠른 문의 가능) | 학교 문의 |
| admission_viewport.png / admission_full.png | /schools/262/admission | **학교명 → "예시고등학교" 치환, 가상 데이터** | 취업·진학 정보 |
| quiz_intro.png / quiz_intro_full.png | /quiz | 시작 화면 | 진로 테스트 |
| quiz_question.png | /quiz | 7/36 문항 | 진로 테스트 |
| quiz_result_viewport.png / quiz_result_full.png | /quiz | 실제 응답 결과(위치 없이, 전국) | 진로 테스트·정리·몽타주 |
| signup.png | /signup | 학생·학부모 회원가입 | 이용 대상 |
| school_account_request.png | /school-account-request | 학교 계정 신청 | 이용 대상 |
| events.png | /events | 학교 일정(현재 일정 0건) | **미사용** |

캡처할 때 손댄 것(화면 내용은 그대로):
- 우하단 "오프라인 직업계고설명회 신청" 플로팅 버튼(외부 사이트 링크) 숨김
- 홈 슬라이드가 전환 도중 찍혀 사진 두 장이 겹치지 않도록 CSS 전환 효과 끔
- 운영 통계를 건드리지 않도록 **학교 조회수·방문자 집계 POST 요청 차단**(화면의 방문자 수는 실제 값을 그대로 받아 그림). 검색 목록 노출 집계(GET 안에서 처리)는 막을 수 없어 캡처 중 몇 건 기록됐을 수 있다.
- 취업/진학 정보: 학교명 텍스트만 "예시고등학교"로 치환(사용자 요청: 임의 데이터 → 가상 데이터 처리)

## 2. 로고 — `video/assets/logos/`

| 파일 | 설명 |
|---|---|
| udj_mark.svg | 사이트 헤더의 "ㅇㅈ" 검정 마크를 사이트 CSS(`.brand-mark`)대로 다시 그린 것 |
| udj_lockup.svg | 마크 + "우리동네 직업계고" + UDJ 배지 |
| favicon.svg | 사이트 `frontend/public/favicon.svg` 원본 사본 |

## 3. 아이콘 — `video/assets/icons/`

영상 전용으로 직접 그린 단순 선 아이콘(24×24, stroke). 외부 아이콘 세트 사용 안 함.
search · map · school · compare · chart · compass · user · family · building · home · mail · link (`.svg` 각 1개, 원본은 `video/src/remotion/components/Icons.tsx`)

## 4. 오디오 — `video/assets/audio/`

| 파일 | 설명 | 라이선스 |
|---|---|---|
| narration/{90s,60s,30s,15s}/*.wav | 장면별 나레이션(문장 단위, 앞뒤 무음 제거, 48kHz) | Microsoft Edge 신경망 TTS(`edge-tts`, ko-KR-SunHiNeural)로 생성. 정식 광고 송출 전에는 성우 녹음 교체를 권장(원고: `docs/UDJ_VIDEO_SCRIPT.md`) |
| bgm_{90s,60s,30s,15s}.wav | 배경음악 | **직접 합성**(`video/src/script/build_bgm.py`, numpy) — 외부 음원 미사용, 저작권 문제 없음. D장조 112BPM, D–A–Bm–G 진행, 마지막은 D 화음 |

믹스: BGM 기본 볼륨 0.20, 나레이션 중 0.075 로 자동 감쇠(앞뒤 0.25초 램프) → 최종 -16 LUFS 로 정규화.

## 5. 글꼴

- Pretendard Variable (`video/src/public/fonts/PretendardVariable.woff2`) — 사이트 본문 글꼴과 동일, SIL Open Font License 1.1 (`LICENSE-Pretendard.txt` 동봉)

## 6. 소스 — `video/src/`

```
video/src/
├── package.json            remotion 4 · @remotion/renderer · playwright-core
├── capture/capture.mjs     실제 사이트 캡처
├── script/
│   ├── narration.json      버전별 나레이션·자막 원고
│   ├── build_audio.py      TTS → 무음 제거 → 장면 타이밍(timeline.json) + SRT
│   └── build_bgm.py        BGM 합성
├── remotion/               영상 구성(React)
│   ├── Main.tsx            장면 배치·나레이션·BGM 더킹
│   ├── scenes/Scenes.tsx   장면 11종
│   ├── components/         BrowserFrame(카메라) · Overlays(하이라이트/커서/타이핑/가상데이터 배지) · UI · Icons
│   ├── rects.json          캡처 요소 좌표
│   └── timeline.json       버전별 장면·문장 프레임
├── public/                 렌더용 캡처·오디오·글꼴 사본
├── subtitles/*.srt         자막 파일
└── render.mjs              렌더 → yuv420p BT.709 재인코딩 + -16 LUFS + faststart
```

## 7. 다시 만들기

```bash
cd hs-portal/video/src
npm install
npm run capture                 # 실제 화면 다시 캡처 (사이트가 바뀌었을 때)
python script/build_audio.py    # 나레이션·타이밍·자막 (pip: edge-tts numpy)
python script/build_bgm.py      # BGM
node render.mjs                 # 4개 버전 렌더 (8코어 기준 약 20분)
node render.mjs --stills 90s    # 검수용 정지 화면만
npm run studio                  # Remotion Studio 로 미리보기·수정
```
