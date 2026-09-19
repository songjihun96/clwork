"""지시서 [44] AI 테스트 10종.

AI 응답을 흉내 내어, 우리 코드가 그 응답을 어떻게 다루는지 본다.
실제 AI 품질이 아니라 "AI 가 이상한 답을 줬을 때 우리가 막는가" 를 본다.
"""
import os,sys,json
os.environ["DATABASE_URL"]="sqlite:////tmp/at.db"; os.environ["SECRET_KEY"]="x"

# 앞선 검사의 자료가 남아 있으면 결과가 달라져,
# 멀쩡한 코드가 실패한 것처럼 보인다. 먼저 지운다.
if os.path.exists("/tmp/at.db"):
    os.remove("/tmp/at.db")
os.environ["ANTHROPIC_API_KEY"]="test-key"
sys.path.insert(0,".")
import importlib
from app import llm; importlib.reload(llm)
from app import ai_service, privacy; importlib.reload(ai_service)
import requests
OK=[]
def chk(n,c,e=""):
    OK.append(bool(c)); print(("  OK  " if c else "  FAIL")+f"  {n}"+(f"  {e}" if not c and e else ""))

class U:
    name="홍길동"; school_name="근명고등학교"; email="hong@t.kr"
    class_name="2학년 3반"; department="기계과"
class E: kind="diary"

sent=[]
class Res:
    def __init__(self,b): self.status_code=200; self._b=b
    def json(self): return self._b
def reply(fn):
    def f(url, headers=None, json=None, timeout=None):
        import json as J
        body=json["messages"][0]["content"]; sent.append(body)
        return Res({"content":[{"type":"text","text":J.dumps(fn(body),ensure_ascii=False)}],
                    "usage":{"input_tokens":1,"output_tokens":1}})
    return f
def analysis(**kw):
    base={"cleaned_content":"정제된 글입니다.","inappropriate":[],
          "experience":{"situation":"","problem":"","goal":"","action":"",
                        "result":"","emotion":"","lesson":""},
          "skills":[],"keywords":[]}
    base.update(kw); return base

print("TEST 1 — 정상적인 일지")
requests.post = reply(lambda b: analysis(
  cleaned_content="선반 실습에서 치수가 맞지 않아 세 번 다시 했습니다.",
  experience={"situation":"선반 실습","problem":"치수 초과","goal":"치수 맞추기",
              "action":"이송 속도를 줄임","result":"치수가 맞음","emotion":"답답",
              "lesson":"원인을 찾는 것이 중요"},
  skills=[{"name":"문제 해결","evidence":"속도를 줄여 해결","confidence":0.9}]))
r=ai_service.analyze_journal(E(), {"memorable":"선반 실습에서 치수가 0.2mm 커서 세 번 다시 했습니다. 이송 속도를 줄이니 맞았습니다."}, U())
chk("분석됨", r["ok"] and r["experience"]["action"], str(r)[:80])

print("TEST 2 — 욕설이 있는 일지")
requests.post = reply(lambda b: analysis(
  cleaned_content="실습이 계획대로 되지 않아 상당히 답답했습니다.",
  inappropriate=[{"text":"개빡쳤","category":"PROFANITY","severity":2,
                  "replacement":"답답했","reason":"비속어"}],
  experience={"situation":"실습","problem":"","goal":"","action":"",
              "result":"","emotion":"답답","lesson":""}))
r=ai_service.analyze_journal(E(), {"memorable":"오늘 실습이 개판이어서 진짜 개빡쳤다. 그래도 끝까지 했다."}, U())
chk("욕설 잡음", r["inappropriate"] and r["inappropriate"][0]["severity"]==2)
chk("감정은 남김", "답답" in r["cleaned_content"], r["cleaned_content"])
chk("원문 보존", "개빡쳤다" in r["original_content"])

print("TEST 3 — 남을 비난하는 내용")
requests.post = reply(lambda b: analysis(
  cleaned_content="팀원의 업무 진행에 어려움이 있어 제가 추가로 처리했습니다.",
  inappropriate=[{"text":"무능","category":"PERSONAL_ATTACK","severity":2,
                  "replacement":"업무 진행에 어려움","reason":"타인 비난"}]))
r=ai_service.analyze_journal(E(), {"memorable":"팀원이 너무 무능해서 최악이었다. 내가 다 했다."}, U())
chk("비난 잡음", r["inappropriate"][0]["category"]=="PERSONAL_ATTACK")
chk("객관적 표현으로", "무능" not in r["cleaned_content"], r["cleaned_content"])

print("TEST 4 — 매우 짧은 일지")
sent.clear()
r=ai_service.analyze_journal(E(), {"memorable":"했다"}, U())
chk("AI 안 부름", r["ok"] is False and len(sent)==0, f"{len(sent)}번 부름")
chk("안내 있음", "짧아" in r["error"], r["error"])

print("TEST 5 — 매우 긴 일지")
sent.clear()
r=ai_service.analyze_journal(E(), {"memorable":"실습을 했습니다. "*2000}, U())
chk("보내지 않음", r["ok"] is False and r.get("error_type")=="too_long", str(r)[:80])
chk("나누라고 안내", "나누어" in r["error"], r["error"])

print("TEST 6 — 경험이 거의 없는 일지")
requests.post = reply(lambda b: analysis(cleaned_content="오늘은 평소와 같았습니다."))
r=ai_service.analyze_journal(E(), {"memorable":"오늘은 그냥 그랬다. 별일 없었다. 집에 와서 잤다."}, U())
chk("빈 칸은 빈 채로", all(not v for v in r["experience"].values()), str(r["experience"]))
chk("없는 역량 안 만듦", r["skills"]==[], str(r["skills"]))

print("TEST 7 — 성과가 명확한 일지")
requests.post = reply(lambda b: analysis(
  experience={"situation":"기능경기대회","problem":"","goal":"입상",
              "action":"매일 두 시간 연습","result":"동상 수상","emotion":"뿌듯",
              "lesson":"꾸준함이 중요"},
  skills=[{"name":"성실성","evidence":"매일 두 시간 연습","confidence":0.9}]))
r=ai_service.analyze_journal(E(), {"memorable":"기능경기대회에서 동상을 받았다. 매일 두 시간씩 연습한 덕분이다."}, U())
chk("성과 담김", r["experience"]["result"]=="동상 수상")
chk("역량에 근거", r["skills"][0]["evidence"]=="매일 두 시간 연습")

print("TEST 8 — 성과가 없는 일지")
requests.post = reply(lambda b: analysis(
  experience={"situation":"자격증 준비","problem":"시간 부족","goal":"합격",
              "action":"매일 공부","result":"","emotion":"아쉬움","lesson":""}))
r=ai_service.analyze_journal(E(), {"memorable":"자격증 시험을 준비했지만 시간이 부족했다. 계속 공부하고 있다."}, U())
chk("없는 성과 안 만듦", r["experience"]["result"]=="", repr(r["experience"]["result"]))

print("TEST 9 — 숫자가 있는 일지")
def keep_number(b):
    if "검사자" in b:
        return {"safe":True,"issues":[]}
    return {"draft":"치수가 0.2mm 초과되어 세 번 다시 작업했습니다.",
            "facts_used":["0.2mm 초과","세 번"],"warnings":[]}
requests.post = reply(keep_number)
g=ai_service.generate_essay("문제 해결",
   [{"experience":{"problem":"치수 0.2mm 초과","action":"세 번 다시 함"}}], U(), limit=500)
chk("숫자 그대로", "0.2mm" in g["draft"] and "세 번" in g["draft"], g["draft"])

print("TEST 10 — AI 가 사실을 지어내려 할 때")
seq=[]
def hallucinate(b):
    seq.append(b)
    if "검사자" in b:
        n=sum(1 for x in seq if "검사자" in x)
        if n==1:
            return {"safe":False,"issues":[
              {"text":"팀장으로서 팀을 이끌어","reason":"원문에 팀장이라는 말이 없음"},
              {"text":"20% 향상","reason":"원문에 없는 숫자"}]}
        return {"safe":True,"issues":[]}
    n=sum(1 for x in seq if "검사자" not in x)
    if n==1:
        return {"draft":"팀장으로서 팀을 이끌어 20% 향상을 달성했습니다.",
                "facts_used":[],"warnings":[]}
    return {"draft":"팀원들과 역할을 나누어 과제를 진행했습니다.",
            "facts_used":["역할을 나눔"],"warnings":[]}
requests.post = reply(hallucinate)
g=ai_service.generate_essay("팀 활동",
   [{"experience":{"action":"팀원들과 역할을 나눠 과제를 함"}}], U(), limit=500)
chk("지어낸 것 걸림", len(seq)==4, f"{len(seq)}번 부름")
chk("다시 써서 통과", g["safe"] is True and "팀장" not in g["draft"], g["draft"])
chk("숫자도 사라짐", "20%" not in g["draft"], g["draft"])

print()
print("추가 — AI 가 safe=true 라 해놓고 문제를 적어올 때")
requests.post = reply(lambda b: {"safe":True,
  "issues":[{"text":"팀장","reason":"원문에 없음"}]})
v=ai_service.verify_essay("팀장으로서 했습니다.", [{"experience":{}}], U())
chk("문제가 있으면 안전하지 않다고 봄", v["safe"] is False, str(v))

print("추가 — 개인정보가 밖으로 안 나간다")
sent.clear()
requests.post = reply(lambda b: analysis())
ai_service.analyze_journal(E(), {"memorable":"근명고등학교 홍길동입니다. 실습에서 치수를 맞췄습니다. 연락처는 010-1234-5678 입니다."}, U())
body=sent[0]
for word in ("홍길동","근명고등학교","010-1234-5678","hong@t.kr"):
    chk(f"{word} 안 나감", word not in body)
print(); print(f"===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
