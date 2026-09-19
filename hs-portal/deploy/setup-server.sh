#!/usr/bin/env bash
# ==========================================================
#  ㅇㅈ 서버 초기 세팅 (Ubuntu 22.04 기준)
#  네이버 클라우드 서버에 접속한 뒤 이 스크립트를 실행하세요.
#  실행: bash deploy/setup-server.sh
# ==========================================================
set -e

echo "[1/6] 시스템 패키지 설치..."
sudo apt update
sudo apt install -y python3-venv python3-pip nginx postgresql postgresql-contrib nodejs npm git

echo "[2/6] PostgreSQL 데이터베이스/계정 생성..."
# 이미 있으면 무시. 비밀번호는 실제로 바꾸세요!
sudo -u postgres psql -c "CREATE USER udt WITH PASSWORD 'CHANGE_THIS_PASSWORD';" 2>/dev/null || echo "  (udt 계정이 이미 있음)"
sudo -u postgres psql -c "CREATE DATABASE udt OWNER udt;" 2>/dev/null || echo "  (udt DB가 이미 있음)"

echo "[3/6] 백엔드 가상환경 + 패키지..."
cd "$(dirname "$0")/../backend"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q

echo "[4/6] .env 확인..."
if [ ! -f .env ]; then
    cp ../deploy/env.example .env
    echo "  >> backend/.env 를 만들었습니다. 편집기로 열어 값을 채우세요:"
    echo "     nano backend/.env"
    echo "  값을 채운 뒤 이 스크립트를 다시 실행하세요."
    exit 0
fi

echo "[5/6] DB 테이블 생성 + 관리자 계정..."
# 관리자 비밀번호를 환경변수로 지정하면 그 값으로 만든다.
# 안 하면 기본값(admin12345)이라 로그인 후 반드시 바꿔야 한다.
if [ -z "$ADMIN_PASSWORD" ]; then
    echo "  (관리자 비밀번호를 정하려면: ADMIN_PASSWORD=원하는비번 bash deploy/setup-server.sh)"
fi
.venv/bin/python -m app.seed
echo "  학교 데이터를 받으려면 나중에 아래를 실행하세요:"
echo "     cd backend && .venv/bin/python -m app.import_neis --majors"

echo "[6/6] 프론트 빌드..."
cd ../frontend
npm install
npm run build

echo ""
echo "=========================================="
echo "  기본 준비 완료!"
echo "  이제 systemd 서비스와 nginx를 설정하세요."
echo "  매뉴얼의 '5단계'부터 이어서 하시면 됩니다."
echo "=========================================="
