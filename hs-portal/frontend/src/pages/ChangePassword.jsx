import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import PhoneVerify from "../components/PhoneVerify";
import { errMsg, okMsg } from "../toast";

export default function ChangePassword() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [cur, setCur] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [phone, setPhone] = useState(user?.phone || "");
  const [phoneToken, setPhoneToken] = useState("");
  // 인증 도입 이전 가입자는 등록된 번호가 없어 문자 인증을 할 수 없다.
  const hasPhone = Boolean(user?.phone);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  if (!user) {
    return (
      <div className="wrap" style={{ maxWidth: 460, padding: "56px 0" }}>
        <div className="empty"><p>로그인이 필요합니다.</p></div>
      </div>
    );
  }

  const submit = async (e) => {
    e.preventDefault();
    setMsg(null);
    if (pw.length < 8) return setMsg(errMsg("새 비밀번호는 8자 이상이어야 합니다."));
    if (pw !== pw2) return setMsg(errMsg("새 비밀번호가 서로 다릅니다."));
    setBusy(true);
    try {
      if (hasPhone && !phoneToken) {
        setMsg(errMsg("휴대폰 인증을 완료해주세요."));
        setBusy(false);
        return;
      }
      await api.changePassword(cur, pw, hasPhone ? phoneToken : undefined);
      setMsg(okMsg("비밀번호가 변경되었습니다."));
      setCur(""); setPw(""); setPw2("");
      setTimeout(() => navigate("/account"), 1200);
    } catch (err) {
      setMsg(errMsg(err.message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="wrap" style={{ maxWidth: 460, padding: "48px 0 70px" }}>
      <Link to="/account" className="label" style={{ color: "var(--steel)", textDecoration: "none" }}>
        ← 마이페이지
      </Link>
      <h1 style={{ fontSize: 24, margin: "10px 0 6px" }}>비밀번호 변경</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 0 }}>
        현재 비밀번호를 확인한 뒤 새 비밀번호로 바꿉니다.
      </p>

      <form className="panel" onSubmit={submit} style={{ marginTop: 16 }}>
        {msg && <div className={`notice notice-${msg.type}`} style={{ marginBottom: 12 }}>{msg.text}</div>}
        <div className="field">
          <label className="label">현재 비밀번호</label>
          <input className="input" type="password" value={cur} onChange={(e) => setCur(e.target.value)} />
        </div>
        <div className="field" style={{ marginTop: 12 }}>
          <label className="label">새 비밀번호</label>
          <input className="input" type="password" value={pw} onChange={(e) => setPw(e.target.value)} />
          <span className="label" style={{ color: "var(--steel-light)" }}>8자 이상</span>
        </div>
        <div className="field" style={{ marginTop: 12 }}>
          <label className="label">새 비밀번호 확인</label>
          <input className="input" type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} />
        </div>
        {hasPhone ? (
          <div style={{ marginTop: 12 }}>
            <PhoneVerify
              purpose="change_pw"
              phone={phone}
              onPhoneChange={setPhone}
              onVerified={(token) => setPhoneToken(token)}
              label="본인확인 (등록된 휴대폰번호)"
            />
          </div>
        ) : (
          <p style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 12, lineHeight: 1.7 }}>
            등록된 휴대폰번호가 없어 본인확인을 건너뜁니다.{" "}
            <Link to="/change-phone">번호를 등록</Link>해두시면 계정을 더 안전하게 보호할 수 있습니다.
          </p>
        )}
        <button className="btn btn-primary" style={{ width: "100%", marginTop: 16 }}
          disabled={busy || (hasPhone && !phoneToken)}>
          {busy ? "변경 중…" : "비밀번호 변경"}
        </button>
      </form>
    </div>
  );
}
