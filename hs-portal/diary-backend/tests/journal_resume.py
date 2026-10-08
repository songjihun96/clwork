"""일지 → 자기소개서 연결 검사 (업.pdf 9~16번).

확인할 것:
  (1) 이름: 학교생활일지 · 수업일지. 수업일지는 새 양식(해결 못한/해결한 내용)
  (2) 일지에 자소서 카테고리 0개·1개·여러 개를 달고, 고치고, 지울 수 있다
      - 카테고리를 안 보낸 저장(예전 화면)은 달아 둔 것을 지우지 않는다
      - 모르는 키는 버린다 / 일지를 지우면 카테고리도 지워진다
  (3) 남의 일지는 못 본다
  (4) 예전 수업일지 양식의 글이 사라지지 않는다(재료·AI 에 그대로 쓰임)
  (5) "이 항목에 쓸 만한 내 기록": 직접 단 카테고리 → 직업군 → 내용 순
  (6) 자소서에 직업군·질문 답을 저장한다. 모르는 직업군은 거절
  (7) 초안: 직업군과 카테고리가 AI 에 넘어가고, 쓴 기록 목록이 돌아온다
  (8) 지원동기·목표 질문: 1~2학년 기록만, 없는 기록을 근거로 댄 질문은 근거에서 뺀다
  (9) 학생의 답으로 초안을 쓸 수 있다
실행:  cd diary-backend && python tests/journal_resume.py
"""
import json
import os
import sys
import tempfile
import time

DB = os.path.join(tempfile.gettempdir(), "diary_journal_resume.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB.replace("\\", "/")
os.environ["SECRET_KEY"] = "x"
os.environ["ANTHROPIC_API_KEY"] = "test-key"
if os.path.exists(DB):
    os.remove(DB)
sys.path.insert(0, ".")

from datetime import date, datetime, timedelta  # noqa: E402

import requests  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import ai_jobs  # noqa: E402
from app.auth import create_access_token  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app, school_year_of  # noqa: E402
from app.models import (JournalEntry, JournalResumeTag, Role, SchoolSeat,  # noqa: E402
                        SeatHolder, User)

OK = []


def chk(n, c, e=""):
    OK.append(bool(c))
    print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))


db = SessionLocal()
stu = User(udj_user_id=3, email="s@t.kr", name="홍길동", role=Role.student,
           school_id=7, school_name="근명고등학교", verified=True, grade=3)
other = User(udj_user_id=4, email="o@t.kr", name="김철수", role=Role.student,
             school_id=7, school_name="근명고등학교", verified=True, grade=3)
db.add_all([stu, other])
db.commit()
db.refresh(stu)
db.refresh(other)
now = datetime.utcnow()
db.add(SchoolSeat(school_id=7, seats=5, started_at=now, expires_at=now + timedelta(days=300)))
db.add(SeatHolder(school_id=7, user_id=stu.id))
db.commit()
SH = {"Authorization": f"Bearer {create_access_token(stu)}"}
OH = {"Authorization": f"Bearer {create_access_token(other)}"}
STU_ID = stu.id

# 지금 3학년 → 두 해 전 학년도가 1학년, 한 해 전이 2학년, 올해가 3학년.
SY = school_year_of(date.today())
D1 = date(SY - 2, 5, 10)     # 1학년
D2 = date(SY - 1, 9, 3)      # 2학년
D3 = date(SY, 4, 2) if date.today() >= date(SY, 4, 2) else date(SY, 3, 5)   # 3학년
db.close()

c = TestClient(app)
ai_jobs.POLL_SECONDS = 0.2
ai_jobs.start()

PROMPTS = []


class Res:
    def __init__(self, b):
        self.status_code = 200
        self._b = b

    def json(self):
        return self._b


def reply(fn):
    def f(url, headers=None, json=None, timeout=None):
        import json as J
        body = json["messages"][0]["content"]
        PROMPTS.append(body)
        return Res({"content": [{"type": "text", "text": J.dumps(fn(body), ensure_ascii=False)}],
                    "usage": {"input_tokens": 1, "output_tokens": 1}})
    return f


def wait(job_id, sec=8):
    for _ in range(int(sec * 10)):
        time.sleep(0.1)
        r = c.get(f"/api/ai/jobs/{job_id}", headers=SH).json()
        if r["status"] in ("done", "failed"):
            return r
    return {"status": "timeout"}


def new_journal(body, h=SH):
    r = c.post("/api/journals", json=body, headers=h)
    return r


print("=== 1. 이름과 양식 ===")
meta = c.get("/api/journal-meta").json()
labels = {k["kind"]: k["label"] for k in meta["kinds"]}
chk("학교생활일지", labels["diary"] == "학교생활일지", str(labels))
chk("수업일지", labels["lesson"] == "수업일지", str(labels))
lesson = next(k for k in meta["kinds"] if k["kind"] == "lesson")
keys = [f["key"] for f in lesson["fields"]]
chk("학습목적·학습목표 칸이 없다", "objective" not in keys and "goal" not in keys, str(keys))
chk("해결 못한 내용 3칸", {"problem", "result", "unsolved_lesson"} <= set(keys), str(keys))
chk("해결한 내용 3칸", {"solved_problem", "solved_process", "solved_lesson"} <= set(keys), str(keys))
chk("소제목 두 개", [s["title"] for s in lesson["sections"]] ==
    ["수업시간에 해결하지 못한 내용", "수업시간에 해결 했던 내용"], str(lesson["sections"]))
chk("예전 칸은 따로 알려 준다",
    {f["key"] for f in lesson["legacy_fields"]} == {"objective", "goal", "solution"})
chk("수업을 통해 느낀 점은 다시 입력 칸(수업내용 바로 다음)", keys[:2] == ["content", "feeling"], str(keys))
chk("결과 칸 이름", next(f["label"] for f in lesson["fields"] if f["key"] == "result").startswith("2) 문제해결 과정 및 결과"))
chk("자소서 카테고리 11개", len(meta["resume_categories"]) == 11, str(len(meta["resume_categories"])))
chk("지원동기는 카테고리가 아니다",
    "apply_motive" not in [x["key"] for x in meta["resume_categories"]])
chk("직업군 21개", len(meta["job_categories"]) == 21, str(len(meta["job_categories"])))
chk("직업군 이름", meta["job_categories"][5]["label"] == "IT·개발·데이터", str(meta["job_categories"][5]))

print("=== 2. 카테고리 0개 · 1개 · 여러 개 ===")
r = new_journal({"kind": "diary", "entry_date": D1.isoformat(), "title": "카테고리 없음",
                 "content": {"memorable": "오늘은 평범한 하루였습니다."}})
chk("0개 저장", r.status_code == 200 and r.json()["resume_tags"] == [], r.text)
J0 = r.json()["id"]
r = new_journal({"kind": "diary", "entry_date": D1.isoformat(), "title": "조별 과제",
                 "content": {"memorable": "조별 과제에서 발표 자료 정리를 맡았습니다. 팀원이 늦어 제가 끝까지 정리했습니다."},
                 "resume_tags": ["teamwork"]})
chk("1개 저장", r.json()["resume_tags"] == ["teamwork"], r.text)
J1 = r.json()["id"]
r = new_journal({"kind": "lesson", "entry_date": D2.isoformat(), "title": "파이썬 반복문",
                 "subject": "프로그래밍",
                 "content": {"content": "파이썬 반복문을 배웠습니다.",
                             "solved_problem": "for 문에서 range 끝 값이 헷갈렸습니다.",
                             "solved_process": "코드를 직접 바꿔 실행해 보며 끝 값이 빠진다는 걸 확인했습니다.",
                             "solved_lesson": "직접 실행해 보는 것이 가장 빠르다는 걸 배웠습니다."},
                 "resume_tags": ["learning", "problem_solving", "모르는키", "learning"]})
chk("여러 개 저장(모르는 키·중복은 버림)",
    r.json()["resume_tags"] == ["problem_solving", "learning"], r.text)
J2 = r.json()["id"]
d = c.get(f"/api/journals/{J2}", headers=SH).json()
chk("상세에 카테고리", d["resume_tags"] == ["problem_solving", "learning"], str(d.get("resume_tags")))
chk("새 칸 내용이 저장됨", "range" in d["content"]["solved_problem"], str(d["content"]))
lst = c.get("/api/journals", headers=SH).json()
chk("목록에 카테고리", next(x for x in lst if x["id"] == J2)["resume_tags"] == ["problem_solving", "learning"])
chk("목록의 종류 이름", next(x for x in lst if x["id"] == J2)["kind_label"] == "수업일지")

print("=== 3. 고치기 ===")
base = {"kind": "lesson", "entry_date": D2.isoformat(), "title": "파이썬 반복문",
        "subject": "프로그래밍", "content": d["content"]}
r = c.put(f"/api/journals/{J2}", json={**base, "resume_tags": ["learning", "challenge"]}, headers=SH)
chk("카테고리 바꾸기", r.json()["resume_tags"] == ["challenge", "learning"], r.text)
r = c.put(f"/api/journals/{J2}", json=base, headers=SH)
chk("카테고리를 안 보내면 그대로", r.json()["resume_tags"] == ["challenge", "learning"], r.text)
r = c.put(f"/api/journals/{J2}", json={**base, "resume_tags": []}, headers=SH)
chk("빈 목록을 보내면 모두 뺀다", r.json()["resume_tags"] == [], r.text)
c.put(f"/api/journals/{J2}", json={**base, "resume_tags": ["learning", "problem_solving"]}, headers=SH)

print("=== 4. 남의 일지 ===")
chk("남의 일지 상세 404", c.get(f"/api/journals/{J1}", headers=OH).status_code == 404)
chk("남의 일지 고치기 404",
    c.put(f"/api/journals/{J1}", json={**base, "resume_tags": []}, headers=OH).status_code == 404)
chk("남의 목록에 안 보임", c.get("/api/journals", headers=OH).json() == [])

print("=== 5. 지우면 카테고리도 지워진다 ===")
r = new_journal({"kind": "diary", "entry_date": D3.isoformat(), "title": "지울 일지",
                 "content": {"memorable": "지울 것"}, "resume_tags": ["rule"]})
JX = r.json()["id"]
chk("지우기", c.delete(f"/api/journals/{JX}", headers=SH).status_code == 200)
s = SessionLocal()
chk("카테고리 줄도 없다", s.query(JournalResumeTag).filter_by(journal_id=JX).count() == 0)
s.close()

print("=== 6. 예전 수업일지 양식의 글 ===")
s = SessionLocal()
old = JournalEntry(user_id=STU_ID, kind="lesson", entry_date=D2, title="예전 양식",
                   subject="전기", content=json.dumps({
                       "objective": "옴의 법칙을 이해한다",
                       "problem": "회로에서 전류 값이 계산과 달랐습니다. 원인을 찾으려고 다시 측정했습니다.",
                       "solution": "선생님께 여쭤보고 저항 값을 다시 확인했습니다. 문제를 해결했습니다.",
                   }, ensure_ascii=False))
s.add(old)
s.commit()
OLD = old.id
s.close()
d = c.get(f"/api/journals/{OLD}", headers=SH).json()
chk("예전 칸 내용이 그대로 온다", d["content"].get("solution", "").startswith("선생님께"), str(d["content"]))
m = c.get("/api/cover-letters/materials", params={"topic": "problem_solving"}, headers=SH).json()
ids = [x["journal_id"] for x in m["topics"][0]["matches"]]
chk("예전 칸 글도 재료로 찾는다", OLD in ids, str(ids))

print("=== 7. 이 항목에 쓸 만한 내 기록 — 순서 ===")
# 카테고리를 안 단, 단서가 아주 많은 일지
r = new_journal({"kind": "diary", "entry_date": D1.isoformat(), "title": "팀 회의",
                 "content": {"memorable": "팀 회의에서 역할을 나눴습니다. 모둠 친구들과 함께 협력해서 발표를 준비했고 제가 맡은 책임을 다했습니다."}})
JT = r.json()["id"]
m = c.get("/api/cover-letters/materials", params={"topic": "teamwork"}, headers=SH).json()
t = m["topics"][0]
chk("직접 단 일지가 맨 위", t["matches"][0]["journal_id"] == J1 and t["matches"][0]["tagged"],
    str([(x["journal_id"], x["tagged"]) for x in t["matches"]]))
chk("단서 많은 일지도 뒤에 나온다", JT in [x["journal_id"] for x in t["matches"]])
chk("직접 단 수", t["tagged_count"] == 1, str(t.get("tagged_count")))
chk("카드에 제목·종류·날짜", t["matches"][0]["title"] == "조별 과제" and
    t["matches"][0]["kind_label"] == "학교생활일지" and t["matches"][0]["entry_date"], str(t["matches"][0]))
chk("아무 카테고리도 안 달린 평범한 일지는 안 나온다",
    J0 not in [x["journal_id"] for x in t["matches"]])

# 직업군: 같은 조건의 두 일지 중 직업군 단서가 있는 쪽이 위로
r1 = new_journal({"kind": "diary", "entry_date": D1.isoformat(), "title": "요리 실습",
                  "content": {"memorable": "새로운 조리법을 배우려고 혼자 스스로 연습했습니다. 요리 영상을 찾아보며 공부했습니다."}})
r2 = new_journal({"kind": "diary", "entry_date": D1.isoformat(), "title": "코딩 독학",
                  "content": {"memorable": "새로운 기술을 배우려고 혼자 스스로 연습했습니다. 파이썬 코딩 영상을 찾아보며 공부했습니다."}})
JC, JP = r1.json()["id"], r2.json()["id"]
m = c.get("/api/cover-letters/materials", params={"topic": "learning", "job": "it"}, headers=SH).json()
order = [x["journal_id"] for x in m["topics"][0]["matches"]]
chk("직업군 단서 있는 쪽이 위", order.index(JP) < order.index(JC), str(order))
chk("그래도 직접 단 것(J2)이 맨 위", order[0] == J2, str(order))
chk("직업군 이름을 돌려준다", m["job_label"] == "IT·개발·데이터", str(m.get("job_label")))
m2 = c.get("/api/cover-letters/materials", params={"topic": "learning", "job": "service"}, headers=SH).json()
order2 = [x["journal_id"] for x in m2["topics"][0]["matches"]]
chk("직업군을 바꾸면 순서도 바뀐다", order2.index(JC) < order2.index(JP), str(order2))
chk("남의 재료는 없다(로그인 사용자 기준)",
    c.get("/api/cover-letters/materials", params={"topic": "learning"}, headers=OH).status_code in (402, 403))

print("=== 8. 자소서에 직업군 저장 ===")
r = c.post("/api/cover-letters", json={"title": "취업 자소서", "content": {}, "job_category": "it"}, headers=SH)
chk("만들기", r.status_code == 200, r.text)
CL = r.json()["id"]
d = c.get(f"/api/cover-letters/{CL}", headers=SH).json()
chk("직업군 저장", d["job_category"] == "it" and d["job_label"] == "IT·개발·데이터", str(d))
r = c.put(f"/api/cover-letters/{CL}", json={"title": "취업 자소서", "content": {"teamwork": "본문"}}, headers=SH)
chk("직업군을 안 보내면 그대로", c.get(f"/api/cover-letters/{CL}", headers=SH).json()["job_category"] == "it")
r = c.put(f"/api/cover-letters/{CL}", json={"title": "t", "content": {}, "job_category": "없는직업"}, headers=SH)
chk("모르는 직업군 400", r.status_code == 400, r.text)
qa = {"apply_motive": {"questions": [{"id": 1, "group": "지원동기", "question": "계기는?", "basis": []}],
                       "answers": {"1": "코딩 동아리"}}, "etc": {"x": 1}}
r = c.put(f"/api/cover-letters/{CL}", json={"title": "t", "content": {}, "job_category": "design",
                                             "question_answers": qa}, headers=SH)
d = c.get(f"/api/cover-letters/{CL}", headers=SH).json()
chk("질문·답 저장", d["question_answers"]["apply_motive"]["answers"]["1"] == "코딩 동아리", str(d))
chk("모르는 칸은 버림", "etc" not in d["question_answers"])
chk("직업군 바꾸기", d["job_category"] == "design")
chk("목록에 직업군", c.get("/api/cover-letters", headers=SH).json()[0]["job_label"] == "디자인")
chk("남의 자소서 404", c.get(f"/api/cover-letters/{CL}", headers=OH).status_code in (402, 403, 404))

print("=== 9. 고른 기록으로 초안 — 직업군·카테고리가 AI 에 간다 ===")


def essay(body):
    if "검사자" in body:
        return {"safe": True, "issues": []}
    return {"draft": "for 문의 끝 값이 헷갈렸을 때 직접 실행해 보며 확인했습니다.",
            "facts_used": ["직접 실행"], "warnings": []}


requests.post = reply(essay)
PROMPTS.clear()
r = c.post("/api/cover-letters/generate", json={
    "question": "새로운 지식이나 기술을 배우기 위해 스스로 노력했던 경험",
    "journal_ids": [J2], "job_category": "it", "topic": "learning", "character_limit": 500}, headers=SH).json()
res = wait(r["job_id"])
chk("초안 나옴", res["status"] == "done" and res["result"]["draft"], str(res)[:200])
gen = next((p for p in PROMPTS if "보조 시스템입니다" in p and "희망 직업군" in p), "")
chk("직업군이 프롬프트에", '"IT·개발·데이터"' in gen, gen[-400:])
chk("카테고리가 프롬프트에", "새로운 지식이나 기술을 배우기 위해" in gen.split("[학생의 경험]")[-1])
chk("날조 금지 규칙", "만들지 마십시오" in gen)
chk("쓴 기록 목록", res["result"]["used_records"][0]["journal_id"] == J2, str(res["result"].get("used_records")))
r = c.post("/api/cover-letters/generate", json={"question": "q", "journal_ids": [J1], "job_category": "???"},
           headers=SH)
chk("모르는 직업군 400", r.status_code == 400)
r = c.post("/api/cover-letters/generate", json={"question": "q", "journal_ids": []}, headers=SH)
chk("경험도 답도 없으면 400", r.status_code == 400)

print("=== 10. 지원동기 질문 — 1~2학년 기록만 ===")
r = new_journal({"kind": "diary", "entry_date": D3.isoformat(), "title": "3학년 현장실습",
                 "content": {"memorable": "3학년 현장실습에서 회사 일을 해 봤습니다. 진로를 다시 생각했습니다."}})
J3 = r.json()["id"]


def questions(body):
    import re
    ids = [int(x) for x in re.findall(r"\[기록 (\d+)\]", body)]
    return {"questions": [
        {"group": "지원동기", "question": "코딩을 혼자 연습했다고 적었어요. 이 분야에 관심을 갖게 된 계기는 뭔가요?",
         "basis": [{"record_id": ids[0], "evidence": "혼자 연습"}, {"record_id": 99999, "evidence": "없는 기록"}]},
        {"group": "엉뚱한그룹", "question": "이 분야 회사에서 해 보고 싶은 일은 무엇인가요?", "basis": []},
    ], "notes": []}


requests.post = reply(questions)
PROMPTS.clear()
r = c.post("/api/cover-letters/motive-questions", json={"topic": "apply_motive", "job_category": "it"},
           headers=SH)
chk("맡겨짐", r.status_code == 200 and r.json()["status"] == "queued", r.text)
res = wait(r.json()["job_id"])
chk("질문이 나옴", res["status"] == "done" and len(res["result"]["questions"]) == 2, str(res)[:300])
q = res["result"]["questions"]
body = PROMPTS[0] if PROMPTS else ""
chk("1학년 기록이 들어감", f"[기록 {J1}]" in body)
chk("2학년 기록이 들어감", f"[기록 {J2}]" in body)
chk("3학년 기록은 안 들어감", f"[기록 {J3}]" not in body)
chk("직업군이 들어감", "IT·개발·데이터" in body)
chk("없는 기록을 댄 근거는 뺀다", [b["record_id"] for b in q[0]["basis"]] != [] and
    all(b["record_id"] != 99999 for b in q[0]["basis"]), str(q[0]["basis"]))
chk("근거에 제목·날짜", q[0]["basis"][0]["title"] and q[0]["basis"][0]["entry_date"], str(q[0]["basis"]))
chk("모르는 그룹은 지원동기로", q[1]["group"] == "지원동기", str(q[1]))
r = c.post("/api/cover-letters/motive-questions", json={"topic": "teamwork"}, headers=SH)
chk("경험 항목에서는 400", r.status_code == 400)


def goals(body):
    return {"questions": [
        {"group": "장기(5년 이후)", "question": "5년 뒤 어떤 개발자가 되고 싶나요?", "basis": []},
        {"group": "단기(1~3년)", "question": "입사 후 1~3년 동안 키우고 싶은 역량은요?", "basis": []},
    ]}


requests.post = reply(goals)
r = c.post("/api/cover-letters/motive-questions", json={"topic": "future_goal"}, headers=SH).json()
res = wait(r["job_id"])
gs = [x["group"] for x in res["result"]["questions"]]
chk("단기 → 장기 순", gs == ["단기(1~3년)", "장기(5년 이후)"], str(gs))

print("=== 11. 학생의 답으로 초안 ===")
requests.post = reply(essay)
PROMPTS.clear()
r = c.post("/api/cover-letters/generate", json={
    "question": "회사에 지원한 이유(지원동기)", "journal_ids": [J2], "job_category": "it",
    "answers": [{"question": "계기는?", "answer": "중학교 때 게임을 만들어 보고 싶었습니다."},
                {"question": "빈 답", "answer": ""}]}, headers=SH).json()
res = wait(r["job_id"])
chk("초안 나옴", res["status"] == "done", str(res)[:200])
gen = next((p for p in PROMPTS if "[학생의 경험]" in p and "보조 시스템입니다" in p), "")
chk("학생의 답이 경험으로 들어감", "게임을 만들어 보고 싶었습니다" in gen)
chk("빈 답은 빠짐", "빈 답" not in gen)
r = c.post("/api/cover-letters/generate", json={
    "question": "입사 후 목표", "journal_ids": [],
    "answers": [{"question": "5년 뒤?", "answer": "팀을 이끄는 개발자"}]}, headers=SH).json()
chk("답만으로도 맡길 수 있다", r.get("status") == "queued", str(r))
wait(r["job_id"])

ai_jobs.stop()
print(f"\n===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
