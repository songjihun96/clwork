"""통장 거래내역 파일 읽기.

은행마다 열 구성이 제각각이다. 어떤 곳은 입금액과 출금액이 나뉘어 있고,
어떤 곳은 거래금액 하나에 입출금 구분이 따로 있다. 파일 앞쪽에 계좌 정보가
몇 줄 붙어 헤더가 5행쯤부터 시작하는 경우도 흔하다.

그래서 열 위치를 고정하지 않고 **머리글 이름을 보고 찾는다.** 못 찾으면
포기하지 말고 숫자와 이름이 있는 열을 추측한다. 읽은 결과는 화면에 먼저
보여주고, 사람이 확인한 뒤에 대조로 넘어간다.

카카오뱅크처럼 비밀번호가 걸린 파일은 msoffcrypto 로 먼저 풀어서 읽는다.
"""

import csv
import io
import re
from typing import List, Optional, Tuple

# ── 머리글에 나올 법한 낱말 ─────────────────────────────────
# 앞에 있는 것을 먼저 고른다. '입금액' 이 '거래금액' 보다 정확하기 때문이다.
IN_AMOUNT_WORDS = ("입금액", "입금금액", "맡기신금액", "입금")
OUT_AMOUNT_WORDS = ("출금액", "출금금액", "찾으신금액", "출금")
ANY_AMOUNT_WORDS = ("거래금액", "거래금액(원)", "금액")
NAME_WORDS = ("보내는분", "받는분", "입금자", "거래상대방", "상대방",
              "적요", "내용", "기재내용", "거래내용", "메모", "비고")
DATE_WORDS = ("거래일시", "거래일자", "일시", "날짜", "거래시간")
TYPE_WORDS = ("구분", "거래구분", "입출금구분", "종류")

# 입출금 구분 열에 들어가는 값
IN_MARKS = ("입금", "입", "받음", "deposit", "credit")

MAX_ROWS = 3000            # 한 번에 읽을 최대 줄 수
HEADER_SCAN_ROWS = 20      # 머리글을 찾을 때 훑을 앞부분 줄 수


def _norm(v) -> str:
    return re.sub(r"\s+", "", str(v or ""))


def _to_amount(v) -> Optional[int]:
    """'5,900' '5900원' '-3,000' 같은 값을 정수로 바꾼다."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        n = int(abs(v))
        return n if n > 0 else None
    text = re.sub(r"[^\d.-]", "", str(v))
    if not text or text in ("-", "."):
        return None
    try:
        n = int(abs(float(text)))
    except ValueError:
        return None
    return n if n > 0 else None


def read_table(data: bytes, filename: str, password: str = "") -> List[list]:
    """파일을 줄의 목록으로 바꾼다. (xlsx / xls / csv)"""
    name = (filename or "").lower()

    if name.endswith(".csv") or name.endswith(".txt"):
        return _read_csv(data)

    stream = io.BytesIO(data)

    # 비밀번호가 걸린 파일(카카오뱅크 등)은 먼저 푼다.
    # 잠긴 파일은 zip 이 아니라 CDFV2 형식이라 그냥 열면 실패한다.
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        try:
            import msoffcrypto
        except ImportError:
            # 라이브러리가 빠진 것은 설정 문제다. 무엇을 해야 하는지 알려준다.
            raise ValueError(
                "잠긴 파일을 열려면 서버에 msoffcrypto-tool 이 설치되어야 합니다. "
                "서버에서 pip install -r requirements.txt 를 실행한 뒤 다시 시도해주세요."
            )
        office = msoffcrypto.OfficeFile(stream)
        if not password:
            raise ValueError(
                "비밀번호가 걸린 파일입니다. 은행에서 받을 때 정한 비밀번호를 함께 입력해주세요."
            )
        out = io.BytesIO()
        try:
            office.load_key(password=password)
            office.decrypt(out)
        except Exception:
            raise ValueError("비밀번호가 맞지 않습니다.")
        out.seek(0)
        stream = out

    try:
        import openpyxl
        wb = openpyxl.load_workbook(stream, data_only=True, read_only=True)
        ws = wb.worksheets[0]
        rows = []
        for row in ws.iter_rows(max_row=MAX_ROWS, values_only=True):
            rows.append(list(row))
        return rows
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"엑셀 파일을 읽지 못했습니다. ({exc})")


def _read_csv(data: bytes) -> List[list]:
    # 은행이 내려주는 csv 는 대개 euc-kr 이다. utf-8 도 함께 시도한다.
    text = None
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("파일의 문자 인코딩을 알 수 없습니다.")
    return [row for row in csv.reader(io.StringIO(text))][:MAX_ROWS]


def find_header(rows: List[list]) -> Tuple[int, dict]:
    """머리글 줄과 열 위치를 찾는다.

    앞부분을 훑으며 '금액' 계열 낱말이 들어간 줄을 머리글로 본다.
    돌려주는 값은 (머리글 줄 번호, {역할: 열번호}).
    """
    best_i, best_cols, best_score = -1, {}, 0

    for i, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        cells = [_norm(c) for c in row]
        if not any(cells):
            continue
        cols, score = {}, 0

        for j, cell in enumerate(cells):
            if not cell:
                continue
            if "in_amount" not in cols and any(w == cell or cell.startswith(w)
                                               for w in IN_AMOUNT_WORDS):
                cols["in_amount"] = j; score += 3; continue
            if "out_amount" not in cols and any(w == cell or cell.startswith(w)
                                                for w in OUT_AMOUNT_WORDS):
                cols["out_amount"] = j; score += 2; continue
            if "amount" not in cols and any(w in cell for w in ANY_AMOUNT_WORDS):
                cols["amount"] = j; score += 2; continue
            if "type" not in cols and any(w == cell for w in TYPE_WORDS):
                cols["type"] = j; score += 1; continue
            if "name" not in cols and any(w in cell for w in NAME_WORDS):
                cols["name"] = j; score += 2; continue
            if "date" not in cols and any(w in cell for w in DATE_WORDS):
                cols["date"] = j; score += 1; continue

        # 금액 열이 하나도 없으면 머리글이라 볼 수 없다.
        if not ({"in_amount", "amount"} & set(cols)):
            continue
        if score > best_score:
            best_i, best_cols, best_score = i, cols, score

    return best_i, best_cols


def parse_file(data: bytes, filename: str, password: str = "") -> dict:
    """파일에서 입금과 출금을 나눠 뽑는다.

    구독 결제를 맞출 때는 들어온 돈만, 환불 송금을 맞출 때는 나간 돈만
    본다. 섞이면 엉뚱한 건에 붙으므로 처음부터 갈라 둔다.
    """
    rows = read_table(data, filename, password)
    if not rows:
        raise ValueError("빈 파일입니다.")

    header_i, cols = find_header(rows)
    if header_i < 0:
        raise ValueError(
            "금액 열을 찾지 못했습니다. 은행에서 받은 원본 파일인지 확인해주세요."
        )

    header_names = [str(c or "") for c in rows[header_i]]
    out, outgoing = [], []

    for row in rows[header_i + 1:]:
        if not row or not any(_norm(c) for c in row):
            continue

        amount = None
        is_in = True

        # 입금액 열이 따로 있으면 그것만 본다. 값이 없으면 출금 줄이다.
        if "in_amount" in cols:
            amount = _to_amount(row[cols["in_amount"]] if cols["in_amount"] < len(row) else None)
            if amount is None:
                amount = _to_amount(row[cols["out_amount"]]) if (
                    "out_amount" in cols and cols["out_amount"] < len(row)) else None
                if amount is None:
                    continue
                is_in = False
        else:
            amount = _to_amount(row[cols["amount"]] if cols["amount"] < len(row) else None)
            if amount is None:
                continue
            # 구분 열이 있으면 그 값으로 입출금을 가른다.
            if "type" in cols and cols["type"] < len(row):
                kind = _norm(row[cols["type"]])
                if kind and not any(m in kind.lower() for m in IN_MARKS):
                    is_in = False
            # 출금액 열에 값이 있으면 그 줄은 출금이다.
            elif "out_amount" in cols and cols["out_amount"] < len(row):
                if _to_amount(row[cols["out_amount"]]) is not None:
                    is_in = False

        name = ""
        if "name" in cols and cols["name"] < len(row):
            name = str(row[cols["name"]] or "").strip()[:40]

        when = ""
        if "date" in cols and cols["date"] < len(row):
            when = str(row[cols["date"]] or "").strip()[:30]

        line = " ".join(str(c) for c in row if c not in (None, ""))[:200]
        item = {"amount": amount, "name": name, "when": when, "line": line}
        (out if is_in else outgoing).append(item)

    return {
        "deposits": out,
        "withdrawals": outgoing,
        "skipped": len(outgoing),
        "header_row": header_i + 1,
        "columns": {k: (header_names[v] if v < len(header_names) else "") for k, v in cols.items()},
    }
