# -*- coding: utf-8 -*-
"""매뉴얼 PDF 공통 스타일. 6개 매뉴얼이 전부 이 모듈로 같은 모양을 낸다."""
import os
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table,
    TableStyle, KeepTogether, NextPageTemplate, PageBreak, HRFlowable,
)
from reportlab.lib import colors

FONT_DIR = "C:/Windows/Fonts"
pdfmetrics.registerFont(TTFont("Malgun", os.path.join(FONT_DIR, "malgun.ttf")))
pdfmetrics.registerFont(TTFont("Malgun-Bold", os.path.join(FONT_DIR, "malgunbd.ttf")))

INK = colors.HexColor("#1c2530")
STEEL = colors.HexColor("#54606e")
STEEL_LIGHT = colors.HexColor("#8993a1")
LINE = colors.HexColor("#dfe4ea")
ACCENT = colors.HexColor("#2f6fed")
PAPER = colors.HexColor("#f4f6f9")
WARN_BG = colors.HexColor("#fff6ea")
WARN_LINE = colors.HexColor("#e8c483")

PAGE_W, PAGE_H = A4
MARGIN = 22 * mm

styles = {
    "cover_title": ParagraphStyle("cover_title", fontName="Malgun-Bold", fontSize=25,
        leading=32, textColor=INK, alignment=TA_LEFT),
    "cover_sub": ParagraphStyle("cover_sub", fontName="Malgun", fontSize=13.5,
        leading=20, textColor=STEEL, alignment=TA_LEFT, spaceBefore=8),
    "cover_meta": ParagraphStyle("cover_meta", fontName="Malgun", fontSize=10.5,
        leading=17, textColor=STEEL_LIGHT, alignment=TA_LEFT),
    "h1": ParagraphStyle("h1", fontName="Malgun-Bold", fontSize=15.5, leading=21,
        textColor=INK, spaceBefore=18, spaceAfter=8),
    "h2": ParagraphStyle("h2", fontName="Malgun-Bold", fontSize=12, leading=17,
        textColor=INK, spaceBefore=12, spaceAfter=5),
    "body": ParagraphStyle("body", fontName="Malgun", fontSize=10.3, leading=16.5,
        textColor=INK, spaceAfter=6),
    "bullet": ParagraphStyle("bullet", fontName="Malgun", fontSize=10.3, leading=16.5,
        textColor=INK, leftIndent=13, bulletIndent=0, spaceAfter=4),
    "callout_title": ParagraphStyle("callout_title", fontName="Malgun-Bold", fontSize=10.3,
        leading=15, textColor=colors.HexColor("#8a5a12")),
    "callout_body": ParagraphStyle("callout_body", fontName="Malgun", fontSize=10, leading=15.5,
        textColor=colors.HexColor("#5c4419")),
    "toc_h": ParagraphStyle("toc_h", fontName="Malgun-Bold", fontSize=13, leading=20,
        textColor=INK, spaceAfter=10),
    "toc_item": ParagraphStyle("toc_item", fontName="Malgun", fontSize=11, leading=22,
        textColor=INK),
    "footer": ParagraphStyle("footer", fontName="Malgun", fontSize=8.3, textColor=STEEL_LIGHT),
    "table_cell": ParagraphStyle("table_cell", fontName="Malgun", fontSize=9.6, leading=14,
        textColor=INK),
    "table_head": ParagraphStyle("table_head", fontName="Malgun-Bold", fontSize=9.6, leading=14,
        textColor=colors.white),
}


def callout(title, body):
    tbl = Table(
        [[Paragraph(f"※ {title}", styles["callout_title"])],
         [Paragraph(body, styles["callout_body"])]],
        colWidths=[PAGE_W - 2 * MARGIN],
    )
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), WARN_BG),
        ("BOX", (0, 0), (-1, -1), 0.8, WARN_LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
        ("TOPPADDING", (0, 1), (-1, 1), 3),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 9),
    ]))
    return KeepTogether([Spacer(1, 4), tbl, Spacer(1, 8)])


def bullets(items):
    out = []
    for it in items:
        out.append(Paragraph(f"•&nbsp;&nbsp;{it}", styles["bullet"]))
    return out


def table(headers, rows, col_widths=None):
    data = [[Paragraph(h, styles["table_head"]) for h in headers]]
    for r in rows:
        data.append([Paragraph(c, styles["table_cell"]) for c in r])
    n = len(headers)
    if col_widths is None:
        col_widths = [(PAGE_W - 2 * MARGIN) / n] * n
    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PAPER]),
    ]))
    return KeepTogether([tbl, Spacer(1, 8)])


class _NumberedCanvas(canvas.Canvas):
    """표지(1쪽)에는 꼬리말을 안 찍고, 그 뒤 페이지에는 '문서명 · N / 총쪽수'를
    찍는다. reportlab에 진짜 2-pass 카운터가 없어, 페이지별 상태를 저장해 뒀다가
    save() 시점에 총쪽수를 알고 나서 한 번에 그리는 표준 패턴을 쓴다."""
    doc_title = ""

    def __init__(self, *a, **kw):
        canvas.Canvas.__init__(self, *a, **kw)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for i, state in enumerate(self._saved):
            self.__dict__.update(state)
            if i > 0:
                self._draw_footer(i + 1, total)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def _draw_footer(self, page_no, total):
        self.saveState()
        self.setStrokeColor(LINE)
        self.setLineWidth(0.6)
        self.line(MARGIN, 16 * mm, PAGE_W - MARGIN, 16 * mm)
        self.setFont("Malgun", 8.3)
        self.setFillColor(STEEL_LIGHT)
        self.drawString(MARGIN, 11 * mm, self.doc_title)
        self.drawRightString(PAGE_W - MARGIN, 11 * mm, f"{page_no} / {total}")
        self.restoreState()


def build_manual(out_path, doc_title, title, subtitle, audience, version, updated, sections):
    """sections: [(heading, [flowable-producing blocks...]), ...]
    각 section body 항목은 문자열(본문 문단), ('bullets', [...]),
    ('callout', 제목, 본문), ('table', headers, rows[, widths]), Flowable 객체 중 하나."""

    frame = Frame(MARGIN, MARGIN, PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN, id="f")
    doc = BaseDocTemplate(out_path, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN)
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame])])

    canvasmaker = type("_C", (_NumberedCanvas,), {"doc_title": doc_title})

    story = []

    # 표지
    story.append(Spacer(1, 26 * mm))
    story.append(Paragraph(title, styles["cover_title"]))
    story.append(Paragraph(subtitle, styles["cover_sub"]))
    story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", thickness=0.8, color=LINE))
    story.append(Spacer(1, 10))
    story.append(Paragraph(f"최종 갱신일 {updated}", styles["cover_meta"]))
    story.append(Paragraph(f"버전 {version}", styles["cover_meta"]))
    story.append(Paragraph(f"대상: {audience}", styles["cover_meta"]))
    story.append(PageBreak())

    # 목차
    story.append(Paragraph("목차", styles["toc_h"]))
    for i, (heading, _body) in enumerate(sections, 1):
        story.append(Paragraph(f"{i}. {heading}", styles["toc_item"]))
    story.append(PageBreak())

    # 본문
    for i, (heading, body) in enumerate(sections, 1):
        story.append(Paragraph(f"{i}. {heading}", styles["h1"]))
        for block in body:
            if isinstance(block, str):
                story.append(Paragraph(block, styles["body"]))
            elif isinstance(block, tuple) and block[0] == "h2":
                story.append(Paragraph(block[1], styles["h2"]))
            elif isinstance(block, tuple) and block[0] == "bullets":
                story.extend(bullets(block[1]))
            elif isinstance(block, tuple) and block[0] == "callout":
                story.append(callout(block[1], block[2]))
            elif isinstance(block, tuple) and block[0] == "table":
                widths = block[3] if len(block) > 3 else None
                story.append(table(block[1], block[2], widths))
            elif isinstance(block, tuple) and block[0] == "space":
                story.append(Spacer(1, block[1]))
            else:
                story.append(block)

    doc.build(story, canvasmaker=canvasmaker)
