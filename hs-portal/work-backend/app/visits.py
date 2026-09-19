"""방문 통계 — 지금 접속자와 기간별 방문자 수.

**원본은 nginx 사이트별 접근 로그다.** 우리동네 직업계고 백엔드의 감시 도구와
같은 로그, 같은 기준(IP+브라우저를 해시한 값, 봇 제외)으로 센다. 두 화면의
숫자가 다르면 어느 쪽도 못 믿게 되기 때문이다. 코드를 가져다 쓰지 않고 여기
따로 둔 건, 이 서비스가 우리동네 직업계고 백엔드와 **프로세스까지 분리**돼
있어서다 — 그쪽을 import 하면 분리한 의미가 없어진다.

**두 갈래로 센다.**
  - 오늘 · 지금: 요청이 올 때 현재 로그를 바로 읽는다(1분 캐시).
  - 지난 날: 백그라운드가 회전된 로그까지 훑어 `work_visit_daily` 에 접어 둔다.
    로그는 2주쯤 뒤 지워지지만 접어 둔 숫자는 남아서 "전체"를 낼 수 있다.

**사이트를 로그 파일 이름으로 가른다.** 2026-09-13 에 nginx 로그를 사이트별로
나누기 전의 기록(access.log.*)은 여러 사이트가 섞여 있어 쓰지 않는다. 그래서
기록은 그날부터 시작한다.
"""

from __future__ import annotations

import gzip
import hashlib
import os
import re
import sys
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, Iterator, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .database import SessionLocal, get_db
from .models import WorkOrg, WorkUser, WorkVisitDaily

router = APIRouter(prefix="/api/work", tags=["visits"])

KST = timedelta(hours=9)

LOG_DIR = os.getenv("VISIT_LOG_DIR", "/var/log/nginx")


def _sites() -> List[Tuple[str, str]]:
    """[(보여 줄 이름, 로그 파일 이름 조각)]. 순서가 곧 화면 순서다."""
    raw = os.getenv("VISIT_SITES", "") or "우리동네 직업계고=udt,기록해=diary"
    out = []
    for part in raw.split(","):
        label, _, needle = part.partition("=")
        if label.strip() and needle.strip():
            out.append((label.strip(), needle.strip()))
    return out


# 감시 도구(backend/app/monitor.py)와 **같은 규칙**이어야 한다. 한쪽만 고치면
# 두 화면의 방문자 수가 어긋난다.
_LINE = re.compile(
    r'^(\S+) \S+ \S+ \[([^\]]+)\] "(\S+) ([^"]*?)(?: HTTP/[^"]*)?" '
    r'(\d{3}) (\d+|-) "([^"]*)" "([^"]*)"'
)
_BOT = re.compile(
    r"bot|crawl|spider|slurp|yeti|daum|facebookexternalhit|embedly|preview|"
    r"curl|wget|python-requests|httpx|okhttp|headless|monitor|uptime|scanner|"
    # 링크 미리보기·자동화 도구·보안 스캐너. 사람이 아니다.
    r"kakaotalk-scrap|whatsapp|go-http-client|axios|node-fetch|aiohttp|java/|"
    r"libwww|scrapy|zgrab|masscan|censys|expanse|nmap|nikto|sqlmap|nuclei|"
    r"l9explore|httpclient|palo alto",
    re.I,
)

# **브라우저로 페이지를 실제로 열었다는 흔적.**
#   두 사이트 모두 nginx 가 없는 주소도 index.html 로 200 을 돌려준다(React
#   새로고침 대응). 그래서 보안 스캐너가 /.env, /wp-login.php 를 찔러도 로그엔
#   "정상 방문"으로 남는다. 스캐너는 주소 하나만 찌르고 떠나지만, 사람의
#   브라우저는 화면을 그리려고 스크립트·스타일을 받아 가고 API 를 부른다.
#   그 흔적이 있는 사람만 방문자로 센다. (favicon 은 스캐너도 자주 받아 가서 뺀다.)
_EVIDENCE = re.compile(
    r"\.(css|js|mjs|png|jpe?g|gif|svg|webp|avif|woff2?)(\?|$)", re.I)

# 세는 규칙이 바뀌면 올린다. 저장된 날짜별 숫자를 새 규칙으로 다시 덮게 한다.
COUNT_RULE = 2
_ASSET = re.compile(
    r"\.(css|js|mjs|png|jpe?g|gif|svg|webp|avif|ico|woff2?|ttf|eot|map|mp4|m4a|webm|txt|xml)(\?|$)",
    re.I,
)
_MONTHS = {m: i for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), start=1)}


def _ts(s: str) -> Optional[datetime]:
    """'13/Sep/2026:05:44:01 +0900' → 로컬(한국) 시각. strptime 보다 몇 배 빠르다."""
    try:
        return datetime(int(s[7:11]), _MONTHS[s[3:6]], int(s[0:2]),
                        int(s[12:14]), int(s[15:17]), int(s[18:20]))
    except (ValueError, KeyError, IndexError):
        return None


def _now_kst() -> datetime:
    return datetime.utcnow() + KST


def _today() -> date:
    return _now_kst().date()


# ─────────────────────────────────────────────────────────────────────────────
# 로그 읽기
# ─────────────────────────────────────────────────────────────────────────────

def _files_for(needle: str) -> List[str]:
    """그 사이트의 로그 파일들. 현재 파일 + 회전된 .1, .2.gz ..."""
    try:
        names = os.listdir(LOG_DIR)
    except OSError:
        return []
    base = f"{needle}.access.log"
    out = [os.path.join(LOG_DIR, n) for n in names
           if n == base or n.startswith(base + ".")]
    return sorted(out)


def _lines(path: str) -> Iterator[str]:
    try:
        if path.endswith(".gz"):
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
                yield from f
        else:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                yield from f
    except OSError:
        return


class _Day:
    """하루치를 접는 그릇. 사람 흔적(해시)은 **이 안에서만** 들고 있다가 버린다.

    일단 요청한 사람을 모두 담아 두고, 그중 브라우저 흔적이 있는 사람만
    마지막에 센다. 흔적은 문서 요청보다 늦게 오기도 해서(문서 → 스크립트 순),
    줄을 읽는 도중에는 판단하지 않는다.
    """

    __slots__ = ("seen", "confirmed", "views", "bots", "buckets", "hours")

    def __init__(self):
        self.seen = set()                                  # 요청한 사람 전부
        self.confirmed = set()                             # 브라우저로 확인된 사람
        self.views: Dict[str, int] = defaultdict(int)      # 사람 -> 문서 연 횟수
        self.bots = 0
        self.buckets: Dict[int, set] = defaultdict(set)    # 5분 칸 -> 사람
        self.hours: Dict[int, set] = defaultdict(set)      # 시 -> 사람

    def add(self, when: datetime, ip: str, method: str, path: str, status: int, ua: str):
        # 브라우저 표시가 비어 있으면 사람일 리가 없다.
        if not ua or ua == "-" or _BOT.search(ua):
            self.bots += 1
            return
        key = hashlib.sha1(f"{ip}|{ua}".encode()).hexdigest()[:16]
        self.seen.add(key)
        self.buckets[(when.hour * 60 + when.minute) // 5].add(key)
        self.hours[when.hour].add(key)
        if status >= 400:
            return
        if path.startswith("/api/") or _EVIDENCE.search(path):
            self.confirmed.add(key)
        elif method == "GET" and not _ASSET.search(path):
            # 페이지 열람 = 화면 문서를 받아 간 횟수. 확인된 사람 것만 나중에 센다.
            self.views[key] += 1

    def summary(self) -> dict:
        c = self.confirmed
        return {
            "visitors": len(c),
            "pageviews": sum(n for k, n in self.views.items() if k in c),
            "peak_5m": max((len(v & c) for v in self.buckets.values()), default=0),
            "bot_hits": self.bots,
            # 요청은 했지만 페이지를 연 흔적이 없어 뺀 수(스캐너 등). 숨기지 않고 보여 준다.
            "excluded": len(self.seen - c),
        }


def _fold(paths: List[str], only_day: Optional[date] = None) -> Dict[date, _Day]:
    days: Dict[date, _Day] = defaultdict(_Day)
    for path in paths:
        for line in _lines(path):
            m = _LINE.match(line)
            if not m:
                continue
            when = _ts(m.group(2))
            if when is None:
                continue
            d = when.date()
            if only_day is not None and d != only_day:
                continue
            days[d].add(when, m.group(1), m.group(3), m.group(4),
                        int(m.group(5)), m.group(8))
    return days


# ─────────────────────────────────────────────────────────────────────────────
# 오늘 · 지금 (요청 때 바로 센다)
# ─────────────────────────────────────────────────────────────────────────────

_live_cache: Dict[str, Tuple[float, dict]] = {}
_live_lock = threading.Lock()


def _live(label: str, needle: str) -> dict:
    """그 사이트의 오늘 숫자 + 시간대별 + 지금 접속자. 1분 캐시."""
    with _live_lock:
        hit = _live_cache.get(label)
        if hit and time.time() - hit[0] < 60:
            return hit[1]

    today = _today()
    # 오늘 기록은 보통 현재 파일에 있지만, 로그 회전이 자정과 딱 맞지 않으면
    # 자정 직후 몇 분이 .1 쪽에 남는다. 둘 다 본다.
    paths = [p for p in _files_for(needle) if not p.endswith(".gz")]
    folded = _fold(paths, only_day=today).get(today) or _Day()

    now = _now_kst()
    cutoff_bucket = ((now.hour * 60 + now.minute) // 5)
    # "지금 접속자" = 최근 5분 칸과 그 직전 칸. 칸 경계에서 숫자가 0으로
    # 떨어졌다 올라가는 걸 막는다.
    recent = set()
    for b in (cutoff_bucket, cutoff_bucket - 1):
        recent |= folded.buckets.get(b, set())
    recent &= folded.confirmed

    data = {
        **folded.summary(),
        "now": len(recent),
        "hourly": [len(folded.hours.get(h, set()) & folded.confirmed) for h in range(24)],
    }
    with _live_lock:
        _live_cache[label] = (time.time(), data)
    return data


# ─────────────────────────────────────────────────────────────────────────────
# 지난 날 (백그라운드가 접어 둔다)
# ─────────────────────────────────────────────────────────────────────────────

def _upsert(db: Session, label: str, day: date, s: dict) -> None:
    row = (db.query(WorkVisitDaily)
           .filter(WorkVisitDaily.site == label, WorkVisitDaily.day == day).first())
    if row is None:
        row = WorkVisitDaily(site=label, day=day)
        db.add(row)
    if (row.rule or 1) != COUNT_RULE:
        # 세는 규칙이 바뀌었다. 예전 규칙으로 센 숫자는 새 숫자와 비교할 수 없으니
        # 그대로 덮는다(아래 max 를 쓰면 부풀었던 옛 숫자가 영영 안 줄어든다).
        row.visitors, row.pageviews = s["visitors"], s["pageviews"]
        row.peak_5m, row.bot_hits = s["peak_5m"], s["bot_hits"]
        row.excluded = s["excluded"]
        row.rule = COUNT_RULE
        return
    # **줄어들게 두지 않는다.** 가장 오래된 로그가 지워지는 날에는 그날 기록이
    # 반만 남은 채로 다시 훑어질 수 있다. 끝난 날의 방문자가 줄어들 일은 없으므로
    # 큰 쪽을 남긴다.
    row.visitors = max(row.visitors or 0, s["visitors"])
    row.pageviews = max(row.pageviews or 0, s["pageviews"])
    row.peak_5m = max(row.peak_5m or 0, s["peak_5m"])
    row.bot_hits = max(row.bot_hits or 0, s["bot_hits"])
    row.excluded = max(row.excluded or 0, s["excluded"])


def collect_once() -> int:
    """모든 사이트의 모든 로그를 훑어 날짜별로 쌓는다. 쌓은 줄 수를 돌려준다.

    회전된 파일은 안 바뀌므로 몇 번을 다시 훑어도 같은 숫자가 나온다 —
    그래서 "이미 했나"를 기억하지 않고 그냥 덮어쓴다. 기억하는 상태가 없으면
    어긋날 일도 없다.
    """
    written = 0
    db = SessionLocal()
    try:
        for label, needle in _sites():
            folded = _fold(_files_for(needle))
            for day, d in folded.items():
                _upsert(db, label, day, d.summary())
                written += 1
            db.commit()
    except Exception as e:
        db.rollback()
        print(f"[우리업무] 방문 집계 실패: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    finally:
        db.close()
    return written


_lock_handle = None


def _hold_lock() -> bool:
    """워커가 여럿이라 집계가 여러 번 돌지 않게, 한 워커만 맡는다.

    그 워커가 죽으면 잠금이 풀리고 다른 워커가 다음 차례에 가져간다.
    """
    global _lock_handle
    if _lock_handle is not None:
        return True
    try:
        import fcntl
    except ImportError:          # 윈도우(개발 PC)는 워커가 하나라 그냥 돈다
        return True
    try:
        fh = open("/tmp/work-visits.lock", "w")
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_handle = fh
        return True
    except OSError:
        return False


def start_collector(every_seconds: int = 600) -> None:
    if os.getenv("VISIT_COLLECT", "1") == "0":
        return

    def loop():
        time.sleep(8)
        while True:
            if _hold_lock():
                n = collect_once()
                print(f"[우리업무] 방문 집계 {n}일치 갱신", file=sys.stderr, flush=True)
            time.sleep(every_seconds)

    threading.Thread(target=loop, name="visit-collector", daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────
# 누가 무엇을 보나
# ─────────────────────────────────────────────────────────────────────────────

def allowed_sites(db: Session, user: WorkUser) -> List[Tuple[str, str]]:
    everything = _sites()
    if user.role == "admin":
        return everything
    if user.role != "partner" or not user.org_id:
        return []
    org = db.get(WorkOrg, user.org_id)
    if org is None or not org.is_active:
        return []
    if org.visit_sites is None:
        return everything
    wanted = {x.strip() for x in org.visit_sites.split(",") if x.strip()}
    return [s for s in everything if s[0] in wanted]


def _viewer(user: WorkUser) -> WorkUser:
    if user.role not in ("admin", "partner"):
        raise HTTPException(status_code=403, detail="방문 통계를 볼 권한이 없습니다.")
    return user


# ─────────────────────────────────────────────────────────────────────────────
# 기간
# ─────────────────────────────────────────────────────────────────────────────

RANGES = ("today", "week", "month", "all", "custom")


def _resolve(db: Session, key: str, start: str, end: str) -> Tuple[date, date]:
    today = _today()
    if key == "today":
        return today, today
    if key == "week":                         # 월요일부터
        return today - timedelta(days=today.weekday()), today
    if key == "month":
        return today.replace(day=1), today
    if key == "all":
        first = db.query(func.min(WorkVisitDaily.day)).scalar()
        return (first or today), today
    try:
        a = date.fromisoformat(start)
        b = date.fromisoformat(end) if end else a
    except ValueError:
        raise HTTPException(status_code=400, detail="날짜는 2026-09-15 형식으로 넣어 주세요.")
    if b < a:
        a, b = b, a
    if b > today:
        b = today
    if (b - a).days > 731:
        raise HTTPException(status_code=400, detail="기간은 2년까지만 볼 수 있습니다.")
    return a, b


# ─────────────────────────────────────────────────────────────────────────────
# 바깥으로
# ─────────────────────────────────────────────────────────────────────────────

# 순환 import 를 피하려고 여기서 가져온다(work.py 가 관문을 갖고 있다).
from .work import current_user, admin_only  # noqa: E402


@router.get("/visits")
def visits(
    period: str = Query("today", alias="range"),
    start: str = "",
    end: str = "",
    site: str = "",
    user: WorkUser = Depends(current_user),
    db: Session = Depends(get_db),
):
    _viewer(user)
    if period not in RANGES:
        raise HTTPException(status_code=400, detail="모르는 기간입니다.")

    sites = allowed_sites(db, user)
    allowed_names = {s[0] for s in sites}
    if not sites:
        return {"sites": [], "empty_reason": "볼 수 있는 사이트가 없습니다. 관리자에게 문의하세요."}
    if site:
        sites = [s for s in sites if s[0] == site] or sites
    labels = [s[0] for s in sites]

    a, b = _resolve(db, period, start, end)
    today = _today()

    # 지난 날은 쌓아 둔 표에서, 오늘은 로그에서 바로.
    rows = (
        db.query(WorkVisitDaily)
        .filter(WorkVisitDaily.site.in_(labels),
                WorkVisitDaily.day >= a, WorkVisitDaily.day <= b,
                WorkVisitDaily.day < today)
        .all()
    )
    table: Dict[date, Dict[str, dict]] = defaultdict(dict)
    for r in rows:
        table[r.day][r.site] = {"visitors": r.visitors, "pageviews": r.pageviews,
                                "peak_5m": r.peak_5m, "excluded": r.excluded or 0}

    live = {}
    if a <= today <= b:
        for label, needle in sites:
            live[label] = _live(label, needle)
            table[today][label] = {k: live[label][k]
                                   for k in ("visitors", "pageviews", "peak_5m", "excluded")}

    # 빈 날도 줄을 만든다. 막대그래프에서 날이 빠지면 추세가 거짓말을 한다.
    daily = []
    d = a
    while d <= b:
        per = {lbl: table.get(d, {}).get(
                   lbl, {"visitors": 0, "pageviews": 0, "peak_5m": 0, "excluded": 0})
               for lbl in labels}
        daily.append({"day": d.isoformat(), "sites": per})
        d += timedelta(days=1)

    by_site = {}
    for lbl in labels:
        by_site[lbl] = {
            "visitors": sum(x["sites"][lbl]["visitors"] for x in daily),
            "pageviews": sum(x["sites"][lbl]["pageviews"] for x in daily),
            "peak_5m": max((x["sites"][lbl]["peak_5m"] for x in daily), default=0),
            "excluded": sum(x["sites"][lbl].get("excluded", 0) for x in daily),
        }

    first = db.query(func.min(WorkVisitDaily.day)).scalar()
    return {
        "range": {"key": period, "from": a.isoformat(), "to": b.isoformat(),
                  "days": (b - a).days + 1},
        "sites": labels,
        # 색은 사이트에 붙는다. 권한 때문에 일부만 보여도 같은 사이트는 늘 같은
        # 색이어야 하므로, 걸러내기 전 전체 순번을 함께 준다.
        # 볼 수 있는 사이트의 순번만 준다. 전체 목록을 주면 화면엔 안 나와도
        # 응답을 열어 보면 권한 없는 사이트 이름이 드러난다.
        "site_index": {lbl: i for i, (lbl, _) in enumerate(_sites()) if lbl in allowed_names},
        "totals": {
            "visitors": sum(v["visitors"] for v in by_site.values()),
            "pageviews": sum(v["pageviews"] for v in by_site.values()),
            "peak_5m": max((v["peak_5m"] for v in by_site.values()), default=0),
        },
        "by_site": by_site,
        "daily": daily,
        # 하루만 볼 때는 시간대별이 더 쓸모 있다. 오늘만 로그에 시각이 남아 있다.
        "hourly": ({lbl: live[lbl]["hourly"] for lbl in live} if a == b == today else None),
        "now": {lbl: live[lbl]["now"] for lbl in live} if live else None,
        "since": first.isoformat() if first else today.isoformat(),
    }


@router.get("/admin/orgs/{org_id}/visit-sites")
def get_org_visit_sites(org_id: int, user: WorkUser = Depends(admin_only),
                        db: Session = Depends(get_db)):
    org = db.get(WorkOrg, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="없는 기업입니다.")
    everything = [s[0] for s in _sites()]
    allowed = everything if org.visit_sites is None else [
        x for x in org.visit_sites.split(",") if x in everything]
    return {"all": everything, "allowed": allowed}


@router.put("/admin/orgs/{org_id}/visit-sites")
def set_org_visit_sites(org_id: int, body: dict, user: WorkUser = Depends(admin_only),
                        db: Session = Depends(get_db)):
    org = db.get(WorkOrg, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="없는 기업입니다.")
    everything = [s[0] for s in _sites()]
    wanted = [x for x in (body.get("allowed") or []) if x in everything]
    # 전부 골랐으면 None 으로 둔다. 나중에 사이트가 늘면 자동으로 따라가게.
    org.visit_sites = None if set(wanted) == set(everything) else ",".join(wanted)
    db.commit()
    return {"all": everything, "allowed": wanted}
