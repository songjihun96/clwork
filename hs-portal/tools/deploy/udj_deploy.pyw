#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UDJ 배포툴 — hs-portal 서버 배포·운영 도구 (Windows 데스크톱 GUI)
================================================================
버전 3.0 (2026-09-19)

서버 한 대(root@.../root/hs-portal) 안에서 도는 다섯 개 서비스를
PC 에서 골라 배포하고, 상태를 보고, 로그를 읽고, 명령을 치는 도구다.

  서비스          도메인              포트   프로세스        코드 폴더
  ─────────────────────────────────────────────────────────────────────
  우리동네 직업계고  udjschool.ggm.kr   8000   udt-backend     backend + frontend
  CS 지원          udjcs.ggm.kr       8000   udt-backend     frontend-cs
    └ 통화 음성중계                    8010   udt-audio       backend (워커 1개 고정)
  기록해           diary.ggm.kr       8100   diary-backend   diary-backend + frontend-journal
  연구·논문        univ.ggm.kr        8200   research-backend research-backend + frontend-research
  우리업무         workwoori.ggm.kr   8300   work-backend    work-backend + frontend-work

**설계에서 지킨 것 — 전부 실제로 사고가 났던 지점이다.**

1. zip 에 `.env` 가 섞이면 배포를 중단한다. 점으로 시작하는 파일은 전부
   빼고, 담은 뒤에 zip 을 다시 열어 검사한다. (`scripts/build_deploy_zip.py`
   와 같은 규칙 — 2026-09-13 운영 `.env` 가 덮어써져 DB 가 빈 SQLite 로
   떨어졌던 사고에서 온 규칙이다.)
2. 그래도 서버에서 `unzip -o` 전에 `.env` 를 따로 복사해 두고, 끝난 뒤
   되돌려 놓는다. 그물은 두 겹이다.
3. pip 은 언제나 해당 서비스의 `.venv/bin/pip` 만 쓴다. 시스템 pip 은
   쓰지 않는다. (우리업무는 기록해 venv 를 공유한다 — reportlab 때문.)
4. 비밀번호는 기본적으로 저장하지 않는다. 설정 파일에 남는 것은 주소·계정·
   경로뿐이다. 키 파일(pem) 방식을 권한다.
5. 재시작·초기화처럼 되돌릴 수 없는 일은 반드시 한 번 더 묻는다.

실행:  배포툴.bat  (또는  pythonw udj_deploy.pyw)
필요:  Python 3.9+ , paramiko  (`pip install paramiko`)
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import zipfile
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

try:
    import paramiko
except ImportError:  # 실행 안내는 GUI 뜨기 전에 한 번만
    paramiko = None


APP_NAME = "UDJ 배포툴"
APP_VER = "3.0"
CONFIG_PATH = Path.home() / ".udj_deploy.json"

# ──────────────────────────────────────────────────────────────────────────
#  서비스 정의
# ──────────────────────────────────────────────────────────────────────────
# key:      내부 식별자
# label:    화면에 보이는 이름
# backend:  코드 폴더(서버·PC 공통 상대경로). 없으면 프론트만 있는 서비스
# venv:     pip 을 돌릴 venv 폴더. 없으면 backend 와 같음
# frontend: 프론트 폴더
# build:    프론트를 npm 으로 빌드해야 하면 True (False 면 정적 파일 그대로)
# service:  systemd 유닛 이름. 없으면 재시작할 프로세스가 없다는 뜻
# extra_services: 같이 재시작해야 하는 유닛
# port:     127.0.0.1 포트 (살아 있는지 확인용)
# domain:   외부 접속 주소 (응답 코드 확인용)
# must:     zip 에 반드시 들어가야 하는 파일 — 하나라도 없으면 배포 중단
SERVICES = [
    {
        "key": "udj",
        "label": "우리동네 직업계고",
        "backend": "backend",
        "venv": "backend",
        "frontend": "frontend",
        "build": True,
        "service": "udt-backend",
        "extra_services": ["udt-audio"],
        "port": 8000,
        "domain": "udjschool.ggm.kr",
        "must": ["backend/app/main.py", "backend/requirements.txt",
                 "backend/app/callcenter/__init__.py", "backend/app/phone/__init__.py"],
    },
    {
        "key": "cs",
        "label": "CS 지원 (상담)",
        "backend": "",
        "venv": "",
        "frontend": "frontend-cs",
        "build": True,
        "service": "",           # 백엔드는 udt-backend 와 공유한다
        "extra_services": [],
        "port": 8010,
        "domain": "udjcs.ggm.kr",
        "must": ["frontend-cs/dist/index.html"],
    },
    {
        "key": "diary",
        "label": "기록해",
        "backend": "diary-backend",
        "venv": "diary-backend",
        "frontend": "frontend-journal",
        "build": True,
        "service": "diary-backend",
        "extra_services": [],
        "port": 8100,
        "domain": "diary.ggm.kr",
        "must": ["diary-backend/app/main.py", "diary-backend/requirements.txt"],
    },
    {
        "key": "research",
        "label": "연구·논문 (대학전형)",
        "backend": "research-backend",
        "venv": "research-backend",
        "frontend": "frontend-research",
        "build": True,
        "service": "research-backend",
        # 이 서비스는 이름이 오락가락했다(univ.ggm.kr 이라 univ-backend 로 등록된
        # 서버도 있다). 접속하면 실제로 등록된 유닛을 찾아 맞춘다.
        "service_alts": ["univ-backend", "research", "univ"],
        "extra_services": [],
        "port": 8200,
        "domain": "univ.ggm.kr",
        "must": ["research-backend/app/main.py", "research-backend/requirements.txt"],
    },
    {
        "key": "work",
        "label": "우리업무",
        "backend": "work-backend",
        # 우리업무는 파이썬 패키지를 따로 안 깐다. 기록해 venv 를 그대로 쓴다
        # (급여명세서 PDF 용 reportlab 이 그쪽에만 있다, 2026-09-15).
        "venv": "diary-backend",
        "frontend": "frontend-work",
        "build": False,          # Vite 가 아니라 정적 파일이다
        "service": "work-backend",
        "extra_services": [],
        "port": 8300,
        "domain": "workwoori.ggm.kr",
        "must": ["work-backend/app/main.py", "work-backend/app/settlement.py",
                 "work-backend/app/payroll.py", "frontend-work/index.html",
                 "frontend-work/payroll.js", "frontend-work/settlement.js"],
    },
]

SERVICE_BY_KEY = {s["key"]: s for s in SERVICES}

# 서비스에 속하지 않지만 다룰 일이 있는 유닛
SYSTEM_UNITS = ["nginx", "postgresql"]

# ──────────────────────────────────────────────────────────────────────────
#  zip 안전 규칙 — scripts/build_deploy_zip.py 와 같은 규칙을 그대로 쓴다
# ──────────────────────────────────────────────────────────────────────────
SKIP_DIRS = {
    ".venv", "venv", "node_modules", "__pycache__", ".git", ".pytest_cache",
    "uploads", "media", ".mypy_cache", ".ruff_cache", ".vite",
}
SKIP_FILE_RE = re.compile(r"^\.|\.(db|db-journal|db-wal|db-shm|pyc|pyo|log|zip|sqlite3?)$", re.I)
FORBIDDEN_RE = re.compile(r"(^|/)\.env|(^|/)\.git/|secret|credential|id_rsa|\.pem$|\.key$|\.db$", re.I)
FORBIDDEN_OK = re.compile(r"env\.example$|\.env\.example$", re.I)

REMOTE_ROOT = "/root/hs-portal"
REMOTE_UPLOAD_DIR = "/root/deploy-uploads"
REMOTE_BACKUP_DIR = "/root/deploy-backups"


def ts() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


# ══════════════════════════════════════════════════════════════════════════
#  로컬: zip 만들기
# ══════════════════════════════════════════════════════════════════════════
def collect_tree(base: Path, prefix: str):
    """폴더 하나를 (실제경로, zip안경로) 목록으로 훑는다."""
    out = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in sorted(files):
            if SKIP_FILE_RE.search(f):
                continue
            p = Path(root) / f
            arc = prefix + "/" + str(p.relative_to(base)).replace("\\", "/")
            out.append((p, arc))
    return out


def unix_zipinfo(arc: str, src=None, base: "zipfile.ZipInfo" = None) -> zipfile.ZipInfo:
    """리눅스 권한을 박아 넣은 zip 항목.

    윈도에서 z.write() 로 담으면 윈도가 주는 권한(0o666, 누구나 쓰기)이
    그대로 들어가고 서버 unzip 이 그걸 살린다(2026-09-19, 서버 index.html 이
    -rw-rw-rw- 가 됐다). 파일은 644, 셸 스크립트만 755 로 못 박는다.
    """
    if base is not None:
        info = zipfile.ZipInfo(arc, base.date_time)
        info.compress_type = zipfile.ZIP_DEFLATED
    else:
        info = zipfile.ZipInfo.from_file(src, arc)
    info.create_system = 3   # 3 = 유닉스. 0(윈도)이면 unzip 이 권한을 멋대로 읽는다
    mode = 0o755 if arc.endswith(".sh") else 0o644
    info.external_attr = (0o100000 | mode) << 16
    return info


def remote_extract_script(rpath: str, rroot: str, wrapper: str = "") -> str:
    """서버에서 zip 을 안전하게 푸는 bash 조각. 배포 세 갈래가 모두 이걸 쓴다.

    2026-09-19 사고 두 가지를 막는다.
      · 예전엔 mktemp -d 로 만든 임시 폴더(700)를 `cp -a $T/. 루트/` 로 옮겨서
        임시 폴더의 권한이 /root/hs-portal 에 그대로 옮겨 붙었다(700 →
        nginx 가 못 읽어 사이트 4곳이 500). 이제 tar 로 옮기며
        --no-overwrite-dir 로 이미 있는 폴더의 권한은 건드리지 않고, 끝에
        원래 권한을 한 번 더 되돌린다.
      · 같은 배포에서 이미 있던 파일(main.py 등)이 덮어써지지 않고 새 파일만
        들어갔다. tar 는 있는 파일을 지우고 새로 쓴다. 그리고 **다 옮긴 뒤
        zip 의 파일 하나하나를 서버 파일과 비교해서 하나라도 다르면 실패**로
        끝낸다 — 반쯤 들어간 배포를 '끝'으로 넘기지 않는다.
    권한은 umask 022 로 맞춘다(파일 644 · 폴더 755). zip 안의 권한은 믿지 않는다.
    """
    src = f'"$T/{wrapper}"' if wrapper else '"$T"'
    return f"""
set -o pipefail
umask 022
ROOTMODE=$(stat -c %a {rroot})
T=$(mktemp -d)
trap 'rm -rf "$T"; chmod "$ROOTMODE" {rroot}' EXIT
unzip -o -q {rpath} -d "$T"
tar -C {src} -cf - . | tar -C {rroot} -xf - --no-same-owner --no-same-permissions --no-overwrite-dir
chmod "$ROOTMODE" {rroot}
N=0; BAD=0
while IFS= read -r -d '' f; do
  N=$((N+1))
  if ! cmp -s {src}/"$f" {rroot}/"$f"; then echo "  안 바뀐 파일: ${{f#./}}"; BAD=$((BAD+1)); fi
done < <(cd {src} && find . -type f -print0)
if [ "$BAD" -ne 0 ]; then echo "서버 파일 $BAD 개가 zip 과 다르다 — 배포가 끝까지 들어가지 않았다"; exit 3; fi
echo "파일 $N 개 모두 zip 과 같다 · 루트 권한 $(stat -c %a {rroot})"
"""


def build_zip(repo: Path, keys, out_path: Path, log):
    """고른 서비스만 담은 배포 zip 을 만든다.

    비밀 파일이 하나라도 섞이면 zip 을 지우고 예외를 던진다. 반쯤 맞는
    zip 을 남기는 쪽이 더 위험하다.
    """
    trees, must = [], []
    for k in keys:
        svc = SERVICE_BY_KEY[k]
        if svc["backend"]:
            trees.append(svc["backend"])
        if svc["frontend"]:
            # Vite 프로젝트는 빌드 결과(dist)만 올린다. 소스는 서버에 필요 없다.
            trees.append(svc["frontend"] + "/dist" if svc["build"] else svc["frontend"])
        must += svc["must"]
    # 배포 설정(systemd·nginx)은 항상 같이 올린다 — 작고, 서버에서 참고한다
    trees.append("deploy")
    trees = list(dict.fromkeys(trees))

    items = []
    for t in trees:
        d = repo / t
        if not d.is_dir():
            if t.endswith("/dist"):
                raise RuntimeError(
                    f"빌드 결과가 없다: {t}\n"
                    f"→ '프론트 빌드' 를 켜고 다시 실행하거나, "
                    f"{t[:-5]} 에서 npm run build 를 먼저 돌려라."
                )
            raise RuntimeError(f"없는 폴더: {t}")
        items += collect_tree(d, t)
        log(f"  담음: {t} ({len(items)}개 누적)")

    return finalize_zip(items, out_path, log, must)


def finalize_zip(items, out_path: Path, log, must=()):
    """(실제경로, zip안경로) 목록을 zip 으로 굳힌다. 검사는 여기서 한다.

    서비스 통째로 올리든 파일을 골라 올리든 이 문을 반드시 지난다 —
    검사를 우회하는 경로를 하나라도 두면 언젠가 그리로 사고가 난다.
    """
    if not items:
        raise RuntimeError("담을 파일이 없다.")

    fd, tmp_name = tempfile.mkstemp(suffix=".zip")
    os.close(fd)                      # 윈도에서는 안 닫으면 파일이 잠긴다
    tmp = Path(tmp_name)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for src, arc in items:
            z.writestr(unix_zipinfo(arc, src), Path(src).read_bytes(), zipfile.ZIP_DEFLATED)

    names = zipfile.ZipFile(tmp).namelist()

    bad = [n for n in names if FORBIDDEN_RE.search(n) and not FORBIDDEN_OK.search(n)]
    if bad:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("들어가면 안 되는 파일이 있어 zip 을 만들지 않았다:\n  "
                           + "\n  ".join(bad[:20]))

    missing = [m for m in must if m not in names]
    if missing:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("빠진 파일이 있어 zip 을 만들지 않았다:\n  " + "\n  ".join(missing))

    shutil.move(str(tmp), str(out_path))
    kb = out_path.stat().st_size / 1024
    log(f"  zip 완성: {out_path.name} — 파일 {len(names)}개 / {kb:,.1f} KB")
    log("  검사 통과: .env·비밀키 없음" + (", 필수 파일 누락 없음" if must else ""))
    return out_path


# ──────────────────────────────────────────────────────────────────────────
#  고른 파일이 서버에서 실제로 쓰이는 파일인지 보는 규칙
# ──────────────────────────────────────────────────────────────────────────
def which_service(rel: str):
    """저장소 안 상대경로가 어느 서비스 것인지 찾는다."""
    top = rel.replace("\\", "/").split("/")[0]
    for svc in SERVICES:
        if top and top in (svc["backend"], svc["frontend"]):
            return svc
    return None


def source_warning(rel: str) -> str:
    """서버가 읽지 않는 파일을 고른 경우 그 이유를 돌려준다. 없으면 빈 문자열."""
    p = rel.replace("\\", "/")
    top = p.split("/")[0]
    svc = which_service(p)
    if svc and svc["frontend"] == top and svc["build"] and "/dist/" not in p:
        return (f"{p} — 화면 소스다. nginx 는 {top}/dist 만 읽으므로 이 파일만 올려서는"
                f" 아무것도 안 바뀐다. '프론트 빌드' 를 켜고 서비스 방식으로 올리거나,"
                f" 빌드한 뒤 {top}/dist 를 골라라.")
    if top in ("tools", "manuals", "docs"):
        return f"{p} — PC 에서만 쓰는 파일이다. 서버에 올릴 필요가 없다."
    return ""


def npm_build(repo: Path, folder: str, log) -> None:
    """PC 에서 프론트를 빌드한다. 실패하면 예외."""
    d = repo / folder
    if not d.is_dir():
        raise RuntimeError(f"없는 폴더: {folder}")
    npm = "npm.cmd" if os.name == "nt" else "npm"
    if not (d / "node_modules").is_dir():
        log(f"  {folder}: node_modules 가 없다 → npm install (처음 한 번은 오래 걸린다)")
        run_local([npm, "install"], d, log)
    log(f"  {folder}: npm run build")
    run_local([npm, "run", "build"], d, log)
    if not (d / "dist" / "index.html").is_file():
        raise RuntimeError(f"{folder}/dist/index.html 이 생기지 않았다. 빌드 로그를 확인하라.")


def run_local(cmd, cwd: Path, log) -> None:
    creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    p = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                         errors="replace", creationflags=creation, shell=False)
    for line in p.stdout:
        line = line.rstrip()
        if line:
            log("    " + line)
    if p.wait() != 0:
        raise RuntimeError(f"명령 실패({p.returncode}): {' '.join(cmd)}")


# ══════════════════════════════════════════════════════════════════════════
#  원격: SSH
# ══════════════════════════════════════════════════════════════════════════
class Remote:
    """paramiko 를 감싼 얇은 층. 실패는 전부 예외로 올린다."""

    def __init__(self):
        self.client = None
        self.sftp = None
        self.info = ""

    @property
    def connected(self) -> bool:
        return self.client is not None and self.client.get_transport() is not None \
            and self.client.get_transport().is_active()

    @staticmethod
    def load_key(path, passphrase=None):
        """키 파일을 형식을 가려가며 읽는다.

        paramiko 에 파일 경로만 넘기면 종류를 하나씩 시험하다가 첫 실패의
        메시지("encountered RSA key, expected OPENSSH key")를 그대로 던져
        버린다. 진짜 원인(암호가 걸렸다든지)이 그 뒤에 가려지므로, 여기서
        직접 순서대로 열어 보고 전부 실패했을 때 이유를 모아서 알린다.
        """
        classes = [c for c in ("RSAKey", "Ed25519Key", "ECDSAKey", "DSSKey")
                   if getattr(paramiko, c, None)]
        tried = []
        for name in classes:
            cls = getattr(paramiko, name)
            try:
                return cls.from_private_key_file(path, password=passphrase or None)
            except paramiko.PasswordRequiredException:
                raise RuntimeError(
                    "키 파일에 암호가 걸려 있다. '비밀번호' 칸에 키 암호를 넣고 다시 연결하라.")
            except Exception as e:
                tried.append(f"{name}: {e}")
        raise RuntimeError(
            "키 파일을 읽지 못했다:\n  " + "\n  ".join(tried) +
            "\n\n형식이 맞지 않는 키다. 둘 중 하나로 풀 수 있다.\n"
            "  1) 비밀번호 방식으로 접속한다 (네이버 클라우드는 pem 으로 관리자\n"
            "     비밀번호를 확인한 뒤, 그 비밀번호로 root 접속하는 방식이다)\n"
            "  2) 키를 OpenSSH 형식으로 바꾼다:  ssh-keygen -p -m PEM -f 키파일")

    def connect(self, host, port, user, password=None, keyfile=None, timeout=15,
                log=None):
        cli = paramiko.SSHClient()
        cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        base = dict(hostname=host, port=int(port), username=user, timeout=timeout,
                    allow_agent=False, look_for_keys=False)

        errors = []
        if keyfile:
            try:
                pkey = self.load_key(keyfile, password)
                if log:
                    log(f"  키 읽음: {type(pkey).__name__}")
                cli.connect(pkey=pkey, **base)
                self._finish(cli, user, host, port)
                return
            except Exception as e:
                errors.append(f"키 방식: {e}")
                if log:
                    log(f"  키 방식 실패 — {e}", "warn")
                if not password:
                    raise RuntimeError(errors[0])

        # 키가 없거나 키로 안 되면 비밀번호로 한 번 더
        if password:
            try:
                cli.connect(password=password, **base)
                self._finish(cli, user, host, port)
                return
            except Exception as e:
                errors.append(f"비밀번호 방식: {e}")
        elif not keyfile:
            raise RuntimeError("비밀번호나 키 파일 중 하나는 있어야 한다.")
        raise RuntimeError("접속하지 못했다.\n  " + "\n  ".join(errors))

    def _finish(self, cli, user, host, port):
        self.client = cli
        self.sftp = cli.open_sftp()
        self.info = f"{user}@{host}:{port}"

    def close(self):
        for o in (self.sftp, self.client):
            try:
                if o:
                    o.close()
            except Exception:
                pass
        self.sftp = self.client = None

    def run(self, cmd, log=None, timeout=900, check=False):
        """명령 하나를 돌리고 (종료코드, 출력) 을 준다. 출력은 줄마다 log 로."""
        if not self.connected:
            raise RuntimeError("서버에 연결돼 있지 않다.")
        chan = self.client.get_transport().open_session()
        chan.settimeout(timeout)
        chan.set_combine_stderr(True)
        chan.exec_command(cmd)
        buf, out = b"", []
        while True:
            if chan.recv_ready():
                buf += chan.recv(65536)
                *lines, buf = buf.split(b"\n")
                for ln in lines:
                    s = ln.decode("utf-8", "replace").rstrip()
                    out.append(s)
                    if log:
                        log("    " + s)
            elif chan.exit_status_ready() and not chan.recv_ready():
                break
            else:
                time.sleep(0.05)
        if buf:
            s = buf.decode("utf-8", "replace").rstrip()
            out.append(s)
            if log:
                log("    " + s)
        code = chan.recv_exit_status()
        chan.close()
        if check and code != 0:
            raise RuntimeError(f"서버 명령 실패(코드 {code}): {cmd.splitlines()[0][:80]}")
        return code, "\n".join(out)

    def upload(self, local: Path, remote_path: str, progress=None):
        size = local.stat().st_size
        sent = [0]

        def cb(done, total):
            sent[0] = done
            if progress:
                progress(done, total or size)

        self.sftp.put(str(local), remote_path, callback=cb)
        return sent[0]


# ══════════════════════════════════════════════════════════════════════════
#  GUI
# ══════════════════════════════════════════════════════════════════════════
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.remote = Remote()
        self.q: "queue.Queue[tuple]" = queue.Queue()
        self.busy = False
        self.picked: list[str] = []      # 파일 골라 올리기 모드에서 고른 상대경로
        self.unit_of: dict[str, str] = {}
        self.cfg = self.load_config()

        root.title(f"{APP_NAME} v{APP_VER}")
        root.geometry("1040x720")
        root.minsize(900, 600)

        self.build_style()
        self.build_header()

        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self.tab_deploy = ttk.Frame(self.nb, padding=10)
        self.tab_service = ttk.Frame(self.nb, padding=10)
        self.tab_check = ttk.Frame(self.nb, padding=10)
        self.tab_console = ttk.Frame(self.nb, padding=10)
        self.tab_conn = ttk.Frame(self.nb, padding=10)
        self.nb.add(self.tab_deploy, text="  배포  ")
        self.nb.add(self.tab_service, text="  서비스  ")
        self.nb.add(self.tab_check, text="  점검  ")
        self.nb.add(self.tab_console, text="  콘솔  ")
        self.nb.add(self.tab_conn, text="  연결 설정  ")

        self.build_deploy_tab()
        self.build_service_tab()
        self.build_check_tab()
        self.build_console_tab()
        self.build_conn_tab()
        self.build_log()

        self.switch_mode()
        self.refresh_picked()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(80, self.pump)

        self.log(f"{APP_NAME} v{APP_VER} — 준비됨", "head")
        if paramiko is None:
            self.log("paramiko 가 없다.  pip install paramiko  후 다시 실행하라.", "err")
        if not self.repo_ok():
            self.log("프로젝트 폴더를 먼저 지정하라 (연결 설정 탭).", "warn")

    # ── 설정 ──────────────────────────────────────────────────────────────
    def load_config(self) -> dict:
        base = {"host": "", "port": 22, "user": "root", "keyfile": "",
                "repo": "", "remote_root": REMOTE_ROOT, "save_password": False,
                "password": ""}
        try:
            if CONFIG_PATH.is_file():
                base.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
        # 프로젝트 폴더를 안 정했으면 이 파일 근처에서 찾아본다
        if not base["repo"]:
            here = Path(__file__).resolve()
            for p in [here.parent] + list(here.parents):
                if (p / "backend" / "app").is_dir() and (p / "deploy").is_dir():
                    base["repo"] = str(p)
                    break
        return base

    def save_config(self):
        data = dict(self.cfg)
        data["host"] = self.v_host.get().strip()
        data["port"] = self.v_port.get().strip() or "22"
        data["user"] = self.v_user.get().strip() or "root"
        data["keyfile"] = self.v_key.get().strip()
        data["repo"] = self.v_repo.get().strip()
        data["remote_root"] = self.v_rroot.get().strip() or REMOTE_ROOT
        data["save_password"] = bool(self.v_savepw.get())
        # 비밀번호는 기본적으로 남기지 않는다. 켠 경우에만, 그것도 이 PC 파일에만.
        data["password"] = self.v_pw.get() if data["save_password"] else ""
        try:
            CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
            if os.name != "nt":
                os.chmod(CONFIG_PATH, 0o600)
            self.cfg = data
            self.log(f"설정을 저장했다: {CONFIG_PATH}", "ok")
            if data["save_password"]:
                self.log("비밀번호가 이 PC 설정 파일에 평문으로 남는다. "
                         "가능하면 키 파일(pem) 방식을 써라.", "warn")
        except Exception as e:
            self.log(f"설정 저장 실패: {e}", "err")

    def repo(self) -> Path:
        return Path(self.v_repo.get().strip())

    def repo_ok(self) -> bool:
        try:
            r = self.repo()
            return r.is_dir() and (r / "deploy").is_dir()
        except Exception:
            return False

    # ── 화면 조각 ─────────────────────────────────────────────────────────
    def build_style(self):
        st = ttk.Style()
        try:
            st.theme_use("vista" if os.name == "nt" else "clam")
        except Exception:
            pass
        st.configure("TButton", padding=(10, 5))
        st.configure("Accent.TButton", padding=(14, 7))
        st.configure("Head.TLabel", font=("Malgun Gothic", 11, "bold"))
        st.configure("Dim.TLabel", foreground="#666")

    def build_header(self):
        bar = ttk.Frame(self.root, padding=(12, 10, 12, 6))
        bar.pack(fill="x")
        ttk.Label(bar, text=f"{APP_NAME}", style="Head.TLabel").pack(side="left")
        self.v_state = tk.StringVar(value="● 연결 안 됨")
        self.lbl_state = ttk.Label(bar, textvariable=self.v_state, foreground="#b00")
        self.lbl_state.pack(side="left", padx=12)
        self.btn_conn = ttk.Button(bar, text="서버 연결", command=self.do_connect)
        self.btn_conn.pack(side="right")
        self.pb = ttk.Progressbar(bar, mode="determinate", length=200)
        self.pb.pack(side="right", padx=10)

    def build_deploy_tab(self):
        f = self.tab_deploy
        ttk.Label(f, text="무엇을 올릴지 고른다", style="Head.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))

        mode = ttk.Frame(f)
        mode.grid(row=0, column=0, columnspan=4, sticky="e")
        self.v_mode = tk.StringVar(value="service")
        ttk.Radiobutton(mode, text="서비스 통째로", value="service", variable=self.v_mode,
                        command=self.switch_mode).pack(side="left")
        ttk.Radiobutton(mode, text="파일 골라서", value="files", variable=self.v_mode,
                        command=self.switch_mode).pack(side="left", padx=10)
        ttk.Radiobutton(mode, text="zip 골라서", value="zip", variable=self.v_mode,
                        command=self.switch_mode).pack(side="left")

        # ── zip 을 직접 골라 올리는 쪽 ───────────────────────────────────
        self.zip_box = ttk.Frame(f)
        self.zip_box.grid(row=1, column=0, columnspan=4, sticky="we")
        zbar = ttk.Frame(self.zip_box)
        zbar.pack(fill="x")
        ttk.Label(zbar, text="zip 파일").pack(side="left")
        self.v_zip = tk.StringVar()
        ttk.Entry(zbar, textvariable=self.v_zip).pack(side="left", fill="x",
                                                      expand=True, padx=8)
        ttk.Button(zbar, text="찾기…", command=self.pick_zip).pack(side="left")
        ttk.Button(zbar, text="다시 검사", command=lambda: self.start(self.inspect_zip)) \
            .pack(side="left", padx=6)
        self.lb_zip = tk.Listbox(self.zip_box, height=8, font=("Consolas", 9),
                                 activestyle="none")
        self.lb_zip.pack(fill="x", pady=(8, 0))
        ttk.Label(self.zip_box,
                  text="고른 zip 을 그대로 서버에 풀어 덮어쓴다. 풀기 전에 안을 들여다보고 "
                       "비밀 파일이 섞였는지, 어느 서비스가 바뀌는지 알려준다.",
                  style="Dim.TLabel", wraplength=900).pack(anchor="w", pady=(4, 0))
        self.zip_box.grid_remove()

        # ── 파일 고르기 쪽 ───────────────────────────────────────────────
        self.file_box = ttk.Frame(f)
        self.file_box.grid(row=1, column=0, columnspan=4, sticky="we")
        bar = ttk.Frame(self.file_box)
        bar.pack(fill="x")
        self.v_picked = tk.StringVar(value="고른 파일 없음")
        ttk.Label(bar, textvariable=self.v_picked).pack(side="left")
        ttk.Button(bar, text="파일 고르기…", command=self.open_picker).pack(side="right")
        ttk.Button(bar, text="비우기", command=lambda: (self.picked.clear(),
                                                     self.refresh_picked())).pack(side="right", padx=6)
        self.lb_picked = tk.Listbox(self.file_box, height=7, font=("Consolas", 9),
                                    activestyle="none")
        self.lb_picked.pack(fill="x", pady=(6, 0))
        ttk.Label(self.file_box,
                  text="고른 파일만 서버의 같은 자리에 덮어쓴다. 나머지는 건드리지 않는다.",
                  style="Dim.TLabel").pack(anchor="w", pady=(4, 0))
        self.file_box.grid_remove()

        self.v_svc = {}
        box = ttk.Frame(f)
        self.svc_box = box
        box.grid(row=1, column=0, columnspan=4, sticky="we")
        for i, svc in enumerate(SERVICES):
            v = tk.BooleanVar(value=False)
            self.v_svc[svc["key"]] = v
            txt = f'{svc["label"]}   ({svc["domain"]}'
            txt += f' · {svc["service"]}' if svc["service"] else " · 화면만"
            txt += ")"
            ttk.Checkbutton(box, text=txt, variable=v).grid(
                row=i, column=0, sticky="w", pady=2)

        opt = ttk.LabelFrame(f, text="함께 할 일", padding=10)
        opt.grid(row=2, column=0, columnspan=4, sticky="we", pady=(14, 8))
        self.v_build = tk.BooleanVar(value=True)
        self.v_pip = tk.BooleanVar(value=False)
        self.v_restart = tk.BooleanVar(value=True)
        self.v_backup = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="프론트 빌드 (npm run build)  — 화면을 고쳤으면 켠다",
                        variable=self.v_build).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(opt, text="파이썬 의존성 설치 (.venv/bin/pip install -r)  — requirements 가 바뀌었을 때만",
                        variable=self.v_pip).grid(row=1, column=0, sticky="w")
        ttk.Checkbutton(opt, text="배포 전 서버 폴더 백업 (tar.gz)  — 되돌릴 수 있게",
                        variable=self.v_backup).grid(row=2, column=0, sticky="w")
        ttk.Checkbutton(opt, text="배포 후 서비스 재시작",
                        variable=self.v_restart).grid(row=3, column=0, sticky="w")

        btns = ttk.Frame(f)
        btns.grid(row=3, column=0, columnspan=4, sticky="we", pady=(4, 0))
        ttk.Button(btns, text="zip 만들기만", command=lambda: self.start(self.job_zip_only)) \
            .pack(side="left")
        ttk.Button(btns, text="전체 선택", command=lambda: [v.set(True) for v in self.v_svc.values()]) \
            .pack(side="left", padx=6)
        ttk.Button(btns, text="선택 해제", command=lambda: [v.set(False) for v in self.v_svc.values()]) \
            .pack(side="left")
        self.btn_deploy = ttk.Button(btns, text="▶  배포 실행", style="Accent.TButton",
                                     command=lambda: self.start(self.job_deploy))
        self.btn_deploy.pack(side="right")

        ttk.Label(f, text="배포는 이 순서로 돈다:  프론트 빌드 → zip(.env 검사) → 업로드 → "
                          "서버 백업 → .env 보관 → unzip -o → .env 복원 → pip → 재시작 → 상태 확인",
                  style="Dim.TLabel", wraplength=960).grid(
            row=4, column=0, columnspan=4, sticky="w", pady=(12, 0))

    # ── 모드 전환 ────────────────────────────────────────────────────────
    def switch_mode(self):
        mode = self.v_mode.get()
        for box, name in ((self.svc_box, "service"), (self.file_box, "files"),
                          (self.zip_box, "zip")):
            box.grid() if mode == name else box.grid_remove()

    # ── zip 직접 올리기 ──────────────────────────────────────────────────
    def pick_zip(self):
        start = str(self.repo().parent) if self.repo_ok() else str(Path.home())
        p = filedialog.askopenfilename(title="올릴 zip 고르기", initialdir=start,
                                       filetypes=[("zip 파일", "*.zip"), ("모든 파일", "*")])
        if p:
            self.v_zip.set(p)
            self.start(self.inspect_zip)

    def inspect_zip(self):
        """풀기 전에 안을 본다. 무엇이 덮어써지는지 모르고 푸는 일이 없도록."""
        path = Path(self.v_zip.get().strip())
        if not path.is_file():
            raise RuntimeError("zip 파일을 고르라.")
        try:
            names = [n for n in zipfile.ZipFile(path).namelist() if not n.endswith("/")]
        except zipfile.BadZipFile:
            raise RuntimeError("zip 파일이 아니거나 깨졌다.")
        if not names:
            raise RuntimeError("zip 이 비어 있다.")

        # 통째로 감싸는 폴더가 있는지 (윈도 탐색기로 만든 zip 이 이렇다)
        tops = {n.replace("\\", "/").split("/")[0] for n in names}
        known = {s[k] for s in SERVICES for k in ("backend", "frontend") if s[k]} | \
                {"deploy", "scripts", "tools", "manuals", "docs"}
        self.zip_wrapper = ""
        if len(tops) == 1 and tops and next(iter(tops)) not in known:
            self.zip_wrapper = next(iter(tops))

        inner = [n[len(self.zip_wrapper) + 1:] if self.zip_wrapper else n for n in names]
        self.zip_names, self.zip_path = inner, path
        self.zip_bad = [n for n, o in zip(inner, names)
                        if FORBIDDEN_RE.search(n) and not FORBIDDEN_OK.search(n)]

        counts = {}
        for n in inner:
            counts[n.split("/")[0]] = counts.get(n.split("/")[0], 0) + 1

        self.lb_zip.delete(0, "end")
        mb = path.stat().st_size / 1024 / 1024
        self.lb_zip.insert("end", f"{path.name}  —  파일 {len(inner)}개 / {mb:.1f} MB")
        if self.zip_wrapper:
            self.lb_zip.insert("end", f"  감싼 폴더 '{self.zip_wrapper}/' 는 벗겨서 푼다")
        for top, c in sorted(counts.items(), key=lambda x: -x[1]):
            svc = next((s["label"] for s in SERVICES
                        if top in (s["backend"], s["frontend"])), "")
            self.lb_zip.insert("end", f"  {top}/  파일 {c}개" + (f"   [{svc}]" if svc else ""))
        for b in self.zip_bad:
            self.lb_zip.insert("end", f"  [위험] {b}")

        svcs = self.services_in_zip()
        self.log(f"zip 검사: {path.name} — 파일 {len(inner)}개", "head")
        self.log("  바뀌는 서비스: " + (", ".join(s["label"] for s in svcs) or "알 수 없음"))
        if self.zip_bad:
            self.log(f"  위험한 파일 {len(self.zip_bad)}개가 들어 있다 "
                     f"({', '.join(self.zip_bad[:5])}) — 올릴 때 빼고 올릴 수 있다", "err")
        else:
            self.log("  비밀 파일(.env·키) 없음", "ok")

    def services_in_zip(self):
        tops = {n.split("/")[0] for n in getattr(self, "zip_names", [])}
        return [s for s in SERVICES if s["backend"] in tops or s["frontend"] in tops]

    def job_deploy_zip(self):
        self.need_remote()
        if not getattr(self, "zip_names", None) or \
                str(getattr(self, "zip_path", "")) != self.v_zip.get().strip():
            self.inspect_zip()
        path, rroot = self.zip_path, (self.v_rroot.get().strip() or REMOTE_ROOT)
        svcs = self.services_in_zip()

        send = path
        if self.zip_bad:
            if not messagebox.askyesno(
                    APP_NAME,
                    f"이 zip 에는 서버에 올라가면 안 되는 파일이 {len(self.zip_bad)}개 있다:\n\n    "
                    + "\n    ".join(self.zip_bad[:10]) +
                    "\n\n운영 .env 나 키를 덮어쓰면 서비스가 죽는다.\n"
                    "이 파일들을 빼고 나머지만 올릴까?  (아니오 = 취소)"):
                self.log("취소했다.", "warn")
                return
            send = self.repack_without_bad(path)

        units, touched = [], []
        for s in svcs:
            if s["service"]:
                units.append(self.unit(s))
                units += s.get("extra_services", [])
                touched.append(s["label"])
        units = list(dict.fromkeys(units))

        if not messagebox.askyesno(
                APP_NAME,
                f"{path.name} 을 서버에 푼다.\n\n"
                f"    파일 {len(self.zip_names)}개\n"
                f"    바뀌는 서비스: {', '.join(s['label'] for s in svcs) or '알 수 없음'}\n"
                f"    재시작: {', '.join(units) if units and self.v_restart.get() else '없음'}\n\n"
                f"서버의 같은 파일은 덮어쓴다. 진행할까?"):
            self.log("취소했다.", "warn")
            return

        self.log("업로드", "head")
        self.remote.run(f"mkdir -p {REMOTE_UPLOAD_DIR} {REMOTE_BACKUP_DIR}", check=True)
        rpath = f"{REMOTE_UPLOAD_DIR}/{send.name}"
        t0 = time.time()
        self.remote.upload(send, rpath, self.progress)
        self.log(f"  올림: {send.name} ({send.stat().st_size / 1024 / 1024:.1f} MB, "
                 f"{time.time() - t0:.1f}초)", "ok")

        dirs = list(dict.fromkeys(
            [d for s in svcs for d in (s["backend"], s["frontend"]) if d]))
        if self.v_backup.get() and dirs:
            self.log("서버 폴더 백업", "head")
            tar = f"{REMOTE_BACKUP_DIR}/before-zip-{ts()}.tar.gz"
            self.remote.run(
                f"cd {rroot} && tar --exclude='.venv' --exclude='node_modules' "
                f"--exclude='__pycache__' -czf {tar} {' '.join(dirs)} 2>/dev/null; ls -lh {tar}",
                self.log)

        self.log("서버에 풀기", "head")
        stamp = ts()
        env_dirs = [s["backend"] for s in svcs if s["backend"]]
        keep = " ".join(env_dirs)
        # 임시 폴더에 풀고 옮긴다 — 감싼 폴더가 있어도 같은 방식으로 처리된다
        script = f"""
set -e
cd {rroot}
for d in {keep or '""'}; do
  if [ -f "$d/.env" ]; then cp -a "$d/.env" "/root/env-keep-{stamp}-$(echo $d | tr / _).env"; fi
done
{remote_extract_script(rpath, rroot, self.zip_wrapper)}
cd {rroot}
for d in {keep or '""'}; do
  f="/root/env-keep-{stamp}-$(echo $d | tr / _).env"
  if [ -f "$f" ]; then cp -a "$f" "$d/.env"; fi
done
echo "풀기 완료"
"""
        code, _ = self.remote.run(f"bash -lc {shquote(script)}", self.log)
        if code != 0:
            raise RuntimeError("서버에서 압축을 푸는 중 실패했다. 위 출력 확인.")
        self.log("  .env 보관 → 풀기 → .env 복원 까지 끝", "ok")

        if self.v_pip.get():
            self.log("파이썬 의존성", "head")
            for s in svcs:
                if not s["backend"]:
                    continue
                pip = f"{rroot}/{s['venv'] or s['backend']}/.venv/bin/pip"
                req = f"{rroot}/{s['backend']}/requirements.txt"
                code, _ = self.remote.run(
                    f"test -f {pip} && test -f {req} && {pip} install -q -r {req} "
                    f"&& echo '  {s['label']}: 설치 완료'", self.log)
                if code != 0:
                    self.log(f"  {s['label']}: 건너뜀 (venv·requirements 없음)", "warn")

        if self.v_restart.get() and units:
            self.log("서비스 재시작", "head")
            for u in units:
                code, _ = self.remote.run(f"systemctl restart {u}", self.log)
                self.log(f"  재시작: {u}" if code == 0 else f"  재시작 실패: {u}",
                         "ok" if code == 0 else "err")
            time.sleep(2)

        self.log("확인", "head")
        if svcs:
            self.job_http([s["key"] for s in svcs])
        self.job_status()
        self.log("배포 끝.", "ok")
        if send != path:
            try:
                send.unlink()
            except Exception:
                pass

    def repack_without_bad(self, path: Path) -> Path:
        """위험한 파일만 빼고 다시 묶는다. 원본 zip 은 건드리지 않는다."""
        out = path.with_name(path.stem + "-안전" + path.suffix)
        bad = set(self.zip_bad)
        src = zipfile.ZipFile(path)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for info in src.infolist():
                if info.is_dir():
                    continue
                name = info.filename.replace("\\", "/")
                inner = name[len(self.zip_wrapper) + 1:] if self.zip_wrapper else name
                if inner in bad:
                    continue
                # 권한도 여기서 바로잡는다 — 윈도에서 만든 zip 이면 666 이 들어 있다
                z.writestr(unix_zipinfo(info.filename, base=info), src.read(info),
                           zipfile.ZIP_DEFLATED)
        left = [n for n in zipfile.ZipFile(out).namelist()
                if FORBIDDEN_RE.search(n) and not FORBIDDEN_OK.search(n)]
        if left:
            out.unlink(missing_ok=True)
            raise RuntimeError("빼고 다시 묶었는데도 위험한 파일이 남았다. 올리지 않는다.")
        self.log(f"  위험한 파일 {len(bad)}개를 빼고 다시 묶었다: {out.name}", "ok")
        return out

    def open_picker(self):
        if not self.repo_ok():
            messagebox.showerror(APP_NAME,
                                 "PC 프로젝트 폴더를 먼저 지정하라 (연결 설정 탭).")
            return
        FilePicker(self, self.repo())

    def refresh_picked(self):
        n = len(self.picked)
        self.v_picked.set(f"고른 파일 {n}개" if n else "고른 파일 없음")
        self.lb_picked.delete(0, "end")
        for rel in self.picked:
            self.lb_picked.insert("end", rel)

    def units_for_picked(self):
        """고른 파일들이 건드리는 서비스의 유닛을 추린다.

        화면(dist)만 바뀐 경우에는 재시작할 것이 없다 — nginx 가 파일을 바로 읽는다.
        """
        units, touched = [], []
        for rel in self.picked:
            svc = which_service(rel)
            if not svc:
                continue
            top = rel.split("/")[0]
            if svc["backend"] and top == svc["backend"] and svc["service"]:
                units.append(self.unit(svc))
                units += svc.get("extra_services", [])
                touched.append(svc["label"])
        return list(dict.fromkeys(units)), list(dict.fromkeys(touched))

    def build_service_tab(self):
        f = self.tab_service
        ttk.Label(f, text="서비스 상태", style="Head.TLabel").pack(anchor="w", pady=(0, 8))

        cols = ("service", "state", "port", "since")
        self.tree = ttk.Treeview(f, columns=cols, show="headings", height=9)
        for c, t, w in zip(cols, ("유닛", "상태", "포트", "동작 시간"), (220, 140, 90, 240)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="x")

        b = ttk.Frame(f)
        b.pack(fill="x", pady=10)
        ttk.Button(b, text="새로고침", command=lambda: self.start(self.job_status)).pack(side="left")
        ttk.Button(b, text="재시작", command=lambda: self.svc_action("restart")).pack(side="left", padx=6)
        ttk.Button(b, text="중지", command=lambda: self.svc_action("stop")).pack(side="left")
        ttk.Button(b, text="시작", command=lambda: self.svc_action("start")).pack(side="left", padx=6)
        ttk.Button(b, text="로그 200줄", command=lambda: self.svc_action("log")).pack(side="left")
        ttk.Button(b, text="따라가기 30초", command=lambda: self.svc_action("follow")).pack(side="left", padx=6)

        ttk.Label(f, text="표에서 유닛을 고른 뒤 버튼을 누른다. 재시작·중지는 한 번 더 묻는다.",
                  style="Dim.TLabel").pack(anchor="w")

    def build_check_tab(self):
        f = self.tab_check
        ttk.Label(f, text="서버 점검", style="Head.TLabel").grid(row=0, column=0, columnspan=3,
                                                              sticky="w", pady=(0, 10))
        items = [
            ("한 번에 점검", "디스크·메모리·포트·nginx 문법·각 사이트 응답을 차례로 본다",
             self.job_healthcheck),
            ("사이트 응답 확인", "다섯 도메인에 HTTPS 로 요청해 응답 코드를 본다", self.job_http),
            ("nginx 문법 검사", "nginx -t", self.job_nginx_test),
            ("열린 포트 보기", "ss -ltnp — 8000·8010·8100·8200·8300 이 떠 있는지", self.job_ports),
            ("디스크·메모리", "df -h / free -h — 50GB 서버라 로그가 쌓이면 금방 찬다", self.job_disk),
            ("DB 백업 받기", "pg_dump 로 서버에 gz 백업을 만든다 (내려받지는 않는다)", self.job_dbdump),
        ]
        for i, (label, desc, fn) in enumerate(items, start=1):
            ttk.Button(f, text=label, width=20,
                       command=lambda fn=fn: self.start(fn)).grid(row=i, column=0, sticky="w", pady=3)
            ttk.Label(f, text=desc, style="Dim.TLabel").grid(row=i, column=1, sticky="w", padx=10)

    def build_console_tab(self):
        f = self.tab_console
        ttk.Label(f, text="원격 명령", style="Head.TLabel").pack(anchor="w", pady=(0, 8))
        row = ttk.Frame(f)
        row.pack(fill="x")
        self.v_cmd = tk.StringVar()
        e = ttk.Entry(row, textvariable=self.v_cmd)
        e.pack(side="left", fill="x", expand=True)
        e.bind("<Return>", lambda _e: self.start(self.job_cmd))
        ttk.Button(row, text="실행", command=lambda: self.start(self.job_cmd)).pack(side="left", padx=6)

        quick = ttk.LabelFrame(f, text="자주 쓰는 것", padding=8)
        quick.pack(fill="x", pady=10)
        presets = [
            ("서비스 전체 상태", "systemctl --no-pager --plain status udt-backend diary-backend "
                            "research-backend work-backend nginx | head -60"),
            ("백엔드 로그(최근)", "journalctl -u udt-backend -n 60 --no-pager"),
            ("기록해 로그(최근)", "journalctl -u diary-backend -n 60 --no-pager"),
            ("업무 로그(최근)", "journalctl -u work-backend -n 60 --no-pager"),
            ("학교 수 세기", "cd /root/hs-portal/backend && .venv/bin/python -c "
                        "\"from app.database import SessionLocal; from app import models; "
                        "s=SessionLocal(); print('학교', s.query(models.School).count(), '개교')\""),
            ("디스크 큰 것 10개", "du -xh /root --max-depth=3 2>/dev/null | sort -rh | head -10"),
        ]
        for i, (label, cmd) in enumerate(presets):
            ttk.Button(quick, text=label,
                       command=lambda c=cmd: (self.v_cmd.set(c), self.start(self.job_cmd))) \
                .grid(row=i // 3, column=i % 3, sticky="we", padx=4, pady=3)
        for c in range(3):
            quick.columnconfigure(c, weight=1)

        ttk.Label(f, text="여기서 친 명령은 root 권한으로 그대로 돈다. rm 은 조심할 것.",
                  style="Dim.TLabel").pack(anchor="w")

    def build_conn_tab(self):
        f = self.tab_conn
        self.v_host = tk.StringVar(value=self.cfg.get("host", ""))
        self.v_port = tk.StringVar(value=str(self.cfg.get("port", 22)))
        self.v_user = tk.StringVar(value=self.cfg.get("user", "root"))
        self.v_pw = tk.StringVar(value=self.cfg.get("password", ""))
        self.v_key = tk.StringVar(value=self.cfg.get("keyfile", ""))
        self.v_repo = tk.StringVar(value=self.cfg.get("repo", ""))
        self.v_rroot = tk.StringVar(value=self.cfg.get("remote_root", REMOTE_ROOT))
        self.v_savepw = tk.BooleanVar(value=bool(self.cfg.get("save_password", False)))

        rows = [
            ("서버 주소", self.v_host, None),
            ("포트", self.v_port, None),
            ("계정", self.v_user, None),
        ]
        r = 0
        ttk.Label(f, text="접속", style="Head.TLabel").grid(row=r, column=0, sticky="w", pady=(0, 8))
        r += 1
        for label, var, _ in rows:
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=3)
            ttk.Entry(f, textvariable=var, width=46).grid(row=r, column=1, sticky="w")
            r += 1

        ttk.Label(f, text="비밀번호").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Entry(f, textvariable=self.v_pw, show="•", width=46).grid(row=r, column=1, sticky="w")
        ttk.Checkbutton(f, text="이 PC 에 저장 (권장하지 않음)", variable=self.v_savepw) \
            .grid(row=r, column=2, sticky="w", padx=8)
        r += 1

        ttk.Label(f, text="키 파일(pem)").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Entry(f, textvariable=self.v_key, width=46).grid(row=r, column=1, sticky="w")
        ttk.Button(f, text="찾기", command=self.pick_key).grid(row=r, column=2, sticky="w", padx=8)
        r += 1

        ttk.Separator(f).grid(row=r, column=0, columnspan=3, sticky="we", pady=12)
        r += 1
        ttk.Label(f, text="경로", style="Head.TLabel").grid(row=r, column=0, sticky="w", pady=(0, 8))
        r += 1
        ttk.Label(f, text="PC 프로젝트 폴더").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Entry(f, textvariable=self.v_repo, width=46).grid(row=r, column=1, sticky="w")
        ttk.Button(f, text="찾기", command=self.pick_repo).grid(row=r, column=2, sticky="w", padx=8)
        r += 1
        ttk.Label(f, text="서버 프로젝트 경로").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Entry(f, textvariable=self.v_rroot, width=46).grid(row=r, column=1, sticky="w")
        r += 1

        b = ttk.Frame(f)
        b.grid(row=r, column=0, columnspan=3, sticky="w", pady=14)
        ttk.Button(b, text="설정 저장", command=self.save_config).pack(side="left")
        ttk.Button(b, text="연결 시험", command=self.do_connect).pack(side="left", padx=8)
        r += 1
        ttk.Label(f, text=f"설정 파일: {CONFIG_PATH}\n"
                          "비밀번호는 저장을 켜지 않으면 남지 않는다. 키 파일 방식을 권한다.",
                  style="Dim.TLabel").grid(row=r, column=0, columnspan=3, sticky="w")

    def build_log(self):
        wrap = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        wrap.pack(fill="both", expand=True)
        head = ttk.Frame(wrap)
        head.pack(fill="x")
        ttk.Label(head, text="기록", style="Head.TLabel").pack(side="left")
        ttk.Button(head, text="지우기", command=lambda: (
            self.txt.config(state="normal"), self.txt.delete("1.0", "end"),
            self.txt.config(state="disabled"))).pack(side="right")
        ttk.Button(head, text="파일로 저장", command=self.save_log).pack(side="right", padx=6)

        self.txt = tk.Text(wrap, height=14, wrap="none", bg="#11141a", fg="#d7dbe0",
                           insertbackground="#d7dbe0", font=("Consolas", 9), relief="flat")
        sb = ttk.Scrollbar(wrap, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        self.txt.pack(side="left", fill="both", expand=True, pady=(6, 0))
        sb.pack(side="right", fill="y", pady=(6, 0))
        self.txt.tag_config("head", foreground="#7fb3ff")
        self.txt.tag_config("ok", foreground="#7ddc8a")
        self.txt.tag_config("warn", foreground="#ffc46b")
        self.txt.tag_config("err", foreground="#ff8080")
        self.txt.tag_config("dim", foreground="#8892a0")
        self.txt.config(state="disabled")

    # ── 도우미 ────────────────────────────────────────────────────────────
    def pick_key(self):
        p = filedialog.askopenfilename(title="SSH 키 파일 선택",
                                       filetypes=[("키 파일", "*.pem *.key *"), ("모든 파일", "*")])
        if p:
            self.v_key.set(p)

    def pick_repo(self):
        p = filedialog.askdirectory(title="hs-portal 폴더 선택")
        if p:
            self.v_repo.set(p)

    def save_log(self):
        p = filedialog.asksaveasfilename(defaultextension=".txt",
                                         initialfile=f"배포기록_{ts()}.txt")
        if p:
            Path(p).write_text(self.txt.get("1.0", "end"), encoding="utf-8")
            self.log(f"기록을 저장했다: {p}", "ok")

    def log(self, msg, tag=""):
        self.q.put(("log", msg, tag))

    def progress(self, done, total):
        self.q.put(("pb", done, total))

    def pump(self):
        """작업 스레드가 보낸 것을 화면에 옮긴다."""
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "log":
                    _, msg, tag = item
                    self.txt.config(state="normal")
                    stamp = datetime.now().strftime("%H:%M:%S")
                    self.txt.insert("end", f"[{stamp}] {msg}\n", tag or "")
                    self.txt.see("end")
                    self.txt.config(state="disabled")
                elif kind == "pb":
                    _, done, total = item
                    self.pb["maximum"] = max(total, 1)
                    self.pb["value"] = done
                elif kind == "state":
                    _, text, color = item
                    self.v_state.set(text)
                    self.lbl_state.configure(foreground=color)
                elif kind == "busy":
                    self.busy = bool(item[1])
                    st = "disabled" if self.busy else "normal"
                    self.btn_deploy.configure(state=st)
                    self.btn_conn.configure(state=st)
                elif kind == "rows":
                    self.tree.delete(*self.tree.get_children())
                    for row in item[1]:
                        self.tree.insert("", "end", values=row)
        except queue.Empty:
            pass
        self.root.after(80, self.pump)

    def start(self, fn):
        """작업을 스레드에서 돌린다. 한 번에 하나만."""
        if self.busy:
            self.log("아직 앞의 일이 안 끝났다.", "warn")
            return

        def wrapper():
            self.q.put(("busy", True))
            try:
                fn()
            except Exception as e:
                self.log(f"중단: {e}", "err")
                for ln in traceback.format_exc().splitlines()[-4:]:
                    self.log("  " + ln, "dim")
            finally:
                self.q.put(("busy", False))
                self.q.put(("pb", 0, 1))

        threading.Thread(target=wrapper, daemon=True).start()

    def need_remote(self):
        if not self.remote.connected:
            raise RuntimeError("서버에 먼저 연결하라 ('서버 연결' 단추).")

    def selected_keys(self):
        return [k for k, v in self.v_svc.items() if v.get()]

    # ── 연결 ──────────────────────────────────────────────────────────────
    def do_connect(self):
        if paramiko is None:
            messagebox.showerror(APP_NAME, "paramiko 가 설치돼 있지 않다.\n\n"
                                           "명령 프롬프트에서:\n    pip install paramiko")
            return
        self.start(self.job_connect)

    def job_connect(self):
        host = self.v_host.get().strip()
        if not host:
            raise RuntimeError("서버 주소가 비어 있다 (연결 설정 탭).")
        user = self.v_user.get().strip() or "root"
        port = self.v_port.get().strip() or "22"
        key = self.v_key.get().strip() or None
        pw = self.v_pw.get() or None

        if self.remote.connected:
            self.remote.close()
        self.log(f"접속 중… {user}@{host}:{port}", "head")
        self.remote.connect(host, port, user, password=pw, keyfile=key,
                            log=lambda m, t="dim": self.log(m, t))
        self.q.put(("state", f"● 연결됨  {self.remote.info}", "#1a7f37"))
        self.log("접속 성공", "ok")
        _, out = self.remote.run("hostname; uptime -p; df -h / | tail -1")
        for ln in out.splitlines():
            self.log("  " + ln, "dim")
        self.resolve_units()
        self.job_status()

    # ── 유닛 이름 맞추기 ─────────────────────────────────────────────────
    def resolve_units(self):
        """서버에 실제로 등록된 유닛 이름을 찾아 둔다.

        서비스마다 이름이 코드와 어긋나 있을 수 있다(연구·논문이 univ-backend
        로 등록돼 있다든지). 없는 이름으로 재시작을 걸면 조용히 아무 일도
        일어나지 않으므로, 붙을 때 한 번 맞춰 놓는다.
        """
        _, out = self.remote.run(
            "systemctl list-unit-files --type=service --no-legend --no-pager | awk '{print $1}'")
        have = {ln.strip().removesuffix(".service") for ln in out.splitlines() if ln.strip()}
        self.unit_of = {}
        for svc in SERVICES:
            if not svc["service"]:
                continue
            name = svc["service"]
            if name in have:
                self.unit_of[svc["key"]] = name
                continue
            found = next((a for a in svc.get("service_alts", []) if a in have), "")
            if found:
                self.unit_of[svc["key"]] = found
                self.log(f"  {svc['label']}: '{name}' 이 없어 '{found}' 로 잡았다", "warn")
            else:
                self.unit_of[svc["key"]] = name
                near = sorted(u for u in have
                              if any(w in u for w in ("backend", "udt", "udj", "univ",
                                                      "research", "diary", "work")))
                self.log(f"  {svc['label']}: 등록된 유닛을 못 찾았다 (찾은 이름: {name})", "warn")
                if near:
                    self.log(f"    서버에 있는 비슷한 유닛: {', '.join(near)}", "dim")

    def unit(self, key_or_svc) -> str:
        """서비스의 실제 유닛 이름. 아직 못 맞췄으면 정의된 이름 그대로."""
        svc = SERVICE_BY_KEY[key_or_svc] if isinstance(key_or_svc, str) else key_or_svc
        return getattr(self, "unit_of", {}).get(svc["key"], svc["service"])

    # ── 배포 ──────────────────────────────────────────────────────────────
    def prepare_local(self, keys):
        """프론트 빌드 + zip. (zip 경로) 를 준다."""
        repo = self.repo()
        if not self.repo_ok():
            raise RuntimeError(f"프로젝트 폴더가 이상하다: {repo}")

        if self.v_build.get():
            targets = [SERVICE_BY_KEY[k] for k in keys
                       if SERVICE_BY_KEY[k]["build"] and SERVICE_BY_KEY[k]["frontend"]]
            if targets:
                self.log("프론트 빌드", "head")
                for svc in targets:
                    npm_build(repo, svc["frontend"], self.log)
            static = [SERVICE_BY_KEY[k]["frontend"] for k in keys
                      if not SERVICE_BY_KEY[k]["build"] and SERVICE_BY_KEY[k]["frontend"]]
            for s in static:
                self.log(f"  {s}: 정적 파일이라 빌드 없이 그대로 올린다", "dim")

        self.log("zip 만들기", "head")
        out = repo.parent / f"deploy-{'-'.join(keys)}-{ts()}.zip"
        return build_zip(repo, keys, out, self.log)

    def prepare_picked(self):
        """고른 파일만 담은 zip. 경로는 저장소 기준 그대로 유지한다."""
        repo = self.repo()
        if not self.repo_ok():
            raise RuntimeError(f"프로젝트 폴더가 이상하다: {repo}")
        if not self.picked:
            raise RuntimeError("올릴 파일을 먼저 골라라 ('파일 고르기…').")

        items, missing = [], []
        for rel in self.picked:
            p = repo / rel
            if p.is_file():
                items.append((p, rel))
            else:
                missing.append(rel)
        if missing:
            raise RuntimeError("PC 에 없는 파일이 목록에 있다:\n  " + "\n  ".join(missing))

        self.log("zip 만들기 (고른 파일만)", "head")
        for _, rel in items:
            self.log(f"  담음: {rel}", "dim")
        out = repo.parent / f"deploy-files-{ts()}.zip"
        return finalize_zip(items, out, self.log)

    def job_zip_only(self):
        if self.v_mode.get() == "zip":
            self.inspect_zip()
            return
        if self.v_mode.get() == "files":
            z = self.prepare_picked()
        else:
            keys = self.selected_keys()
            if not keys:
                raise RuntimeError("서비스를 하나 이상 골라라.")
            z = self.prepare_local(keys)
        self.log(f"끝. zip 만 만들었다: {z}", "ok")

    def job_deploy(self):
        if self.v_mode.get() == "files":
            self.job_deploy_files()
            return
        if self.v_mode.get() == "zip":
            self.job_deploy_zip()
            return
        keys = self.selected_keys()
        if not keys:
            raise RuntimeError("서비스를 하나 이상 골라라.")
        self.need_remote()

        names = ", ".join(SERVICE_BY_KEY[k]["label"] for k in keys)
        if not messagebox.askyesno(APP_NAME,
                                   f"다음을 서버에 올린다:\n\n    {names}\n\n"
                                   f"서버의 같은 파일은 덮어쓴다. 진행할까?"):
            self.log("취소했다.", "warn")
            return

        zip_path = self.prepare_local(keys)
        rroot = self.v_rroot.get().strip() or REMOTE_ROOT

        self.log("업로드", "head")
        self.remote.run(f"mkdir -p {REMOTE_UPLOAD_DIR} {REMOTE_BACKUP_DIR}", check=True)
        rpath = f"{REMOTE_UPLOAD_DIR}/{zip_path.name}"
        t0 = time.time()
        self.remote.upload(zip_path, rpath, self.progress)
        mb = zip_path.stat().st_size / 1024 / 1024
        self.log(f"  올림: {zip_path.name} ({mb:.1f} MB, {time.time() - t0:.1f}초)", "ok")

        # 서버 백업 — .venv·node_modules 는 빼고 코드만
        if self.v_backup.get():
            self.log("서버 폴더 백업", "head")
            dirs = []
            for k in keys:
                s = SERVICE_BY_KEY[k]
                if s["backend"]:
                    dirs.append(s["backend"])
                if s["frontend"]:
                    dirs.append(s["frontend"])
            dirs = list(dict.fromkeys(dirs))
            tar = f"{REMOTE_BACKUP_DIR}/before-{'-'.join(keys)}-{ts()}.tar.gz"
            cmd = (f"cd {rroot} && tar --exclude='.venv' --exclude='node_modules' "
                   f"--exclude='__pycache__' -czf {tar} {' '.join(dirs)} 2>/dev/null; "
                   f"ls -lh {tar}")
            self.remote.run(cmd, self.log)
            self.log(f"  백업: {tar}", "ok")

        # .env 보관 → 풀기 → 되돌리기
        self.log("서버에 풀기", "head")
        stamp = ts()
        env_dirs = [SERVICE_BY_KEY[k]["backend"] for k in keys if SERVICE_BY_KEY[k]["backend"]]
        # 우리업무는 기록해 venv 를 쓰지만 .env 는 제 것을 쓴다 — 위 목록에 이미 들어간다
        keep = " ".join(env_dirs)
        script = f"""
set -e
cd {rroot}
for d in {keep or '""'}; do
  if [ -f "$d/.env" ]; then cp -a "$d/.env" "/root/env-keep-{stamp}-$(echo $d | tr / _).env"; fi
done
{remote_extract_script(rpath, rroot)}
cd {rroot}
for d in {keep or '""'}; do
  f="/root/env-keep-{stamp}-$(echo $d | tr / _).env"
  if [ -f "$f" ]; then cp -a "$f" "$d/.env"; fi
done
echo "풀기 완료"
"""
        code, _ = self.remote.run(f"bash -lc {shquote(script)}", self.log)
        if code != 0:
            raise RuntimeError("서버에서 압축을 푸는 중 실패했다. 위 출력 확인.")
        self.log("  .env 보관 → unzip -o → .env 복원 까지 끝", "ok")

        # 파이썬 의존성
        if self.v_pip.get():
            self.log("파이썬 의존성", "head")
            for k in keys:
                s = SERVICE_BY_KEY[k]
                if not s["backend"]:
                    continue
                venv = s["venv"] or s["backend"]
                pip = f"{rroot}/{venv}/.venv/bin/pip"
                req = f"{rroot}/{s['backend']}/requirements.txt"
                self.log(f"  {s['label']}: {pip} install -r requirements.txt")
                code, _ = self.remote.run(f"test -f {pip} && test -f {req} && "
                                          f"{pip} install -q -r {req} && echo '  설치 완료'",
                                          self.log)
                if code != 0:
                    self.log(f"  건너뜀 — venv 나 requirements 가 없다 ({venv})", "warn")

        # 재시작
        if self.v_restart.get():
            self.log("서비스 재시작", "head")
            units = []
            for k in keys:
                s = SERVICE_BY_KEY[k]
                if s["service"]:
                    units.append(self.unit(s))
                units += s.get("extra_services", [])
            # 화면만 바뀐 서비스(cs 등)는 재시작할 프로세스가 없다
            units = [u for u in dict.fromkeys(units)]
            if units:
                # 유닛 하나가 없다고 배포 전체를 실패로 끝내지는 않는다. 파일은
                # 이미 올라갔으므로, 무엇이 되고 무엇이 안 됐는지 알려주는 편이 낫다.
                for u in units:
                    code, _ = self.remote.run(f"systemctl restart {u}", self.log)
                    if code == 0:
                        self.log(f"  재시작: {u}", "ok")
                    else:
                        self.log(f"  재시작 실패: {u} — 유닛 이름이 맞는지 확인하라 "
                                 f"(콘솔 탭: systemctl list-units --type=service | grep backend)",
                                 "err")
            else:
                self.log("  재시작할 프로세스가 없다 (정적 화면만 바뀌었다)", "dim")
            # nginx 는 정적 파일을 바로 읽으므로 건드릴 필요가 없다
            time.sleep(2)

        self.log("확인", "head")
        self.job_http(keys)
        self.job_status()
        self.log("배포 끝.", "ok")
        try:
            zip_path.unlink()
        except Exception:
            pass

    def job_deploy_files(self):
        """고른 파일만 올린다. 서버의 나머지는 건드리지 않는다."""
        self.need_remote()
        rroot = self.v_rroot.get().strip() or REMOTE_ROOT

        warns = [w for w in (source_warning(r) for r in self.picked) if w]
        units, touched = self.units_for_picked()
        head = "\n".join("    " + r for r in self.picked[:15])
        if len(self.picked) > 15:
            head += f"\n    … 그 밖 {len(self.picked) - 15}개"
        msg = (f"파일 {len(self.picked)}개를 서버에 덮어쓴다.\n\n{head}\n\n"
               + (f"재시작할 서비스: {', '.join(touched)}\n\n" if units and self.v_restart.get()
                  else "재시작할 서비스 없음 (화면 파일만 바뀐다)\n\n")
               + ("확인할 것이 있다:\n" + "\n".join("  · " + w.split(" — ")[0] for w in warns)
                  + "\n\n" if warns else "")
               + "진행할까?")
        if not messagebox.askyesno(APP_NAME, msg):
            self.log("취소했다.", "warn")
            return
        for w in warns:
            self.log("  주의: " + w, "warn")

        zip_path = self.prepare_picked()

        self.log("업로드", "head")
        self.remote.run(f"mkdir -p {REMOTE_UPLOAD_DIR} {REMOTE_BACKUP_DIR}", check=True)
        rpath = f"{REMOTE_UPLOAD_DIR}/{zip_path.name}"
        self.remote.upload(zip_path, rpath, self.progress)
        self.log(f"  올림: {zip_path.name} ({zip_path.stat().st_size / 1024:,.1f} KB)", "ok")

        # 덮어쓸 파일만 골라 백업한다 — 통째로 tar 뜰 이유가 없다
        if self.v_backup.get():
            self.log("덮어쓸 파일 백업", "head")
            tar = f"{REMOTE_BACKUP_DIR}/files-{ts()}.tar.gz"
            listed = " ".join(shquote(r) for r in self.picked)
            self.remote.run(
                f"cd {rroot} && for f in {listed}; do [ -f \"$f\" ] && echo \"$f\"; done "
                f"> /tmp/tolist.txt; tar -czf {tar} -T /tmp/tolist.txt 2>/dev/null; "
                f"echo \"백업한 파일 $(wc -l < /tmp/tolist.txt)개\"; ls -lh {tar} 2>/dev/null "
                f"|| echo '  (서버에 없던 새 파일들이라 백업할 것이 없다)'", self.log)

        self.log("서버에 풀기", "head")
        script = "set -e\n" + remote_extract_script(rpath, rroot) + "echo '풀기 완료'\n"
        code, _ = self.remote.run(f"bash -lc {shquote(script)}", self.log)
        if code != 0:
            raise RuntimeError("서버에서 압축을 푸는 중 실패했다. 위 출력 확인.")

        # 올라간 파일이 서버에서 실제로 바뀌었는지 눈으로 확인할 수 있게
        self.remote.run(f"cd {rroot} && ls -l --time-style=+%m-%d\\ %H:%M "
                        + " ".join(shquote(r) for r in self.picked[:15]), self.log)

        if self.v_restart.get() and units:
            self.log("서비스 재시작", "head")
            for u in units:
                code, _ = self.remote.run(f"systemctl restart {u}", self.log)
                self.log(f"  재시작: {u}" if code == 0 else f"  재시작 실패: {u}",
                         "ok" if code == 0 else "err")
            time.sleep(2)
        elif self.v_restart.get():
            self.log("  재시작할 프로세스가 없다 (화면 파일만 바뀌었다)", "dim")

        self.log("확인", "head")
        keys = list(dict.fromkeys(
            [s["key"] for s in (which_service(r) for r in self.picked) if s]))
        if keys:
            self.job_http(keys)
        self.job_status()
        self.log("배포 끝.", "ok")
        try:
            zip_path.unlink()
        except Exception:
            pass

    # ── 서비스 ────────────────────────────────────────────────────────────
    def job_status(self):
        self.need_remote()
        units = []
        for s in SERVICES:
            if s["service"]:
                units.append(self.unit(s))
            units += s.get("extra_services", [])
        units += SYSTEM_UNITS
        units = list(dict.fromkeys(units))

        _, out = self.remote.run(
            "for u in " + " ".join(units) + "; do "
            "st=$(systemctl is-active $u 2>/dev/null); "
            "since=$(systemctl show -p ActiveEnterTimestamp --value $u 2>/dev/null); "
            "echo \"$u|$st|$since\"; done")
        port_of = {}
        for s in SERVICES:
            if s["service"]:
                port_of[self.unit(s)] = s["port"]
        port_of.setdefault("udt-audio", 8010)
        port_of["nginx"] = 80

        rows = []
        for ln in out.splitlines():
            if "|" not in ln:
                continue
            u, st, since = (ln.split("|") + ["", ""])[:3]
            mark = "● 동작 중" if st == "active" else ("○ " + (st or "없음"))
            rows.append((u, mark, port_of.get(u, ""), since.strip()))
        self.q.put(("rows", rows))
        dead = [r[0] for r in rows if not r[1].startswith("●")]
        if dead:
            self.log("동작 중이 아닌 유닛: " + ", ".join(dead), "warn")

    def svc_action(self, what):
        sel = self.tree.selection()
        if not sel:
            self.log("표에서 유닛을 먼저 고른다.", "warn")
            return
        unit = self.tree.item(sel[0])["values"][0]
        if what in ("restart", "stop") and not messagebox.askyesno(
                APP_NAME, f"{unit} 을(를) {'재시작' if what == 'restart' else '중지'}할까?"):
            return

        def job():
            self.need_remote()
            if what == "log":
                self.log(f"{unit} 최근 로그", "head")
                self.remote.run(f"journalctl -u {unit} -n 200 --no-pager", self.log)
            elif what == "follow":
                self.log(f"{unit} 로그 30초 따라가기", "head")
                self.remote.run(f"timeout 30 journalctl -u {unit} -f --no-pager", self.log)
            else:
                self.log(f"{unit} {what}", "head")
                self.remote.run(f"systemctl {what} {unit}", self.log, check=True)
                time.sleep(1.5)
                self.job_status()
        self.start(job)

    # ── 점검 ──────────────────────────────────────────────────────────────
    def job_healthcheck(self):
        self.need_remote()
        self.log("서버 점검", "head")
        self.job_disk()
        self.job_ports()
        self.job_nginx_test()
        self.job_http()
        self.job_status()
        self.log("점검 끝.", "ok")

    def job_disk(self):
        self.need_remote()
        self.log("디스크·메모리", "head")
        self.remote.run("df -h / | tail -1; free -h | head -2", self.log)

    def job_ports(self):
        self.need_remote()
        self.log("열린 포트", "head")
        self.remote.run("ss -ltnp 2>/dev/null | grep -E '127.0.0.1:(8000|8010|8100|8200|8300)' "
                        "|| echo '  127.0.0.1 대기 포트를 못 찾았다'", self.log)

    def job_nginx_test(self):
        self.need_remote()
        self.log("nginx 문법", "head")
        code, _ = self.remote.run("nginx -t", self.log)
        self.log("  문법 정상" if code == 0 else "  문법 오류 — 위 출력 확인",
                 "ok" if code == 0 else "err")

    def job_http(self, keys=None):
        self.need_remote()
        targets = [SERVICE_BY_KEY[k] for k in keys] if keys else SERVICES
        self.log("사이트 응답", "head")
        for s in targets:
            if not s["domain"]:
                continue
            _, out = self.remote.run(
                f"curl -s -o /dev/null -m 10 -w '%{{http_code}} %{{time_total}}s' https://{s['domain']}/ "
                f"|| echo '요청 실패'")
            code = out.strip().split()[0] if out.strip() else "?"
            tag = "ok" if code.startswith(("2", "3")) else "err"
            self.log(f"  {s['label']:<18} https://{s['domain']}  →  {out.strip()}", tag)

    def job_dbdump(self):
        self.need_remote()
        db = simpledialog.askstring(APP_NAME, "백업할 DB 이름 (예: udt, diary, univ, work)",
                                    parent=self.root)
        if not db:
            return
        self.log(f"{db} 백업", "head")
        path = f"/root/db-backups/{db}-{ts()}.sql.gz"
        self.remote.run(f"mkdir -p /root/db-backups && "
                        f"sudo -u postgres pg_dump {db} | gzip > {path} && ls -lh {path}",
                        self.log, check=True)
        self.log(f"  받아뒀다: {path}", "ok")

    # ── 콘솔 ──────────────────────────────────────────────────────────────
    def job_cmd(self):
        self.need_remote()
        cmd = self.v_cmd.get().strip()
        if not cmd:
            return
        self.log(f"$ {cmd}", "head")
        code, _ = self.remote.run(f"bash -lc {shquote(cmd)}", self.log)
        self.log(f"  (종료코드 {code})", "dim" if code == 0 else "err")

    # ── 종료 ──────────────────────────────────────────────────────────────
    def on_close(self):
        if self.busy and not messagebox.askyesno(APP_NAME, "작업이 도는 중이다. 정말 닫을까?"):
            return
        try:
            self.remote.close()
        except Exception:
            pass
        self.root.destroy()


class FilePicker(tk.Toplevel):
    """올릴 파일을 그때그때 고르는 창.

    저장소 전체를 늘어놓으면 수천 개라 못 고른다. 그래서 기본은 **최근에
    바뀐 순**으로 보여주고, 검색어와 기간, git 변경분으로 좁힌다.
    """

    def __init__(self, app, repo: Path):
        super().__init__(app.root)
        self.app, self.repo = app, repo
        self.title("올릴 파일 고르기")
        self.geometry("900x620")
        self.transient(app.root)

        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="검색").pack(side="left")
        self.v_q = tk.StringVar()
        e = ttk.Entry(top, textvariable=self.v_q, width=30)
        e.pack(side="left", padx=(6, 14))
        e.bind("<KeyRelease>", lambda _e: self.refresh())

        ttk.Label(top, text="기간").pack(side="left")
        self.v_age = tk.StringVar(value="전체")
        cb = ttk.Combobox(top, textvariable=self.v_age, state="readonly", width=10,
                          values=["전체", "1시간", "24시간", "7일", "30일"])
        cb.pack(side="left", padx=(6, 14))
        cb.bind("<<ComboboxSelected>>", lambda _e: self.refresh())

        self.v_git = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="git 변경분만", variable=self.v_git,
                        command=self.refresh).pack(side="left")
        ttk.Button(top, text="새로고침", command=self.refresh).pack(side="right")

        mid = ttk.Frame(self, padding=(10, 0))
        mid.pack(fill="both", expand=True)

        left = ttk.Frame(mid)
        left.pack(side="left", fill="both", expand=True)
        ttk.Label(left, text="저장소 파일 (최근 바뀐 순)").pack(anchor="w")
        self.lb = tk.Listbox(left, selectmode="extended", font=("Consolas", 9),
                             activestyle="none")
        sb = ttk.Scrollbar(left, command=self.lb.yview)
        self.lb.configure(yscrollcommand=sb.set)
        self.lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.lb.bind("<Double-Button-1>", lambda _e: self.add_selected())

        btns = ttk.Frame(mid, padding=8)
        btns.pack(side="left", fill="y")
        ttk.Button(btns, text="추가  →", command=self.add_selected).pack(pady=3)
        ttk.Button(btns, text="전부 추가", command=self.add_all).pack(pady=3)
        ttk.Button(btns, text="←  빼기", command=self.remove_selected).pack(pady=(18, 3))
        ttk.Button(btns, text="모두 비우기", command=self.clear).pack(pady=3)
        ttk.Button(btns, text="직접 찾기…", command=self.browse).pack(pady=(18, 3))

        right = ttk.Frame(mid)
        right.pack(side="left", fill="both", expand=True)
        self.v_count = tk.StringVar(value="고른 파일 0개")
        ttk.Label(right, textvariable=self.v_count).pack(anchor="w")
        self.lb2 = tk.Listbox(right, selectmode="extended", font=("Consolas", 9),
                              activestyle="none")
        sb2 = ttk.Scrollbar(right, command=self.lb2.yview)
        self.lb2.configure(yscrollcommand=sb2.set)
        self.lb2.pack(side="left", fill="both", expand=True)
        sb2.pack(side="right", fill="y")

        bottom = ttk.Frame(self, padding=10)
        bottom.pack(fill="x")
        self.v_note = tk.StringVar(value="")
        ttk.Label(bottom, textvariable=self.v_note, style="Dim.TLabel",
                  wraplength=700).pack(side="left")
        ttk.Button(bottom, text="닫기", command=self.destroy).pack(side="right")

        self.rows = []
        self.refresh()
        self.sync()

    # ── 목록 만들기 ───────────────────────────────────────────────────────
    def candidates(self):
        """저장소를 훑어 (수정시각, 상대경로) 목록을 만든다. 빼는 규칙은 zip 과 같다."""
        out = []
        for root, dirs, files in os.walk(self.repo):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for f in files:
                if SKIP_FILE_RE.search(f):
                    continue
                p = Path(root) / f
                try:
                    out.append((p.stat().st_mtime, str(p.relative_to(self.repo)).replace("\\", "/")))
                except OSError:
                    pass
        out.sort(reverse=True)
        return out

    def git_changed(self):
        """git 이 바뀐 것으로 보는 파일. 저장소가 위 폴더에 있을 수도 있다."""
        for base in (self.repo, self.repo.parent):
            try:
                # core.quotePath 를 끄지 않으면 한글 파일 이름이 "\354\203\210…"
                # 처럼 8진수로 나와 경로가 안 맞는다.
                r = subprocess.run(["git", "-c", "core.quotePath=false",
                                    "-C", str(base), "status", "--porcelain"],
                                   capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=20)
            except Exception:
                continue
            if r.returncode != 0:
                continue
            got = set()
            for ln in r.stdout.splitlines():
                path = ln[3:].strip().strip('"')
                if " -> " in path:                 # 이름이 바뀐 경우
                    path = path.split(" -> ")[-1]
                full = (base / path).resolve()
                try:
                    got.add(str(full.relative_to(self.repo.resolve())).replace("\\", "/"))
                except ValueError:
                    pass
            if got:
                return got
        return set()

    def refresh(self):
        if not hasattr(self, "_all"):
            self._all = self.candidates()
        rows = self._all
        limit = {"전체": 0, "1시간": 3600, "24시간": 86400,
                 "7일": 604800, "30일": 2592000}[self.v_age.get()]
        if limit:
            cut = time.time() - limit
            rows = [r for r in rows if r[0] >= cut]
        if self.v_git.get():
            g = self.git_changed()
            rows = [r for r in rows if r[1] in g]
            if not g:
                self.v_note.set("git 변경분을 찾지 못했다 (git 저장소가 아니거나 바뀐 파일이 없다).")
        for w in self.v_q.get().lower().split():
            rows = [r for r in rows if w in r[1].lower()]
        self.rows = rows[:3000]
        self.lb.delete(0, "end")
        for mt, rel in self.rows:
            self.lb.insert("end", f"{datetime.fromtimestamp(mt):%m-%d %H:%M}  {rel}")
        if not self.v_git.get():
            self.v_note.set(f"{len(self.rows)}개 보임 (전체 {len(self._all)}개)")

    # ── 고르기 ────────────────────────────────────────────────────────────
    def add(self, rels):
        warned = []
        for rel in rels:
            if rel in self.app.picked:
                continue
            self.app.picked.append(rel)
            w = source_warning(rel)
            if w:
                warned.append(w)
        self.sync()
        if warned:
            messagebox.showwarning("확인할 것", "\n\n".join(warned[:6]), parent=self)

    def add_selected(self):
        self.add([self.rows[i][1] for i in self.lb.curselection()])

    def add_all(self):
        self.add([r[1] for r in self.rows])

    def remove_selected(self):
        for i in sorted(self.lb2.curselection(), reverse=True):
            del self.app.picked[i]
        self.sync()

    def clear(self):
        self.app.picked.clear()
        self.sync()

    def browse(self):
        paths = filedialog.askopenfilenames(title="올릴 파일 고르기",
                                            initialdir=str(self.repo), parent=self)
        rels = []
        for p in paths:
            try:
                rels.append(str(Path(p).resolve().relative_to(self.repo.resolve())).replace("\\", "/"))
            except ValueError:
                messagebox.showerror("안 됨", f"저장소 밖 파일은 올릴 수 없다:\n{p}", parent=self)
        self.add(rels)

    def sync(self):
        self.lb2.delete(0, "end")
        for rel in self.app.picked:
            self.lb2.insert("end", rel)
        self.v_count.set(f"고른 파일 {len(self.app.picked)}개")
        self.app.refresh_picked()


def shquote(s: str) -> str:
    """bash -lc 에 통째로 넘기기 위한 작은따옴표 감싸기."""
    return "'" + s.replace("'", "'\\''") + "'"


def crash_report(exc_text: str) -> None:
    """창 없이(pythonw) 띄운 탓에 조용히 죽는 일이 없도록, 기록을 남기고 알린다."""
    log = Path(__file__).resolve().parent / "오류기록.txt"
    body = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {APP_NAME} v{APP_VER}\n" \
           f"파이썬: {sys.version}\n실행 파일: {sys.executable}\n\n{exc_text}\n"
    try:
        with open(log, "a", encoding="utf-8") as f:
            f.write(body + "\n" + "-" * 70 + "\n")
    except Exception:
        log = None

    msg = (f"프로그램을 시작하지 못했습니다.\n\n{exc_text.strip().splitlines()[-1]}\n\n"
           + (f"자세한 내용: {log}" if log else ""))
    try:                       # 되도록 tk 로
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror(APP_NAME, msg)
        r.destroy()
        return
    except Exception:
        pass
    try:                       # tk 조차 안 되면 윈도 기본 대화상자로
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, APP_NAME, 0x10)
    except Exception:
        # 콘솔 인코딩(cp949)에 없는 글자가 섞여 있으면 여기서 또 죽는다.
        # 마지막 알림 수단이므로 못 적는 글자는 버리고라도 내보낸다.
        try:
            enc = (getattr(sys.stderr, "encoding", None) or "utf-8")
            sys.stderr.write(body.encode(enc, "replace").decode(enc, "replace") + "\n")
        except Exception:
            pass


def main():
    root = tk.Tk()
    try:
        root.call("tk", "scaling", 1.2)
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        crash_report(traceback.format_exc())
        sys.exit(1)
