"""유료 서비스 신청 접수 검사.

로그인 없이 받는 창구라 확인할 것이 셋이다.
  1) 신청이 제대로 저장되고, 금액과 계좌가 안내되는가
  2) **가격표를 나중에 올려도 예전 신청의 금액이 안 바뀌는가** — 입금 대조의
     기준이 흔들리면 누가 얼마를 넣었는지 맞출 수가 없다
  3) 아무나 마구 눌러도 버티는가(스팸 제한), 그리고 관리자만 볼 수 있는가
"""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:////tmp/applications.db"
os.environ["SECRET_KEY"] = "x"
os.environ["PARTNER_SECRET"] = "test-partner-secret"
if os.path.exists("/tmp/applications.db"):
    os.remove("/tmp/applications.db")

sys.path.insert(0, ".")
from fastapi.testclient import TestClient              # noqa: E402
from app.main import app                                # noqa: E402
from app.database import SessionLocal                   # noqa: E402
from app.models import Role, ServiceApplication, User    # noqa: E402
from app.auth import create_access_token, hash_password  # noqa: E402
from app import applications as ap                       # noqa: E402

OK = []


def chk(n, c, e=""):
    OK.append(bool(c))
    print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))


db = SessionLocal()
adm = User(email="a@t.kr", password_hash=hash_password("p1234567"),
           name="관리자", role=Role.admin)
stu = User(email="s@t.kr", password_hash=hash_password("p1234567"),
           name="학생", role=Role.student)
db.add(adm); db.add(stu); db.commit()
db.refresh(adm); db.refresh(stu)
AH = {"Authorization": f"Bearer {create_access_token(adm)}"}
SH = {"Authorization": f"Bearer {create_access_token(stu)}"}
db.close()
c = TestClient(app)


def clear_rate():
    """검사마다 IP 제한을 풀어 준다(제한 자체는 따로 검사한다)."""
    ap._RECENT.clear()


BASE = {"name": "홍길동", "phone": "010-1234-5678", "email": "h@t.kr",
        "found_path": "소개", "applicant": "학부모",
        "message": "3학년 진학을 앞두고 상담받고 싶습니다."}

print("=== 1. 신청 전 안내 ===")
r = c.get("/api/applications/info", params={"kind": "plan_consulting"})
chk("로그인 없이 200", r.status_code == 200, r.text)
chk("금액 30만원", r.json()["amount"] == 300000, r.text)
chk("계좌 안내가 있다", "기업은행" in r.json()["bank"], r.text)
chk("없는 종류는 404",
    c.get("/api/applications/info", params={"kind": "없음"}).status_code == 404)

print("=== 2. 신청하기 ===")
clear_rate()
r = c.post("/api/applications", json={"kind": "plan_consulting", **BASE})
chk("로그인 없이 접수 200", r.status_code == 200, r.text)
chk("금액을 알려준다", r.json()["amount"] == 300000, r.text)
chk("계좌를 알려준다", "439-011129-01-016" in r.json()["bank"], r.text)
AID = r.json()["id"]

print("=== 3. 잘못된 입력은 막는다 ===")
clear_rate()
chk("없는 종류 거부",
    c.post("/api/applications", json={"kind": "없음", **BASE}).status_code == 400)
chk("이름이 없으면 거부",
    c.post("/api/applications",
           json={"kind": "counseling", **{**BASE, "name": ""}}).status_code == 422)
chk("전화번호가 없으면 거부",
    c.post("/api/applications",
           json={"kind": "counseling", **{**BASE, "phone": ""}}).status_code == 422)
chk("이상한 경로는 거부",
    c.post("/api/applications",
           json={"kind": "counseling", **{**BASE, "found_path": "해킹"}}).status_code == 400)

print("=== 4. 목록은 관리자만 ===")
chk("로그인 없으면 거부", c.get("/api/admin/applications").status_code in (401, 403))
chk("학생은 거부", c.get("/api/admin/applications", headers=SH).status_code == 403)
r = c.get("/api/admin/applications", headers=AH)
chk("관리자는 200", r.status_code == 200, r.text)
body = r.json()
chk("방금 넣은 신청이 보인다", any(x["id"] == AID for x in body["items"]), r.text)
one = next(x for x in body["items"] if x["id"] == AID)
chk("이름", one["name"] == "홍길동", str(one))
chk("종류 이름을 사람 말로 준다", one["kind_label"] == "직업계고 3년Plan 컨설팅", str(one))
chk("처음 상태는 접수", one["status"] == "received" and one["status_label"] == "접수", str(one))
chk("요청사항이 그대로", "3학년" in one["message"], str(one))
chk("종류별 개수도 준다", body["counts"]["plan_consulting"] == 1, str(body["counts"]))

print("=== 5. 상태와 메모 ===")
r = c.patch(f"/api/admin/applications/{AID}", headers=AH, json={"status": "paid"})
chk("입금 확인으로 200", r.status_code == 200, r.text)
chk("상태가 바뀐다", r.json()["status"] == "paid", r.text)
r = c.patch(f"/api/admin/applications/{AID}", headers=AH,
            json={"admin_note": "10/2 통화, 다음 주 토요일 10시로 잡음"})
chk("메모 저장", "10/2" in r.json()["admin_note"], r.text)
chk("메모만 바꿔도 상태는 그대로", r.json()["status"] == "paid", r.text)
chk("없는 상태는 거부",
    c.patch(f"/api/admin/applications/{AID}", headers=AH,
            json={"status": "이상한상태"}).status_code == 400)
chk("학생은 못 바꾼다",
    c.patch(f"/api/admin/applications/{AID}", headers=SH,
            json={"status": "done"}).status_code == 403)

print("=== 6. 가격을 올려도 예전 신청은 그대로 ===")
# 여기가 흔들리면 입금 대조가 불가능해진다.
before = ap.KINDS["plan_consulting"]["amount"]
ap.KINDS["plan_consulting"]["amount"] = 500000
try:
    clear_rate()
    r2 = c.post("/api/applications", json={"kind": "plan_consulting", **BASE})
    chk("새 신청은 오른 금액", r2.json()["amount"] == 500000, r2.text)
    old = c.get("/api/admin/applications", headers=AH).json()["items"]
    old_one = next(x for x in old if x["id"] == AID)
    chk("예전 신청은 신청 당시 금액", old_one["amount"] == 300000, str(old_one))
finally:
    ap.KINDS["plan_consulting"]["amount"] = before

print("=== 7. 거르기 ===")
clear_rate()
c.post("/api/applications", json={"kind": "counseling", **BASE})
r = c.get("/api/admin/applications", headers=AH, params={"kind": "counseling"})
chk("종류로 거른다", all(x["kind"] == "counseling" for x in r.json()["items"]), r.text)
r = c.get("/api/admin/applications", headers=AH, params={"status": "paid"})
chk("상태로 거른다", all(x["status"] == "paid" for x in r.json()["items"]), r.text)

print("=== 8. 엑셀로 받기 ===")
r = c.get("/api/admin/applications.csv", headers=AH)
chk("내려받기 200", r.status_code == 200, r.text[:200])
chk("엑셀이 한글을 안 깨도록 BOM", r.content.startswith(b"\xef\xbb\xbf"), str(r.content[:6]))
text = r.content.decode("utf-8-sig")
chk("머리줄이 있다", "신청일" in text and "연락처" in text, text[:120])
chk("내용이 들어 있다", "홍길동" in text, text[:200])
chk("학생은 못 받는다",
    c.get("/api/admin/applications.csv", headers=SH).status_code == 403)

print("=== 9. 스팸 제한 ===")
clear_rate()
codes = [c.post("/api/applications", json={"kind": "counseling", **BASE}).status_code
         for _ in range(ap.MAX_PER_HOUR + 2)]
chk("처음 몇 건은 받는다", codes[:ap.MAX_PER_HOUR] == [200] * ap.MAX_PER_HOUR, str(codes))
chk("그 뒤로는 429", codes[-1] == 429, str(codes))
clear_rate()
chk("제한이 풀리면 다시 받는다",
    c.post("/api/applications", json={"kind": "counseling", **BASE}).status_code == 200)

print("=== 10. 설정(알림 메일·계좌) ===")
chk("학생은 설정을 못 본다",
    c.get("/api/admin/application-settings", headers=SH).status_code == 403)
r = c.put("/api/admin/application-settings", headers=AH,
          json={"notify_email": "boss@t.kr", "bank": "우리은행 1002-000-000000 (홍길동)"})
chk("설정 저장 200", r.status_code == 200, r.text)
chk("메일 주소 저장", r.json()["notify_email"] == "boss@t.kr", r.text)
clear_rate()
r = c.post("/api/applications", json={"kind": "counseling", **BASE})
chk("바꾼 계좌가 안내된다", "우리은행" in r.json()["bank"], r.text)
r = c.put("/api/admin/application-settings", headers=AH,
          json={"notify_email": "", "bank": ""})
chk("계좌를 비우면 기본값으로", "기업은행" in r.json()["bank"], r.text)

print("=== 11. 삭제 ===")
chk("학생은 못 지운다",
    c.delete(f"/api/admin/applications/{AID}", headers=SH).status_code == 403)
chk("관리자는 지운다",
    c.delete(f"/api/admin/applications/{AID}", headers=AH).status_code == 200)
chk("정말 사라졌다",
    not any(x["id"] == AID
            for x in c.get("/api/admin/applications", headers=AH).json()["items"]))
chk("없는 것을 지우면 404",
    c.delete("/api/admin/applications/99999", headers=AH).status_code == 404)

print("=== 12. 설명회 시청 신청은 돈을 안 받는다 ===")
clear_rate()
r = c.post("/api/applications", json={
    "kind": "briefing_survey", "name": "김학생", "phone": "010-0000-0000",
    "found_path": "검색", "applicant": "학생",
    "extra": {"중학교": "양주중학교"}})
chk("접수 200", r.status_code == 200, r.text)
chk("금액 0원", r.json()["amount"] == 0, r.text)
items = c.get("/api/admin/applications", headers=AH,
              params={"kind": "briefing_survey"}).json()["items"]
chk("폼마다 다른 항목도 남는다", items[0]["extra"].get("중학교") == "양주중학교", str(items[0]))

print("=== 13. 신청 시각에 시간대가 붙는다 ===")
# 표시가 없으면 브라우저가 제 지역 시간으로 읽어 9시간이 어긋난다.
clear_rate()
r = c.post("/api/applications", json={"kind": "counseling", **BASE})
one = c.get("/api/admin/applications", headers=AH).json()["items"][0]
chk("created_at 이 문자열", isinstance(one["created_at"], str), str(type(one["created_at"])))
chk("시간대 표시가 있다",
    one["created_at"].endswith("+00:00") or one["created_at"].endswith("Z"),
    one["created_at"])

print(f"\n===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
