# 우리동네 직업계고 (ㅇㅈ) — 네이버 클라우드 배포 매뉴얼

이 문서는 **네이버 클라우드 플랫폼(NCP)** 서버 한 대에 이 사이트를
올려 인터넷에 공개하는 전체 과정을 담고 있습니다.

구성은 이렇습니다. 서버 한 대 안에 전부 넣는 가장 단순한 방식입니다.

```
[방문자] → (도메인/HTTPS) → nginx ┬→ /api → FastAPI(gunicorn) → PostgreSQL
                                    └→ /    → React 정적파일(dist)
```

- **nginx**: 방문자의 요청을 받아, `/api`는 백엔드로, 나머지는 프론트 화면으로 나눠 보냄
- **FastAPI**: 실제 로직. gunicorn이 항상 켜둠
- **PostgreSQL**: 데이터 저장 (SQLite 대신)

> 예상 비용: 서버(2vCPU/4GB) 월 3~5만원 + 공인IP 월 약 4천원 + 도메인 연 1~2만원.
> 더 작은 서버(1~2GB)로도 되지만 빌드가 느릴 수 있습니다.

---

## 0단계 — 미리 준비할 것

- 네이버 클라우드 플랫폼 회원가입 + 결제수단 등록 (https://www.ncloud.com)
- 도메인 (가비아·후이즈 등에서 구입, 없으면 공인IP로도 접속은 됨)
- 본인 PC에 터미널(Windows는 PowerShell 또는 PuTTY)

---

## 1단계 — 서버(Server) 생성

1. NCP 콘솔 → **Services → Compute → Server** → **서버 생성**
2. 설정:
   - 이미지: **Ubuntu 22.04**
   - 서버 타입: **2vCPU / 4GB** 이상 권장 (Compact/Standard)
   - 요금제: 월요금제가 예측 가능
3. **인증키(로그인용 pem 파일)** 새로 생성 → 다운로드해서 잘 보관
   (이 파일이 서버 접속 열쇠입니다. 잃어버리면 접속 불가)
4. 서버가 만들어지면 **공인 IP 신청** (Server → 공인 IP → 신청 후 서버에 할당)

## 2단계 — 방화벽(ACG) 열기

NCP는 **ACG(Access Control Group)** 로 포트를 막아둡니다. 열어야 합니다.

1. Server → **ACG** → 해당 서버의 ACG 선택 → **규칙 설정**
2. **Inbound(들어오는)** 규칙에 추가:
   | 프로토콜 | 접근 소스 | 포트 |
   |---|---|---|
   | TCP | 내 IP (또는 0.0.0.0/0) | 22 (SSH 접속용) |
   | TCP | 0.0.0.0/0 | 80 (HTTP) |
   | TCP | 0.0.0.0/0 | 443 (HTTPS) |

   > 22번은 가능하면 '내 IP'로 제한하는 게 안전합니다.
   > PostgreSQL(5432)은 **외부에 열지 마세요.** 서버 안에서만 씁니다.

## 3단계 — 서버 접속

관리자 비밀번호를 먼저 받아야 합니다.
1. Server → 서버 선택 → **관리자 비밀번호 확인** → 아까 그 pem 파일 올리면 root 비밀번호가 나옴
2. 터미널에서 접속:
   ```
   ssh root@공인IP
   ```
   (Windows PuTTY라면 Host에 공인IP, 포트 22)

접속했으면 작업용 계정을 하나 만듭니다(root로 다 하는 건 위험).
```bash
adduser udt              # 비밀번호 설정
usermod -aG sudo udt     # 관리자 권한
su - udt                 # 이제부터 udt 계정으로 작업
```

> **중요:** 제공된 설정 파일들(`udt-backend.service`, `nginx-udt.conf`)은
> 코드가 `/root/hs-portal`에 있다고 가정합니다(운영 서버가 실제로 이 배치입니다).
> 다른 경로에 두면 그 두 파일 안의 경로(`/root/hs-portal/...`)와
> `User=udt`, `Group=udt`를 실제 계정명으로 바꿔야 합니다.

## 4단계 — 코드 올리기

**방법 A. Git 사용 (권장)**
GitHub 등에 올린 저장소가 있다면:
```bash
cd ~
git clone https://github.com/내계정/hs-portal.git
```

**방법 B. 직접 업로드**
본인 PC에서 zip을 서버로 보냅니다(PC 터미널에서):
```bash
scp hs-portal.zip udt@공인IP:~
```
서버에서:
```bash
cd ~
sudo apt install -y unzip
unzip hs-portal.zip
```

## 5단계 — 자동 세팅 스크립트 실행

코드를 올린 폴더로 가서:
```bash
cd ~/hs-portal
bash deploy/setup-server.sh
```

이 스크립트가 파이썬·nginx·PostgreSQL·Node를 설치하고, DB와 가상환경을 만듭니다.

**중간에 멈추면서 `.env`를 채우라고 합니다.** 그때:
```bash
nano backend/.env
```
로 열어 값을 채웁니다. 최소한 이 두 개는 꼭:

- `SECRET_KEY` — 아래 명령으로 랜덤값 생성해 붙여넣기:
  ```bash
  python3 -c "import secrets; print(secrets.token_hex(32))"
  ```
- `DATABASE_URL` — `postgresql://udt:설정한비밀번호@127.0.0.1:5432/udt`
  (PostgreSQL 비밀번호는 setup 스크립트 안 `CHANGE_THIS_PASSWORD`를 바꾼 값. 안 바꿨다면 아래로 변경:
  ```bash
  sudo -u postgres psql -c "ALTER USER udt WITH PASSWORD '새비밀번호';"
  ```
  )

`ALLOWED_ORIGINS`에는 도메인을 넣습니다: `https://내도메인.kr,https://www.내도메인.kr`
(도메인이 아직 없으면 비워둬도 nginx 같은 도메인 방식이라 동작합니다.)

값을 채운 뒤 **스크립트를 한 번 더 실행**하면 DB 테이블·관리자 계정 생성과 프론트 빌드까지 됩니다:
```bash
bash deploy/setup-server.sh
```

## 6단계 — 백엔드를 서비스로 등록 (항상 켜두기)

```bash
# 서비스 파일 복사 (경로가 /root/hs-portal 이 맞는지 확인)
sudo cp ~/hs-portal/deploy/udt-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable udt-backend
sudo systemctl start udt-backend

# 상태 확인
sudo systemctl status udt-backend
```
초록색 `active (running)`이 보이면 성공. 오류가 나면:
```bash
sudo journalctl -u udt-backend -n 50
```
로 로그를 봅니다. (대개 .env의 DATABASE_URL 오타나 비밀번호 불일치)

## 7단계 — nginx 설정

```bash
# 설정 파일 복사
sudo cp ~/hs-portal/deploy/nginx-udt.conf /etc/nginx/sites-available/udt

# 도메인 이름을 실제 값으로 바꾸기
sudo nano /etc/nginx/sites-available/udt
#   server_name 내도메인.kr www.내도메인.kr;  <- 여기와
#   root /root/hs-portal/frontend/dist;    <- 경로 확인

# 활성화
sudo ln -s /etc/nginx/sites-available/udt /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default   # 기본 페이지 제거
sudo nginx -t         # 문법 검사 (ok 나와야 함)
sudo systemctl restart nginx
```

이제 브라우저에서 **http://공인IP** 또는 **http://내도메인.kr** 로 접속되면 성공입니다.

## 8단계 — 도메인 연결

도메인 업체(가비아 등) 관리페이지에서 DNS 레코드 추가:
| 타입 | 호스트 | 값 |
|---|---|---|
| A | @ | 서버 공인IP |
| A | www | 서버 공인IP |

전파에 몇 분~몇 시간 걸립니다.

## 9단계 — HTTPS(자물쇠) 적용

무료 인증서(Let's Encrypt)를 자동 발급받습니다. **도메인 연결이 끝난 뒤** 실행:
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d 내도메인.kr -d www.내도메인.kr
```
이메일 입력하고 안내를 따르면 자동으로 HTTPS가 켜지고, `http://`는 `https://`로 자동 전환됩니다. 인증서는 자동 갱신됩니다.

HTTPS를 켠 뒤 `backend/.env`의 `ALLOWED_ORIGINS`가 `https://`로 시작하는지 확인하고, 바꿨다면 재시작:
```bash
sudo systemctl restart udt-backend
```

---

## 학교 데이터 채우기

배포 직후엔 학교가 비어 있습니다. NEIS 키를 .env에 넣었다면:
```bash
cd ~/hs-portal/backend
.venv/bin/python -m app.import_neis --majors
```
전국 특성화고·마이스터고·특목고가 들어옵니다. 카카오 키까지 넣었다면 좌표도:
```bash
.venv/bin/python -m app.import_neis --geocode
```

---

## 코드를 고쳐서 다시 배포할 때

```bash
cd ~/hs-portal
git pull                      # (Git 사용 시) 새 코드 받기

# 백엔드 바뀌었으면
cd backend
.venv/bin/pip install -r requirements.txt   # 의존성 바뀐 경우만
sudo systemctl restart udt-backend

# 프론트 바뀌었으면
cd ../frontend
npm install                   # 의존성 바뀐 경우만
npm run build                 # dist 새로 생성 (nginx가 자동으로 새 파일 사용)
```

---

## 운영 중 자주 쓰는 명령

| 하고 싶은 것 | 명령 |
|---|---|
| 백엔드 상태 보기 | `sudo systemctl status udt-backend` |
| 백엔드 로그 보기 | `sudo journalctl -u udt-backend -f` |
| 백엔드 재시작 | `sudo systemctl restart udt-backend` |
| nginx 재시작 | `sudo systemctl restart nginx` |
| DB 접속 | `sudo -u postgres psql udt` |
| DB 백업 | `pg_dump -U udt udt > backup_$(date +%F).sql` |
| DB 복구 | `psql -U udt udt < backup_파일.sql` |

---

## 오픈 전 필수 — 운영 기관 정보 채우기

이 서비스는 문의 기능으로 개인정보(이메일·전화)를 수집하므로,
「개인정보 보호법」에 따라 **개인정보처리방침**과 **개인정보 보호책임자**가 있어야 합니다.

**`frontend/src/org.js`** 파일을 열어 `[ ]`로 표시된 값들을 실제 값으로 채우세요:

- 개인정보 보호책임자 성명·직책·이메일·전화
- 기관 대표 이메일·전화·주소
- 개인정보처리방침 시행일(오픈일)

운영 기관은 이미 `특성화고신문`으로 설정돼 있습니다. 값을 채운 뒤 프론트를 다시 빌드하면
(`cd frontend && npm run build`) 사이트 하단 "개인정보처리방침" 페이지와 문의 폼에 반영됩니다.

채우지 않으면 방침 페이지에 `[개인정보 보호책임자 성명]`처럼 대괄호가 그대로 보이므로,
**오픈 전 반드시 확인**하세요.

---

## 보안·법률 체크리스트

- [ ] `backend/.env`는 **절대 git에 올리지 않기** (.gitignore에 이미 포함)
- [ ] `SECRET_KEY`를 기본값에서 **랜덤값으로 변경**했는지
- [ ] PostgreSQL 비밀번호를 `CHANGE_THIS_PASSWORD`에서 **변경**했는지
- [ ] ACG에서 5432(DB) 포트를 **외부에 열지 않았는지**
- [ ] SSH(22) 포트를 가능하면 **내 IP로 제한**했는지
- [ ] HTTPS를 적용했는지 (문의로 개인정보를 받으므로 사실상 필수)
- [ ] **개인정보처리방침** 페이지/고지를 준비했는지 (문의 기능이 이메일·전화를 수집하므로 개인정보보호법 대상). 수집 항목·목적·보유기간·파기를 명시하세요.
- [ ] 정기 **DB 백업** 습관 (위 pg_dump를 크론으로 걸어두면 좋음)

---

## 자주 나는 문제

**사이트는 열리는데 로그인/검색이 안 돼요 (500 오류)**
→ 백엔드가 죽었거나 DB 연결 실패. `sudo journalctl -u udt-backend -n 50` 확인.
대개 `.env`의 `DATABASE_URL` 비밀번호 불일치입니다.

**"접속할 수 없음"으로 아예 안 열려요**
→ ACG에서 80/443을 열었는지, nginx가 켜져 있는지(`sudo systemctl status nginx`) 확인.

**화면은 뜨는데 새로고침하면 404**
→ nginx 설정의 `try_files ... /index.html` 부분이 있는지 확인(제공된 설정엔 포함됨).

**메일 답변이 안 보내져요**
→ 각 학교 대시보드에서 SMTP 계정을 등록해야 합니다. 네이버 메일은 '2단계 인증 → 앱 비밀번호'를 발급해 넣어야 하고, 메일 설정에서 SMTP 사용을 켜야 합니다.

**한글이 깨져 보여요 (DB)**
→ PostgreSQL은 기본 UTF-8이라 대개 문제없지만, 만약 깨지면 DB를 `ENCODING 'UTF8'`로 다시 생성하세요.
