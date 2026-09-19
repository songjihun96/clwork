import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../api";
import { ORG } from "../org";

// 개인정보 보호법 제22조의2 / 시행령 제17조의2에 따른 법정대리인 동의 화면.
// 만 14세 미만 아동이 가입 신청하면 보호자 메일로 이 주소가 전달된다.
export default function GuardianConsent() {
  const { token } = useParams();
  const [info, setInfo] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [agree, setAgree] = useState(false);

  useEffect(() => {
    api
      .guardianConsentInfo(token)
      .then(setInfo)
      .catch((e) => setError(e.message));
  }, [token]);

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      await api.guardianConsentSubmit(token);
      setDone(true);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (error && !info) {
    return (
      <div className="wrap" style={{ maxWidth: 520, padding: "56px 0" }}>
        <div className="notice notice-error">{error}</div>
      </div>
    );
  }
  if (!info) {
    return (
      <div className="wrap" style={{ maxWidth: 520, padding: "56px 0" }}>
        <p style={{ color: "var(--steel)" }}>확인하는 중입니다…</p>
      </div>
    );
  }

  if (done || info.consented) {
    return (
      <div className="wrap" style={{ maxWidth: 520, padding: "56px 0" }}>
        <span className="label">동의 완료</span>
        <h1 style={{ fontSize: 24, margin: "8px 0 14px" }}>동의해주셔서 감사합니다</h1>
        <div className="notice" style={{ lineHeight: 1.7 }}>
          {info.student_name}님의 계정이 활성화되었습니다. 이제 로그인해서 서비스를
          이용할 수 있습니다.
        </div>
        <Link to="/login" className="btn" style={{ marginTop: 18 }}>로그인 화면으로</Link>
      </div>
    );
  }

  if (info.expired) {
    return (
      <div className="wrap" style={{ maxWidth: 520, padding: "56px 0" }}>
        <span className="label">링크 만료</span>
        <h1 style={{ fontSize: 24, margin: "8px 0 14px" }}>동의 기간이 지났습니다</h1>
        <div className="notice notice-error" style={{ lineHeight: 1.7 }}>
          이 동의 링크는 만료되었습니다. 자녀분께 다시 회원가입을 진행하도록
          안내해주세요.
        </div>
      </div>
    );
  }

  return (
    <div className="wrap" style={{ maxWidth: 560, padding: "56px 0 70px" }}>
      <span className="label" style={{ color: "var(--signal-deep)" }}>법정대리인 동의</span>
      <h1 style={{ fontSize: 25, margin: "8px 0 6px" }}>
        자녀의 회원가입에 동의해주세요
      </h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 0, lineHeight: 1.7 }}>
        만 14세 미만 아동은 개인정보 보호법에 따라 법정대리인의 동의가 있어야
        회원가입이 완료됩니다.
      </p>

      <div
        style={{
          border: "1px solid var(--line)",
          borderRadius: 8,
          padding: 18,
          marginTop: 22,
          fontSize: 14.5,
          lineHeight: 1.75,
          color: "var(--ink-soft)",
        }}
      >
        <Row label="가입 신청자" value={info.student_name} />
        <Row label="수집 항목" value={(info.items || []).join(", ")} />
        <Row label="이용 목적" value={info.purpose} />
        <Row label="보유 기간" value={info.retention} />
        <p style={{ margin: "14px 0 0", fontSize: 13, color: "var(--steel)" }}>
          동의를 거부하실 수 있으며, 이 경우 자녀의 회원가입은 완료되지 않습니다.
          자세한 내용은 <Link to="/privacy">개인정보처리방침</Link>에서 확인하실 수 있습니다.
        </p>
      </div>

      <label
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: 8,
          marginTop: 20,
          fontSize: 14,
          cursor: "pointer",
        }}
      >
        <input
          type="checkbox"
          checked={agree}
          onChange={(e) => setAgree(e.target.checked)}
          style={{ marginTop: 3 }}
        />
        <span>
          위 내용을 확인했으며, 자녀의 개인정보 수집·이용에 동의합니다.
        </span>
      </label>

      {error && (
        <div className="notice notice-error" style={{ marginTop: 14 }}>{error}</div>
      )}

      <button
        className="btn"
        style={{ marginTop: 18 }}
        disabled={!agree || busy}
        onClick={submit}
      >
        {busy ? "처리 중…" : "동의하고 가입 완료하기"}
      </button>

      <p style={{ fontSize: 12, color: "var(--steel-light)", marginTop: 22, lineHeight: 1.7 }}>
        문의: {ORG.contactPhone} · {ORG.contactEmail} · 운영 {ORG.operator}
      </p>
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div style={{ display: "flex", gap: 12, padding: "5px 0" }}>
      <span style={{ minWidth: 84, color: "var(--steel)", fontWeight: 600 }}>{label}</span>
      <span>{value}</span>
    </div>
  );
}
