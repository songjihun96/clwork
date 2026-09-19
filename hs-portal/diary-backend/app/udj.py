"""UDJ 계정 서버와의 통신.

계정의 원본은 UDJ 다. 이곳은 창구 역할만 한다. 이용자는 기록해 화면에서
가입·로그인·정보변경·탈퇴를 하지만, 실제 처리는 UDJ 가 한다.

그래야 비밀번호 해시가 한 곳에만 있고, 탈퇴하면 두 서비스 모두에서
확실히 로그인할 수 없게 된다.
"""

import os
from typing import Optional

import requests
from fastapi import HTTPException

TIMEOUT = 12


def api_base() -> str:
    return (os.getenv("UDJ_API_BASE", "") or "http://127.0.0.1:8000").split("#", 1)[0].strip().rstrip("/")


def partner_secret() -> str:
    return (os.getenv("PARTNER_SECRET", "") or "").split("#", 1)[0].strip()


def is_ready() -> bool:
    return bool(partner_secret())


def _headers() -> dict:
    return {"X-Partner-Secret": partner_secret(), "Content-Type": "application/json"}


def _call(method: str, path: str, **kwargs) -> dict:
    """UDJ 를 부르고 결과를 돌려준다.

    UDJ 가 준 오류 문구를 그대로 이용자에게 보여준다. '이미 가입된 이메일입니다'
    같은 안내를 여기서 다시 만들면 두 서비스의 문구가 어긋난다.
    """
    if not is_ready():
        raise HTTPException(status_code=503, detail="계정 연동이 설정되지 않았습니다.")
    url = f"{api_base()}/api/partner{path}"
    try:
        res = requests.request(method, url, headers=_headers(), timeout=TIMEOUT, **kwargs)
    except requests.RequestException:
        raise HTTPException(
            status_code=503,
            detail="계정 서버에 연결하지 못했습니다. 잠시 후 다시 시도해주세요.",
        )

    if res.status_code >= 400:
        detail = "요청을 처리하지 못했습니다."
        try:
            data = res.json()
            if isinstance(data.get("detail"), str):
                detail = data["detail"]
        except ValueError:
            pass
        raise HTTPException(status_code=res.status_code, detail=detail)

    try:
        return res.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="계정 서버의 응답을 이해하지 못했습니다.")


def login(email: str, password: str) -> dict:
    """이메일·비밀번호를 UDJ 에 확인시키고 프로필을 받는다."""
    return _call("POST", "/login", json={"email": email, "password": password})


def fetch_profile(udj_user_id: int) -> Optional[dict]:
    """최신 소속 정보를 다시 받아온다. 실패하면 None(기존 값을 유지)."""
    try:
        return _call("GET", f"/users/{udj_user_id}")
    except HTTPException:
        return None


def create_user(payload: dict) -> dict:
    return _call("POST", "/users", json=payload)


def update_user(udj_user_id: int, payload: dict) -> dict:
    return _call("PATCH", f"/users/{udj_user_id}", json=payload)


def change_password(udj_user_id: int, current_password: str, new_password: str) -> dict:
    return _call("POST", f"/users/{udj_user_id}/change-password",
                 json={"current_password": current_password, "new_password": new_password})


def delete_user(udj_user_id: int, password: str) -> dict:
    return _call("POST", f"/users/{udj_user_id}/delete", json={"password": password})


def list_teachers(school_id: int) -> list:
    """이 학교의 선생님 계정 목록. 계정 원본이 UDJ 뿐이라 매번 새로 받는다."""
    return _call("GET", f"/schools/{school_id}/teachers")


def search_teacher_candidates(school_id: int, q: str) -> list:
    """선생님 권한을 줄 수 있는, 이미 가입된 계정을 UDJ에서 찾는다."""
    return _call("GET", f"/schools/{school_id}/teacher-candidates", params={"q": q})


def grant_teacher(school_id: int, user_id: int, class_name: str) -> dict:
    return _call(
        "POST", f"/schools/{school_id}/teachers/grant",
        json={"user_id": user_id, "class_name": class_name},
    )


def update_teacher(school_id: int, teacher_id: int, payload: dict) -> dict:
    return _call("PUT", f"/schools/{school_id}/teachers/{teacher_id}", json=payload)


def revoke_teacher(school_id: int, teacher_id: int) -> dict:
    return _call("DELETE", f"/schools/{school_id}/teachers/{teacher_id}")


def fetch_school_subjects(school_id: int) -> Optional[dict]:
    """학교의 학과·과목을 UDJ 에서 그때그때 받아온다.

    실패하면 None 을 돌려준다(연동 미설정 포함) — 부르는 쪽이 예전에
    받아 둔 로컬 사본으로 조용히 물러나게 하기 위해서다. UDJ 가 잠깐
    안 되더라도 학과 드롭다운이 아예 비는 것보다는, 낡았더라도 있는
    것을 보여주는 편이 낫다.
    """
    try:
        return _call("GET", f"/schools/{school_id}/subjects")
    except HTTPException:
        return None
