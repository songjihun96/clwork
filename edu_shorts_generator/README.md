# 교육 쇼츠 자동 생성기 (edu_shorts_generator)

긴 교육 영상(강의/수업/특강/설명 영상)을 분석해서, **학습 가치가 높은 구간만** 골라
1분 내외의 세로형(9:16) 교육 쇼츠로 자동 변환하는 로컬 데스크톱 앱입니다.

- 조회수가 아니라 **학습 가치**를 기준으로 구간을 고릅니다(핵심 개념성, 독립적 이해
  가능성, 설명 완결성, 오개념 방지 등 10개 항목 채점).
- 음성 인식은 **로컬 Whisper**(무료, 인터넷/과금 불필요)를 사용합니다.
- 구간별 교육적 가치 채점은 **Claude API**(Anthropic)를 사용합니다.

## 1. 설치 (처음 한 번만)

### 1) Python
Python 3.10 ~ 3.13 권장. [python.org](https://www.python.org/downloads/)에서 설치.

### 2) ffmpeg
Whisper와 영상 자르기/자막 굽기/세로 변환에 모두 필요합니다.

- https://www.gyan.dev/ffmpeg/builds/ 에서 "release essentials" zip 다운로드
- 압축을 풀고 `bin` 폴더 안의 `ffmpeg.exe`, `ffprobe.exe` 를 이 프로그램 폴더 밑
  `ffmpeg/` 폴더에 복사하거나 (`edu_shorts_generator/ffmpeg/ffmpeg.exe`),
  시스템 PATH 환경변수에 ffmpeg의 `bin` 폴더를 추가하세요.
- **다른 PC로 배포할 때도 `ffmpeg/` 폴더를 프로그램과 함께 통째로 복사**하면
  그 PC에 ffmpeg를 따로 설치하지 않아도 동작합니다.

### 3) 파이썬 패키지 설치
```bash
cd edu_shorts_generator
pip install -r requirements.txt
```
(`openai-whisper`, `torch` 설치는 용량이 크고 시간이 좀 걸립니다. GPU가 있으면
자동으로 활용되어 더 빠릅니다.)

### 4) Anthropic API 키
1. https://console.anthropic.com 에서 API 키 발급 (유료, 사용한 만큼 과금)
2. 앱 실행 → "설정" 버튼 → API 키 입력 → 저장
   (이 PC의 `secrets.json` 파일에만 로컬 저장되며 어디로도 전송되지 않습니다.
   이 파일을 다른 사람과 공유하지 마세요.)

비용 참고: Claude Sonnet 기준 1시간 강의 1개 분석에 대략 몇십~백원 수준입니다
(영상 길이·쇼츠 개수에 따라 달라짐).

## 2. 실행
```bash
python main.py
```

## 3. 사용법
1. "영상 파일 선택"으로 교육 영상을 고릅니다.
2. 생성할 쇼츠 개수(기본 5개), 최대 길이(기본 60초), 자막/세로형 여부를 설정합니다.
3. "쇼츠 생성 시작" 클릭 → 전사 → AI 분석 → 렌더링이 순서대로 진행됩니다
   (영상 길이에 따라 수 분~수십 분 소요).
4. 완료되면 결과 화면에서 각 쇼츠를 미리보기하거나, 전체를 zip으로 다운로드할 수
   있습니다. 결과 파일은 `output/<영상이름>_<시각>/` 폴더에 저장됩니다
   (쇼츠 mp4 + 자막 .ass + `metadata.json`).

AI가 기준(최소 통과 점수, 기본 70점)을 만족하는 후보를 사용자가 요청한 개수만큼
찾지 못하면, 억지로 채우지 않고 찾은 만큼만 생성합니다.

## 4. 평가 기준 커스터마이징
`config.json`에서 다음을 직접 조정할 수 있습니다(설정 창에서도 가중치/최소점수/
Whisper 모델은 편집 가능):
- `weights`: 학습 가치, 핵심 개념성, 독립적 이해 가능성 등 8개 항목의 가중치(%)
- `penalties`: 반복/문맥의존/저가치 콘텐츠 감점 폭
- `min_shorts_score`: 이 점수 미만 후보는 탈락
- `type_guidance`: 과목별(수학/역사/과학/직업교육 등) 평가 시 강조할 지침 문구
- `whisper_model`: tiny/base/small/medium/large (클수록 정확하지만 느림)
- `chunk_minutes`: 긴 영상을 몇 분 단위로 나눠서 AI에 보낼지

## 5. 다른 PC에서 실행 파일(.exe)로 배포하기
개발 PC에서:
```bash
pip install pyinstaller
pyinstaller --name EduShortsGenerator --windowed --onedir main.py
```
`dist/EduShortsGenerator/` 폴더가 생성됩니다. 이 폴더 안에:
- `ffmpeg/ffmpeg.exe`, `ffmpeg/ffprobe.exe` 를 복사해 넣고
- `config.json`이 없다면 첫 실행 시 자동 생성됩니다

폴더 전체를 다른 PC에 복사하면 Python 설치 없이 실행됩니다(`EduShortsGenerator.exe`
더블클릭). Whisper 모델(`medium` 기준 약 1.5GB)은 최초 실행 시 자동 다운로드되므로,
완전 오프라인 PC라면 실행 PC에서 한 번 먼저 실행해 모델을 받아두거나
`~/.cache/whisper` 폴더를 함께 복사해야 합니다.

## 6. 폴더 구조
```
edu_shorts_generator/
  main.py                 # 실행 진입점
  config.json              # 평가 가중치 등 설정(자동 생성)
  secrets.json              # API 키(자동 생성, 공유 금지)
  requirements.txt
  edu_shorts/
    transcriber.py          # 로컬 Whisper 전사
    analyzer.py              # Claude API 기반 교육적 가치 분석 ("두뇌")
    selector.py               # 점수 계산 + 최종 후보 선정
    subtitles.py              # 쇼츠용 자막(.ass) 생성
    video_editor.py            # ffmpeg로 자르기/9:16 변환/자막 굽기
    pipeline.py                # 전체 파이프라인 연결
    gui.py                      # Tkinter 화면
    config.py, models.py, utils.py, secrets.py
  output/                  # 생성된 쇼츠가 저장되는 폴더
```
