"""UDJ 에서 학생이 겪는 흐름을 순서대로 훑는다."""
import os,sys
os.environ["DATABASE_URL"]="sqlite:////tmp/uf.db"; os.environ["SECRET_KEY"]="x"

# 앞선 검사의 자료가 남아 있으면 결과가 달라져,
# 멀쩡한 코드가 실패한 것처럼 보인다. 먼저 지운다.
if os.path.exists("/tmp/uf.db"):
    os.remove("/tmp/uf.db")
sys.path.insert(0,".")
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import *
from app.auth import hash_password, create_access_token
from sqlalchemy import func as F
OK=[]
def chk(n,c,e=""):
    OK.append(bool(c)); print(("  OK  " if c else "  FAIL")+f"  {n}"+(f"  {e}" if not c and e else ""))

db=SessionLocal()
ids=[]
for nm,dep,la,ln in [
    ("양주기계고","기계과\n자동차과",37.79,127.05),
    ("양주소프트고","소프트웨어과\n정보통신과",37.80,127.06),
    ("서울농생명고","농업과\n원예과",37.55,126.99)]:
    s=School(name=nm,category="특성화고",region="경기" if "양주" in nm else "서울",
             address="a",coed=Coed.coed,departments=dep,latitude=la,longitude=ln,
             is_visible=True)
    db.add(s); db.commit(); db.refresh(s); ids.append(s.id)
# 직업계고가 아닌 학교. 추천에 섞이면 안 된다.
db.add(School(name="양주외고",category="외국어고",region="경기",address="a",
              coed=Coed.coed,departments="영어과",latitude=37.79,longitude=127.05,
              is_visible=True))
db.commit(); db.close()
c=TestClient(app)

print("=== 1. 학교를 찾는다 ===")
r=c.get("/api/schools", params={"q":"양주"}).json()
chk("이름으로 검색", r["total"]>=2, str(r["total"]))
r=c.get("/api/schools", params={"region":"경기"}).json()
chk("지역으로 검색", r["total"]>=2, str(r["total"]))

print("=== 2. 진로 테스트 ===")
q=c.get("/api/quiz/questions").json()
seeds={c.get("/api/quiz/questions").json()["seed"] for _ in range(3)}
chk("문항이 매번 다름", len(seeds)>=2, str(len(seeds)))
r=c.post("/api/quiz/result", json={"answers":["5"]*36,"seed":q["seed"],
  "lat":37.79,"lng":127.06,"location_label":"경기도 양주시","commute_time":"1h"}).json()
chk("결과 나옴", r.get("departments"), str(r)[:80])
names=[s["name"] for s in r.get("schools",[])]
chk("외고는 안 나옴", "양주외고" not in names, str(names))
chk("가까운 곳 위주", all("양주" in n for n in names) if names else True, str(names))

print("=== 3. 같은 seed 면 같은 문항 ===")
a=c.get("/api/quiz/questions", params={"seed":q["seed"]}).json()
chk("되살아남", [x["q"] for x in a["questions"]]==[x["q"] for x in q["questions"]])

print("=== 4. 노출·수요가 쌓인다 ===")
db=SessionLocal()
shown=db.query(F.coalesce(F.sum(SchoolExposure.search_count),0)).scalar()
quiz=db.query(F.coalesce(F.sum(SchoolExposure.quiz_count),0)).scalar()
dem=db.query(QuizDemand).all()
db.close()
chk("검색 노출 기록", shown>0, str(shown))
chk("추천 기록", quiz>0, str(quiz))
chk("지역 수요 기록", len(dem)>0, str([(d.region,d.axis) for d in dem][:3]))
chk("지역이 시·군까지", all(d.region=="경기도 양주시" for d in dem),
    str({d.region for d in dem}))

print("=== 5. 진단 도구 ===")
import subprocess
out=subprocess.run([sys.executable,"-m","app.diagnose_quiz"],
    capture_output=True,text=True,encoding="utf-8",env={**os.environ}).stdout
chk("진단 동작", "직업계고 학교" in out, out[:120])
chk("직업계고만 셈", "3곳" in out.split("\n")[1] if len(out.split("\n"))>1 else False,
    out.split("\n")[1] if len(out.split("\n"))>1 else "")
print(); print(f"===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
