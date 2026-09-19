"""AI로 포트폴리오를 돕는 자리.

`ai_service.py`와 같은 원칙(개인정보 가리기 → 지시문 채우기 → 부르기 →
되돌리기)을 그대로 따르되, 재료 선택 방식이 다르다. 자소서는 "학생이
고른 경험"을 그대로 쓰지만, 포트폴리오 테마 추천은 AI를 부르기 *전에*
`portfolio.py`의 키워드 점수로 후보를 이미 추려 둔 뒤 그 후보에 대한
설명 문구만 AI에게 맡긴다 — 전체 기록을 매번 AI에 보내지 않기 위해서다.
"""

import base64
import json
from typing import Dict, List

from . import ai_prompts, llm, portfolio, privacy

DESCRIPTION_LIMIT = 200
BLOCK_TEXT_LIMIT = 300

ACTION_DESC = {
    "TEXT_EDIT": "문장을 자연스럽게 다듬으십시오. 뜻은 바꾸지 마십시오.",
    "TEXT_SHORTEN": "같은 뜻을 유지하며 더 짧게 줄이십시오.",
    "TEXT_EXPAND": "원문에 있는 내용을 조금 더 구체적으로 풀어 쓰십시오. 없는 내용을 더하지 마십시오.",
    "TEXT_PROOFREAD": "맞춤법과 띄어쓰기만 고치십시오. 문장 구조나 뜻은 바꾸지 마십시오.",
    "TITLE_SUGGEST": "이 글에 어울리는 짧은 제목을 하나 만드십시오.",
}


# ── 테마 추천 ──────────────────────────────────────────────

def recommend_themes(entries: List[dict], dept_field: str, user, top_n: int = 5) -> dict:
    """1차: portfolio.score_themes()로 후보를 추린다. 후보가 없으면 AI를
    부르지 않고 바로 빈 결과를 돌려준다 — 쓸 재료가 없는데 AI에게 만들어
    내라고 하지 않는다."""
    candidates = portfolio.score_themes(entries, dept_field)[:top_n]
    if not candidates:
        return {"ok": True, "recommendations": []}

    mask = privacy.build(user)
    cand_text = "\n".join(
        f"- {c['theme_type']} ({c['title']}): 관련 기록 {c['source_count']}개"
        for c in candidates
    )
    prompt = ai_prompts.fill(ai_prompts.THEME_RECOMMEND_PROMPT,
                             candidates=mask.mask(cand_text))
    res = llm.generate_json(prompt, temperature=0.4, op="theme_recommend")

    reasons = {}
    if res.ok:
        for r in ((res.data or {}).get("recommendations") or []):
            if isinstance(r, dict) and r.get("theme_type"):
                reasons[str(r["theme_type"])] = mask.unmask(str(r.get("reason") or ""))

    out = []
    for c in candidates:
        out.append({
            "theme_type": c["theme_type"],
            "title": c["title"],
            "reason": reasons.get(c["theme_type"])
                      or f"관련 기록이 {c['source_count']}개 확인되었습니다.",
            "source_count": c["source_count"],
            "journal_ids": [m["journal_id"] for m in c["matches"]],
        })
    return {"ok": True, "recommendations": out}


# ── 포트폴리오 생성 ────────────────────────────────────────

def generate_portfolio(theme_type: str, purpose: str, records: List[dict], user) -> dict:
    """관련 기록만으로 제목·설명·페이지 구성을 만든다.

    records: [{journal_id, entry_date, text}, ...] — 이미 이 테마에 해당하는
    것만 골라져 있어야 한다(main.py가 걸러서 넘긴다).
    """
    if not records:
        return {"ok": False, "error": "바탕이 될 기록이 없습니다.", "error_type": "no_records"}

    mask = privacy.build(user)
    body = "\n\n".join(f"[{r.get('entry_date','')}] (id={r['journal_id']})\n{r.get('text','')}"
                       for r in records)

    prompt = ai_prompts.fill(
        ai_prompts.PORTFOLIO_GENERATION_PROMPT,
        theme_label=portfolio.THEME_LABEL.get(theme_type, theme_type),
        purpose_label=portfolio.PURPOSE_LABEL.get(purpose, purpose),
        records=mask.mask(body),
    )
    res = llm.generate_json(prompt, temperature=0.4, op="portfolio_generate", max_tokens=3000)
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    d = res.data or {}
    title = mask.unmask(str(d.get("title") or "")).strip()[:120]
    description = mask.unmask(str(d.get("description") or "")).strip()[:DESCRIPTION_LIMIT]
    valid_ids = {r["journal_id"] for r in records}

    pages = []
    for p in (d.get("pages") or [])[:8]:
        if not isinstance(p, dict):
            continue
        blocks = []
        for b in (p.get("blocks") or [])[:6]:
            if not isinstance(b, dict):
                continue
            btype = str(b.get("type") or "text")
            if btype not in ("heading", "text"):
                continue
            text = mask.unmask(str(b.get("content") or "")).strip()
            if not text:
                continue
            if btype == "text":
                text = text[:BLOCK_TEXT_LIMIT]
            blocks.append({"type": btype, "content": text})
        if not blocks:
            continue
        source_ids = [int(i) for i in (p.get("source_journal_ids") or [])
                     if isinstance(i, (int, str)) and str(i).isdigit() and int(i) in valid_ids]
        pages.append({"title": mask.unmask(str(p.get("title") or "")).strip()[:120] or "페이지",
                      "blocks": blocks, "source_journal_ids": source_ids})

    if not pages:
        return {"ok": False, "error": "포트폴리오 구성을 만들지 못했습니다. 다시 시도해주세요.",
                "error_type": "empty"}

    return {"ok": True, "title": title or portfolio.THEME_LABEL.get(theme_type, "포트폴리오"),
           "description": description, "pages": pages, "model": llm.MODEL}


# ── 경험 추출 ──────────────────────────────────────────────

def extract_experience(journal_text: str, user) -> dict:
    if len(journal_text.strip()) < 20:
        return {"ok": False, "error": "글이 너무 짧아 경험을 정리할 수 없습니다.",
                "error_type": "too_short"}

    mask = privacy.build(user)
    safe = mask.mask(journal_text)
    leaks = privacy.find_leaks(safe)
    if leaks:
        return {"ok": False, "error": "글에 개인정보로 보이는 내용이 있어 처리하지 않았습니다.",
                "error_type": "leak"}

    prompt = ai_prompts.fill(ai_prompts.EXPERIENCE_EXTRACTION_PROMPT, content=safe)
    res = llm.generate_json(prompt, temperature=0.2, op="experience_extract")
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    d = res.data or {}
    out = {k: mask.unmask(str(d.get(k) or "")) for k in
          ("title", "type", "situation", "problem", "action", "result", "lesson")}
    if not out["situation"] and not out["action"]:
        return {"ok": False, "error": "경험을 정리하지 못했습니다. 다른 기록으로 시도해주세요.",
                "error_type": "empty"}
    return {"ok": True, **out, "model": llm.MODEL}


# ── 글 첨삭(제한된 Action) ──────────────────────────────────

def proofread_text(text: str, action: str, user) -> dict:
    if action not in ACTION_DESC:
        return {"ok": False, "error": "지원하지 않는 동작입니다.", "error_type": "bad_action"}
    if not (text or "").strip():
        return {"ok": False, "error": "다듬을 글이 없습니다.", "error_type": "empty"}

    mask = privacy.build(user)
    prompt = ai_prompts.fill(ai_prompts.PORTFOLIO_PROOFREAD_PROMPT,
                             action=action, action_desc=ACTION_DESC[action],
                             text=mask.mask(text))
    res = llm.generate_json(prompt, temperature=0.2, op=f"proofread_{action.lower()}")
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}

    result = mask.unmask(str((res.data or {}).get("result") or "")).strip()
    if not result:
        return {"ok": False, "error": "결과를 만들지 못했습니다.", "error_type": "empty"}
    return {"ok": True, "result": result, "model": llm.MODEL}


# ── 사진 설명 ──────────────────────────────────────────────

def caption_image(image_bytes: bytes) -> dict:
    """사용자가 명시적으로 요청했을 때만 호출된다(main.py가 보장).
    개인정보 마스킹은 사진에는 적용할 수 없으므로, 프롬프트 자체에서
    사진에 보이는 사실만 쓰라고 강하게 못박는다."""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    prompt = ai_prompts.fill(ai_prompts.IMAGE_CAPTION_PROMPT)
    res = llm.generate_json(prompt, temperature=0.3, op="image_caption", image_b64=b64)
    if not res.ok:
        return {"ok": False, "error": res.error, "error_type": res.error_type}
    caption = str((res.data or {}).get("caption") or "").strip()
    if not caption:
        return {"ok": False, "error": "사진 설명을 만들지 못했습니다.", "error_type": "empty"}
    return {"ok": True, "caption": caption[:200], "model": llm.MODEL}
