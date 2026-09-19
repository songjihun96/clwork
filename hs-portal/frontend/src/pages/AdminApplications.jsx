import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useSeo } from "../seo";
import { errMsg, okMsg } from "../toast";

/** 신청 관리 — 컨설팅·상담·영상·설명회 신청을 한 화면에서.
 *
 * 결제를 붙이지 않았으므로 **입금 확인이 사람 손을 탄다.** 그래서 상태를
 * 접수 → 입금 확인 → 완료로 두고, 목록에서 바로 넘길 수 있게 했다.
 * 메모 칸이 있는 이유도 같다 — "10/2 통화, 다음 주 토요일로 잡음" 같은 말을
 * 적어 둘 데가 없으면 결국 따로 엑셀을 만들게 된다.
 */

const STATUS_CLASS = {
  received: "badge-dorm", paid: "badge-cat", done: "badge-cat", cancelled: "badge-dorm",
};

/** 서버 시각을 보는 사람의 시간대로 보여 준다.
 *
 * 서버는 UTC 로 저장한다. 그런데 시간대 표시가 없는 문자열
 * ("2026-09-10T04:43:00")을 그대로 넘기면 브라우저가 **제 지역 시간**으로
 * 읽어 9시간이 어긋난다. 지금은 서버가 +00:00 을 붙여 보내지만, 예전에
 * 저장된 값이나 다른 화면에서 넘어온 값도 안전하게 읽도록 여기서 한 번 더
 * 막는다 — 시간대 표시가 없으면 UTC 로 본다.
 */
function fmtWhen(iso) {
  if (!iso) return "";
  const hasZone = /[Zz]|[+-]\d{2}:?\d{2}$/.test(iso);
  const d = new Date(hasZone ? iso : `${iso}Z`);
  if (Number.isNaN(d.getTime())) return "";
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export default function AdminApplications() {
  useSeo({ title: "신청 관리", path: "/admin/applications" });
  return (
    <div className="wrap" style={{ padding: "34px 0 60px" }}>
      <span className="label">관리자</span>
      <h1 style={{ fontSize: 26, margin: "8px 0 4px" }}>신청 관리</h1>
      <ApplicationsPanel />
    </div>
  );
}

/** 신청 목록 본체. 관리자 화면의 탭 안에서도 그대로 쓴다 —
 * 같은 화면을 두 벌 만들면 한쪽만 고치는 일이 반드시 생긴다. */
export function ApplicationsPanel() {
  const [data, setData] = useState(null);
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("");
  const [openId, setOpenId] = useState(null);
  const [settings, setSettings] = useState(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [msg, setMsg] = useState(null);
  const [csvBusy, setCsvBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await api.adminApplications({ kind, status }));
    } catch (e) {
      setMsg(errMsg(e.message));
    }
  }, [kind, status]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    api.applicationSettings().then(setSettings).catch(() => setSettings(null));
  }, []);

  const patch = async (id, body) => {
    try {
      await api.updateApplication(id, body);
      await load();
    } catch (e) {
      setMsg(errMsg(e.message));
    }
  };

  const remove = async (a) => {
    if (!window.confirm(`'${a.name}' 님의 ${a.kind_label} 신청을 삭제할까요?\n\n되돌릴 수 없습니다.`)) return;
    try {
      await api.deleteApplication(a.id);
      await load();
      setMsg(okMsg("삭제했습니다."));
    } catch (e) {
      setMsg(errMsg(e.message));
    }
  };

  const items = data?.items || [];

  return (
    <div>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 0 }}>
        컨설팅·상담·영상·설명회 신청이 모두 여기로 들어옵니다.
      </p>

      {/* 설정 */}
      <div className="panel" style={{ marginTop: 14, padding: "12px 14px" }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ fontSize: 12.5, color: "var(--steel)" }}>
            알림 메일 {settings?.notify_email
              ? <b style={{ color: "var(--ink)" }}>{settings.notify_email}</b>
              : "안 받는 중"}
          </span>
          <span style={{ flex: 1 }} />
          <button className="btn btn-ghost btn-sm" onClick={() => setSettingsOpen(!settingsOpen)}>
            {settingsOpen ? "설정 접기" : "설정"}
          </button>
        </div>
        {settingsOpen && settings && (
          <div style={{ display: "grid", gap: 12, marginTop: 14,
            paddingTop: 14, borderTop: "1px solid var(--line)" }}>
            <div className="field">
              <label className="label">새 신청 알림 받을 메일</label>
              <input className="input" style={{ maxWidth: 360 }}
                value={settings.notify_email} placeholder="비우면 알림을 안 보냅니다"
                onChange={(e) => setSettings({ ...settings, notify_email: e.target.value })} />
            </div>
            <div className="field">
              <label className="label">안내할 입금 계좌</label>
              <input className="input" style={{ maxWidth: 460 }} value={settings.bank}
                onChange={(e) => setSettings({ ...settings, bank: e.target.value })} />
              <p style={{ fontSize: 12, color: "var(--steel)", margin: "6px 0 0" }}>
                신청을 마친 화면에 이 문구가 그대로 나갑니다.
              </p>
            </div>
            <div>
              <button className="btn btn-sm" onClick={async () => {
                try {
                  setSettings(await api.saveApplicationSettings(settings));
                  setMsg(okMsg("저장했습니다."));
                } catch (e) { setMsg(errMsg(e.message)); }
              }}>설정 저장</button>
            </div>
          </div>
        )}
      </div>

      {msg && <div className={`notice notice-${msg.type}`} style={{ marginTop: 12 }}>{msg.text}</div>}

      {/* 거르기 */}
      <div style={{ display: "flex", gap: 8, alignItems: "center",
        flexWrap: "wrap", marginTop: 16 }}>
        <select className="select" style={{ width: "auto" }}
          value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">전체 종류</option>
          {(data?.kinds || []).map((k) => (
            <option key={k.key} value={k.key}>
              {k.label} ({data.counts?.[k.key] ?? 0})
            </option>
          ))}
        </select>
        <select className="select" style={{ width: "auto" }}
          value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">전체 상태</option>
          {(data?.statuses || []).map((s) => (
            <option key={s.key} value={s.key}>{s.label}</option>
          ))}
        </select>
        <span style={{ flex: 1 }} />
        <button className="btn btn-ghost btn-sm" disabled={csvBusy}
          onClick={async () => {
            setCsvBusy(true);
            try { await api.downloadApplicationsCsv(kind); }
            catch (e) { setMsg(errMsg(e.message)); }
            finally { setCsvBusy(false); }
          }}>
          {csvBusy ? "만드는 중…" : "엑셀로 받기"}
        </button>
      </div>

      {!data ? (
        <p style={{ fontSize: 13.5, color: "var(--steel)", marginTop: 18 }}>불러오는 중…</p>
      ) : items.length === 0 ? (
        <div className="empty" style={{ marginTop: 18 }}>
          <p>아직 신청이 없습니다.</p>
        </div>
      ) : (
        <div style={{ display: "grid", gap: 8, marginTop: 14 }}>
          {items.map((a) => (
            <div key={a.id} className="panel" style={{ padding: 0, overflow: "hidden" }}>
              <div style={{ display: "flex", gap: 10, alignItems: "center",
                flexWrap: "wrap", padding: 12 }}>
                <span className={`badge ${STATUS_CLASS[a.status] || "badge-dorm"}`}>
                  {a.status_label}
                </span>
                <div style={{ flex: "1 1 200px", minWidth: 0 }}>
                  <strong style={{ fontSize: 14.5 }}>{a.name}</strong>
                  <span style={{ color: "var(--steel)", fontSize: 13 }}> · {a.kind_label}</span>
                  <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 2 }}>
                    {a.phone}
                    {a.email && <> · {a.email}</>}
                    {a.amount > 0 && <> · {a.amount.toLocaleString()}원</>}
                    {" · "}{fmtWhen(a.created_at)}
                  </div>
                </div>
                <select className="select" style={{ width: "auto" }}
                  value={a.status} onChange={(e) => patch(a.id, { status: e.target.value })}>
                  {(data.statuses || []).map((s) => (
                    <option key={s.key} value={s.key}>{s.label}</option>
                  ))}
                </select>
                <button className="btn btn-ghost btn-sm"
                  onClick={() => setOpenId(openId === a.id ? null : a.id)}>
                  {openId === a.id ? "닫기" : "자세히"}
                </button>
              </div>

              {openId === a.id && (
                <div style={{ padding: "12px 14px 14px", borderTop: "1px solid var(--line)",
                  display: "grid", gap: 12, fontSize: 13.5 }}>
                  {/* 연락처는 한 곳에 모아 둔다. 응대할 때 제일 먼저 보는 값이라
                    * 다른 항목 사이에 흩어 놓으면 매번 눈으로 찾게 된다.
                    * 전화·메일은 눌러서 바로 걸거나 쓸 수 있게 한다. */}
                  <dl style={{
                    display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 14px",
                    margin: 0, padding: "12px 14px", borderRadius: "var(--radius-sm)",
                    background: "var(--raised)", border: "1px solid var(--line)",
                  }}>
                    <dt style={{ color: "var(--steel)" }}>이름</dt>
                    <dd style={{ margin: 0, fontWeight: 600 }}>{a.name}</dd>
                    <dt style={{ color: "var(--steel)" }}>연락처</dt>
                    <dd style={{ margin: 0, fontWeight: 600 }}>
                      {a.phone
                        ? <a href={`tel:${a.phone.replace(/[^0-9+]/g, "")}`}>{a.phone}</a>
                        : "-"}
                    </dd>
                    <dt style={{ color: "var(--steel)" }}>이메일</dt>
                    <dd style={{ margin: 0, fontWeight: 600 }}>
                      {a.email ? <a href={`mailto:${a.email}`}>{a.email}</a> : "-"}
                    </dd>
                    <dt style={{ color: "var(--steel)" }}>신청 종류</dt>
                    <dd style={{ margin: 0 }}>
                      {a.kind_label}
                      {a.amount > 0 && ` · ${a.amount.toLocaleString()}원`}
                    </dd>
                    <dt style={{ color: "var(--steel)" }}>신청 일시</dt>
                    <dd style={{ margin: 0 }}>{fmtWhen(a.created_at)}</dd>
                    {a.account && (
                      <>
                        {/* 어느 계정에 열리는지. 로그인해서 사는 신청(합격생
                            영상)만 나온다 — 입금 확인이 곧 그 계정을 여는
                            일이라, 누구인지 보이지 않으면 동명이인이나 대신
                            신청한 경우에 엉뚱한 사람이 열린다. */}
                        <dt style={{ color: "var(--steel)" }}>열리는 계정</dt>
                        <dd style={{ margin: 0, fontWeight: 600 }}>
                          {a.account.gone
                            ? <span style={{ color: "var(--color-danger)" }}>
                                탈퇴한 계정입니다 (열어 줄 수 없습니다)
                              </span>
                            : `${a.account.name || "(이름 없음)"} · ${a.account.email}`}
                        </dd>
                      </>
                    )}
                  </dl>

                  <div>
                    <b>신청자 구분</b> {a.applicant || "-"}
                    {"  ·  "}
                    <b>알게 된 경로</b> {a.found_path || "-"}
                    {a.found_etc && ` (${a.found_etc})`}
                  </div>
                  {Object.keys(a.extra || {}).length > 0 && (
                    <div>
                      {Object.entries(a.extra).map(([k, v]) => (
                        <div key={k}><b>{k}</b> {String(v)}</div>
                      ))}
                    </div>
                  )}
                  <div>
                    <b>문의 및 요청사항</b>
                    <p style={{ whiteSpace: "pre-wrap", margin: "4px 0 0",
                      color: a.message ? "inherit" : "var(--steel)" }}>
                      {a.message || "(없음)"}
                    </p>
                  </div>
                  <div className="field">
                    <label className="label">메모 <span style={{ fontWeight: "normal", color: "var(--steel)" }}>(관리자만 봅니다)</span></label>
                    <textarea className="textarea" rows={2} defaultValue={a.admin_note}
                      placeholder="통화 내용, 잡은 일정 등"
                      onBlur={(e) => {
                        if (e.target.value !== a.admin_note) {
                          patch(a.id, { admin_note: e.target.value });
                        }
                      }} />
                  </div>
                  <div style={{
                    display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
                    paddingTop: 10, borderTop: "1px solid var(--line)",
                  }}>
                    <button className="btn btn-ghost btn-sm"
                      style={{ color: "var(--color-attention)",
                        borderColor: "var(--color-attention)" }}
                      onClick={() => remove(a)}>
                      이 신청 삭제
                    </button>
                    <span style={{ fontSize: 12, color: "var(--steel)" }}>
                      되돌릴 수 없습니다. 처리가 끝난 건은 삭제 대신
                      상태를 <b>완료</b>로 두면 기록이 남습니다.
                    </span>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
