"""서버·트래픽 감시. 바깥에서 한 번 부르면 지금 상태가 전부 나온다.

**왜 만들었나.** 서비스가 한 대의 서버 위에 여러 개 올라가 있다(UDJ, 기록해,
상담, 음성중계). 어느 하나가 조용히 죽거나 디스크가 차오르는 걸 알아채는
수단이 지금은 "사용자가 알려 주는 것"뿐이다.

**설계에서 정한 것 세 가지.**

1. **접속자 수는 nginx 로그에서 센다.** 파이썬 메모리에 카운터를 두면 gunicorn
   워커 3개가 각자 다른 숫자를 들고 있어서 새로고침할 때마다 값이 바뀐다.
   로그는 사이트 3개 트래픽이 한 곳에 모이고, 정적 파일까지 잡히고, 백엔드를
   재시작해도 안 날아간다.

2. **새로 설치할 것을 만들지 않는다.** psutil 을 쓰면 서버에서 pip install 을
   해야 하는데, 여기는 배포가 zip 수동 적용이라 그 한 줄이 실패하면 배포가
   멈춘다. 그래서 /proc 을 직접 읽는다. 표준 라이브러리만 쓴다.

3. **감시가 부하가 되면 안 된다.** 로그 파싱과 systemctl 호출은 한 번에 몇십
   밀리초씩 먹는다. 결과를 몇 초 캐시해서, 위젯이 1초마다 불러도 실제 수집은
   그 주기로만 돈다.

**여는 방법.** `.env` 에 `MONITOR_TOKEN=충분히긴임의문자열` 을 넣고, 부를 때
`X-Monitor-Token` 헤더에 같은 값을 실는다. 관리자 계정의 JWT 로도 열린다.
토큰을 안 넣으면 이 API 는 토큰 경로로는 아예 안 열린다(빈 문자열 우회 방지).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from . import models
from .auth import get_current_user_optional
from .database import SessionLocal, get_db
from .models import (
    AdminAuditLog,
    CsCallLog,
    CsCallSession,
    Inquiry,
    MonitorSample,
    PlanOrder,
    QuizTaken,
    Role,
    SubscriptionOrder,
    User,
)

router = APIRouter(prefix="/api/monitor", tags=["monitor"])


# ─────────────────────────────────────────────────────────────────────────────
# 설정. 전부 환경변수로 덮을 수 있게 두되, 기본값만으로 이 서버에서 돈다.
# ─────────────────────────────────────────────────────────────────────────────

def _env_list(name: str, default: str) -> List[str]:
    raw = (os.getenv(name, "") or "").strip() or default
    return [x.strip() for x in raw.split(",") if x.strip()]


# 살았는지 볼 systemd 유닛.
#   diary-ai-worker 는 일부러 뺐다. AI_QUEUE_BACKEND=redis 로 바꿨을 때만 쓰는
#   템플릿 서비스라, 기본 구성에서는 꺼져 있는 게 정상이다. 정상인 것을
#   "죽었다"고 띄우면 경보 전체가 무시당한다.
UNITS = _env_list(
    "MONITOR_UNITS",
    "udt-backend,diary-backend,udt-audio,nginx,postgresql",
)

# 실제로 응답하는지 찔러 볼 곳. "이름=주소" 형식.
#   systemctl 이 active 라고 해도 gunicorn 워커가 부팅에 실패해 있는 경우가
#   실제로 있었다. 마스터는 살아 있고 워커만 죽는다. 그래서 진짜 요청을 보낸다.
PROBES = _env_list(
    "MONITOR_PROBES",
    "UDJ=http://127.0.0.1:8000/api/meta,"
    "기록해=http://127.0.0.1:8100/api/health,"
    "음성중계=http://127.0.0.1:8010/api/meta",
)

# nginx 접근 로그. 비워 두면 /var/log/nginx 아래 access 로그를 전부 찾는다.
LOG_PATHS = _env_list("MONITOR_NGINX_LOGS", "")
LOG_DIR = os.getenv("MONITOR_NGINX_LOG_DIR", "/var/log/nginx")

# 없으면 경고할 외부 연동. 여기 없는 것은 "안 씀"으로만 적는다.
#   토스 결제는 무통장입금만 쓰는 동안 키가 없는 게 정상이고, LLM 키는
#   기록해 쪽(diary-backend/.env)에 따로 있다.
REQUIRED_DEPS = set(_env_list("MONITOR_REQUIRED_DEPS", "sms,mail,phone"))

# 사이트 이름 = 로그 파일 이름에 들어 있는 조각.
#   nginx combined 형식에는 어느 도메인으로 들어왔는지가 안 남는다. 그래서
#   사이트를 가르는 유일한 근거가 "어느 로그 파일에 적혔나"다. 사이트별로
#   access_log 를 따로 두면 이 표대로 이름이 붙는다.
SITE_MAP_RAW = _env_list(
    "MONITOR_SITES",
    "우리동네 직업계고=udt,기록해=diary,상담=cs",
)
SITE_RULES: List[Tuple[str, str]] = []
for _entry in SITE_MAP_RAW:
    _label, _, _needle = _entry.partition("=")
    if _needle:
        SITE_RULES.append((_label.strip(), _needle.strip().lower()))
SITE_LABELS = [lbl for lbl, _ in SITE_RULES]


# 어느 사이트로도 안 맞는 로그에 붙일 이름.
#   사이트별로 로그를 갈라 놓아도 기본 서버 블록(도메인 없이 IP 로 들어오는
#   요청, 호스트를 모르는 스캐너)은 여전히 access.log 로 떨어진다. 그걸
#   "access" 라는 탭으로 보여 주면 무슨 뜻인지 알 수가 없다.
SITE_OTHER = os.getenv("MONITOR_SITE_OTHER", "기타").strip() or "기타"


def site_of(log_path: str) -> str:
    """로그 파일 이름에서 사이트 이름을 찾는다."""
    base = os.path.basename(log_path)
    name = base.lower()
    for label, needle in SITE_RULES:
        if needle in name:
            return label
    # nginx 기본 로그는 여러 사이트가 섞여 있어 사이트 이름을 붙일 수 없다.
    if name in ("access.log", "access_log"):
        return SITE_OTHER
    return base.replace(".access.log", "").replace(".log", "") or SITE_OTHER


# 로그를 뒤에서 얼마나 읽을지. 1시간치를 담을 만큼이면 된다.
LOG_TAIL_BYTES = int(os.getenv("MONITOR_LOG_TAIL_BYTES", str(8 * 1024 * 1024)))

# 인증서 폴더(certbot 기본 위치).
CERT_DIR = os.getenv("MONITOR_CERT_DIR", "/etc/letsencrypt/live")

# DB 백업이 떨어지는 곳. 여기 제일 새 파일의 나이를 본다.
BACKUP_DIRS = _env_list("MONITOR_BACKUP_DIRS", "/root/backups,/var/backups/postgres")

# 용량을 따로 봐야 하는 폴더(업로드·영상은 여기가 차면 서비스가 멈춘다).
WATCH_DIRS = _env_list(
    "MONITOR_WATCH_DIRS",
    "/root/hs-portal/backend/uploads,/root/hs-portal/backend/media,/var/log",
)

SNAPSHOT_TTL = float(os.getenv("MONITOR_CACHE_SECONDS", "4"))
HISTORY_DAYS = int(os.getenv("MONITOR_HISTORY_DAYS", "30"))


# ─────────────────────────────────────────────────────────────────────────────
# 관문
# ─────────────────────────────────────────────────────────────────────────────

def require_monitor(
    x_monitor_token: str = Header(default=""),
    user: Optional[User] = Depends(get_current_user_optional),
) -> str:
    """토큰이 맞거나, 관리자로 로그인했거나."""
    want = (os.getenv("MONITOR_TOKEN", "") or "").strip()
    got = (x_monitor_token or "").strip()
    # want 가 비어 있을 때 got 도 비면 통과해 버리는 일이 없도록 both-empty 를 먼저 막는다.
    if want and got and _consteq(want, got):
        return "token"
    if user is not None and user.role == Role.admin:
        return "admin"
    raise HTTPException(status_code=401, detail="감시 토큰이 필요합니다.")


def _consteq(a: str, b: str) -> bool:
    """길이가 새어 나가도 상관없지만, 앞자리부터 맞춰 보는 비교는 피한다."""
    return hashlib.sha256(a.encode()).digest() == hashlib.sha256(b.encode()).digest()


# ─────────────────────────────────────────────────────────────────────────────
# 1. 시스템 — /proc 을 직접 읽는다
# ─────────────────────────────────────────────────────────────────────────────

_cpu_prev: Dict[str, float] = {}


def _read(path: str) -> str:
    try:
        with open(path, "r") as f:
            return f.read()
    except OSError:
        return ""


def cpu_percent() -> float:
    """/proc/stat 의 누적값 차이로 구한다.

    누적값이라 한 번만 읽어서는 못 낸다. 직전에 읽은 값과의 차이를 쓰고,
    첫 호출은 0 을 돌려준다(1분 표본이 도는 동안 곧 채워진다).
    """
    line = _read("/proc/stat").split("\n", 1)[0]
    if not line.startswith("cpu "):
        return 0.0
    parts = [float(x) for x in line.split()[1:]]
    idle = parts[3] + (parts[4] if len(parts) > 4 else 0.0)
    total = sum(parts)
    prev_total = _cpu_prev.get("total", 0.0)
    prev_idle = _cpu_prev.get("idle", 0.0)
    _cpu_prev["total"], _cpu_prev["idle"] = total, idle
    dt, di = total - prev_total, idle - prev_idle
    if prev_total <= 0 or dt <= 0:
        return 0.0
    return round(max(0.0, min(100.0, (1.0 - di / dt) * 100.0)), 1)


def _meminfo() -> Dict[str, int]:
    out: Dict[str, int] = {}
    for line in _read("/proc/meminfo").splitlines():
        k, _, rest = line.partition(":")
        try:
            out[k.strip()] = int(rest.split()[0])   # kB
        except (IndexError, ValueError):
            continue
    return out


def system_section() -> dict:
    mi = _meminfo()
    total = mi.get("MemTotal", 0)
    avail = mi.get("MemAvailable", mi.get("MemFree", 0))
    swap_total = mi.get("SwapTotal", 0)
    swap_free = mi.get("SwapFree", 0)

    load = (_read("/proc/loadavg") or "0 0 0").split()
    try:
        uptime_s = float((_read("/proc/uptime") or "0").split()[0])
    except (IndexError, ValueError):
        uptime_s = 0.0

    cores = os.cpu_count() or 1
    return {
        "hostname": socket.gethostname(),
        "cpu_percent": cpu_percent(),
        "cores": cores,
        "load1": _f(load[0] if load else 0),
        "load5": _f(load[1] if len(load) > 1 else 0),
        "load15": _f(load[2] if len(load) > 2 else 0),
        # 코어 수로 나눈 값. 1.0 을 넘으면 줄을 서고 있다는 뜻이라 이게 더 읽기 쉽다.
        "load_per_core": round(_f(load[0] if load else 0) / cores, 2),
        "mem_total_mb": total // 1024,
        "mem_used_mb": (total - avail) // 1024,
        "mem_percent": round((total - avail) / total * 100, 1) if total else 0.0,
        "swap_total_mb": swap_total // 1024,
        "swap_used_mb": (swap_total - swap_free) // 1024,
        "uptime_hours": round(uptime_s / 3600, 1),
        "booted_at": (datetime.now() - timedelta(seconds=uptime_s)).strftime("%Y-%m-%d %H:%M"),
        "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
# 2. 디스크 — 남은 용량보다 "며칠 남았나"가 쓸모 있다
# ─────────────────────────────────────────────────────────────────────────────

_du_cache: Dict[str, Tuple[float, int]] = {}


def _dir_size_mb(path: str, ttl: float = 600.0) -> Optional[int]:
    """폴더 용량. du 는 비싸므로 10분 캐시한다."""
    hit = _du_cache.get(path)
    now = time.time()
    if hit and now - hit[0] < ttl:
        return hit[1]
    if not os.path.isdir(path):
        return None
    try:
        out = subprocess.run(
            ["du", "-sm", "--", path],
            capture_output=True, text=True, timeout=20,
        ).stdout
        mb = int(out.split()[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None
    _du_cache[path] = (now, mb)
    return mb


def disk_section(db: Optional[Session] = None) -> dict:
    try:
        du = shutil.disk_usage("/")
    except OSError:
        return {"mounts": [], "watch": [], "days_left": None}

    used_mb = (du.total - du.free) // (1024 * 1024)
    total_mb = du.total // (1024 * 1024)
    percent = round((du.total - du.free) / du.total * 100, 1) if du.total else 0.0

    # 하루 전 표본과 비교해 증가 속도를 낸다. 표본이 없으면 아직 모른다고 답한다.
    days_left = None
    per_day_mb = None
    if db is not None:
        ago = datetime.utcnow() - timedelta(hours=24)
        old = (
            db.query(MonitorSample.disk_used_mb, MonitorSample.created_at)
            .filter(MonitorSample.created_at <= ago)
            .order_by(MonitorSample.created_at.desc())
            .first()
        )
        if old and old[0]:
            hours = max(1.0, (datetime.utcnow() - old[1]).total_seconds() / 3600)
            per_day_mb = round((used_mb - old[0]) / hours * 24)
            if per_day_mb > 0:
                days_left = int((du.free // (1024 * 1024)) / per_day_mb)

    watch = []
    for d in WATCH_DIRS:
        mb = _dir_size_mb(d)
        if mb is not None:
            watch.append({"path": d, "size_mb": mb})

    return {
        "total_mb": total_mb,
        "used_mb": used_mb,
        "free_mb": du.free // (1024 * 1024),
        "percent": percent,
        "growth_mb_per_day": per_day_mb,
        "days_left": days_left,
        "watch": sorted(watch, key=lambda x: -x["size_mb"]),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. nginx 접근 로그 — 접속자·트래픽·봇·보안 신호가 전부 여기서 나온다
# ─────────────────────────────────────────────────────────────────────────────

_MONTHS = {m: i for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), start=1)}

# combined 형식. 맨 뒤의 응답시간은 log_format 에 $request_time 을 넣었을 때만
# 붙는다. 없으면 없는 대로 돈다(그 경우 응답시간 통계만 비어 나온다).
_LINE = re.compile(
    r'^(\S+) \S+ \S+ \[([^\]]+)\] "(\S+) ([^"]*?)(?: HTTP/[^"]*)?" '
    r'(\d{3}) (\d+|-) "([^"]*)" "([^"]*)"(?:\s+(\d+\.\d+))?'
)

_BOT = re.compile(
    r"bot|crawl|spider|slurp|yeti|daum|facebookexternalhit|embedly|preview|"
    r"curl|wget|python-requests|httpx|okhttp|headless|monitor|uptime|scanner|"
    r"kakaotalk-scrap|whatsapp|go-http-client|axios|node-fetch|aiohttp|java/|"
    r"libwww|scrapy|zgrab|masscan|censys|expanse|nmap|nikto|sqlmap|nuclei|"
    r"l9explore|httpclient|palo alto",
    re.I,
)

# 브라우저로 페이지를 실제로 열었다는 흔적. **work-backend/app/visits.py 와 같은
# 규칙이어야 한다** — 업무 사이트 방문 통계와 이 화면의 접속자 수가 맞아야 한다.
#   nginx 가 없는 주소도 index.html 로 200 을 돌려주는 설정이라, 보안 스캐너가
#   /.env 같은 걸 찔러도 로그엔 정상 방문으로 남는다. 2026-09-15 서버 로그를 보니
#   기록해 하루 30명 중 29명이 그런 접근이었다. 사람의 브라우저는 화면을 그리려고
#   스크립트·스타일을 받아 가거나 API 를 부르므로, 그 흔적이 있는 사람만 센다.
_EVIDENCE = re.compile(
    r"\.(css|js|mjs|png|jpe?g|gif|svg|webp|avif|woff2?)(\?|$)", re.I)
_ASSET = re.compile(
    r"\.(css|js|mjs|png|jpe?g|gif|svg|webp|avif|ico|woff2?|ttf|eot|map|mp4|m4a|webm)(\?|$)",
    re.I,
)
_CRAWLERS = [
    ("Googlebot", re.compile(r"googlebot", re.I)),
    ("bingbot", re.compile(r"bingbot", re.I)),
    ("네이버(Yeti)", re.compile(r"yeti", re.I)),
    ("다음(Daum)", re.compile(r"daum", re.I)),
    ("AI 크롤러", re.compile(r"gptbot|claudebot|anthropic|perplexity|ccbot", re.I)),
]


def _parse_ts(s: str) -> Optional[datetime]:
    """'13/Sep/2026:05:44:01 +0900' → datetime(로컬).

    strptime 은 한 줄에 10µs 쯤 먹는다. 5만 줄이면 그것만으로 0.5초라
    자리를 알고 자르는 쪽으로 직접 짠다.
    """
    try:
        return datetime(
            int(s[7:11]), _MONTHS[s[3:6]], int(s[0:2]),
            int(s[12:14]), int(s[15:17]), int(s[18:20]),
        )
    except (ValueError, KeyError, IndexError):
        return None


def _log_files() -> List[str]:
    if LOG_PATHS:
        return [p for p in LOG_PATHS if os.path.isfile(p)]
    try:
        names = os.listdir(LOG_DIR)
    except OSError:
        return []
    out = []
    for n in names:
        # 회전된 .1 / .gz 는 안 읽는다. 우리가 보는 건 최근 1시간뿐이다.
        if "access" in n and n.endswith(".log"):
            out.append(os.path.join(LOG_DIR, n))
    return sorted(out)


def _tail_lines(path: str, nbytes: int) -> List[str]:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > nbytes:
                f.seek(size - nbytes)
                f.readline()          # 잘린 첫 줄은 버린다
            data = f.read()
    except OSError:
        return []
    return data.decode("utf-8", "replace").splitlines()


class _Hit:
    __slots__ = ("ts", "ip", "method", "path", "status", "bytes", "ref", "ua", "rt", "src")

    def __init__(self, ts, ip, method, path, status, nbytes, ref, ua, rt, src):
        self.ts, self.ip, self.method, self.path = ts, ip, method, path
        self.status, self.bytes, self.ref, self.ua, self.rt, self.src = (
            status, nbytes, ref, ua, rt, src
        )


def _collect_hits(minutes: int = 60) -> List[_Hit]:
    """최근 N분치 요청. 뒤에서부터 읽다가 시간이 지나면 멈춘다."""
    cutoff = datetime.now() - timedelta(minutes=minutes)
    hits: List[_Hit] = []
    for path in _log_files():
        src = site_of(path)
        for line in reversed(_tail_lines(path, LOG_TAIL_BYTES)):
            m = _LINE.match(line)
            if not m:
                continue
            ts = _parse_ts(m.group(2))
            if ts is None:
                continue
            if ts < cutoff:
                break                 # 로그는 시간 순이므로 여기서 끝
            hits.append(_Hit(
                ts, m.group(1), m.group(3), m.group(4), int(m.group(5)),
                int(m.group(6)) if m.group(6) != "-" else 0,
                m.group(7), m.group(8),
                float(m.group(9)) if m.group(9) else None,
                src,
            ))
    return hits


def _viewer_key(h: _Hit) -> str:
    """IP 를 그대로 들고 있지 않으려고 해시한다. 세는 데는 이걸로 충분하다."""
    return hashlib.sha1(f"{h.ip}|{h.ua}".encode()).hexdigest()[:16]


def _percentile(vals: List[float], p: float) -> Optional[float]:
    if not vals:
        return None
    vals = sorted(vals)
    i = min(len(vals) - 1, int(len(vals) * p))
    return round(vals[i], 3)


def _aggregate(hits: List[_Hit], now: datetime) -> dict:
    """요청 목록 하나를 지표 한 묶음으로 접는다.

    전체와 사이트별이 똑같은 모양이어야 화면에서 같은 자리에 끼워 넣을 수
    있다. 그래서 집계를 여기 한 곳에 두고 대상만 바꿔 부른다.
    """
    w5 = now - timedelta(minutes=5)
    w1 = now - timedelta(minutes=1)

    humans_5m, all_5m, humans_60m = set(), set(), set()
    confirmed = set()   # 브라우저 흔적이 있는 사람
    req_5m = req_1m = 0
    status_counts = Counter()
    bytes_60m = 0
    bot_req = 0
    paths = Counter()
    refs = Counter()
    crawlers = Counter()
    rts: List[float] = []
    recent_5xx: List[dict] = []

    for h in hits:
        is_bot = (not h.ua) or h.ua == "-" or bool(_BOT.search(h.ua))
        key = _viewer_key(h)
        status_counts[h.status // 100] += 1
        bytes_60m += h.bytes
        if is_bot:
            bot_req += 1
            for name, rx in _CRAWLERS:
                if rx.search(h.ua):
                    crawlers[name] += 1
                    break
        else:
            humans_60m.add(key)
            if h.status < 400 and (h.path.startswith("/api/") or _EVIDENCE.search(h.path)):
                confirmed.add(key)
            if not _ASSET.search(h.path):
                paths[h.path.split("?")[0]] += 1
        if h.rt is not None:
            rts.append(h.rt)
        if h.ref and "://" in h.ref and not _same_host(h.ref):
            refs[_host_of(h.ref)] += 1
        if h.status >= 500 and len(recent_5xx) < 20:
            recent_5xx.append({
                "at": h.ts.strftime("%H:%M:%S"),
                "status": h.status,
                "path": h.path[:120],
            })
        if h.ts >= w5:
            req_5m += 1
            all_5m.add(key)
            if not is_bot:
                humans_5m.add(key)
            if h.ts >= w1:
                req_1m += 1

    total = max(1, len(hits))
    return {
        # 이게 "현재 접속자". 최근 5분 안에 요청이 있었고, 최근 60분 안에 페이지를
        # 실제로 연 흔적이 있는 사람 수(봇·스캐너 제외).
        "visitors_now": len(humans_5m & confirmed),
        "visitors_now_including_bots": len(all_5m),
        "visitors_60m": len(humans_60m & confirmed),
        # 요청은 했지만 페이지를 연 흔적이 없어 뺀 사람(스캐너 등)
        "excluded_60m": len(humans_60m - confirmed),
        "requests_per_min_5m": round(req_5m / 5, 1),
        "requests_last_min": req_1m,
        "requests_60m": len(hits),
        "status": {
            "2xx": status_counts[2], "3xx": status_counts[3],
            "4xx": status_counts[4], "5xx": status_counts[5],
        },
        "error_rate_percent": round(status_counts[5] / total * 100, 2),
        "bandwidth_60m_mb": round(bytes_60m / 1024 / 1024, 1),
        "bot_percent": round(bot_req / total * 100, 1),
        "top_paths": [{"path": p, "hits": c} for p, c in paths.most_common(10)],
        "top_referrers": [{"host": r, "hits": c} for r, c in refs.most_common(8)],
        "crawlers": dict(crawlers),
        "response_time": {
            "p50": _percentile(rts, 0.50),
            "p95": _percentile(rts, 0.95),
            "p99": _percentile(rts, 0.99),
            "samples": len(rts),
        },
        "recent_5xx": recent_5xx,
    }


def traffic_section(hits: List[_Hit]) -> dict:
    """전체 + 사이트별.

    사이트를 가르는 근거는 **어느 로그 파일에서 나왔나** 하나뿐이다. nginx
    기본 combined 형식에는 어느 도메인으로 들어온 요청인지가 안 남기 때문에,
    사이트별로 access_log 를 따로 두지 않으면 전부 한 덩어리로 보인다.
    그래서 사이트가 하나로만 잡히면 화면에 그 사실을 알려 준다(needs_split).
    """
    now = datetime.now()
    out = _aggregate(hits, now)

    groups: Dict[str, List[_Hit]] = defaultdict(list)
    for h in hits:
        groups[h.src].append(h)

    # **조용한 사이트도 자리를 지킨다.** 트래픽이 0이라고 탭이 사라지면,
    # 한산한 건지 로그가 안 읽히는 건지 화면만 보고는 알 수가 없다. 그래서
    # 목록은 "요청이 있었던 곳"이 아니라 **"우리가 읽고 있는 로그"** 로 만든다.
    watching: List[str] = []
    for path in _log_files():
        label = site_of(path)
        if label not in watching:
            watching.append(label)

    # 설정에 적힌 순서를 먼저 두고, 거기 없는 것은 뒤에 붙인다. '기타'는 끝.
    seen = set(watching) | set(groups)
    order = [label for label in SITE_LABELS if label in seen]
    order += [k for k in watching if k not in order and k != SITE_OTHER]
    order += [k for k in groups if k not in order and k != SITE_OTHER]
    if SITE_OTHER in seen:
        order.append(SITE_OTHER)

    out["sites"] = {label: _aggregate(groups.get(label, []), now)
                    for label in order}
    out["site_order"] = order
    out["by_site"] = {label: len(groups[label]) for label in order}
    out["log_files"] = [os.path.basename(p) for p in _log_files()]
    # 로그가 한 파일뿐이면 사이트를 못 가른다. 위젯이 이걸 보고 안내를 띄운다.
    out["needs_split"] = len(out["log_files"]) <= 1
    return out


def _host_of(url: str) -> str:
    try:
        return url.split("://", 1)[1].split("/", 1)[0][:60]
    except IndexError:
        return url[:60]


_OWN_HOSTS = re.compile(
    os.getenv("MONITOR_OWN_HOSTS", r"ggm\.kr|localhost|127\.0\.0\.1"), re.I
)


def _same_host(url: str) -> bool:
    return bool(_OWN_HOSTS.search(_host_of(url)))


def security_section(hits: List[_Hit], db: Session) -> dict:
    """공격 신호. 대부분 nginx 로그만으로 나온다 — 새 표를 만들 필요가 없다."""
    login_fail = 0
    login_ok = 0
    not_found = Counter()
    suspicious = Counter()
    # 우리 사이트에 없는데 자꾸 찾는 경로 = 자동 스캐너.
    scan_rx = re.compile(r"(wp-|\.php|\.env|/admin\.|phpmyadmin|\.git|xmlrpc)", re.I)

    for h in hits:
        if h.path.startswith("/api/auth/login") and h.method == "POST":
            if h.status in (400, 401, 403):
                login_fail += 1
            elif h.status < 300:
                login_ok += 1
        if h.status == 404:
            not_found[h.ip] += 1
        if scan_rx.search(h.path):
            suspicious[h.ip] += 1

    since = datetime.utcnow() - timedelta(hours=24)
    try:
        admin_actions = (
            db.query(AdminAuditLog)
            .filter(AdminAuditLog.created_at >= since)
            .order_by(AdminAuditLog.created_at.desc())
            .limit(10)
            .all()
        )
        recent_admin = [{
            "at": a.created_at.strftime("%m-%d %H:%M") if a.created_at else "",
            "who": a.actor_email or "-",
            "what": a.action,
            "detail": (a.detail or "")[:60],
        } for a in admin_actions]
        admin_count = (
            db.query(func.count(AdminAuditLog.id))
            .filter(AdminAuditLog.created_at >= since).scalar() or 0
        )
    except Exception:
        recent_admin, admin_count = [], 0

    return {
        "login_failures_60m": login_fail,
        "login_success_60m": login_ok,
        # 실패가 성공보다 압도적이면 자동 대입 공격을 의심한다.
        "login_failure_ratio": round(login_fail / max(1, login_fail + login_ok) * 100, 1),
        "top_404_ips": [{"ip": _mask_ip(i), "hits": c} for i, c in not_found.most_common(5)],
        "scanner_ips": [{"ip": _mask_ip(i), "hits": c} for i, c in suspicious.most_common(5)],
        "admin_actions_24h": admin_count,
        "recent_admin_actions": recent_admin,
    }


def _mask_ip(ip: str) -> str:
    """화면에 띄우는 값이라 끝자리를 가린다. 차단은 서버 로그를 보고 한다."""
    parts = ip.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.{parts[2]}.x"
    return ip[:12] + "…"


# ─────────────────────────────────────────────────────────────────────────────
# 4. 서비스 생사 — systemctl 이 살았다고 해도 한 번은 찔러 본다
# ─────────────────────────────────────────────────────────────────────────────

def _run(cmd: List[str], timeout: float = 5.0) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (p.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _parallel(jobs, workers: int = 8):
    """짧은 외부 호출을 한꺼번에 돌린다.

    **왜 필요한가.** systemctl 5번 + 실제 요청 3번 + journalctl 5번을 차례로
    돌리면, 하나하나는 빨라도 타임아웃이 겹치는 순간 합이 수십 초가 된다.
    그 동안 감시 API 가 안 끝나고, 보는 쪽은 "서버가 죽었나" 하게 된다.
    전부 바깥을 기다리는 일이라 스레드로 겹쳐 두면 가장 느린 하나만큼만 걸린다.
    """
    jobs = list(jobs)
    if not jobs:
        return []
    with ThreadPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
        return list(pool.map(lambda f: f(), jobs))


def services_section() -> dict:
    def unit_job(u: str):
        def run():
            show = _run([
                "systemctl", "show", u,
                "-p", "ActiveState", "-p", "SubState", "-p", "NRestarts",
                "-p", "ActiveEnterTimestamp", "-p", "MemoryCurrent",
            ])
            kv = dict(
                line.split("=", 1) for line in show.splitlines() if "=" in line
            ) if show else {}
            mem = kv.get("MemoryCurrent", "")
            return {
                "unit": u,
                "state": kv.get("ActiveState", "unknown"),
                "sub": kv.get("SubState", ""),
                "restarts": int(kv.get("NRestarts", "0") or 0),
                "since": (kv.get("ActiveEnterTimestamp", "") or "")[:25],
                "mem_mb": int(mem) // (1024 * 1024) if mem.isdigit() else None,
                "ok": kv.get("ActiveState") == "active",
            }
        return run

    def probe_job(entry: str):
        name, _, url = entry.partition("=")

        def run():
            started = time.monotonic()
            code, err = _probe(url)
            return {
                "name": name,
                "url": url,
                "status": code,
                "ms": int((time.monotonic() - started) * 1000),
                "ok": code is not None and code < 500,
                "error": err,
            }
        return run

    units = _parallel(unit_job(u) for u in UNITS)
    probes = _parallel(probe_job(e) for e in PROBES if "=" in e)
    return {"units": units, "probes": probes}


def _probe(url: str, timeout: float = 2.5) -> Tuple[Optional[int], str]:
    """응답 코드만 본다. 본문은 안 읽는다 — 감시가 부하가 되면 안 된다."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "hs-monitor"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, ""
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:                      # 연결 거부·타임아웃 등
        return None, type(e).__name__


# ─────────────────────────────────────────────────────────────────────────────
# 5. 인증서 — certbot 타이머가 조용히 실패하는 일이 실제로 있다
# ─────────────────────────────────────────────────────────────────────────────

def ssl_section() -> List[dict]:
    out = []
    try:
        names = sorted(os.listdir(CERT_DIR))
    except OSError:
        return out
    for name in names:
        pem = os.path.join(CERT_DIR, name, "fullchain.pem")
        if not os.path.isfile(pem):
            continue
        raw = _run(["openssl", "x509", "-enddate", "-noout", "-in", pem])
        # notAfter=Dec  4 09:12:33 2026 GMT
        _, _, value = raw.partition("=")
        try:
            exp = datetime.strptime(value.strip(), "%b %d %H:%M:%S %Y %Z")
        except ValueError:
            continue
        days = (exp - datetime.utcnow()).days
        out.append({
            "domain": name,
            "expires_at": exp.strftime("%Y-%m-%d"),
            "days_left": days,
            "ok": days > 14,
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 6. 백업 — 언제부터 안 돌았는지는 보통 복구할 때 알게 된다
# ─────────────────────────────────────────────────────────────────────────────

def backup_section() -> dict:
    newest = None
    where = ""
    count = 0
    for d in BACKUP_DIRS:
        if not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            for fn in files:
                p = os.path.join(root, fn)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                count += 1
                if newest is None or st.st_mtime > newest[0]:
                    newest = (st.st_mtime, st.st_size, p)
                    where = d
            break                       # 한 단계만 본다
    if newest is None:
        return {"found": False, "dirs": BACKUP_DIRS,
                "note": "백업 폴더를 못 찾았다. MONITOR_BACKUP_DIRS 로 알려 주면 본다."}
    age_h = (time.time() - newest[0]) / 3600
    return {
        "found": True,
        "dir": where,
        "file": os.path.basename(newest[2]),
        "size_mb": round(newest[1] / 1024 / 1024, 1),
        "age_hours": round(age_h, 1),
        "at": datetime.fromtimestamp(newest[0]).strftime("%Y-%m-%d %H:%M"),
        "count": count,
        # 하루 한 번 도는 걸 전제로 본다.
        "ok": age_h < 30 and newest[1] > 1024,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 7. 에러 로그 — 같은 예외가 몇 번인지가 목록보다 중요하다
# ─────────────────────────────────────────────────────────────────────────────

# 예외 이름과 메시지. 파이썬 예외는 거의 이 모양으로 끝난다.
#   sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) table ...
_EXC = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Timeout|Warning|Interrupt))\s*:\s*(.*)")

# gunicorn/uvicorn 이 남기는 레벨 표시.
_LEVEL = re.compile(r"\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\]")

# **정상인데 무섭게 생긴 줄들.** 재시작할 때마다 워커 수만큼 쏟아진다.
#   이것들을 안 걸러내면 배포 한 번에 "에러 30줄"이 뜨고, 그걸 몇 번 보고 나면
#   에러 숫자를 아예 안 보게 된다. 진짜가 묻힌다.
_BENIGN = re.compile(
    r"was sent SIGTERM|Worker exiting|Shutting down|Handling signal|"
    r"Booting worker|Error while closing socket|Bad file descriptor|"
    r"Finished server process|Waiting for|Application startup|"
    r"connection is closed|ConnectionResetError|"
    r"GET /api/meta|/api/health|favicon",
    re.I,
)

# 트레이스백의 뼈대. 여기에 이름이 안 붙으므로 세지 않는다 —
# 맨 끝의 예외 한 줄만 세야 "같은 에러 n번"이 제대로 나온다.
_FRAME = re.compile(
    r"^\s*(Traceback \(most recent|File \"|The above exception|"
    r"During handling of|\.\.\.|\^+\s*$)"
)

_ERR_LEVEL = re.compile(r"\[(ERROR|CRITICAL)\]")


def errors_section(hours: int = 6) -> dict:
    """journalctl 에서 진짜 예외만 골라 같은 것끼리 묶는다."""
    groups: Counter = Counter()
    samples: Dict[str, str] = {}
    scanned = 0

    def journal_job(u: str):
        return lambda: (u, _run([
            "journalctl", "-u", u, "--since", f"-{hours}h",
            "--no-pager", "-n", "800", "-o", "cat",
        ], timeout=8.0))

    # 유닛마다 최대 8초다. 차례로 돌리면 다섯이면 40초까지 간다.
    for u, raw in _parallel(journal_job(u) for u in UNITS):
        for line in raw.splitlines():
            scanned += 1
            if _BENIGN.search(line):
                continue
            level = _LEVEL.search(line)
            if level and level.group(1) in ("DEBUG", "INFO"):
                continue            # 글자에 Error 가 있어도 INFO 는 에러가 아니다
            if _FRAME.match(line):
                continue            # 트레이스백 뼈대는 안 센다

            body = line.strip()
            exc = _EXC.match(body)
            if exc:
                # 숫자·주소처럼 매번 바뀌는 값을 지워야 같은 에러로 묶인다.
                sig = exc.group(1) + ": " + re.sub(r"0x[0-9a-f]+|\d+", "#", exc.group(2))[:90]
            elif _ERR_LEVEL.search(line):
                sig = re.sub(r"0x[0-9a-f]+|\d+", "#", body)[:110]
            else:
                continue            # 그 밖의 줄은 에러로 안 본다

            key = f"{u}|{sig}"
            groups[key] += 1
            samples.setdefault(key, body[:300])

    top = []
    for key, n in groups.most_common(8):
        unit, _, sig = key.partition("|")
        top.append({"unit": unit, "count": n, "sample": samples.get(key, sig)})
    return {
        "hours": hours,
        "total": sum(groups.values()),
        "scanned": scanned,
        "top": top,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 8. 데이터베이스
# ─────────────────────────────────────────────────────────────────────────────

def db_section(db: Session) -> dict:
    dialect = db.bind.dialect.name if db.bind is not None else "unknown"
    out: dict = {"dialect": dialect, "ok": True}
    started = time.monotonic()
    try:
        db.execute(text("SELECT 1"))
        out["ping_ms"] = int((time.monotonic() - started) * 1000)
    except Exception as e:
        return {"dialect": dialect, "ok": False, "error": type(e).__name__}

    if dialect != "postgresql":
        # 로컬 SQLite 에서는 아래 통계가 없다. 화면이 깨지지 않게 빈 값으로 둔다.
        out.update({"connections": None, "size_mb": None, "tables": [], "slow_queries": 0})
        return out

    def scalar(sql: str, default=None):
        try:
            return db.execute(text(sql)).scalar()
        except Exception:
            return default

    out["connections"] = scalar(
        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()", 0)
    out["max_connections"] = int(scalar("SHOW max_connections", 100) or 100)
    size = scalar("SELECT pg_database_size(current_database())", 0) or 0
    out["size_mb"] = round(size / 1024 / 1024, 1)
    # 5초 넘게 붙들고 있는 질의. 하나라도 있으면 어딘가 잠겨 있다는 신호다.
    out["slow_queries"] = scalar(
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE state = 'active' AND now() - query_start > interval '5 seconds'", 0)
    out["idle_in_transaction"] = scalar(
        "SELECT count(*) FROM pg_stat_activity WHERE state = 'idle in transaction'", 0)
    try:
        rows = db.execute(text(
            "SELECT relname, pg_total_relation_size(c.oid) AS bytes "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' "
            "ORDER BY bytes DESC LIMIT 8"
        )).fetchall()
        out["tables"] = [
            {"name": r[0], "size_mb": round((r[1] or 0) / 1024 / 1024, 1)} for r in rows
        ]
    except Exception:
        out["tables"] = []
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 9. 바깥에 기대고 있는 것들 — 우리가 멀쩡해도 이쪽이 끊기면 서비스는 멈춘다
# ─────────────────────────────────────────────────────────────────────────────

def deps_section(db: Session) -> dict:
    """바깥에 기대고 있는 것들.

    **안 쓰는 걸 "문제"라고 부르지 않는다.** 토스 결제나 LLM 키처럼 이 서버가
    원래 안 쓰는 것까지 경고로 띄우면, 경고가 늘 켜져 있는 상태가 된다.
    그러면 진짜 경고가 떴을 때도 똑같이 안 본다 — 경보를 없앤 것과 같다.

    그래서 **꼭 있어야 하는 것**(MONITOR_REQUIRED_DEPS)만 없을 때 경고하고,
    나머지는 "안 씀"으로 적어 두기만 한다. 쓰기 시작하면 목록에 넣으면 되고,
    그때부터는 키가 사라지면 바로 걸린다.
    """
    items = []

    def add(key: str, name: str, configured: bool, note: str,
            healthy: bool = True) -> None:
        required = key in REQUIRED_DEPS
        if not configured:
            items.append({
                "key": key, "name": name, "configured": False,
                "note": note or ("설정 없음" if required else "안 씀"),
                "ok": not required,
            })
            return
        items.append({"key": key, "name": name, "configured": True,
                      "note": note, "ok": healthy})

    # 문자/알림톡 — 휴대폰 본인확인이 여기에 걸려 있다.
    try:
        from . import sms as _sms
        add("sms", f"문자({_sms.provider()})", _sms.is_ready(),
            f"채널 {_sms.channel()}")
    except Exception:
        pass

    # 메일 — 문의 답변이 이걸로 나간다. 실패가 쌓이면 학교가 답을 못 받는다.
    try:
        from . import mailer as _mailer
        cfg = _mailer.system_config()
        since = datetime.utcnow() - timedelta(days=7)
        failed = (
            db.query(func.count(Inquiry.id))
            .filter(Inquiry.created_at >= since,
                    Inquiry.delivery_status == models.DeliveryStatus.failed)
            .scalar() or 0
        )
        add("mail", "메일(SMTP)", cfg.is_ready(),
            f"최근 7일 발송 실패 {failed}건", healthy=(failed == 0))
    except Exception:
        pass

    # 전화망 — mock 이면 실제로는 전화가 안 걸린다.
    try:
        from .phone import provider_name
        name = provider_name()
        since = datetime.utcnow() - timedelta(hours=24)
        calls = (
            db.query(func.count(CsCallLog.id))
            .filter(CsCallLog.created_at >= since).scalar() or 0
        )
        last = (
            db.query(CsCallLog.created_at)
            .order_by(CsCallLog.created_at.desc()).first()
        )
        add("phone", f"전화({name})", name != "mock",
            (f"24시간 수신 {calls}건"
             + (f" · 마지막 {last[0]:%m-%d %H:%M}" if last and last[0] else "")))
    except Exception:
        pass

    # 결제(토스) — 무통장입금만 쓰면 키가 없는 게 정상이다.
    toss_ready = bool((os.getenv("TOSS_SECRET_KEY", "") or "").strip())
    try:
        since = datetime.utcnow() - timedelta(days=7)
        paid = (
            db.query(func.count(SubscriptionOrder.id))
            .filter(SubscriptionOrder.paid_at >= since).scalar() or 0
        )
    except Exception:
        paid = 0
    add("toss", "결제(토스페이먼츠)", toss_ready, f"최근 7일 결제 {paid}건")

    # AI — 이 서버(UDJ)는 안 쓴다. 기록해 쪽 키는 diary-backend/.env 에 따로 있다.
    ai_keys = [k for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")
               if (os.getenv(k, "") or "").strip()]
    add("ai", "AI(LLM)", bool(ai_keys),
        ", ".join(k.split("_")[0] for k in ai_keys))

    return {"items": items, "required": sorted(REQUIRED_DEPS)}


# ─────────────────────────────────────────────────────────────────────────────
# 10. 오늘의 장사 — 서버가 멀쩡한 것과 서비스가 돌아가는 건 다른 얘기다
# ─────────────────────────────────────────────────────────────────────────────

def _kst_day_start_utc() -> datetime:
    """DB 시각은 UTC 로 쌓이는데 '오늘'은 한국 날짜여야 한다."""
    kst_now = datetime.utcnow() + timedelta(hours=9)
    kst_midnight = datetime(kst_now.year, kst_now.month, kst_now.day)
    return kst_midnight - timedelta(hours=9)


def business_section(db: Session) -> dict:
    today = _kst_day_start_utc()

    def count(model, field="created_at", since=today, **filters):
        try:
            q = db.query(func.count(model.id)).filter(getattr(model, field) >= since)
            for k, v in filters.items():
                q = q.filter(getattr(model, k) == v)
            return int(q.scalar() or 0)
        except Exception:
            return 0

    try:
        active_calls = int(
            db.query(func.count(CsCallSession.id))
            .filter(CsCallSession.state != "ENDED").scalar() or 0
        )
    except Exception:
        active_calls = 0
    try:
        pending_orders = int(
            db.query(func.count(PlanOrder.id))
            .filter(PlanOrder.status == models.OrderStatus.pending).scalar() or 0
        )
    except Exception:
        pending_orders = 0
    try:
        unanswered = int(
            db.query(func.count(Inquiry.id))
            .filter(Inquiry.status == models.InquiryStatus.pending).scalar() or 0
        )
    except Exception:
        unanswered = 0

    return {
        "signups_today": count(User),
        "inquiries_today": count(Inquiry),
        "quiz_today": count(QuizTaken),
        "calls_today": count(CsCallLog),
        "subscription_orders_today": count(SubscriptionOrder),
        "active_calls": active_calls,
        "pending_orders": pending_orders,
        "unanswered_inquiries": unanswered,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 11. 경보 — 보는 대시보드보다 울리는 알림이 실제로는 더 중요하다
# ─────────────────────────────────────────────────────────────────────────────

def build_alerts(snap: dict) -> List[dict]:
    """임계치를 넘은 것만 골라 낸다. 위젯은 이 목록만 보고 색을 정한다."""
    out: List[dict] = []

    def add(level: str, key: str, msg: str):
        out.append({"level": level, "key": key, "message": msg})

    for u in snap["services"]["units"]:
        if not u["ok"]:
            add("critical", "unit:" + u["unit"], f"{u['unit']} 가 죽었다 ({u['state']})")
        elif u["restarts"] >= 3:
            add("warn", "restart:" + u["unit"], f"{u['unit']} 가 {u['restarts']}번 재시작됐다")
    for p in snap["services"]["probes"]:
        if not p["ok"]:
            add("critical", "probe:" + p["name"],
                f"{p['name']} 응답 없음 ({p['error'] or p['status']})")
        elif p["ms"] > 2000:
            add("warn", "slow:" + p["name"], f"{p['name']} 응답이 {p['ms']}ms 로 느리다")

    d = snap["disk"]
    if d.get("percent", 0) >= 90:
        add("critical", "disk", f"디스크 {d['percent']}% — 곧 서비스가 멈춘다")
    elif d.get("percent", 0) >= 80:
        add("warn", "disk", f"디스크 {d['percent']}%")
    if d.get("days_left") is not None and d["days_left"] <= 7:
        add("warn", "disk_growth", f"이 속도면 디스크가 {d['days_left']}일 뒤 찬다")

    s = snap["system"]
    if s["mem_percent"] >= 92:
        add("warn", "mem", f"메모리 {s['mem_percent']}%")
    if s["load_per_core"] >= 2.0:
        add("warn", "load", f"부하 {s['load_per_core']}/코어 — 요청이 줄 서고 있다")

    t = snap["traffic"]
    if t["requests_60m"] >= 20 and t["error_rate_percent"] >= 5:
        add("critical", "5xx", f"서버 오류 {t['error_rate_percent']}% ({t['status']['5xx']}건)")
    elif t["status"]["5xx"] > 0:
        add("warn", "5xx", f"서버 오류 {t['status']['5xx']}건")

    for c in snap["ssl"]:
        if c["days_left"] <= 3:
            add("critical", "ssl:" + c["domain"],
                f"{c['domain']} 인증서 {c['days_left']}일 남음")
        elif c["days_left"] <= 14:
            add("warn", "ssl:" + c["domain"],
                f"{c['domain']} 인증서 {c['days_left']}일 남음")

    b = snap["backup"]
    if not b.get("found"):
        add("warn", "backup", "백업을 못 찾았다")
    elif not b.get("ok"):
        add("critical", "backup", f"백업이 {b['age_hours']}시간째 안 돌았다")

    dbi = snap["db"]
    if not dbi.get("ok"):
        add("critical", "db", "DB 에 붙지 못한다")
    else:
        conns, mx = dbi.get("connections"), dbi.get("max_connections")
        if conns and mx and conns > mx * 0.8:
            add("warn", "db_conn", f"DB 연결 {conns}/{mx}")
        if dbi.get("slow_queries"):
            add("warn", "db_slow", f"5초 넘는 질의 {dbi['slow_queries']}건")
        if dbi.get("idle_in_transaction") and dbi["idle_in_transaction"] >= 3:
            add("warn", "db_idle", f"열어 둔 트랜잭션 {dbi['idle_in_transaction']}건")

    sec = snap["security"]
    attempts = sec["login_failures_60m"] + sec["login_success_60m"]
    if attempts >= 20 and sec["login_failure_ratio"] >= 70:
        add("warn", "login", f"로그인 실패 {sec['login_failures_60m']}건 — 대입 공격 의심")
    if sec["scanner_ips"]:
        add("warn", "scanner", f"스캐너로 보이는 IP {len(sec['scanner_ips'])}곳")

    if snap["errors"]["total"] >= 50:
        add("warn", "errors",
            f"최근 {snap['errors']['hours']}시간 에러 {snap['errors']['total']}줄")

    for dep in snap["deps"]["items"]:
        if not dep["ok"]:
            add("warn", "dep:" + dep["name"], f"{dep['name']} — {dep['note']}")

    if snap["business"]["unanswered_inquiries"] >= 5:
        add("warn", "inquiry",
            f"답변 안 한 문의 {snap['business']['unanswered_inquiries']}건")

    return out


# ─────────────────────────────────────────────────────────────────────────────
# 12. 한 장으로 묶기
# ─────────────────────────────────────────────────────────────────────────────

_cache: Dict[str, object] = {"at": 0.0, "data": None}
_cache_lock = threading.Lock()


def collect(db: Session) -> dict:
    hits = _collect_hits(60)
    snap = {
        "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "system": system_section(),
        "disk": disk_section(db),
        "traffic": traffic_section(hits),
        "services": services_section(),
        "ssl": ssl_section(),
        "backup": backup_section(),
        "errors": errors_section(),
        "db": db_section(db),
        "deps": deps_section(db),
        "business": business_section(db),
        "security": security_section(hits, db),
    }
    snap["alerts"] = build_alerts(snap)
    snap["status"] = (
        "critical" if any(a["level"] == "critical" for a in snap["alerts"])
        else "warn" if snap["alerts"] else "ok"
    )
    snap["uptime"] = uptime_section(db)
    return snap


def cached_snapshot(db: Session) -> dict:
    """위젯이 1초마다 불러도 실제 수집은 SNAPSHOT_TTL 주기로만 돈다."""
    with _cache_lock:
        now = time.time()
        if _cache["data"] is not None and now - float(_cache["at"]) < SNAPSHOT_TTL:
            return _cache["data"]            # type: ignore[return-value]
        data = collect(db)
        _cache["at"], _cache["data"] = now, data
        return data


def uptime_section(db: Session) -> dict:
    """표본 중 '전부 살아 있었다'의 비율. 30일 가동률."""
    since = datetime.utcnow() - timedelta(days=30)
    try:
        total = int(db.query(func.count(MonitorSample.id))
                    .filter(MonitorSample.created_at >= since).scalar() or 0)
        up = int(db.query(func.count(MonitorSample.id))
                 .filter(MonitorSample.created_at >= since,
                         MonitorSample.all_up.is_(True)).scalar() or 0)
    except Exception:
        return {"samples": 0, "percent": None}
    if total == 0:
        return {"samples": 0, "percent": None}
    return {
        "samples": total,
        "percent": round(up / total * 100, 3),
        # 1분에 한 표본이므로 내려간 표본 수가 곧 분이다.
        "down_minutes": total - up,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 13. 표본 기록 — 그래프와 증가율은 전부 이 표에서 나온다
# ─────────────────────────────────────────────────────────────────────────────

SAMPLE_INTERVAL = int(os.getenv("MONITOR_SAMPLE_SECONDS", "60"))
_sampler_started = False


def take_sample() -> bool:
    """한 줄 남긴다. 이미 방금 누가 남겼으면 건너뛴다.

    워커 3개가 각자 타이머를 돌리므로 그냥 쓰면 1분에 3줄이 쌓인다.
    '마지막 표본이 충분히 오래됐을 때만 쓴다'로 막는다. 동시에 통과하는
    아주 짧은 창이 남지만, 그래프가 1분에 두 줄 되는 정도라 문제가 아니다.
    """
    db = SessionLocal()
    try:
        last = db.query(MonitorSample.created_at).order_by(
            MonitorSample.created_at.desc()).first()
        if last and last[0]:
            if (datetime.utcnow() - last[0]).total_seconds() < SAMPLE_INTERVAL * 0.9:
                return False
        snap = collect(db)
        sysv, disk, tr = snap["system"], snap["disk"], snap["traffic"]
        all_up = (
            all(u["ok"] for u in snap["services"]["units"])
            and all(p["ok"] for p in snap["services"]["probes"])
        )
        db.add(MonitorSample(
            cpu_percent=sysv["cpu_percent"],
            mem_percent=sysv["mem_percent"],
            disk_percent=disk.get("percent", 0.0),
            disk_used_mb=disk.get("used_mb", 0),
            load1=sysv["load1"],
            visitors_5m=tr["visitors_now"],
            requests_per_min=tr["requests_per_min_5m"],
            error_5xx=tr["status"]["5xx"],
            all_up=all_up,
            payload=json.dumps({
                "status": snap["status"],
                "alerts": [a["key"] for a in snap["alerts"]],
                "bandwidth_mb": tr["bandwidth_60m_mb"],
                "signups": snap["business"]["signups_today"],
                # 사이트별 접속자도 남긴다. 이게 있어야 그래프를 사이트마다
                # 따로 그릴 수 있다. 칸으로 빼지 않은 건 사이트가 늘거나
                # 이름이 바뀌어도 표를 안 고치기 위해서다.
                "sites": {k: v["visitors_now"] for k, v in tr["sites"].items()},
            }, ensure_ascii=False),
        ))
        db.commit()
        _purge_old(db)
        return True
    except Exception:
        db.rollback()
        return False
    finally:
        db.close()


_last_purge = [0.0]


def _purge_old(db: Session) -> None:
    """하루에 한 번만 지운다. 매 분 DELETE 를 날릴 이유가 없다."""
    now = time.time()
    if now - _last_purge[0] < 86400:
        return
    _last_purge[0] = now
    try:
        cutoff = datetime.utcnow() - timedelta(days=HISTORY_DAYS)
        db.query(MonitorSample).filter(MonitorSample.created_at < cutoff).delete()
        db.commit()
    except Exception:
        db.rollback()


def start_sampler() -> None:
    global _sampler_started
    if _sampler_started or os.getenv("MONITOR_SAMPLER", "1") == "0":
        return
    _sampler_started = True

    def loop():
        # 뜨자마자 세 워커가 한꺼번에 도는 걸 피하려고 조금 흩뜨린다.
        time.sleep(5 + (os.getpid() % 17))
        while True:
            try:
                take_sample()
            except Exception:
                pass
            time.sleep(SAMPLE_INTERVAL)

    threading.Thread(target=loop, name="monitor-sampler", daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────
# 14. 바깥으로 여는 자리
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/snapshot")
def snapshot(db: Session = Depends(get_db), who: str = Depends(require_monitor)):
    """지금 상태 전부. 바탕화면 위젯이 이것 하나만 부른다."""
    return cached_snapshot(db)


@router.get("/history")
def history(
    hours: int = 24,
    points: int = 120,
    db: Session = Depends(get_db),
    who: str = Depends(require_monitor),
):
    """그래프용 시계열. 화면 폭에 맞춰 points 개로 솎아서 준다."""
    hours = max(1, min(hours, HISTORY_DAYS * 24))
    points = max(10, min(points, 600))
    since = datetime.utcnow() - timedelta(hours=hours)
    rows = (
        db.query(MonitorSample)
        .filter(MonitorSample.created_at >= since)
        .order_by(MonitorSample.created_at.asc())
        .all()
    )
    step = max(1, len(rows) // points)
    out = []
    seen_sites: List[str] = []
    for r in rows[::step]:
        try:
            sites = (json.loads(r.payload or "{}") or {}).get("sites", {})
        except ValueError:
            sites = {}
        for k in sites:
            if k not in seen_sites:
                seen_sites.append(k)
        out.append({
            "at": (r.created_at + timedelta(hours=9)).strftime("%m-%d %H:%M"),
            "cpu": r.cpu_percent,
            "mem": r.mem_percent,
            "disk": r.disk_percent,
            "visitors": r.visitors_5m,
            "sites": sites,
            "rpm": r.requests_per_min,
            "err": r.error_5xx,
            "up": bool(r.all_up),
        })
    return {"hours": hours, "count": len(out), "sites": seen_sites, "points": out}


@router.get("/ping")
def ping(who: str = Depends(require_monitor)):
    """토큰이 맞는지만 확인하는 가벼운 자리. 위젯 설정 화면이 쓴다."""
    return {"ok": True, "as": who, "at": datetime.now().strftime("%H:%M:%S")}
