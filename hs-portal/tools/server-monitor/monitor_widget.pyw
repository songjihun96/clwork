"""바탕화면에 띄워 두는 서버 감시 위젯.

서버의 `/api/monitor/snapshot` 을 주기적으로 불러서 한 화면에 늘어놓는다.

**왜 파이썬 표준 라이브러리만 쓰나.** 이 파일은 사용자의 PC 에서 도는데,
pip install 이 하나라도 끼면 "실행이 안 된다"가 생긴다. tkinter·urllib·
winsound 는 파이썬을 깔면 그냥 있다. 그래픽도 Canvas 에 직접 그린다.

**왜 화면을 다시 그리지 않고 값만 바꾸나.** 위젯은 몇 초마다 갱신되므로
매번 위젯을 지웠다 만들면 눈에 보이게 깜빡인다. 만들 때 한 번 배치하고
이후에는 텍스트와 색만 갈아 끼운다.

**바깥에서 보는 감시라는 점이 중요하다.** 서버 안에 대시보드를 두면 서버가
죽었을 때 대시보드도 같이 죽어서 아무것도 안 보인다. 이 위젯은 내 PC 에서
도니까 서버가 안 뜨면 "못 닿음"이 그대로 화면에 남는다 — 그게 제일 중요한
신호다. 다만 PC 를 꺼 두면 못 보므로, 24시간 감시는 바깥 서비스
(UptimeRobot 등)를 하나 더 걸어 두는 게 맞다. README 참고.

실행:  monitor_widget.pyw 를 더블클릭 (콘솔 창이 안 뜨는 확장자다)
"""

from __future__ import annotations

import json
import os
import queue
import socket
import ssl
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
from tkinter import messagebox

try:
    import winsound
except ImportError:                     # 윈도우가 아니면 소리만 빠진다
    winsound = None

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")

DEFAULTS = {
    "url": "https://udjcs.ggm.kr",      # 백엔드가 붙어 있는 주소 아무 곳이나
    "token": "",
    "interval": 10,                     # 초
    "history_hours": 24,
    "alpha": 1.0,                       # 창 투명도 (0.5~1.0)
    "topmost": False,
    "compact": False,
    "sound": True,
    "x": 60,
    "y": 60,
    "scale": 1.0,
}

# ── 색 ───────────────────────────────────────────────────────────────────────
BG = "#11151c"
BG2 = "#171d27"
FG = "#e6edf3"
DIM = "#7d8899"
LINE = "#232b38"
OK = "#3fb950"
WARN = "#d29922"
CRIT = "#f85149"
ACCENT = "#58a6ff"

LEVEL_COLOR = {"ok": OK, "warn": WARN, "critical": CRIT, "offline": CRIT}


# ─────────────────────────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# 서버에 물어보기
# ─────────────────────────────────────────────────────────────────────────────

class Fetcher(threading.Thread):
    """한 박자마다 snapshot 을 가져와 큐에 넣는다.

    UI 스레드에서 직접 네트워크를 타면 서버가 느릴 때 창이 얼어붙는다.
    그래서 따로 돌리고, 결과만 큐로 넘긴다.
    """

    def __init__(self, cfg: dict, out: "queue.Queue"):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.out = out
        self.wake = threading.Event()
        self.stopped = False
        self._hist_at = 0.0

    def run(self) -> None:
        while not self.stopped:
            try:
                snap = self._get("/api/monitor/snapshot")
                self.out.put(("snapshot", snap))
                # 그래프는 자주 받을 이유가 없다. 1분에 한 번이면 충분하다.
                if time.time() - self._hist_at > 60:
                    hours = int(self.cfg.get("history_hours", 24))
                    hist = self._get(f"/api/monitor/history?hours={hours}&points=120")
                    self.out.put(("history", hist))
                    self._hist_at = time.time()
            except Exception as e:
                self.out.put(("error", _explain(e)))
            self.wake.wait(max(3, int(self.cfg.get("interval", 10))))
            self.wake.clear()

    def _get(self, path: str) -> dict:
        base = (self.cfg.get("url") or "").rstrip("/")
        req = urllib.request.Request(
            base + path,
            headers={
                "X-Monitor-Token": self.cfg.get("token", ""),
                "User-Agent": "hs-monitor-widget",
            },
        )
        # 사설 인증서를 쓰는 경우까지 막지는 않는다. 읽기 전용 감시라서.
        ctx = ssl.create_default_context()
        if self.cfg.get("insecure"):
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=12, context=ctx) as r:
            return json.loads(r.read().decode("utf-8"))


def _explain(e: Exception) -> str:
    if isinstance(e, urllib.error.HTTPError):
        if e.code == 401:
            return "토큰이 틀렸다 (설정에서 MONITOR_TOKEN 확인)"
        if e.code == 404:
            return "감시 API 가 없다 — 서버에 monitor.py 배포가 됐는지 확인"
        return f"HTTP {e.code}"
    if isinstance(e, urllib.error.URLError):
        return f"서버에 못 닿음 ({getattr(e.reason, 'strerror', e.reason)})"
    if isinstance(e, socket.timeout):
        return "응답이 없다 (타임아웃)"
    return f"{type(e).__name__}: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# 작은 부품들
# ─────────────────────────────────────────────────────────────────────────────

class Bar(tk.Canvas):
    """CPU·메모리·디스크처럼 0~100 을 보여 주는 가로 막대."""

    def __init__(self, master, width=120, height=8):
        super().__init__(master, width=width, height=height, bg=BG2,
                         highlightthickness=0, bd=0)
        self._cw, self._ch = width, height
        self.create_rectangle(0, 0, width, height, fill=LINE, outline="")
        self._fill = self.create_rectangle(0, 0, 0, height, fill=OK, outline="")

    def set(self, percent: float, warn=70.0, crit=88.0) -> None:
        p = max(0.0, min(100.0, float(percent or 0)))
        color = CRIT if p >= crit else WARN if p >= warn else OK
        self.coords(self._fill, 0, 0, self._cw * p / 100.0, self._ch)
        self.itemconfig(self._fill, fill=color)


class Spark(tk.Canvas):
    """작은 꺾은선. 축도 눈금도 없다 — 모양만 본다."""

    def __init__(self, master, width=330, height=46, color=ACCENT):
        super().__init__(master, width=width, height=height, bg=BG2,
                         highlightthickness=0, bd=0)
        self._cw, self._ch, self._color = width, height, color

    def set(self, values, down_flags=None) -> None:
        self.delete("all")
        vals = [float(v or 0) for v in (values or [])]
        if len(vals) < 2:
            self.create_text(self._cw / 2, self._ch / 2, text="표본을 모으는 중…",
                             fill=DIM, font=("Malgun Gothic", 8))
            return
        top = max(vals) or 1.0
        pad = 4
        h = self._ch - pad * 2
        step = self._cw / (len(vals) - 1)

        # 서비스가 내려가 있던 구간을 뒤에 붉게 깔아 둔다. 그래프의 골짜기가
        # 한산해서 그런 건지 죽어 있어서 그런 건지 구분이 된다.
        if down_flags:
            for i, down in enumerate(down_flags):
                if down:
                    x = i * step
                    self.create_rectangle(x, 0, x + step, self._ch,
                                          fill="#3d1418", outline="")

        pts = []
        for i, v in enumerate(vals):
            pts += [i * step, pad + h - (v / top) * h]
        self.create_line(*pts, fill=self._color, width=1.6, smooth=True)
        # 면적을 옅게 채우면 작은 크기에서 훨씬 읽기 쉽다.
        self.create_polygon(*(pts + [self._cw, self._ch, 0, self._ch]),
                            fill=self._color, outline="", stipple="gray25")
        self.create_text(self._cw - 3, 8, text=f"최고 {_num(top)}", anchor="e",
                         fill=DIM, font=("Malgun Gothic", 7))


def _num(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "-"
    if f >= 100:
        return f"{int(round(f)):,}"
    if f == int(f):
        return str(int(f))
    return f"{f:.1f}"


class Section(tk.Frame):
    """제목 한 줄 + 내용. 접을 수 있다."""

    def __init__(self, master, title: str, collapsed=False):
        super().__init__(master, bg=BG)
        self.title = title
        self._open = not collapsed

        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", pady=(9, 3))
        self._arrow = tk.Label(head, text="▾" if self._open else "▸", bg=BG,
                               fg=DIM, font=("Malgun Gothic", 7))
        self._arrow.pack(side="left")
        self._label = tk.Label(head, text=title, bg=BG, fg=DIM,
                               font=("Malgun Gothic", 8, "bold"))
        self._label.pack(side="left", padx=(3, 0))
        self._badge = tk.Label(head, text="", bg=BG, fg=DIM,
                               font=("Malgun Gothic", 8))
        self._badge.pack(side="right")

        self.body = tk.Frame(self, bg=BG)
        if self._open:
            self.body.pack(fill="x")

        for w in (head, self._arrow, self._label):
            w.bind("<Button-1>", self._toggle)

    def _toggle(self, _e=None):
        self._open = not self._open
        self._arrow.config(text="▾" if self._open else "▸")
        if self._open:
            self.body.pack(fill="x")
        else:
            self.body.forget()

    def badge(self, text: str, color: str = DIM):
        self._badge.config(text=text, fg=color)

    def rename(self, text: str):
        if text != self.title:
            self.title = text
            self._label.config(text=text)


def row(master, label: str):
    """왼쪽 라벨 / 오른쪽 값 한 줄. 값 라벨을 돌려준다."""
    f = tk.Frame(master, bg=BG)
    f.pack(fill="x", pady=1)
    tk.Label(f, text=label, bg=BG, fg=DIM, font=("Malgun Gothic", 8),
             anchor="w").pack(side="left")
    v = tk.Label(f, text="-", bg=BG, fg=FG, font=("Malgun Gothic", 8),
                 anchor="e")
    v.pack(side="right")
    return v


# ─────────────────────────────────────────────────────────────────────────────
# 창
# ─────────────────────────────────────────────────────────────────────────────

class Widget(tk.Tk):

    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.q: "queue.Queue" = queue.Queue()
        self.snap: dict | None = None
        self.hist: dict | None = None
        self.last_error: str = ""
        self.last_ok_at: float = 0.0
        self._known_alerts: set = set()
        self._sigs: dict = {}

        self.title("서버 감시")
        self.configure(bg=BG)
        self.overrideredirect(True)              # 제목 표시줄 없이
        self.attributes("-alpha", float(self.cfg.get("alpha", 0.94)))
        self.attributes("-topmost", bool(self.cfg.get("topmost", False)))
        self.geometry(f"+{int(self.cfg.get('x', 60))}+{int(self.cfg.get('y', 60))}")

        self._build()
        self._bind_drag()
        self._menu()

        self.fetcher = Fetcher(self.cfg, self.q)
        self.fetcher.start()
        self.after(200, self._drain)
        self.after(1000, self._tick)

        if not self.cfg.get("token"):
            self.after(400, self.open_settings)

    # ── 화면 만들기 ─────────────────────────────────────────────────────────

    def _build(self):
        wrap = tk.Frame(self, bg=BG, highlightbackground=LINE,
                        highlightthickness=1)
        wrap.pack(fill="both", expand=True)
        self.wrap = wrap

        # 머리말
        head = tk.Frame(wrap, bg=BG)
        head.pack(fill="x", padx=10, pady=(8, 0))
        self.head = head

        self.dot = tk.Canvas(head, width=10, height=10, bg=BG,
                             highlightthickness=0)
        self.dot_id = self.dot.create_oval(1, 1, 9, 9, fill=DIM, outline="")
        self.dot.pack(side="left")

        self.host_lbl = tk.Label(head, text="연결 중…", bg=BG, fg=FG,
                                 font=("Malgun Gothic", 9, "bold"))
        self.host_lbl.pack(side="left", padx=(6, 0))

        for text, cmd in (("✕", self.quit_all), ("⚙", self.open_settings),
                          ("▭", self.toggle_compact)):
            b = tk.Label(head, text=text, bg=BG, fg=DIM,
                         font=("Malgun Gothic", 9), cursor="hand2")
            b.pack(side="right", padx=3)
            b.bind("<Button-1>", lambda e, c=cmd: c())
            b.bind("<Enter>", lambda e, w=None: e.widget.config(fg=FG))
            b.bind("<Leave>", lambda e: e.widget.config(fg=DIM))

        self.stamp = tk.Label(wrap, text="", bg=BG, fg=DIM,
                              font=("Malgun Gothic", 7))
        self.stamp.pack(anchor="w", padx=10)

        # 제일 크게 보여 줄 숫자 — 지금 몇 명이 보고 있나
        hero = tk.Frame(wrap, bg=BG)
        hero.pack(fill="x", padx=10, pady=(6, 0))
        self.hero = hero
        left = tk.Frame(hero, bg=BG)
        left.pack(side="left")
        self.visitors = tk.Label(left, text="–", bg=BG, fg=ACCENT,
                                 font=("Malgun Gothic", 30, "bold"))
        self.visitors.pack(anchor="w")
        self.hero_cap = tk.Label(left, text="현재 접속자 (최근 5분)", bg=BG,
                                 fg=DIM, font=("Malgun Gothic", 8))
        self.hero_cap.pack(anchor="w")

        right = tk.Frame(hero, bg=BG)
        right.pack(side="right", anchor="s", pady=4)
        self.v60 = tk.Label(right, text="", bg=BG, fg=FG,
                            font=("Malgun Gothic", 8), anchor="e")
        self.v60.pack(anchor="e")
        self.rpm = tk.Label(right, text="", bg=BG, fg=DIM,
                            font=("Malgun Gothic", 8), anchor="e")
        self.rpm.pack(anchor="e")
        self.errl = tk.Label(right, text="", bg=BG, fg=DIM,
                             font=("Malgun Gothic", 8), anchor="e")
        self.errl.pack(anchor="e")

        # 사이트 전환. 두 서비스가 한 서버에 얹혀 있어서 숫자를 합쳐 놓으면
        # 어느 쪽이 오르내리는 건지 알 수가 없다.
        self.site_row = tk.Frame(wrap, bg=BG)
        self.site_row.pack(fill="x", padx=10, pady=(8, 0))
        self._site_chips = {}
        self.site = self.cfg.get("site", "전체")

        self.split_note = tk.Label(
            wrap, text="", bg=BG, fg=WARN, font=("Malgun Gothic", 7),
            anchor="w", wraplength=330, justify="left")

        self.spark = Spark(wrap)
        self.spark.pack(fill="x", padx=10, pady=(6, 2))
        self.spark_cap = tk.Label(wrap, text="접속자 추이", bg=BG, fg=DIM,
                                  font=("Malgun Gothic", 7))
        self.spark_cap.pack(anchor="w", padx=10)

        # 경보 — 접혀 있어도 항상 보인다
        self.alert_box = tk.Frame(wrap, bg=BG)
        self.alert_box.pack(fill="x", padx=10, pady=(4, 0))

        # 스크롤되는 본문
        body_wrap = tk.Frame(wrap, bg=BG)
        body_wrap.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.body_wrap = body_wrap
        canvas = tk.Canvas(body_wrap, bg=BG, highlightthickness=0,
                           width=340, height=360)
        canvas.pack(side="left", fill="both", expand=True)
        self.canvas = canvas
        inner = tk.Frame(canvas, bg=BG)
        self._inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(self._inner_id, width=e.width))
        self.bind_all("<MouseWheel>", self._wheel)

        self._build_sections(inner)

        if self.cfg.get("compact"):
            self.after(50, lambda: self._apply_compact(True))

    def _build_sections(self, p):
        # 1. 트래픽
        s = Section(p, "트래픽 (최근 60분)")
        s.pack(fill="x")
        self.sec_traffic = s
        self.t_req = row(s.body, "요청 수")
        self.t_status = row(s.body, "상태코드")
        self.t_err = row(s.body, "서버 오류율")
        self.t_bw = row(s.body, "전송량")
        self.t_bot = row(s.body, "봇 비율")
        self.t_rt = row(s.body, "응답시간 p50/p95")
        self.t_paths = self._list_frame(s.body, "많이 열린 곳")
        self.t_refs = self._list_frame(s.body, "유입 경로")
        self.t_crawl = self._list_frame(s.body, "검색엔진 크롤러")

        # 2. 서버
        s = Section(p, "서버")
        s.pack(fill="x")
        self.sec_sys = s
        self.g_cpu, self.b_cpu = self._gauge(s.body, "CPU")
        self.g_mem, self.b_mem = self._gauge(s.body, "메모리")
        self.g_disk, self.b_disk = self._gauge(s.body, "디스크")
        self.s_load = row(s.body, "부하 (코어당)")
        self.s_up = row(s.body, "가동 시간")

        # 3. 서비스
        s = Section(p, "서비스")
        s.pack(fill="x")
        self.sec_svc = s
        self.svc_frame = tk.Frame(s.body, bg=BG)
        self.svc_frame.pack(fill="x")

        # 4. 디스크·백업
        s = Section(p, "디스크 · 백업", collapsed=True)
        s.pack(fill="x")
        self.sec_disk = s
        self.d_free = row(s.body, "남은 용량")
        self.d_growth = row(s.body, "증가 속도")
        self.d_days = row(s.body, "이 속도면")
        self.d_watch = self._list_frame(s.body, "큰 폴더")
        self.bk_when = row(s.body, "마지막 백업")
        self.bk_size = row(s.body, "백업 크기")

        # 5. DB
        s = Section(p, "데이터베이스", collapsed=True)
        s.pack(fill="x")
        self.sec_db = s
        self.db_ping = row(s.body, "응답")
        self.db_conn = row(s.body, "연결 수")
        self.db_size = row(s.body, "용량")
        self.db_slow = row(s.body, "느린 질의")
        self.db_tables = self._list_frame(s.body, "큰 테이블")

        # 6. 인증서
        s = Section(p, "SSL 인증서", collapsed=True)
        s.pack(fill="x")
        self.sec_ssl = s
        self.ssl_frame = tk.Frame(s.body, bg=BG)
        self.ssl_frame.pack(fill="x")

        # 7. 외부 연동
        s = Section(p, "외부 연동", collapsed=True)
        s.pack(fill="x")
        self.sec_dep = s
        self.dep_frame = tk.Frame(s.body, bg=BG)
        self.dep_frame.pack(fill="x")

        # 8. 보안
        s = Section(p, "보안", collapsed=True)
        s.pack(fill="x")
        self.sec_sec = s
        self.sec_login = row(s.body, "로그인 실패/성공")
        self.sec_ratio = row(s.body, "실패 비율")
        self.sec_admin = row(s.body, "관리자 작업 24h")
        self.sec_scan = self._list_frame(s.body, "스캐너로 보이는 IP")
        self.sec_404 = self._list_frame(s.body, "404 많은 IP")

        # 9. 에러 로그
        s = Section(p, "에러 로그", collapsed=True)
        s.pack(fill="x")
        self.sec_err = s
        self.err_frame = tk.Frame(s.body, bg=BG)
        self.err_frame.pack(fill="x")

        # 10. 오늘
        s = Section(p, "오늘 · 우리동네 직업계고")
        s.pack(fill="x")
        self.sec_biz = s
        self.b_signup = row(s.body, "가입")
        self.b_quiz = row(s.body, "적성검사")
        self.b_inq = row(s.body, "문의")
        self.b_call = row(s.body, "통화")
        self.b_wait = row(s.body, "대기 중 (주문/미답변/통화)")

        # 11. 가동률
        s = Section(p, "가동률 (30일)", collapsed=True)
        s.pack(fill="x")
        self.up_pct = row(s.body, "가동률")
        self.up_down = row(s.body, "내려가 있던 시간")
        self.up_n = row(s.body, "표본")

    def _gauge(self, p, label):
        f = tk.Frame(p, bg=BG)
        f.pack(fill="x", pady=2)
        tk.Label(f, text=label, bg=BG, fg=DIM, font=("Malgun Gothic", 8),
                 width=6, anchor="w").pack(side="left")
        v = tk.Label(f, text="-", bg=BG, fg=FG, font=("Malgun Gothic", 8),
                     width=11, anchor="e")
        v.pack(side="right")
        bar = Bar(f, width=170)
        bar.pack(side="right", padx=6)
        return v, bar

    def _list_frame(self, p, title):
        tk.Label(p, text=title, bg=BG, fg=DIM,
                 font=("Malgun Gothic", 7)).pack(anchor="w", pady=(5, 0))
        f = tk.Frame(p, bg=BG)
        f.pack(fill="x")
        return f

    # ── 상호작용 ────────────────────────────────────────────────────────────

    def _bind_drag(self):
        def press(e):
            self._dx, self._dy = e.x_root - self.winfo_x(), e.y_root - self.winfo_y()

        def drag(e):
            self.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

        def release(_e):
            self.cfg["x"], self.cfg["y"] = self.winfo_x(), self.winfo_y()
            save_config(self.cfg)

        for w in (self.head, self.host_lbl, self.stamp, self.hero):
            w.bind("<Button-1>", press)
            w.bind("<B1-Motion>", drag)
            w.bind("<ButtonRelease-1>", release)

    def _menu(self):
        m = tk.Menu(self, tearoff=0, bg=BG2, fg=FG, activebackground=ACCENT,
                    activeforeground="#000", font=("Malgun Gothic", 9))
        m.add_command(label="지금 새로고침", command=self.refresh_now)
        m.add_separator()
        m.add_command(label="항상 위에 두기 켜기/끄기", command=self.toggle_topmost)
        m.add_command(label="작게/크게 보기", command=self.toggle_compact)
        m.add_command(label="소리 알림 켜기/끄기", command=self.toggle_sound)
        m.add_separator()
        m.add_command(label="설정…", command=self.open_settings)
        m.add_command(label="종료", command=self.quit_all)
        self.popup = m
        self.bind("<Button-3>", lambda e: m.tk_popup(e.x_root, e.y_root))
        self.bind("<F5>", lambda e: self.refresh_now())
        self.bind("<Escape>", lambda e: self.quit_all())

    def _wheel(self, e):
        self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")

    def refresh_now(self):
        self.fetcher.wake.set()

    def toggle_topmost(self):
        self.cfg["topmost"] = not self.cfg.get("topmost")
        self.attributes("-topmost", bool(self.cfg["topmost"]))
        save_config(self.cfg)

    def toggle_sound(self):
        self.cfg["sound"] = not self.cfg.get("sound", True)
        save_config(self.cfg)

    def toggle_compact(self):
        self.cfg["compact"] = not self.cfg.get("compact")
        self._apply_compact(self.cfg["compact"])
        save_config(self.cfg)

    def _apply_compact(self, on: bool):
        if on:
            self.body_wrap.forget()
            self.spark.forget()
            self.spark_cap.forget()
        else:
            self.spark.pack(fill="x", padx=10, pady=(6, 2), before=self.alert_box)
            self.spark_cap.pack(anchor="w", padx=10, before=self.alert_box)
            self.body_wrap.pack(fill="both", expand=True, padx=10, pady=(0, 8))

    def quit_all(self):
        self.fetcher.stopped = True
        self.cfg["x"], self.cfg["y"] = self.winfo_x(), self.winfo_y()
        save_config(self.cfg)
        self.destroy()
        sys.exit(0)

    # ── 설정 창 ─────────────────────────────────────────────────────────────

    def open_settings(self):
        win = tk.Toplevel(self, bg=BG)
        win.title("서버 감시 설정")
        win.configure(padx=14, pady=12)
        win.attributes("-topmost", True)
        fields = [
            ("서버 주소", "url", "예: https://udjcs.ggm.kr"),
            ("감시 토큰", "token", "서버 .env 의 MONITOR_TOKEN 과 같은 값"),
            ("갱신 주기(초)", "interval", "10 정도면 충분하다"),
            ("그래프 범위(시간)", "history_hours", "24"),
            ("투명도(0.5~1.0)", "alpha", "0.94"),
        ]
        entries = {}
        for i, (label, key, hint) in enumerate(fields):
            tk.Label(win, text=label, bg=BG, fg=FG,
                     font=("Malgun Gothic", 9)).grid(row=i * 2, column=0, sticky="w")
            e = tk.Entry(win, width=38, bg=BG2, fg=FG, insertbackground=FG,
                         relief="flat", font=("Malgun Gothic", 9))
            e.insert(0, str(self.cfg.get(key, "")))
            e.grid(row=i * 2, column=1, padx=(8, 0), pady=2)
            tk.Label(win, text=hint, bg=BG, fg=DIM,
                     font=("Malgun Gothic", 7)).grid(row=i * 2 + 1, column=1,
                                                     sticky="w", padx=(8, 0))
            entries[key] = e

        def test():
            cfg = dict(self.cfg)
            cfg["url"] = entries["url"].get().strip()
            cfg["token"] = entries["token"].get().strip()
            try:
                Fetcher(cfg, queue.Queue())._get("/api/monitor/ping")
                messagebox.showinfo("연결 확인", "잘 붙는다.", parent=win)
            except Exception as e:
                messagebox.showerror("연결 실패", _explain(e), parent=win)

        def save():
            self.cfg["url"] = entries["url"].get().strip()
            self.cfg["token"] = entries["token"].get().strip()
            for k, cast in (("interval", int), ("history_hours", int),
                            ("alpha", float)):
                try:
                    self.cfg[k] = cast(entries[k].get().strip())
                except ValueError:
                    pass
            self.attributes("-alpha", float(self.cfg.get("alpha", 0.94)))
            self.fetcher.cfg = self.cfg
            save_config(self.cfg)
            self.refresh_now()
            win.destroy()

        bar = tk.Frame(win, bg=BG)
        bar.grid(row=len(fields) * 2, column=1, sticky="e", pady=(10, 0))
        for text, cmd in (("연결 확인", test), ("저장", save)):
            tk.Button(bar, text=text, command=cmd, bg=BG2, fg=FG, relief="flat",
                      font=("Malgun Gothic", 9), padx=10).pack(side="left", padx=4)

    # ── 큐 비우기 / 시계 ────────────────────────────────────────────────────

    def _drain(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "snapshot":
                    self.snap = payload
                    self.last_error = ""
                    self.last_ok_at = time.time()
                    self._render()
                elif kind == "history":
                    self.hist = payload
                    self._render_spark()
                elif kind == "error":
                    self.last_error = payload
                    self._render_offline()
        except queue.Empty:
            pass
        self.after(200, self._drain)

    def _tick(self):
        """마지막으로 받은 지 얼마나 됐는지를 계속 보여 준다.

        숫자가 멈춰 있는 화면은 "조용한 것"과 "끊긴 것"이 똑같이 보인다.
        경과 시간을 같이 띄워야 그 둘이 구분된다.
        """
        if self.last_ok_at:
            ago = int(time.time() - self.last_ok_at)
            when = self.snap.get("collected_at", "")[-8:] if self.snap else ""
            self.stamp.config(
                text=f"{when} · {ago}초 전" + (f" · {self.last_error}" if self.last_error else ""),
                fg=CRIT if (self.last_error or ago > 120) else DIM,
            )
        self.after(1000, self._tick)

    # ── 그리기 ──────────────────────────────────────────────────────────────

    def _render_offline(self):
        self.dot.itemconfig(self.dot_id, fill=CRIT)
        self.host_lbl.config(text="서버에 못 닿음", fg=CRIT)
        self.visitors.config(text="–", fg=CRIT)
        self._render_alerts([{"level": "critical", "key": "offline",
                              "message": self.last_error or "연결 실패"}])

    def _pick(self, tr):
        """지금 고른 사이트의 지표. '전체'면 합쳐 놓은 쪽을 그대로 쓴다."""
        if self.site == "전체":
            return tr
        return (tr.get("sites") or {}).get(self.site) or tr

    def _render_site_tabs(self, tr):
        order = ["전체"] + list(tr.get("site_order") or [])
        if list(self._site_chips) != order:
            for w in self.site_row.winfo_children():
                w.destroy()
            self._site_chips = {}
            if self.site not in order:
                self.site = "전체"
            for label in order:
                f = tk.Frame(self.site_row, bg=BG2, highlightthickness=1,
                             highlightbackground=LINE, cursor="hand2")
                f.pack(side="left", padx=(0, 4))
                name = tk.Label(f, text=label, bg=BG2, fg=DIM,
                                font=("Malgun Gothic", 7))
                name.pack(padx=(6, 2), pady=(2, 0))
                num = tk.Label(f, text="-", bg=BG2, fg=FG,
                               font=("Malgun Gothic", 10, "bold"))
                num.pack(padx=6, pady=(0, 2))
                for w in (f, name, num):
                    w.bind("<Button-1>", lambda e, l=label: self._choose_site(l))
                self._site_chips[label] = (f, name, num)

        for label, (f, name, num) in self._site_chips.items():
            block = tr if label == "전체" else (tr.get("sites") or {}).get(label, {})
            num.config(text=str(block.get("visitors_now", 0)))
            on = (label == self.site)
            f.config(highlightbackground=ACCENT if on else LINE)
            name.config(fg=ACCENT if on else DIM)
            num.config(fg=FG if on else DIM)

        # 로그가 한 파일뿐이면 갈라 봐야 의미가 없다. 왜 그런지 알려 준다.
        if tr.get("needs_split"):
            self.split_note.config(
                text="사이트가 한 덩어리로 잡힌다 — nginx 설정에서 사이트마다 "
                     "access_log 를 따로 두면 나뉜다 (README 참고)")
            self.split_note.pack(fill="x", padx=10, pady=(3, 0),
                                 before=self.spark)
        else:
            self.split_note.forget()

    def _choose_site(self, label):
        self.site = label
        self.cfg["site"] = label
        save_config(self.cfg)
        self._render()
        self._render_spark()

    def _render(self):
        s = self.snap
        if not s:
            return
        status = s.get("status", "ok")
        color = LEVEL_COLOR.get(status, DIM)
        self.dot.itemconfig(self.dot_id, fill=color)
        self.host_lbl.config(text=s["system"].get("hostname", "서버"), fg=FG)

        tr_all = s["traffic"]
        self._render_site_tabs(tr_all)
        t = self._pick(tr_all)

        self.visitors.config(text=str(t["visitors_now"]), fg=color)
        self.hero_cap.config(
            text="현재 접속자 (최근 5분)" if self.site == "전체"
            else f"{self.site} · 현재 접속자 (최근 5분)")
        self.v60.config(text=f"60분 {t['visitors_60m']}명")
        self.rpm.config(text=f"분당 {t['requests_per_min_5m']}건")
        n5 = t["status"]["5xx"]
        self.errl.config(text=f"오류 {n5}건" if n5 else "오류 없음",
                         fg=CRIT if n5 else DIM)

        # 트래픽
        self.t_req.config(text=f"{t['requests_60m']:,}건")
        st = t["status"]
        self.t_status.config(
            text=f"2xx {st['2xx']:,} / 4xx {st['4xx']:,} / 5xx {st['5xx']:,}")
        self.t_err.config(text=f"{t['error_rate_percent']}%",
                          fg=CRIT if t["error_rate_percent"] >= 5 else FG)
        self.t_bw.config(text=f"{t['bandwidth_60m_mb']} MB")
        self.t_bot.config(text=f"{t['bot_percent']}%")
        rt = t["response_time"]
        self.t_rt.config(
            text=(f"{rt['p50']}s / {rt['p95']}s" if rt["p50"] is not None
                  else "nginx 로그에 시간 없음"))
        self._fill(self.t_paths, [(p["path"][:38], f"{p['hits']:,}")
                                 for p in t["top_paths"][:6]])
        self._fill(self.t_refs, [(r["host"][:30], f"{r['hits']:,}")
                                 for r in t["top_referrers"][:5]]
                   or [("(직접 유입만)", "")])
        self._fill(self.t_crawl, [(k, str(v)) for k, v in t["crawlers"].items()]
                   or [("최근 60분 방문 없음", "")])
        self.sec_traffic.badge(f"{t['requests_60m']:,}건")
        self.sec_traffic.rename(
            "트래픽 (최근 60분)" if self.site == "전체"
            else f"트래픽 · {self.site} (최근 60분)")

        # 서버
        sy = s["system"]
        self.g_cpu.config(text=f"{sy['cpu_percent']}%")
        self.b_cpu.set(sy["cpu_percent"])
        self.g_mem.config(text=f"{sy['mem_used_mb']:,}/{sy['mem_total_mb']:,}MB")
        self.b_mem.set(sy["mem_percent"])
        d = s["disk"]
        self.g_disk.config(text=f"{d.get('percent', 0)}%")
        self.b_disk.set(d.get("percent", 0), warn=75, crit=88)
        self.s_load.config(text=f"{sy['load_per_core']} ({sy['load1']} / {sy['cores']}코어)",
                           fg=WARN if sy["load_per_core"] >= 1 else FG)
        self.s_up.config(text=f"{sy['uptime_hours']}시간 · {sy['booted_at']} 부팅")
        self.sec_sys.badge(f"CPU {sy['cpu_percent']}% · 메모리 {sy['mem_percent']}%")

        # 서비스
        svc = s["services"]
        sig = json.dumps([(u["unit"], u["state"], u["restarts"]) for u in svc["units"]]
                         + [(p["name"], p["ok"]) for p in svc["probes"]])
        if self._sigs.get("svc") != sig:
            self._sigs["svc"] = sig
            for w in self.svc_frame.winfo_children():
                w.destroy()
            for u in svc["units"]:
                self._chip(self.svc_frame, u["unit"],
                           u["state"] + (f" · 재시작 {u['restarts']}회" if u["restarts"] else "")
                           + (f" · {u['mem_mb']}MB" if u.get("mem_mb") else ""),
                           OK if u["ok"] else CRIT)
            for p in svc["probes"]:
                self._chip(self.svc_frame, p["name"],
                           (f"{p['status']} · {p['ms']}ms" if p["status"]
                            else (p["error"] or "무응답")),
                           OK if p["ok"] else CRIT)
        down = sum(1 for u in svc["units"] if not u["ok"]) + \
            sum(1 for p in svc["probes"] if not p["ok"])
        self.sec_svc.badge("모두 정상" if not down else f"{down}개 내려감",
                           OK if not down else CRIT)

        # 디스크·백업
        self.d_free.config(text=f"{d.get('free_mb', 0):,}MB 남음 / {d.get('total_mb', 0):,}MB")
        g = d.get("growth_mb_per_day")
        self.d_growth.config(text=(f"하루 {g:+,}MB" if g is not None else "표본을 모으는 중"))
        dl = d.get("days_left")
        self.d_days.config(
            text=("여유 있음" if dl is None else f"{dl}일 뒤 가득 참"),
            fg=CRIT if (dl is not None and dl <= 7) else FG)
        self._fill(self.d_watch, [(w["path"].split("/")[-1] or w["path"],
                                   f"{w['size_mb']:,}MB") for w in d.get("watch", [])])
        b = s["backup"]
        if b.get("found"):
            self.bk_when.config(text=f"{b['at']} ({b['age_hours']}시간 전)",
                                fg=CRIT if not b["ok"] else FG)
            self.bk_size.config(text=f"{b['size_mb']}MB · {b['file'][:28]}")
        else:
            self.bk_when.config(text="못 찾음", fg=WARN)
            self.bk_size.config(text=b.get("note", "")[:34])
        self.sec_disk.badge(f"{d.get('percent', 0)}%",
                            CRIT if d.get("percent", 0) >= 88 else DIM)

        # DB
        db = s["db"]
        self.db_ping.config(text=(f"{db.get('ping_ms')}ms" if db.get("ok") else "연결 실패"),
                            fg=FG if db.get("ok") else CRIT)
        self.db_conn.config(text=(f"{db.get('connections')}/{db.get('max_connections')}"
                                  if db.get("connections") is not None else "-"))
        self.db_size.config(text=(f"{db.get('size_mb')}MB"
                                  if db.get("size_mb") is not None else "-"))
        self.db_slow.config(text=f"{db.get('slow_queries', 0)}건",
                            fg=WARN if db.get("slow_queries") else FG)
        self._fill(self.db_tables, [(x["name"][:28], f"{x['size_mb']}MB")
                                    for x in db.get("tables", [])])

        # SSL
        sig = json.dumps([(c["domain"], c["days_left"]) for c in s["ssl"]])
        if self._sigs.get("ssl") != sig:
            self._sigs["ssl"] = sig
            for w in self.ssl_frame.winfo_children():
                w.destroy()
            for c in s["ssl"]:
                self._chip(self.ssl_frame, c["domain"],
                           f"{c['days_left']}일 남음 · {c['expires_at']}",
                           OK if c["days_left"] > 14 else
                           (WARN if c["days_left"] > 3 else CRIT))
            if not s["ssl"]:
                self._chip(self.ssl_frame, "인증서 폴더를 못 읽음",
                           "MONITOR_CERT_DIR 확인", DIM)
        soon = min([c["days_left"] for c in s["ssl"]], default=None)
        self.sec_ssl.badge("" if soon is None else f"{soon}일",
                           CRIT if (soon is not None and soon <= 14) else DIM)

        # 외부 연동
        deps = s["deps"]["items"]
        sig = json.dumps([(x["name"], x["ok"], x["note"]) for x in deps], ensure_ascii=False)
        if self._sigs.get("dep") != sig:
            self._sigs["dep"] = sig
            for w in self.dep_frame.winfo_children():
                w.destroy()
            for x in deps:
                self._chip(self.dep_frame, x["name"], x["note"],
                           OK if x["ok"] else WARN)
        bad = sum(1 for x in deps if not x["ok"])
        self.sec_dep.badge("정상" if not bad else f"{bad}개 확인 필요",
                           OK if not bad else WARN)

        # 보안
        sec = s["security"]
        self.sec_login.config(
            text=f"{sec['login_failures_60m']} / {sec['login_success_60m']}")
        self.sec_ratio.config(
            text=f"{sec['login_failure_ratio']}%",
            fg=WARN if sec["login_failure_ratio"] >= 70 else FG)
        self.sec_admin.config(text=f"{sec['admin_actions_24h']}건")
        self._fill(self.sec_scan, [(x["ip"], f"{x['hits']}회")
                                   for x in sec["scanner_ips"]] or [("없음", "")])
        self._fill(self.sec_404, [(x["ip"], f"{x['hits']}회")
                                  for x in sec["top_404_ips"]] or [("없음", "")])

        # 에러 로그
        er = s["errors"]
        sig = json.dumps([(x["unit"], x["count"], x["sample"][:60]) for x in er["top"]],
                         ensure_ascii=False)
        if self._sigs.get("err") != sig:
            self._sigs["err"] = sig
            for w in self.err_frame.winfo_children():
                w.destroy()
            for x in er["top"]:
                self._chip(self.err_frame, f"{x['unit']} × {x['count']}",
                           x["sample"][:70], WARN)
            if not er["top"]:
                self._chip(self.err_frame, "최근 에러 없음", "", OK)
        self.sec_err.badge(f"{er['total']}줄 / {er['hours']}시간",
                           WARN if er["total"] >= 50 else DIM)

        # 오늘
        bz = s["business"]
        self.b_signup.config(text=f"{bz['signups_today']}명")
        self.b_quiz.config(text=f"{bz['quiz_today']}회")
        self.b_inq.config(text=f"{bz['inquiries_today']}건")
        self.b_call.config(text=f"{bz['calls_today']}통 (진행 중 {bz['active_calls']})")
        waiting = bz["pending_orders"] + bz["unanswered_inquiries"] + bz["active_calls"]
        self.b_wait.config(
            text=f"{bz['pending_orders']} / {bz['unanswered_inquiries']} / {bz['active_calls']}",
            fg=WARN if waiting else FG)

        # 가동률
        up = s["uptime"]
        self.up_pct.config(text=("표본 부족" if up.get("percent") is None
                                 else f"{up['percent']}%"))
        self.up_down.config(text=f"{up.get('down_minutes', 0)}분",
                            fg=CRIT if up.get("down_minutes") else FG)
        self.up_n.config(text=f"{up.get('samples', 0):,}개")

        self._render_alerts(s["alerts"])

    def _render_spark(self):
        pts = (self.hist or {}).get("points", [])
        if self.site == "전체":
            vals = [p["visitors"] for p in pts]
        else:
            vals = [(p.get("sites") or {}).get(self.site, 0) for p in pts]
        self.spark.set(vals, [not p["up"] for p in pts])
        if pts:
            who = "" if self.site == "전체" else f"{self.site} "
            self.spark_cap.config(
                text=f"{who}접속자 추이 · {pts[0]['at']} ~ {pts[-1]['at']}")

    def _render_alerts(self, alerts):
        sig = json.dumps([(a["level"], a["key"], a["message"]) for a in alerts],
                         ensure_ascii=False)
        if self._sigs.get("alerts") != sig:
            self._sigs["alerts"] = sig
            for w in self.alert_box.winfo_children():
                w.destroy()
            for a in alerts[:4]:
                c = LEVEL_COLOR.get(a["level"], WARN)
                f = tk.Frame(self.alert_box, bg=BG2, highlightbackground=c,
                             highlightthickness=1)
                f.pack(fill="x", pady=1)
                tk.Label(f, text=("■ " if a["level"] == "critical" else "▲ ") + a["message"],
                         bg=BG2, fg=c, font=("Malgun Gothic", 8), anchor="w",
                         wraplength=320, justify="left").pack(fill="x", padx=6, pady=2)
            if len(alerts) > 4:
                tk.Label(self.alert_box, text=f"그 밖에 {len(alerts) - 4}건", bg=BG,
                         fg=DIM, font=("Malgun Gothic", 7)).pack(anchor="w")

        # 처음 보는 심각 경보만 알린다. 같은 게 계속 떠 있다고 매번 울리면
        # 금방 무시하게 되고, 그때부터 알림은 없는 것과 같아진다.
        fresh = [a for a in alerts
                 if a["level"] == "critical" and a["key"] not in self._known_alerts]
        self._known_alerts = {a["key"] for a in alerts}
        if fresh:
            self._notify(fresh)

    def _notify(self, alerts):
        if self.cfg.get("sound", True) and winsound is not None:
            try:
                winsound.MessageBeep(winsound.MB_ICONHAND)
            except Exception:
                pass
        # 위젯이 다른 창에 가려 있어도 보이게 따로 띄운다.
        pop = tk.Toplevel(self, bg=CRIT)
        pop.overrideredirect(True)
        pop.attributes("-topmost", True)
        pop.attributes("-alpha", 0.97)
        body = tk.Frame(pop, bg="#2a0d10", padx=14, pady=10)
        body.pack(padx=2, pady=2)
        tk.Label(body, text="서버 경보", bg="#2a0d10", fg=CRIT,
                 font=("Malgun Gothic", 11, "bold")).pack(anchor="w")
        for a in alerts[:5]:
            tk.Label(body, text="· " + a["message"], bg="#2a0d10", fg=FG,
                     font=("Malgun Gothic", 9), anchor="w", wraplength=340,
                     justify="left").pack(anchor="w", pady=1)
        tk.Label(body, text="클릭하면 닫힘", bg="#2a0d10", fg=DIM,
                 font=("Malgun Gothic", 7)).pack(anchor="e", pady=(6, 0))
        pop.update_idletasks()
        sw, sh = pop.winfo_screenwidth(), pop.winfo_screenheight()
        pop.geometry(f"+{sw - pop.winfo_width() - 24}+{sh - pop.winfo_height() - 70}")
        pop.bind("<Button-1>", lambda e: pop.destroy())
        pop.after(20000, lambda: pop.winfo_exists() and pop.destroy())

    # ── 목록 채우기 ─────────────────────────────────────────────────────────

    def _fill(self, frame, pairs):
        sig = json.dumps(pairs, ensure_ascii=False)
        if self._sigs.get(id(frame)) == sig:
            return
        self._sigs[id(frame)] = sig
        for w in frame.winfo_children():
            w.destroy()
        for left, right in pairs:
            f = tk.Frame(frame, bg=BG)
            f.pack(fill="x")
            tk.Label(f, text=left, bg=BG, fg=FG, font=("Malgun Gothic", 8),
                     anchor="w").pack(side="left")
            tk.Label(f, text=right, bg=BG, fg=DIM, font=("Malgun Gothic", 8),
                     anchor="e").pack(side="right")

    def _chip(self, parent, title, note, color):
        f = tk.Frame(parent, bg=BG)
        f.pack(fill="x", pady=1)
        c = tk.Canvas(f, width=8, height=8, bg=BG, highlightthickness=0)
        c.create_oval(1, 1, 7, 7, fill=color, outline="")
        c.pack(side="left", pady=3)
        tk.Label(f, text=title, bg=BG, fg=FG, font=("Malgun Gothic", 8),
                 anchor="w").pack(side="left", padx=(5, 0))
        tk.Label(f, text=note, bg=BG, fg=DIM, font=("Malgun Gothic", 7),
                 anchor="e").pack(side="right")


def main():
    app = Widget()
    app.mainloop()


if __name__ == "__main__":
    main()
