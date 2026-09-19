"""기록해 통합 테스트.

    DATABASE_URL="sqlite:///./_test.db" SECRET_KEY=test python -m app.full_test
    rm -f _test.db

UDJ 계정 서버는 가짜로 대신한다. 실제 연동은 서버를 둘 다 띄워 확인할 것.
운영 DB 를 건드리지 않도록 반드시 별도 DATABASE_URL 로 실행한다.
"""

import sys
from datetime import date, datetime, timedelta

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("✅ " if cond else "❌ ") + name + ("" if cond or not detail else f"\n     └ {detail}"))


def section(title):
    print(f"\n── {title} " + "─" * max(0, 44 - len(title)))


def main() -> int:
    from fastapi.testclient import TestClient
    import app.main as m
    import app.udj as udj_mod

    # UDJ 계정 서버 대역. 이 테스트의 관심사는 기록해 쪽 로직이다.
    store = {}
    next_id = [100]

    def fake_call(method, path, **kw):
        from fastapi import HTTPException
        body = kw.get("json") or {}
        if path == "/login":
            u = store.get(body.get("email"))
            if not u or u["password"] != body.get("password"):
                raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 맞지 않습니다.")
            return {k: v for k, v in u.items() if k != "password"}
        if path == "/users" and method == "POST":
            if body["email"] in store:
                raise HTTPException(status_code=400, detail="이미 가입된 이메일입니다.")
            next_id[0] += 1
            u = {
                "udj_user_id": next_id[0], "email": body["email"], "name": body["name"],
                "role": "student", "phone": body.get("phone", ""),
                "password": body["password"], "department": "", "grade": None,
                "school_id": None, "school_name": "", "verified": False,
                "teacher_udj_id": None, "class_name": "", "is_active": True,
            }
            store[body["email"]] = u
            return {"profile": {k: v for k, v in u.items() if k != "password"},
                    "guardian_consent_required": False}
        if path.startswith("/users/") and path.endswith("/change-password"):
            uid = int(path.split("/")[2])
            u = next(x for x in store.values() if x["udj_user_id"] == uid)
            if u["password"] != body.get("current_password"):
                raise HTTPException(status_code=400, detail="현재 비밀번호가 맞지 않습니다.")
            u["password"] = body["new_password"]
            return {"ok": True}
        if path.startswith("/users/") and path.endswith("/delete"):
            uid = int(path.split("/")[2])
            email = next(k for k, v in store.items() if v["udj_user_id"] == uid)
            if store[email]["password"] != body.get("password"):
                raise HTTPException(status_code=400, detail="비밀번호가 일치하지 않습니다.")
            del store[email]
            return {"ok": True}
        if path.startswith("/users/") and method == "PATCH":
            uid = int(path.split("/")[2])
            u = next(x for x in store.values() if x["udj_user_id"] == uid)
            u.update({k: v for k, v in body.items() if k in ("name", "department", "grade")})
            return {k: v for k, v in u.items() if k != "password"}
        if path.startswith("/users/"):
            uid = int(path.split("/")[2])
            u = next((x for x in store.values() if x["udj_user_id"] == uid), None)
            if not u:
                raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
            return {k: v for k, v in u.items() if k != "password"}
        raise HTTPException(status_code=404, detail="없는 경로")

    udj_mod._call = fake_call
    udj_mod.is_ready = lambda: True
    m.udj._call = fake_call
    m.udj.is_ready = lambda: True

    from app.main import app
    from app.database import SessionLocal
    from app.models import JournalEntry, Role, SchoolSeat, SchoolSubject, SeatHolder, User
    c = TestClient(app)

    # ── 가입 · 로그인 ─────────────────────────────
    section("계정")
    r = c.post("/api/auth/signup", json={
        "email": "stu@t.com", "password": "pw12345678", "name": "학생",
        "phone": "01011112222", "phone_verification_token": "x",
        "birth_date": "2009-03-02", "privacy_consent": True, "terms_consent": True})
    check("회원가입", r.status_code == 200, r.text[:100])
    H = {"Authorization": "Bearer " + r.json()["access_token"]}
    uid = r.json()["user"]["id"]

    r2 = c.post("/api/auth/signup", json={
        "email": "stu@t.com", "password": "pw12345678", "name": "중복",
        "phone": "01011112222", "phone_verification_token": "x",
        "birth_date": "2009-03-02", "privacy_consent": True, "terms_consent": True})
    check("중복 가입 차단", r2.status_code == 400, f"{r2.status_code} {r2.text[:60]}")
    r3 = c.post("/api/auth/signup", json={
        "email": "z@t.com", "password": "pw12345678", "name": "동의",
        "phone": "01099998888", "phone_verification_token": "x",
        "birth_date": "2009-03-02", "privacy_consent": False, "terms_consent": True})
    check("약관 미동의 거부", r3.status_code == 400, f"{r3.status_code} {r3.text[:70]}")
    check("로그인", c.post("/api/auth/login", json={
        "email": "stu@t.com", "password": "pw12345678"}).status_code == 200)
    check("틀린 비밀번호", c.post("/api/auth/login", json={
        "email": "stu@t.com", "password": "wrong"}).status_code == 401)
    check("내 정보", c.get("/api/auth/me", headers=H).json()["email"] == "stu@t.com")
    check("이름 변경", c.patch("/api/me", headers=H,
                            json={"name": "새이름"}).json()["name"] == "새이름")
    check("비밀번호 변경", c.post("/api/me/change-password", headers=H, json={
        "current_password": "pw12345678", "new_password": "newpw12345"}).status_code == 200)
    check("새 비밀번호 로그인", c.post("/api/auth/login", json={
        "email": "stu@t.com", "password": "newpw12345"}).status_code == 200)

    # ── 일지 ──────────────────────────────────────
    section("일지 · 일기")
    check("메타 조회", c.get("/api/journal-meta").status_code == 200)
    r = c.post("/api/journals", headers=H, json={
        "kind": "diary", "entry_date": "2026-07-28", "title": "조별 과제 발표",
        "content": {"memorable": "조별 과제에서 발표를 맡았다. 조원들과 역할을 나누고 회의를 세 번 했다."}})
    check("일지 작성", r.status_code == 200, r.text[:80])
    jid = r.json()["id"]
    check("일지 목록", len(c.get("/api/journals", headers=H).json()) == 1)
    check("일지 상세", c.get(f"/api/journals/{jid}", headers=H).json()["kind"] == "diary")
    check("일지 수정", c.put(f"/api/journals/{jid}", headers=H, json={
        "kind": "diary", "entry_date": "2026-07-28", "title": "조별 과제 발표",
        "content": {"memorable": "조별 과제에서 발표를 맡았다. 조원들과 역할을 "
                                 "나누고 회의를 세 번 했다. 책임감 있게 끝냈다."}}).status_code == 200)
    check("제목 없으면 거부", c.post("/api/journals", headers=H, json={
        "kind": "diary", "entry_date": "2026-07-28",
        "content": {"memorable": "제목 없이 써본다."}}).status_code == 400)

    r = c.post(f"/api/journals/{jid}/submit", headers=H)
    check("미인증은 제출 불가", r.status_code == 400, r.text[:60])

    # 재학생 인증을 받은 상태로 만든다
    db = SessionLocal()
    me = db.get(User, uid)
    me.school_id, me.school_name, me.verified = 1, "테스트고", True
    me.department, me.grade, me.teacher_udj_id = "미디어소프트웨어과", 2, 500
    for d, g, n in [("미디어소프트웨어과", 1, "프로그래밍"),
                    ("미디어소프트웨어과", 2, "웹프로그래밍"), ("기계과", 1, "용접")]:
        db.add(SchoolSubject(school_id=1, department=d, grade=g, name=n))
    tea = User(udj_user_id=500, email="tea@t.com", name="교사", role=Role.teacher,
               school_id=1)
    sch = User(udj_user_id=501, email="school@t.com", name="학교", role=Role.school,
               school_id=1, school_name="테스트고")
    db.add(tea)
    db.add(sch)
    db.commit()
    tid, sid = tea.id, sch.id
    db.close()

    check("인증 후 제출", c.post(f"/api/journals/{jid}/submit", headers=H).status_code == 200)

    d = c.get("/api/journal-subjects", headers=H).json()
    check("과목 학과·학년 필터", d["subjects"] == ["웹프로그래밍"], str(d["subjects"]))

    # ── 맞춤법 ────────────────────────────────────
    section("맞춤법")
    r = c.post("/api/spellcheck", json={"fields": {"a": "오늘 실습이 잘 됬다. 할수있다."}})
    found = [x["found"] for x in r.json()["results"]["a"]]
    check("오타 검출", "됬" in found and "할수있" in found, str(found))
    check("정상 문장 무지적",
          len(c.post("/api/spellcheck", json={"fields": {"a": "표를 잘 만들었습니다."}})
              .json()["results"].get("a", [])) == 0)

    # ── 교사 열람 ─────────────────────────────────
    section("교사 열람")
    db = SessionLocal()
    tea_user = db.get(User, tid)
    from app.auth import create_access_token
    TH = {"Authorization": "Bearer " + create_access_token(tea_user)}
    db.close()
    rows = c.get("/api/teacher/journals?scope=mine", headers=TH).json()
    check("담당 학급 일지", len(rows) == 1, str(rows)[:80])
    check("일지 상세", c.get(f"/api/teacher/journals/{jid}", headers=TH).status_code == 200)
    check("학생은 교사 화면 차단",
          c.get("/api/teacher/journals", headers=H).status_code == 403)

    # ── 이용권 · 자소서 ─────────────────────────────
    # 결제 주체가 개인에서 학교로 바뀌었다(README "개인 결제는 없어졌다").
    # 학교가 좌석을 신청하고 관리자가 승인하는 실제 흐름으로 검사한다.
    section("이용권 · 자기소개서")
    check("미구독 자소서 차단", c.get("/api/cover-letters", headers=H).status_code == 402)

    db = SessionLocal()
    school_user = db.get(User, sid)
    SCH = {"Authorization": "Bearer " + create_access_token(school_user)}
    db.close()

    r = c.post("/api/school/seat-orders", headers=SCH, json={"seats": 3, "school_name": "테스트고"})
    check("좌석 신청", r.status_code == 200 and r.json()["amount"] > 0, str(r.json())[:80])
    oid = r.json()["id"]

    # 좌석을 받아야 자소서를 쓸 수 있다. 좌석 배정(코드 등록) 자체는
    # tests/enrollment.py 에서 이미 검사하므로, 여기서는 접근 권한이 이어지는
    # 것만 확인하기 위해 곧바로 좌석을 준다.
    db = SessionLocal()
    now = datetime.utcnow()
    db.add(SchoolSeat(school_id=1, seats=3, started_at=now, expires_at=now + timedelta(days=300)))
    db.add(SeatHolder(school_id=1, user_id=uid))
    db.commit()
    db.close()

    check("좌석 받은 뒤 접근", c.get("/api/cover-letters", headers=H).status_code == 200)
    r = c.post("/api/cover-letters", headers=H,
               json={"title": "2027 수시", "content": {"growth": "성장했다"}})
    check("자소서 작성", r.status_code == 200)
    check("자소서 목록", len(c.get("/api/cover-letters", headers=H).json()) == 1)
    mat = c.get("/api/cover-letters/materials", headers=H).json()
    check("자소서 재료 분류", any(t["count"] > 0 for t in mat["topics"]),
          f"문단 {mat['passage_count']}개")

    one = c.get("/api/cover-letters/materials?topic=teamwork", headers=H).json()
    check("항목별 재료 조회", len(one["topics"]) == 1 and one["topics"][0]["key"] == "teamwork",
          str([t["key"] for t in one["topics"]]))

    r = c.post("/api/cover-letters/review", headers=H,
               json={"fields": {"growth": "저는 열심히 노력했습니다. 많은 것을 배웠습니다."}})
    rv = r.json()["results"]["growth"]
    check("글 점검 — 빠진 요소", len(rv["missing"]) > 0, str(rv["missing"])[:60])
    check("글 점검 — 막연한 표현", any(n["kind"] == "vague" for n in rv["notes"]),
          str([n["kind"] for n in rv["notes"]]))

    # 구조가 갖춰지고 분량도 충분한 글은 지적이 없어야 한다.
    good = ("1학년 때 조별 과제에서 발표를 맡았다. 조원 네 명과 역할을 나누고 회의를 "
            "세 번 했다. 자료 정리는 지민이가, 화면 구성은 서준이가 맡았고 나는 대본을 "
            "다섯 번 고쳐 쓰며 거울 앞에서 연습했다. 발표가 끝난 뒤 구성이 깔끔하다는 "
            "말을 들었다. 이 일로 맡은 일이 늦어지면 팀 전체가 밀린다는 것을 배웠다. "
            "다음 과제에서는 마감을 하루 앞당겨 잡기로 했다.")
    rv2 = c.post("/api/cover-letters/review", headers=H,
                 json={"fields": {"growth": good}}).json()["results"]["growth"]
    check("잘 쓴 글은 지적 없음", rv2["ok"],
          f"빠짐 {len(rv2['missing'])} 지적 {len(rv2['notes'])}")

    # ── 관리자 ────────────────────────────────────
    section("관리자")
    db = SessionLocal()
    adm = User(udj_user_id=900, email="adm@t.com", name="관리자", role=Role.admin)
    db.add(adm)
    db.commit()
    AH = {"Authorization": "Bearer " + create_access_token(adm)}
    db.close()
    check("현황", c.get("/api/admin/stats", headers=AH).status_code == 200)
    check("좌석 신청 목록", len(c.get("/api/admin/seat-orders", headers=AH).json()) == 1)
    check("좌석 신청 승인",
          c.post(f"/api/admin/seat-orders/{oid}/approve", headers=AH, json={}).status_code == 200)
    check("설정 저장", c.put("/api/admin/settings", headers=AH,
                          json={"bank_name": "국민", "subscription_price": "5900"}).status_code == 200)
    check("설정 반영",
          c.get("/api/admin/settings", headers=AH).json()["bank_name"] == "국민")
    check("학생은 관리자 차단", c.get("/api/admin/stats", headers=H).status_code == 403)
    check("비로그인 차단", c.get("/api/admin/stats").status_code == 401)

    # ── 탈퇴 ─────────────────────────────────────
    section("탈퇴")
    r = c.request("DELETE", "/api/me", headers=H, json={"password": "newpw12345"})
    check("회원 탈퇴", r.status_code == 200, r.text[:80])
    db = SessionLocal()
    check("일지 함께 삭제",
          db.query(JournalEntry).filter(JournalEntry.user_id == uid).count() == 0)
    check("계정 사본 삭제", db.query(User).filter(User.id == uid).count() == 0)
    db.close()
    check("UDJ 계정도 삭제", "stu@t.com" not in store)

    print("\n" + "=" * 50)
    print(f"통과 {len(PASS)}건 / 실패 {len(FAIL)}건")
    if FAIL:
        print("\n실패 항목:")
        for f in FAIL:
            print("  -", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
