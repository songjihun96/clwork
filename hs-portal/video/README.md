# UDJ(우리동네 직업계고) 서비스 소개영상

실제 운영 사이트 https://udjschool.ggm.kr/ 화면을 캡처해 만든 서비스 소개·홍보 영상과 그 제작 소스.
기존 서비스 코드(frontend/backend)는 건드리지 않는다. 배포 zip(`scripts/build_deploy_zip.py`)에도 들어가지 않는다.

| 파일 | 길이 | 용도 |
|---|---|---|
| main/udj_intro_90s.mp4 | 90초 | 서비스 소개영상 |
| main/udj_intro_60s.mp4 | 60초 | 홍보영상 |
| shorts/udj_intro_30s.mp4 | 30초 | 짧은 홍보영상 |
| shorts/udj_intro_15s.mp4 | 15초 | 숏폼 |

공통 규격: 1920×1080, 60fps, H.264 High(yuv420p, BT.709), AAC 48kHz 192kbps, -16 LUFS, faststart.
자막 파일: `src/subtitles/*.srt` (영상에는 자막이 이미 입혀져 있다 — 플랫폼 자막용으로 따로 올릴 때 사용)

문서: `../docs/UDJ_SERVICE_FEATURES_FOR_VIDEO.md`, `UDJ_VIDEO_STORYBOARD.md`, `UDJ_VIDEO_SCRIPT.md`, `UDJ_VIDEO_ASSETS.md`

## 다시 만들기

```bash
cd video/src
npm install
python -m pip install edge-tts numpy
npm run capture                # 실제 사이트 다시 캡처 (Edge 사용)
python script/build_audio.py   # 나레이션 TTS + 장면 타이밍 + SRT
python script/build_bgm.py     # BGM 합성
node render.mjs                # 4개 버전 렌더 → main/, shorts/
```

- 미리보기·수정: `npm run studio` (Remotion Studio)
- 검수용 정지 화면: `node render.mjs --stills 90s` → `src/review/90s/`
- 사이트 화면이 바뀌면 `npm run capture` 후 `src/remotion/scenes/Scenes.tsx` 의 카메라 좌표(CSS px)를 확인한다.

## 주의

- **취업/진학 정보 장면은 가상 데이터 예시**다(현재 공개된 학교 자료가 임의 입력값). 실제 학교 자료가 공개되면 `capture.mjs` 의 학교명 치환을 빼고 다시 캡처한다.
- 나레이션은 TTS(Microsoft Edge 신경망 음성)다. 방송·유료 광고로 송출하기 전에는 성우 녹음으로 바꾸는 것을 권한다 → `../docs/UDJ_VIDEO_SCRIPT.md` 끝부분 참고.
- BGM 은 직접 합성한 음원이라 저작권 문제가 없다.

---

## 학교·교사용 기능 소개영상 (2026-10-02)

| 파일 | 길이 | 내용 | 상태 |
|---|---|---|---|
| full/udj_school_teacher_full.mp4 | 7:04 | 통합본(챕터 바 포함) | 2026-10-06 특성화고신문 보도자료 장면 추가 |
| school/udj_school_intro.mp4 | 1:47 | 학교 도입 전체 흐름 | 필요할 때 `node render_school.mjs school_intro` |
| school/udj_school_admin.mp4 | 2:20 | 학교 관리자 기능(학교 계정) | ⚠ 화살표 수정 전 버전 — `node render_school.mjs school_admin` 으로 다시 |
| teacher/udj_teacher_guide.mp4 | 2:31 | 담당 선생님 업무 가이드(학교 계정으로 하는 일) | 필요할 때 `node render_school.mjs teacher_guide` |
| student/udj_student_service.mp4 | 1:55 | 학생 서비스 | 필요할 때 `node render_school.mjs student_service` |

렌더는 2분 단위 구간으로 나눠 하고(`src/.render_chunks/`), 중간에 끊겨도 다시 실행하면 남은 구간부터 이어서 한다.

- UDJ에서는 선생님(teacher) 권한을 없애기로 해서 `/teacher` 화면은 다루지 않는다.
- 학교 계정 화면은 **시연 환경**(`school-demo/` — 실제 UDJ 코드 + 테스트 DB + 가상 데이터)에서 실제로 조작하며 찍었다. 운영 사이트에는 로그인하지 않는다.
- 문서: `../docs/UDJ_SCHOOL_TEACHER_FEATURES.md`, `UDJ_SCHOOL_VIDEO_STORYBOARD.md`, `UDJ_SCHOOL_VIDEO_SCRIPT.md`, `UDJ_TEACHER_VIDEO_SCRIPT.md`, `UDJ_VIDEO_SCREEN_LIST.md`

```bash
# 1) 시연 환경 (처음 한 번)
cd video/school-demo && python -m venv .venv && .venv/Scripts/python.exe -m pip install -r ../../backend/requirements.txt
# 2) 시연 서버: .claude/launch.json 의 udj-demo-backend(8800) · udj-demo-frontend(5190)
# 3) 캡처 → 음성 → BGM → 렌더
cd ../src
node capture/capture_school.mjs
python script/build_school_audio.py
python script/build_bgm.py
python script/build_school_docs.py
node render_school.mjs                 # 5개 영상 (8코어 약 1시간 30분)
node render_school.mjs --stills school_teacher_full   # 검수용 정지 화면
```
