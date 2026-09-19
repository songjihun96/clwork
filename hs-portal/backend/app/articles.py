"""
특성화고신문(sinmoon.net) 기사 크롤러.

같은 곳/협력 관계로 기사를 수집해 학교와 연결한다.
- 목록 페이지에서 기사 링크·제목·썸네일·요약·날짜를 뽑는다.
- 제목에 들어있는 학교명을 우리 DB의 학교와 매칭한다.
- 출처는 항상 '특성화고신문 제공'으로 표기하고 원문 링크를 남긴다.

주의:
- 사이트가 EUC-KR 인코딩이라 디코딩에 주의한다.
- 일부 서버 환경(데이터센터 IP)에서는 sinmoon.net이 403으로 막힐 수 있다.
  그 경우 크롤링은 조용히 실패하고, 수동 등록은 계속 동작한다.
- 사이트 구조가 바뀌면 파싱이 깨질 수 있으므로 실패해도 예외를 삼킨다.
"""

import html as html_lib
import re
import time
from datetime import date, datetime
from typing import Optional
from urllib.parse import urljoin, urlparse, parse_qs

import requests

from .database import SessionLocal
from .models import Article, School

BASE = "https://www.sinmoon.net"
# 학교 소개/지역 기사가 모이는 섹션. 필요 시 추가.
LIST_SECTIONS = [110]  # 지역별 학교 기사

# 2026년 8월 사이트 개편으로 주소가 /content/ 에서 /news/ 로 바뀌었다.
# no·category 값은 그대로 유지된다.
OLD_PATH = "/content/view.html"
NEW_PATH = "/news/view.html"

# 목록 페이지가 자바스크립트로 그려져 HTML 만으로는 기사를 얻을 수 없다.
# 대신 RSS 를 쓴다. 서버가 완성된 XML 을 주므로 훨씬 안정적이다.
# 다만 최신 10건만 나오므로, 과거 기사는 이미 DB 에 있는 것을 그대로 쓴다.
RSS_URL = f"{BASE}/rankup_module/rankup_rss/index.html"

# 'compatible;' 이 들어간 User-Agent 는 많은 CMS 가 봇으로 판정해 모바일이나
# 간이 페이지를 내려준다. 그 페이지는 이미지 구조가 달라 썸네일이 비어 버린다.
# 그래서 일반 데스크톱 브라우저와 같은 값을 쓰고, 출처는 별도 헤더로 밝힌다.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": BASE + "/",
    # 운영자가 접속 기록에서 우리 수집기임을 알아볼 수 있게 남긴다.
    "X-Crawler": "UDT-Portal/1.0 (+https://udjschool.ggm.kr)",
}

TIMEOUT = 10
# 한 섹션에서 최대 몇 페이지까지 넘길지(안전 상한). 페이지당 20건이므로
# 500페이지면 약 1만 건까지 커버한다. 빈 페이지가 나오면 그 전에 멈춘다.
MAX_PAGES = 500
# 서버 부담을 줄이기 위한 요청 간 딜레이(초)
PAGE_DELAY = 0.4


class SourceUnavailable(Exception):
    """원문 사이트가 기사를 주지 못하는 상태."""


# 호스팅이 만료되면 랭크업이 안내 페이지를 200 으로 돌려준다.
# 응답 코드만 보면 성공으로 보이므로, 내용으로 알아내야 한다.
# 그대로 두면 기사 제목이 '호스팅서비스가 만료되었습니다' 로 덮어써진다.
UNAVAILABLE_MARKS = (
    "호스팅서비스가 만료",
    "호스팅기간이 만료",
    "해당사이트의",
    "rankup.co.kr",
)


def to_new_url(url: str) -> str:
    """옛 주소(/content/view.html)를 새 주소(/news/view.html)로 바꾼다."""
    if not url:
        return url
    return url.replace(OLD_PATH, NEW_PATH)


def looks_unavailable(html: str) -> bool:
    head = (html or "")[:3000]
    return any(mark in head for mark in UNAVAILABLE_MARKS)


def _fetch(url: str) -> Optional[str]:
    """URL을 받아 EUC-KR로 디코딩한 HTML을 돌려준다. 실패하면 None."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
    except requests.RequestException:
        return None
    # 이 사이트는 euc-kr. requests가 잘못 추정할 수 있어 명시적으로 디코딩.
    raw = r.content
    html = None
    for enc in ("euc-kr", "cp949", "utf-8"):
        try:
            html = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if html is None:
        html = raw.decode("euc-kr", errors="replace")

    # 만료 안내 페이지를 기사로 착각하면 기존 자료를 망친다. 즉시 멈춘다.
    if looks_unavailable(html):
        raise SourceUnavailable(
            "특성화고신문(sinmoon.net) 호스팅이 만료되어 기사를 읽을 수 없습니다. "
            "호스팅을 연장한 뒤 다시 수집해주세요."
        )
    return html


def _extract_no(url: str) -> Optional[int]:
    """view.html?...&no=1234 에서 1234를 뽑는다."""
    try:
        qs = parse_qs(urlparse(url).query)
        if "no" in qs:
            return int(qs["no"][0])
    except (ValueError, KeyError):
        pass
    return None


def _clean(text: str) -> str:
    """기사 제목·요약을 사람이 읽는 글자로 되돌린다.

    태그를 먼저 지우고 그다음에 실체 참조를 푼다. 순서를 바꾸면 안 된다 —
    기사 제목에는 '< 2026 일본 학교 간 국제교육교류활동 >' 처럼 꺾쇠를
    괄호로 쓰는 관행이 있어서, 먼저 풀어버리면 그게 태그로 보여 통째로
    지워진다. 같은 이유로 태그 판별도 '<' 다음에 영문자가 오는 것만으로
    좁혔다 — 신문사가 이미 풀어서 보내주는 제목도 섞여 있어서다.

    예전에는 &nbsp; &amp; &quot; 넷만 손으로 골라 바꿨는데, 그러다 보니
    &lt; &gt; &#8211;(줄표) &#8203;(폭 없는 공백) 같은 나머지가 화면에
    그대로 나왔다. 종류를 늘려 잡는 대신 표준 해석기에 맡긴다.
    """
    text = re.sub(r"</?[A-Za-z][^>]*>", "", text)   # 태그만 제거
    text = html_lib.unescape(text)               # &lt; &#8211; ... 전부
    # 폭 없는 공백은 눈에 안 보이면서 글자 수·검색만 어긋나게 한다.
    text = text.replace("\u200b", "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", text).strip()


def parse_list(html: str) -> list[dict]:
    """목록 페이지 HTML에서 기사 항목들을 뽑는다.
    특성화고신문 CMS의 view.html 링크를 기준으로 파싱한다.
    같은 기사가 이미지링크+제목링크로 두 번 나오므로 no 기준으로 합친다."""
    # no -> {url, title, thumbnail}
    articles: dict[int, dict] = {}

    # 1) 모든 view 링크와 그 앵커 안쪽 내용을 추출
    #    <a href="...no=N"> ...내용... </a>
    anchor_re = re.compile(
        r'<a[^>]+href=["\']([^"\']*content/view\.html\?[^"\']*no=(\d+))["\'][^>]*>(.*?)</a>',
        re.DOTALL | re.IGNORECASE,
    )
    for m in anchor_re.finditer(html):
        href, no_str, inner = m.group(1), m.group(2), m.group(3)
        no = int(no_str)
        # 모바일 주소로 저장하면 나중에 상세를 다시 읽을 때도 이미지가 없다.
        # 원문 링크를 눌렀을 때도 데스크톱 페이지가 열리도록 통일한다.
        url = urljoin(BASE, href).replace(f"{BASE}/m/", f"{BASE}/")
        entry = articles.setdefault(no, {"no": no, "url": url, "title": "", "thumbnail": ""})

        # 앵커 안에 img가 있으면 썸네일.
        # 모바일 페이지는 지연 로딩을 써서 src 대신 data-src/data-original 에
        # 진짜 주소를 넣고, src 에는 1x1 placeholder 를 두는 경우가 많다.
        if not entry["thumbnail"]:
            entry["thumbnail"] = _pick_image(inner)

        # 앵커 안의 순수 텍스트가 제목 후보 (이미지만 있는 링크는 텍스트가 비어있음)
        text = _clean(inner)
        if text and len(text) >= 5 and not entry["title"]:
            entry["title"] = text

    # 제목이 있는 것만 유효 기사로 반환
    return [a for a in articles.values() if a["title"]]


# 실제 사진이 아닌 것들. 이런 주소가 썸네일로 잡히면 빈 회색 칸만 보인다.
IMG_SKIP = (
    "blank", "spacer", "placeholder", "loading", "dummy", "noimage", "no_image",
    "data:image", "1x1", "icon", "logo", "btn_", "bg_", "ico_",
)


def _usable(url: str) -> bool:
    url = (url or "").strip()
    if not url:
        return False
    low = url.lower()
    return not any(bad in low for bad in IMG_SKIP)


def _pick_image(html_fragment: str) -> str:
    """조각에서 쓸 만한 이미지 주소를 고른다.

    지연 로딩 속성을 먼저 본다. 모바일 페이지는 src 에 빈 그림을 넣고
    data-src 에 진짜 주소를 두는 일이 흔하다.
    따옴표가 없는 속성(src=/foo.jpg)과 srcset, 배경 이미지까지 훑는다.
    """
    attrs = ("data-src", "data-original", "data-lazy", "data-echo",
             "data-thumb", "data-image", "src")

    for attr in attrs:
        # 따옴표가 있는 경우
        for m in re.finditer(
            rf'<img[^>]+{attr}\s*=\s*["\']([^"\']+)["\']', html_fragment, re.IGNORECASE
        ):
            if _usable(m.group(1)):
                return urljoin(BASE, m.group(1).strip())
        # 따옴표가 없는 경우
        for m in re.finditer(
            rf'<img[^>]+{attr}\s*=\s*([^\s>"\']+)', html_fragment, re.IGNORECASE
        ):
            if _usable(m.group(1)):
                return urljoin(BASE, m.group(1).strip())

    # srcset="a.jpg 1x, b.jpg 2x" 형태
    for m in re.finditer(
        r'<img[^>]+srcset\s*=\s*["\']([^"\']+)["\']', html_fragment, re.IGNORECASE
    ):
        first = m.group(1).split(",")[0].strip().split(" ")[0]
        if _usable(first):
            return urljoin(BASE, first)

    # style="background-image:url(...)"
    for m in re.finditer(
        r'background-image\s*:\s*url\(\s*["\']?([^"\')]+)', html_fragment, re.IGNORECASE
    ):
        if _usable(m.group(1)):
            return urljoin(BASE, m.group(1).strip())

    return ""


def fetch_article_detail(url: str) -> dict:
    """기사 상세에서 요약과 날짜를 보강한다. 실패해도 빈 값."""
    # 예전에 모바일 주소로 저장된 기사도 데스크톱 페이지에서 읽는다.
    url = url.replace(f"{BASE}/m/", f"{BASE}/")
    html = _fetch(url)
    if not html:
        return {}
    detail = {}

    # 본문 앞부분을 요약으로 (태그 제거 후 120자)
    # 흔한 본문 컨테이너를 못 특정하므로, 메타 description 우선
    desc_m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
    if desc_m:
        detail["summary"] = _clean(desc_m.group(1))[:150]

    # 대표 이미지. 목록(특히 모바일)에서 썸네일을 못 건진 기사를 여기서 채운다.
    og_m = re.search(
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.I
    )
    if not og_m:
        og_m = re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html, re.I
        )
    if og_m:
        detail["thumbnail"] = urljoin(BASE, og_m.group(1).strip())
    else:
        # og:image 가 없으면 본문에서 가장 먼저 나오는 쓸 만한 이미지를 쓴다.
        found = _pick_image(html)
        if found:
            detail["thumbnail"] = found

    # 날짜: YYYY-MM-DD 또는 YYYY.MM.DD 패턴
    date_m = re.search(r'(20\d{2})[.\-](\d{1,2})[.\-](\d{1,2})', html)
    if date_m:
        try:
            y, mo, d = int(date_m.group(1)), int(date_m.group(2)), int(date_m.group(3))
            detail["published_at"] = date(y, mo, d)
        except ValueError:
            pass

    return detail


RENAMED_SCHOOLS = {
    "근명여자정보고등학교": "근명고등학교",
    # 다른 개명 학교가 발견되면 여기에 추가
}


def _abbreviations(name: str) -> list[str]:
    """정식 학교명에서 흔히 쓰이는 줄임말 후보들을 만든다.
    예) 대전여자상업고등학교 -> [대전여상, 대전여상고]
        경북기계공업고등학교 -> [경북기계공고, 경북공고]
    """
    cands = set()
    n = name
    cands.add(n)
    cands.add(n.replace("고등학교", "고"))

    rules = [
        ("여자정보산업고등학교", ["여정산", "여정고"]),
        ("여자상업고등학교", ["여상", "여상고"]),
        ("여자정보고등학교", ["여정", "여정고"]),
        ("기계공업고등학교", ["기계공고", "공고"]),
        ("전자공업고등학교", ["전자공고", "공고"]),
        ("공업고등학교", ["공고"]),
        ("상업고등학교", ["상고"]),
        ("정보산업고등학교", ["정산", "정보고"]),
        ("정보고등학교", ["정보고"]),
        ("여자고등학교", ["여고"]),
        ("생활과학고등학교", ["생과고"]),
        ("디자인고등학교", ["디자인고"]),
        ("관광고등학교", ["관광고"]),
    ]
    for suffix, abbrs in rules:
        if n.endswith(suffix):
            prefix = n[: -len(suffix)]
            for a in abbrs:
                cands.add(prefix + a)
            break

    # 너무 짧은 후보는 오매칭 위험이 커서 3글자 이상만
    return [c for c in cands if len(c) >= 3]


def match_school(title: str, schools: list[School]) -> Optional[int]:
    """기사 제목에서 학교명을 찾아 school_id를 돌려준다.

    매칭 순서(정확도 높은 것부터):
    1) 개명된 학교: 기사의 옛 이름이 제목에 있으면 새 이름 학교에 연결
    2) 정식명 그대로
    3) 줄임말 후보(대전여상, 경북공고 등)

    긴 후보부터 대조해 부분일치 오류를 줄인다.
    """
    # 1) 개명 학교 우선 처리
    for old_name, new_name in RENAMED_SCHOOLS.items():
        if old_name in title:
            for s in schools:
                if s.name == new_name:
                    return s.id

    # 2)+3) 각 학교의 후보(정식명+줄임말)를 만들어 대조.
    #    긴 후보가 먼저 매칭되도록 (지역명 포함 후보 우선)
    best = None
    best_len = 0
    for s in schools:
        if not s.name:
            continue
        for cand in _abbreviations(s.name):
            if cand in title and len(cand) > best_len:
                best = s.id
                best_len = len(cand)
    return best


def fetch_rss() -> list:
    """RSS 에서 최신 기사를 읽는다.

    목록 페이지가 자바스크립트로 그려지도록 바뀌어 HTML 파싱이 불가능해졌다.
    RSS 는 서버가 완성된 XML 을 주므로 구조가 바뀌어도 잘 견딘다.
    최신 10건 정도만 나오지만, 하루 몇 건 올라오는 매체라 충분하다.
    """
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    try:
        r = requests.get(RSS_URL, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as exc:
        raise SourceUnavailable(f"RSS 를 읽지 못했습니다: {exc}")

    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as exc:
        raise SourceUnavailable(f"RSS 형식을 이해하지 못했습니다: {exc}")

    items = []
    for node in root.iterfind(".//item"):
        link = (node.findtext("link") or "").strip()
        title = (node.findtext("title") or "").strip()
        if not link or not title:
            continue

        # 링크에서 기사 번호를 뽑는다. 이 값으로 중복을 가린다.
        m = re.search(r"[?&]no=(\d+)", link)
        if not m:
            continue

        published = None
        raw_date = (node.findtext("pubDate") or "").strip()
        if raw_date:
            try:
                published = parsedate_to_datetime(raw_date).date()
            except (TypeError, ValueError):
                published = None

        desc = (node.findtext("description") or "").strip()
        items.append({
            "no": m.group(1),
            "url": to_new_url(link),
            # RSS 로 받은 값도 목록 수집과 똑같이 씻는다. 예전에는 여기서만
            # 태그만 지우고 넘겨서, RSS 로 들어온 기사에는 &nbsp; 같은 게
            # 그대로 남아 화면에 노출됐다.
            "title": _clean(title),
            "summary": _clean(desc)[:300],
            "published_at": published,
            "thumbnail": "",
        })
    return items


def crawl_rss() -> dict:
    """RSS 로 새 기사를 수집한다. 이미 있는 기사는 건너뛴다."""
    db = SessionLocal()
    try:
        items = fetch_rss()
        schools = db.query(School).all()
        existing = {
            n for (n,) in db.query(Article.source_no)
            .filter(Article.source_no.isnot(None)).all()
        }
        existing_titles = {t for (t,) in db.query(Article.title).all()}

        added = 0
        matched = 0
        for it in items:
            if it["no"] in existing or it["title"] in existing_titles:
                continue
            school_id = match_school(it["title"], schools)

            # RSS 에는 이미지가 안 들어온다. 그래서 예전에는 RSS 로 들어온
            # 기사가 전부 썸네일 없이 회색 칸으로 나왔다. 새로 넣는 기사만
            # 원문에서 대표 이미지를 찾아 채운다(이미 있는 기사는 위에서
            # continue 로 걸러지므로 매번 다시 받지 않는다).
            #
            # 가져오는 건 이미지뿐이다. 원문의 meta description 은 기사 요약이
            # 아니라 신문사 소개문이고, 날짜도 엉뚱한 값이 나온다 — 둘 다
            # RSS 값이 정확하므로 그대로 둔다.
            detail = fetch_article_detail(it["url"])
            time.sleep(PAGE_DELAY)

            db.add(Article(
                source_no=it["no"],
                title=it["title"][:300],
                url=it["url"][:500],
                summary=it["summary"],
                thumbnail=(detail or {}).get("thumbnail", "")[:500],
                published_at=it["published_at"],
                school_id=school_id,
                source="rss",
            ))
            added += 1
            if school_id:
                matched += 1

        db.commit()
        return {"ok": True, "scanned": len(items), "added": added, "matched": matched}
    except SourceUnavailable as exc:
        db.rollback()
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        db.rollback()
        return {"ok": False, "error": str(exc)}
    finally:
        db.close()


def crawl(max_pages: int = MAX_PAGES, fetch_detail: bool = False) -> dict:
    """기사를 수집해 저장한다.

    목록 페이지를 1페이지부터 끝까지(빈 페이지가 나올 때까지) 넘기며 수집한다.
    페이지당 20건이며, 학교 기사가 수천 건이라 상세 페이지 요청은 기본적으로
    생략한다(fetch_detail=True면 요약·날짜까지 보강하지만 매우 느려진다).

    실패하면 예외 없이 {'ok': False} 를 반환한다.
    """
    # 목록 페이지가 자바스크립트로 바뀌어 HTML 수집이 더 이상 동작하지 않는다.
    # 같은 이름으로 불리는 곳이 여럿이라, 여기서 RSS 수집으로 넘긴다.
    return crawl_rss()


def crawl_html(max_pages: int = MAX_PAGES, fetch_detail: bool = False) -> dict:
    """옛 목록 HTML 수집. 사이트가 바뀌어 지금은 쓰이지 않는다(참고용)."""
    db = SessionLocal()
    try:
        schools = db.query(School).all()
        # 이미 저장된 source_no 집합(중복 저장 방지, 매번 DB 조회 대신 메모리 캐시)
        existing_nos = {
            n for (n,) in db.query(Article.source_no).filter(Article.source_no.isnot(None)).all()
        }

        added = 0
        matched = 0
        scanned = 0
        empty_streak = 0  # 연속으로 빈 페이지가 나온 횟수
        # 이미 저장된 제목 집합(같은 기사가 여러 no로 중복되는 것 방지)
        existing_titles = {t for (t,) in db.query(Article.title).all()}

        for section in LIST_SECTIONS:
            for page in range(1, max_pages + 1):
                # 모바일 페이지(/m/)는 목록 썸네일을 지연 로딩으로 처리해
                # HTML 에 실제 이미지 주소가 없다. 데스크톱 주소로 받는다.
                list_url = f"{BASE}/content/index.html?section={section}&page={page}"
                html = _fetch(list_url)
                items = parse_list(html) if html else []

                if not items:
                    empty_streak += 1
                    # 빈 페이지가 2번 연속이면 그 섹션은 끝난 것으로 보고 중단
                    if empty_streak >= 2:
                        break
                    time.sleep(PAGE_DELAY)
                    continue
                empty_streak = 0

                new_in_page = 0
                for item in items:
                    scanned += 1
                    if item["no"] in existing_nos:
                        continue
                    existing_nos.add(item["no"])
                    # 같은 제목 기사가 이미 있으면 건너뜀(다른 카테고리 중복 노출 방지)
                    if item["title"] in existing_titles:
                        continue
                    existing_titles.add(item["title"])
                    new_in_page += 1

                    school_id = match_school(item["title"], schools)
                    if school_id:
                        matched += 1

                    # 학교에 연결된 기사만 상세를 받아 요약·날짜를 보강한다.
                    # (전체 수천 건에 상세 요청하면 너무 느리고 서버 부담이 크다)
                    detail = {}
                    if school_id or fetch_detail:
                        detail = fetch_article_detail(item["url"])
                        time.sleep(PAGE_DELAY)

                    db.add(Article(
                        source_no=item["no"],
                        url=item["url"],
                        title=item["title"][:300],
                        summary=detail.get("summary", ""),
                        thumbnail=item.get("thumbnail", "")[:500],
                        published_at=detail.get("published_at"),
                        school_id=school_id,
                        source="crawl",
                    ))
                    added += 1

                # 페이지 단위로 커밋(중간에 끊겨도 저장 보존)
                if new_in_page:
                    db.commit()
                time.sleep(PAGE_DELAY)

        db.commit()
        return {"ok": True, "scanned": scanned, "added": added, "matched": matched}
    except Exception as e:  # 크롤링 실패가 서비스를 멈추면 안 된다
        db.rollback()
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def rematch_all() -> dict:
    """이미 저장된 기사들을 개선된 매칭 로직으로 다시 학교와 연결한다.
    재크롤링 없이 school_id만 갱신한다. 매칭 로직을 바꾼 뒤 한 번 실행하면 된다."""
    db = SessionLocal()
    try:
        schools = db.query(School).all()
        articles = db.query(Article).all()
        updated = 0
        for a in articles:
            new_sid = match_school(a.title, schools)
            if new_sid and new_sid != a.school_id:
                a.school_id = new_sid
                updated += 1
        db.commit()
        total_matched = db.query(Article).filter(Article.school_id.isnot(None)).count()
        return {"ok": True, "updated": updated, "total_matched": total_matched}
    except Exception as e:
        db.rollback()
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def dedupe() -> dict:
    """제목이 완전히 같은 중복 기사를 정리한다.
    특성화고신문이 같은 기사를 여러 카테고리에 노출해 no가 달라지는 경우가 있다.
    같은 제목 그룹에서 가장 오래된(가장 작은 id) 하나만 남기고 삭제한다."""
    db = SessionLocal()
    try:
        from sqlalchemy import func as _f
        # 제목별로 여러 건인 것들을 찾는다
        dup_titles = (
            db.query(Article.title)
            .group_by(Article.title)
            .having(_f.count(Article.id) > 1)
            .all()
        )
        removed = 0
        for (title,) in dup_titles:
            rows = (
                db.query(Article)
                .filter(Article.title == title)
                .order_by(Article.id.asc())
                .all()
            )
            # 첫 번째(가장 이른)만 남기고 나머지 삭제.
            # 단, 남길 것에 school_id가 없고 뒤엣것에 있으면 그걸 남긴 것에 채운다.
            keep = rows[0]
            for r in rows[1:]:
                if not keep.school_id and r.school_id:
                    keep.school_id = r.school_id
                if not keep.summary and r.summary:
                    keep.summary = r.summary
                if not keep.thumbnail and r.thumbnail:
                    keep.thumbnail = r.thumbnail
                db.delete(r)
                removed += 1
        db.commit()
        return {"ok": True, "removed": removed}
    except Exception as e:
        db.rollback()
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "rematch":
        r = rematch_all()
        if r["ok"]:
            print(f"재매칭 완료 — {r['updated']}건 갱신, 총 {r['total_matched']}건 학교 연결됨")
        else:
            print(f"재매칭 실패: {r.get('error')}")
    elif len(sys.argv) > 1 and sys.argv[1] == "dedupe":
        r = dedupe()
        if r["ok"]:
            print(f"중복 제거 완료 — {r['removed']}건 삭제")
        else:
            print(f"중복 제거 실패: {r.get('error')}")
    else:
        result = crawl()
        if result["ok"]:
            msg = f"수집 완료 — 스캔 {result.get('scanned', 0)}건, 신규 {result.get('added', 0)}건"
            if "matched" in result:
                msg += f", 학교매칭 {result['matched']}건"
            print(msg)
        else:
            print(f"수집 실패: {result.get('error')}")
