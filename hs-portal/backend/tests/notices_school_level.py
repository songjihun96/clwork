"""학교급(중·고) 분리 · 공지사항 · 공지 알림 · 우리동네직업계고 담당 선생님 공지.

확인할 것:
  [학교 계정]
  (1) 중학교·고등학교 신청이 학교급과 함께 저장된다. 중학교는 지역이 있어야 하고 고교 목록에서 못 고른다
  (2) 중학교 승인 → 숨김 학교가 만들어지고 계정이 붙는다. 고등학교 승인 → 담당 선생님이 등록된다
  (3) 로그인 정보에 학교급이 실린다
  (4) 중학교 계정은 고등학교 전용 API(학교 정보·통계·진학정보 등)가 막힌다. 고등학교는 그대로 된다
  (5) 중학교 학교는 공개 검색·상세에 나오지 않고 노출을 켤 수 없다
  [공지]
  (6) 게시판 공지 작성·임시저장·게시·게시 취소·수정·삭제, 중요 공지가 위로, 상세
  (7) 우리동네직업계고 공지는 고등학교 계정·관리자만 본다
  [알림]
  (8) 학교 계정 메일: 학교급 대상(전체·고·중)대로, 학생·선생님에게는 안 감, 알림 끈 학교 제외
  (9) 담당 선생님 메일·문자, 비활성 담당자 제외, 주소 없음은 '보낼 수 없음'으로 기록
  (10) 다시 게시해도 중복 발송 없음, 실패 기록·재발송
  (11) 공지 알림 설정(학교 계정), 관리자 학교 계정 목록 필터
  (12) 마이그레이션 status/downgrade/upgrade
  (13) 수신 동의: 동의 없는 담당자는 안 보냄(기록만), 나중에 동의하면 다시 게시·수정 때 보냄,
       신청서 선택 동의가 담당자 동의로 옮겨짐, 이벤트 공지는 메일·문자 안 보냄
실행:  cd backend && python tests/notices_school_level.py
"""
import os
import sys
import tempfile
from datetime import datetime

DB = os.path.join(tempfile.gettempdir(), "udj_notices_test.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB.replace("\\", "/")
os.environ["SECRET_KEY"] = "x"
os.environ.setdefault("PARTNER_SECRET", "test-partner-secret")
if os.path.exists(DB):
    os.remove(DB)
sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402

from app import mailer, notices as N, sms  # noqa: E402
from app.auth import create_access_token, hash_password  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (Coed, NotificationLog, Plan, Role, School,  # noqa: E402
                        SchoolContact, User)

OK = []


def chk(n, c, e=""):
    OK.append(bool(c))
    print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))


# ── 가짜 메일·문자 ──
SENT = {"email": [], "sms": []}
FAIL_TO = set()


class Cfg:
    def is_ready(self):
        return True


mailer.system_config = lambda: Cfg()


def fake_mail(cfg, to, subject, body, from_name="", **kw):
    if to in FAIL_TO:
        return False, "SMTP 550 거부"
    SENT["email"].append((to, subject, body))
    return True, ""


def fake_sms(phone, text):
    SENT["sms"].append((phone, text))
    return True, ""


mailer.send_email = fake_mail
sms.send_sms = fake_sms

db = SessionLocal()


def mk_school(name, level="high", visible=True):
    s = School(name=name, category="특성화고" if level == "high" else "중학교", region="경기",
               address="수원", coed=Coed.coed, plan=Plan.free, is_visible=visible,
               phone="031", school_level=level)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def mk_user(email, role, school_id=None, active=True):
    u = User(email=email, password_hash=hash_password("p1234567"), name=email, role=role,
             school_id=school_id, is_active=active)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


H1 = mk_school("한빛공업고")          # 고등학교, 학교 계정 있음
H2 = mk_school("새솔상업고")          # 고등학교, 학교 계정 있음(알림 끔)
H3 = mk_school("담당자없는고")         # 고등학교, 계정 없음
H5 = mk_school("동의없는고")           # 고등학교, 담당자는 있으나 공지 수신 동의 없음(예전 담당자)
adm = mk_user("admin@t.kr", Role.admin)
s1 = mk_user("h1@school.kr", Role.school, H1.id)
s2 = mk_user("h2@school.kr", Role.school, H2.id)
stu = mk_user("stu@t.kr", Role.student, H1.id)
H2.notice_email_enabled = False
NOW = datetime.utcnow()
db.add(SchoolContact(school_id=H1.id, name="김담당", email="kim@h1.kr", phone="010-1111-2222",
                     consent_at=NOW, consent_source="school"))
db.add(SchoolContact(school_id=H2.id, name="이담당", email="", phone="01033334444",
                     consent_at=NOW, consent_source="school"))
db.add(SchoolContact(school_id=H5.id, name="옛담당", email="old@h5.kr", phone="01077770000"))
db.add(SchoolContact(school_id=H3.id, name="퇴직", email="old@h3.kr", phone="01055556666", is_active=False))
db.commit()
H1ID, H2ID, H3ID, H5ID = H1.id, H2.id, H3.id, H5.id
T = {u.email: {"Authorization": f"Bearer {create_access_token(u)}"} for u in (adm, s1, s2, stu)}
AH, S1H, STH = T["admin@t.kr"], T["h1@school.kr"], T["stu@t.kr"]
db.close()
c = TestClient(app)


def drain():
    """백그라운드 발송을 테스트에서 확실히 끝낸다(TestClient 는 응답 뒤 실행)."""
    N.process()


print("=== 1. 학교 계정 신청: 중학교·고등학교 ===")
base = {"manager_name": "박선생", "manager_phone": "010-9999-8888", "privacy_consent": True}
r = c.post("/api/school-account-requests", json={**base, "school_name": "푸른중학교",
                                                  "school_level": "middle", "manager_email": "m@mid.kr"})
chk("중학교는 지역 필수", r.status_code == 422 and "지역" in r.json()["detail"], r.text)
r = c.post("/api/school-account-requests", json={**base, "school_name": "푸른중학교", "region": "경기",
                                                  "school_level": "middle", "school_id": H1ID,
                                                  "manager_email": "m@mid.kr"})
chk("중학교는 고교 목록에서 못 고름", r.status_code == 422, r.text)
r = c.post("/api/school-account-requests", json={**base, "school_name": "푸른중학교", "region": "경기",
                                                  "school_level": "middle", "manager_email": "m@mid.kr"})
chk("중학교 신청 접수", r.status_code == 200, r.text)
MREQ = r.json()["id"]
H4 = None
db = SessionLocal()
H4 = School(name="해솔전자고", category="특성화고", region="부산", address="부산", coed=Coed.coed,
            plan=Plan.free, is_visible=True, phone="051")
db.add(H4)
db.commit()
H4ID = H4.id
db.close()
r = c.post("/api/school-account-requests", json={**base, "school_name": "해솔전자고", "school_id": H4ID,
                                                  "school_level": "high", "manager_email": "t@h4.kr",
                                                  "manager_position": "부장", "notice_consent": True})
chk("고등학교 신청 접수", r.status_code == 200, r.text)
HREQ = r.json()["id"]
chk("모르는 학교급 422", c.post("/api/school-account-requests", json={
    **base, "school_name": "어딘가학교", "school_level": "elem", "manager_email": "e@e.kr"}).status_code == 422)
lst = c.get("/api/admin/school-account-requests", params={"level": "middle"}, headers=AH).json()
chk("관리자: 중학교만 거르기", [x["id"] for x in lst["items"]] == [MREQ], str(lst["items"]))
chk("관리자: 학교급 표시", lst["items"][0]["school_level_label"] == "중학교" and lst["items"][0]["region"] == "경기")
chk("관리자: 승인 대기 필터", {x["id"] for x in c.get("/api/admin/school-account-requests",
    params={"status": "open"}, headers=AH).json()["items"]} == {MREQ, HREQ})

print("=== 2. 승인 ===")
r = c.post(f"/api/admin/school-account-requests/{MREQ}/approve", headers=AH)
chk("중학교 승인(학교 자동 생성)", r.status_code == 200, r.text)
db = SessionLocal()
mu = db.query(User).filter_by(email="m@mid.kr").first()
ms = db.get(School, mu.school_id)
chk("중학교 학교: 숨김·중학교", ms.school_level == "middle" and ms.is_visible is False
    and ms.category == "중학교" and ms.region == "경기", f"{ms.school_level} {ms.is_visible}")
chk("중학교에는 담당 선생님을 두지 않음", db.query(SchoolContact).filter_by(school_id=ms.id).count() == 0)
MSID = ms.id
MH = {"Authorization": f"Bearer {create_access_token(mu)}"}
db.close()
r = c.post(f"/api/admin/school-account-requests/{HREQ}/approve", headers=AH)
chk("고등학교 승인", r.status_code == 200, r.text)
db = SessionLocal()
ct = db.query(SchoolContact).filter_by(school_id=H4ID).first()
chk("고등학교 승인 → 담당 선생님 등록", ct and ct.email == "t@h4.kr" and ct.position == "부장")
chk("신청서 공지 수신 동의 → 담당자 동의로", ct.consent_at is not None and ct.consent_source == "request")
hu = db.query(User).filter_by(email="t@h4.kr").first()
H4H = {"Authorization": f"Bearer {create_access_token(hu)}"}
db.close()

print("=== 3·4. 학교급과 권한 ===")
me = c.get("/api/auth/me", headers=MH).json()
chk("로그인 정보: 중학교", me.get("school_level") == "middle", str(me))
chk("로그인 정보: 고등학교", c.get("/api/auth/me", headers=S1H).json().get("school_level") == "high")
for path in ["/api/school-admin/profile", "/api/school-admin/stats", "/api/school-admin/events",
             "/api/school-admin/admission", "/api/school-admin/orders"]:
    r = c.get(path, headers=MH)
    chk(f"중학교 {path} 403", r.status_code == 403 and "중학교" in r.json().get("detail", ""), f"{r.status_code}")
chk("고등학교는 학교 정보 그대로", c.get("/api/school-admin/profile", headers=S1H).status_code == 200)
chk("중학교도 공지 알림 설정은 됨", c.get("/api/school/notification-settings", headers=MH).status_code == 200)
chk("학생은 공지 알림 설정 403", c.get("/api/school/notification-settings", headers=STH).status_code == 403)

print("=== 5. 중학교는 공개 목록에 없다 ===")
names = [x["name"] for x in c.get("/api/schools", params={"size": 50}).json()["items"]]
chk("검색에 없음", "푸른중학교" not in names and "한빛공업고" in names, str(names))
chk("상세 비공개(방문자)", c.get(f"/api/schools/{MSID}").status_code == 404)
chk("상세: 그 학교 계정은 봄", c.get(f"/api/schools/{MSID}", headers=MH).status_code == 200)
chk("노출 켜기 거부", c.patch(f"/api/admin/schools/{MSID}/visibility", params={"visible": True},
                            headers=AH).status_code == 422)
c.patch("/api/admin/categories/중학교/visibility", params={"visible": True}, headers=AH)
db = SessionLocal()
chk("계열 일괄 켜기에도 숨김 유지", db.get(School, MSID).is_visible is False)
db.close()

print("=== 6. 게시판 공지 ===")
r = c.post("/api/admin/notices", headers=AH, json={"title": "임시 공지", "body": "초안", "publish": False})
chk("임시저장", r.status_code == 200 and r.json()["status"] == "draft", r.text)
DRAFT = r.json()["id"]
chk("임시저장은 목록에 안 보임", all(x["id"] != DRAFT for x in c.get("/api/notices").json()["items"]))
chk("임시저장 상세 404", c.get(f"/api/notices/{DRAFT}").status_code == 404)
r = c.post("/api/admin/notices", headers=AH, json={"title": "일반 공지", "body": "본문", "category": "update"})
NORMAL = r.json()["id"]
r = c.post("/api/admin/notices", headers=AH, json={"title": "중요 공지", "is_important": True,
                                                    "category": "maintenance"})
IMP = r.json()["id"]
items = c.get("/api/notices").json()["items"]
chk("중요 공지가 맨 위", items[0]["id"] == IMP, str([i["id"] for i in items]))
chk("유형 이름", items[0]["category_label"] == "점검")
chk("유형 필터", [i["id"] for i in c.get("/api/notices", params={"category": "update"}).json()["items"]] == [NORMAL])
chk("상세", c.get(f"/api/notices/{NORMAL}").json()["body"] == "본문")
r = c.put(f"/api/admin/notices/{NORMAL}", headers=AH, json={"title": "일반 공지(수정)", "body": "고침",
                                                             "category": "update"})
chk("수정", r.status_code == 200 and c.get(f"/api/notices/{NORMAL}").json()["title"] == "일반 공지(수정)")
chk("게시 취소", c.post(f"/api/admin/notices/{NORMAL}/unpublish", headers=AH).json()["status"] == "draft"
    and c.get(f"/api/notices/{NORMAL}").status_code == 404)
chk("다시 게시", c.post(f"/api/admin/notices/{NORMAL}/publish", headers=AH).json()["status"] == "published")
chk("모르는 유형 422", c.post("/api/admin/notices", headers=AH, json={"title": "x", "category": "zzz"}).status_code == 422)
chk("학생은 관리 403", c.post("/api/admin/notices", headers=STH, json={"title": "x"}).status_code == 403)
chk("임시저장 삭제", c.delete(f"/api/admin/notices/{DRAFT}", headers=AH).status_code == 200)

print("=== 8. 학교 계정 메일 알림 ===")
SENT["email"].clear()
pv = c.post("/api/admin/notices/preview", headers=AH, json={"title": "t", "email_enabled": True}).json()
chk("미리보기: 계정 있는 학교 4곳 중 알림 끈 1곳 제외 → 3곳", pv["email"] == 3 and pv["opted_out"] == 1, str(pv))
r = c.post("/api/admin/notices", headers=AH, json={"title": "전체 학교 알림", "body": "모두에게",
                                                    "email_enabled": True, "target_level": "all"})
ALLN = r.json()["id"]
chk("응답에 대기 건수", r.json()["queued"] == 3, str(r.json()))
drain()
to = sorted(x[0] for x in SENT["email"])
chk("학교 계정 3곳에 발송(고2·중1)", to == sorted(["h1@school.kr", "t@h4.kr", "m@mid.kr"]), str(to))
chk("학생에게는 안 감", "stu@t.kr" not in to)
chk("제목 머리", SENT["email"][0][1].startswith("[UDJ] "))
chk("본문에 상세 링크", f"/notices/{ALLN}" in SENT["email"][0][2])
SENT["email"].clear()
c.post("/api/admin/notices", headers=AH, json={"title": "중학교만", "email_enabled": True, "target_level": "middle"})
drain()
chk("중학교 대상 → 중학교만", [x[0] for x in SENT["email"]] == ["m@mid.kr"], str(SENT["email"]))
SENT["email"].clear()
c.put("/api/school/notification-settings", headers=S1H,
      json={"notice_email": "notice@h1.kr", "notice_email_enabled": True})
c.post("/api/admin/notices", headers=AH, json={"title": "고교만", "email_enabled": True, "target_level": "high"})
drain()
chk("고등학교 대상 + 공지 알림 이메일로", sorted(x[0] for x in SENT["email"]) == ["notice@h1.kr", "t@h4.kr"],
    str(SENT["email"]))

print("=== 10. 중복 방지 ===")
SENT["email"].clear()
c.post(f"/api/admin/notices/{ALLN}/unpublish", headers=AH)
c.post(f"/api/admin/notices/{ALLN}/publish", headers=AH)
c.post(f"/api/admin/notices/{ALLN}/publish", headers=AH)
drain()
chk("다시 게시해도 다시 안 감", SENT["email"] == [], str(SENT["email"]))
logs = c.get(f"/api/admin/notices/{ALLN}/logs", headers=AH).json()
chk("발송 기록 3줄", len(logs) == 3 and all(x["status"] == "sent" for x in logs), str(logs))
chk("관리자 화면 주소 가림", all("***" in x["address"] for x in logs), str([x["address"] for x in logs]))

print("=== 9. 우리동네직업계고 공지(담당 선생님) ===")
SENT["email"].clear(); SENT["sms"].clear()
FAIL_TO.add("t@h4.kr")
pv = c.post("/api/admin/notices/preview", headers=AH, json={"kind": "vocational", "title": "t",
                                                             "email_enabled": True, "sms_enabled": True}).json()
chk("미리보기: 학교 3곳(H1·H2·H4), 비활성 1·동의 없음 1 제외",
    pv["schools"] == 3 and pv["inactive"] == 1 and pv["no_consent"] == 1, str(pv))
chk("미리보기: 메일 2(H2 주소 없음)·문자 3", pv["email"] == 2 and pv["email_unreachable"] == 1 and pv["sms"] == 3, str(pv))
r = c.post("/api/admin/notices", headers=AH, json={"kind": "vocational", "title": "2학기 설명회 촬영 안내",
                                                    "body": "촬영 일정을 알려 주세요.",
                                                    "email_enabled": True, "sms_enabled": True,
                                                    "target_level": "middle"})
VOC = r.json()["id"]
chk("직업계고 공지는 학교급이 고등학교로 고정", r.json()["target_level"] == "high")
drain()
chk("담당 선생님 메일(H1) 성공", [x[0] for x in SENT["email"]] == ["kim@h1.kr"], str(SENT["email"]))
chk("메일 제목 머리", SENT["email"][0][1].startswith("[우리동네직업계고] "))
chk("문자 3건", sorted(x[0] for x in SENT["sms"]) == ["01011112222", "01033334444", "01099998888"], str(SENT["sms"]))
chk("문자 90바이트 이하", all(len(t.encode("euc-kr", errors="replace")) <= 90 for _, t in SENT["sms"]))
chk("비활성 담당자에게 안 감", all("old@h3.kr" != x[0] for x in SENT["email"]))
chk("동의 없는 담당자에게 안 감", all("old@h5.kr" != x[0] for x in SENT["email"])
    and all("01077770000" != x[0] for x in SENT["sms"]))
logs = c.get(f"/api/admin/notices/{VOC}/logs", headers=AH).json()
st = sorted((x["channel"], x["status"]) for x in logs)
chk("기록: 메일 성공1·실패1·주소없음1·동의없음1, 문자 성공3·동의없음1", st == sorted(
    [("email", "sent"), ("email", "failed"), ("email", "cancelled"), ("email", "cancelled"),
     ("sms", "sent"), ("sms", "sent"), ("sms", "sent"), ("sms", "cancelled")]), str(st))
chk("동의 없음 사유 기록", sum(1 for x in logs if x["error"] == "수신 동의 없음") == 2)
failed = next(x for x in logs if x["status"] == "failed")
chk("실패 사유 기록", "550" in failed["error"])
FAIL_TO.clear()
SENT["email"].clear()
c.post(f"/api/admin/notification-logs/{failed['id']}/retry", headers=AH)
drain()
chk("재발송 성공", [x[0] for x in SENT["email"]] == ["t@h4.kr"], str(SENT["email"]))
sent_one = next(x for x in c.get(f"/api/admin/notices/{VOC}/logs", headers=AH).json() if x["id"] == failed["id"])
chk("재발송 뒤 성공으로 바뀜", sent_one["status"] == "sent" and sent_one["attempts"] == 2, str(sent_one))
chk("보낸 건 재발송 거부", c.post(f"/api/admin/notification-logs/{failed['id']}/retry", headers=AH).status_code == 409)
lst = c.get("/api/admin/notices", params={"kind": "vocational"}, headers=AH).json()
chk("목록에 발송 집계", lst[0]["send"]["sms"]["sent"] == 3, str(lst[0]["send"]))

print("=== 13. 수신 동의 · 이벤트 ===")
SENT["email"].clear(); SENT["sms"].clear()
r = c.put(f"/api/admin/schools/{H5ID}/contact", headers=AH, json={
    "name": "옛담당", "email": "old@h5.kr", "phone": "01077770000", "consent": True})
chk("관리자가 동의 확인 기록", r.json()["contact"]["consent"] is True
    and r.json()["contact"]["consent_source"] == "admin", r.text)
c.post(f"/api/admin/notices/{VOC}/publish", headers=AH)
drain()
chk("동의 뒤 다시 게시하면 그 담당자에게만 감", [x[0] for x in SENT["email"]] == ["old@h5.kr"]
    and [x[0] for x in SENT["sms"]] == ["01077770000"], f"{SENT}")
SENT["email"].clear(); SENT["sms"].clear()
c.post(f"/api/admin/notices/{VOC}/publish", headers=AH)
drain()
chk("또 게시해도 중복 없음", SENT["email"] == [] and SENT["sms"] == [])
r = c.put(f"/api/admin/schools/{H5ID}/contact", headers=AH, json={
    "name": "옛담당", "email": "old@h5.kr", "phone": "01077770000", "consent": False})
chk("동의 철회", r.json()["contact"]["consent"] is False)
r = c.post("/api/admin/notices", headers=AH, json={"kind": "vocational", "title": "가을 이벤트",
                                                    "category": "event", "email_enabled": True,
                                                    "sms_enabled": True})
chk("이벤트 공지: 메일·문자 꺼짐", r.json()["email_enabled"] is False and r.json()["sms_enabled"] is False, r.text)
pv = c.post("/api/admin/notices/preview", headers=AH, json={"kind": "board", "title": "t", "category": "event",
                                                             "email_enabled": True}).json()
chk("이벤트 미리보기: 0건·막힘 표시", pv["email"] == 0 and pv["blocked_category"] is True, str(pv))
drain()
chk("이벤트 공지는 안 감", SENT["email"] == [] and SENT["sms"] == [])

print("=== 7. 직업계고 공지가 보이는 범위 ===")
chk("방문자에게 안 보임", c.get(f"/api/notices/{VOC}").status_code == 404)
chk("학생에게 안 보임", c.get(f"/api/notices/{VOC}", headers=STH).status_code == 404)
chk("중학교 계정에 안 보임", c.get(f"/api/notices/{VOC}", headers=MH).status_code == 404)
chk("고등학교 계정에 보임", c.get(f"/api/notices/{VOC}", headers=S1H).status_code == 200)

print("=== 11. 설정 · 학교 계정 목록 ===")
r = c.put("/api/school/notification-settings", headers=H4H, json={
    "notice_email": "", "notice_email_enabled": True,
    "contact": {"name": "최담당", "email": "choi@h4.kr", "phone": "010-7777-8888"}})
chk("고등학교: 담당 선생님 고침", r.status_code == 200 and r.json()["contact"]["name"] == "최담당", r.text)
chk("동의 체크 없이 저장하면 동의 없음", r.json()["contact"]["consent"] is False)
chk("설정 화면에 동의 안내문", "purpose" in r.json()["contact_consent_text"])
r = c.put("/api/school/notification-settings", headers=H4H, json={
    "notice_email": "", "notice_email_enabled": True,
    "contact": {"name": "최담당", "email": "choi@h4.kr", "phone": "010-7777-8888", "consent": True}})
chk("학교가 동의 체크 → 동의 기록", r.json()["contact"]["consent"] is True
    and r.json()["contact"]["consent_source"] == "school")
chk("중학교: 담당 선생님 등록 거부", c.put("/api/school/notification-settings", headers=MH, json={
    "notice_email": "", "contact": {"name": "x"}}).status_code == 403)
chk("잘못된 메일 422", c.put("/api/school/notification-settings", headers=S1H, json={
    "notice_email": "not-mail"}).status_code == 422)
chk("잘못된 휴대폰 422", c.put("/api/school/notification-settings", headers=H4H, json={
    "contact": {"name": "x", "phone": "12345"}}).status_code == 422)
a = c.get("/api/admin/school-accounts", headers=AH).json()
chk("학교 계정 집계 고3·중1", a["counts"] == {"high": 3, "middle": 1}, str(a["counts"]))
chk("중학교 필터", [x["school_name"] for x in c.get("/api/admin/school-accounts", params={"level": "middle"},
                                                     headers=AH).json()["items"]] == ["푸른중학교"])
chk("검색(담당자 이메일)", [x["email"] for x in c.get("/api/admin/school-accounts", params={"q": "h4.kr"},
                                                     headers=AH).json()["items"]] == ["t@h4.kr"])
chk("학교급 바꾸기", c.put(f"/api/admin/schools/{H3ID}/school-level", json={"school_level": "middle"},
                       headers=AH).json()["is_visible"] is False)

print("=== 12. 마이그레이션 ===")
from app import migrate_2026_10_notices as MIG  # noqa: E402
st = MIG.status()
chk("status: 다 적용됨", all(st["tables"].values()) and all(all(v.values()) for v in st["columns"].values()))
MIG.downgrade()
st = MIG.status()
chk("downgrade: 새 표·칸 없음", not any(st["tables"].values())
    and not any(any(v.values()) for v in st["columns"].values()), str(st))
db = SessionLocal()
from sqlalchemy import text  # noqa: E402
chk("downgrade 뒤에도 학교·계정 그대로", db.execute(text("select count(*) from users")).scalar() >= 6
    and db.execute(text("select count(*) from schools")).scalar() >= 5)
db.close()
MIG.upgrade()
st = MIG.status()
chk("upgrade: 다시 다 있음", all(st["tables"].values()) and all(all(v.values()) for v in st["columns"].values()))
db = SessionLocal()
chk("upgrade 뒤 기존 학교는 high 기본값", db.execute(text(
    "select count(*) from schools where school_level='high'")).scalar() >= 4)
db.close()

print(f"\n{sum(OK)}/{len(OK)} 통과")
sys.exit(0 if all(OK) else 1)
