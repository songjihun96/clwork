# UDJ 배포툴 v3.0

hs-portal 서버(root@… `/root/hs-portal`) 한 대에 들어 있는 다섯 서비스를
PC 에서 골라 배포하고, 상태를 보고, 로그를 읽고, 명령을 치는 도구.

## 두는 곳

`hs-portal/tools/deploy/` 안에 네 파일을 같이 둔다.

```
hs-portal/
  tools/
    deploy/
      udj_deploy.pyw   ← 본체
      배포툴.bat        ← 이걸 두 번 누른다
      진단실행.bat      ← 안 뜰 때. 콘솔을 띄운 채 돌려서 오류를 보여준다
      precheck.py      ← 실행 전 확인(배치가 부른다)
```

`배포툴.bat` 이 파이썬을 찾고(PATH 에 없으면
`%LOCALAPPDATA%\Programs\Python\Python314` 등 설치 위치를 직접 본다),
`tkinter`·`paramiko`·본체 문법을 확인하고, `paramiko` 가 없으면 한 번 설치한 뒤
창 없이 띄운다. 저장소 안에 두면 **PC 프로젝트 폴더가 자동으로 잡힌다**
(위로 올라가며 `backend/app` 과 `deploy` 가 같이 있는 폴더를 찾는다).

### 안 뜨고 바로 꺼질 때

배치는 매번 같은 폴더에 `launch.log` 를 남긴다. 창이 순식간에 닫혔다면 그
파일을 먼저 본다. 프로그램 쪽이 죽은 경우에는 `오류기록.txt` 가 생긴다.
둘 다 없으면 `진단실행.bat` 을 눌러 콘솔에 남는 내용을 본다.

> 배치 파일은 **CP949(ANSI)** 로 저장해야 한다. UTF-8 로 저장하면 cmd 가
> 한글이 든 줄에서 읽던 자리를 잃고 조용히 끝나버린다 — 창이 뜨자마자
> 닫히던 원인이 이것이었다. 메모장에서 고쳤다면 "다른 이름으로 저장 →
> 인코딩: ANSI" 를 확인할 것.

## 처음 한 번

**연결 설정** 탭에서:

| 항목 | 값 |
|---|---|
| 서버 주소 | 운영 서버 공인 IP |
| 포트 | 22 |
| 계정 | root |
| 키 파일(pem) | NCP 에서 받은 인증키 — **이 방식을 권한다** |
| PC 프로젝트 폴더 | `C:\Users\user\clwork\hs-portal` |
| 서버 프로젝트 경로 | `/root/hs-portal` |

**비밀번호는 기본적으로 저장되지 않는다.** 설정 파일(`%USERPROFILE%\.udj_deploy.json`)에
남는 것은 주소·계정·경로뿐이다. "이 PC 에 저장" 을 켜면 평문으로 남으니,
가급적 키 파일을 쓴다.

[설정 저장] → [연결 시험] 을 눌러 초록불이 뜨면 끝.

## 배포

**배포** 탭에서 올릴 서비스를 고르고 `▶ 배포 실행`.

| 서비스 | 도메인 | 포트 | 유닛 | 폴더 |
|---|---|---|---|---|
| 우리동네 직업계고 | udjschool.ggm.kr | 8000 | `udt-backend` (+`udt-audio`) | `backend`, `frontend` |
| CS 지원 | udjcs.ggm.kr | 8010 | 화면만 (백엔드 공유) | `frontend-cs` |
| 기록해 | diary.ggm.kr | 8100 | `diary-backend` | `diary-backend`, `frontend-journal` |
| 연구·논문 | univ.ggm.kr | 8200 | `research-backend` | `research-backend`, `frontend-research` |
| 우리업무 | workwoori.ggm.kr | 8300 | `work-backend` | `work-backend`, `frontend-work` |

도는 순서:

```
프론트 빌드(npm run build)
  → zip 만들기 + 검사(.env·비밀키 섞이면 즉시 중단)
  → 업로드(SFTP)
  → 서버 폴더 tar.gz 백업
  → .env 따로 보관
  → unzip -o
  → .env 되돌리기
  → .venv/bin/pip install -r  (켠 경우만)
  → systemctl restart
  → 포트·사이트 응답 확인
```

체크박스 네 개의 뜻:

- **프론트 빌드** — 화면(React)을 고쳤으면 켠다. 서버에서 빌드하지 않고 PC 에서
  빌드한 `dist` 만 올린다. 우리업무는 Vite 가 아니라 정적 파일이라 그냥 올라간다.
- **파이썬 의존성 설치** — `requirements.txt` 가 바뀌었을 때만 켠다. 언제나
  `.venv/bin/pip` 만 쓴다. 우리업무는 기록해 venv(`diary-backend/.venv`)를
  공유한다 — 급여명세서 PDF 의 reportlab 이 그쪽에만 있다.
- **배포 전 백업** — `/root/deploy-backups/before-*.tar.gz`. 되돌릴 때:
  ```
  cd /root/hs-portal && tar -xzf /root/deploy-backups/before-....tar.gz -C /root/hs-portal
  systemctl restart work-backend
  ```
- **재시작** — 화면만 바뀐 서비스는 재시작할 프로세스가 없으므로 건너뛴다.

## 안전장치

2026-09-13 에 손으로 만든 zip 에 로컬 `backend/.env` 가 딸려 들어가 서버의
운영 `.env` 를 덮어썼고, 백엔드가 PostgreSQL 대신 빈 SQLite 로 떨어져 사이트가
"학교 0개교" 로 보였다. 그 사고에서 나온 규칙을 그대로 넣었다.

1. 점으로 시작하는 파일은 전부 뺀다 — `.env` 가 여기 걸린다.
2. zip 을 담은 뒤 **다시 열어서** `.env`·`secret`·`id_rsa`·`*.pem`·`*.key`·`*.db`
   가 있는지 검사한다. 걸리면 zip 을 지우고 배포를 멈춘다.
3. 서비스별 필수 파일(`app/main.py`, `requirements.txt`, `frontend-work/payroll.js` …)이
   빠졌으면 역시 멈춘다. 예전에 `app/callcenter` 가 통째로 빠진 zip 이 나가
   ImportError 로 서비스가 죽은 적이 있다.
4. 그래도 서버에서 `unzip -o` 전에 `.env` 를 복사해 두고 끝나면 되돌린다.
5. 고른 서비스의 폴더만 담는다 — 업무 시스템을 고쳤다고 직업계고 백엔드까지
   덮어쓰지 않는다.

## 서비스 탭

다섯 유닛 + `nginx`, `postgresql` 의 상태·동작 시간을 한 표에서 본다.
고른 뒤 재시작 / 중지 / 시작 / 로그 200줄 / 30초 따라가기.
재시작·중지는 한 번 더 묻는다.

## 점검 탭

- **한 번에 점검** — 디스크·메모리 → 포트 → nginx 문법 → 다섯 사이트 응답 → 유닛 상태
- **사이트 응답 확인** — 서버에서 각 도메인에 HTTPS 로 요청해 응답 코드와 시간
- **열린 포트 보기** — `ss -ltnp` 로 8000·8010·8100·8200·8300 확인.
  새 서비스를 붙일 때는 이걸로 빈 포트를 먼저 봐야 한다(8200 충돌로 work-backend 가
  못 떴던 적이 있다)
- **DB 백업** — `sudo -u postgres pg_dump <db> | gzip > /root/db-backups/…`

## 콘솔 탭

친 명령이 `bash -lc` 로 root 권한에서 그대로 돈다. 자주 쓰는 것은 단추로 넣어뒀다
(서비스 전체 상태, 각 백엔드 최근 로그, 학교 수 세기, 디스크 큰 것 10개).

## 아직 안 넣은 것

- **데이터 초기화** — 넣지 않았다. users 를 참조하는 테이블 8개의 삭제 순서가
  틀리면 FK 제약에 걸려 반쯤 지워진 상태로 남는다. 초기화는 백엔드 쪽에
  순서를 명시한 스크립트를 두고 거기서 부르는 편이 안전하다.
- **마이그레이션 실행** — 현재 `_ensure_columns()` 로 기동할 때 붙는 방식이라
  재시작만으로 적용된다. 별도 단추가 필요해지면 그때 넣는다.

## 손볼 곳

서비스 구성이 바뀌면 `udj_deploy.pyw` 위쪽 `SERVICES` 목록만 고치면 된다
(이름·폴더·유닛·포트·도메인·필수 파일). 화면과 배포 절차는 그 목록을 보고 돈다.

---
확인한 것: zip 안전규칙 15개 항목, GUI 구성·설정 저장, 그리고 실제 SSH 서버를
띄워 업로드 → `.env` 보관 → `unzip -o` → `.env` 복원 → 백업 되돌리기까지 —
운영 `.env` 값이 그대로 살아남는 것을 확인했다.
