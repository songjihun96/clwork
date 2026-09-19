"""전체 기능 통합 테스트.

    DATABASE_URL="sqlite:///./_test.db" SECRET_KEY=test python -m app.full_test

실제 서버를 띄워 주요 흐름을 끝에서 끝까지 돌린다.
운영 DB를 건드리지 않도록 반드시 별도 DATABASE_URL 로 실행할 것.
"""

import os
import re
import sys
from datetime import date, datetime, timedelta

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    mark = "✅" if cond else "❌"
    line = f"{mark} {name}"
    if not cond and detail:
        line += f"\n     └ {detail}"
    print(line)


def section(title):
    print(f"\n── {title} " + "─" * max(0, 46 - len(title)))


def main() -> int:
    from fastapi.testclient import TestClient
    import app.main as main_mod
    from app.database import SessionLocal
    from app.models import (
        AdminAuditLog, GuardianConsent, PhoneVerification,
        Role, School, SchoolViewHit, User,
    )
    from app.auth import hash_password

    # 메일/문자 발송을 가로채 인증번호를 읽는다
    sent_mail, sent_sms = {}, {}

    class Cfg:
        def is_ready(self):
            return True

    main_mod.mailer.system_config = lambda: Cfg()
    main_mod.mailer.send_email = lambda cfg, to, sub, body, **kw: (sent_mail.update({to: body}), (True, ""))[1]
    main_mod.sms.send_sms = lambda phone, text: (sent_sms.update({phone: text}), (True, ""))[1]

    from app.main import app
    c = TestClient(app)

    def code_from(store, key):
        m = re.search(r"(\d{6})", store.get(key, ""))
        return m.group(1) if m else None

    def verify(phone, purpose, email=None, headers=None):
        # change_pw / change_phone 은 로그인 상태에서만 인증번호를 받을 수 있다.
        c.post("/api/phone/send-code", headers=headers or {},
               json={"phone": phone, "purpose": purpose, "email": email})
        # 채널 설정에 따라 문자 또는 메일로 가므로 양쪽을 모두 본다.
        code = code_from(sent_sms, phone) or (code_from(sent_mail, email) if email else None)
        r = c.post("/api/phone/verify-code", json={"phone": phone, "purpose": purpose, "code": code})
        return r.json().get("verification_token")

    def signup(email, phone, birth="2005-01-01", guardian=None):
        tok = verify(phone, "signup", email)
        body = {
            "email": email, "password": "pw12345678", "name": "테스터", "phone": phone,
            "phone_verification_token": tok, "birth_date": birth,
            "privacy_consent": True, "terms_consent": True,
        }
        if guardian:
            body["guardian_email"] = guardian
        return c.post("/api/auth/signup", json=body)

    # ── 기본 데이터 준비 ────────────────────────────────
    db = SessionLocal()
    db.add(User(email="adm@t.com", password_hash=hash_password("adminpw123"),
                name="관리자", role=Role.admin, phone="01000000000"))
    rows = [
        ("수원미디어고", "경기", "경기도 수원시 장안구 1", "미디어소프트웨어과\n앱서비스과", 37.30, 127.01, "특성화고"),
        ("수원조리고", "경기", "경기도 수원시 영통구 2", "조리과\n제과제빵과", 37.25, 127.07, "특성화고"),
        ("안양기계마이스터고", "경기", "경기도 안양시 만안구 3", "기계과", 37.39, 126.92, "마이스터고"),
        ("부산기계공고", "부산", "부산광역시 사상구 4", "기계과\n금형설계과", 35.15, 129.00, "특성화고"),
        ("좌표없는고", "경기", "경기도 수원시 팔달구 5", "패션디자인과", None, None, "특성화고"),
    ]
    for n, reg, addr, dept, la, ln, cat in rows:
        s = School(name=n, category=cat, region=reg, address=addr, phone="031-0",
                   departments=dept, latitude=la, longitude=ln)
        main_mod.refresh_dept_fields(s)
        db.add(s)
    db.commit()
    school_id = db.query(School).filter(School.name == "수원미디어고").first().id
    db.close()

    AH = {"Authorization": "Bearer " + c.post("/api/auth/login", json={
        "email": "adm@t.com", "password": "adminpw123"}).json()["access_token"]}

    # ── 1. 공개 엔드포인트 ──────────────────────────────
    section("공개 엔드포인트")
    for path in ["/api/meta", "/api/terms", "/api/refund-policy", "/api/verify-config",
                 "/api/quiz/questions", "/api/sigungu?region=경기", "/api/schools?size=5",
                 "/api/schools/map", "/api/geo-config"]:
        r = c.get(path)
        check(f"GET {path}", r.status_code == 200, f"{r.status_code} {r.text[:80]}")

    # ── 2. 회원가입 / 본인확인 ──────────────────────────
    section("회원가입 · 본인확인")
    r = signup("adult@t.com", "01011112222")
    check("성인 가입", r.status_code == 200, r.text[:120])
    UH = {"Authorization": "Bearer " + r.json()["access_token"]}
    uid = r.json()["user"]["id"]
    check("내 정보에 휴대폰 포함", c.get("/api/auth/me", headers=UH).json().get("phone") == "01011112222")

    r = c.post("/api/phone/send-code", json={"phone": "01011112222", "purpose": "signup", "email": "x@t.com"})
    check("중복 번호 가입 차단", r.status_code == 400, r.text[:80])

    tok = verify("01055556666", "signup", "dup@t.com")
    c.post("/api/auth/signup", json={"email": "dup@t.com", "password": "pw12345678", "name": "A",
                                     "phone": "01055556666", "phone_verification_token": tok,
                                     "birth_date": "2005-01-01", "privacy_consent": True, "terms_consent": True})
    r = c.post("/api/auth/signup", json={"email": "dup2@t.com", "password": "pw12345678", "name": "B",
                                         "phone": "01055556666", "phone_verification_token": tok,
                                         "birth_date": "2005-01-01", "privacy_consent": True, "terms_consent": True})
    check("인증 토큰 재사용 차단", r.status_code == 400, r.text[:80])

    r = c.post("/api/phone/verify-code", json={"phone": "01011112222", "purpose": "signup", "code": "000000"})
    check("틀린 인증번호 거부", r.status_code == 400, r.text[:80])

    for _ in range(6):
        r = c.post("/api/phone/send-code", json={"phone": "01099998888", "purpose": "signup", "email": "z@t.com"})
    check("인증번호 발송 횟수 제한", r.status_code == 429, f"{r.status_code}")

    # ── 3. 만 14세 미만 ────────────────────────────────
    section("만 14세 미만 법정대리인 동의")
    r = signup("kid@t.com", "01033334444", birth="2014-01-01", guardian="mom@t.com")
    check("아동 가입 → 동의 대기", r.status_code == 200 and r.json().get("guardian_consent_required"), r.text[:120])
    r = c.post("/api/auth/login", json={"email": "kid@t.com", "password": "pw12345678"})
    check("동의 전 로그인 차단", r.status_code == 403, f"{r.status_code}")
    db = SessionLocal()
    gtok = db.query(GuardianConsent).first().token
    db.close()
    check("동의 화면 정보 조회", c.get(f"/api/guardian-consent/{gtok}").status_code == 200)
    check("보호자 동의 처리", c.post(f"/api/guardian-consent/{gtok}").status_code == 200)
    check("동의 후 로그인 가능", c.post("/api/auth/login", json={
        "email": "kid@t.com", "password": "pw12345678"}).status_code == 200)
    r = signup("kid2@t.com", "01044445555", birth="2014-01-01")
    check("보호자 이메일 없으면 거부", r.status_code == 400, r.text[:80])

    # ── 4. 계정 찾기 · 비밀번호 ─────────────────────────
    section("계정 찾기 · 비밀번호")
    # 문자 채널에서는 본인확인이 필수, 메일 채널에서는 불가능하므로 생략된다.
    need_verify = c.get("/api/verify-config").json()["find_id_requires_verification"]
    body = {"name": "테스터", "phone": "01011112222"}
    if need_verify:
        body["phone_verification_token"] = verify("01011112222", "find_id", "adult@t.com")
    r = c.post("/api/auth/find-id", json=body)
    check(f"아이디 찾기({'인증 필요' if need_verify else '인증 생략'})",
          r.status_code == 200 and r.json()["emails"], r.text[:100])

    t = verify("01011112222", "reset_pw", "adult@t.com")
    r = c.post("/api/auth/reset-password-by-phone", json={
        "email": "adult@t.com", "phone": "01011112222",
        "phone_verification_token": t, "new_password": "reset12345"})
    check("휴대폰으로 비밀번호 재설정", r.status_code == 200, r.text[:100])
    check("새 비밀번호로 로그인", c.post("/api/auth/login", json={
        "email": "adult@t.com", "password": "reset12345"}).status_code == 200)

    t = verify("01011112222", "change_pw", "adult@t.com", headers=UH)
    r = c.post("/api/auth/change-password", headers=UH, json={
        "current_password": "reset12345", "new_password": "changed12345",
        "phone_verification_token": t})
    check("비밀번호 변경", r.status_code == 200, r.text[:100])

    t = verify("01077778888", "change_phone", "adult@t.com", headers=UH)
    r = c.post("/api/me/change-phone", headers=UH, json={
        "current_password": "changed12345", "new_phone": "01077778888",
        "phone_verification_token": t})
    check("휴대폰 번호 변경", r.status_code == 200 and r.json().get("phone") == "01077778888", r.text[:100])
    check("이전 번호로 변경 통지", "변경되었습니다" in sent_sms.get("01011112222", ""))

    r = c.post("/api/me/change-phone", headers=UH, json={
        "current_password": "틀린비번", "new_phone": "01066667777",
        "phone_verification_token": "bad"})
    check("비밀번호 틀리면 번호 변경 거부", r.status_code == 400, r.text[:80])

    # ── 5. 학교 검색 필터 ──────────────────────────────
    section("학교 검색 · 필터")
    cases = [
        ("region=경기", 4, "지역"),
        ("region=경기&sigungu=수원시", 3, "시 전체"),
        ("region=경기&sigungu=수원시 장안구", 1, "구 단위"),
        ("category=마이스터고", 1, "학교 계열"),
        ("dept_field=it", 1, "학과 계열 IT"),
        ("dept_field=food", 1, "학과 계열 조리"),
        ("name=기계", 2, "이름 검색"),
    ]
    for q, expect, label in cases:
        r = c.get(f"/api/schools?{q}&size=50").json()
        check(f"필터: {label}", r["total"] == expect, f"기대 {expect} / 실제 {r['total']}")

    for sort in ["recommended", "name", "views"]:
        check(f"정렬: {sort}", c.get(f"/api/schools?sort={sort}&size=5").status_code == 200)

    r = c.get("/api/schools?size=2&page=2").json()
    check("페이지네이션", len(r["items"]) == 2 and r["total"] == 5, f"{len(r['items'])}건 / total {r['total']}")

    # ── 6. 지도 ────────────────────────────────────────
    section("지도")
    for q, label in [("region=경기", "지역"), ("region=경기&sigungu=수원시", "시 전체"), ("dept_field=it", "학과 계열")]:
        lst = c.get(f"/api/schools?{q}&size=50").json()
        mp = c.get(f"/api/schools/map?{q}").json()
        names_l = {i["name"] for i in lst["items"] if i["name"] != "좌표없는고"}
        names_m = {i["name"] for i in mp}
        check(f"지도-목록 일치: {label}", names_l == names_m, f"목록 {names_l} / 지도 {names_m}")
    check("좌표 없는 학교는 지도 제외", all(i["name"] != "좌표없는고" for i in c.get("/api/schools/map").json()))

    # ── 7. 조회수 ──────────────────────────────────────
    section("조회수 집계")
    before = c.get(f"/api/schools/{school_id}").json()["view_count"]
    for _ in range(3):
        c.get(f"/api/schools/{school_id}")
    after = c.get(f"/api/schools/{school_id}").json()["view_count"]
    check("상세 조회는 집계 안 함", before == after, f"{before} → {after}")
    r1 = c.post(f"/api/schools/{school_id}/view").json()
    r2 = c.post(f"/api/schools/{school_id}/view").json()
    check("조회 1회 집계", r1.get("counted") is True, str(r1))
    check("30분 내 중복 차단", r2.get("counted") is False and r2.get("reason") == "duplicate", str(r2))
    r3 = c.post(f"/api/schools/{school_id}/view", headers={"User-Agent": "other"}).json()
    check("다른 이용자는 집계", r3.get("counted") is True, str(r3))
    r4 = c.post(f"/api/schools/{school_id}/view", headers=AH).json()
    check("관리자는 집계 제외", r4.get("counted") is False and r4.get("reason") == "self", str(r4))

    # ── 8. 관리자 ──────────────────────────────────────
    section("관리자 기능")
    cats = c.get("/api/admin/category-visibility", headers=AH).json()
    check("계열 목록 조회", {x["category"] for x in cats} == {"특성화고", "마이스터고"}, str(cats)[:100])
    c.patch("/api/admin/schools-visibility-by-category?category=마이스터고&visible=false", headers=AH)
    check("계열 숨김 반영", c.get("/api/schools?category=마이스터고&size=5").json()["total"] == 0)
    c.patch("/api/admin/schools-visibility-by-category?category=마이스터고&visible=true", headers=AH)
    check("계열 노출 복구", c.get("/api/schools?category=마이스터고&size=5").json()["total"] == 1)

    d = c.get("/api/admin/dept-field-filter", headers=AH).json()
    check("학과 계열 설정 조회", d["enabled"] is True and d["tagged"] == 5, str(d)[:120])
    c.patch("/api/admin/dept-field-filter?enabled=false", headers=AH)
    check("학과 계열 필터 끄기", c.get("/api/meta").json()["dept_field_enabled"] is False)
    check("꺼진 상태에선 필터 무시", c.get("/api/schools?dept_field=it&size=50").json()["total"] == 5)
    c.patch("/api/admin/dept-field-filter?enabled=true", headers=AH)
    check("학과 계열 재계산", c.post("/api/admin/dept-field-filter/rebuild", headers=AH).status_code == 200)

    logs = c.get("/api/admin/audit-logs", headers=AH).json()
    check("감사 로그 기록", len(logs) > 0, str([x["action"] for x in logs]))
    check("비관리자 접근 차단", c.get("/api/admin/audit-logs", headers=UH).status_code == 403)
    check("비로그인 접근 차단", c.get("/api/admin/audit-logs").status_code == 401)

    # ── 10. 진로 테스트 ─────────────────────────────────
    section("진로 적성 테스트")
    qs = c.get("/api/quiz/questions").json()
    questions = qs if isinstance(qs, list) else qs.get("questions", [])
    answers = [str((i % 5) + 1) for i in range(len(questions))]
    r = c.post("/api/quiz/result", json={"answers": answers, "commute_time": "any"})
    check("진로 테스트 결과", r.status_code == 200, r.text[:120])
    if r.status_code == 200:
        db = SessionLocal()
        from app.models import QuizTaken
        n = db.query(QuizTaken).count()
        db.close()
        check("참여 기록 저장", n >= 1, f"{n}건")

    # ── 11. 개인정보 파기 ───────────────────────────────
    section("개인정보 파기")
    db = SessionLocal()
    db.add(PhoneVerification(phone="01099990000", purpose="signup", code_hash="x",
                             expires_at=datetime.utcnow(),
                             created_at=datetime.utcnow() - timedelta(hours=30)))
    db.commit()
    n_before = db.query(PhoneVerification).count()
    main_mod.purge_expired_verifications(db)
    n_after = db.query(PhoneVerification).count()
    db.close()
    check("오래된 인증기록 파기", n_after < n_before, f"{n_before} → {n_after}")

    r = c.request("DELETE", "/api/auth/me", headers=UH, json={"password": "changed12345"})
    check("회원 탈퇴", r.status_code == 200, r.text[:120])
    db = SessionLocal()
    check("계정 삭제됨", db.query(User).filter(User.id == uid).count() == 0)
    check("감사 로그는 보존", db.query(AdminAuditLog).count() > 0)
    db.close()

    # ── 12. 학과 계열 분류 ──────────────────────────────
    section("학과 계열 분류")
    from app import dept_fields as df
    cls = [
        ("미디어소프트웨어과\n앱서비스과", {"it", "media"}),
        ("패션산업디자인과", {"fashion", "design"}),
        ("마케팅경영과", {"business"}),
        ("조리과\n제과제빵과", {"food"}),
        ("보통과\n일반과", set()),
    ]
    for text, expect in cls:
        got = set(df.classify(text))
        check(f"분류: {text.splitlines()[0]}", expect <= got, f"기대 {expect} ⊆ 실제 {got}")

    # ── 결과 ───────────────────────────────────────────
    print("\n" + "=" * 54)
    print(f"통과 {len(PASS)}건 / 실패 {len(FAIL)}건")
    if FAIL:
        print("\n실패 항목:")
        for f in FAIL:
            print("  -", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
