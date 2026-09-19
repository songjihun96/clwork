import sys, os, json, time
sys.path.insert(0,".")
OK=[]
def chk(n,c,e=""):
    OK.append(bool(c)); print(("  OK  " if c else "  FAIL")+f"  {n}"+(f"  {e}" if not c and e else ""))

print("=== 1. 키가 없을 때 ===")
os.environ.pop("ANTHROPIC_API_KEY", None)
import importlib
from app import llm
importlib.reload(llm)
chk("쓸 수 없다고 알림", llm.available() is False)
st=llm.status()
chk("상태에 키 없음", st["available"] is False and st["model"]=="", str(st))
r=llm.generate("안녕")
chk("예외 대신 결과", r.ok is False and r.error_type=="no_key", r.error_type)
chk("화면 문구 있음", "준비" in r.error, r.error)

print("=== 2. JSON 꺼내기 ===")
os.environ["ANTHROPIC_API_KEY"]="test-key"
importlib.reload(llm)
cases=[
 ('{"a":1}', {"a":1}, "그냥 JSON"),
 ('```json\n{"a":2}\n```', {"a":2}, "코드블록"),
 ('설명입니다.\n{"a":3}\n끝.', {"a":3}, "앞뒤 군더더기"),
 ('아무 말', None, "JSON 아님"),
 ('[1,2]', None, "배열은 거부"),
]
for text, want, label in cases:
    chk(label, llm._extract_json(text)==want, repr(llm._extract_json(text)))

print("=== 3. 너무 긴 글 ===")
r=llm.generate("가"*20000)
chk("보내지 않고 거부", r.ok is False and r.error_type=="too_long")

print("=== 4. 서버가 실패해도 안 터진다 ===")
import requests
real=requests.post
class FakeRes:
    def __init__(self, code=200, body=None, headers=None):
        self.status_code=code; self._b=body or {}; self.headers=headers or {}
    def json(self): return self._b
def make(code=200, body=None, exc=None):
    def f(*a, **k):
        if exc: raise exc
        return FakeRes(code, body)
    return f

requests.post = make(exc=requests.Timeout())
r=llm.generate("x"); chk("타임아웃", r.ok is False and r.error_type=="timeout", r.error_type)
chk("친절한 안내", "다시" in r.error, r.error)

requests.post = make(code=401)
r=llm.generate("x"); chk("인증 실패", r.ok is False and r.error_type=="http_401")
chk("내부 사정 숨김", "401" not in r.error, r.error)

requests.post = make(code=529)
r=llm.generate("x"); chk("서버 과부하", r.ok is False and r.error_type=="http_529")

requests.post = make(exc=ConnectionError("no route"))
r=llm.generate("x"); chk("연결 실패", r.ok is False)
chk("에러 내용 안 새어나감", "no route" not in r.error, r.error)

requests.post = make(body={"content":[]})
r=llm.generate("x"); chk("빈 응답", r.ok is False and r.error_type=="empty")

print("=== 5. 정상 흐름 ===")
requests.post = make(body={"content":[{"type":"text","text":'{"draft":"안녕하세요"}'}],
                           "usage":{"input_tokens":10,"output_tokens":5}})
r=llm.generate_json("x")
chk("JSON 받음", r.ok and r.data=={"draft":"안녕하세요"}, str(r.data))
chk("토큰 기록", r.meta.get("in_tokens")==10, str(r.meta))

print("=== 6. 형식이 틀리면 한 번만 더 ===")
calls=[]
def bad(*a, **k):
    calls.append(1)
    return FakeRes(200, {"content":[{"type":"text","text":"JSON 아님"}]})
requests.post = bad
r=llm.generate_json("x", retry=1)
chk("실패로 끝남", r.ok is False and r.error_type=="bad_json")
chk("두 번만 부름", len(calls)==2, f"{len(calls)}번")

print("=== 6-1. max_tokens에 걸려 끊기면 한도를 늘려 다시 ===")
seen_tokens = []
def truncated_then_ok(*a, **k):
    seen_tokens.append(k["json"]["max_tokens"])
    if len(seen_tokens) == 1:
        # 실제로 있었던 증상: JSON을 다 쓰기 전에 max_tokens에 걸려 끊김
        return FakeRes(200, {"content": [{"type": "text", "text": '{"a": "안 끝난'}],
                             "stop_reason": "max_tokens"})
    return FakeRes(200, {"content": [{"type": "text", "text": '{"a":"완성됨"}'}],
                         "stop_reason": "end_turn"})
requests.post = truncated_then_ok
r = llm.generate_json("x", retry=1, max_tokens=100)
chk("두 번째 시도에서 성공", r.ok and r.data == {"a": "완성됨"}, str(r.data))
chk("두 번째 호출은 한도를 두 배로 늘려 보냄", seen_tokens == [100, 200], str(seen_tokens))

seen_tokens = []
def truncated_forever(*a, **k):
    seen_tokens.append(k["json"]["max_tokens"])
    return FakeRes(200, {"content": [{"type": "text", "text": '{"a": "안 끝난'}],
                         "stop_reason": "max_tokens"})
requests.post = truncated_forever
r = llm.generate_json("x", retry=1, max_tokens=3900)
chk("한도 확대도 8000을 넘지 않음", seen_tokens == [3900, 7800], str(seen_tokens))
chk("계속 끊기면 결국 실패로 끝남(무한 재시도 안 함)", r.ok is False and r.error_type == "bad_json")

print("=== 6-2. 더 빠른 모델 지정 ===")
seen_models = []
def record_model(*a, **k):
    seen_models.append(k["json"]["model"])
    return FakeRes(200, {"content": [{"type": "text", "text": '{"a":1}'}]})
requests.post = record_model
llm.generate_json("x", model="claude-haiku-4-5-20251001")
chk("model을 넘기면 그 모델로 부름", seen_models == ["claude-haiku-4-5-20251001"], str(seen_models))
seen_models = []
llm.generate_json("x")
chk("안 넘기면 기본 모델", seen_models == [llm.MODEL], str(seen_models))

print("=== 6-3. 여러 계정 키 — 돌아가며 사용 ===")
os.environ["ANTHROPIC_API_KEYS"] = "key-a,key-b,key-c"
importlib.reload(llm)
chk("키 세 개가 모두 등록됨", llm.API_KEYS == ["key-a", "key-b", "key-c"], str(llm.API_KEYS))
chk("동시 처리 기본값도 키 개수만큼 늘어남(키당 2)", llm.MAX_CONCURRENT == 6, llm.MAX_CONCURRENT)

seen_keys = []
def record_key(url, headers=None, json=None, timeout=None):
    seen_keys.append(headers["x-api-key"])
    return FakeRes(200, {"content": [{"type": "text", "text": "ok"}]})
requests.post = record_key
for _ in range(6):
    llm.generate("x")
chk("키를 돌아가며 골고루 사용", seen_keys == ["key-a", "key-b", "key-c"] * 2, str(seen_keys))

print("=== 6-4. 요청 제한(429) — 다른 키로 재시도 ===")
calls = []
state = {"blocked": None}
def rate_limited_then_ok(url, headers=None, json=None, timeout=None):
    key = headers["x-api-key"]
    calls.append(key)
    if state["blocked"] is None:
        state["blocked"] = key
    if key == state["blocked"]:
        return FakeRes(429, {}, headers={"retry-after": "0"})
    return FakeRes(200, {"content": [{"type": "text", "text": "ok"}]})
requests.post = rate_limited_then_ok
r = llm.generate("x")
chk("먼저 고른 키가 막히면 다른 키로 넘어가 성공", r.ok and len(calls) >= 2 and calls[0] != calls[1], str(calls))

print("=== 6-5. 모든 키가 막히면 결국 실패로 끝남(무한 재시도 안 함) ===")
calls = []
def always_rate_limited(url, headers=None, json=None, timeout=None):
    calls.append(headers["x-api-key"])
    return FakeRes(429, {}, headers={"retry-after": "0"})
requests.post = always_rate_limited
r = llm.generate("x")
chk("전부 막히면 실패로 끝남", r.ok is False and r.error_type == "http_429", r.error_type)
chk("키 개수(3번)만큼만 시도하고 멈춤", len(calls) == 3, str(calls))

os.environ.pop("ANTHROPIC_API_KEYS", None)
importlib.reload(llm)
chk("키 설정을 빼면 다시 단일 키로 돌아감", llm.API_KEYS == ["test-key"], str(llm.API_KEYS))

print("=== 7. 동시 실행 제한 ===")
requests.post = real
import threading
llm.MAX_CONCURRENT=1
llm._gate = threading.Semaphore(1)
slow_done=[]
def slow(*a, **k):
    time.sleep(0.4); slow_done.append(1)
    return FakeRes(200, {"content":[{"type":"text","text":"ok"}]})
requests.post = slow
t=threading.Thread(target=lambda: llm.generate("a")); t.start()
time.sleep(0.05)
s=time.time(); llm.generate("b"); waited=time.time()-s
t.join()
chk("뒤 요청이 기다림", waited>0.2, f"{waited:.2f}초")
requests.post = real
print(); print(f"===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
