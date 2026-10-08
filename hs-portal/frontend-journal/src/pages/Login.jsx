import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../auth";
import { homeFor } from "../App";

// 본 사이트(udjschool.ggm.kr)와 같은 계정을 쓴다.
// 도메인이 달라 로그인 상태는 공유되지 않으므로 여기서 한 번 더 로그인한다.
export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  // 로그인이 필요해 보내진 경우 끝나면 그 화면으로 돌아간다. 우리 사이트 안 경로만.
  const [search] = useSearchParams();
  const rawNext = search.get("next") || "";
  const next = rawNext.startsWith("/") && !rawNext.startsWith("//") ? rawNext : "";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const me = await login(email.trim(), password);
      // 역할마다 쓸 수 있는 화면이 달라 각자의 시작 화면으로 보낸다.
      navigate(next && me.role === "student" ? next : homeFor(me), { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="wrap page" style={{ maxWidth: 420 }}>
      <span className="label">기록해</span>
      <h1>학교생활을 기록하세요</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 0 }}>
        우리동네 직업계고 계정으로 그대로 로그인할 수 있습니다.
      </p>

      <form className="panel" onSubmit={submit} style={{ marginTop: 18 }}>
        {error && <div className="notice notice-error" style={{ marginBottom: 14 }}>{error}</div>}

        <label className="field">
          <span className="label">이메일</span>
          <input className="input" type="email" value={email} required
            autoComplete="username" onChange={(e) => setEmail(e.target.value)} />
        </label>

        <label className="field">
          <span className="label">비밀번호</span>
          <input className="input" type="password" value={password} required
            autoComplete="current-password" onChange={(e) => setPassword(e.target.value)} />
        </label>

        <button className="btn btn-primary" style={{ width: "100%" }} disabled={busy}>
          {busy ? "로그인 중…" : "로그인"}
        </button>
      </form>

      <p style={{ fontSize: 13, color: "var(--steel)", marginTop: 16, lineHeight: 1.8 }}>
        계정이 없으신가요? <Link to={next ? `/signup?next=${encodeURIComponent(next)}` : "/signup"}>회원가입</Link><br />
        비밀번호를 잊으셨다면{" "}
        <a href="https://udjschool.ggm.kr/find-account">계정 찾기</a>를 이용해주세요.
      </p>
    </div>
  );
}
