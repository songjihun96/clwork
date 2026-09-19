"""우리업무 백엔드 — 우리동네 직업계고·기록해와 **완전히 분리된 별도 프로세스**.

**왜 따로 떼었나.** 같은 백엔드에 얹으면 업무 시스템을 한 줄 고칠 때마다
우리동네 직업계고와 상담 사이트가 같이 재시작된다. 배포가 잘못되면 셋이
한꺼번에 멈춘다. 표도 계정도 이미 따로였으니, 프로세스까지 나누면
**한쪽이 망가져도 다른 쪽은 그대로 돈다.**

**새로 설치할 것은 없다.** 기존 `backend/.venv` 를 그대로 쓴다. 필요한
라이브러리(fastapi·sqlalchemy·psycopg2·jose·passlib)가 이미 다 들어 있다.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# work-backend/.env 를 읽는다. systemd 가 EnvironmentFile 로 이미 넣어 준
# 값은 덮지 않으므로(load_dotenv 의 기본 동작), 운영에서는 systemd 가 이긴다.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
