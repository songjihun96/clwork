import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import PhoneVerify from "../components/PhoneVerify";
import { errMsg, okMsg } from "../toast";

function FindIdBox() {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [phoneToken, setPhoneToken] = useState("");
  const [needVerify, setNeedVerify] = useState(true);

  useEffect(() => {
    api.verifyConfig()
      .then((c) => setNeedVerify(c.find_id_requires_verification))
      .catch(() => {});
  }, []);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setResult(null);
    setBusy(true);
    try {
      const res = await api.findId({
        name: name.trim(),
        phone: phone.trim(),
        phone_verification_token: phoneToken,
      });
      setResult(res.emails);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} style={{ display: "grid", gap: 14 }}>
      <p style={{ fontSize: 13.5, color: "var(--steel)", margin: 0 }}>
        가입할 때 입력한 <b>이름</b>과, <b>본인 확인을 마친 휴대폰번호</b>가 일치해야
        이메일(아이디)을 알려드립니다. 타인의 번호로 조회할 수 없도록 문자 인증을 거치며,
        이메일 일부는 가려서 보여드립니다.
      </p>
      <div className="field">
        <label className="label">이름</label>
        <input className="input" value={name} required onChange={(e) => setName(e.target.value)} />
      </div>
      {needVerify ? (
        <PhoneVerify
          purpose="find_id"
          phone={phone}
          onPhoneChange={setPhone}
          onVerified={(token) => setPhoneToken(token)}
          label="가입 시 등록한 휴대폰번호"
        />
      ) : (
        <div className="field">
          <label className="label">가입 시 등록한 휴대폰번호</label>
          <input className="input" value={phone} required inputMode="tel"
            placeholder="010-1234-5678" onChange={(e) => setPhone(e.target.value)} />
        </div>
      )}
      {error && <div className="notice notice-error">{error}</div>}
      <button className="btn btn-signal" disabled={busy || (needVerify && !phoneToken)}>
        {busy ? "찾는 중…" : "아이디 찾기"}
      </button>

      {result && (
        <div className="notice notice-ok">
          {result.length === 0 ? (
            "이름과 휴대폰번호가 일치하는 계정을 찾지 못했습니다. 휴대폰번호를 등록하지 않았다면 비밀번호 재설정 또는 관리자에게 문의해주세요."
          ) : (
            <>
              <div style={{ marginBottom: 6 }}>찾은 이메일(아이디):</div>
              {result.map((em) => (
                <div key={em} style={{ fontWeight: 600 }}>{em}</div>
              ))}
            </>
          )}
        </div>
      )}
    </form>
  );
}

function FindPwBox() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1); // 1: 이메일 입력, 2: 코드+새 비번
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  const sendCode = async (e) => {
    e.preventDefault();
    setMsg(null);
    setBusy(true);
    try {
      const res = await api.forgotPassword(email.trim());
      setStep(2);
      setMsg({ type: res.mail_configured === false ? "info" : "ok", text: res.message });
    } catch (err) {
      setMsg(errMsg(err.message));
    } finally {
      setBusy(false);
    }
  };

  const reset = async (e) => {
    e.preventDefault();
    setMsg(null);
    if (pw.length < 8) return setMsg(errMsg("비밀번호는 8자 이상이어야 합니다."));
    if (pw !== pw2) return setMsg(errMsg("비밀번호가 서로 다릅니다."));
    setBusy(true);
    try {
      await api.resetPassword(email.trim(), code.trim(), pw);
      setMsg(okMsg("비밀번호가 변경되었습니다. 로그인 화면으로 이동합니다."));
      setTimeout(() => navigate("/login"), 1200);
    } catch (err) {
      setMsg(errMsg(err.message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <p style={{ fontSize: 13.5, color: "var(--steel)", margin: 0 }}>
        가입한 이메일로 6자리 인증코드를 보내드립니다. 코드를 입력하면 새 비밀번호를 설정할 수 있습니다.
      </p>

      {step === 1 ? (
        <form onSubmit={sendCode} style={{ display: "grid", gap: 14 }}>
          <div className="field">
            <label className="label">가입한 이메일</label>
            <input className="input" type="email" value={email} required onChange={(e) => setEmail(e.target.value)} />
          </div>
          {msg && <div className={`notice notice-${msg.type}`}>{msg.text}</div>}
          <button className="btn btn-signal" disabled={busy}>{busy ? "발송 중…" : "인증코드 받기"}</button>
        </form>
      ) : (
        <form onSubmit={reset} style={{ display: "grid", gap: 14 }}>
          {msg && <div className={`notice notice-${msg.type}`}>{msg.text}</div>}
          <div className="field">
            <label className="label">인증코드 (6자리)</label>
            <input className="input" value={code} required maxLength={6} inputMode="numeric"
              placeholder="메일로 받은 숫자 6자리" onChange={(e) => setCode(e.target.value)} />
          </div>
          <div className="field">
            <label className="label">새 비밀번호</label>
            <input className="input" type="password" value={pw} required autoComplete="new-password"
              onChange={(e) => setPw(e.target.value)} />
            <span style={{ fontSize: 12, color: "var(--steel-light)" }}>8자 이상</span>
          </div>
          <div className="field">
            <label className="label">새 비밀번호 확인</label>
            <input className="input" type="password" value={pw2} required autoComplete="new-password"
              onChange={(e) => setPw2(e.target.value)} />
          </div>
          <button className="btn btn-signal" disabled={busy}>{busy ? "변경 중…" : "비밀번호 변경"}</button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setStep(1); setMsg(null); }}>
            이메일 다시 입력
          </button>
        </form>
      )}
    </div>
  );
}

export default function FindAccount() {
  const [tab, setTab] = useState("id");

  return (
    <div className="wrap" style={{ maxWidth: 420, padding: "56px 0" }}>
      <span className="label">계정 찾기</span>
      <h1 style={{ fontSize: 26, margin: "8px 0 22px" }}>아이디 · 비밀번호 찾기</h1>

      <div className="tabs" style={{ marginBottom: 20 }}>
        <button className={`tab ${tab === "id" ? "active" : ""}`} onClick={() => setTab("id")}>아이디 찾기</button>
        <button className={`tab ${tab === "pw" ? "active" : ""}`} onClick={() => setTab("pw")}>비밀번호 재설정</button>
      </div>

      {tab === "id" ? <FindIdBox /> : <FindPwBox />}

      <p style={{ fontSize: 13.5, color: "var(--steel)", marginTop: 18 }}>
        <Link to="/login" style={{ color: "var(--ink)", fontWeight: 600 }}>로그인으로 돌아가기</Link>
      </p>
    </div>
  );
}
