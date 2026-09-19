"""교육 쇼츠 자동 생성기 — 실행 진입점.

사용법: python main.py
(패키징된 exe에서는 이 파일이 그대로 진입점이 된다. build_exe.md 참고.)
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main():
    from edu_shorts.gui import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
