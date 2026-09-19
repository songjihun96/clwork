"""PDF 로 그릴 때 쓰는 한글 글꼴 찾기.

원래는 자기소개서 내보내기(resume_export.py)에 있던 것을, 연구 서비스로
떼어 오면서 **필요한 부분만** 옮겼다. 자소서 코드 전체를 끌고 오면 이
서비스와 상관없는 화면·모델까지 딸려 온다.

한글을 그리려면 글꼴 파일이 있어야 하는데 서버에 무엇이 깔려 있을지 알 수
없다. 나눔고딕을 먼저 찾고, 없으면 시스템에 있는 한글 글꼴 아무거나 쓴다.
그것도 없으면 PDF 만 못 만들고 다른 형식은 그대로 내려준다.
"""

import os

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




def safe_filename(base: str) -> str:
    """파일 이름에 쓸 수 없는 글자를 뺀다."""
    import re
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "", base or "").strip()
    return (name or "연구자료")[:60]
