# UDJ 학교·교사용 영상 — 사용 화면 목록

## 화면 출처

| 구분 | 어디서 | 데이터 | 영상 배지 |
|---|---|---|---|
| 시연 환경 | 로컬 `video/school-demo` — **실제 UDJ 코드**(backend/app, frontend)를 그대로 띄우고 DB 만 테스트 DB(`data/demo.db`)로 바꿨다. 주소 `http://127.0.0.1:5190` | 가상 학교 4곳(예시미래산업고 등), 가상 계정, 가상 문의·일정·진학 자료. 플랜 가격·혜택은 운영 공개값과 같게 맞췄다 | 시연용 테스트 환경 · 가상 데이터 |
| 운영 공개 화면 | https://udjschool.ggm.kr/ (비로그인) — 학생 홍보영상 때 찍은 캡처를 재사용 | 실제 공개 학교 정보(NEIS) | 실제 서비스 공개 화면 |

영상 속 주소창에는 운영 주소(udjschool.ggm.kr/…)로 표시해 시청자가 실제 경로를 알 수 있게 했다. 시연 환경 화면은 배지로 구분한다.

## 개인정보·보안 점검

- 운영 사이트에 로그인하지 않았고, 운영 DB·운영 데이터를 쓰지 않았다.
- 화면에 나오는 사람·학교·연락처는 모두 가상이다: 이메일 `@example.com`(예약 도메인), 전화 `010-0000-0000`·`031-000-0000`, 주소 "(가상 주소)".
- 테스트 계정 비밀번호는 무작위로 만들어 `video/school-demo/data/demo_accounts.json`(커밋 제외)에만 있고, 화면에는 ●로만 보인다.
- 메일은 실제로 보내지 않는다 — 시연 백엔드가 발송 함수를 바꿔 `data/outbox/*.eml` 로 저장한다(`backend/app/full_test.py` 와 같은 방식).
- 토큰·API 키는 화면에 나오지 않는다. 시연 백엔드의 서명 키는 시연 전용 값이다.
- 푸터의 운영 기관 정보(대표·사업자번호·주소·대표전화)는 실제 사이트에 공개된 사업자 표기다.

## 시연 환경 화면 (`video/assets/screenshots/school/`, 렌더용 사본 `video/src/public/shots/s_*.png`)

| 파일 | 실제 URL | 화면 상태 | 사용 장면 |
|---|---|---|---|
| req_empty | /school-account-request | 빈 신청서 | 학교 계정 신청 |
| req_search | 〃 | "예시미래" 검색 결과 | 〃 |
| req_filled | 〃 | 담당자 정보 입력 완료(가상) | 〃 |
| req_done | 〃 | "신청이 접수되었습니다" | 〃 |
| login_empty / login_filled | /login | 빈 화면 / 입력 완료(비밀번호 ●) | 첫 로그인 |
| ms_first | /my-school | 임시 비밀번호 안내 배너 + 통계 | 첫 로그인 |
| pw_change | /account/password | 비밀번호 변경 | 첫 로그인 |
| ms_stats | /my-school (통계) | 누적 조회수·즐겨찾기·노출 순서·14일 그래프 | 개요·통계, 소개 |
| ms_profile_empty / ms_profile_filled / ms_profile_saved | /my-school (학교 정보) | 입력 전 / 입력 후 / 저장 완료 | 학교 정보 |
| pub_school_before / pub_school_after | /schools/1 | 저장 전 / 저장 후 공개 학교 페이지 | 학교 정보 |
| pub_inquiry_filled / pub_inquiry_done | /schools/1 | 학부모 문의 작성 / 접수 | 문의 관리 |
| ms_inq_list / ms_inq_typed / ms_inq_sent | /my-school (문의 관리) | 목록 / 답변 입력 / 발송 완료 | 문의 관리 |
| ms_inq_notify | 〃 | 새 문의 알림 이메일 입력 | 문의 관리 |
| ms_events_empty / ms_events_filled / ms_events_added | /my-school (학교일정등록) | 양식 / 입력 / 등록 목록 | 학교일정등록 |
| pub_events | /events | 학교 일정 모아보기 | 학교일정등록, 학생 서비스 |
| pub_school_events | /schools/1 | 학교 페이지 "학교 설명회" | 학교일정등록 |
| adm_stats / adm_univ / adm_emp / adm_employers / adm_excel / adm_vis | /my-school (취업/진학 정보) | 기본 통계 / 대학·학과 / 취업 분야 / 주요 취업처 / Excel 업로드 / 공개 설정 | 취업/진학 정보 |
| pub_admission | /schools/1/admission | 공개 페이지(가상 자료) | 취업/진학 정보 |
| ms_plan | /my-school (노출 플랜) | 현재 기능·플랜 카드(운영 가격)·신청·신청 내역 | 노출 플랜 |
| stu_fav / stu_fav_events | /favorites | 학생 즐겨찾기·메모 / 일정 D-day | 학생 서비스, 학교일정등록 |
| stu_school | /schools/1 | 학생 로그인 상태의 학교 페이지 | 학생 서비스 |

## 운영 공개 화면 (`video/assets/screenshots/`)

| 파일 | 실제 URL | 사용 장면 |
|---|---|---|
| home_viewport | https://udjschool.ggm.kr/ | 학생 서비스 |
| search_result_full | https://udjschool.ggm.kr/search | 소개, 학생 서비스 |
| search_map | https://udjschool.ggm.kr/search (지도) | 학생 서비스 |
| search_compare_modal | https://udjschool.ggm.kr/search (나란히 비교) | 학생 서비스 |
| quiz_result_full | https://udjschool.ggm.kr/quiz | 학생 서비스 |
| signup | https://udjschool.ggm.kr/signup | 학생 서비스 |
| news_343_full | https://udjschool.ggm.kr/schools/343 (영서고) | 특성화고신문 보도자료 — 학생 이름·얼굴이 없는 기관 소식 기사만 있는 학교로 골랐다. `capture/capture_news.mjs` |
| home_full | https://udjschool.ggm.kr/ (하단 연락처) | 특성화고신문 보도자료 — 게재 권한 문의처 |

## 다시 찍는 방법

```bash
# 시연 서버 2개 (프로젝트 루트의 .claude/launch.json: udj-demo-backend, udj-demo-frontend)
cd hs-portal/video/school-demo
python -m venv .venv && .venv/Scripts/python.exe -m pip install -r ../../backend/requirements.txt
cd ../src
node capture/capture_school.mjs        # 시드(seed_demo.py) → 실제 조작하며 36장 캡처 + 좌표(school_meta.json)
```
