"""ClawOps 방식(VoiceML 웹훅)으로 순차분배가 도는지 확인한다.

실제 070 회선을 쓰지 않는다. ClawOps 가 보낼 웹훅을 그대로 흉내 내고,
우리가 돌려주는 XML 이 맞는지 본다. 여기서 통과했다고 실제 통화가 된다는
뜻은 아니다. 그건 회선을 붙이고 진짜로 걸어봐야 안다.

확인하는 것
  - 서명이 틀리면 거절하는가 (이 문은 인터넷에 열려 있다)
  - 전화가 오면 1번 상담원에게 <Dial> 하는가
  - 안 받으면(no-answer) 2번, 3번으로 넘어가는가
  - 아무도 없으면 대기열 안내를 하는가
  - 받으면(completed) 통화가 정리되는가
  - 사업자가 시간을 세는 방식이면 우리 ticker 가 끼어들지 않는가
"""
import base64
import hashlib
import hmac
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:////tmp/vm.db"
os.environ["SECRET_KEY"] = "x"
os.environ["PHONE_PROVIDER"] = "clawops"
os.environ["PHONE_API_KEY"] = "test-key"
os.environ["PHONE_ACCOUNT_ID"] = "acc_test"
os.environ["PHONE_WEBHOOK_SECRET"] = "test-signing-secret"
os.environ["PHONE_DID_NUMBER"] = "07000000000"      # 실제 번호를 코드에 두지 않는다
os.environ["PHONE_VOICE_BASE"] = "https://cs.example.kr"

if os.path.exists("/tmp/vm.db"):
    os.remove("/tmp/vm.db")
sys.path.insert(0, ".")

from fastapi.testclient import TestClient          # noqa: E402
from app.main import app                           # noqa: E402
from app.database import SessionLocal              # noqa: E402
from app.models import CsCallLog, CsCallSession, Role, Setting, User  # noqa: E402
from app.auth import hash_password                 # noqa: E402
from app.callcenter import engine                  # noqa: E402

SECRET = os.environ["PHONE_WEBHOOK_SECRET"]
BASE = os.environ["PHONE_VOICE_BASE"]

OK = []


def chk(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  OK  " if cond else "  FAIL") + f"  {name}" + (f"  {extra}" if not cond and extra else ""))


def sign(path: str, params: dict) -> str:
    """ClawOps 와 같은 방식으로 서명을 만든다: URL + 정렬된 key+value, HMAC-SHA256, base64."""
    data = BASE + path + "".join(f"{k}{v}" for k, v in sorted(params.items()))
    return base64.b64encode(
        hmac.new(SECRET.encode(), data.encode(), hashlib.sha256).digest()
    ).decode()


def post(c, path, params):
    return c.post(path, data=params, headers={"X-Signature": sign(path, params)})


# ── 상담원 3명 ────────────────────────────────────────────────
db = SessionLocal()
for i, (name, email, phone) in enumerate([
    ("김상담", "v1@t.kr", "01011110001"),
    ("이상담", "v2@t.kr", "01011110002"),
    ("박상담", "v3@t.kr", "01011110003"),
]):
    u = User(email=email, name=name, role=Role.cs,
             password_hash=hash_password("pw12345!"), is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    p = engine.ensure_profile(db, u)
    p.ring_order = (i + 1) * 10
    p.availability_status = "AVAILABLE"
    p.phone_number = phone
db.add(Setting(key=engine.SETTING_RING_TIMEOUT, value="20"))
db.commit()
ids = {u.email: u.id for u in db.query(User).all()}
db.close()

c = TestClient(app)
CALL = "clawops-call-001"

print("=== 0. 설정 ===")
db = SessionLocal()
caps = __import__("app.phone", fromlist=["x"]).get_provider().capabilities()
chk("Provider 는 clawops", __import__("app.phone", fromlist=["x"]).get_provider().name == "clawops")
chk("사업자가 링 시간을 센다고 알림", caps.get("external_ring_timeout") is True, str(caps))
chk("브라우저 음성은 아직 아니라고 알림", caps.get("webrtc_audio") is False)
db.close()

print("=== 1. 서명 ===")
params = {"CallId": CALL, "From": "01099998888", "To": "07000000000",
          "CallStatus": "ringing", "Direction": "inbound"}
r = c.post("/api/cs/phone/voice/incoming", data=params,
           headers={"X-Signature": "aaaa-wrong"})
chk("틀린 서명은 401", r.status_code == 401, str(r.status_code))
r = c.post("/api/cs/phone/voice/incoming", data=params)
chk("서명 없으면 401", r.status_code == 401, str(r.status_code))

print("=== 2. 전화가 오면 1번 상담원에게 ===")
r = post(c, "/api/cs/phone/voice/incoming", params)
chk("200 응답", r.status_code == 200, str(r.status_code))
chk("XML 로 답한다", "application/xml" in r.headers.get("content-type", ""),
    r.headers.get("content-type", ""))
chk("Dial 로 연결 지시", "<Dial" in r.text, r.text[:200])
chk("링 시간 20초", 'timeout="20"' in r.text, r.text[:200])
chk("1번 상담원 번호", "01011110001" in r.text, r.text[:200])
chk("action 콜백 지정", "/api/cs/phone/voice/after-dial" in r.text, r.text[:200])

db = SessionLocal()
call = db.query(CsCallLog).filter(CsCallLog.external_call_id == CALL).first()
sess = db.query(CsCallSession).filter(CsCallSession.call_log_id == call.id).first()
chk("통화 기록 생성", call is not None and call.status == "RINGING", call.status if call else "-")
chk("발신번호 정규화 저장", call.phone_number == "01099998888", call.phone_number)
chk("사업자가 세므로 마감시각 비움", sess.ring_deadline is None, str(sess.ring_deadline))
# ticker 가 끼어들면 안 된다
moved = engine.tick_timeouts(db)
db.refresh(sess)
chk("ticker 가 안 건드림", moved == 0 and sess.current_counselor_id == ids["v1@t.kr"],
    f"moved={moved} cur={sess.current_counselor_id}")
db.close()

print("=== 3. 안 받으면 다음 상담원 ===")
after = {"CallId": CALL, "From": "01099998888", "To": "07000000000",
         "DialCallStatus": "no-answer"}
r = post(c, "/api/cs/phone/voice/after-dial", after)
chk("2번 상담원에게", "01011110002" in r.text, r.text[:200])
r = post(c, "/api/cs/phone/voice/after-dial", after)
chk("3번 상담원에게", "01011110003" in r.text, r.text[:200])

print("=== 4. 아무도 없으면 대기열 ===")
r = post(c, "/api/cs/phone/voice/after-dial", after)
chk("대기 안내", "기다려" in r.text, r.text[:250])
chk("잠시 멈춤", "<Pause" in r.text, r.text[:250])
chk("다시 물어보러 옴", "/api/cs/phone/voice/queue" in r.text, r.text[:250])

db = SessionLocal()
call = db.query(CsCallLog).filter(CsCallLog.external_call_id == CALL).first()
chk("통화 상태 QUEUED", call.status == "QUEUED", call.status)
db.close()

print("=== 5. 대기 중 상담원이 돌아오면 다시 연결 ===")
db = SessionLocal()
engine.set_availability(db, db.get(User, ids["v2@t.kr"]), "AVAILABLE")
db.close()
r = post(c, "/api/cs/phone/voice/queue", {"CallId": CALL, "round": "1"})
chk("다시 상담원 호출", "<Dial" in r.text, r.text[:250])

print("=== 6. 받으면 통화가 정리된다 ===")
done = {"CallId": CALL, "From": "01099998888", "To": "07000000000",
        "DialCallStatus": "completed"}
r = post(c, "/api/cs/phone/voice/after-dial", done)
chk("끊기 지시", "<Hangup/>" in r.text, r.text[:200])

db = SessionLocal()
call = db.query(CsCallLog).filter(CsCallLog.external_call_id == CALL).first()
sess = db.query(CsCallSession).filter(CsCallSession.call_log_id == call.id).first()
chk("통화 종료 기록", call.status in ("COMPLETED", "MISSED"), call.status)
chk("세션 종료", sess.state == "ENDED", sess.state)
db.close()

print("=== 7. 연락처 없는 상담원은 건너뛴다 ===")
db = SessionLocal()
# 1번의 번호를 지운다. 그 사람에서 전화가 죽으면 안 된다.
p1 = engine.ensure_profile(db, db.get(User, ids["v1@t.kr"]))
p1.phone_number = ""
for e in ("v1@t.kr", "v2@t.kr", "v3@t.kr"):
    engine.set_availability(db, db.get(User, ids[e]), "AVAILABLE")
db.commit()
db.close()

CALL2 = "clawops-call-002"
r = post(c, "/api/cs/phone/voice/incoming",
         {"CallId": CALL2, "From": "01077776666", "To": "07000000000",
          "CallStatus": "ringing", "Direction": "inbound"})
chk("번호 없는 1번을 건너뛰고 2번에게", "01011110002" in r.text, r.text[:250])

print("=== 8. 모르는 통화는 조용히 끊는다 ===")
r = post(c, "/api/cs/phone/voice/after-dial",
         {"CallId": "does-not-exist", "DialCallStatus": "no-answer"})
chk("Hangup", "<Hangup/>" in r.text, r.text[:150])

print("=== 9. 브라우저 전화기(WebRTC) ===")
# 사업자 API 를 부르지 않고, 토큰 발급 부분만 가짜로 갈아 끼운다.
# 실제 SIP 등록과 음성은 여기서 확인할 수 없다. 그건 회선을 붙이고
# 진짜로 걸어봐야 안다.
import app.phone as _phone  # noqa: E402
_prov = _phone.get_provider()
_issued = {"n": 0}


def _fake_issue():
    _issued["n"] += 1
    import time as _t
    return {
        "sip_username": f"ephem_{_issued['n']:04d}",
        "sip_password": "pw",
        "ws_url": "wss://sip.example.com",
        "realm": "acct.sip.example.com",
        "ice_servers": [{"urls": "stun:stun.example.com"}],
        "sip_uri": f"ephem_{_issued['n']:04d}@acct.sip.example.com",
        "expires_at": int(_t.time()) + 360,
    }


_prov.sip_credential_id = "cred_test"           # 부가서비스가 켜진 상태로 가정
_prov.issue_webrtc_token = lambda: {**_fake_issue(),
                                    "sip_uri": "sip:" + _fake_issue()["sip_username"]
                                               + "@acct.sip.example.com"}

# 상담원으로 로그인한다. 새 기기는 승인 대기가 되므로 관리자가 승인한 셈 친다.
first = c.post("/api/cs/login", json={"email": "v1@t.kr", "password": "pw12345!"}).json()
device_token = first.get("device_token", "")
db = SessionLocal()
from app.models import CsDevice  # noqa: E402
dev = db.query(CsDevice).first()
if dev is not None:
    dev.status = "approved"
    db.commit()
db.close()
tok = c.post("/api/cs/login", json={"email": "v1@t.kr", "password": "pw12345!"},
             headers={"X-CS-Device": device_token}).json()
H1 = {"Authorization": f"Bearer {tok['token']}", "X-CS-Device": device_token}
chk("상담원 로그인", tok.get("ok") is True, str(tok)[:120])

r = c.post("/api/cs/phone/webrtc-token", headers=H1)
chk("토큰 발급 200", r.status_code == 200, r.text[:200])
body = r.json()
chk("접속 주소를 준다", body.get("ws_url") == "wss://sip.example.com", str(body)[:160])
chk("API 키는 안 내려간다", "api_key" not in body and "token" not in body, str(body.keys()))

db = SessionLocal()
p1 = engine.ensure_profile(db, db.get(User, ids["v1@t.kr"]))
chk("서버가 SIP 주소를 기록", p1.sip_uri.startswith("sip:ephem_"), p1.sip_uri)
chk("만료시각도 기록", p1.sip_uri_expires_at is not None)
saved_uri = p1.sip_uri
db.close()

# sip 모드로 바꾸면 그 주소로 전화가 간다
db = SessionLocal()
from app.callcenter import voice as _voice  # noqa: E402
row = db.get(Setting, _voice.SETTING_DIAL_MODE)
if row is None:
    db.add(Setting(key=_voice.SETTING_DIAL_MODE, value="sip"))
else:
    row.value = "sip"
db.commit()
for e in ("v1@t.kr", "v2@t.kr", "v3@t.kr"):
    engine.set_availability(db, db.get(User, ids[e]), "AVAILABLE")
db.close()

CALL3 = "clawops-call-003"
r = post(c, "/api/cs/phone/voice/incoming",
         {"CallId": CALL3, "From": "01055554444", "To": "07000000000",
          "CallStatus": "ringing", "Direction": "inbound"})
chk("브라우저 주소로 연결 지시", f"<Sip>{saved_uri}</Sip>" in r.text, r.text[:250])
chk("휴대폰이 아니라 SIP", "<Number>" not in r.text, r.text[:250])

# 등록이 만료되면 그 상담원은 건너뛴다
db = SessionLocal()
import datetime as _dt  # noqa: E402
p1 = engine.ensure_profile(db, db.get(User, ids["v1@t.kr"]))
p1.sip_uri_expires_at = _dt.datetime.utcnow() - _dt.timedelta(minutes=1)
db.commit()
db.close()
c.post(f"/api/cs/phone/voice/after-dial",
       data={"CallId": CALL3, "DialCallStatus": "completed"},
       headers={"X-Signature": sign("/api/cs/phone/voice/after-dial",
                                    {"CallId": CALL3, "DialCallStatus": "completed"})})

CALL4 = "clawops-call-004"
r = post(c, "/api/cs/phone/voice/incoming",
         {"CallId": CALL4, "From": "01055554444", "To": "07000000000",
          "CallStatus": "ringing", "Direction": "inbound"})
chk("만료된 등록은 건너뛴다", saved_uri not in r.text, r.text[:250])

# 등록 해제
r = c.request("DELETE", "/api/cs/phone/webrtc-token", headers=H1)
chk("등록 해제", r.status_code == 200, r.text[:120])
db = SessionLocal()
p1 = engine.ensure_profile(db, db.get(User, ids["v1@t.kr"]))
chk("주소가 지워짐", p1.sip_uri == "", p1.sip_uri)
db.close()

# 부가서비스가 꺼져 있으면 501
_prov.sip_credential_id = ""
delattr(_prov, "issue_webrtc_token")
r = c.post("/api/cs/phone/webrtc-token", headers=H1)
chk("부가서비스 없으면 501", r.status_code == 501, str(r.status_code))

print("=== 10. stream 모드 VoiceML ===")
db = SessionLocal()
row = db.get(Setting, engine.SETTING_DIAL_MODE)
if row is None:
    db.add(Setting(key=engine.SETTING_DIAL_MODE, value="stream"))
else:
    row.value = "stream"
db.commit()
for e in ("v1@t.kr", "v2@t.kr", "v3@t.kr"):
    engine.set_availability(db, db.get(User, ids[e]), "AVAILABLE")
db.close()

CALL5 = "clawops-call-005"
r = post(c, "/api/cs/phone/voice/incoming",
         {"CallId": CALL5, "From": "01033332222", "To": "07000000000",
          "CallStatus": "ringing", "Direction": "inbound"})
chk("Connect/Stream 으로 응답", "<Connect" in r.text and "<Stream" in r.text, r.text[:250])
chk("wss 주소로 보낸다", "wss://" in r.text, r.text[:250])
chk("표가 붙어 있다", "?t=" in r.text, r.text[:250])
chk("끝난 뒤 부를 주소 지정", "after-stream" in r.text, r.text[:250])
chk("Dial 은 쓰지 않는다", "<Dial" not in r.text, r.text[:250])

db = SessionLocal()
call5 = db.query(CsCallLog).filter(CsCallLog.external_call_id == CALL5).first()
sess5 = db.query(CsCallSession).filter(CsCallSession.call_log_id == call5.id).first()
chk("stream 에서는 우리가 20초를 센다", sess5.ring_deadline is not None,
    str(sess5.ring_deadline))
db.close()

r = post(c, "/api/cs/phone/voice/after-stream", {"CallId": CALL5})
chk("중계 끝나면 통화 정리", "<Hangup/>" in r.text, r.text[:200])
db = SessionLocal()
call5 = db.query(CsCallLog).filter(CsCallLog.external_call_id == CALL5).first()
chk("통화 기록 종료됨", call5.status in ("COMPLETED", "MISSED"), call5.status)
db.close()

print("=== 11. 발신 통화 — 받자마자 끊기지 않아야 한다 ===")
db = SessionLocal()
row = db.get(Setting, engine.SETTING_DIAL_MODE)
row.value = "stream"
db.commit()
# 음성 중계 모드에서는 상담원 휴대폰 번호가 없다. 그래도 끊기면 안 된다.
p1 = engine.ensure_profile(db, db.get(User, ids["v1@t.kr"]))
p1.phone_number = ""
db.commit()
out_call = CsCallLog(provider="clawops", external_call_id="ob-1",
                     phone_number="01044445555", counselor_id=ids["v1@t.kr"],
                     direction="OUTBOUND", status="RINGING")
db.add(out_call); db.commit(); db.refresh(out_call)
db.add(CsCallSession(call_log_id=out_call.id, state="RINGING",
                     current_counselor_id=ids["v1@t.kr"], ring_step=1))
db.commit()
db.close()

r = post(c, "/api/cs/phone/voice/outbound", {"CallId": "ob-1", "CallStatus": "answered"})
chk("끊지 않는다", "<Hangup/>" not in r.text, r.text[:250])
chk("음성 중계로 잇는다", "<Connect" in r.text and "<Stream" in r.text, r.text[:250])
chk("휴대폰으로 되걸지 않는다", "<Dial" not in r.text, r.text[:250])

db = SessionLocal()
oc = db.query(CsCallLog).filter(CsCallLog.external_call_id == "ob-1").first()
os_ = db.query(CsCallSession).filter(CsCallSession.call_log_id == oc.id).first()
chk("통화중으로 표시", oc.status == "ANSWERED", oc.status)
chk("세션도 통화중", os_.state == "ANSWERED", os_.state)
db.close()

print("=== 12. 휴대폰 모드 발신은 예전대로 ===")
db = SessionLocal()
db.get(Setting, engine.SETTING_DIAL_MODE).value = "number"
p1 = engine.ensure_profile(db, db.get(User, ids["v1@t.kr"]))
p1.phone_number = "01011110001"
db.commit()
out2 = CsCallLog(provider="clawops", external_call_id="ob-2",
                 phone_number="01044445555", counselor_id=ids["v1@t.kr"],
                 direction="OUTBOUND", status="RINGING")
db.add(out2); db.commit(); db.refresh(out2)
db.add(CsCallSession(call_log_id=out2.id, state="RINGING",
                     current_counselor_id=ids["v1@t.kr"], ring_step=1))
db.commit()
db.close()

r = post(c, "/api/cs/phone/voice/outbound", {"CallId": "ob-2", "CallStatus": "answered"})
chk("상담원 휴대폰으로 잇는다", "01011110001" in r.text, r.text[:250])
chk("끊지 않는다", "<Hangup/>" not in r.text, r.text[:250])

print("=== 13. 휴대폰 모드인데 번호가 없으면 ===")
db = SessionLocal()
p1 = engine.ensure_profile(db, db.get(User, ids["v1@t.kr"]))
p1.phone_number = ""
db.commit()
out3 = CsCallLog(provider="clawops", external_call_id="ob-3",
                 phone_number="01044445555", counselor_id=ids["v1@t.kr"],
                 direction="OUTBOUND", status="RINGING")
db.add(out3); db.commit(); db.refresh(out3)
db.commit()
db.close()
r = post(c, "/api/cs/phone/voice/outbound", {"CallId": "ob-3", "CallStatus": "answered"})
chk("안내하고 끊는다(무음 아님)", "<Say" in r.text and "<Hangup/>" in r.text, r.text[:250])

print("=== 14. 통화 ID 를 못 잡았어도 발신이 끊기지 않아야 한다 ===")
db = SessionLocal()
db.get(Setting, engine.SETTING_DIAL_MODE).value = "stream"
# 사업자 응답에서 ID 를 못 잡은 상황: external_call_id 가 비어 있다
orphan = CsCallLog(provider="clawops", external_call_id="",
                   phone_number="01066667777", counselor_id=ids["v1@t.kr"],
                   direction="OUTBOUND", status="RINGING")
db.add(orphan); db.commit(); db.refresh(orphan)
orphan_id = orphan.id
db.close()

r = post(c, "/api/cs/phone/voice/outbound",
         {"CallId": "CA-late-0001", "To": "01066667777", "CallStatus": "answered"})
chk("끊지 않는다", "<Hangup/>" not in r.text, r.text[:200])
chk("음성 중계로 잇는다", "<Connect" in r.text, r.text[:200])

db = SessionLocal()
fixed = db.get(CsCallLog, orphan_id)
chk("통화 ID 를 뒤늦게 붙였다", fixed.external_call_id == "CA-late-0001",
    fixed.external_call_id)
chk("통화중으로 표시", fixed.status == "ANSWERED", fixed.status)
db.close()

print("=== 15. 아무 통화나 붙잡지는 않는다 ===")
r = post(c, "/api/cs/phone/voice/outbound",
         {"CallId": "CA-nomatch-1", "To": "01099990000", "CallStatus": "answered"})
chk("번호가 다르면 붙이지 않는다", "<Hangup/>" in r.text, r.text[:200])

print("=== 16. 전화 소리 ===")
from app.callcenter import sounds as _snd  # noqa: E402

# 이 검사에는 관리자가 필요하다. 소리를 바꾸는 것은 관리자만 할 수 있어야 한다.
db = SessionLocal()
if db.query(User).filter(User.email == "snd-adm@t.kr").first() is None:
    db.add(User(email="snd-adm@t.kr", name="관리자", role=Role.admin,
                password_hash=hash_password("pw12345!"), is_active=True))
    db.commit()
db.close()
_first = c.post("/api/cs/login",
                json={"email": "snd-adm@t.kr", "password": "pw12345!"}).json()
_adm_device = _first.get("device_token", "")
db = SessionLocal()
from app.models import CsDevice as _Dev  # noqa: E402
_d = db.query(_Dev).order_by(_Dev.id.desc()).first()
if _d is not None:
    _d.status = "approved"
    db.commit()
db.close()
_ra = c.post("/api/cs/login", json={"email": "snd-adm@t.kr", "password": "pw12345!"},
             headers={"X-CS-Device": _adm_device}).json()
HA = {"Authorization": f"Bearer {_ra['token']}", "X-CS-Device": _adm_device}
chk("관리자 로그인", _ra.get("ok") is True, str(_ra)[:120])
for k in _snd.KINDS:
    _snd.clear(k)

r = c.get("/api/cs/phone/sounds", headers=H1).json()
chk("세 가지 소리가 있다", set(r.keys()) == {"ring", "dial", "hold"}, str(r.keys()))
chk("처음엔 기본 소리", all(not v.get("exists") for v in r.values()), str(r))

# 상담원은 못 올린다
r = c.put("/api/cs/phone/sounds/ring", headers=H1,
          files={"file": ("a.mp3", b"\x00" * 100, "audio/mpeg")})
chk("상담원은 못 올린다", r.status_code == 403, str(r.status_code))

# 관리자는 올린다
r = c.put("/api/cs/phone/sounds/ring", headers=HA,
          files={"file": ("bell.mp3", b"ID3" + b"\x00" * 500, "audio/mpeg")})
chk("수신 벨 올리기", r.status_code == 200 and r.json()["exists"] is True, r.text[:160])

r = c.get("/api/cs/phone/sounds/ring/file", headers=H1)
chk("상담원이 내려받을 수 있다", r.status_code == 200 and len(r.content) > 100,
    str(r.status_code))
chk("캐시하지 않는다", "no-store" in r.headers.get("cache-control", ""),
    r.headers.get("cache-control", ""))

# 대기음: 8kHz μ-law 라 초 단위로 계산된다 (8000바이트 = 1초)
r = c.put("/api/cs/phone/sounds/hold", headers=HA,
          files={"file": ("hold.ulaw", bytes([0x7F]) * 16000, "application/octet-stream")})
chk("대기음 올리기", r.status_code == 200, r.text[:160])
chk("길이를 초로 알려준다", abs(r.json()["seconds"] - 2.0) < 0.05, str(r.json()))

frames = _snd.hold_frames()
chk("음성 중계가 읽을 수 있다", frames is not None and len(frames) == 100,
    str(len(frames) if frames else None))
chk("한 조각은 20ms(160바이트)", frames and len(frames[0]) == 160,
    str(len(frames[0]) if frames else 0))

# 너무 긴 대기음은 잘린다
r = c.put("/api/cs/phone/sounds/hold", headers=HA,
          files={"file": ("long.ulaw", bytes([0x7F]) * (8000 * 200),
                          "application/octet-stream")})
chk("너무 길면 거절", r.status_code == 413, str(r.status_code))

# 없는 종류
r = c.put("/api/cs/phone/sounds/nope", headers=HA,
          files={"file": ("x.mp3", b"x" * 10, "audio/mpeg")})
chk("모르는 종류는 404", r.status_code == 404, str(r.status_code))

# 기본으로 되돌리기
r = c.request("DELETE", "/api/cs/phone/sounds/ring", headers=HA)
chk("기본으로 되돌리기", r.status_code == 200 and r.json()["exists"] is False, r.text[:160])
r = c.get("/api/cs/phone/sounds/ring/file", headers=H1)
chk("되돌리면 파일이 없다", r.status_code == 404, str(r.status_code))

for k in _snd.KINDS:
    _snd.clear(k)
chk("대기음도 치우면 기본으로", _snd.hold_frames() is None)

print()
print(f"===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
