import { useState } from "react";
import { api, setDevice } from "../api";
import { useAuth } from "../auth";
import { Note } from "../components/ui";

export default function Login() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // 기기 승인이 필요한 상태. { status, code }
  const [pending, setPending] = useState(null);

  const submit = async () => {
    if (!email || !password) {
      setError("이메일과 비밀번호를 입력해주세요.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const r = await api.login(email.trim(), password, label.trim());
      if (r.ok) {
        login(r.token, r.user);
        return;
      }
      // 새 기기면 서버가 토큰을 준다. 저장해 둬야 승인 후 알아본다.
      if (r.device_token) setDevice(r.device_token);
      setPending({ status: r.device_status, code: r.device_code, message: r.message });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (pending) {
    const revoked = pending.status === "revoked";
    return (
      <div className="gate">
        <div className="gate-box">
          <h1>{revoked ? "사용이 중지된 기기입니다" : "기기 승인이 필요합니다"}</h1>
          <p className="sub">
            {revoked
              ? "이 기기는 관리자가 사용을 중지했습니다. 다시 쓰려면 관리자에게 요청하세요."
              : "사무실 밖에서는 등록된 기기에서만 접속할 수 있습니다."}
          </p>

          {pending.code && (
            <>
              <div className="code">{pending.code}</div>
              <Note kind="info">
                관리자에게 이 코드를 알려주고 승인을 요청하세요. 승인되면 이 기기에서 바로
                로그인할 수 있습니다.
              </Note>
            </>
          )}

          <button className="btn primary" onClick={() => setPending(null)}>
            로그인 화면으로
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="gate">
      <div className="gate-box">
        <h1>
          <span>ㅇㅈ</span> 상담 지원
        </h1>
        <p className="sub">우리동네 직업계고 내부 업무용 화면입니다.</p>

        <Note kind="bad">{error}</Note>

        <div className="field">
          <label htmlFor="email">이메일</label>
          <input
            id="email"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
          />
        </div>
        <div className="field">
          <label htmlFor="pw">비밀번호</label>
          <input
            id="pw"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
          />
        </div>
        <div className="field">
          <label htmlFor="label">이 기기 이름 (선택)</label>
          <input
            id="label"
            placeholder="예: 사무실 노트북"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
          />
        </div>

        <button className="btn go" onClick={submit} disabled={busy}>
          {busy ? "확인하는 중…" : "로그인"}
        </button>
      </div>
    </div>
  );
}
