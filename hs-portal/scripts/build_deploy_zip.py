"""배포 zip 을 만든다. **비밀 파일이 한 개라도 섞이면 만들지 않는다.**

**왜 이 파일이 생겼나.** 2026-09-13, 손으로 만든 zip 에 로컬
`backend/.env` 가 딸려 들어갔고, 서버에서 `unzip -o` 가 운영 `.env` 를
덮어썼다. 로컬 `.env` 에는 `DATABASE_URL` 이 없어서 백엔드가 PostgreSQL
대신 빈 SQLite 로 떨어졌고, 사이트가 "학교 0개교" 로 보였다. DB 자체는
멀쩡했지만 운영 비밀값이 통째로 날아갈 뻔했다.

원인은 단순하다 — 빼는 목록(`.venv`, `__pycache__`, `*.db`)에 **점으로
시작하는 파일이 없었다.** 사람이 매번 기억해야 하는 목록은 언젠가 빠진다.
그래서 규칙을 코드로 옮기고, **담은 뒤에 다시 열어서 검사**한다. 검사에
걸리면 zip 을 지우고 실패로 끝낸다 — 반쯤 맞는 zip 을 남기는 쪽이 더
위험하다.

쓰기:
    python scripts/build_deploy_zip.py                  # hs-portal.zip (UDJ 백엔드)
    python scripts/build_deploy_zip.py --target work    # workwoori.zip (업무 시스템)
    python scripts/build_deploy_zip.py --include diary-backend
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 통째로 빼는 폴더.
SKIP_DIRS = {
    ".venv", "venv", "node_modules", "__pycache__", ".git", ".pytest_cache",
    "uploads", "media", ".mypy_cache", ".ruff_cache",
}

# 빼는 파일. 점으로 시작하는 건 전부 뺀다 — .env 가 여기에 걸린다.
SKIP_FILE_RE = re.compile(
    r"^\.|\.(db|db-journal|db-wal|db-shm|pyc|pyo|log|zip|sqlite3?)$", re.I
)

# 담긴 뒤에 다시 열어서 하나라도 걸리면 실패시킨다.
# 위의 SKIP 규칙과 일부러 겹쳐 둔다. 규칙을 고치다 실수해도 이 그물에 걸린다.
FORBIDDEN_RE = re.compile(
    r"(^|/)\.env|(^|/)\.git/|secret|credential|id_rsa|\.pem$|\.key$|\.db$",
    re.I,
)
# 이름에 secret/key 가 들어가도 괜찮은 것들(예제·설정 견본).
FORBIDDEN_OK = re.compile(r"env\.example$|\.env\.example$", re.I)


def collect(base: Path, prefix: str) -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in sorted(files):
            if SKIP_FILE_RE.search(f):
                continue
            p = Path(root) / f
            arc = prefix + "/" + str(p.relative_to(base)).replace("\\", "/")
            out.append((p, arc))
    return out


# 무엇을 담을지. 서비스마다 zip 을 따로 만든다 —
# 업무 시스템을 고쳤다고 우리동네 직업계고 백엔드까지 덮어쓸 이유가 없다.
TARGETS = {
    # 우리동네 직업계고·기록해·상담 백엔드
    "portal": {
        "out": "hs-portal.zip",
        "trees": [("backend", "backend")],
        "files": [("deploy/env.example", "deploy/env.example")],
        "must": ["backend/app/callcenter/__init__.py",
                 "backend/app/phone/__init__.py",
                 "backend/requirements.txt"],
    },
    # 서버에 올라가는 것 전부. 백엔드 넷 + 화면 다섯(빌드 결과) + 배포 설정.
    # PC 에서만 쓰는 tools/, 문서(manuals/, docs/)는 뺀다.
    # **전부 덮어쓰므로**, 서버에서 직접 고친 파일이 있으면 그게 사라진다.
    "full": {
        "out": "hs-portal.zip",
        "trees": [("backend", "backend"),
                  ("diary-backend", "diary-backend"),
                  ("research-backend", "research-backend"),
                  ("work-backend", "work-backend"),
                  ("frontend/dist", "frontend/dist"),
                  ("frontend-cs/dist", "frontend-cs/dist"),
                  ("frontend-journal/dist", "frontend-journal/dist"),
                  ("frontend-research/dist", "frontend-research/dist"),
                  ("frontend-work", "frontend-work"),
                  ("deploy", "deploy"),
                  ("scripts", "scripts")],
        "files": [],
        "must": ["backend/app/callcenter/__init__.py", "backend/app/phone/__init__.py",
                 "backend/requirements.txt", "backend/app/monitor.py",
                 "diary-backend/app/main.py", "diary-backend/requirements.txt",
                 "research-backend/app/main.py", "research-backend/requirements.txt",
                 "work-backend/app/main.py", "work-backend/app/settlement.py",
                 "work-backend/app/payroll.py", "frontend-work/payroll.js",
                 "frontend/dist/index.html", "frontend-cs/dist/index.html",
                 "frontend-journal/dist/index.html", "frontend-research/dist/index.html",
                 "frontend-work/index.html", "frontend-work/settlement.js",
                 "deploy/work-backend.service", "deploy/nginx-work.conf"],
    },
    # 우리업무 (workwoori.ggm.kr) — 별도 프로세스라 이 안에 다 들어 있다.
    "work": {
        "out": "workwoori.zip",
        "trees": [("work-backend", "work-backend"),
                  ("frontend-work", "frontend-work")],
        "files": [("deploy/nginx-work.conf", "deploy/nginx-work.conf"),
                  ("deploy/work-backend.service", "deploy/work-backend.service")],
        # 점으로 시작하면 담기 전에 걸러지므로(.env 사고 방지 규칙) 견본은
        # 점 없는 이름으로 두고, 서버에서 .env 로 복사해 쓴다.
        "must": ["work-backend/app/main.py", "work-backend/app/work.py",
                 "work-backend/app/models.py", "work-backend/app/visits.py",
                 "work-backend/app/settlement.py", "frontend-work/settlement.js",
                 "work-backend/app/payroll.py", "frontend-work/payroll.js",
                 "work-backend/env.example",
                 "frontend-work/index.html", "frontend-work/visits.js"],
    },
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=sorted(TARGETS), default="portal")
    ap.add_argument("--out", default="")
    ap.add_argument("--include", action="append", default=[],
                    help="추가로 담을 최상위 폴더")
    args = ap.parse_args()
    spec = TARGETS[args.target]

    items: list[tuple[Path, str]] = []
    for src, prefix in spec["trees"]:
        d = ROOT / src
        if not d.is_dir():
            print(f"없는 폴더: {src}", file=sys.stderr)
            return 2
        items += collect(d, prefix)
    for name in args.include:
        d = ROOT / name
        if not d.is_dir():
            print(f"없는 폴더: {name}", file=sys.stderr)
            return 2
        items += collect(d, name)
    for src, arc in spec["files"]:
        p = ROOT / src
        if p.is_file():
            items.append((p, arc))

    args.out = args.out or str(ROOT.parent / spec["out"])
    out = Path(args.out)
    # mkstemp 는 열린 파일 서술자를 같이 준다. 윈도에서는 그걸 안 닫으면
    # 파일이 잠겨 있어서 마지막에 옮기지를 못한다.
    _fd, _tmp_name = tempfile.mkstemp(suffix=".zip")
    os.close(_fd)
    tmp = Path(_tmp_name)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for src, arc in items:
            z.write(src, arc)

    # ── 담은 것을 다시 열어서 검사한다 ──────────────────────────────────────
    names = zipfile.ZipFile(tmp).namelist()
    bad = [n for n in names
           if FORBIDDEN_RE.search(n) and not FORBIDDEN_OK.search(n)]
    if bad:
        tmp.unlink(missing_ok=True)
        print("zip 을 만들지 않았다. 들어가면 안 되는 파일이 있다:", file=sys.stderr)
        for n in bad:
            print("   ", n, file=sys.stderr)
        return 1

    # 파이썬 패키지가 통째로 빠지지 않았는지 본다. 예전에 app/callcenter 가
    # 빠진 zip 이 나가서 서비스가 ImportError 로 죽은 적이 있다.
    for pkg in spec["must"]:
        if pkg not in names:
            tmp.unlink(missing_ok=True)
            print(f"zip 을 만들지 않았다. 빠진 파일: {pkg}", file=sys.stderr)
            return 1

    shutil.move(str(tmp), str(out))
    size_kb = out.stat().st_size / 1024
    print(f"만들었다: {out}")
    print(f"  파일 {len(names)}개 / {size_kb:,.1f} KB")
    print(f"  검사 통과: .env·비밀키 없음, 패키지 누락 없음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
