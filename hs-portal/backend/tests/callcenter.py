"""상담원 3명에게 전화가 순서대로 넘어가는지, 끝까지 훑는다.

실제 전화 없이 MockPhoneProvider 로 돌린다. 여기서 통과했다고 해서
실제 010 통화가 된다는 뜻은 아니다. 그건 전화 사업자를 붙인 뒤에
진짜 통화로 확인해야 한다.
"""
import os
import sys
import time

os.environ["DATABASE_URL"] = "sqlite:////tmp/cc.db"
os.environ["SECRET_KEY"] = "x"
os.environ["PHONE_PROVIDER"] = "mock"

if os.path.exists("/tmp/cc.db"):
    os.remove("/tmp/cc.db")
sys.path.insert(0, ".")

from fastapi.testclient import TestClient          # noqa: E402
from app.main import app                            # noqa: E402
from app.database import SessionLocal               # noqa: E402
from app.models import (                            # noqa: E402
    CsCallLog, CsCallSession, CsCustomer, CsInquiryType, Role, Setting, User,
)
from app.auth import hash_password                  # noqa: E402
from app.callcenter import engine                   # noqa: E402
from app.callcenter.phones import format_phone, mask_phone, normalize_phone  # noqa: E402

OK = []


def chk(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  OK  " if cond else "  FAIL") + f"  {name}" + (f"  {extra}" if not cond and extra else ""))


# ── 상담원 3명 + 관리자 ────────────────────────────────────────
db = SessionLocal()
people = []
for name, email, role in [
    ("김상담", "cs1@t.kr", Role.cs),
    ("이상담", "cs2@t.kr", Role.cs),
    ("박상담", "cs3@t.kr", Role.cs),
    ("관리자", "adm@t.kr", Role.admin),
]:
    u = User(email=email, name=name, role=role,
             password_hash=hash_password("pw12345!"), is_active=True)
    db.add(u)
db.commit()
users = {u.email: u for u in db.query(User).all()}
cs1, cs2, cs3 = users["cs1@t.kr"], users["cs2@t.kr"], users["cs3@t.kr"]
admin = users["adm@t.kr"]

# 순서를 못 박는다. 김 -> 이 -> 박
for i, u in enumerate([cs1, cs2, cs3]):
    p = engine.ensure_profile(db, u)
    p.ring_order = (i + 1) * 10
    p.availability_status = "AVAILABLE"
# 관리자는 통화 큐에서 뺀다.
pa = engine.ensure_profile(db, admin)
pa.accepts_calls = False
db.commit()

# 링 타임아웃은 하한이 3초다(engine.get_ring_timeout). 그에 맞춰 기다린다.
db.add(Setting(key=engine.SETTING_RING_TIMEOUT, value="3"))
db.commit()

# 기존 고객 하나
db.add(CsCustomer(name="홍길동", phone_number="01012345678",
                  customer_type="STUDENT", school_name="양주공업고"))
db.commit()
ids = {"cs1": cs1.id, "cs2": cs2.id, "cs3": cs3.id}
db.close()

print("=== 0. 전화번호 정규화 ===")
chk("하이픈 제거", normalize_phone("010-1234-5678") == "01012345678")
chk("국제표기 +82", normalize_phone("+82 10-1234-5678") == "01012345678")
chk("국제표기 0082", normalize_phone("008210 1234 5678") == "01012345678")
chk("표시 형식", format_phone("01012345678") == "010-1234-5678",
    format_phone("01012345678"))
chk("서울 유선", format_phone("0212345678") == "02-1234-5678", format_phone("0212345678"))
chk("마스킹", mask_phone("+821012345678") == "010-****-5678", mask_phone("+821012345678"))

print("=== 1. 순차분배: 아무도 안 받으면 다음 사람 ===")
db = SessionLocal()
call = engine.start_inbound_call(db, from_number="010-1234-5678",
                                  external_call_id="t-1", provider_name="mock")
sess = db.query(CsCallSession).filter(CsCallSession.call_log_id == call.id).first()
chk("1번 상담원에게 울림", sess.current_counselor_id == ids["cs1"], str(sess.current_counselor_id))
chk("통화 상태 RINGING", call.status == "RINGING", call.status)

time.sleep(3.2)
engine.tick_timeouts(db)
db.refresh(sess)
chk("무응답 -> 2번 상담원", sess.current_counselor_id == ids["cs2"], str(sess.current_counselor_id))

time.sleep(3.2)
engine.tick_timeouts(db)
db.refresh(sess)
chk("무응답 -> 3번 상담원", sess.current_counselor_id == ids["cs3"], str(sess.current_counselor_id))

time.sleep(3.2)
engine.tick_timeouts(db)
db.refresh(sess)
db.refresh(call)
chk("모두 무응답 -> 대기열", sess.state == "QUEUED", sess.state)
chk("통화 상태 QUEUED", call.status == "QUEUED", call.status)

print("=== 2. 대기열: 상담원이 다시 가능해지면 이어준다 ===")
# 셋 다 이미 불렸으므로 tried 를 비워 새 순번을 돌게 한다(실제로는 새 전화가 온 상황).
sess.tried_ids = ""
db.commit()
engine.set_availability(db, db.get(User, ids["cs2"]), "AVAILABLE")
db.refresh(sess)
chk("대기열에서 다시 울림", sess.state == "RINGING", sess.state)
chk("1번부터 다시", sess.current_counselor_id == ids["cs1"], str(sess.current_counselor_id))

print("=== 3. 거절하면 기다리지 않고 바로 다음 사람 ===")
engine.reject_call(db, call.id, db.get(User, ids["cs1"]))
db.refresh(sess)
chk("거절 -> 2번", sess.current_counselor_id == ids["cs2"], str(sess.current_counselor_id))

print("=== 4. 받으면 통화중, 끊으면 상담가능 ===")
engine.answer_call(db, call.id, db.get(User, ids["cs2"]))
db.refresh(call)
chk("상태 ANSWERED", call.status == "ANSWERED", call.status)
chk("담당 상담원 기록", call.counselor_id == ids["cs2"], str(call.counselor_id))
p2 = engine.ensure_profile(db, db.get(User, ids["cs2"]))
chk("상담원 BUSY", p2.availability_status == "BUSY", p2.availability_status)

time.sleep(1.1)
engine.hangup_call(db, call.id)
db.refresh(call)
db.refresh(p2)
chk("상태 COMPLETED", call.status == "COMPLETED", call.status)
chk("통화시간 기록", (call.duration_seconds or 0) >= 1, str(call.duration_seconds))
chk("상담원 AVAILABLE 복귀", p2.availability_status == "AVAILABLE", p2.availability_status)

print("=== 5. 아무도 없을 때는 부재중 ===")
for uid in ids.values():
    engine.set_availability(db, db.get(User, uid), "OFFLINE")
db.add(Setting(key=engine.SETTING_QUEUE, value="false"))
db.commit()
call2 = engine.start_inbound_call(db, from_number="01099998888",
                                   external_call_id="t-2", provider_name="mock")
db.refresh(call2)
chk("부재중 처리", call2.status == "MISSED", call2.status)
db.query(Setting).filter(Setting.key == engine.SETTING_QUEUE).update({"value": "true"})
db.commit()
db.close()

print("=== 6. HTTP: 로그인 → 테스트 전화 → 받기 → 상담 저장 ===")
# startup 이벤트(문의 유형 기본값 넣기, 링 타이머 시작)는 TestClient 를
# 컨텍스트 매니저로 열어야 실제로 돈다. 그냥 TestClient(app) 만 쓰면
# 운영에서 도는 준비 과정을 건너뛴 채로 검사하게 된다.
with TestClient(app) as c:
    r = c.post("/api/cs/login", json={"email": "cs1@t.kr", "password": "pw12345!"})
    body = r.json()
    # 사무실 IP 설정이 비어 있으므로 첫 접속은 기기 승인 대기가 된다.
    chk("새 기기는 승인 대기", body.get("device_status") == "pending", str(body)[:120])

    # 관리자가 승인한다.
    db = SessionLocal()
    from app.models import CsDevice  # noqa: E402
    dev = db.query(CsDevice).first()
    dev.status = "approved"
    db.commit()
    device_token = body["device_token"]
    db.close()

    r = c.post("/api/cs/login", json={"email": "cs1@t.kr", "password": "pw12345!"},
               headers={"X-CS-Device": device_token})
    body = r.json()
    chk("승인 후 로그인", body.get("ok") is True, str(body)[:120])
    H = {"Authorization": f"Bearer {body['token']}", "X-CS-Device": device_token}

    r = c.get("/api/cs/phone/settings", headers=H).json()
    chk("Provider 는 mock", r.get("provider") == "mock", str(r)[:120])
    chk("음성은 아직 안 흐른다고 알림", r.get("audio_ready") is False, str(r.get("audio_ready")))

    c.put("/api/cs/counselors/me/status", headers=H, json={"status": "AVAILABLE"})
    r = c.post("/api/cs/calls/mock/incoming", headers=H, json={"phone_number": "010-1234-5678"})
    chk("테스트 전화 걸기", r.status_code == 200, r.text[:160])
    call_id = r.json()["id"]

    r = c.get("/api/cs/calls/active", headers=H).json()
    mine = [x for x in r["items"] if x["id"] == call_id]
    chk("활성 통화 목록에 뜬다", len(mine) == 1, str(r)[:160])
    chk("나에게 울리는 중", mine and mine[0]["ringing_for_me"] is True, str(mine)[:200])
    chk("기존 고객으로 인식", mine and mine[0]["is_new_customer"] is False, str(mine)[:200])

    r = c.get("/api/cs/customers/lookup", headers=H, params={"phone": "01012345678"}).json()
    chk("발신번호로 고객 조회", r.get("found") is True and r["customer"]["name"] == "홍길동", str(r)[:160])
    chk("통화 중에는 번호 원문", r["customer"]["phone_number"] == "010-1234-5678",
        r["customer"]["phone_number"])
    customer_id = r["customer"]["id"]

    r = c.post(f"/api/cs/calls/{call_id}/answer", headers=H)
    chk("전화 받기", r.status_code == 200, r.text[:160])

    r = c.get("/api/cs/inquiry-types", headers=H).json()
    chk("문의 유형 기본값 있음", r["total"] > 0, str(r["total"]))
    type_id = r["items"][0]["id"]

    r = c.post("/api/cs/consultations", headers=H, json={
        "customer_id": customer_id, "call_log_id": call_id, "channel": "PHONE",
        "inquiry_type_id": type_id, "subject": "로그인 문의",
        "content": "비밀번호를 잊었다고 함", "result": "재설정 메일 안내",
        "status": "COMPLETED", "priority": "NORMAL",
    })
    chk("상담 저장", r.status_code == 200 and r.json()["status"] == "COMPLETED", r.text[:160])

    r = c.post(f"/api/cs/calls/{call_id}/hangup", headers=H)
    chk("통화 종료", r.status_code == 200 and r.json()["status"] == "COMPLETED", r.text[:160])

    r = c.get(f"/api/cs/customers/{customer_id}/call-logs", headers=H).json()
    chk("고객 통화 이력", r["total"] >= 1, str(r["total"]))
    chk("목록에서는 번호 마스킹", r["items"][0]["phone_number"] == "010-****-5678",
        r["items"][0]["phone_number"])

    r = c.get("/api/cs/statistics", headers=H).json()
    chk("통계 오늘 상담", r["consultations_today"] >= 1, str(r["consultations_today"]))
    chk("통계 상담원별", any(x["name"] == "김상담" for x in r["per_counselor"]), str(r["per_counselor"])[:160])

    print("=== 7. 권한: 상담원은 관리자 설정을 못 바꾼다 ===")
    r = c.put("/api/cs/phone/settings", headers=H,
              json={"ring_timeout_seconds": 30, "sequential_enabled": True, "queue_enabled": True})
    chk("상담원은 설정 변경 불가", r.status_code == 403, str(r.status_code))

    print("=== 8. 신규 고객 등록 ===")
    r = c.post("/api/cs/customers", headers=H, json={
        "name": "새손님", "phone_number": "010-5555-6666", "customer_type": "TEACHER",
        "school_name": "테스트고", "email": "", "memo": "",
    })
    chk("신규 고객 등록", r.status_code == 200, r.text[:160])
    r2 = c.post("/api/cs/customers", headers=H, json={
        "name": "중복", "phone_number": "01055556666", "customer_type": "OTHER",
        "school_name": "", "email": "", "memo": "",
    })
    chk("같은 번호 중복 등록 차단", r2.status_code == 409, str(r2.status_code))

    print("=== 9. 전화 걸기(발신) ===")
    r = c.post("/api/cs/calls/outbound", headers=H, json={"phone_number": "010-2222-3333"})
    chk("발신 통화 생성", r.status_code == 200 and r.json()["direction"] == "OUTBOUND", r.text[:160])
    out_id = r.json()["id"]

    r = c.get("/api/cs/calls/active", headers=H).json()
    mine = [x for x in r["items"] if x["id"] == out_id]
    chk("발신도 활성 목록에 뜬다", len(mine) == 1, str(r)[:200])
    chk("발신에는 받기 배너가 안 뜬다", mine and mine[0]["ringing_for_me"] is False, str(mine)[:200])
    chk("내가 건 전화로 표시", mine and mine[0]["outbound_for_me"] is True, str(mine)[:200])

    # 발신은 순차분배 대상이 아니다. 타임아웃으로 남에게 넘어가면 안 된다.
    db = SessionLocal()
    sess_out = db.query(CsCallSession).filter(CsCallSession.call_log_id == out_id).first()
    chk("발신은 링 타임아웃 없음", sess_out.ring_deadline is None, str(sess_out.ring_deadline))
    engine.tick_timeouts(db)
    db.refresh(sess_out)
    chk("ticker 가 발신을 안 건드림", sess_out.current_counselor_id == ids["cs1"],
        str(sess_out.current_counselor_id))
    db.close()

    r = c.post(f"/api/cs/calls/{out_id}/mock/answered", headers=H)
    chk("상대가 받음(Mock)", r.status_code == 200 and r.json()["status"] == "ANSWERED", r.text[:160])
    r = c.post(f"/api/cs/calls/{out_id}/hangup", headers=H)
    chk("발신 종료", r.status_code == 200 and r.json()["status"] == "COMPLETED", r.text[:160])

    print("=== 10. 통화 돌리기 ===")
    db = SessionLocal()
    engine.set_availability(db, db.get(User, ids["cs2"]), "AVAILABLE")
    db.close()

    r = c.post("/api/cs/calls/mock/incoming", headers=H, json={"phone_number": "010-1234-5678"})
    t_id = r.json()["id"]
    c.post(f"/api/cs/calls/{t_id}/answer", headers=H)

    r = c.post(f"/api/cs/calls/{t_id}/transfer", headers=H, json={"counselor_id": ids["cs2"]})
    chk("상담원에게 돌리기", r.status_code == 200, r.text[:200])

    db = SessionLocal()
    sess_t = db.query(CsCallSession).filter(CsCallSession.call_log_id == t_id).first()
    call_t = db.get(CsCallLog, t_id)
    chk("넘겨받은 사람에게 울림", sess_t.current_counselor_id == ids["cs2"],
        str(sess_t.current_counselor_id))
    chk("받기 전까지는 통화 아님", call_t.status == "RINGING", call_t.status)
    p1 = engine.ensure_profile(db, db.get(User, ids["cs1"]))
    chk("넘긴 사람은 상담 가능 복귀", p1.availability_status == "AVAILABLE", p1.availability_status)
    db.close()

    r = c.post(f"/api/cs/calls/{t_id}/transfer", headers=H, json={"counselor_id": ids["cs3"]})
    chk("내 통화가 아니면 못 돌림", r.status_code in (409, 400), str(r.status_code))
    c.post(f"/api/cs/calls/{t_id}/hangup", headers=H)

    print("=== 11. 상담 상태·우선순위 설정 ===")
    r = c.get("/api/cs/consultation-options", headers=H).json()
    chk("상태 목록", len(r["statuses"]) == 7, str(len(r["statuses"])))
    chk("완료는 미처리가 아님",
        next(o for o in r["statuses"] if o["code"] == "COMPLETED")["is_open"] is False)
    chk("완료는 잠김", next(o for o in r["statuses"] if o["code"] == "COMPLETED")["locked"] is True)

    r = c.put("/api/cs/consultation-options", headers=H,
              json={"statuses": [{"code": "HOLD", "label": "잠깐 보류"}]})
    chk("상담원은 상태 설정 변경 불가", r.status_code == 403, str(r.status_code))

    ra = c.post("/api/cs/login", json={"email": "adm@t.kr", "password": "pw12345!"},
                headers={"X-CS-Device": device_token}).json()
    HA = {"Authorization": f"Bearer {ra['token']}", "X-CS-Device": device_token}
    r = c.put("/api/cs/consultation-options", headers=HA, json={
        "statuses": [{"code": "HOLD", "label": "잠깐 보류", "is_open": False}],
        "priorities": [{"code": "URGENT", "label": "아주 급함"}],
    })
    chk("관리자는 이름 변경 가능", r.status_code == 200, r.text[:160])
    body = r.json()
    chk("바뀐 이름 반영",
        next(o for o in body["statuses"] if o["code"] == "HOLD")["label"] == "잠깐 보류",
        str(body["statuses"])[:160])
    chk("미처리에서 뺀 것 반영",
        next(o for o in body["statuses"] if o["code"] == "HOLD")["is_open"] is False)
    chk("우선순위 이름 변경",
        next(o for o in body["priorities"] if o["code"] == "URGENT")["label"] == "아주 급함")

    r = c.put("/api/cs/consultation-options", headers=HA,
              json={"statuses": [{"code": "MADE_UP", "label": "없는 상태"}]})
    chk("없는 코드는 무시", r.status_code == 200
        and all(o["code"] != "MADE_UP" for o in r.json()["statuses"]), r.text[:160])

    print("=== 12. 홈페이지 문의가 상담으로 들어온다 ===")
    db = SessionLocal()
    from app.models import Coed, School  # noqa: E402
    school = School(name="테스트공업고", category="특성화고", region="경기", address="a",
                    coed=Coed.coed, departments="기계과", is_visible=True)
    db.add(school)
    db.commit()
    db.refresh(school)
    school_id = school.id
    db.close()

    r = c.post(f"/api/schools/{school_id}/inquiries", json={
        "asker_name": "문의자", "contact_email": "ask@t.kr", "contact_phone": "010-7777-1111",
        "question": "입학 상담을 받고 싶습니다.", "privacy_consent": True,
    })
    chk("문의 접수 성공", r.status_code == 200 and r.json().get("ok") is True, r.text[:160])

    r = c.get("/api/cs/consultations", headers=H, params={"channel": "HOMEPAGE"}).json()
    chk("상담 목록에 올라옴", r["total"] >= 1, str(r)[:200])
    hp = r["items"][0]
    chk("채널 HOMEPAGE", hp["channel"] == "HOMEPAGE", hp["channel"])
    chk("원본 문의 번호 표시", "[홈페이지 문의 #" in hp["content"], hp["content"][:60])

    r = c.get("/api/cs/customers/lookup", headers=H, params={"phone": "01077771111"}).json()
    chk("문의자가 고객으로 등록", r.get("found") is True, str(r)[:160])
    chk("고객 이름 반영", r["customer"]["name"] == "문의자", str(r["customer"])[:120])

print()
print(f"===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
