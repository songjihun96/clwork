"""전화망 ↔ 브라우저 음성 다리가 실제로 소리를 옮기는지 확인한다.

ClawOps 없이, 사업자가 보낼 WebSocket 프레임을 그대로 흉내 낸다.
여기서 통과했다고 실제 통화 음질이 좋다는 뜻은 아니다. 그건 진짜로
걸어봐야 안다. 여기서 보는 것은 "소리가 양쪽으로 흐르는가"와
"남의 통화에 못 끼어드는가"다.
"""
import base64
import json
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:////tmp/ab.db"
os.environ["SECRET_KEY"] = "x"
os.environ["PHONE_PROVIDER"] = "clawops"
os.environ["PHONE_API_KEY"] = "k"
os.environ["PHONE_ACCOUNT_ID"] = "a"
os.environ["PHONE_WEBHOOK_SECRET"] = "test-signing-secret"
os.environ["PHONE_DID_NUMBER"] = "07000000000"
os.environ["PHONE_VOICE_BASE"] = "https://cs.example.kr"

if os.path.exists("/tmp/ab.db"):
    os.remove("/tmp/ab.db")
sys.path.insert(0, ".")

from fastapi.testclient import TestClient          # noqa: E402
from app.main import app                           # noqa: E402
from app.database import SessionLocal              # noqa: E402
from app.models import CsCallLog, CsCallSession, Role, Setting, User  # noqa: E402
from app.auth import create_access_token, hash_password  # noqa: E402
from app.callcenter import audio, engine           # noqa: E402

OK = []


def chk(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  OK  " if cond else "  FAIL") + f"  {name}" + (f"  {extra}" if not cond and extra else ""))


# ── 상담원 둘과 통화 하나 ─────────────────────────────────────
db = SessionLocal()
for name, email in [("김상담", "a1@t.kr"), ("이상담", "a2@t.kr")]:
    u = User(email=email, name=name, role=Role.cs,
             password_hash=hash_password("pw12345!"), is_active=True)
    db.add(u); db.commit(); db.refresh(u)
    p = engine.ensure_profile(db, u)
    p.availability_status = "AVAILABLE"
db.add(Setting(key=engine.SETTING_DIAL_MODE, value="stream"))
db.commit()
ids = {u.email: u.id for u in db.query(User).all()}

call = CsCallLog(provider="clawops", external_call_id="ab-1", phone_number="01011112222",
                 direction="INBOUND", status="RINGING")
db.add(call); db.commit(); db.refresh(call)
db.add(CsCallSession(call_log_id=call.id, state="RINGING",
                     current_counselor_id=ids["a1@t.kr"], ring_step=1))
db.commit()
CALL_ID = call.id
db.close()

TOK1 = create_access_token_user = None
db = SessionLocal()
TOK1 = create_access_token(db.get(User, ids["a1@t.kr"]))
TOK2 = create_access_token(db.get(User, ids["a2@t.kr"]))
db.close()

c = TestClient(app)
GOOD = audio.stream_token(CALL_ID)
TONE = base64.b64encode(bytes([0xFF] * 160)).decode()   # 고객 목소리 대신
MIC = base64.b64encode(bytes([0x7F] * 160)).decode()    # 상담원 목소리 대신

print("=== 1. 연결 방식 ===")
db = SessionLocal()
chk("stream 모드", engine.dial_mode(db) == "stream", engine.dial_mode(db))
chk("우리가 링 시간을 센다",
    engine.external_ring_timer(db, __import__("app.phone", fromlist=["x"]).get_provider()) is False)
db.close()

print("=== 2. 아무나 못 붙는다 ===")
try:
    with c.websocket_connect(f"/api/cs/phone/voice/stream/{CALL_ID}?t=bad.token"):
        chk("잘못된 표는 거절", False, "붙어버렸다")
except Exception:
    chk("잘못된 표는 거절", True)

try:
    with c.websocket_connect(f"/api/cs/phone/voice/stream/{CALL_ID}"):
        chk("표 없으면 거절", False, "붙어버렸다")
except Exception:
    chk("표 없으면 거절", True)

print("=== 3. 소리가 양쪽으로 흐른다 ===")
with c.websocket_connect(f"/api/cs/phone/voice/stream/{CALL_ID}?t={GOOD}") as net:
    chk("전화망 연결됨", audio.active_bridge_count() == 1, str(audio.active_bridge_count()))

    # 상담원이 붙기 전에는 연결음이 고객에게 간다
    first = json.loads(net.receive_text())
    chk("연결음이 흐른다", first.get("event") == "media"
        and bool(first.get("media", {}).get("payload")), str(first)[:120])

    # 남의 통화에는 못 붙는다
    try:
        with c.websocket_connect(f"/api/cs/ws/audio?token={TOK2}&call_id={CALL_ID}"):
            chk("배정 안 된 상담원은 거절", False, "붙어버렸다")
    except Exception:
        chk("배정 안 된 상담원은 거절", True)

    # 배정된 상담원은 붙는다
    with c.websocket_connect(f"/api/cs/ws/audio?token={TOK1}&call_id={CALL_ID}") as agent:
        # 고객 목소리 → 상담원
        net.send_text(json.dumps({
            "event": "media", "sequenceNumber": "1",
            "media": {"track": "inbound", "chunk": "1", "timestamp": "0", "payload": TONE},
        }))
        got = json.loads(agent.receive_text())
        chk("고객 목소리가 상담원에게", got.get("t") == "audio" and got.get("p") == TONE,
            str(got)[:120])

        # 상담원 목소리 → 고객
        agent.send_text(json.dumps({"t": "audio", "p": MIC}))
        for _ in range(60):     # 연결음 프레임이 섞여 오므로 걸러낸다
            out = json.loads(net.receive_text())
            if out.get("media", {}).get("payload") == MIC:
                break
        chk("상담원 목소리가 고객에게",
            out.get("event") == "media" and out.get("media", {}).get("payload") == MIC,
            str(out)[:120])

        chk("사업자가 정한 형식대로 보낸다",
            set(out.keys()) == {"event", "media"} and set(out["media"].keys()) == {"payload"},
            str(out)[:120])

print("=== 4. 끊으면 정리된다 ===")
chk("다리가 치워짐", audio.active_bridge_count() == 0, str(audio.active_bridge_count()))

print("=== 5. 없는 통화에는 못 붙는다 ===")
try:
    with c.websocket_connect(f"/api/cs/ws/audio?token={TOK1}&call_id=99999"):
        chk("없는 통화 거절", False, "붙어버렸다")
except Exception:
    chk("없는 통화 거절", True)

print()
print(f"===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
