import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import PhoneVerify from "../components/PhoneVerify";
import { errMsg, okMsg } from "../toast";

// 휴대폰번호는 아이디·비밀번호 찾기의 본인확인 수단이라
// 현재 비밀번호와 새 번호 인증을 모두 거쳐야 바꿀 수 있다.
export default function ChangePhone() {
  const navigate = useNavigate();
  const [current, setCurrent] = useState("");   // 현재 등록된 번호
  const [pw, setPw] = useState("");
  const [phone, setPhone] = useState("");
  const [phoneToken, setPhoneToken] = useState("");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.myAccount().then((me) => setCurrent(me.phone || "")).catch(() => {});
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setMsg(null);
    if (!pw) {
      setMsg(errMsg("현재 비밀번호를 입력해주세요."));
      return;
    }
    if (!phoneToken) {
      setMsg(errMsg("새 휴대폰번호 인증을 완료해주세요."));
      return;
    }
    setBusy(true);
    try {
      const res = await api.changePhone(pw, phone.trim(), phoneToken);
      setCurrent(res.phone || phone.trim());
      setMsg(okMsg("휴대폰번호가 변경되었습니다."));
      setTimeout(() => navigate("/account"), 1200);
    } catch (err) {
      setMsg(errMsg(err.message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="wrap" style={{ maxWidth: 420, padding: "48px 0 70px" }}>
      <span className="label">계정 설정</span>
      <h1 style={{ fontSize: 24, margin: "8px 0 6px" }}>
        {current ? "휴대폰번호 변경" : "휴대폰번호 등록"}
      </h1>
      <p style={{ fontSize: 13.5, color: "var(--steel)", lineHeight: 1.7, marginTop: 0 }}>
        {current ? (
          <>현재 등록된 번호는 <b>{fmt(current)}</b> 입니다. </>
        ) : (
          <>아직 등록된 번호가 없습니다. </>
        )}
        아이디·비밀번호 찾기에 쓰이는 본인확인 수단이라 비밀번호 확인과 번호 인증이
        함께 필요합니다.
      </p>

      <form className="panel" onSubmit={submit} style={{ marginTop: 16 }}>
        {msg && (
          <div className={`notice notice-${msg.type}`} style={{ marginBottom: 12 }}>
            {msg.text}
          </div>
        )}

        <div className="field">
          <label className="label">현재 비밀번호</label>
          <input
            className="input"
            type="password"
            value={pw}
            autoComplete="current-password"
            onChange={(e) => setPw(e.target.value)}
          />
        </div>

        <div style={{ marginTop: 12 }}>
          <PhoneVerify
            purpose="change_phone"
            phone={phone}
            onPhoneChange={setPhone}
            onVerified={(token) => setPhoneToken(token)}
            label={current ? "새 휴대폰번호" : "휴대폰번호"}
          />
        </div>

        <button
          className="btn btn-primary"
          style={{ width: "100%", marginTop: 16 }}
          disabled={busy || !phoneToken || !pw}
        >
          {busy ? "처리 중…" : current ? "휴대폰번호 변경" : "휴대폰번호 등록"}
        </button>
      </form>

      <p style={{ fontSize: 12, color: "var(--steel-light)", marginTop: 16, lineHeight: 1.7 }}>
        번호를 바꾸면 이전 번호로도 알림이 발송됩니다.
        본인이 하지 않은 변경이라면 즉시 고객센터로 알려주세요.
      </p>

      <Link to="/account" className="label" style={{ display: "inline-block", marginTop: 14 }}>
        내 정보로 돌아가기
      </Link>
    </div>
  );
}

function fmt(phone) {
  const d = (phone || "").replace(/\D/g, "");
  if (d.length < 7) return "등록된 번호 없음";
  return `${d.slice(0, 3)}****${d.slice(-4)}`;
}
