import os,sys,json
os.environ["DATABASE_URL"]="sqlite:////tmp/sv.db"; os.environ["SECRET_KEY"]="x"

# 앞선 검사의 자료가 남아 있으면 결과가 달라져,
# 멀쩡한 코드가 실패한 것처럼 보인다. 먼저 지운다.
if os.path.exists("/tmp/sv.db"):
    os.remove("/tmp/sv.db")
os.environ["ANTHROPIC_API_KEY"]="test-key"
sys.path.insert(0,".")
import importlib
from app import llm; importlib.reload(llm)
from app import ai_service, privacy
importlib.reload(ai_service)
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
def reply(payload):
    def f(url, headers=None, json=None, timeout=None):
        sent.append(json["messages"][0]["content"])
        import json as J
        return Res({"content":[{"type":"text","text":J.dumps(payload,ensure_ascii=False)}],
                    "usage":{"input_tokens":1,"output_tokens":1}})
    return f

print("=== 1. 개인정보가 안 나간다 ===")
requests.post = reply({
 "cleaned_content":"[[SCHOOL_1]]에서 [[PERSON_1]]이 실습했습니다.",
 "inappropriate":[{"text":"개빡","category":"PROFANITY","severity":2,
                   "replacement":"답답","reason":"비속어"}],
 "experience":{"situation":"실습","problem":"치수","goal":"","action":"속도를 줄임",
               "result":"맞음","emotion":"답답","lesson":"확인이 중요"},
 "skills":[{"name":"문제 해결","evidence":"속도를 줄여 해결","confidence":0.8},
           {"name":"리더십","evidence":"","confidence":0.2}],
 "keywords":["실습","치수"]})
# 전화번호는 가림막이 자리표로 바꾸므로 보내도 된다. 검사에도 안 걸린다.
sent.clear()
content={"memorable":"근명고등학교 홍길동입니다. 010-9999-8888. 실습에서 치수가 안 맞아 개빡쳤다."}
r=ai_service.analyze_journal(E(), content, U())
chk("전화번호는 가려서 보냄", r["ok"] and "010-9999-8888" not in sent[0], sent[0][:80] if sent else "")

# 가림막이 놓친 것이 있으면 보내지 않는다. 그 상황을 만들어 본다.
_real_mask = privacy.Pseudonymizer.mask
privacy.Pseudonymizer.mask = lambda self, t: t or ""   # 아무것도 안 가리게
r=ai_service.analyze_journal(E(), content, U())
privacy.Pseudonymizer.mask = _real_mask
chk("가림막이 놓치면 안 보냄", r["ok"] is False and r["error_type"]=="leak", str(r)[:80])

content={"memorable":"근명고등학교 홍길동입니다. 선반 실습에서 치수가 안 맞아 개빡쳤습니다. 이송 속도를 줄이니 맞았습니다."}
sent.clear()
r=ai_service.analyze_journal(E(), content, U())
chk("분석 성공", r["ok"], str(r)[:100])
prompt=sent[0]
chk("이름 안 나감", "홍길동" not in prompt, "이름이 그대로 전송됨")
chk("학교 안 나감", "근명고등학교" not in prompt, "학교가 그대로 전송됨")
chk("자리표로 나감", "[[PERSON_1]]" in prompt or "[[SCHOOL_1]]" in prompt)

print("=== 2. 결과는 원래 이름으로 ===")
chk("되돌려짐", "근명고등학교" in r["cleaned_content"] and "홍길동" in r["cleaned_content"],
    r["cleaned_content"])
chk("원문 함께 보관", "개빡쳤습니다" in r["original_content"])

print("=== 3. 근거 약한 역량은 버린다 ===")
names=[s["name"] for s in r["skills"]]
chk("문제 해결은 남음", "문제 해결" in names, str(names))
chk("리더십은 버림", "리더십" not in names, str(names))

print("=== 4. 짧은 글 ===")
r2=ai_service.analyze_journal(E(), {"memorable":"했다"}, U())
chk("짧으면 안 보냄", r2["ok"] is False and r2["error_type"]=="too_short", str(r2))

print("=== 5. 어울림 점수 ===")
requests.post = reply({"score":88,"reason":"맞음","strengths":["행동이 뚜렷"],
                       "weaknesses":[],"recommended":False})
m=ai_service.match_experience("문제를 해결한 경험", {"action":"속도를 줄임"}, U())
chk("점수 받음", m["ok"] and m["score"]==88, str(m))
chk("점수로 판단", m["recommended"] is True, "AI 가 false 라 해도 점수를 믿어야 함")

print("=== 6. 자소서 초안 + 검증 ===")
calls=[]
def essay_then_verify(url, headers=None, json=None, timeout=None):
    body=json["messages"][0]["content"]; calls.append(body)
    import json as J
    if "검사자" in body:
        return Res({"content":[{"type":"text","text":J.dumps({"safe":True,"issues":[]})}]})
    return Res({"content":[{"type":"text","text":J.dumps(
        {"draft":"[[PERSON_1]]은 실습에서 치수를 맞췄습니다.",
         "facts_used":["속도를 줄임"],"warnings":[]},ensure_ascii=False)}]})
requests.post = essay_then_verify
g=ai_service.generate_essay("문제 해결 경험", [{"action":"속도를 줄임"}], U(), limit=500)
chk("초안 나옴", g["ok"] and "홍길동" in g["draft"], str(g)[:120])
chk("검증까지 함", g["verified"] and g["safe"] is True, str(g.get("safe")))
chk("두 번 부름", len(calls)==2, f"{len(calls)}번")
chk("글자 수 셈", g["character_count"]==len(g["draft"]))

print("=== 7. 지어낸 게 있으면 다시 쓴다 ===")
seq=[]
def with_issue(url, headers=None, json=None, timeout=None):
    body=json["messages"][0]["content"]; seq.append(body)
    import json as J
    if "검사자" in body:
        # 첫 검증은 문제, 두 번째는 통과
        n=sum(1 for s in seq if "검사자" in s)
        if n==1:
            return Res({"content":[{"type":"text","text":J.dumps(
                {"safe":False,"issues":[{"text":"팀장으로서","reason":"원문에 없음"}]},
                ensure_ascii=False)}]})
        return Res({"content":[{"type":"text","text":J.dumps({"safe":True,"issues":[]})}]})
    return Res({"content":[{"type":"text","text":J.dumps(
        {"draft":"실습에서 치수를 맞췄습니다.","facts_used":[],"warnings":[]},
        ensure_ascii=False)}]})
requests.post = with_issue
g=ai_service.generate_essay("문제 해결", [{"action":"속도를 줄임"}], U(), limit=500)
chk("다시 쓰고 재검증", len(seq)==4, f"{len(seq)}번 부름")
chk("최종 안전", g["safe"] is True, str(g.get("issues")))

print("=== 8. 글자 수 넘으면 문장 단위로 ===")
long_draft="가나다라마바사. "*100
def long_reply(url, headers=None, json=None, timeout=None):
    import json as J
    body=json["messages"][0]["content"]
    if "검사자" in body:
        return Res({"content":[{"type":"text","text":J.dumps({"safe":True,"issues":[]})}]})
    return Res({"content":[{"type":"text","text":J.dumps(
        {"draft":long_draft,"facts_used":[],"warnings":[]},ensure_ascii=False)}]})
requests.post = long_reply
g=ai_service.generate_essay("문항", [{"action":"x"}], U(), limit=100)
chk("한도 안", g["character_count"]<=100, str(g["character_count"]))
chk("문장 중간에서 안 끊김", g["draft"].rstrip().endswith("."), repr(g["draft"][-20:]))

print("=== 9. AI 가 죽어도 ===")
requests.post = lambda *a, **k: (_ for _ in ()).throw(requests.Timeout())
r=ai_service.analyze_journal(E(), {"memorable":"선반 실습에서 치수를 맞췄습니다. 속도를 줄였습니다."}, U())
chk("예외 안 던짐", r["ok"] is False and r["error_type"]=="timeout", str(r))
print(); print(f"===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
