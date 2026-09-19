"""외부 AI 로 글을 보내기 전에 개인을 알아볼 수 있는 것을 가려낸다.

개인정보처리방침 제7조에 이렇게 적어 두었다.

    이름, 학교명, 이메일, 전화번호 등 개인을 알아볼 수 있는 정보는
    전송 전에 서비스가 가명으로 바꾸어 처리하므로 이전되지 않습니다.

이 파일이 그 약속을 지키는 자리다. 여기가 새면 방침이 거짓말이 된다.

**되돌릴 수 있게 바꾼다**

지우지 않고 자리표(`[[NAME_1]]`)로 바꾼다. AI 가 돌려준 글에서 자리표를
원래 말로 되돌리면 학생은 자기 이름이 그대로 있는 글을 받는다.
지워 버리면 "누가 무엇을 했는지" 가 사라져 글이 이상해진다.

**두 갈래로 찾는다**

  1) 아는 것 — 그 학생의 이름·학교·이메일. 확실하니 먼저 바꾼다.
  2) 모르는 것 — 글 속의 다른 사람 이름, 전화번호, 주민번호 같은 것.
     생김새로 찾는다. 놓칠 수 있으므로 1) 을 반드시 함께 쓴다.

**놓치는 것이 있다**

한국어 이름은 일반 낱말과 겹쳐(`이한` `강산`) 완벽히 가려낼 수 없다.
그래서 학생에게 "글이 외부로 나간다" 고 알리고 동의를 받는 절차를
함께 둔다. 기술만으로 막는다고 하지 않는다.
"""

import re
from typing import Dict, List, Tuple

# 자리표 모양. 본문에 우연히 나올 수 없는 형태로 잡는다.
TOKEN = "[[{kind}_{n}]]"
TOKEN_RE = re.compile(r"\[\[([A-Z]+)_(\d+)\]\]")


# ── 생김새로 찾는 것들 ──────────────────────────────────────
# 순서가 중요하다. 주민번호를 먼저 찾아야 그 안의 숫자가
# 전화번호로 잘못 잡히지 않는다.
PATTERNS: List[Tuple[str, re.Pattern]] = [
    # 주민등록번호. 뒷자리가 있으면 무조건 가린다.
    ("RRN", re.compile(r"\d{6}\s*[-–]\s*[1-4]\d{6}")),
    # 이메일
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    # 휴대폰·일반전화
    ("PHONE", re.compile(r"0\d{1,2}[-–.\s]?\d{3,4}[-–.\s]?\d{4}")),
    # 계좌번호로 보이는 긴 숫자 묶음
    ("ACCOUNT", re.compile(r"\d{2,6}[-–]\d{2,6}[-–]\d{2,7}")),
    # 학교 이름. '○○고등학교' 처럼 온전한 이름만 잡는다.
    #
    # 예전에는 '고' 와 '중' 한 글자로도 끝나면 학교로 봤는데,
    # 그러면 '맡겠다고', '잘했다고' 같은 평범한 말이 통째로 가려진다.
    # 실제로 초안에 [[SCHOOL_2]] 가 열 개 넘게 나오는 일이 있었다.
    #
    # 줄여 부르는 이름('근명고')은 이 규칙으로 못 잡지만,
    # 그 학생의 학교는 build() 에서 미리 등록해 두므로 가려진다.
    ("SCHOOL", re.compile(
        r"[가-힣]{2,10}(?:고등학교|중학교|초등학교|대학교|여자고등학교|공업고등학교)")),
    # 주소로 보이는 대목
    ("ADDRESS", re.compile(r"[가-힣]+(?:시|군|구)\s*[가-힣]+(?:읍|면|동|로|길)\s*\d[\d-]*")),
]

# 사람 이름처럼 보이는 대목. 호칭이 붙어 있을 때만 잡는다.
# 그냥 두 세 글자를 다 이름으로 보면 멀쩡한 낱말까지 가려진다.
# 성씨. 이름 앞에 오는 글자로 한정해야 '끝났고 선생님' 의 '났고' 처럼
# 평범한 말이 사람 이름으로 잡히지 않는다.
SURNAMES = (
    "김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노하곽성"
    "차주우구민류진지엄채원천방공현함변염양변여추노도소신석선설마길연위표명"
    "기반라왕금옥육인맹제모장남탁국여진어은편구용"
)

# 이름과 호칭 사이의 공백도 그대로 살려야 되돌렸을 때 원문과 같아진다.
NAME_WITH_TITLE = re.compile(
    r"([" + SURNAMES + r"][가-힣]{1,3})(\s*)"
    r"(선생님|쌤|교수님|팀장|반장|부장|과장|대리|사원|학생|군|양|씨)"
)

# 호칭 앞에 와도 이름이 아닌 말들. 성씨로 시작해 걸리는 것을 걸러낸다.
# (예: '오늘 선생님' 의 '오늘', '고생한 학생' 의 '고생한')
# 호칭 없이 조사만 붙은 이름(김민수가, 이지훈과)은 잡지 않는다.
#
# 성씨 + 두 글자 + 조사로 규칙을 세워 봤더니 '강의실은', '안전모가',
# '이번에는' 같은 평범한 말이 함께 걸렸다. 한국어 이름은 일반 낱말과
# 글자가 겹쳐, 호칭이라는 단서 없이는 가려낼 수 없다.
#
# 잘못 가리면 AI 에게 뜻이 통하지 않는 글이 가고, 초안이 이상해진다.
# 실제로 [[SCHOOL_2]] 가 열 개 넘게 박힌 초안이 나온 적이 있다.
#
# 그래서 여기서는 놓치는 쪽을 택하고, 대신 학생에게 "글이 외부로
# 나간다" 고 알리고 동의를 받는다. 기술만으로 막는다고 하지 않는다.

NOT_A_NAME = {
    "오늘", "어제", "내일", "이번", "저번", "지난", "다음", "당시", "그때",
    "우리", "저희", "모든", "여러", "담당", "국어", "수학", "영어", "과학",
    "체육", "음악", "미술", "기술", "가정", "도덕", "역사", "지리", "윤리",
    "고생", "노력", "성실", "친절", "무서", "재밌", "좋은", "나쁜", "새로",
    "강의", "수업", "실습", "전공", "학과", "학년", "반의", "조의",
}


class Pseudonymizer:
    """글에서 개인을 알아볼 수 있는 것을 자리표로 바꾸고, 되돌린다.

    한 번 쓰고 버린다. 같은 말은 같은 자리표를 받으므로,
    글 안에서 "그 사람" 이 누구인지는 AI 도 알 수 있다.
    """

    def __init__(self):
        self._map: Dict[str, str] = {}      # 원래 말 → 자리표
        self._back: Dict[str, str] = {}     # 자리표 → 원래 말
        self._count: Dict[str, int] = {}

    def _token_for(self, kind: str, value: str) -> str:
        if value in self._map:
            return self._map[value]
        self._count[kind] = self._count.get(kind, 0) + 1
        token = TOKEN.format(kind=kind, n=self._count[kind])
        self._map[value] = token
        self._back[token] = value
        return token

    def learn(self, kind: str, value: str) -> None:
        """미리 아는 것을 등록한다. 그 학생의 이름·학교 같은 것.

        너무 짧은 말은 등록하지 않는다. 한 글자를 가리면 글 곳곳이
        자리표로 뒤덮인다.
        """
        v = (value or "").strip()
        if len(v) < 2:
            return
        self._token_for(kind, v)

    def mask(self, text: str) -> str:
        """글에서 개인을 알아볼 수 있는 것을 자리표로 바꾼다."""
        out = text or ""

        # 1) 아는 것부터. 긴 말을 먼저 바꿔야 '근명고등학교' 가
        #    '근명고' 로 잘려 반쪽만 가려지는 일이 없다.
        for value in sorted(self._map, key=len, reverse=True):
            if value and value in out:
                out = out.replace(value, self._map[value])

        # 2) 호칭이 붙은 이름
        def _name(m):
            word = m.group(1)
            if word in NOT_A_NAME:
                return m.group(0)      # 이름이 아니므로 그대로 둔다
            return self._token_for("PERSON", word) + m.group(2) + m.group(3)

        out = NAME_WITH_TITLE.sub(_name, out)


        # 3) 생김새로 찾는 것들
        for kind, pat in PATTERNS:
            out = pat.sub(lambda m: self._token_for(kind, m.group(0)), out)

        return out

    def unmask(self, text: str) -> str:
        """AI 가 돌려준 글에서 자리표를 원래 말로 되돌린다.

        AI 가 자리표를 지웠거나 바꿔 썼을 수 있다. 그런 것은
        그대로 두고, 아는 자리표만 되돌린다.
        """
        out = text or ""
        for token, value in self._back.items():
            out = out.replace(token, value)
        return out

    @property
    def replaced(self) -> int:
        return len(self._back)


def build(user, extra: List[str] = None) -> Pseudonymizer:
    """그 학생에 맞는 가림막을 만든다.

    이름·학교·이메일처럼 우리가 아는 것을 먼저 등록해 두면,
    생김새로 못 찾는 경우에도 확실히 가려진다.
    """
    p = Pseudonymizer()
    if user is not None:
        p.learn("PERSON", getattr(user, "name", "") or "")
        p.learn("SCHOOL", getattr(user, "school_name", "") or "")
        p.learn("EMAIL", getattr(user, "email", "") or "")
        p.learn("CLASS", getattr(user, "class_name", "") or "")
        p.learn("DEPT", getattr(user, "department", "") or "")
    for v in (extra or []):
        p.learn("PERSON", v)
    return p


def build_many(users, extra: List[str] = None) -> Pseudonymizer:
    """여러 학생이 함께 쓴 글(팀 게시판 등)을 가릴 때 쓴다.

    build() 는 호출한 사람 한 명만 알아, 팀 글에 섞인 다른 팀원 이름은
    호칭 뒤에 붙은 경우("민수 학생")가 아니면 못 가린다("민수가 실험을
    맡고" 처럼 흔한 표현은 그냥 지나간다). 팀원 전원을 미리 등록해 두면
    이 문제가 사라진다 — 단발성 인스턴스라는 점(한 번 쓰고 버림)은
    build() 와 같다."""
    p = Pseudonymizer()
    for user in users or []:
        if user is None:
            continue
        p.learn("PERSON", getattr(user, "name", "") or "")
        p.learn("SCHOOL", getattr(user, "school_name", "") or "")
        p.learn("EMAIL", getattr(user, "email", "") or "")
        p.learn("CLASS", getattr(user, "class_name", "") or "")
        p.learn("DEPT", getattr(user, "department", "") or "")
    for v in (extra or []):
        p.learn("PERSON", v)
    return p


# ── 새어 나갔는지 확인 ──────────────────────────────────────
# 보내기 직전에 한 번 더 본다. 가림막이 놓친 것이 있으면
# 보내지 않고 멈춘다. 방침에 적은 약속을 코드로도 지킨다.

LEAK_CHECKS = [
    ("주민등록번호", re.compile(r"\d{6}\s*[-–]\s*[1-4]\d{6}")),
    ("이메일", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("전화번호", re.compile(r"0\d{1,2}[-–.\s]?\d{3,4}[-–.\s]?\d{4}")),
]


def find_leaks(text: str) -> List[str]:
    """아직 남아 있는 개인정보를 찾는다. 무엇이 남았는지만 알려준다.

    남은 값 자체는 돌려주지 않는다. 로그에 찍혀 되레 새면 안 된다.
    """
    out = []
    for label, pat in LEAK_CHECKS:
        if pat.search(text or ""):
            out.append(label)
    return out
