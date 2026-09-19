"""이용권 코드로 학년·반·학과가 옮겨지는지 본다.

학생이 직접 고르면 오타가 나고, 반을 잘못 고르면 담당 선생님과
이어지지 않는다. 코드에 딸려 오게 한 것이 실제로 도는지 확인한다.
"""
import os,sys,json
os.environ["DATABASE_URL"]="sqlite:////tmp/cc.db"; os.environ["SECRET_KEY"]="x"

# 앞선 검사의 자료가 남아 있으면 결과가 달라져,
# 멀쩡한 코드가 실패한 것처럼 보인다. 먼저 지운다.
if os.path.exists("/tmp/cc.db"):
    os.remove("/tmp/cc.db")
for k in ("TOSS_SECRET_KEY","TOSS_CLIENT_KEY"): os.environ.pop(k,None)
sys.path.insert(0,".")
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import *
from app.auth import create_access_token
from datetime import datetime, timedelta
OK=[]
def chk(n,c,e=""):
    OK.append(bool(c)); print(("  OK  " if c else "  FAIL")+f"  {n}"+(f"  {e}" if not c and e else ""))

db=SessionLocal()
tea=User(udj_user_id=10,email="t@t.kr",name="김선생",role=Role.teacher,school_id=7)
stu=User(udj_user_id=11,email="s@t.kr",name="홍길동",role=Role.student,school_id=7,verified=True)
sch=User(udj_user_id=12,email="sc@t.kr",name="학교",role=Role.school,school_id=7)
for u in (tea,stu,sch): db.add(u)
db.commit(); [db.refresh(u) for u in (tea,stu,sch)]
now=datetime.utcnow()
db.add(SchoolSeat(school_id=7,seats=100,started_at=now,expires_at=now+timedelta(days=300)))
db.commit()
TH={"Authorization":f"Bearer {create_access_token(tea)}"}
SH={"Authorization":f"Bearer {create_access_token(stu)}"}
CH={"Authorization":f"Bearer {create_access_token(sch)}"}
db.close()
c=TestClient(app)

print("=== 1. 선생님이 담당 학급을 적는다 ===")
r=c.patch("/api/me/class", json={"grade":2,"class_name":"3반","department":"기계과"}, headers=TH)
chk("저장됨", r.status_code==200, str(r.json())[:100])
m=r.json()
chk("학년", m["grade"]==2); chk("반", m["class_name"]=="3반"); chk("학과", m["department"]=="기계과")
chk("학생은 못 씀", c.patch("/api/me/class", json={"grade":1}, headers=SH).status_code==403)
chk("이상한 학년 거부", c.patch("/api/me/class", json={"grade":9}, headers=TH).status_code==400)

print("=== 2. 코드에 담긴다 ===")
r=c.post("/api/school/seat-codes", json={"max_uses":30}, headers=TH)
chk("코드 발급", r.status_code==200, str(r.json())[:100])
code=r.json()
chk("학년 담김", code["grade"]==2, str(code))
chk("반 담김", code["class_no"]=="3반")
chk("학과 담김", code["department"]=="기계과")
chk("이름표 자동", code["label"]=="2학년 3반 기계과", code["label"])

print("=== 3. 학생이 코드를 넣으면 옮겨진다 ===")
db=SessionLocal(); s0=db.query(User).filter(User.email=="s@t.kr").first()
chk("등록 전엔 비어 있음", not s0.grade and not s0.class_name, f"{s0.grade} {s0.class_name}")
db.close()
r=c.post("/api/seat-codes/redeem", json={"code":code["code"]}, headers=SH)
chk("등록됨", r.status_code==200 and r.json()["ok"], str(r.json())[:100])
chk("어디로 갔는지 알려줌", "2학년 3반 기계과" in r.json()["message"], r.json()["message"])
db=SessionLocal(); s1=db.query(User).filter(User.email=="s@t.kr").first()
chk("학년 옮겨짐", s1.grade==2, str(s1.grade))
chk("반 옮겨짐", s1.class_name=="3반", s1.class_name)
chk("학과 옮겨짐", s1.department=="기계과", s1.department)
chk("담당 선생님 이어짐", s1.teacher_udj_id==10, str(s1.teacher_udj_id))
db.close()

print("=== 4. 다음 로그인에 되돌아가지 않는다 ===")
db=SessionLocal(); s2=db.query(User).filter(User.email=="s@t.kr").first()
# UDJ 가 학급 정보를 주지 않는 경우(직업계고는 대개 그렇다)
s2.apply_profile({"email":"s@t.kr","name":"홍길동","role":"student",
                  "school_id":7,"school_name":"근명고","verified":True})
db.commit(); db.refresh(s2)
chk("학년 유지", s2.grade==2, str(s2.grade))
chk("반 유지", s2.class_name=="3반", s2.class_name)
chk("학과 유지", s2.department=="기계과", s2.department)
# UDJ 가 값을 주면 그것을 따른다
s2.apply_profile({"email":"s@t.kr","name":"홍길동","role":"student",
                  "school_id":7,"school_name":"근명고","verified":True,
                  "grade":3,"class_name":"1반","department":"전기과"})
db.commit(); db.refresh(s2)
chk("UDJ 가 주면 따름", s2.grade==3 and s2.class_name=="1반", f"{s2.grade} {s2.class_name}")
db.close()

print("=== 5. 학교 계정은 직접 적는다 ===")
r=c.post("/api/school/seat-codes",
  json={"max_uses":20,"grade":1,"class_no":"5반","department":"전기과"}, headers=CH)
chk("발급됨", r.status_code==200, str(r.json())[:100])
chk("적은 대로", r.json()["grade"]==1 and r.json()["class_no"]=="5반", str(r.json())[:80])

print("=== 6. 학급 없는 코드도 된다 ===")
db=SessionLocal()
t2=User(udj_user_id=13,email="t2@t.kr",name="이선생",role=Role.teacher,school_id=7)
db.add(t2); db.commit(); db.refresh(t2)
T2={"Authorization":f"Bearer {create_access_token(t2)}"}
s3=User(udj_user_id=14,email="s3@t.kr",name="김학생",role=Role.student,school_id=7,verified=True)
db.add(s3); db.commit(); db.refresh(s3)
S3={"Authorization":f"Bearer {create_access_token(s3)}"}
db.close()
r=c.post("/api/school/seat-codes", json={"max_uses":5}, headers=T2).json()
chk("학급 없이도 발급", r.get("code"), str(r)[:80])
rr=c.post("/api/seat-codes/redeem", json={"code":r["code"]}, headers=S3)
chk("등록됨", rr.status_code==200, str(rr.json())[:80])
chk("배정 문구 없음", "배정" not in rr.json()["message"], rr.json()["message"])
print(); print(f"===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
