import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .database import get_db
from .models import Role, User

SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production-please")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", str(60 * 24 * 2)))


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

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)


def hash_password(raw: str) -> str:
    return pwd_context.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return pwd_context.verify(raw, hashed)


def create_access_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user_optional(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """비로그인 방문자도 검색은 할 수 있어야 하므로 토큰이 없으면 None."""
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


def get_current_user(
    user: Optional[User] = Depends(get_current_user_optional),
) -> User:
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


require_admin = require_roles(Role.admin)


def school_level_of(user: User) -> str:
    """학교 계정의 학교급. 학교가 없거나 값이 비면 고등학교로 본다(예전 계정)."""
    s = getattr(user, "school", None)
    return (getattr(s, "school_level", None) or "high") if s is not None else "high"


# 중학교·고등학교 학교 계정이 함께 쓰는 기능(공지 알림 설정 등).
require_school_any = require_roles(Role.school)


def require_school(user: User = Depends(require_school_any)) -> User:
    """고등학교 학교 계정 전용. 학교 홍보·운영 기능(학교 정보·일정·문의·진학정보·
    플랜 등)은 전부 이걸 쓴다. 중학교 계정은 화면에서 숨길 뿐 아니라 여기서 막는다."""
    if school_level_of(user) == "middle":
        raise HTTPException(status_code=403,
                            detail="중학교 학교 계정에서는 이용할 수 없는 기능입니다.")
    return user
require_student = require_roles(Role.student)
