"""지시서 [43] 기존 기능 회귀. AI 를 붙이며 깨진 것이 없는지 본다."""
import os,sys,json
os.environ["DATABASE_URL"]="sqlite:////tmp/rg.db"; os.environ["SECRET_KEY"]="x"

# 앞선 검사의 자료가 남아 있으면 결과가 달라져,
# 멀쩡한 코드가 실패한 것처럼 보인다. 먼저 지운다.
if os.path.exists("/tmp/rg.db"):
    os.remove("/tmp/rg.db")
os.environ.pop("ANTHROPIC_API_KEY", None)      # 키 없는 평소 상태
for k in ("TOSS_SECRET_KEY","TOSS_CLIENT_KEY"): os.environ.pop(k,None)
sys.path.insert(0,".")
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import *
from app.auth import create_access_token
from datetime import datetime, timedelta, date
OK=[]
def chk(n,c,e=""):
    OK.append(bool(c)); print(("  OK  " if c else "  FAIL")+f"  {n}"+(f"  {e}" if not c and e else ""))

db=SessionLocal()
adm=User(udj_user_id=1,email="a@t.kr",name="관리자",role=Role.admin)
sch=User(udj_user_id=2,email="sc@t.kr",name="학교",role=Role.school,school_id=7)
tea=User(udj_user_id=3,email="t@t.kr",name="교사",role=Role.teacher,school_id=7,class_name="2-3")
stu=User(udj_user_id=4,email="s@t.kr",name="홍길동",role=Role.student,school_id=7,
         teacher_udj_id=3,verified=True)
for u in (adm,sch,tea,stu): db.add(u)
db.commit(); [db.refresh(u) for u in (adm,sch,tea,stu)]
now=datetime.utcnow()
db.add(SchoolSeat(school_id=7,seats=5,started_at=now,expires_at=now+timedelta(days=300)))
db.add(SeatHolder(school_id=7,user_id=stu.id))
for k,v in [("bank_name","기업"),("bank_account","439"),("bank_holder","강"),
            ("payment_method","bank")]:
    db.add(Setting(key=k,value=v))
db.commit()
AH={"Authorization":f"Bearer {create_access_token(adm)}"}
CH={"Authorization":f"Bearer {create_access_token(sch)}"}
TH={"Authorization":f"Bearer {create_access_token(tea)}"}
SH={"Authorization":f"Bearer {create_access_token(stu)}"}
db.close()
c=TestClient(app)

print("=== 일지 ===")
r=c.post("/api/journals", json={"kind":"diary","entry_date":"2026-05-01","title":"선반 실습",
  "content":{"memorable":"선반 실습에서 치수가 안 맞아 세 번 다시 했습니다."}}, headers=SH)
chk("작성", r.status_code==200, str(r.json())[:80]); JID=r.json()["id"]
chk("제목 없으면 거부", c.post("/api/journals", json={"kind":"diary","entry_date":"2026-05-01",
  "content":{"memorable":"제목 없이 써본다."}}, headers=SH).status_code==400)
rows=c.get("/api/journals", headers=SH).json()
chk("목록", len(rows)==1)
chk("목록에 제목", rows[0].get("title")=="선반 실습", str(rows[0])[:100])
# 자소서에서 일지를 직접 골라야 해서, 날짜만으로는 어느 것인지 알 수 없다.
chk("목록에 미리보기", rows[0].get("preview"), str(rows[0])[:100])
chk("목록에 종류 이름", rows[0].get("kind_label"), str(rows[0].get("kind_label")))
chk("조회", c.get(f"/api/journals/{JID}", headers=SH).status_code==200)
r=c.put(f"/api/journals/{JID}", json={"kind":"diary","entry_date":"2026-05-01","title":"선반 실습(수정)",
  "content":{"memorable":"고친 내용입니다. 이송 속도를 줄이니 치수가 맞았습니다."}}, headers=SH)
chk("수정", r.status_code==200, str(r.json())[:80])
chk("제출", c.post(f"/api/journals/{JID}/submit", headers=SH).status_code==200)
chk("공유", c.post(f"/api/journals/{JID}/share", headers=SH).status_code==200)

print("=== 교사·학교 ===")
chk("교사 목록", c.get("/api/teacher/journals", headers=TH).status_code==200)
chk("피드백", c.post(f"/api/teacher/journals/{JID}/feedback",
    json={"text":"잘했어요"}, headers=TH).status_code==200)
chk("학교 대시보드", c.get("/api/school/dashboard", headers=CH).status_code==200)
chk("학생 명단", c.get("/api/school/students", headers=CH).status_code==200)
chk("좌석 현황", c.get("/api/school/seats", headers=CH).status_code==200)

print("=== 자기소개서 ===")
r=c.post("/api/cover-letters", json={"title":"지원","content":{"strength":"꼼꼼합니다."}}, headers=SH)
chk("작성", r.status_code==200); CID=r.json()["id"]
chk("목록", len(c.get("/api/cover-letters", headers=SH).json())>=1)
chk("수정", c.put(f"/api/cover-letters/{CID}",
    json={"title":"지원2","content":{"strength":"꼼꼼한 것이 강점입니다."}}, headers=SH).status_code==200)
m=c.get("/api/cover-letters/materials", headers=SH).json()
chk("재료 찾기", len(m["topics"])==13, str(len(m.get("topics",[]))))
chk("항목 13개", len(c.get("/api/journal-meta", headers=SH).json()["resume_templates"])==13)

print("=== 글 도구 ===")
chk("맞춤법", c.post("/api/spellcheck", json={"fields":{"a":"안녕하세요"}}).status_code==200)
chk("글 살펴보기", c.post("/api/cover-letters/review",
    json={"fields":{"a":"내용입니다."},"limit":1000}, headers=SH).status_code==200)
r=c.post("/api/cover-letters/polish", json={"text":"진짜 개빡쳤음"}, headers=SH)
chk("말투 다듬기", r.status_code==200 and r.json()["changed"], str(r.json())[:80])

print("=== 문서 내려받기 ===")
for fmt in ("pdf","docx","hwpx","txt"):
    chk(f"{fmt}", c.get(f"/api/cover-letters/{CID}/download",
        params={"fmt":fmt}, headers=SH).status_code==200)

print("=== 관리자 ===")
chk("통계", c.get("/api/admin/stats", headers=AH).status_code==200)
chk("설정", c.get("/api/admin/settings", headers=AH).status_code==200)
chk("이용권 신청 목록", c.get("/api/admin/seat-orders", headers=AH).status_code==200)

print("=== 약관·규정 ===")
chk("환불 규정", c.get("/api/refund-policy").status_code==200)

print("=== 키가 없어도 AI 만 막힌다 ===")
st=c.get("/api/ai/status", headers=SH).json()
chk("쓸 수 없다고 알림", st["available"] is False, str(st))
chk("분석 막힘", c.post(f"/api/journals/{JID}/analyze", headers=SH).status_code==503)
chk("나머지는 전부 정상", c.get("/api/journals", headers=SH).status_code==200)
print(); print(f"===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
