"""연구·논문 서비스가 혼자 힘으로 도는지 확인한다.

기록해에서 떼어낸 직후라, 확인할 것은 "연구 기능이 잘 되는가"보다
**남의 것에 기대지 않는가**다.
  1) 여기서 가입하고 로그인이 되는가 (UDJ 없이)
  2) 연구를 만들고 다시 읽을 수 있는가
  3) 기록해에만 있던 화면(일지·자소서·이용권)이 정말 사라졌는가
  4) 남의 연구를 못 보는가
"""
import os
import sys

os.environ["RESEARCH_DATABASE_URL"] = "sqlite:////tmp/research_smoke.db"
os.environ["SECRET_KEY"] = "test-secret-key-for-research-service-x"
if os.path.exists("/tmp/research_smoke.db"):
    os.remove("/tmp/research_smoke.db")

sys.path.insert(0, ".")
from fastapi.testclient import TestClient   # noqa: E402
from app.main import app                     # noqa: E402

OK = []


def chk(n, c, e=""):
    OK.append(bool(c))
    print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))


c = TestClient(app)

SIGNUP = {"email": "a@t.kr", "password": "p1234567", "name": "학생",
          "role": "student", "school_name": "양주중학교",
          "privacy_consent": True, "terms_consent": True}

print("=== 1. 이 서비스에서 직접 가입한다 ===")
r = c.post("/api/auth/signup", json=SIGNUP)
chk("가입 200", r.status_code == 200, r.text)
chk("바로 토큰을 준다", bool(r.json().get("access_token")), r.text)
TOKEN = r.json()["access_token"]
H = {"Authorization": f"Bearer {TOKEN}"}

chk("같은 이메일은 다시 못 만든다",
    c.post("/api/auth/signup", json=SIGNUP).status_code == 400)
chk("동의 없이는 못 만든다",
    c.post("/api/auth/signup",
           json={**SIGNUP, "email": "b@t.kr", "terms_consent": False}).status_code == 400)
chk("짧은 비밀번호는 거부",
    c.post("/api/auth/signup",
           json={**SIGNUP, "email": "c@t.kr", "password": "123"}).status_code == 422)

print("=== 2. 로그인 ===")
r = c.post("/api/auth/login", json={"email": "a@t.kr", "password": "p1234567"})
chk("로그인 200", r.status_code == 200, r.text)
chk("이름을 돌려준다", r.json()["user"]["name"] == "학생", r.text)
r = c.post("/api/auth/login", json={"email": "a@t.kr", "password": "틀린비밀번호"})
chk("비밀번호가 틀리면 401", r.status_code == 401, r.text)
# 없는 이메일과 틀린 비밀번호를 구분해 알려주면 가입 여부를 훑을 수 있다.
r2 = c.post("/api/auth/login", json={"email": "none@t.kr", "password": "p1234567"})
chk("없는 계정도 같은 401", r2.status_code == 401 and r2.json() == r.json(), r2.text)

print("=== 3. 내 정보 ===")
r = c.get("/api/auth/me", headers=H)
chk("내 정보 200", r.status_code == 200, r.text)
chk("로그인 없이는 거부", c.get("/api/auth/me").status_code in (401, 403))
r = c.patch("/api/me", headers=H, json={"school_name": "옮긴중학교"})
chk("소속을 내가 고친다", r.json()["school_name"] == "옮긴중학교", r.text)

print("=== 4. 비밀번호 바꾸기 ===")
chk("지금 비밀번호가 틀리면 거부",
    c.post("/api/me/change-password", headers=H,
           json={"current_password": "x1234567", "new_password": "n1234567"}).status_code == 400)
chk("맞으면 바뀐다",
    c.post("/api/me/change-password", headers=H,
           json={"current_password": "p1234567", "new_password": "n1234567"}).status_code == 200)
chk("새 비밀번호로 로그인",
    c.post("/api/auth/login", json={"email": "a@t.kr", "password": "n1234567"}).status_code == 200)
chk("옛 비밀번호는 안 된다",
    c.post("/api/auth/login", json={"email": "a@t.kr", "password": "p1234567"}).status_code == 401)

print("=== 5. 연구를 만들고 읽는다 ===")
r = c.post("/api/research", headers=H, json={"interest_keyword": "플라스틱 분해"})
chk("연구 생성 200", r.status_code == 200, r.text)
RID = r.json().get("id")
chk("번호를 준다", bool(RID), r.text)
r = c.get("/api/research", headers=H)
chk("목록에 나온다", any(x["id"] == RID for x in r.json()["items"]), r.text)
r = c.get(f"/api/research/{RID}", headers=H)
chk("상세 200", r.status_code == 200, r.text)

print("=== 6. 남의 연구는 못 본다 ===")
r = c.post("/api/auth/signup", json={**SIGNUP, "email": "other@t.kr"})
H2 = {"Authorization": f"Bearer {r.json()['access_token']}"}
chk("남의 연구는 404", c.get(f"/api/research/{RID}", headers=H2).status_code == 404)
chk("남의 목록에는 안 보인다",
    not any(x["id"] == RID for x in c.get("/api/research", headers=H2).json()["items"]))

print("=== 7. 기록해 기능은 따라오지 않았다 ===")
# 여기 남아 있으면 떼어낸 의미가 없다.
for path in ("/api/journals", "/api/cover-letters", "/api/portfolios",
             "/api/subscription/me", "/api/seat-codes/redeem",
             "/api/teacher/observations", "/api/school/classes"):
    chk(f"{path} 없음", c.get(path, headers=H).status_code == 404, path)

print("=== 8. 살아 있어야 하는 것 ===")
chk("헬스체크", c.get("/api/health").status_code == 200)
chk("AI 상태", c.get("/api/ai/status", headers=H).status_code == 200)
chk("학과 계열 목록", c.get("/api/dept-fields").status_code == 200)

print(f"\n===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
