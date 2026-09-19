"""자기소개서를 파일로 내보낸다.

학생이 실제로 제출할 때는 회사나 학교가 정한 양식에 옮겨 적어야 한다.
화면에서 하나씩 복사해 붙이면 항목을 빠뜨리거나 순서가 뒤바뀐다.
그래서 양식이 갖춰진 파일로 바로 받게 한다.

**HWP 를 직접 만들지 않는 이유**

한글 문서(.hwp)는 공개되지 않은 이진 형식이라 파이썬으로 만들 수 없다.
대신 한글이 함께 쓰는 개방형 형식인 HWPX(.hwpx)를 만든다. 한글 2014
이상에서 그냥 열리고 편집도 된다. 겉보기에는 hwp 와 다르지 않다.

**PDF 를 손으로 그리는 이유**

한글을 그리려면 글꼴 파일이 있어야 하는데, 서버에 어떤 글꼴이 깔려
있을지 알 수 없다. 그래서 나눔고딕을 먼저 찾고, 없으면 시스템에 있는
한글 글꼴 아무거나 쓴다. 그것도 없으면 PDF 만 못 만들고 다른 형식은
그대로 내려준다.
"""

import io
import math
import os
import re
import zipfile
from datetime import datetime
from typing import List, Tuple
from xml.sax.saxutils import escape

# 한글이 나오는 글꼴. reportlab 은 TrueType 윤곽선만 읽는다.
# Noto CJK 는 PostScript 윤곽선이라 읽지 못하므로, 먼저 TrueType 을 찾고
# 없으면 Noto 를 TrueType 으로 바꿔 쓴다.
# 자소서 기본 글꼴은 맑은 고딕이다. 리눅스 서버에는 없는 것이 보통이라,
# 있으면 쓰고 없으면 생김새가 가장 가까운 나눔고딕으로 대신한다.
# HWPX·DOCX 는 글꼴 '이름'만 적어 보내므로, 학생 컴퓨터에서 열면
# 진짜 맑은 고딕으로 보인다. 서버 글꼴은 PDF 를 그릴 때만 쓴다.
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/msttcorefonts/malgun.ttf",
    "/usr/share/fonts/truetype/malgun/malgun.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
    "/usr/share/fonts/truetype/unfonts-core/UnDotum.ttf",
    "/usr/share/fonts/truetype/baekmuk/dotum.ttf",
]

def has_hangul(path: str) -> bool:
    """이 글꼴에 한글이 들어 있는가.

    이름만 보고 고르면 안 된다. 일본어 고딕처럼 'gothic' 이 붙었는데
    한글 글립이 없는 글꼴이 있고, 그러면 PDF 에서 글자가 통째로 빠진다.
    실제로 '가' 자가 있는지 확인한다.

    확인에는 fontTools 가 필요하다. 없으면 판단할 수 없으므로 False 를
    돌려주는데, 그래서 이 함수는 이름을 믿을 수 없는 글꼴에만 쓴다.
    아래 FONT_CANDIDATES 처럼 한글 글꼴임이 분명한 것은 검사하지 않는다.
    """
    try:
        from fontTools.ttLib import TTFont as FTFont
    except ImportError:
        return False
    try:
        font = FTFont(path, fontNumber=0, lazy=True)
        cmap = font.getBestCmap()
        font.close()
        return ord("가") in cmap and ord("힣") in cmap
    except Exception:
        return False


_FONT_CACHE = None


def find_font() -> str:
    """쓸 수 있는 한글 글꼴 경로. 한 번 찾으면 기억해 둔다.

    글꼴 파일을 하나씩 열어 확인하므로 처음 한 번은 느릴 수 있다.
    """
    global _FONT_CACHE
    if _FONT_CACHE is not None:
        return _FONT_CACHE
    _FONT_CACHE = _find_font_slow()
    # 못 찾으면 서버 로그에 남긴다. 화면에는 '만들 수 없습니다' 만 나가므로
    # 무엇이 없어서인지 운영자가 알 길이 있어야 한다.
    if _FONT_CACHE:
        print(f"[자소서 PDF] 글꼴: {_FONT_CACHE}", flush=True)
    else:
        print("[자소서 PDF] 한글 글꼴을 찾지 못했습니다. "
              "apt-get install fonts-nanum 으로 설치해 주세요.", flush=True)
    return _FONT_CACHE


def _find_font_slow() -> str:
    # 목록에 적어 둔 것은 한글 글꼴임을 알고 넣은 것이라 검사하지 않는다.
    # 검사를 거치게 두면 fontTools 가 없는 서버에서 전부 탈락해,
    # 나눔고딕이 깔려 있는데도 PDF 가 안 되는 일이 생긴다.
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    # 목록에 없으면 시스템을 훑는다. 이때는 이름을 믿을 수 없어
    # 글꼴 안에 한글이 실제로 있는지 확인한다(fontTools 필요).
    for root in ("/usr/share/fonts", "/usr/local/share/fonts"):
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for f in sorted(files):
                if not f.lower().endswith(".ttf"):
                    continue
                full = os.path.join(dirpath, f)
                if has_hangul(full):
                    return full
    return ""


def clean(text: str) -> str:
    """줄 끝 공백만 정리한다. 문단 구분은 학생이 쓴 그대로 둔다."""
    lines = [ln.rstrip() for ln in (text or "").replace("\r\n", "\n").split("\n")]
    return "\n".join(lines).strip()


# ── PDF ────────────────────────────────────────────────────


# 한 장에 넣을 항목 수. 항목마다 쓸 자리가 넉넉해야 학생이 길게 적을 수
# 있고, 종이에 옮겨 적을 때도 보기 좋다. 내용이 짧아 빈칸이 남더라도
# 칸 크기를 줄이지 않는다.
ITEMS_PER_PAGE = 4


def paginate(items, need_slots, pad: bool = True):
    """항목을 장별로 끊는다. 긴 글은 여러 칸을 차지한다.

    한 장은 네 칸이다. 글이 길어 한 칸에 안 들어가면 두 칸, 세 칸을
    쓴다. 칸 높이를 고정해 두면 넘친 글이 다음 칸 위에 겹쳐 그려져
    읽을 수 없게 된다. 실제로 그런 자소서가 나온 적이 있다.

    반환: [[(항목명, 본문, 칸수), ...], ...]  장별 목록
    """
    out, page, left = [], [], ITEMS_PER_PAGE
    for (label, body) in items:
        need = max(1, min(ITEMS_PER_PAGE, need_slots(label, body)))
        if need > left and page:
            # 이 장에 자리가 모자라면 다음 장으로 넘긴다.
            if pad and left:
                page.append(("", "", left))
            out.append(page)
            page, left = [], ITEMS_PER_PAGE
        page.append((label, body, need))
        left -= need
    if page or not out:
        if pad and left:
            page.append(("", "", left))
        out.append(page)
    return out


# 표 색. 항목 칸은 연한 초록, 테두리는 진회색.
LABEL_BG = "#E2EFD9"
BORDER = "#7F7F7F"


def build_pdf(name: str, title: str, items: List[Tuple[str, str]]) -> bytes:
    """항목명과 본문을 좌우로 나눈 표 형태의 PDF."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        SimpleDocTemplate, PageBreak, Paragraph, Table, TableStyle,
    )

    font_path = find_font()
    if not font_path:
        # 글꼴이 없으면 글자가 통째로 빠진 PDF 가 나온다. 그런 파일을
        # 주느니 안 만드는 편이 낫다. 다른 형식은 그대로 쓸 수 있다.
        raise RuntimeError(
            "서버에 한글 글꼴이 없어 PDF 를 만들 수 없습니다. "
            "HWPX·워드·텍스트 형식을 이용해 주세요. "
            "(서버에 fonts-nanum 설치가 필요합니다)"
        )

    # 같은 이름으로 두 번 등록하면 오류가 나므로 한 번만 한다.
    if "KR" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("KR", font_path))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=20 * mm, bottomMargin=18 * mm,
        title=title or "자기소개서", author=name or "",
    )

    st_title = ParagraphStyle("t", fontName="KR", fontSize=17, leading=24,
                              alignment=1, spaceAfter=14)
    st_name = ParagraphStyle("n", fontName="KR", fontSize=11, leading=17,
                             spaceAfter=6)
    # 항목명이 길어 여러 줄로 접힌다. 본문보다 조금 작게 두어 덜 답답하게.
    st_label = ParagraphStyle("l", fontName="KR", fontSize=9.5, leading=14,
                              alignment=1)
    st_body = ParagraphStyle("b", fontName="KR", fontSize=11, leading=19)

    def para(text, style):
        return Paragraph(escape(text).replace("\n", "<br/>"), style)

    # 제목은 글자 사이를 벌려 양식처럼 보이게 한다.
    story = [para(" ".join(title or "자기소개서"), st_title)]
    story.append(para(f"■ 성 명 : {name or ''}", st_name))

    label_w = 42 * mm
    body_w = doc.width - label_w

    # 제목·성명 줄이 차지하는 몫을 빼고, 남는 높이를 항목 수로 나눈다.
    # 한 장에 늘 같은 수가 들어가야 장마다 칸 크기가 같아 양식처럼 보인다.
    head_h = 26 * mm
    row_h = (doc.height - head_h) / ITEMS_PER_PAGE

    style = TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.7, colors.HexColor(BORDER)),
        ("VALIGN", (0, 0), (0, -1), "MIDDLE"),
        ("VALIGN", (1, 0), (1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor(LABEL_BG)),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ])

    # 글이 한 칸에 들어가는지 실제로 재 본다. 글자 수로 어림하면
    # 줄바꿈 때문에 어긋나, 넘친 글이 다음 칸 위에 겹쳐 그려진다.
    inner_w = body_w - 12          # 좌우 여백을 뺀 실제 글 너비
    def slots_for(label, body):
        text = clean(body)
        if not text:
            return 1
        _w, h = para(text, st_body).wrap(inner_w, 10 ** 6)
        return math.ceil((h + 16) / row_h)      # 위아래 여백 몫을 더한다

    for n, chunk in enumerate(paginate(items, slots_for)):
        if n:
            # 둘째 장부터는 제목을 다시 얹어 어떤 서류인지 알 수 있게 한다.
            story.append(PageBreak())
            story.append(para(" ".join(title or "자기소개서"), st_title))
            story.append(para(f"■ 성 명 : {name or ''}", st_name))

        rows = [[para(label, st_label), para(clean(body), st_body)]
                for label, body, _n in chunk]
        table = Table(rows, colWidths=[label_w, body_w],
                      rowHeights=[row_h * n2 for _l, _b, n2 in chunk],
                      repeatRows=0)
        table.setStyle(style)
        story.append(table)

    doc.build(story)
    return buf.getvalue()


# ── HWPX ───────────────────────────────────────────────────
#
# HWPX 는 zip 안에 XML 을 담은 형식이다. 한글이 읽는 데 꼭 필요한 파일만
# 넣어 최소한으로 만든다. 서식을 화려하게 하기보다, 한글에서 열려서
# 학생이 바로 고칠 수 있는 것을 목표로 한다.

HWPX_VERSION = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version"
 tagetApplication="WORDPROCESSOR" major="5" minor="0" micro="5" buildNumber="0"
 os="1" xmlVersion="1.4" application="Hancom Office Hangul"
 appVersion="9, 1, 1, 5656 WIN32LEWindows_Unknown_Version"/>"""

HWPX_CONTAINER = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container"
 xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf">
 <ocf:rootfiles>
  <ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/>
 </ocf:rootfiles>
</ocf:container>"""

HWPX_MANIFEST = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
 odf:version="1.2">
 <odf:file-entry odf:full-path="/" odf:media-type="application/hwp+zip"/>
</odf:manifest>"""

HWPX_CONTENT_HPF = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<opf:package xmlns:opf="http://www.idpf.org/2007/opf/" version=""
 unique-identifier="" id="">
 <opf:metadata xmlns:opf="http://www.idpf.org/2007/opf/"
  xmlns:dc="http://purl.org/dc/elements/1.1/">
  <opf:title>{title}</opf:title>
 </opf:metadata>
 <opf:manifest>
  <opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>
  <opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>
 </opf:manifest>
 <opf:spine>
  <opf:itemref idref="header" linear="yes"/>
  <opf:itemref idref="section0" linear="yes"/>
 </opf:spine>
</opf:package>"""

HWPX_HEADER = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head"
 xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" version="1.4" secCnt="1">
 <hh:refList>
  <hh:fontfaces itemCnt="1">
   <hh:fontface lang="HANGUL" fontCnt="1">
    <hh:font id="0" face="맑은 고딕" type="TTF" isEmbedded="0"/>
   </hh:fontface>
  </hh:fontfaces>
  <hh:borderFills itemCnt="3">
   <hh:borderFill id="1" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">
    <hh:slash type="NONE" Crooked="0" isCounter="0"/>
    <hh:backSlash type="NONE" Crooked="0" isCounter="0"/>
    <hh:leftBorder type="NONE" width="0.1 mm" color="#000000"/>
    <hh:rightBorder type="NONE" width="0.1 mm" color="#000000"/>
    <hh:topBorder type="NONE" width="0.1 mm" color="#000000"/>
    <hh:bottomBorder type="NONE" width="0.1 mm" color="#000000"/>
    <hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>
   </hh:borderFill>
   <hh:borderFill id="2" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">
    <hh:slash type="NONE" Crooked="0" isCounter="0"/>
    <hh:backSlash type="NONE" Crooked="0" isCounter="0"/>
    <hh:leftBorder type="SOLID" width="0.12 mm" color="#7F7F7F"/>
    <hh:rightBorder type="SOLID" width="0.12 mm" color="#7F7F7F"/>
    <hh:topBorder type="SOLID" width="0.12 mm" color="#7F7F7F"/>
    <hh:bottomBorder type="SOLID" width="0.12 mm" color="#7F7F7F"/>
    <hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>
   </hh:borderFill>
   <hh:borderFill id="3" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">
    <hh:slash type="NONE" Crooked="0" isCounter="0"/>
    <hh:backSlash type="NONE" Crooked="0" isCounter="0"/>
    <hh:leftBorder type="SOLID" width="0.12 mm" color="#7F7F7F"/>
    <hh:rightBorder type="SOLID" width="0.12 mm" color="#7F7F7F"/>
    <hh:topBorder type="SOLID" width="0.12 mm" color="#7F7F7F"/>
    <hh:bottomBorder type="SOLID" width="0.12 mm" color="#7F7F7F"/>
    <hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>
    <hc:fillBrush>
     <hc:winBrush faceColor="#E2EFD9" hatchColor="#999999" alpha="0"/>
    </hc:fillBrush>
   </hh:borderFill>
  </hh:borderFills>
  <hh:charProperties itemCnt="4">
   <hh:charPr id="0" height="1100" textColor="#000000" shadeColor="none"
    useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="1">
    <hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0"
     symbol="0" user="0"/>
    <hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100"
     symbol="100" user="100"/>
    <hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0"
     symbol="0" user="0"/>
    <hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100"
     symbol="100" user="100"/>
    <hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0"
     symbol="0" user="0"/>
   </hh:charPr>
   <hh:charPr id="1" height="1600" textColor="#000000" shadeColor="none"
    useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="1">
    <hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0"
     symbol="0" user="0"/>
    <hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100"
     symbol="100" user="100"/>
    <hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0"
     symbol="0" user="0"/>
    <hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100"
     symbol="100" user="100"/>
    <hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0"
     symbol="0" user="0"/>
    <hh:bold/>
   </hh:charPr>
   <hh:charPr id="2" height="1200" textColor="#000000" shadeColor="none"
    useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="1">
    <hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0"
     symbol="0" user="0"/>
    <hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100"
     symbol="100" user="100"/>
    <hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0"
     symbol="0" user="0"/>
    <hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100"
     symbol="100" user="100"/>
    <hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0"
     symbol="0" user="0"/>
    <hh:bold/>
   </hh:charPr>
   <hh:charPr id="3" height="800" textColor="#8B949E" shadeColor="none"
    useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="1">
    <hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0"
     symbol="0" user="0"/>
    <hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100"
     symbol="100" user="100"/>
    <hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0"
     symbol="0" user="0"/>
    <hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100"
     symbol="100" user="100"/>
    <hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0"
     symbol="0" user="0"/>
   </hh:charPr>
  </hh:charProperties>
  <hh:paraProperties itemCnt="3">
   <hh:paraPr id="0" tabPrIDRef="0" condense="0" fontLineHeight="0"
    snapToGrid="1" suppressLineNumbers="0" checked="0">
    <hh:align horizontal="JUSTIFY" vertical="BASELINE"/>
    <hh:heading type="NONE" idRef="0" level="0"/>
    <hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD"
     widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0"
     lineWrap="BREAK"/>
    <hh:margin>
     <hc:intent value="0" unit="HWPUNIT"/><hc:left value="0" unit="HWPUNIT"/>
     <hc:right value="0" unit="HWPUNIT"/><hc:prev value="0" unit="HWPUNIT"/>
     <hc:next value="0" unit="HWPUNIT"/>
    </hh:margin>
    <hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/>
   </hh:paraPr>
   <hh:paraPr id="1" tabPrIDRef="0" condense="0" fontLineHeight="0"
    snapToGrid="1" suppressLineNumbers="0" checked="0">
    <hh:align horizontal="CENTER" vertical="BASELINE"/>
    <hh:heading type="NONE" idRef="0" level="0"/>
    <hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD"
     widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0"
     lineWrap="BREAK"/>
    <hh:margin>
     <hc:intent value="0" unit="HWPUNIT"/><hc:left value="0" unit="HWPUNIT"/>
     <hc:right value="0" unit="HWPUNIT"/><hc:prev value="0" unit="HWPUNIT"/>
     <hc:next value="0" unit="HWPUNIT"/>
    </hh:margin>
    <hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/>
   </hh:paraPr>
   <hh:paraPr id="2" tabPrIDRef="0" condense="0" fontLineHeight="0"
    snapToGrid="1" suppressLineNumbers="0" checked="0">
    <hh:align horizontal="RIGHT" vertical="BASELINE"/>
    <hh:heading type="NONE" idRef="0" level="0"/>
    <hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD"
     widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0"
     lineWrap="BREAK"/>
    <hh:margin>
     <hc:intent value="0" unit="HWPUNIT"/><hc:left value="0" unit="HWPUNIT"/>
     <hc:right value="0" unit="HWPUNIT"/><hc:prev value="0" unit="HWPUNIT"/>
     <hc:next value="0" unit="HWPUNIT"/>
    </hh:margin>
    <hh:lineSpacing type="PERCENT" value="130" unit="HWPUNIT"/>
   </hh:paraPr>
  </hh:paraProperties>
  <hh:styles itemCnt="1">
   <hh:style id="0" type="PARA" name="바탕글" engName="Normal" paraPrIDRef="0"
    charPrIDRef="0" nextStyleIDRef="0" langID="1042" lockForm="0"/>
  </hh:styles>
 </hh:refList>
</hh:head>"""


# 한글 단위(HWPUNIT). 1mm = 283.465
MM = 283.465
LABEL_W = int(42 * MM)      # 항목 칸 너비. 항목명이 길어 넉넉히 잡는다.
BODY_W = int(108 * MM)      # 본문 칸 너비
ROW_MIN_H = int(22 * MM)    # 칸 최소 높이. 양식처럼 보이게 여유를 둔다.

# A4 높이 29.7cm 에서 위아래 여백과 제목·성명 줄을 뺀 값.
# 한 장에 늘 같은 수가 들어가야 장마다 칸 크기가 같아 양식처럼 보인다.
PAGE_BODY_MM = 29.7 * 10 - 20 * 2 - 45


def _hwpx_para(text: str, char_pr: int = 0, para_pr: int = 0) -> str:
    """문단 하나. 빈 줄도 문단으로 넣어야 간격이 산다."""
    return (
        f'<hp:p id="0" paraPrIDRef="{para_pr}" styleIDRef="0" pageBreak="0" '
        f'columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="{char_pr}">'
        f'<hp:t>{escape(text)}</hp:t>'
        f'</hp:run></hp:p>'
    )


def _hwpx_cell(paras: str, col: int, row: int, width: int, height: int,
               border_fill: int) -> str:
    """표 칸 하나. border_fill 2 는 흰 칸, 3 은 초록 칸이다."""
    return (
        f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" '
        f'dirty="0" borderFillIDRef="{border_fill}">'
        f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" '
        f'vertAlign="CENTER" linkListIDRef="0" linkListNextIDRef="0" '
        f'textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
        f'{paras}'
        f'</hp:subList>'
        f'<hp:cellAddr colAddr="{col}" rowAddr="{row}"/>'
        f'<hp:cellSpan colSpan="1" rowSpan="1"/>'
        f'<hp:cellSz width="{width}" height="{height}"/>'
        f'<hp:cellMargin left="850" right="850" top="510" bottom="510"/>'
        f'</hp:tc>'
    )


def _hwpx_slots(label: str, body: str) -> int:
    """한글에서 이 글이 몇 칸을 차지할지 어림한다."""
    text = clean(body)
    if not text:
        return 1
    lines = sum(max(1, len(ln) // 32 + 1) for ln in text.split("\n"))
    return max(math.ceil(len(text) / 250), math.ceil(lines / 8))


def _hwpx_table(items) -> str:
    """자소서 항목을 좌우 두 칸으로 나눈 표."""
    # 한 칸 높이. 긴 글은 여러 칸을 차지한다.
    slot_h = int(PAGE_BODY_MM / ITEMS_PER_PAGE * MM)

    rows_xml, total_h = [], 0
    for i, item in enumerate(items):
        label, body = item[0], item[1]
        slots = item[2] if len(item) > 2 else 1
        height = slot_h * slots
        total_h += height
        left = _hwpx_cell(_hwpx_para(label, 2, 1), 0, i, LABEL_W, height, 3)
        body_paras = "".join(_hwpx_para(ln) for ln in clean(body).split("\n"))
        right = _hwpx_cell(body_paras, 1, i, BODY_W, height, 2)
        rows_xml.append(f'<hp:tr>{left}{right}</hp:tr>')

    return (
        '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" '
        'columnBreak="0" merged="0"><hp:run charPrIDRef="0">'
        f'<hp:tbl id="1" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" '
        f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" '
        f'pageBreak="CELL" repeatHeader="0" rowCnt="{len(items)}" colCnt="2" '
        f'cellSpacing="0" borderFillIDRef="2" noAdjust="0">'
        '<hp:sz width="' + str(LABEL_W + BODY_W) + '" widthRelTo="ABSOLUTE" '
        f'height="{total_h}" heightRelTo="ABSOLUTE" protect="0"/>'
        '<hp:pos treatAsChar="0" affectLSpacing="0" flowWithText="1" '
        'allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" '
        'horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" '
        'vertOffset="0" horzOffset="0"/>'
        '<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
        '<hp:inMargin left="510" right="510" top="141" bottom="141"/>'
        + "".join(rows_xml) +
        '</hp:tbl></hp:run></hp:p>'
    )


def build_hwpx(name: str, title: str, items: List[Tuple[str, str]]) -> bytes:
    """한글에서 열리는 HWPX 파일. 자소서 양식처럼 표로 만든다."""
    paras = []
    # 한 칸에 들어갈 만한 글자 수. 폭 10cm, 11pt 로 한 줄에 약 30자,
    # 한 칸에 약 8줄이 들어간다. 정확히 재려면 글꼴 정보가 필요한데,
    # 워드는 넘치면 스스로 늘리므로 어림값으로 충분하다.
    PER_SLOT_CHARS = 230

    def slots_for(label, body):
        text = clean(body)
        if not text:
            return 1
        # 줄바꿈이 많으면 그만큼 줄이 늘어난다.
        lines = sum(max(1, len(ln) // 30 + 1) for ln in text.split("\n"))
        return max(math.ceil(len(text) / PER_SLOT_CHARS), math.ceil(lines / 8))

    for page_no, chunk in enumerate(paginate(items, slots_for)):
        if page_no:
            # 둘째 장부터는 쪽을 넘기고 제목을 다시 얹는다.
            paras.append(
                '<hp:p id="0" paraPrIDRef="1" styleIDRef="0" pageBreak="1" '
                'columnBreak="0" merged="0"><hp:run charPrIDRef="1">'
                f'<hp:t>{escape(" ".join(title or "자기소개서"))}</hp:t>'
                '</hp:run></hp:p>'
            )
        else:
            # 제목은 글자 사이를 벌려 양식처럼 보이게 한다.
            paras.append(_hwpx_para(" ".join(title or "자기소개서"), 1, 1))
        paras.append(_hwpx_para(""))
        paras.append(_hwpx_para(f"■ 성 명 : {name or ''}", 2))
        paras.append(_hwpx_table(chunk))
    paras.append(_hwpx_para(""))

    section = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
        'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core">'
        + "".join(paras) +
        '</hs:sec>'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # mimetype 은 압축하지 않고 맨 앞에 두어야 한다.
        z.writestr(zipfile.ZipInfo("mimetype"), "application/hwp+zip",
                   compress_type=zipfile.ZIP_STORED)
        z.writestr("version.xml", HWPX_VERSION)
        z.writestr("META-INF/container.xml", HWPX_CONTAINER)
        z.writestr("META-INF/manifest.xml", HWPX_MANIFEST)
        z.writestr("Contents/content.hpf",
                   HWPX_CONTENT_HPF.format(title=escape(title or "자기소개서")))
        z.writestr("Contents/header.xml", HWPX_HEADER)
        z.writestr("Contents/section0.xml", section)
    return buf.getvalue()


# ── DOCX ───────────────────────────────────────────────────


def _shade(cell, color_hex: str) -> None:
    """표 칸에 배경색을 넣는다. python-docx 에 기본 기능이 없어 직접 붙인다."""
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color_hex.lstrip("#"))
    tcPr.append(shd)


def build_docx(name: str, title: str, items: List[Tuple[str, str]]) -> bytes:
    """항목명과 본문을 좌우로 나눈 표 형태의 워드 문서.

    한 장에 네 항목씩 넣는다. 빈 칸이 남더라도 칸 크기를 줄이지 않아,
    장마다 같은 틀이 되고 인쇄해 손으로 적을 자리로도 쓸 수 있다.
    """
    from docx import Document
    from docx.enum.table import WD_ALIGN_VERTICAL
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.oxml.ns import qn
    from docx.shared import Pt, Cm

    LABEL_CM, BODY_CM = 4.6, 10.0      # 합계 14.6cm = 쓸 수 있는 폭
    TWIP = 567                          # 1cm = 567 twip(1/20 pt)
    TOP_CM = BOTTOM_CM = 1.8

    # 한 장에 늘 같은 수가 들어가야 장마다 칸 크기가 같아 양식처럼 보인다.
    # A4 높이에서 위아래 여백과 제목·성명 줄을 뺀 값을 넷으로 나눈다.
    # 딱 맞게 잡으면 테두리 두께만큼 넘쳐 마지막 칸이 다음 장으로 밀린다.
    # 1.5cm 를 더 덜어내 여유를 둔다.
    row_cm = (29.7 - TOP_CM - BOTTOM_CM - 3.2 - 1.5) / ITEMS_PER_PAGE

    doc = Document()
    for sec in doc.sections:
        sec.left_margin = Cm(2.2)
        sec.right_margin = Cm(2.2)
        sec.top_margin = Cm(TOP_CM)
        sec.bottom_margin = Cm(BOTTOM_CM)

    style = doc.styles["Normal"]
    style.font.name = "맑은 고딕"
    style.font.size = Pt(11)
    # 한글은 eastAsia 글꼴을 따로 정해야 제대로 나온다.
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "맑은 고딕")

    def ensure(parent, tag, index=None):
        """python-docx 가 이미 넣어 둔 것을 찾아 고친다. 새로 만들어 덧붙이면
        같은 요소가 둘이 되어 프로그램이 어느 쪽을 볼지 알 수 없다."""
        el = parent.find(qn(tag))
        if el is None:
            el = parent.makeelement(qn(tag), {})
            if index is None:
                parent.append(el)
            else:
                parent.insert(index, el)
        return el

    def header(first: bool):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if not first:
            # 둘째 장부터는 앞에 쪽 나눔을 넣는다.
            p.add_run().add_break(WD_BREAK.PAGE)
        # 제목은 글자 사이를 벌려 양식처럼 보이게 한다.
        r = p.add_run(" ".join(title or "자기소개서"))
        r.bold = True
        r.font.size = Pt(17)

        n = doc.add_paragraph()
        nr = n.add_run(f"■ 성 명 : {name or ''}")
        nr.bold = True

    for page_no, chunk in enumerate(paginate(items, _hwpx_slots)):
        header(page_no == 0)

        table = doc.add_table(rows=0, cols=2)
        table.style = "Table Grid"
        table.autofit = False

        tbl = table._tbl
        tblPr = tbl.tblPr

        tblW = ensure(tblPr, "w:tblW")
        tblW.set(qn("w:w"), str(int((LABEL_CM + BODY_CM) * TWIP)))
        tblW.set(qn("w:type"), "dxa")

        layout = ensure(tblPr, "w:tblLayout")
        layout.set(qn("w:type"), "fixed")

        # 열 너비는 tblGrid 에 적어야 워드·한글·리브레오피스가 모두 지킨다.
        grid = ensure(tbl, "w:tblGrid", 1)
        for col in list(grid):
            grid.remove(col)
        for cm in (LABEL_CM, BODY_CM):
            col = grid.makeelement(qn("w:gridCol"), {})
            col.set(qn("w:w"), str(int(cm * TWIP)))
            grid.append(col)

        for label, body, slots in chunk:
            row = table.add_row()
            left, right = row.cells

            # 최소 높이만 정해 둔다. 내용이 넘치면 워드가 알아서 늘린다.
            trPr = row._tr.get_or_add_trPr()
            trH = trPr.makeelement(qn("w:trHeight"), {})
            trH.set(qn("w:val"), str(int(row_cm * slots * TWIP)))
            trH.set(qn("w:hRule"), "atLeast")
            trPr.append(trH)

            # 칸에도 같은 값을 적어 둔다. tblGrid 만 보는 프로그램과
            # 칸 값을 보는 프로그램이 섞여 있다.
            left.width = Cm(LABEL_CM)
            right.width = Cm(BODY_CM)
            left.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            _shade(left, LABEL_BG)

            lp = left.paragraphs[0]
            lp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            lr = lp.add_run(label)
            lr.bold = True
            # 항목명이 길어 여러 줄로 접힌다. 본문보다 조금 작게 둔다.
            lr.font.size = Pt(9.5)

            # 첫 문단은 칸에 이미 있으므로 그것부터 채운다.
            lines = clean(body).split("\n")
            first = right.paragraphs[0]
            first.text = lines[0] if lines else ""
            first.paragraph_format.line_spacing = 1.5
            for line in lines[1:]:
                bp = right.add_paragraph(line)
                bp.paragraph_format.line_spacing = 1.5
                bp.paragraph_format.space_after = Pt(0)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ── 공통 ───────────────────────────────────────────────────


def build_txt(name: str, title: str, items: List[Tuple[str, str]]) -> bytes:
    """어디서든 열리는 최소 형태. 다른 형식이 안 될 때의 대비책이기도 하다."""
    out = [title or "자기소개서"]
    meta = " · ".join(x for x in [name, datetime.now().strftime("%Y-%m-%d")] if x)
    if meta:
        out.append(meta)
    out.append("")
    for label, body in items:
        out.append(f"[ {label} ]")
        out.append(clean(body))
        out.append("")
    return "\n".join(out).encode("utf-8-sig")


FORMATS = {
    "pdf": ("application/pdf", "pdf", build_pdf),
    "hwpx": ("application/hwp+zip", "hwpx", build_hwpx),
    "docx": ("application/vnd.openxmlformats-officedocument."
             "wordprocessingml.document", "docx", build_docx),
    "txt": ("text/plain; charset=utf-8", "txt", build_txt),
}


def safe_filename(base: str) -> str:
    """파일 이름에 쓸 수 없는 글자를 뺀다."""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "", base or "").strip()
    return (name or "자기소개서")[:60]
