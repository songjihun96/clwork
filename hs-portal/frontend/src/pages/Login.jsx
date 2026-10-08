import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import SchoolAccountNotice from "../components/SchoolAccountNotice";
import { useAuth } from "../auth";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  // 로그인이 필요해서 여기로 보내진 경우, 끝나면 보던 자리로 돌려보낸다.
  // 안 그러면 홈으로 떨어져서 무엇을 하려던 참이었는지부터 다시 찾아야 한다.
  const [search] = useSearchParams();
  const next = search.get("next") || "";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const user = await login(email, password);
      // 남이 준 주소로 밖에 내보내지 않는다 — 우리 사이트 안 경로만 받는다.
      if (next.startsWith("/") && !next.startsWith("//")) navigate(next);
      else if (user.role === "admin") navigate("/admin");
      else if (user.role === "school") navigate("/my-school");
      else navigate("/");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="wrap" style={{ maxWidth: 400, padding: "56px 0" }}>
      <span className="label">로그인</span>
      <h1 style={{ fontSize: 26, margin: "8px 0 22px" }}>다시 오셨네요</h1>

      <form onSubmit={submit} style={{ display: "grid", gap: 14 }}>
        <div className="field">
          <label className="label" htmlFor="email">이메일</label>
          <input id="email" className="input" type="email" value={email} required
            onChange={(e) => setEmail(e.target.value)} autoComplete="username" />
        </div>
        <div className="field">
          <label className="label" htmlFor="pw">비밀번호</label>
          <input id="pw" className="input" type="password" value={password} required
            onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </div>
        {error && <div className="notice notice-error">{error}</div>}
        <button className="btn btn-signal" disabled={busy}>
          {busy ? "확인 중…" : "로그인"}
        </button>
      </form>

      <p style={{ fontSize: 13.5, color: "var(--steel)", marginTop: 18 }}>
        학생 계정이 없다면 <Link to={next ? `/signup?next=${encodeURIComponent(next)}` : "/signup"} style={{ color: "var(--ink)", fontWeight: 600 }}>회원가입</Link>
        {" · "}
        <Link to="/find-account" style={{ color: "var(--ink)", fontWeight: 600 }}>아이디·비밀번호 찾기</Link>
      </p>

      <SchoolAccountNotice style={{ marginTop: 20 }} />
    </div>
  );
}
