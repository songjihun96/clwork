"""AI 연구 코치 — 관심 키워드에서 연구 주제를 좁혀 가는 대화, 주제 추천, 주제 검토.

`ai_service.py`와 같은 흐름(개인정보 가리기 → 지시문 채우기 → 부르기 →
되돌리기)을 그대로 따른다. 자소서·생기부와는 다른 프롬프트 세트를 쓰므로
파일을 나눴다 — ai_service.py는 이미 자소서·생기부 전용으로 커져 있어,
여기 섞으면 어떤 함수가 어떤 기능용인지 헷갈린다.
"""

import json
from typing import Dict, List

from . import ai_prompts, llm, privacy


def _history_text(turns: List[dict]) -> str:
    """대화 턴들을 하나의 글로 잇는다."""
    parts = []
    for t in turns:
        speaker = "학생" if t.get("role") == "student" else "코치"
        body = (t.get("content") or "").strip()
        if body:
            parts.append(f"[{speaker}] {body}")
    return "\n".join(parts)


def run_dialogue(interest_keyword: str, turns: List[dict], message: str, user) -> dict:
    """대화 한 턴을 진행한다. AI의 다음 질문과 준비완료 여부를 돌려준다."""
    mask = privacy.build(user)
    history = mask.mask(_history_text(turns))
    safe_message = mask.mask(message)

    leaks = privacy.find_leaks(safe_message)
    if leaks:
        return {"ok": False,
                "error": "메시지에 연락처나 주민등록번호로 보이는 내용이 있어 보내지 않았습니다. 지우고 다시 시도해주세요.",
                "error_type": "leak"}

    prompt = ai_prompts.fill(ai_prompts.RESEARCH_DIALOGUE_USER,
                             interest_keyword=interest_keyword, history=history,
                             message=safe_message)
    res = llm.generate_json(prompt, temperature=0.4, op="research_dialogue",
                            system=ai_prompts.RESEARCH_DIALOGUE_SYSTEM)
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    d = res.data or {}
    question = mask.unmask(str(d.get("question") or "")).strip()
    if not question:
        return {"ok": False, "error": "다음 질문을 만들지 못했습니다. 다시 시도해주세요.",
                "error_type": "empty"}

    options = [mask.unmask(str(o)).strip() for o in (d.get("options") or [])]
    options = [o for o in options if o][:4]

    return {
        "ok": True,
        "question": question,
        "options": options,
        "ready_for_topics": bool(d.get("ready_for_topics")),
        "model": llm.MODEL,
    }


def generate_topics(interest_keyword: str, turns: List[dict], user,
                    difficulty: str = "easy") -> dict:
    """대화 내용을 바탕으로 연구 주제 후보 4~5개를 만든다."""
    mask = privacy.build(user)
    history = mask.mask(_history_text(turns))

    prompt = ai_prompts.fill(ai_prompts.RESEARCH_TOPICS_PROMPT,
                             interest_keyword=interest_keyword, history=history,
                             difficulty_level=difficulty or "easy")
    res = llm.generate_json(prompt, temperature=0.5, op="research_topics", max_tokens=3000)
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    topics = []
    for t in (res.data or {}).get("topics") or []:
        if not isinstance(t, dict):
            continue
        title = mask.unmask(str(t.get("title") or "")).strip()
        if not title:
            continue
        topics.append({
            "title": title,
            "research_question": mask.unmask(str(t.get("research_question") or "")),
            "research_type": str(t.get("research_type") or ""),
            "feasibility_note": mask.unmask(str(t.get("feasibility_note") or "")),
            "expected_duration": str(t.get("expected_duration") or ""),
            "required_materials": mask.unmask(str(t.get("required_materials") or "")),
            "method_summary": mask.unmask(str(t.get("method_summary") or "")),
            "difficulty": str(t.get("difficulty") or ""),
            "extensibility": mask.unmask(str(t.get("extensibility") or "")),
        })
    if not topics:
        return {"ok": False, "error": "주제를 만들지 못했습니다. 다시 시도해주세요.",
                "error_type": "empty"}

    return {"ok": True, "topics": topics, "model": llm.MODEL}


def review_topic(interest_keyword: str, title: str, research_question: str, user) -> dict:
    """학생이 수정한 주제의 수행 가능성을 검토한다. 주제를 대신 정하지 않는다."""
    mask = privacy.build(user)
    safe_title = mask.mask(title)
    safe_question = mask.mask(research_question)

    prompt = ai_prompts.fill(ai_prompts.RESEARCH_TOPIC_REVIEW_PROMPT,
                             interest_keyword=interest_keyword, title=safe_title,
                             research_question=safe_question)
    res = llm.generate_json(prompt, temperature=0.2, op="research_topic_review")
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    d = res.data or {}
    return {
        "ok": True,
        "feasible": bool(d.get("feasible")),
        "comment": mask.unmask(str(d.get("comment") or "")),
        "concerns": [mask.unmask(str(c)) for c in (d.get("concerns") or [])],
    }


def generate_plan(title: str, research_question: str, research_type: str, user,
                  difficulty: str = "easy") -> dict:
    """확정된 주제로 연구 계획 초안(가설·변수·대상·방법·한계)을 만든다."""
    mask = privacy.build(user)
    prompt = ai_prompts.fill(ai_prompts.RESEARCH_PLAN_PROMPT,
                             title=mask.mask(title), research_question=mask.mask(research_question),
                             research_type=research_type or "미정",
                             difficulty_level=difficulty or "easy")
    res = llm.generate_json(prompt, temperature=0.3, op="research_plan", max_tokens=2000,
                            model=llm.FAST_MODEL)
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    d = res.data or {}
    return {
        "ok": True,
        "hypothesis": mask.unmask(str(d.get("hypothesis") or "")),
        "variables": mask.unmask(str(d.get("variables") or "")),
        "target_sample": mask.unmask(str(d.get("target_sample") or "")),
        "method_detail": mask.unmask(str(d.get("method_detail") or "")),
        "expected_limitations": mask.unmask(str(d.get("expected_limitations") or "")),
    }


def structure_plan(research, user) -> dict:
    """학생이 쉬운 말로 쓴 계획을 전문 연구 구조로 번역한다.

    내용을 새로 짓지 않고 번역만 한다 — 근거가 없는 항목은 unclear에 담겨 온다.
    이 결과는 학생 화면에 노출하지 않는다.
    """
    mask = privacy.build(user)
    prompt = ai_prompts.fill(
        ai_prompts.RESEARCH_STRUCTURE_PROMPT,
        research_question=mask.mask(research.research_question or ""),
        research_type=research.research_type or "미정",
        hypothesis=mask.mask(research.hypothesis or ""),
        variables=mask.mask(research.variables or ""),
        target_sample=mask.mask(research.target_sample or ""),
        method_detail=mask.mask(research.method_detail or ""))
    res = llm.generate_json(prompt, temperature=0.2, op="research_structure", max_tokens=1500,
                            model=llm.FAST_MODEL)
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    d = res.data or {}
    return {
        "ok": True,
        "research_question": mask.unmask(str(d.get("research_question") or "")),
        "hypothesis_formal": mask.unmask(str(d.get("hypothesis_formal") or "")),
        "independent_variable": mask.unmask(str(d.get("independent_variable") or "")),
        "dependent_variable": mask.unmask(str(d.get("dependent_variable") or "")),
        "control_variables": [mask.unmask(str(v)) for v in (d.get("control_variables") or [])],
        "comparison_groups": [mask.unmask(str(v)) for v in (d.get("comparison_groups") or [])],
        "measurement": mask.unmask(str(d.get("measurement") or "")),
        "sample": mask.unmask(str(d.get("sample") or "")),
        "repetition": mask.unmask(str(d.get("repetition") or "")),
        "unclear": [str(v) for v in (d.get("unclear") or [])],
    }


def generate_roadmap(title: str, research_question: str, research_type: str,
                     duration_weeks: int, user, difficulty: str = "easy") -> dict:
    """연구 기간을 주차별 로드맵으로 나눈다."""
    mask = privacy.build(user)
    prompt = ai_prompts.fill(ai_prompts.RESEARCH_ROADMAP_PROMPT,
                             title=mask.mask(title), research_question=mask.mask(research_question),
                             research_type=research_type or "미정", duration_weeks=duration_weeks,
                             difficulty_level=difficulty or "easy")
    res = llm.generate_json(prompt, temperature=0.3, op="research_roadmap", max_tokens=4000,
                            model=llm.FAST_MODEL)
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    weeks = []
    for w in (res.data or {}).get("weeks") or []:
        if not isinstance(w, dict):
            continue
        try:
            week_number = int(w.get("week_number") or 0)
        except (TypeError, ValueError):
            continue
        if week_number < 1:
            continue
        weeks.append({
            "week_number": week_number,
            "title": mask.unmask(str(w.get("title") or ""))[:120],
            "goal": mask.unmask(str(w.get("goal") or "")),
            "tasks": [mask.unmask(str(t)) for t in (w.get("tasks") or []) if str(t).strip()],
            "expected_hours": str(w.get("expected_hours") or ""),
            "completion_criteria": mask.unmask(str(w.get("completion_criteria") or "")),
        })
    weeks.sort(key=lambda w: w["week_number"])
    if not weeks:
        return {"ok": False, "error": "로드맵을 만들지 못했습니다. 다시 시도해주세요.",
                "error_type": "empty"}

    return {"ok": True, "weeks": weeks}


def suggest_literature(research_question: str, hypothesis: str, user) -> dict:
    """참고 자료 후보를 제안한다. 전부 미확인 상태로 저장되어야 한다."""
    mask = privacy.build(user)
    prompt = ai_prompts.fill(ai_prompts.RESEARCH_LITERATURE_PROMPT,
                             research_question=mask.mask(research_question),
                             hypothesis=mask.mask(hypothesis))
    res = llm.generate_json(prompt, temperature=0.4, op="research_literature", max_tokens=2500,
                            model=llm.FAST_MODEL)
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    items = []
    for it in (res.data or {}).get("items") or []:
        if not isinstance(it, dict):
            continue
        title = mask.unmask(str(it.get("title") or "")).strip()
        if not title:
            continue
        stance = str(it.get("stance") or "uncertain")
        if stance not in ("support", "oppose", "conditional", "uncertain"):
            stance = "uncertain"
        items.append({
            "title": title[:300],
            "author": mask.unmask(str(it.get("author") or ""))[:200],
            "year": str(it.get("year") or "")[:10],
            "source": mask.unmask(str(it.get("source") or ""))[:200],
            "url": str(it.get("url") or "")[:500],
            "summary": mask.unmask(str(it.get("summary") or "")),
            "relevance": mask.unmask(str(it.get("relevance") or "")),
            "stance": stance,
        })
    if not items:
        return {"ok": False, "error": "제안을 만들지 못했습니다. 다시 시도해주세요.",
                "error_type": "empty"}
    return {"ok": True, "items": items}


def suggest_data_direction(research, literature: str, user) -> dict:
    """아직 데이터를 모으기 전, 무엇을 어떻게 모으면 좋을지 방향을 제안한다."""
    mask = privacy.build(user)
    prompt = ai_prompts.fill(
        ai_prompts.RESEARCH_DATA_DIRECTION_PROMPT,
        research_question=mask.mask(research.research_question),
        hypothesis=mask.mask(research.hypothesis or "(없음)"),
        research_type=research.research_type or "(미정)",
        variables=mask.mask(research.variables or "(없음)"),
        target_sample=mask.mask(research.target_sample or "(없음)"),
        method_detail=mask.mask(research.method_detail or "(없음)"),
        literature=mask.mask(literature or "(없음)"))
    res = llm.generate_json(prompt, temperature=0.4, op="research_data_direction", max_tokens=2200,
                            model=llm.FAST_MODEL)
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    d = res.data or {}
    return {
        "ok": True,
        "direction": mask.unmask(str(d.get("direction") or "")),
        "what_to_collect": mask.unmask(str(d.get("what_to_collect") or "")),
        "how_to_collect": mask.unmask(str(d.get("how_to_collect") or "")),
        "suggested_analysis": mask.unmask(str(d.get("suggested_analysis") or "")),
    }


def generate_task_guide(task_title: str, step_goal: str, research, user) -> dict:
    """로드맵 할 일 하나를 실제로 어떻게 하면 되는지 단계별로 안내한다."""
    mask = privacy.build(user)
    prompt = ai_prompts.fill(
        ai_prompts.RESEARCH_TASK_GUIDE_PROMPT,
        step_goal=mask.mask(step_goal or ""), task_title=mask.mask(task_title),
        research_question=mask.mask(research.research_question or ""),
        research_type=research.research_type or "(미정)")
    res = llm.generate_json(prompt, temperature=0.4, op="research_task_guide", max_tokens=1500,
                            model=llm.FAST_MODEL)
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    d = res.data or {}
    steps = [mask.unmask(str(s)).strip() for s in (d.get("steps") or [])]
    steps = [s for s in steps if s]
    return {"ok": True, "steps": steps, "tips": mask.unmask(str(d.get("tips") or ""))}


def interpret_analysis(research_question: str, hypothesis: str, stats: dict, user) -> dict:
    """서버가 이미 계산한 통계를 해석하고 다음 분석 방법을 제안한다."""
    mask = privacy.build(user)
    prompt = ai_prompts.fill(ai_prompts.RESEARCH_ANALYSIS_PROMPT,
                             research_question=mask.mask(research_question),
                             hypothesis=mask.mask(hypothesis),
                             stats=json.dumps(stats, ensure_ascii=False))
    res = llm.generate_json(prompt, temperature=0.3, op="research_analysis", max_tokens=1500,
                            model=llm.FAST_MODEL)
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    d = res.data or {}
    return {
        "ok": True,
        "interpretation": mask.unmask(str(d.get("interpretation") or "")),
        "method_suggestion": mask.unmask(str(d.get("method_suggestion") or "")),
    }


def _structure_text(research) -> str:
    """저장된 연구 구조(structure_json)를 읽기 쉬운 한 덩어리 글로 만든다."""
    try:
        s = json.loads(research.structure_json) if research.structure_json else {}
    except (ValueError, TypeError):
        s = {}
    if not s:
        return "(아직 만들어지지 않음)"
    lines = []
    if s.get("independent_variable"):
        lines.append(f"독립변수: {s['independent_variable']}")
    if s.get("dependent_variable"):
        lines.append(f"종속변수: {s['dependent_variable']}")
    if s.get("control_variables"):
        lines.append(f"통제변수: {', '.join(s['control_variables'])}")
    if s.get("comparison_groups"):
        lines.append(f"비교 집단: {', '.join(s['comparison_groups'])}")
    if s.get("sample"):
        lines.append(f"표본: {s['sample']}")
    if s.get("repetition"):
        lines.append(f"반복·재검증: {s['repetition']}")
    return "\n".join(lines) if lines else "(아직 만들어지지 않음)"


def review_research(research, summary: str, user) -> dict:
    """연구의 논리적 취약점을 검토한다. 학생을 평가하지 않는다."""
    mask = privacy.build(user)
    prompt = ai_prompts.fill(ai_prompts.RESEARCH_REVIEW_PROMPT,
                             research_question=mask.mask(research.research_question),
                             hypothesis=mask.mask(research.hypothesis),
                             method_detail=mask.mask(research.method_detail),
                             target_sample=mask.mask(research.target_sample),
                             structure=mask.mask(_structure_text(research)),
                             summary=mask.mask(summary))
    res = llm.generate_json(prompt, temperature=0.4, op="research_review", max_tokens=2000)
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    findings = []
    for f in (res.data or {}).get("findings") or []:
        if not isinstance(f, dict):
            continue
        concern = mask.unmask(str(f.get("concern") or "")).strip()
        if not concern:
            continue
        findings.append({"area": mask.unmask(str(f.get("area") or "")), "concern": concern})
    return {"ok": True, "findings": findings}


def suggest_followup(research_question: str, expected_limitations: str, user) -> dict:
    """후속 연구 방향을 제안한다."""
    mask = privacy.build(user)
    prompt = ai_prompts.fill(ai_prompts.RESEARCH_FOLLOWUP_PROMPT,
                             research_question=mask.mask(research_question),
                             expected_limitations=mask.mask(expected_limitations))
    res = llm.generate_json(prompt, temperature=0.5, op="research_followup", max_tokens=1200,
                            model=llm.FAST_MODEL)
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    ideas = [mask.unmask(str(i)) for i in (res.data or {}).get("ideas") or [] if str(i).strip()]
    if not ideas:
        return {"ok": False, "error": "제안을 만들지 못했습니다. 다시 시도해주세요.",
                "error_type": "empty"}
    return {"ok": True, "ideas": ideas}


def draft_report(research_question: str, current_stage: str, completed_tasks: List[str],
                 blockers: str, user) -> dict:
    """완료한 할 일(실제 기록)만 근거로 리포트 초안을 만든다."""
    mask = privacy.build(user)
    tasks_text = "\n".join(f"- {t}" for t in completed_tasks) or "(이번 기간에 완료 표시한 항목 없음)"
    prompt = ai_prompts.fill(ai_prompts.RESEARCH_REPORT_PROMPT,
                             research_question=mask.mask(research_question),
                             current_stage=current_stage,
                             completed_tasks=mask.mask(tasks_text),
                             blockers=mask.mask(blockers or "(없음)"))
    res = llm.generate_json(prompt, temperature=0.3, op="research_report", max_tokens=1500,
                            model=llm.FAST_MODEL)
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    d = res.data or {}
    return {
        "ok": True,
        "summary": mask.unmask(str(d.get("summary") or "")),
        "ai_feedback": mask.unmask(str(d.get("ai_feedback") or "")),
        "next_steps": mask.unmask(str(d.get("next_steps") or "")),
    }


PAPER_KEYS = ["introduction", "literature_review", "method", "results",
             "discussion", "limitations", "conclusion"]
PORTFOLIO_KEYS = ["why", "question", "hypothesis", "method", "data",
                 "result", "discussion", "limitation", "next"]


def draft_paper(research_summary: str, literature: str, analysis: str, review: str,
                limitations: str, followup: str, user) -> dict:
    """확인된 참고자료·실제 분석 결과만 근거로 논문 초안을 만든다."""
    mask = privacy.build(user)
    prompt = ai_prompts.fill(
        ai_prompts.RESEARCH_PAPER_PROMPT,
        research_summary=mask.mask(research_summary), literature=mask.mask(literature or "(없음)"),
        analysis=mask.mask(analysis or "(없음)"), review=mask.mask(review or "(없음)"),
        limitations=mask.mask(limitations or "(없음)"), followup=mask.mask(followup or "(없음)"))
    res = llm.generate_json(prompt, temperature=0.3, op="research_paper", max_tokens=8000)
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    d = res.data or {}
    sections = {k: mask.unmask(str(d.get(k) or "")) for k in PAPER_KEYS}
    return {
        "ok": True,
        "title": mask.unmask(str(d.get("title") or "")),
        "abstract": mask.unmask(str(d.get("abstract") or "")),
        "sections": sections,
    }


def draft_portfolio(research_summary: str, analysis: str, user) -> dict:
    """실제 연구 기록만 근거로 포트폴리오 초안을 만든다."""
    mask = privacy.build(user)
    prompt = ai_prompts.fill(ai_prompts.RESEARCH_PORTFOLIO_PROMPT,
                             research_summary=mask.mask(research_summary),
                             analysis=mask.mask(analysis or "(없음)"))
    res = llm.generate_json(prompt, temperature=0.4, op="research_portfolio", max_tokens=3000)
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    d = res.data or {}
    sections = {k: mask.unmask(str(d.get(k) or "")) for k in PORTFOLIO_KEYS}
    return {
        "ok": True,
        "title": mask.unmask(str(d.get("title") or "")),
        "sections": sections,
    }


def suggest_team_roles(research_question: str, research_type: str, team_size: int, user) -> dict:
    """팀 연구에 필요한 역할 후보를 제안한다. 누구에게 배정할지는 정하지
    않는다 — 팀원들이 협의해서 고른다(§11·§12)."""
    mask = privacy.build(user)
    prompt = ai_prompts.fill(ai_prompts.RESEARCH_TEAM_ROLES_PROMPT,
                             research_question=mask.mask(research_question),
                             research_type=research_type or "미정",
                             team_size=max(1, team_size))
    res = llm.generate_json(prompt, temperature=0.4, op="research_team_roles", max_tokens=1200,
                            model=llm.FAST_MODEL)
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    roles = []
    for r in (res.data or {}).get("roles") or []:
        if not isinstance(r, dict):
            continue
        name = mask.unmask(str(r.get("name") or "")).strip()
        if not name:
            continue
        roles.append({"name": name, "description": mask.unmask(str(r.get("description") or ""))})
    if not roles:
        return {"ok": False, "error": "역할 후보를 만들지 못했습니다. 다시 시도해주세요.",
                "error_type": "empty"}
    return {"ok": True, "roles": roles}


def synthesize_board(research_question: str, posts: List[dict], users: list, user) -> dict:
    """팀 게시판 글 전체를 검토해 각 글에 제안을 단다. 승인/반려를
    확정하지 않는다 — 최종 결정은 학생이 한다(§14).

    posts 의 글쓴이가 여러 명이라 build(user) 하나로는 부족하다(다른
    팀원 이름은 호칭 없이 쓰이면 못 가린다) — build_many 로 팀원 전체를
    먼저 등록한다."""
    mask = privacy.build_many(users)
    lines = [f"[post_id={p['id']}] {p.get('title') or '(제목 없음)'}\n{p['content']}" for p in posts]
    posts_text = mask.mask("\n\n".join(lines))
    prompt = ai_prompts.fill(ai_prompts.RESEARCH_BOARD_SYNTHESIS_PROMPT,
                             research_question=mask.mask(research_question), posts=posts_text)
    res = llm.generate_json(prompt, temperature=0.3, op="research_board_synthesis", max_tokens=3000,
                            model=llm.FAST_MODEL)
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    items = []
    for it in (res.data or {}).get("items") or []:
        if not isinstance(it, dict):
            continue
        try:
            post_id = int(it.get("post_id"))
        except (TypeError, ValueError):
            continue
        suggestion = str(it.get("suggestion") or "")
        if suggestion not in ("keep", "revise", "duplicate", "weak", "exclude"):
            continue
        items.append({"post_id": post_id, "suggestion": suggestion,
                      "note": mask.unmask(str(it.get("note") or ""))})
    return {"ok": True, "items": items}


def suggest_question_tags(research_title: str, question_body: str, user) -> dict:
    """외부 교사 질문에 분야 키워드를 추천한다. 학생은 직접 고르지 않는다(§16)."""
    mask = privacy.build(user)
    prompt = ai_prompts.fill(ai_prompts.RESEARCH_QUESTION_TAGS_PROMPT,
                             research_title=mask.mask(research_title),
                             question_body=mask.mask(question_body))
    res = llm.generate_json(prompt, temperature=0.3, op="research_question_tags", max_tokens=300,
                            model=llm.FAST_MODEL)
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    tags = []
    for t in (res.data or {}).get("tags") or []:
        tag = mask.unmask(str(t or "")).strip()
        if tag and tag not in tags:
            tags.append(tag)
    return {"ok": True, "tags": tags[:4]}


def reflect_answer(question_body: str, answer_body: str, user) -> dict:
    """교사 답변을 연구에 어떻게 반영하면 좋을지 정리한다. AI는 정리만
    하고 확정하지 않는다 — 학생이 승인해야 논문에 쓰인다(§19)."""
    mask = privacy.build(user)
    prompt = ai_prompts.fill(ai_prompts.RESEARCH_REFLECT_ANSWER_PROMPT,
                             question_body=mask.mask(question_body),
                             answer_body=mask.mask(answer_body))
    res = llm.generate_json(prompt, temperature=0.3, op="research_reflect_answer", max_tokens=800,
                            model=llm.FAST_MODEL)
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    d = res.data or {}
    stage = str(d.get("suggested_stage") or "")
    if stage not in ("literature", "method", "analysis", "discussion"):
        stage = ""
    note = mask.unmask(str(d.get("note") or "")).strip()
    if not note:
        return {"ok": False, "error": "반영할 내용을 정리하지 못했습니다. 다시 시도해주세요.",
                "error_type": "empty"}
    return {"ok": True, "suggested_stage": stage, "note": note}
