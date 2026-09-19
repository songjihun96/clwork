"""서버에 올릴 hs-portal.zip 을 만든다.

    python scripts/build_zip.py                # 저장소 바로 위에 hs-portal.zip
    python scripts/build_zip.py --out D:/a.zip # 자리 지정
    python scripts/build_zip.py --skip-boot-test

서버는 git 이 없어 zip 을 풀어 배포한다. 그래서 zip 이 곧 배포 그 자체이고,
빠진 파일 하나가 서비스를 세운다.

실제로 한 번 세웠다. 예전에는 `cp backend/app/*.py` 처럼 파일을 골라 담았는데,
그 방식이 `app/callcenter/` · `app/phone/` **폴더를 통째로** 빠뜨렸다.
main.py 가 그 패키지를 import 하므로, 서버는 zip 을 풀고 재시작하는 순간
`ImportError: cannot import name 'callcenter'` 로 죽었다. 로컬 검사는 전부
통과했는데 — 로컬은 저장소에서 읽으니 파일이 있었기 때문이다.

그래서 이 스크립트는 두 가지를 지킨다.
  1. 넣을 것을 고르지 않고 폴더를 통째로 담은 뒤, **뺄 것만** 지정한다.
  2. 다 만든 뒤 zip 을 임시 폴더에 풀어 `import app.main` 을 실제로 돌려 본다.
     서버가 하는 일과 같아서, 모듈 누락이 여기서 걸린다.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 서버에 올리면 안 되는 것들.
#   .venv / node_modules : 서버에 이미 있고 플랫폼도 다르다
#   __pycache__          : 소스와 어긋나면 오히려 해가 된다
#   *.db                 : 로컬 개발용 SQLite. 운영은 Postgres 라 쓸모없다
#   uploads / media      : 로컬에서 올린 파일. 서버 것을 덮어쓰면 안 된다
# media 는 관리자가 올린 롱폼·숏츠 원본이 쌓이는 자리다. 기가 단위라
# zip 에 담으면 배포가 불가능해지고, 서버 것을 덮어써서도 안 된다.
SKIP_DIRS = {".venv", "node_modules", "__pycache__", ".git", ".vite",
             "uploads", "media"}
SKIP_EXTS = {".db", ".db-journal", ".pyc", ".pyo", ".log"}

# 하위 폴더까지 통째로 담을 곳
TREES = [
    "backend/app", "backend/tests",
    "diary-backend/app", "diary-backend/tests",
    "research-backend/app", "research-backend/tests",
    "deploy",
    "frontend/src", "frontend/dist", "frontend/public",
    "frontend-cs/src", "frontend-cs/dist", "frontend-cs/public",
    "frontend-journal/src", "frontend-journal/dist", "frontend-journal/public",
    "frontend-research/src", "frontend-research/dist", "frontend-research/public",
]

# 낱개로 담을 파일
FILES = [
    "README.md",
    "backend/requirements.txt", "diary-backend/requirements.txt",
    "research-backend/requirements.txt", "research-backend/README.md",
    "frontend/index.html", "frontend/package.json", "frontend/vite.config.js",
    "frontend-cs/index.html", "frontend-cs/package.json", "frontend-cs/vite.config.js",
    "frontend-journal/index.html", "frontend-journal/package.json",
    "frontend-journal/vite.config.js",
    "frontend-research/index.html", "frontend-research/package.json",
    "frontend-research/vite.config.js",
]

# 들어갔는지 반드시 확인할 파일. 한 번이라도 빠져서 사고가 났던 것들을 남긴다.
MUST_HAVE = [
    "backend/app/main.py",
    "backend/app/callcenter/__init__.py",
    "backend/app/callcenter/intake.py",
    "backend/app/phone/__init__.py",
    "backend/app/fingerprint.py",
    "backend/requirements.txt",
    "diary-backend/app/main.py",
    "diary-backend/requirements.txt",
    "research-backend/app/main.py",
    "research-backend/app/fonts.py",
    "research-backend/requirements.txt",
    "frontend/dist/index.html",
]


def venv_python(backend_dir: str) -> str:
    """그 백엔드의 가상환경 파이썬. 없으면 빈 문자열."""
    for rel in ("Scripts/python.exe", "bin/python"):
        p = os.path.join(REPO, backend_dir, ".venv", *rel.split("/"))
        if os.path.exists(p):
            return p
    return ""


def add_tree(z: zipfile.ZipFile, rel: str) -> int:
    root = os.path.join(REPO, rel)
    if not os.path.isdir(root):
        print(f"  [없음] {rel}")
        return 0
    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if os.path.splitext(name)[1].lower() in SKIP_EXTS:
                continue
            full = os.path.join(dirpath, name)
            z.write(full, os.path.relpath(full, REPO).replace("\\", "/"))
            n += 1
    return n


def boot_test(zip_path: str) -> bool:
    """zip 을 풀어 서버처럼 import 해 본다. 모듈 누락은 여기서 걸린다."""
    tmp = tempfile.mkdtemp(prefix="hsportal-boot-")
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        ok = True
        for backend, extra in (("backend", {}),
                               ("diary-backend", {"PARTNER_SECRET": "x"})):
            py = venv_python(backend)
            if not py:
                print(f"  [건너뜀] {backend}: .venv 를 못 찾았습니다")
                continue
            env = dict(os.environ)
            env.update({
                "DATABASE_URL": "sqlite:///" + os.path.join(tmp, backend + ".db").replace("\\", "/"),
                "SECRET_KEY": "build-zip-boot-test",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
            })
            env.update(extra)
            r = subprocess.run(
                [py, "-c", "import sys; sys.path.insert(0, '.'); import app.main;"
                           " print(len(app.main.app.routes))"],
                cwd=os.path.join(tmp, backend), env=env,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            if r.returncode == 0:
                print(f"  {backend}: 기동 확인 (라우트 {r.stdout.strip().splitlines()[-1]}개)")
            else:
                ok = False
                print(f"  {backend}: 기동 실패")
                print((r.stderr or r.stdout or "").strip()[-1200:])
        return ok
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="배포용 hs-portal.zip 만들기")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(REPO), "hs-portal.zip"),
                    help="만들 zip 경로 (기본: 저장소 바로 위 hs-portal.zip)")
    ap.add_argument("--skip-boot-test", action="store_true",
                    help="풀어서 기동해 보는 검사를 건너뛴다(권장하지 않음)")
    args = ap.parse_args()

    out = os.path.abspath(args.out)
    if os.path.exists(out):
        os.remove(out)

    total = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in TREES:
            n = add_tree(z, rel)
            total += n
            print(f"  {rel:<34} {n}개")
        for rel in FILES:
            full = os.path.join(REPO, rel)
            if os.path.exists(full):
                z.write(full, rel)
                total += 1
            else:
                print(f"  [없음] {rel}")

    print(f"\n{out}  ({os.path.getsize(out):,} 바이트, {total}개 파일)")

    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
    missing = [p for p in MUST_HAVE if p not in names]
    if missing:
        print("\n필수 파일이 빠졌습니다:")
        for p in missing:
            print("  -", p)
        return 1
    print("필수 파일 확인 완료")

    if args.skip_boot_test:
        print("기동 검사를 건너뛰었습니다.")
        return 0
    print("\n풀어서 기동 검사:")
    if not boot_test(out):
        print("\n기동에 실패했습니다. 이 zip 을 서버에 올리면 서비스가 멈춥니다.")
        return 1
    print("\n보내도 됩니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
