"""전화번호 다루기.

번호를 저장하는 방법이 두 가지가 되면 같은 사람이 두 고객이 된다.
010-1234-5678 로 남긴 고객과 +821012345678 로 걸려온 전화가 서로를 못 찾는다.
그래서 DB 에 넣기 전에는 반드시 normalize_phone 하나만 지난다.

  받는 모양   01012345678 / 010-1234-5678 / +82 10-1234-5678 / 0082101234...
  넣는 모양   01012345678   (숫자만, 국내 0 붙은 형태)
  보는 모양   010-1234-5678 (format_phone) 또는 010-****-5678 (mask_phone)
"""

from __future__ import annotations

import re

# 국내 지역번호. 하이픈을 어디에 넣을지 가르는 데만 쓴다.
_AREA_2 = ("02",)
_AREA_3 = (
    "031", "032", "033", "041", "042", "043", "044",
    "051", "052", "053", "054", "055", "061", "062", "063", "064",
    "070", "010", "011", "016", "017", "018", "019",
    "080", "050", "060", "030",
)


def normalize_phone(raw: str) -> str:
    """어떤 모양으로 들어와도 하나의 저장형으로 만든다.

    국제표기(+82)는 국내표기(0...)로 되돌린다. 우리 고객은 사실상 전부
    국내 번호이고, 상담원이 눈으로 대조하는 것도 국내표기이기 때문이다.
    알아볼 수 없는 값은 숫자만 남겨 그대로 둔다. 억지로 고치면 엉뚱한
    고객에 붙는다.
    """
    if not raw:
        return ""
    s = str(raw).strip()

    # 국제표기 흔적을 먼저 걷어낸다: +82, 0082, 82 로 시작하는 11자리 이상
    s = re.sub(r"[^\d+]", "", s)
    if s.startswith("+82"):
        s = "0" + s[3:]
    elif s.startswith("0082"):
        s = "0" + s[4:]
    elif s.startswith("82") and len(s) >= 11:
        s = "0" + s[2:]
    s = s.replace("+", "")

    digits = "".join(c for c in s if c.isdigit())

    # +82 를 떼면 010... 이 아니라 10... 이 되는 표기도 있다.
    if digits and not digits.startswith("0") and len(digits) in (9, 10):
        digits = "0" + digits

    # 국내 번호는 아무리 길어도 12자리를 넘지 않는다. 그보다 길면 앞에
    # 사업자 식별 같은 군더더기가 붙은 것이므로 손대지 않고 그대로 둔다.
    return digits[:20]


def format_phone(value: str) -> str:
    """화면에 보여줄 모양. 저장형을 사람이 읽는 모양으로만 바꾼다."""
    d = normalize_phone(value)
    if not d:
        return ""
    if d.startswith(_AREA_2) and len(d) in (9, 10):
        return f"{d[:2]}-{d[2:-4]}-{d[-4:]}"
    if d.startswith(_AREA_3) and len(d) in (10, 11):
        return f"{d[:3]}-{d[3:-4]}-{d[-4:]}"
    if len(d) in (10, 11):
        return f"{d[:3]}-{d[3:-4]}-{d[-4:]}"
    return d


def mask_phone(value: str) -> str:
    """가운데를 가린다. 01012345678 -> 010-****-5678

    휴대폰 번호에서는 cs.py 의 같은 이름 함수와 결과가 같다. 화면마다 가리는
    자리가 다르면 상담원이 같은 번호를 다른 번호로 읽기 때문이다.

    다만 서울 유선(02)은 국번이 두 자리라, 앞 세 자리를 남기면 021 처럼
    있지도 않은 지역번호가 보인다. 그래서 02 만 따로 둔다.
    """
    digits = normalize_phone(value)
    if len(digits) < 7:
        return "***" if digits else ""
    if digits.startswith("02"):
        return f"02-****-{digits[-4:]}"
    return f"{digits[:3]}-****-{digits[-4:]}"


def is_valid_phone(value: str) -> bool:
    """저장할 만한 번호인지. 너무 짧은 값이 고객으로 들어오는 것만 막는다."""
    d = normalize_phone(value)
    return 8 <= len(d) <= 12


def phone_variants(value: str) -> list:
    """검색어 하나로 여러 표기를 훑기 위한 후보들.

    예전에 정규화 없이 들어간 값이 남아 있을 수 있어, 조회는 넉넉히 본다.
    """
    d = normalize_phone(value)
    if not d:
        return []
    out = {d, format_phone(d)}
    if d.startswith("0"):
        out.add("+82" + d[1:])
        out.add("82" + d[1:])
    return [v for v in out if v]
