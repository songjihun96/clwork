import { useEffect, useState } from "react";
import { api } from "../api";

/** 기록해 학교 계정(중·고)의 공지 알림 설정. 기록해 공지를 받을 메일 주소와 수신 여부.
 *  UDJ 공지 알림 설정은 UDJ 학교 관리 화면에서 따로 한다. */
export default function SchoolNoticeSettings() {
  const [s, setS] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.schoolNoticeSettings().then(setS).catch((e) => setMsg({ type: "error", text: e.message }));
  }, []);
  if (!s) return msg ? <div className={`notice notice-${msg.type}`}>{msg.text}</div> : null;
  const save = async () => {
    setBusy(true); setMsg(null);
    try {
      setS(await api.saveSchoolNoticeSettings({ notice_email: s.notice_email, enabled: s.enabled }));
      setMsg({ type: "ok", text: "저장했습니다." });
    } catch (e) { setMsg({ type: "error", text: e.message }); } finally { setBusy(false); }
  };
  return (
    <div className="panel" id="notice-settings">
      <h3 style={{ marginTop: 0 }}>공지 알림 설정</h3>
      <p className="meta" style={{ margin: "0 0 10px", lineHeight: 1.7 }}>
        기록해 공지를 이 주소로 받습니다. 비워 두면 로그인 이메일(<b>{s.fallback_email}</b>)로 보냅니다.
      </p>
      {msg && <div className={`notice notice-${msg.type}`} style={{ marginBottom: 10 }}>{msg.text}</div>}
      <label className="field">
        <span className="label">공지 알림 이메일</span>
        <input className="input" type="email" value={s.notice_email} maxLength={120} placeholder={s.fallback_email}
          onChange={(e) => setS({ ...s, notice_email: e.target.value })} />
      </label>
      <label className="row" style={{ gap: 6, marginBottom: 12 }}>
        <input type="checkbox" checked={s.enabled} onChange={(e) => setS({ ...s, enabled: e.target.checked })} />
        기록해 공지 이메일 받기
      </label>
      <button type="button" className="btn btn-primary btn-sm" onClick={save} disabled={busy}>
        {busy ? "저장 중…" : "저장"}
      </button>
    </div>
  );
}
