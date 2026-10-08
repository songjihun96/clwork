import { useEffect, useState } from "react";
import { api } from "../api";
import { errMsg, okMsg } from "../toast";

/** 학교 계정의 공지 알림 설정(중·고 모두).
 *
 *  공지 알림 이메일 : 관리자가 공지를 올리며 '학교 계정 이메일 알림'을 켜면 이 주소로 간다.
 *                    비우면 학교 계정 로그인 메일로 간다.
 *  담당 선생님(고등학교만): '우리동네직업계고 공지'를 이메일·문자로 받는 분.
 *                    학교 계정 알림과는 별개로 관리한다.
 */
/** 서버가 준 UTC 시각(시간대 표시 없음)을 한국 날짜(YYYY-MM-DD)로. */
export const kstDate = (v) => {
  if (!v) return "";
  const s = String(v);
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : `${s}Z`);
  return Number.isNaN(d.getTime()) ? s.slice(0, 10)
    : new Date(d.getTime() + 9 * 3600e3).toISOString().slice(0, 10);
};

export default function NoticeSettings() {
  const [s, setS] = useState(null);
  const [contact, setContact] = useState({ name: "", position: "", email: "", phone: "", is_active: true, consent: false });
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.schoolNoticeSettings().then((d) => {
      setS(d);
      if (d.contact) setContact({ ...contact, ...d.contact });
    }).catch((e) => setMsg(errMsg(e.message)));
  }, []);

  if (!s) return <div className="panel"><p className="label">{msg?.text || "불러오는 중…"}</p></div>;
  const high = s.school_level !== "middle";

  const save = async () => {
    setBusy(true); setMsg(null);
    try {
      const body = { notice_email: s.notice_email, notice_email_enabled: s.notice_email_enabled };
      if (high) body.contact = contact;
      const d = await api.saveSchoolNoticeSettings(body);
      setS(d);
      if (d.contact) setContact({ ...contact, ...d.contact });
      setMsg(okMsg("저장했습니다."));
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally { setBusy(false); }
  };

  const cset = (k) => (e) => setContact({ ...contact, [k]: e.target.value });

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {msg && <div className={`notice notice-${msg.type}`}>{msg.text}</div>}
      <div className="panel">
        <h3>공지 알림 이메일</h3>
        <p className="adm-note" style={{ marginTop: -4 }}>
          우리동네 직업계고가 학교 계정에 알리는 공지를 이 주소로 받습니다.
          비워 두면 로그인 이메일(<b>{s.fallback_email || "없음"}</b>)로 보냅니다.
        </p>
        <div className="field">
          <label className="label" htmlFor="ns-email">공지 알림 이메일</label>
          <input id="ns-email" className="input" type="email" value={s.notice_email} maxLength={120}
            placeholder={s.fallback_email || "office@school.kr"}
            onChange={(e) => setS({ ...s, notice_email: e.target.value })} />
        </div>
        <label style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 10, fontSize: 14, cursor: "pointer" }}>
          <input type="checkbox" checked={s.notice_email_enabled}
            onChange={(e) => setS({ ...s, notice_email_enabled: e.target.checked })} />
          우리동네 직업계고 공지 이메일 받기
        </label>
      </div>

      {high && (
        <div className="panel">
          <h3>우리동네직업계고 담당 선생님</h3>
          <p className="adm-note" style={{ marginTop: -4 }}>
            우리동네 직업계고 운영팀이 직업계고에 보내는 공지(촬영·행사·안내 등)를 <b>이메일과 문자</b>로
            받으실 선생님입니다. 담당이 바뀌면 여기서 고쳐 주세요.
          </p>
          <div className={`notice ${contact.consent_at ? "notice-ok" : ""}`} style={{ marginBottom: 12, fontSize: 13 }}>
            {contact.consent_at
              ? `공지 수신 동의 ${kstDate(contact.consent_at)} · 이메일·문자로 공지를 보냅니다.`
              : "공지 수신 동의가 없어 이메일·문자를 보내지 않습니다. 아래에서 동의해 주세요."}
          </div>
          <div className="nm-grid">
            <div className="field">
              <label className="label" htmlFor="ct-name">이름</label>
              <input id="ct-name" className="input" value={contact.name} maxLength={40} onChange={cset("name")} />
            </div>
            <div className="field">
              <label className="label" htmlFor="ct-pos">직위</label>
              <input id="ct-pos" className="input" value={contact.position} maxLength={40}
                placeholder="예: 취업부장" onChange={cset("position")} />
            </div>
            <div className="field">
              <label className="label" htmlFor="ct-email">이메일</label>
              <input id="ct-email" className="input" type="email" value={contact.email} maxLength={120}
                onChange={cset("email")} />
            </div>
            <div className="field">
              <label className="label" htmlFor="ct-phone">휴대폰</label>
              <input id="ct-phone" className="input" inputMode="tel" value={contact.phone} maxLength={30}
                placeholder="010-0000-0000" onChange={cset("phone")} />
            </div>
          </div>
          {s.contact_consent_text && (
            <details style={{ marginTop: 12, fontSize: 13, color: "var(--steel)" }}>
              <summary style={{ cursor: "pointer", fontWeight: 600 }}>공지 수신 개인정보 수집·이용 안내</summary>
              <ul style={{ lineHeight: 1.8, marginBottom: 0 }}>
                <li>항목: {s.contact_consent_text.items}</li>
                <li>목적: {s.contact_consent_text.purpose}</li>
                <li>보관: {s.contact_consent_text.retention}</li>
                <li>{s.contact_consent_text.right_to_refuse}</li>
              </ul>
            </details>
          )}
          <label style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 10, fontSize: 14, cursor: "pointer" }}>
            <input type="checkbox" checked={!!contact.consent} style={{ marginTop: 3 }}
              onChange={(e) => setContact({ ...contact, consent: e.target.checked })} />
            <span>담당 선생님이 우리동네직업계고 공지를 이메일·문자로 받는 데(개인정보 수집·이용) 동의합니다. <b>(선택)</b>
              <small style={{ display: "block", color: "var(--steel)" }}>체크를 해제하고 저장하면 동의가 철회되어 더 이상 보내지 않습니다.</small></span>
          </label>
        </div>
      )}

      <div>
        <button type="button" className="btn btn-primary" onClick={save} disabled={busy}>
          {busy ? "저장 중…" : "저장"}
        </button>
      </div>
    </div>
  );
}
