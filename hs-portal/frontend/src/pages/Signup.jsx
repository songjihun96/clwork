import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import PhoneVerify from "../components/PhoneVerify";

export default function Signup() {
  const { signup } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({
    name: "", email: "", phone: "", password: "", confirm: "",
    birth: "", guardianEmail: "",
  });
  const [pending, setPending] = useState(null);   // 보호자 동의 대기 안내
  const [phoneToken, setPhoneToken] = useState("");  // 휴대폰 인증 토큰
  const [consent, setConsent] = useState(false);
  const [termsConsent, setTermsConsent] = useState(false);
  const [showNotice, setShowNotice] = useState(false);
  const [showTerms, setShowTerms] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  // 만 나이. 생년월일이 비었거나 이상하면 null.
  const age = (() => {
    if (!form.birth) return null;
    const b = new Date(form.birth);
    if (Number.isNaN(b.getTime())) return null;
    const t = new Date();
    let y = t.getFullYear() - b.getFullYear();
    const before =
      t.getMonth() < b.getMonth() ||
      (t.getMonth() === b.getMonth() && t.getDate() < b.getDate());
    if (before) y -= 1;
    return y;
  })();
  const isChild = age !== null && age < 14;

  const submit = async (e) => {
    e.preventDefault();
    if (form.password !== form.confirm) {
      setError("비밀번호가 서로 다릅니다.");
      return;
    }
    if (form.password.length < 8) {
      setError("비밀번호는 8자 이상이어야 합니다.");
      return;
    }
    if (!consent) {
      setError("개인정보 수집·이용에 동의해야 가입할 수 있습니다.");
      return;
    }
    if (!termsConsent) {
      setError("이용약관에 동의해야 가입할 수 있습니다.");
      return;
    }
    if (!phoneToken) {
      setError("휴대폰 인증을 완료해주세요.");
      return;
    }
    if (age === null || age < 0 || age > 120) {
      setError("생년월일을 정확히 입력해주세요.");
      return;
    }
    if (isChild && !form.guardianEmail.trim()) {
      setError("만 14세 미만은 보호자 이메일이 필요합니다.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const res = await signup({
        email: form.email,
        password: form.password,
        name: form.name,
        phone: form.phone.trim(),
        phone_verification_token: phoneToken,
        privacy_consent: consent,
        terms_consent: termsConsent,
        birth_date: form.birth,
        guardian_email: isChild ? form.guardianEmail.trim() : null,
      });
      // 만 14세 미만이면 바로 로그인되지 않고 보호자 동의를 기다린다.
      if (res && res.guardian_consent_required) {
        setPending(res);
        return;
      }
      navigate("/");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  if (pending) {
    return (
      <div className="wrap" style={{ maxWidth: 460, padding: "56px 0" }}>
        <span className="label">보호자 동의 대기</span>
        <h1 style={{ fontSize: 24, margin: "8px 0 14px" }}>거의 다 됐어요</h1>
        <div className="notice" style={{ lineHeight: 1.7 }}>
          <b>{pending.guardian_email}</b> 로 보호자 동의 요청 메일을 보냈습니다.
          보호자께서 메일의 링크를 눌러 동의해주시면 바로 로그인할 수 있습니다.
          {!pending.mail_sent && (
            <div style={{ marginTop: 8, color: "var(--alert)" }}>
              메일 발송에 실패했습니다. 고객센터로 문의해주세요.
            </div>
          )}
        </div>
        <p style={{ fontSize: 13, color: "var(--steel)", marginTop: 14, lineHeight: 1.7 }}>
          개인정보 보호법에 따라 만 14세 미만 아동은 법정대리인의 동의가 있어야
          회원가입이 완료됩니다. 동의 링크는 7일간 유효합니다.
        </p>
        <Link to="/login" className="btn" style={{ marginTop: 18 }}>로그인 화면으로</Link>
      </div>
    );
  }

  return (
    <div className="wrap" style={{ maxWidth: 400, padding: "56px 0" }}>
      <span className="label">학생 회원가입</span>
      <h1 style={{ fontSize: 26, margin: "8px 0 22px" }}>학교를 저장하고 비교하세요</h1>

      <form onSubmit={submit} style={{ display: "grid", gap: 14 }}>
        <div className="field">
          <label className="label" htmlFor="name">이름</label>
          <input id="name" className="input" value={form.name} required onChange={set("name")} />
        </div>
        <div className="field">
          <label className="label" htmlFor="email">이메일</label>
          <input id="email" className="input" type="email" value={form.email} required
            onChange={set("email")} autoComplete="username" />
        </div>
        <PhoneVerify
          purpose="signup"
          email={form.email}
          phone={form.phone}
          onPhoneChange={(v) => setForm((f) => ({ ...f, phone: v }))}
          onVerified={(token) => setPhoneToken(token)}
        />
        <div className="field">
          <label className="label" htmlFor="birth">생년월일</label>
          <input id="birth" className="input" type="date" value={form.birth} required
            max={new Date().toISOString().slice(0, 10)} onChange={set("birth")} />
          <span style={{ fontSize: 12, color: "var(--steel-light)" }}>
            만 14세 미만은 보호자 동의가 있어야 가입할 수 있어 확인이 필요합니다.
          </span>
        </div>

        {isChild && (
          <div className="field">
            <label className="label" htmlFor="guardian">보호자 이메일</label>
            <input id="guardian" className="input" type="email" value={form.guardianEmail}
              required onChange={set("guardianEmail")} placeholder="보호자님의 이메일 주소" />
            <span style={{ fontSize: 12, color: "var(--signal-deep)" }}>
              만 {14}세 미만이라 보호자 동의가 필요합니다. 입력하신 주소로 동의 요청 메일이 갑니다.
            </span>
          </div>
        )}

        <div className="field">
          <label className="label" htmlFor="pw">비밀번호</label>
          <input id="pw" className="input" type="password" value={form.password} required
            onChange={set("password")} autoComplete="new-password" />
          <span style={{ fontSize: 12, color: "var(--steel-light)" }}>8자 이상</span>
        </div>
        <div className="field">
          <label className="label" htmlFor="pw2">비밀번호 확인</label>
          <input id="pw2" className="input" type="password" value={form.confirm} required
            onChange={set("confirm")} autoComplete="new-password" />
        </div>

        <div style={{ border: "1px solid var(--line)", borderRadius: 6, padding: 12 }}>
          <label style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: 13, cursor: "pointer" }}>
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)}
              style={{ marginTop: 2 }} />
            <span>
              <strong>[필수]</strong> 개인정보 수집·이용에 동의합니다.
              <button type="button" onClick={() => setShowNotice((v) => !v)}
                style={{ marginLeft: 6, background: "none", border: "none", color: "var(--signal-deep)", cursor: "pointer", padding: 0, fontSize: 12.5, textDecoration: "underline" }}>
                {showNotice ? "접기" : "자세히 보기"}
              </button>
            </span>
          </label>
          {showNotice && (
            <div style={{ marginTop: 10, fontSize: 12.5, color: "var(--steel)", lineHeight: 1.7 }}>
              <div><b>수집 항목</b> : 이름, 이메일, 비밀번호(암호화 저장), 휴대폰번호(선택)</div>
              <div><b>수집·이용 목적</b> : 회원 식별·로그인, 즐겨찾기 등 서비스 제공, 계정(아이디·비밀번호) 찾기</div>
              <div><b>보유·이용 기간</b> : 회원 탈퇴 시까지 보관 후 파기</div>
              <div style={{ color: "var(--alert)" }}>동의를 거부할 수 있으나, 이 경우 회원가입이 제한됩니다.</div>
            </div>
          )}
        </div>

        <div style={{ border: "1px solid var(--line)", borderRadius: 6, padding: 12 }}>
          <label style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: 13, cursor: "pointer" }}>
            <input type="checkbox" checked={termsConsent} onChange={(e) => setTermsConsent(e.target.checked)}
              style={{ marginTop: 2 }} />
            <span>
              <strong>[필수]</strong> 이용약관에 동의합니다.
              <Link to="/terms" target="_blank"
                style={{ marginLeft: 6, color: "var(--signal-deep)", fontSize: 12.5, textDecoration: "underline" }}>
                약관 보기
              </Link>
            </span>
          </label>
        </div>

        {error && <div className="notice notice-error">{error}</div>}
        <button className="btn btn-signal" disabled={busy}>
          {busy ? "가입 중…" : "가입하기"}
        </button>
      </form>

      <p style={{ fontSize: 13.5, color: "var(--steel)", marginTop: 18 }}>
        이미 계정이 있다면 <Link to="/login" style={{ color: "var(--ink)", fontWeight: 600 }}>로그인</Link>
      </p>
    </div>
  );
}
