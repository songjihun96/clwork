"""기록해 자체 토큰.

계정 확인은 UDJ 가 하지만, 확인이 끝난 뒤에는 기록해가 자기 토큰을 발급한다.
그래야 화면을 볼 때마다 UDJ 를 부르지 않고, UDJ 가 잠깐 멈춰도 이미 로그인한
사람은 계속 쓸 수 있다.
"""

import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from .database import get_db
from .models import Role, User

SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production-please")
ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", str(60 * 24 * 2)))


def _validate_secret_key() -> None:
    """서버 시작 시 SECRET_KEY 를 검증한다.

    개발 환경(ENV=development 또는 ENV 미설정)에서는 기본값 허용.
    운영 환경(ENV=production 또는 그 외)에서는 기본값·짧은 값 사용을 차단.
    """
    env = (os.getenv("ENV", "") or "").lower().strip()
    is_production = env not in ("", "development", "dev", "local")

    if not is_production:
        return

    default = "change-me-in-production-please"
    if SECRET_KEY == default:
        raise RuntimeError(
            "[보안] SECRET_KEY가 기본값입니다. "
            "운영 환경에서는 반드시 고유한 SECRET_KEY 환경변수를 설정하세요. "
            "서버를 중지합니다."
        )
    if len(SECRET_KEY) < 32:
        raise RuntimeError(
            f"[보안] SECRET_KEY가 너무 짧습니다(현재 {len(SECRET_KEY)}자). "
            "최소 32자 이상의 무작위 문자열을 사용하세요. 서버를 중지합니다."
        )


_validate_secret_key()

bearer = HTTPBearer(auto_error=False)


def create_access_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "udj": user.udj_user_id,
        "role": user.role.value,
        "exp": datetime.utcnow() + timedelta(minutes=TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user_optional(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    db: Session = Depends(get_db),
) -> Optional[User]:
    if creds is None:
        return None
    try:
        payload = jwt.decode(creds.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        return None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    return user


def get_current_user(user: Optional[User] = Depends(get_current_user_optional)) -> User:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인이 필요합니다.",
        )
    return user


def require_roles(*roles: Role):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
        return user
    return dependency


require_student = require_roles(Role.student)
require_teacher = require_roles(Role.teacher)
require_admin = require_roles(Role.admin)
# 제출된 학생 일지를 볼 수 있는 계정
require_journal_viewer = require_roles(Role.teacher, Role.school, Role.admin)
