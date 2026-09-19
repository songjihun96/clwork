"""우리업무를 바탕화면 위젯처럼 띄운다.

브라우저를 **주소창·탭 없는 창**으로 열고 항상 위에 고정한다. 로그인은
브라우저가 기억하므로 한 번만 하면 된다.

감시 위젯과 달리 중간 서버가 없다 — 업무 시스템은 사람마다 로그인하는
구조라, 토큰을 대신 들고 있어 줄 필요가 없기 때문이다. 그래서 이 파일은
그냥 창을 띄우고 고정하는 일만 한다.

  설정: config.json 의 url 을 회사 주소로 바꾼다.
  실행: "업무위젯 열기.bat" 더블클릭
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULTS = {
    "url": "https://workwoori.ggm.kr",
    "width": 420,
    "height": 780,
    "x": 60,
    "y": 60,
    "always_on_top": True,
}

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def pin_on_top(title_part: str, seconds: float = 15.0) -> None:
    """그 창을 항상 위에 둔다. 브라우저에는 이런 설정이 없어서 윈도우에 직접 시킨다."""
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    HWND_TOPMOST, SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = -1, 0x0002, 0x0001, 0x0010
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def once() -> bool:
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

    end = time.time() + seconds
    while time.time() < end:
        if once():
            return
        time.sleep(0.5)


def main() -> int:
    cfg = load()
    exe = next((p for p in BROWSERS if os.path.isfile(p)), "")
    url = cfg["url"].rstrip("/") + "/?widget=1"

    if not exe:
        import webbrowser
        webbrowser.open(url)
        return 0

    # 전용 프로필을 준다. 안 주면 이미 떠 있는 브라우저가 요청을 가로채서
    # 그냥 새 탭으로 열고, 창 크기 지정도 무시된다.
    subprocess.Popen([
        exe, f"--app={url}",
        f"--user-data-dir={os.path.join(HERE, '.browser-profile')}",
        f"--window-size={cfg['width']},{cfg['height']}",
        f"--window-position={cfg['x']},{cfg['y']}",
        "--no-first-run", "--no-default-browser-check",
    ])
    if cfg.get("always_on_top", True) and sys.platform.startswith("win"):
        pin_on_top("우리 업무")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
