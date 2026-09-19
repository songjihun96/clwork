import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import StrictRequest

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128


class RegisterRequest(StrictRequest):
    email: EmailStr = Field(max_length=320)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    display_name: str | None = Field(default=None, min_length=1, max_length=80)


class LoginRequest(StrictRequest):
    email: EmailStr = Field(max_length=320)
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class RefreshRequest(StrictRequest):
    refresh_token: str = Field(min_length=20, max_length=128)


class LogoutRequest(StrictRequest):
    refresh_token: str = Field(min_length=20, max_length=128)


class IdentityLoginRequest(StrictRequest):
    id_token: str = Field(min_length=20, max_length=8192)
    nonce: str | None = Field(default=None, min_length=8, max_length=256)
    # Apple returns the user's name only on the very first authorization, to the app — not in the token.
    display_name: str | None = Field(default=None, min_length=1, max_length=80)


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str | None
    display_name: str | None
    created_at: datetime


class TokenResponse(BaseModel):
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    access_token: str
    access_token_expires_at: datetime
    refresh_token: str
    refresh_token_expires_at: datetime
    user: UserResponse


class DeleteAccountRequest(StrictRequest):
    password: str | None = Field(default=None, min_length=1, max_length=PASSWORD_MAX_LENGTH)
