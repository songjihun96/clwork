# KIBO 제출자료 ② 계약-코드 연결 매핑

> 대상 코드베이스: `hs-portal/` — README상 제품명 **"우리동네 특성화고 (U.D.T)"**.
> 백엔드 FastAPI(Python) + 프런트엔드 React/Vite + SQLite(로컬)/PostgreSQL(운영).
> 코드 내부에서 발주사 사업자등록번호(`214-13-75982`)와 대표자명(`강승구`), 이메일(`news@sinmoon.net`)이
> [backend/app/main.py:2729](../hs-portal/backend/app/main.py), [:3566](../hs-portal/backend/app/main.py)에
> 그대로 하드코딩되어 있어, **계약서상 발주사와 실제 운영 코드의 대상이 동일함**이 코드 수준에서 직접 확인됩니다.

## 매핑 표

| 계약상 업무 | 실제 구현 기능 | 코드 파일 | API/연동 | DB | 구현상태 |
|---|---|---|---|---|---|
| 1. 웹사이트 신규 개발 | 전국 특성화고·마이스터고 검색 포털(검색/필터/지도/비교) 전체 신규 구축 | `backend/app/main.py`(라우트 전체), `frontend/src/pages/Search.jsx`, `SchoolPage.jsx`, `App.jsx` | 자체 REST API | SQLAlchemy 모델(`models.py`) | 구현됨 |
| 2. 관리자 페이지 | 학교 계정 발급, 플랜 승인/반려, 통계, 콘텐츠 관리 대시보드 | `frontend/src/pages/AdminPanel.jsx`(약 96KB), `SchoolAdmin.jsx`, `backend/app/seed.py` | 관리자 전용 API(JWT 역할검사) | User/School/Plan 테이블 | 구현됨 |
| 3. 기능 개선(지속) | 진학정보(플래티넘 전용) 입력·검증·엑셀 업로드·집계·공개 페이지 등 지속 확장 | `backend/app/admission.py`(약 1,468줄), `frontend/src/components/AdmissionManager.jsx`, `pages/SchoolAdmission.jsx` | 자체 API | Admission 관련 테이블 | 구현됨 (9/19~9/27 최근까지 수정 이력 확인) |
| 4. 외부 API 및 서비스 연동 | ① NEIS(나이스) 교육정보 개방 포털에서 학교 기본정보·학과정보 수집<br>② 카카오 REST API로 주소→좌표 지오코딩, 도로명주소 검색<br>③ 토스페이먼츠로 플랜 결제·환불 연동<br>④ Anthropic Claude API로 진로상담 챗봇<br>⑤ 특성화고신문(sinmoon.net) 기사 자동 크롤링 | `backend/app/import_neis.py`, `geo.py`, `toss.py`, `career_chat.py`, `ai.py`, `articles.py` | NEIS API, Kakao API, TossPayments API, Anthropic API, sinmoon.net 크롤링 | School/Article 테이블 | 구현됨 |
| 5. 오류 수정 및 예외처리 | 결제 금액 서버측 재검증(클라이언트 위변조 방지), 기사 파싱 예외 처리, 진단 스크립트 | `backend/app/toss.py`(주석: "서버에 저장해 둔 금액과 반드시 대조"), `fix_articles.py`, `diagnose_quiz.py`, `monitor.py` | - | - | 구현됨 (README "검증된 동작" 목록에 구체 사례 다수 명시) |
| 6. 서버·도메인 연동 | 네이버클라우드 서버 배포 가이드, systemd 서비스화, nginx 리버스프록시, Let's Encrypt HTTPS 자동 발급 | `deploy/DEPLOY_GUIDE_naver_cloud.md`, `deploy/setup-server.sh`, `deploy/udt-backend.service`, `deploy/nginx-udt.conf` | certbot(HTTPS) | - | 구현됨. 단, 저장소 내 nginx 설정의 도메인명은 `내도메인.kr` **플레이스홀더** → 실제 운영 도메인 확정본은 **[확인 필요]** |
| 7. 웹사이트 운영 지원 | 실시간 서버 감시 위젯(접속자·트래픽·CPU·에러로그), 콜센터/전화상담 순차분배 엔진, 데이터 초기화 도구 | `tools/server-monitor/`, `backend/app/monitor.py`, `backend/app/callcenter/engine.py`, `reset-data.bat` | `/api/monitor/snapshot` | cs_call_sessions 등 | 구현됨 |
| 8. 데이터베이스 | User/School/Article/Review/Plan/Admission 등 도메인 모델, 로컬 SQLite → 운영 PostgreSQL 전환 구조 | `backend/app/models.py`(약 1,459줄) | - | SQLite(dev) / PostgreSQL(prod) | 구현됨 |
| 9. 사용자 관리 | 학생(자가가입)/학교(관리자 발급)/관리자 3단계 역할 체계, 계정 정지, 테스트 계정 생성 도구 | `models.py`(Role), `make_school_accounts.py`, `make_test_accounts.py`, `frontend/src/pages/Signup.jsx`, `Login.jsx` | - | User 테이블 | 구현됨 |
| 10. 인증 | JWT 기반 인증, bcrypt 비밀번호 해시, 운영/개발 환경별 SECRET_KEY 검증 로직 | `backend/app/auth.py` | - | - | 구현됨 |
| 11. 콘텐츠 관리 | 특성화고신문 기사 자동 크롤링·수동 등록, 출처 표기("특성화고신문 제공") 및 원문 링크 유지, 학교-기사 자동 연결 | `backend/app/articles.py`(약 657줄), `models.py`(Article 모델), `frontend/src/pages/AdminPanel.jsx`(기사 관리 UI), `Home.jsx`, `SchoolDetailView.jsx` | sinmoon.net | Article 테이블 | 구현됨 |
| 12. 기타 계약상 업무 | 유료 플랜(무료/베이직/프리미엄/플래티넘) 결제·정산 인프라, 정산계좌 예금주가 "특성화고신문"으로 코드에 명시, 대표 소개/보도자료 관리 페이지, 특성화고신문 링크를 패밀리사이트로 노출 | `toss.py`, `main.py`("bank_holder": "특성화고신문"), `frontend/src/pages/AdminBriefing.jsx`, `components/FamilySites.jsx` | TossPayments | Plan/Payment 테이블 | 구현됨 |

## ⚠️ 코드에서 확인되지 않는 것

- **60:40 자동 수익배분·정산 로직**: 결제(`toss.py`)와 정산계좌 예금주 정보는 코드에 있으나, "발생 총수익의 60%/40% 자동 분배" 기능 자체는 코드베이스에서 발견되지 않았습니다. 계약 제7조상 정산은 "수익 수령·관리 당사자가 월별로 산정해 수동 지급"하는 구조로 보이며, 이는 **회계·정산 프로세스이지 소프트웨어 기능이 아닐 수 있습니다** → **구현 확인 불가 (수동 정산으로 추정)**.
- **실제 운영 도메인 확정본**: 저장소의 nginx 설정은 플레이스홀더(`내도메인.kr`) → **확인 필요**.
- **Git 커밋 이력**: 현재 저장소에는 `hs-portal` 관련 커밋이 1건(백업 커밋, 2026-09-19)만 있어 세부 개발 이력(누가/언제/무엇을 커밋했는지)은 git log로 증명되지 않습니다. 대신 파일 수정시각(mtime) 기준으로 2026-09-19~2026-09-27까지 지속적으로 수정된 정황은 확인됩니다 → 상세 개발 이력이 필요하면 Claude Code 세션 로그, 로컬 에디터 히스토리, 배포 zip 파일들(`hs-portal.zip`, `hs-portal-updated.zip`, `udj-*.zip` 등 타임스탬프 상이한 다수 백업본 존재)을 보조 증빙으로 활용 권장.
