import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

const today = () => new Date().toISOString().slice(0, 10);

// 만 나이. 생일이 지나지 않았으면 한 살 빼야 한다.
function ageOf(iso) {
  if (!iso) return null;
  const b = new Date(iso);
  if (Number.isNaN(b.getTime())) return null;
  const t = new Date();
  let y = t.getFullYear() - b.getFullYear();
  const before =
    t.getMonth() < b.getMonth() ||
    (t.getMonth() === b.getMonth() && t.getDate() < b.getDate());
  return before ? y - 1 : y;
}

export default function Signup() {
  const { setSession } = useAuth();
  const navigate = useNavigate();

  const [form, setForm] = useState({
    email: "", password: "", confirm: "", name: "",
    phone: "", birth: "", guardianEmail: "",
  });
  const [agree, setAgree] = useState({ privacy: false, terms: false });
  const [phoneToken, setPhoneToken] = useState("");
  const [pending, setPending] = useState(null);   // 보호자 동의 대기
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const age = ageOf(form.birth);
  const isChild = age !== null && age < 14;

  const submit = async (e) => {
    e.preventDefault();
    setError("");

    if (form.password !== form.confirm) {
      setError("비밀번호가 서로 다릅니다.");
      return;
    }
    if (form.password.length < 8) {
      setError("비밀번호는 8자 이상이어야 합니다.");
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
    if (!agree.privacy || !agree.terms) {
      setError("약관과 개인정보 수집에 동의해야 가입할 수 있습니다.");
      return;
    }

    setBusy(true);
    try {
      const res = await api.signup({
        email: form.email.trim(),
        password: form.password,
        name: form.name.trim(),
        phone: form.phone.trim(),
        phone_verification_token: phoneToken,
        birth_date: form.birth,
        guardian_email: isChild ? form.guardianEmail.trim() : null,
        privacy_consent: agree.privacy,
        terms_consent: agree.terms,
      });

      if (res.guardian_consent_required) {
        setPending(res);
        return;
      }
      setSession(res.access_token, res.user);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  if (pending) {
    return (
      <div className="wrap page" style={{ maxWidth: 460 }}>
        <span className="label">보호자 동의 대기</span>
        <h1>거의 다 됐어요</h1>
        <div className="notice" style={{ lineHeight: 1.8 }}>
          <b>{pending.guardian_email}</b> 로 보호자 동의 요청 메일을 보냈습니다.
          보호자께서 링크를 눌러 동의해주시면 바로 로그인할 수 있습니다.
        </div>
        <p style={{ fontSize: 13, color: "var(--steel)", marginTop: 14, lineHeight: 1.8 }}>
          개인정보 보호법에 따라 만 14세 미만은 법정대리인 동의가 있어야 가입이
          완료됩니다. 동의 링크는 7일간 유효합니다.
        </p>
        <Link to="/login" className="btn" style={{ marginTop: 16 }}>로그인 화면으로</Link>
      </div>
    );
  }

  return (
    <div className="wrap page" style={{ maxWidth: 440 }}>
      <span className="label">회원가입</span>
      <h1>기록해 시작하기</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 0, lineHeight: 1.8 }}>
        하나의 계정으로 <a href="https://udjschool.ggm.kr">우리동네 직업계고</a>도
        함께 이용할 수 있습니다.
      </p>

      <form className="panel" onSubmit={submit} style={{ marginTop: 16 }}>
        {error && <div className="notice notice-error" style={{ marginBottom: 14 }}>{error}</div>}

        <label className="field">
          <span className="label">이메일</span>
          <input className="input" type="email" value={form.email} required
            autoComplete="username" onChange={set("email")} />
        </label>

        <label className="field">
          <span className="label">이름</span>
          <input className="input" value={form.name} required minLength={2}
            onChange={set("name")} />
        </label>

        <label className="field">
          <span className="label">생년월일</span>
          <input className="input" type="date" value={form.birth} required
            max={today()} onChange={set("birth")} />
          <span style={{ fontSize: 12, color: "var(--steel-light)" }}>
            만 14세 미만은 보호자 동의가 있어야 가입할 수 있어 확인이 필요합니다.
          </span>
        </label>

        {isChild && (
          <label className="field">
            <span className="label">보호자 이메일</span>
            <input className="input" type="email" value={form.guardianEmail} required
              placeholder="보호자님의 이메일 주소" onChange={set("guardianEmail")} />
            <span style={{ fontSize: 12, color: "var(--signal-deep)" }}>
              입력하신 주소로 동의 요청 메일이 갑니다.
            </span>
          </label>
        )}

        <PhoneVerify
          email={form.email}
          phone={form.phone}
          onPhoneChange={(v) => setForm((f) => ({ ...f, phone: v }))}
          onVerified={setPhoneToken}
        />

        <label className="field">
          <span className="label">비밀번호</span>
          <input className="input" type="password" value={form.password} required
            minLength={8} autoComplete="new-password" onChange={set("password")} />
        </label>

        <label className="field">
          <span className="label">비밀번호 확인</span>
          <input className="input" type="password" value={form.confirm} required
            autoComplete="new-password" onChange={set("confirm")} />
        </label>

        <div style={{ borderTop: "1px solid var(--line)", paddingTop: 14, marginTop: 4 }}>
          {[
            ["privacy", "개인정보 수집·이용에 동의합니다", "https://udjschool.ggm.kr/privacy"],
            ["terms", "이용약관에 동의합니다", "https://udjschool.ggm.kr/terms"],
          ].map(([key, label, href]) => (
            <label key={key} className="row" style={{ alignItems: "flex-start", gap: 8,
              marginBottom: 8, cursor: "pointer" }}>
              <input type="checkbox" checked={agree[key]} style={{ marginTop: 4 }}
                onChange={(e) => setAgree({ ...agree, [key]: e.target.checked })} />
              <span style={{ fontSize: 14, lineHeight: 1.6 }}>
                {label} <a href={href} target="_blank" rel="noreferrer">보기</a>
              </span>
            </label>
          ))}

          {/* AI 동의는 가입 시점부터 켜져 있다(자기소개서 화면에서 벽을 한 번
              더 세우지 않는다). 그러면 여기서 무슨 일이 일어나는지 반드시
              알려야 한다 — 모르고 동의된 것은 동의가 아니다. */}
          <p style={{ fontSize: 12.5, color: "var(--steel)", lineHeight: 1.7,
                      margin: "10px 0 0" }}>
            자기소개서 AI 도움을 바로 쓸 수 있게 준비해 둡니다. 분석을 위해
            작성한 글이 <b>국외(미국)의 AI 서비스로 전송</b>되며, 이름·학교·
            연락처는 전송 전에 가려서 보냅니다. 원하지 않으시면 가입 후
            <b> 내 정보 → 보안</b>에서 언제든 거둘 수 있습니다.{" "}
            <a href="https://udjschool.ggm.kr/privacy" target="_blank"
              rel="noreferrer">개인정보처리방침 제7조</a>
          </p>
        </div>

        <button className="btn btn-primary" style={{ width: "100%", marginTop: 10 }}
          disabled={busy}>
          {busy ? "가입 중…" : "가입하기"}
        </button>
      </form>

      <p style={{ fontSize: 13, color: "var(--steel)", marginTop: 16 }}>
        이미 계정이 있으신가요? <Link to="/login">로그인</Link>
      </p>
    </div>
  );
}

/* ─────────── 휴대폰 인증 ───────────
   인증 자체는 UDJ 것을 그대로 쓴다. 계정이 그쪽에 만들어지므로
   인증 토큰도 같은 곳에서 발급받아야 한다. */
function PhoneVerify({ email, phone, onPhoneChange, onVerified }) {
  const [channel, setChannel] = useState("sms");
  const [sent, setSent] = useState(false);
  const [code, setCode] = useState("");
  const [verified, setVerified] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [left, setLeft] = useState(0);
  const [cool, setCool] = useState(0);
  const timer = useRef(null);
  const coolTimer = useRef(null);

  useEffect(() => {
    api.udjVerifyConfig().then((c) => setChannel(c.channel)).catch(() => {});
    return () => {
      clearInterval(timer.current);
      clearInterval(coolTimer.current);
    };
  }, []);

  // 번호를 바꾸면 인증을 처음부터 다시 한다.
  useEffect(() => {
    setSent(false);
    setVerified(false);
    setCode("");
    onVerified("");
  }, [phone]);

  const countdown = (setter, seconds, ref) => {
    setter(seconds);
    clearInterval(ref.current);
    ref.current = setInterval(() => {
      setter((v) => {
        if (v <= 1) {
          clearInterval(ref.current);
          return 0;
        }
        return v - 1;
      });
    }, 1000);
  };

  const send = async () => {
    setBusy(true);
    setError("");
    setMsg("");
    try {
      const res = await api.udjSendCode({ phone, purpose: "signup", email: email || undefined });
      setSent(true);
      countdown(setLeft, (res.ttl_min || 3) * 60, timer);
      countdown(setCool, 60, coolTimer);
      const where = res.sent_to ? ` (${res.sent_to})` : "";
      setMsg(res.channel === "email"
        ? `인증번호를 이메일로 보냈습니다${where}.`
        : `인증번호를 문자로 보냈습니다${where}.`);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const verify = async () => {
    setBusy(true);
    setError("");
    try {
      const res = await api.udjVerifyCode({ phone, purpose: "signup", code });
      setVerified(true);
      setMsg("인증이 완료되었습니다.");
      clearInterval(timer.current);
      onVerified(res.verification_token);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const mmss = `${String(Math.floor(left / 60)).padStart(2, "0")}:${String(left % 60).padStart(2, "0")}`;
  const canSend = !busy && cool === 0 && (phone || "").replace(/\D/g, "").length >= 10;

  return (
    <div className="field">
      <span className="label">휴대폰번호</span>
      {channel === "email" && (
        <span style={{ fontSize: 12, color: "var(--steel-light)", display: "block", marginBottom: 4 }}>
          인증번호는 문자가 아니라 <b>이메일</b>로 발송됩니다
          {email ? ` (${email})` : "(위에 입력한 이메일)"}.
        </span>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        <input className="input" value={phone} required inputMode="tel" maxLength={30}
          autoComplete="tel" placeholder="010-1234-5678" disabled={verified}
          onChange={(e) => onPhoneChange(e.target.value)} />
        <button type="button" className="btn btn-sm" style={{ whiteSpace: "nowrap" }}
          disabled={!canSend || verified} onClick={send}>
          {verified ? "인증완료" : cool > 0 ? `재발송 ${cool}초` : sent ? "재발송" : "인증번호 받기"}
        </button>
      </div>

      {sent && !verified && (
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <input className="input" value={code} inputMode="numeric" maxLength={6}
            placeholder="인증번호 6자리"
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
          <button type="button" className="btn btn-sm" style={{ whiteSpace: "nowrap" }}
            disabled={busy || code.length !== 6} onClick={verify}>확인</button>
        </div>
      )}

      {sent && !verified && left > 0 && (
        <span style={{ fontSize: 12, color: "var(--steel)" }}>남은 시간 {mmss}</span>
      )}
      {msg && !error && (
        <span style={{ fontSize: 12, color: verified ? "var(--verify)" : "var(--steel-light)" }}>
          {msg}
        </span>
      )}
      {error && <span style={{ fontSize: 12, color: "var(--alert)" }}>{error}</span>}
    </div>
  );
}
