"""브라우저로 보는 서버 감시 대시보드.

내 PC 에서 아주 작은 웹서버를 띄우고, 브라우저를 열어 준다. 그 웹서버가
실제 서버의 `/api/monitor/*` 를 대신 불러다 준다.

**왜 브라우저가 서버를 직접 안 부르나.** 두 가지 때문이다.

1. **CORS.** 로컬 파일(file://)이나 다른 출처의 페이지가 `udjcs.ggm.kr` 을
   직접 부르면 브라우저가 막는다. 서버에 CORS 허용을 추가할 수도 있지만,
   감시 하나 보자고 운영 서버의 접근 정책을 넓히는 건 맞바꾸기가 나쁘다.
2. **토큰.** 브라우저가 직접 부르려면 감시 토큰이 페이지 안에 들어가야 한다.
   지금 구조에서는 토큰이 `config.json` 에만 있고 브라우저는 구경도 못 한다.

그래서 중간에 한 겹을 둔다. 브라우저 ↔ 127.0.0.1 ↔ 서버.

**표준 라이브러리만 쓴다.** `http.server` 와 `urllib` 이면 충분하다. 차트도
SVG 로 직접 그리므로 설치할 것이 하나도 없다.

실행:  `대시보드 열기.bat` 더블클릭
"""

from __future__ import annotations

import json
import os
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")

DEFAULTS = {
    "url": "https://udjcs.ggm.kr",
    "token": "",
    "interval": 10,
    "history_hours": 24,
    "port": 8777,
}

# 정적 파일. 여기 없는 이름은 아예 안 읽는다 — 폴더를 통째로 여는 것보다
# 목록을 적어 두는 쪽이 실수할 여지가 없다.
STATIC = {
    "/": ("dashboard.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


CFG = load_config()


def fetch(path: str) -> tuple[int, bytes]:
    """진짜 서버에 물어본다. 토큰은 여기서만 붙는다."""
    base = (CFG.get("url") or "").rstrip("/")
    req = urllib.request.Request(
        base + path,
        headers={
            "X-Monitor-Token": CFG.get("token", ""),
            "User-Agent": "hs-monitor-dashboard",
        },
    )
    ctx = ssl.create_default_context()
    if CFG.get("insecure"):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, json.dumps({"error": explain(e)}).encode()
    except Exception as e:
        return 502, json.dumps({"error": explain(e)}).encode()


def explain(e: Exception) -> str:
    if isinstance(e, urllib.error.HTTPError):
        if e.code == 401:
            return "감시 토큰이 틀렸습니다 (설정에서 확인하세요)"
        if e.code == 404:
            return "서버에 감시 API 가 없습니다 — 배포가 됐는지 확인하세요"
        return f"서버가 HTTP {e.code} 로 답했습니다"
    if isinstance(e, urllib.error.URLError):
        return f"서버에 닿지 못했습니다 ({getattr(e.reason, 'strerror', e.reason)})"
    if isinstance(e, socket.timeout):
        return "서버가 제때 답하지 않았습니다"
    return f"{type(e).__name__}: {e}"


class Handler(BaseHTTPRequestHandler):
    server_version = "hs-monitor"

    def log_message(self, *_args):
        pass                      # 콘솔을 조용히 둔다

    # ── 안전장치 ────────────────────────────────────────────────────────────
    def _host_ok(self) -> bool:
        """DNS 리바인딩 방어.

        127.0.0.1 에만 묶어 놔도, 바깥 페이지가 자기 도메인을 127.0.0.1 로
        가리키게 만들면 브라우저는 그걸 '같은 출처'로 착각한다. Host 머리글을
        확인하면 그 길이 막힌다.
        """
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost", "[::1]", "::1")

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # 다른 사이트가 이 응답을 읽어 가지 못하게 한다(CORS 머리글을 안 준다).
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass                  # 브라우저가 먼저 닫은 것뿐이다

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")

    # ── 라우팅 ──────────────────────────────────────────────────────────────
    def do_GET(self):
        if not self._host_ok():
            self._send(403, b"forbidden", "text/plain")
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in STATIC:
            name, ctype = STATIC[path]
            try:
                with open(os.path.join(HERE, name), "rb") as f:
                    self._send(200, f.read(), ctype)
            except OSError:
                self._send(404, f"{name} 없음".encode(), "text/plain; charset=utf-8")
            return

        if path == "/api/config":
            # 토큰은 안 내보낸다. 화면이 알아야 하는 것만.
            self._json(200, {
                "url": CFG.get("url", ""),
                "interval": int(CFG.get("interval", 10)),
                "history_hours": int(CFG.get("history_hours", 24)),
                "configured": bool(CFG.get("token")),
            })
            return

        if path == "/api/snapshot":
            code, body = fetch("/api/monitor/snapshot")
            self._send(code, body, "application/json; charset=utf-8")
            return

        if path == "/api/history":
            q = urllib.parse.parse_qs(parsed.query)
            hours = int((q.get("hours") or ["24"])[0])
            points = int((q.get("points") or ["180"])[0])
            code, body = fetch(f"/api/monitor/history?hours={hours}&points={points}")
            self._send(code, body, "application/json; charset=utf-8")
            return

        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if not self._host_ok():
            self._send(403, b"forbidden", "text/plain")
            return
        if urllib.parse.urlparse(self.path).path != "/api/config":
            self._send(404, b"not found", "text/plain")
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, OSError):
            self._json(400, {"error": "읽을 수 없는 요청"})
            return

        for key in ("url", "token"):
            if key in data:
                CFG[key] = str(data[key]).strip()
        for key in ("interval", "history_hours"):
            if key in data:
                try:
                    CFG[key] = int(data[key])
                except (TypeError, ValueError):
                    pass
        try:
            save_config(CFG)
        except OSError as e:
            self._json(500, {"error": f"설정을 저장하지 못했습니다: {e}"})
            return

        code, body = fetch("/api/monitor/ping")
        ok = code == 200
        self._json(200, {
            "saved": True, "ok": ok,
            "message": "잘 붙습니다." if ok else json.loads(body or b"{}").get(
                "error", f"HTTP {code}"),
        })


# ─────────────────────────────────────────────────────────────────────────────
# 위젯처럼 띄우기
# ─────────────────────────────────────────────────────────────────────────────

EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def find_browser() -> str:
    """앱 창을 띄울 수 있는 브라우저. 윈도우에는 Edge 가 항상 있다."""
    for p in EDGE_PATHS + CHROME_PATHS:
        if os.path.isfile(p):
            return p
    return ""


def open_widget(url: str) -> bool:
    """주소창·탭 없는 창으로 연다.

    `--app=` 로 열면 브라우저 껍데기가 사라져서 작은 프로그램처럼 보인다.
    `--user-data-dir` 을 따로 주는 게 중요하다 — 안 주면 이미 떠 있는
    브라우저가 요청을 가로채서 그냥 새 탭으로 열어 버리고, 창 크기 지정도
    무시된다.
    """
    exe = find_browser()
    if not exe:
        return False
    profile = os.path.join(HERE, ".browser-profile")
    w = int(CFG.get("widget_width", 430))
    h = int(CFG.get("widget_height", 860))
    x = int(CFG.get("widget_x", 60))
    y = int(CFG.get("widget_y", 60))
    try:
        import subprocess
        subprocess.Popen([
            exe,
            f"--app={url}?widget=1",
            f"--user-data-dir={profile}",
            f"--window-size={w},{h}",
            f"--window-position={x},{y}",
            "--no-first-run",
            "--no-default-browser-check",
        ])
        return True
    except OSError:
        return False


def pin_on_top(title_part: str = "서버 감시", seconds: float = 12.0) -> None:
    """그 창을 항상 위에 둔다.

    브라우저 자체에는 이런 설정이 없어서 윈도우에 직접 시킨다. 창이 뜨는 데
    시간이 걸리므로 잠깐 동안 찾아본다.
    """
    if not sys.platform.startswith("win") or not CFG.get("always_on_top", True):
        return
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return

    user32 = ctypes.windll.user32
    HWND_TOPMOST, SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = -1, 0x0002, 0x0001, 0x0010
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def find_and_pin() -> bool:
        found = []

        def each(hwnd, _lp):
            if not user32.IsWindowVisible(hwnd):
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if title_part in buf.value:
                found.append(hwnd)
                return False
            return True

        user32.EnumWindows(CB(each), 0)
        if not found:
            return False
        user32.SetWindowPos(found[0], HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        return True

    deadline = time.time() + seconds
    while time.time() < deadline:
        if find_and_pin():
            return
        time.sleep(0.5)


def free_port(start: int) -> int:
    """이미 쓰는 포트면 옆으로 비켜 준다. 두 번 띄워도 안 죽게."""
    for port in range(start, start + 20):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


def main() -> None:
    widget_mode = "--widget" in sys.argv
    port = free_port(int(CFG.get("port", 8777)))
    # 127.0.0.1 에만 묶는다. 같은 공유기 안의 다른 기기도 못 본다.
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"

    def launch():
        time.sleep(0.4)
        if widget_mode and open_widget(url):
            pin_on_top()
        else:
            webbrowser.open(url + ("?widget=1" if widget_mode else ""))

    threading.Thread(target=launch, daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
