"""연구 논문·포트폴리오를 PDF로 내보낸다.

자소서 PDF(resume_export.py)는 "칸이 정해진 양식"이라 표 형태로 그리지만,
논문·포트폴리오는 길게 이어지는 글이라 표가 아니라 그냥 흘러가는 문서로
그린다. 한글 글꼴을 찾는 부분은 서버 사정이 같으므로 resume_export.py의
find_font()를 그대로 쓴다 — 새로 찾을 이유가 없다.

개인정보: 학생 이름·학교명 같은 걸 자동으로 표지에 넣지 않는다(사용자
지시서 40번 "학생이 공개하고 싶지 않은 개인정보가 자동으로 들어가지
않도록"). 연구 자체에 대한 정보(제목·기간·질문)만 넣는다.
"""

import io
from typing import List, Optional, Tuple
from xml.sax.saxutils import escape, quoteattr

from .fonts import clean, find_font


def build_research_pdf(kind_label: str, title: str, subtitle: str,
                       meta_lines: List[Tuple[str, str]],
                       sections: List[Tuple[str, str]],
                       references: Optional[List[dict]] = None) -> bytes:
    """kind_label: "연구 논문" 또는 "연구 포트폴리오".
    meta_lines: 표지에 넣을 (라벨, 값) 목록(연구 정보만, 개인정보 제외).
    sections: 본문 (제목, 내용) 목록, 순서대로 그린다.
    references: 참고문헌 목록(선택). {"citation": "...", "url": "..."} 형태로
    주면 맨 끝에 "참고문헌" 절로 붙이고, url이 있는 항목은 PDF 안에서도
    실제로 클릭할 수 있는 링크로 만든다.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    font_path = find_font()
    if not font_path:
        raise RuntimeError(
            "서버에 한글 글꼴이 없어 PDF를 만들 수 없습니다. "
            "(서버에 fonts-nanum 설치가 필요합니다)"
        )
    if "KR" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("KR", font_path))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=22 * mm, rightMargin=22 * mm,
        topMargin=25 * mm, bottomMargin=20 * mm,
        title=title or kind_label,
    )

    st_kind = ParagraphStyle("kind", fontName="KR", fontSize=11, leading=16,
                             alignment=1, textColor="#6b6b6b", spaceAfter=10)
    st_cover_title = ParagraphStyle("ct", fontName="KR", fontSize=22, leading=30,
                                    alignment=1, spaceAfter=14)
    st_subtitle = ParagraphStyle("st", fontName="KR", fontSize=12.5, leading=19,
                                 alignment=1, textColor="#4a4a4a", spaceAfter=24)
    st_meta = ParagraphStyle("m", fontName="KR", fontSize=10.5, leading=17,
                             alignment=1, textColor="#6b6b6b")
    st_heading = ParagraphStyle("h", fontName="KR", fontSize=14, leading=20,
                                spaceBefore=18, spaceAfter=8)
    st_body = ParagraphStyle("b", fontName="KR", fontSize=11, leading=18,
                             spaceAfter=6)

    def para(text, style):
        return Paragraph(escape(text).replace("\n", "<br/>"), style)

    # 표지
    story = [Spacer(1, 40 * mm), para(kind_label, st_kind),
            para(title or "(제목 없음)", st_cover_title)]
    if subtitle:
        story.append(para(subtitle, st_subtitle))
    for label, value in meta_lines:
        if value:
            story.append(para(f"{label}  {value}", st_meta))
    story.append(PageBreak())

    # 본문
    for heading, body in sections:
        text = clean(body)
        if not text:
            continue
        story.append(para(heading, st_heading))
        story.append(para(text, st_body))

    # 참고문헌 — url이 있는 항목만 실제로 클릭되는 링크로 감싼다.
    # citation·url 모두 학생이 입력했거나 학생이 직접 확인한 값이라
    # escape()로 안전하게 감싼 뒤 <a>/<br/> 구조만 직접 붙인다.
    if references:
        lines = []
        for ref in references:
            text = escape(str(ref.get("citation") or ""))
            if not text:
                continue
            url = str(ref.get("url") or "").strip()
            if url:
                lines.append(f'<a href={quoteattr(url)} color="#3157d5"><u>{text}</u></a>')
            else:
                lines.append(text)
        if lines:
            story.append(Paragraph("참고문헌", st_heading))
            story.append(Paragraph("<br/>".join(lines), st_body))

    doc.build(story)
    return buf.getvalue()
