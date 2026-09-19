# 기록해 분리 배포 안내

우리동네 직업계고(UDJ)에서 일지·자기소개서 기능을 떼어 **기록해**라는 별도
서비스로 만들었습니다. 두 서비스는 서버·DB·코드가 모두 분리되어 있고,
**계정만 UDJ 것을 함께** 씁니다.

| | 우리동네 직업계고 | 기록해 |
|---|---|---|
| 주소 | udjschool.ggm.kr | diary.ggm.kr |
| 백엔드 | `backend` (포트 8000) | `diary-backend` (포트 8100) |
| 프론트 | `frontend` | `frontend-journal` |
| 서비스 | `udt-backend` | `diary-backend` |
| DB | udt | **diary (새로 만들어야 함)** |

계정의 원본은 UDJ 에만 있습니다. 기록해에서 가입·정보변경·탈퇴를 해도
실제 처리는 UDJ 가 합니다. 그래서 비밀번호 해시가 한 곳에만 있고,
탈퇴하면 양쪽에서 확실히 사라집니다.

---

## 처음 한 번만 하는 설정

### 1. 연동 키 만들기

두 서비스가 서로를 알아보는 열쇠입니다. 아무에게도 알려지면 안 됩니다.

```bash
openssl rand -hex 32        # 나온 값을 아래 양쪽에 똑같이 넣습니다
```

```bash
# UDJ 쪽
echo 'PARTNER_SECRET=여기에_붙여넣기' >> ~/hs-portal/backend/.env
```

### 2. 기록해 DB 만들기

```bash
sudo -u postgres psql -c "CREATE DATABASE diary OWNER udt;"
```

### 3. 기록해 백엔드 준비

```bash
cd ~/hs-portal/diary-backend
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

cp .env.example .env
nano .env
```

`.env` 에 채울 값입니다.

```
DATABASE_URL=postgresql://udt:비밀번호@localhost:5432/diary
SECRET_KEY=<openssl rand -hex 32 로 새로 만든 값. UDJ 와 달라야 합니다>
UDJ_API_BASE=http://127.0.0.1:8000
PARTNER_SECRET=<1번에서 만든 값. UDJ 와 똑같아야 합니다>
```

### 4. 기존 데이터 옮기기

**배포 전에 반드시 합니다.** 이걸 건너뛰면 학생들이 쓴 일지가 보이지 않습니다.

```bash
cd ~/hs-portal/diary-backend
UDJ_DB="postgresql://udt:비밀번호@localhost:5432/udt"

.venv/bin/python -m app.migrate_from_udj --udj-db "$UDJ_DB" --dry-run   # 먼저 확인
.venv/bin/python -m app.migrate_from_udj --udj-db "$UDJ_DB" --yes       # 실제 이전
```

여러 번 돌려도 안전합니다. UDJ 쪽 자료는 **지우지 않습니다** — 기록해에서
잘 보이는지 확인한 뒤 직접 정리하세요.

### 5. 서비스 등록

```bash
sudo cp ~/hs-portal/deploy/diary-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now diary-backend
systemctl is-active diary-backend        # active 여야 합니다
curl -s http://127.0.0.1:8100/api/health # udj_linked: true 여야 합니다
```

### 6. nginx

```bash
sudo cp ~/hs-portal/deploy/nginx-diary.conf /etc/nginx/sites-available/diary
sudo ln -sf /etc/nginx/sites-available/diary /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

`root` 경로가 실제 위치와 맞는지 확인하세요. 기본값은 `/root/hs-portal/frontend-journal/dist` 입니다.

---

## 평소 배포

**배포 도구(udj_tool.py)** 의 `원클릭 배포` 탭에서 대상을 고르면 됩니다.
한쪽만 고쳤으면 그쪽만 배포하는 게 빠르고 안전합니다.

명령으로 하실 때는 이렇습니다.

```bash
cd ~/hs-portal && cp backend/.env /tmp/env1 && cp diary-backend/.env /tmp/env2
unzip -o ~/hs-portal.zip -d ~
cp /tmp/env1 backend/.env && cp /tmp/env2 diary-backend/.env

cd frontend && npm install && npm run build
cd ../frontend-journal && npm install && npm run build

sudo systemctl restart udt-backend diary-backend
```

---

## 확인

```bash
# 두 서비스 상태
for s in udt-backend diary-backend; do printf '%-16s %s\n' "$s" "$(systemctl is-active $s)"; done

# 연동
curl -s http://127.0.0.1:8100/api/health

# 통합 테스트 (운영 DB 를 건드리지 않도록 별도 DB 로)
cd ~/hs-portal/backend
DATABASE_URL="sqlite:///./_t.db" SECRET_KEY=test .venv/bin/python -m app.full_test; rm -f _t.db

cd ~/hs-portal/diary-backend
DATABASE_URL="sqlite:///./_t.db" SECRET_KEY=test .venv/bin/python -m app.full_test; rm -f _t.db
```

### 테스트 계정

배포 도구의 `테스트 계정` 탭에서 만들 수 있습니다. 명령으로는 이렇습니다.

```bash
cd ~/hs-portal/backend
.venv/bin/python -m app.make_test_accounts --school 262 --password test12345
.venv/bin/python -m app.make_test_accounts --check     # 상태 보기
.venv/bin/python -m app.make_test_accounts --delete    # 정리
```

학생·선생님·학교 세 계정을 한 벌로 만들고 재학생 인증까지 연결합니다.
선생님 계정으로 기록해에 들어가면 그 학생의 일지가 보여야 정상입니다.

---

## 문제가 생기면

**기록해에서 로그인이 안 됩니다**
`PARTNER_SECRET` 이 양쪽에서 같은지 확인하세요. 다르면 401 이 납니다.

```bash
grep PARTNER_SECRET ~/hs-portal/backend/.env ~/hs-portal/diary-backend/.env
```

**"계정 서버에 연결하지 못했습니다"**
UDJ 가 떠 있는지, `UDJ_API_BASE` 가 맞는지 봅니다.

```bash
systemctl is-active udt-backend
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/meta
```

**일지가 하나도 안 보입니다**
데이터 이전(4번)을 안 했거나, 기록해 DB 가 비어 있습니다.

```bash
cd ~/hs-portal/diary-backend
.venv/bin/python -c "
from app.database import SessionLocal
from app.models import JournalEntry, User
db=SessionLocal(); print('계정', db.query(User).count(), '일지', db.query(JournalEntry).count()); db.close()"
```

**선생님 화면에 학생이 안 보입니다**
그 학생의 재학생 인증이 승인되어 있어야 합니다. 인증은 UDJ 에서 합니다.
승인 후 학생이 기록해에 **다시 로그인해야** 소속 정보가 갱신됩니다.
