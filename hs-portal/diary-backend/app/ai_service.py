"""AI 로 일지를 분석하고 자소서를 돕는 자리.

`llm.py` 는 "부르는 법" 만 안다. 여기서 "무엇을 시킬지" 를 정한다.
개인정보 가리기 → 지시문 채우기 → 부르기 → 되돌리기 → 검사하기가
한 흐름으로 이어진다.

**기존 것을 버리지 않는다**

`ai.py` 의 키워드 매칭은 그대로 쓴다. 일지가 수백 건이 되어도 전부
AI 에게 보내면 돈과 시간이 감당되지 않는다. 키워드로 후보를 몇 개로
줄인 뒤, 그것만 AI 에게 물어본다.

    전체 일지 → (키워드) 후보 몇 개 → (AI) 정밀 판단

**AI 가 지어낸 것은 걸러낸다**

만든 쪽과 확인하는 쪽을 나눈다. 초안을 만든 뒤 다시 한 번
"경험에 없는 내용이 있는가" 를 물어본다. 문제가 있으면 학생에게
그대로 알린다. 우리가 임의로 고쳐 주지 않는다. 자기 글이기 때문이다.
"""

import hashlib
import json
from typing import Dict, List, Optional

from . import ai, ai_prompts, llm, privacy

# 한 번에 AI 에게 보낼 후보 일지 수. 늘리면 정확해지지만 돈이 더 든다.
MAX_CANDIDATES = 5

# 자소서 한 항목의 기본 글자 수
DEFAULT_LIMIT = 1000


def content_hash(text: str) -> str:
    """글의 지문. 글이 바뀌었는지 가리는 데 쓴다."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def journal_text(entry, content: Dict[str, str]) -> str:
    """일지의 여러 칸을 하나의 글로 잇는다.

    칸 이름을 함께 적어야 AI 가 무엇에 대한 답인지 알 수 있다.
    """
    labels = dict(ai.field_labels(entry.kind))
    parts = []
    for key, label in ai.field_labels(entry.kind):
        body = (content.get(key) or "").strip()
        if body:
            parts.append(f"[{label}]\n{body}")
    return "\n\n".join(parts)


# ── 일지 분석 ──────────────────────────────────────────────


def analyze_journal(entry, content: Dict[str, str], user) -> dict:
    """일지 하나를 분석한다.

    반환에는 늘 `ok` 가 있다. 실패해도 예외를 던지지 않으므로
    부르는 쪽은 결과만 보고 판단하면 된다.
    """
    text = journal_text(entry, content)

    # 칸 이름([기억에 남는 일] 같은 것)을 뺀 실제 내용으로 길이를 잰다.
    # 이름까지 세면 "했다" 한 마디도 길이를 넘겨 AI 를 부르게 된다.
    body_len = sum(len((v or "").strip()) for v in content.values())
    if body_len < 20:
        return {"ok": False,
                "error": "글이 너무 짧아 분석할 내용이 없습니다. 조금 더 적어주세요.",
                "error_type": "too_short"}

    # 1) 개인정보를 가린다. 방침에 적은 약속이다.
    mask = privacy.build(user)
    safe_text = mask.mask(text)

    # 2) 보내기 직전에 한 번 더 본다. 남은 것이 있으면 보내지 않는다.
    leaks = privacy.find_leaks(safe_text)
    if leaks:
        print(f"[AI] 개인정보가 남아 보내지 않음: {', '.join(leaks)}", flush=True)
        return {"ok": False,
                "error": ("글에 연락처나 주민등록번호로 보이는 내용이 있어 "
                          "분석하지 않았습니다. 지우고 다시 시도해주세요."),
                "error_type": "leak"}

    # 3) AI 에게 물어본다.
    prompt = ai_prompts.fill(ai_prompts.JOURNAL_ANALYSIS_PROMPT, content=safe_text)
    res = llm.generate_json(prompt, temperature=0.1, op="analyze")
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    data = res.data or {}

    # 4) 자리표를 원래 말로 되돌린다.
    cleaned = mask.unmask(str(data.get("cleaned_content") or ""))
    experience = {
        k: mask.unmask(str((data.get("experience") or {}).get(k) or ""))
        for k in ("situation", "problem", "goal", "action",
                  "result", "emotion", "lesson")
    }

    skills = []
    for s in (data.get("skills") or []):
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or "").strip()
        if not name:
            continue
        try:
            conf = float(s.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        # 근거가 약한 역량은 버린다. 억지로 붙이면 면접에서 학생이 곤란해진다.
        if conf < 0.4:
            continue
        skills.append({
            "name": name,
            "evidence": mask.unmask(str(s.get("evidence") or "")),
            "confidence": round(min(max(conf, 0.0), 1.0), 2),
        })

    inappropriate = []
    for it in (data.get("inappropriate") or []):
        if not isinstance(it, dict):
            continue
        inappropriate.append({
            "text": mask.unmask(str(it.get("text") or "")),
            "category": str(it.get("category") or "INAPPROPRIATE_LANGUAGE"),
            "severity": int(it.get("severity") or 1),
            "replacement": mask.unmask(str(it.get("replacement") or "")),
            "reason": str(it.get("reason") or ""),
        })

    return {
        "ok": True,
        "cleaned_content": cleaned,
        "original_content": text,      # 학생이 언제든 견줘 볼 수 있게
        "inappropriate": inappropriate,
        "experience": experience,
        "skills": skills,
        "keywords": [str(k) for k in (data.get("keywords") or [])][:10],
        "model": llm.MODEL,
        "duration_ms": res.duration_ms,
    }


# ── 문항과 경험의 어울림 ───────────────────────────────────


def match_experience(question: str, experience: dict, user) -> dict:
    """이 경험이 그 문항에 맞는지 AI 에게 물어본다."""
    mask = privacy.build(user)
    body = mask.mask(json.dumps(experience, ensure_ascii=False, indent=2))

    prompt = ai_prompts.fill(ai_prompts.EXPERIENCE_MATCH_PROMPT,
                             question=question, experience=body)
    res = llm.generate_json(prompt, temperature=0.1, op="match")
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    d = res.data or {}
    try:
        score = int(d.get("score") or 0)
    except (TypeError, ValueError):
        score = 0
    score = min(max(score, 0), 100)

    return {
        "ok": True,
        "score": score,
        "reason": mask.unmask(str(d.get("reason") or "")),
        "strengths": [mask.unmask(str(x)) for x in (d.get("strengths") or [])],
        "weaknesses": [mask.unmask(str(x)) for x in (d.get("weaknesses") or [])],
        # AI 가 말한 값보다 점수를 믿는다. 둘이 어긋나면 기준이 흔들린다.
        "recommended": score >= 75,
    }


# ── 자소서 초안 ────────────────────────────────────────────


def _shorten(text: str, limit: int) -> str:
    """글자 수를 넘으면 문장 단위로 줄인다.

    글자 수로 뚝 자르면 문장이 중간에서 끊긴다. 뒤 문장부터 덜어낸다.
    """
    if len(text) <= limit:
        return text
    sents = ai.split_sentences(text)
    out = ""
    for s in sents:
        if len(out) + len(s) + 1 > limit:
            break
        out = (out + " " + s).strip()
    # 첫 문장부터 한도를 넘으면 어쩔 수 없이 자른다.
    return out or text[:limit]


def generate_essay(question: str, experiences: List[dict], user,
                   limit: int = DEFAULT_LIMIT, job: str = "") -> dict:
    """경험을 근거로 자소서 초안을 만들고, 사실인지 확인한다.

    AI 호출은 초안 1회 + 확인 1회, 문제가 있으면 다시 쓰기 1회까지.
    그 이상은 하지 않는다. 부를 때마다 돈이 나가고, 두 번 고쳐서 안 되면
    세 번째도 안 될 가능성이 크다.
    """
    if not experiences:
        return {"ok": False, "error": "쓸 경험을 골라주세요.",
                "error_type": "no_experience"}

    mask = privacy.build(user)
    body = mask.mask(json.dumps(experiences, ensure_ascii=False, indent=2))

    prompt = ai_prompts.fill(ai_prompts.ESSAY_GENERATION_PROMPT,
                             question=question, experience=body, limit=limit,
                             job=(job or "").strip() or "(고르지 않음)")
    res = llm.generate_json(prompt, temperature=0.3, op="essay",
                            max_tokens=min(4000, limit * 3))
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    d = res.data or {}
    draft = mask.unmask(str(d.get("draft") or "")).strip()
    if not draft:
        return {"ok": False, "error": "초안을 만들지 못했습니다. 다시 시도해주세요.",
                "error_type": "empty_draft"}

    warnings = [str(w) for w in (d.get("warnings") or [])]
    facts = [mask.unmask(str(f)) for f in (d.get("facts_used") or [])]

    # 사실인지 확인한다. 만든 쪽과 확인하는 쪽을 나눈다.
    check = verify_essay(draft, experiences, user)
    if check.get("ok") and not check.get("safe"):
        # 한 번만 다시 써 본다.
        issues = "\n".join(f"- {i['text']}: {i['reason']}"
                           for i in check.get("issues", []))
        retry_prompt = prompt + (
            "\n\n[앞서 만든 초안에서 아래 문제가 발견되었습니다]\n"
            + issues
            + "\n\n이 부분을 경험에 있는 사실만으로 다시 쓰십시오."
        )
        again = llm.generate_json(retry_prompt, temperature=0.2, op="essay_retry",
                                  max_tokens=min(4000, limit * 3))
        if again.ok and (again.data or {}).get("draft"):
            draft = mask.unmask(str(again.data["draft"])).strip()
            check = verify_essay(draft, experiences, user)

    # 글자 수는 AI 말을 믿지 않고 여기서 센다.
    if len(draft) > limit:
        draft = _shorten(draft, limit)

    return {
        "ok": True,
        "draft": draft,
        "character_count": len(draft),
        "character_limit": limit,
        "facts_used": facts,
        "warnings": warnings,
        "verified": check.get("ok", False),
        "safe": check.get("safe", None),
        "issues": check.get("issues", []),
        "model": llm.MODEL,
    }


# ── 지원동기 · 입사 후 목표 질문 ────────────────────────────

MOTIVE_TOPICS = {"apply_motive": "회사에 지원한 이유(지원동기)",
                 "future_goal": "입사 후 이루고 싶은 목표 (단기 1~3년 / 장기 5년 이후)"}
MOTIVE_GROUPS = {"apply_motive": ["지원동기"],
                 "future_goal": ["단기(1~3년)", "장기(5년 이후)"]}
MAX_QUESTIONS = 6


def generate_motive_questions(topic: str, records: List[dict], user, job: str = "") -> dict:
    """학생의 1~2학년 기록에서 출발하는 지원동기·입사 후 목표 질문을 만든다.

    records: [{record_id, entry_date, kind_label, title, content}]
    질문의 근거(basis)는 넘겨준 기록 번호만 남긴다 — AI 가 없는 기록을 가리키면 버린다.
    """
    if topic not in MOTIVE_TOPICS:
        return {"ok": False, "error": "지원동기나 입사 후 목표에서만 쓸 수 있습니다.",
                "error_type": "bad_topic"}

    mask = privacy.build(user)
    lines = []
    for r in records:
        body = (r.get("content") or "").strip()
        if not body:
            continue
        lines.append(f"[기록 {r['record_id']}] {r.get('entry_date', '')} · "
                     f"{r.get('kind_label', '')} · {r.get('title', '')}\n{body}")
    body = mask.mask("\n\n".join(lines)) if lines else "(기록 없음)"

    prompt = ai_prompts.fill(
        ai_prompts.MOTIVE_QUESTIONS_PROMPT,
        topic=MOTIVE_TOPICS[topic],
        instructions=ai_prompts.MOTIVE_INSTRUCTIONS[topic],
        job=(job or "").strip() or "(고르지 않음)",
        records=body)
    res = llm.generate_json(prompt, temperature=0.3, op="motive_questions", max_tokens=2000)
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    known = {int(r["record_id"]): r for r in records}
    groups = MOTIVE_GROUPS[topic]
    out = []
    for q in ((res.data or {}).get("questions") or []):
        if not isinstance(q, dict):
            continue
        text = mask.unmask(str(q.get("question") or "")).strip()
        if not text:
            continue
        group = str(q.get("group") or "").strip()
        if group not in groups:
            group = groups[0] if len(groups) == 1 else (
                groups[1] if ("장기" in group or "5년" in group) else groups[0])
        basis = []
        for b in (q.get("basis") or []):
            if not isinstance(b, dict):
                continue
            try:
                rid = int(b.get("record_id"))
            except (TypeError, ValueError):
                continue
            if rid not in known:
                continue          # 없는 기록을 근거로 댄 것은 버린다
            r = known[rid]
            basis.append({"record_id": rid,
                          "evidence": mask.unmask(str(b.get("evidence") or "")).strip(),
                          "entry_date": r.get("entry_date", ""),
                          "title": r.get("title", ""),
                          "kind_label": r.get("kind_label", "")})
        out.append({"id": len(out) + 1, "group": group, "question": text, "basis": basis})
        if len(out) >= MAX_QUESTIONS:
            break

    if not out:
        return {"ok": False, "error": "질문을 만들지 못했습니다. 다시 시도해주세요.",
                "error_type": "empty"}
    # 단기 → 장기 순으로 보여 준다.
    out.sort(key=lambda q: groups.index(q["group"]))
    for i, q in enumerate(out, 1):
        q["id"] = i
    return {"ok": True, "topic": topic, "questions": out,
            "record_count": len(lines), "model": llm.MODEL}


# ── 사실 확인 ──────────────────────────────────────────────


def verify_essay(draft: str, experiences: List[dict], user) -> dict:
    """초안에 경험에 없는 내용이 들어갔는지 확인한다."""
    if not (draft or "").strip():
        return {"ok": False, "error": "확인할 글이 없습니다.",
                "error_type": "empty"}

    mask = privacy.build(user)
    body = mask.mask(json.dumps(experiences, ensure_ascii=False, indent=2))
    safe_draft = mask.mask(draft)

    prompt = ai_prompts.fill(ai_prompts.ESSAY_VERIFY_PROMPT,
                             experience=body, draft=safe_draft)
    res = llm.generate_json(prompt, temperature=0.0, op="verify")
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    d = res.data or {}
    issues = []
    for it in (d.get("issues") or []):
        if not isinstance(it, dict):
            continue
        issues.append({
            "text": mask.unmask(str(it.get("text") or "")),
            "reason": mask.unmask(str(it.get("reason") or "")),
        })

    return {
        "ok": True,
        # 문제 목록이 비어 있을 때만 안전하다고 본다.
        # AI 가 safe=true 라 해 놓고 문제를 적어 오는 경우가 있다.
        "safe": bool(d.get("safe")) and not issues,
        "issues": issues,
    }


# ── 생기부(세특·행동특성) 초안 ──────────────────────────────
# 자소서 초안과 같은 원칙(만든 쪽과 확인하는 쪽을 나눈다)을 그대로 쓴다.
# 다만 재료가 "학생이 고른 경험"이 아니라 "교사가 부를 수 있는 범위의
# 일지 전부"라서, 어떤 일지를 넘길지는 반드시 main.py 의 권한 검사를
# 통과한 뒤 여기로 와야 한다 — 이 함수 자체는 넘어온 것을 그대로 쓴다.

RECORD_NOTE_LIMIT = 500   # 세특·행동특성 한 항목 표준 글자 수 근사치


def _records_text(records: List[dict]) -> str:
    """일지 여러 건을 하나의 글로 잇는다. 날짜를 함께 적어야 언제 있었던
    일인지 AI 가 알 수 있다."""
    parts = []
    for r in records:
        date = r.get("entry_date") or ""
        body = (r.get("content") or "").strip()
        if body:
            parts.append(f"[{date}]\n{body}")
    return "\n\n".join(parts)


def _build_record_note(template: str, extra: Dict[str, str], records: List[dict],
                       user, limit: int, op: str) -> dict:
    """세특·행동특성 공통 생성 로직. 프롬프트만 다르고 흐름은 같다."""
    if not records:
        return {"ok": False, "error": "바탕이 될 기록이 없습니다.",
                "error_type": "no_experience"}

    mask = privacy.build(user)
    body = mask.mask(_records_text(records))

    prompt = ai_prompts.fill(template, records=body, limit=limit, **extra)
    res = llm.generate_json(prompt, temperature=0.3, op=op,
                            max_tokens=min(3000, limit * 3))
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    d = res.data or {}
    draft = mask.unmask(str(d.get("draft") or "")).strip()
    if not draft:
        return {"ok": False, "error": "초안을 만들지 못했습니다. 다시 시도해주세요.",
                "error_type": "empty_draft"}

    warnings = [str(w) for w in (d.get("warnings") or [])]
    facts = [mask.unmask(str(f)) for f in (d.get("facts_used") or [])]

    # 사실인지 확인한다. verify_essay 는 재료가 어떤 목적이든 형식만 맞으면
    # 그대로 쓸 수 있게 만들어져 있다.
    check = verify_essay(draft, records, user)
    if check.get("ok") and not check.get("safe"):
        issues = "\n".join(f"- {i['text']}: {i['reason']}"
                           for i in check.get("issues", []))
        retry_prompt = prompt + (
            "\n\n[앞서 만든 초안에서 아래 문제가 발견되었습니다]\n"
            + issues + "\n\n이 부분을 기록에 있는 사실만으로 다시 쓰십시오."
        )
        again = llm.generate_json(retry_prompt, temperature=0.2, op=f"{op}_retry",
                                  max_tokens=min(3000, limit * 3))
        if again.ok and (again.data or {}).get("draft"):
            draft = mask.unmask(str(again.data["draft"])).strip()
            check = verify_essay(draft, records, user)

    if len(draft) > limit:
        draft = _shorten(draft, limit)

    return {
        "ok": True,
        "draft": draft,
        "character_count": len(draft),
        "character_limit": limit,
        "facts_used": facts,
        "warnings": warnings,
        "verified": check.get("ok", False),
        "safe": check.get("safe", None),
        "issues": check.get("issues", []),
        "model": llm.MODEL,
    }


def build_subject_note(records: List[dict], subject_name: str, user,
                       limit: int = RECORD_NOTE_LIMIT) -> dict:
    """과목별 수업일지만 모아 세특 초안을 만든다.

    records 에는 반드시 그 과목의 수업일지만 담겨 있어야 한다 — 다른
    과목이나 학교생활일지를 걸러내는 일은 main.py 가 DB 단계에서 한다.
    """
    return _build_record_note(ai_prompts.SUBJECT_NOTE_PROMPT,
                              {"subject": subject_name}, records, user, limit,
                              "subject_note")


def build_behavior_note(records: List[dict], user,
                        limit: int = RECORD_NOTE_LIMIT) -> dict:
    """담임 학급 학생의 학교생활일지만 모아 행동특성 초안을 만든다."""
    return _build_record_note(ai_prompts.BEHAVIOR_NOTE_PROMPT, {}, records, user,
                              limit, "behavior_note")
