# -*- coding: utf-8 -*-
"""실행 전 확인 — 무엇이 없어서 안 뜨는지 한 줄로 알려준다.

종료코드
    0  다 갖춰졌다
    2  paramiko 만 없다 (배치가 알아서 설치하고 다시 부른다)
    1  그 밖의 문제 (tkinter 없음 등) — 사람이 손봐야 한다
"""
import sys
import os

print("파이썬:", sys.version.replace("\n", " "))
print("실행 파일:", sys.executable)

problems = []

try:
    import tkinter
    root_ok = True
    try:
        r = tkinter.Tk()
        r.withdraw()
        r.destroy()
    except Exception as e:
        root_ok = False
        problems.append(
            "tkinter 는 있는데 창을 못 연다: %s\n"
            "  → 파이썬을 다시 설치하면서 'tcl/tk and IDLE' 을 켜야 한다." % e)
    if root_ok:
        print("tkinter: 정상 (Tk %s)" % tkinter.TkVersion)
except Exception as e:
    problems.append(
        "tkinter 가 없다: %s\n"
        "  → 파이썬 설치 관리자에서 'tcl/tk and IDLE' 을 켜고 다시 설치한다." % e)

need_paramiko = False
try:
    import paramiko
    print("paramiko:", paramiko.__version__)
except Exception:
    need_paramiko = True
    print("paramiko: 없음")

here = os.path.dirname(os.path.abspath(__file__))
main_file = os.path.join(here, "udj_deploy.pyw")
if not os.path.isfile(main_file):
    problems.append("udj_deploy.pyw 가 같은 폴더에 없다: %s" % here)
else:
    # 문법이 깨진 채로 배포되지 않았는지 미리 본다
    try:
        import py_compile
        py_compile.compile(main_file, cfile=os.path.join(
            here, "__pycache__", "precheck.pyc"), doraise=True)
        print("udj_deploy.pyw: 문법 정상")
    except Exception as e:
        problems.append("udj_deploy.pyw 를 읽을 수 없다: %s" % e)

if problems:
    print()
    for p in problems:
        print("[문제]", p)
    sys.exit(1)

if need_paramiko:
    sys.exit(2)

print("확인 완료 — 실행할 수 있다.")
sys.exit(0)
