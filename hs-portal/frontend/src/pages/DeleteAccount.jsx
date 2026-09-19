import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { errMsg } from "../toast";

export default function DeleteAccount() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [pw, setPw] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  if (!user) {
    return (
      <div className="wrap" style={{ maxWidth: 460, padding: "56px 0" }}>
        <div className="empty"><p>로그인이 필요합니다.</p></div>
      </div>
    );
  }

  const submit = async () => {
    if (!agreed) return setMsg(errMsg("안내를 확인하고 동의해 주세요."));
    if (!pw) return setMsg(errMsg("비밀번호를 입력해 주세요."));
    if (!window.confirm("정말 탈퇴하시겠습니까?\n되돌릴 수 없습니다.")) return;
    setBusy(true); setMsg(null);
    try {
      await api.deleteMyAccount(pw);
      logout();
      navigate("/");
    } catch (e) {
      setMsg(errMsg(e.message));
      setBusy(false);
    }
  };

  return (
    <div className="wrap" style={{ maxWidth: 460, padding: "48px 0 70px" }}>
      <Link to="/account" className="label" style={{ color: "var(--steel)", textDecoration: "none" }}>
        ← 마이페이지
      </Link>
      <h1 style={{ fontSize: 24, margin: "10px 0 6px" }}>회원 탈퇴</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 0 }}>
        탈퇴 전 아래 내용을 확인해 주세요.
      </p>

      <div className="panel" style={{ marginTop: 16 }}>
        <div className="notice notice-error" style={{ marginBottom: 14 }}>
          <b>탈퇴하면 이렇게 됩니다</b>
          <ul style={{ margin: "6px 0 0", paddingLeft: 18, lineHeight: 1.8 }}>
            <li>계정 정보와 즐겨찾기가 삭제됩니다.</li>
            <li>작성한 학교생활 일지와 재학생 인증 기록도 함께 삭제됩니다.</li>
            <li>같은 이메일로 다시 가입할 수 있지만, 이전 기록은 복구되지 않습니다.</li>
          </ul>
        </div>

        {msg && <div className={`notice notice-${msg.type}`} style={{ marginBottom: 12 }}>{msg.text}</div>}

        <label style={{ display: "flex", gap: 8, alignItems: "flex-start", cursor: "pointer", marginBottom: 14 }}>
          <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} style={{ marginTop: 3 }} />
          <span style={{ fontSize: 13.5, lineHeight: 1.6 }}>
            위 내용을 확인했으며, 삭제된 정보는 복구할 수 없음에 동의합니다.
          </span>
        </label>

        <div className="field">
          <label className="label">비밀번호 확인</label>
          <input className="input" type="password" value={pw} placeholder="본인 확인을 위해 입력해 주세요"
            onChange={(e) => setPw(e.target.value)} />
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
          <button className="btn btn-ghost" onClick={() => navigate("/account")} disabled={busy}>
            취소
          </button>
          <button
            onClick={submit}
            disabled={busy || !agreed}
            style={{
              flex: 1, padding: "10px 16px", borderRadius: 999, border: "none", cursor: agreed ? "pointer" : "not-allowed",
              background: agreed ? "var(--alert)" : "#c9ccd0", color: "#fff", fontWeight: 700, fontSize: 14,
            }}
          >
            {busy ? "처리 중…" : "탈퇴하기"}
          </button>
        </div>
      </div>
    </div>
  );
}
