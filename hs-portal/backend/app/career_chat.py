"""진로 테스트 결과의 추천 학과 챗봇.

역할을 둘로 나눴다.

  · **사실은 정보표(career_data)에서만 나온다.** 초봉·자격증·되는 길 같은 것은
    AI 가 그럴듯하게 지어내는 버릇이 있고, 중학생과 학부모는 그걸 그대로
    믿는다. 그래서 Claude 에게는 그 계열의 표만 주고 "여기 없는 사실은 말하지
    마라"고 못 박는다.
  · **Claude 는 풀어 말하기와 되묻기를 맡는다.** 표를 중학생 말로 바꾸고,
    "그럼 수학 못해도 돼요?" 같은 자유 질문에 답한다.

단추로 누르는 질문(되는 길·자격증·초봉)은 **AI 를 부르지 않는다** — 화면이
표에서 바로 보여 준다. AI 는 학생이 직접 쳐서 물을 때만 쓴다. 가장 많이
눌리는 질문에 돈이 안 들고, 틀릴 일도 없다.

대상이 중학생이라 지키는 것:
  · 이름·학교·연락처를 묻지 않는다
  · 진로와 상관없는 이야기는 부드럽게 되돌린다
  · 힘든 마음을 털어놓으면 믿을 만한 어른과 청소년상담 1388 을 알려 준다
"""

from __future__ import annotations

import os
import time
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request

# **패키지가 없어도 서버는 떠야 한다.** 이 서비스는 zip 을 풀어 올리고 패키지는
# 따로 손으로 깐다. 깔기 전에 풀면 여기서 ImportError 가 나서 UDJ 사이트
# 전체가 안 뜬다 — 챗봇 하나 때문에 학교 검색까지 죽는 셈이다. 없으면 챗봇의
# 직접 묻기만 끄고(단추 질문은 표로 그대로 된다) 나머지는 평소대로 돈다.
try:
    import anthropic
except ImportError:          # pragma: no cover - 서버에 아직 안 깔았을 때
    anthropic = None
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import career_data
from .auth import require_admin
from .database import get_db
from .models import User

router = APIRouter(prefix="/api", tags=["career-chat"])

MODEL = os.getenv("CAREER_CHAT_MODEL", "claude-opus-5")

# 한 대화에서 받는 질문 수와 한 번에 칠 수 있는 글자 수. 중학생 상담이라
# 길게 이어질 이유가 없고, 로그인 없이 여는 창구라 끝없이 돌리게 둘 수 없다.
MAX_TURNS = 8
MAX_CHARS = 300

# IP 별 한 시간에 AI 에게 물을 수 있는 횟수(메모리, 서버 한 대 기준).
_RECENT: dict[str, list[float]] = {}
MAX_PER_HOUR = 20
WINDOW_SEC = 3600


def _client():
    """키나 패키지가 없으면 None — 그러면 자유 질문 칸만 닫고 표는 그대로 보여 준다.

    검사에서 이 함수를 바꿔 끼워 실제 API 를 부르지 않게 한다.
    """
    if anthropic is None or not os.getenv("ANTHROPIC_API_KEY"):
        return None
    return anthropic.Anthropic(timeout=30.0, max_retries=2)


def ai_available() -> bool:
    return anthropic is not None and bool(os.getenv("ANTHROPIC_API_KEY"))


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate(ip: str) -> None:
    now = time.time()
    recent = [t for t in _RECENT.get(ip, []) if now - t < WINDOW_SEC]
    _RECENT[ip] = recent
    if len(recent) >= MAX_PER_HOUR:
        raise HTTPException(status_code=429,
                            detail="질문이 너무 많아요. 잠시 뒤에 다시 물어봐 주세요.")
    recent.append(now)


# ---------------------------------------------------------------- 지시문
def _table_text(group: str, jobs: list) -> str:
    """Claude 에게 줄 표. 사람이 읽기 좋은 모양 그대로 준다."""
    lines = [f"[계열] {group}"]
    for j in jobs:
        lines.append("")
        lines.append(f"■ {j.get('name', '')}")
        lines.append(f"- 하는 일: {j.get('easy', '')}")
        path = j.get("path") or []
        if path:
            lines.append("- 되는 길: " + " → ".join(path))
        if j.get("effort"):
            lines.append(f"- 필요한 노력: {j['effort']}")
        certs = j.get("certs") or []
        lines.append("- 추천 자격증: " + (", ".join(certs) if certs else "꼭 필요한 자격증은 따로 없음"))
        if (j.get("salary") or "").strip():
            src = (j.get("salary_source") or "").strip()
            lines.append(f"- 첫해 연봉(확인된 값): {j['salary']}" + (f" (출처: {src})" if src else ""))
        else:
            lines.append("- 첫해 연봉: 아직 확인된 값 없음")
    return "\n".join(lines)


def system_prompt(group: str, jobs: list) -> str:
    lookup = ", ".join(f"{x['name']}({x['url']})" for x in career_data.SALARY_LOOKUP)
    return f"""너는 '우리동네 직업계고' 사이트의 진로 도우미야. 진로 테스트를 마친 중학생이
추천받은 학과와 관련된 직업을 물어보면 답해 줘.

말투
- 중학생이 한 번에 알아듣는 쉬운 말로 써. 존댓말 '~해요'체.
- 전문용어를 쓰지 마. 꼭 필요하면 바로 뒤 괄호에 쉬운 말로 풀어 줘.
- 짧게. 보통 3~6문장. 줄바꿈과 '•' 정도만 쓰고, 제목·표·굵은 글씨 같은 꾸밈은 쓰지 마.

사실은 아래 표에서만
- 초봉·연봉·자격증 이름·되는 길은 아래 표에 있는 것만 말해. 표에 없는 숫자(연봉,
  취업률, 합격률 등)나 자격증 이름, 학교·회사 이름은 절대 지어내지 마.
- 표에 첫해 연봉이 "아직 확인된 값 없음"이면 숫자를 말하지 말고, 회사 크기와 지역에
  따라 많이 달라서 확인된 숫자가 아직 없다고 솔직히 말한 뒤 {lookup} 에서 찾아볼 수
  있다고 알려 줘.
- 표로 답할 수 없는 질문이면 모른다고 말하고, 학교 선생님이나 직업계고 입학 설명회에서
  물어보라고 권해 줘.

지켜야 할 것
- 이름, 학교, 전화번호 같은 개인정보를 묻지 마.
- 진로와 상관없는 이야기(숙제 대신 풀기, 게임, 연애 등)는 부드럽게 진로 이야기로 되돌려.
- 학생이 힘들거나 무섭다고 털어놓으면, 따뜻하게 받아 주고 부모님이나 선생님 같은 믿을
  만한 어른, 그리고 청소년상담 1388(전화·문자 1388)에 이야기해 보라고 알려 줘.

표
{_table_text(group, jobs)}
"""


# ---------------------------------------------------------------- 공개
@router.get("/career-guide")
def get_career_guide(group: str, db: Session = Depends(get_db)):
    """한 계열의 표. 단추 질문(되는 길·자격증·초봉)은 화면이 이것으로 바로 답한다."""
    jobs = career_data.jobs_of(db, group)
    if not jobs:
        raise HTTPException(status_code=404, detail="해당 계열의 정보가 없습니다.")
    return {
        "group": group,
        "jobs": jobs,
        "salary_lookup": career_data.SALARY_LOOKUP,
        "ai_available": ai_available(),
        "max_turns": MAX_TURNS,
        "max_chars": MAX_CHARS,
    }


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class ChatIn(BaseModel):
    group: str = Field(min_length=1, max_length=40)
    messages: List[ChatMessage]


@router.post("/career-chat")
def career_chat(payload: ChatIn, request: Request, db: Session = Depends(get_db)):
    """학생이 직접 쳐서 묻는 질문에 답한다."""
    jobs = career_data.jobs_of(db, payload.group)
    if not jobs:
        raise HTTPException(status_code=404, detail="해당 계열의 정보가 없습니다.")

    msgs = payload.messages
    if not msgs or msgs[-1].role != "user":
        raise HTTPException(status_code=400, detail="질문을 입력해 주세요.")
    if len(msgs[-1].content.strip()) > MAX_CHARS:
        raise HTTPException(status_code=400,
                            detail=f"질문은 {MAX_CHARS}자 안으로 써 주세요.")
    if sum(1 for m in msgs if m.role == "user") > MAX_TURNS:
        raise HTTPException(status_code=400,
                            detail="이 대화에서는 여기까지 물어볼 수 있어요. 새로 열어서 다시 물어봐 주세요.")

    client = _client()
    if client is None:
        raise HTTPException(status_code=503, detail="지금은 AI 도우미를 쓸 수 없어요.")

    _check_rate(_client_ip(request))

    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=4096,
            # 계열마다 지시문이 같다 — 같은 계열 대화가 이어지면 이 부분을 캐시에서 읽는다.
            system=[{"type": "text", "text": system_prompt(payload.group, jobs),
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": m.role, "content": m.content} for m in msgs],
            # 짧은 상담 답이라 깊게 생각할 일이 적다.
            output_config={"effort": "low"},
            # 안전 분류기가 거절하면 서버가 알맞은 다른 모델로 한 번 더 돌려 준다.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError:
        print("[진로챗] API 키가 잘못됐습니다 — ANTHROPIC_API_KEY 확인", flush=True)
        raise HTTPException(status_code=503, detail="지금은 AI 도우미를 쓸 수 없어요.")
    except anthropic.RateLimitError:
        raise HTTPException(status_code=503, detail="질문이 몰려 있어요. 잠시 뒤에 다시 물어봐 주세요.")
    except anthropic.BadRequestError as e:
        print(f"[진로챗] 잘못된 요청: {e.message}", flush=True)
        raise HTTPException(status_code=502, detail="답을 만들지 못했어요. 다시 물어봐 주세요.")
    except anthropic.APIStatusError as e:
        print(f"[진로챗] API 오류 {e.status_code}", flush=True)
        raise HTTPException(status_code=503, detail="잠시 뒤에 다시 물어봐 주세요.")
    except anthropic.APIConnectionError:
        raise HTTPException(status_code=503, detail="잠시 뒤에 다시 물어봐 주세요.")

    # 안전상 끝까지 거절됐으면 본문을 읽지 않고 정해진 말로 답한다.
    if response.stop_reason == "refusal":
        return {"reply": "그 질문에는 답하기 어려워요. 추천받은 직업에 대해 궁금한 걸 물어봐 줄래요?"}

    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise HTTPException(status_code=502, detail="답을 만들지 못했어요. 다시 물어봐 주세요.")

    u = response.usage
    print(f"[진로챗] group={payload.group} in={u.input_tokens} out={u.output_tokens} "
          f"cache_read={getattr(u, 'cache_read_input_tokens', 0)}", flush=True)
    return {"reply": text}


# ---------------------------------------------------------------- 관리
@router.get("/admin/career-guide")
def admin_get_guide(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    guide = career_data.load_guide(db)
    missing = sum(1 for g in guide.values() for j in (g.get("jobs") or [])
                  if not (j.get("salary") or "").strip())
    return {"guide": guide, "salary_lookup": career_data.SALARY_LOOKUP,
            "salary_missing": missing, "ai_available": ai_available()}


class JobIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    easy: str = Field(default="", max_length=200)
    path: List[str] = []
    effort: str = Field(default="", max_length=300)
    certs: List[str] = []
    salary: str = Field(default="", max_length=80)
    salary_source: str = Field(default="", max_length=200)


class GuideIn(BaseModel):
    group: str = Field(min_length=1, max_length=40)
    jobs: List[JobIn]


@router.put("/admin/career-guide")
def admin_put_guide(payload: GuideIn, db: Session = Depends(get_db),
                    user: User = Depends(require_admin)):
    guide = career_data.load_guide(db)
    if payload.group not in guide:
        raise HTTPException(status_code=404, detail="없는 계열입니다.")
    jobs = []
    for j in payload.jobs:
        salary = j.salary.strip()
        source = j.salary_source.strip()
        # 출처 없는 숫자는 받지 않는다. 챗봇이 이 값을 사실로 말하기 때문에,
        # 어디서 봤는지 적어 두지 않으면 나중에 맞는지 확인할 길이 없다.
        if salary and not source:
            raise HTTPException(status_code=400,
                                detail=f"'{j.name}' 초봉의 출처를 적어 주세요.")
        jobs.append({
            "name": j.name.strip(),
            "easy": j.easy.strip(),
            "path": [p.strip() for p in j.path if p.strip()][:8],
            "effort": j.effort.strip(),
            "certs": [c.strip() for c in j.certs if c.strip()][:6],
            "salary": salary,
            "salary_source": source,
        })
    guide[payload.group] = {"jobs": jobs}
    career_data.save_guide(db, guide)
    return admin_get_guide(db, user)
