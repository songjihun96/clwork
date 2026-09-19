import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

/** 가입 — 이 서비스가 직접 받는다.
 *
 * 기록해는 UDJ 계정을 빌려 썼고 그래서 전화번호 인증까지 거쳤다. 여기는
 * 별도 사이트라 기댈 곳이 없고, 아직 돈을 받지도 않는다. 그래서 가입에서
 * 묻는 것을 **최소한**으로 둔다 — 이메일·비밀번호·이름·구분.
 * 학교나 학년은 나중에 내 정보에서 적으면 된다.
 */
export default function Signup() {
  const navigate = useNavigate();
  const { setSession } = useAuth();
  const [form, setForm] = useState({
    email: "", password: "", password2: "", name: "",
    role: "student", school_name: "",
    privacy_consent: false, terms_consent: false,
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const set = (patch) => setForm({ ...form, ...patch });

  const submit = async (e) => {
    e.preventDefault();
    if (form.password.length < 8) {
      setError("비밀번호는 8자 이상으로 정해주세요.");
      return;
    }
    if (form.password !== form.password2) {
      setError("비밀번호가 서로 다릅니다.");
      return;
    }
    if (!form.privacy_consent || !form.terms_consent) {
      setError("약관과 개인정보 수집에 동의해야 가입할 수 있습니다.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const body = { ...form };
      delete body.password2;   // 확인용이라 서버에 안 보낸다
      const data = await api.signup(body);
      setSession(data.access_token, data.user);
      navigate("/");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="wrap" style={{ maxWidth: 460, padding: "40px 0 60px" }}>
      <h1 style={{ fontSize: 26, marginBottom: 6 }}>가입하기</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 0 }}>
        연구를 시작하고 논문까지 정리할 수 있습니다.
      </p>

      <form className="panel" onSubmit={submit} style={{ marginTop: 18, display: "grid", gap: 14 }}>
        <div className="field">
          <label className="label">이메일</label>
          <input className="input" type="email" required value={form.email}
            onChange={(e) => set({ email: e.target.value })} />
        </div>

        <div className="field">
          <label className="label">이름</label>
          <input className="input" required value={form.name}
            onChange={(e) => set({ name: e.target.value })} />
        </div>

        <div className="field">
          <label className="label">구분</label>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            {[["student", "학생"], ["teacher", "교사"]].map(([v, label]) => (
              <label key={v} style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 14 }}>
                <input type="radio" name="role" checked={form.role === v}
                  onChange={() => set({ role: v })} />
                {label}
              </label>
            ))}
          </div>
        </div>

        <div className="field">
          <label className="label">학교 <span style={{ fontWeight: "normal", color: "var(--steel)" }}>(선택)</span></label>
          <input className="input" value={form.school_name}
            placeholder="예) 양주중학교"
            onChange={(e) => set({ school_name: e.target.value })} />
        </div>

        <div className="field">
          <label className="label">비밀번호 <span style={{ fontWeight: "normal", color: "var(--steel)" }}>(8자 이상)</span></label>
          <input className="input" type="password" required value={form.password}
            onChange={(e) => set({ password: e.target.value })} />
        </div>

        <div className="field">
          <label className="label">비밀번호 확인</label>
          <input className="input" type="password" required value={form.password2}
            onChange={(e) => set({ password2: e.target.value })} />
        </div>

        <div style={{ display: "grid", gap: 8 }}>
          <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13.5 }}>
            <input type="checkbox" checked={form.terms_consent}
              onChange={(e) => set({ terms_consent: e.target.checked })} />
            이용약관에 동의합니다.
          </label>
          <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13.5 }}>
            <input type="checkbox" checked={form.privacy_consent}
              onChange={(e) => set({ privacy_consent: e.target.checked })} />
            개인정보 수집·이용에 동의합니다.
          </label>
        </div>

        {error && <div className="notice notice-error">{error}</div>}

        <button className="btn btn-signal" type="submit" disabled={busy}>
          {busy ? "가입하는 중…" : "가입하기"}
        </button>

        <p style={{ fontSize: 13, color: "var(--steel)", margin: 0, textAlign: "center" }}>
          이미 계정이 있다면 <Link to="/login">로그인</Link>
        </p>
      </form>
    </div>
  );
}
