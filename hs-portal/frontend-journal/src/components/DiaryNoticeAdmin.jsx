import { Fragment, useEffect, useState } from "react";
import { api } from "../api";

/** 기록해 공지 관리(관리자). UDJ 공지와 별개다.
 *  게시판에 올리고, 원하면 기록해 학교 계정(중·고)의 공지 알림 이메일로 알린다.
 *  알림을 보내는 게시는 대상 수를 먼저 보여 주고 확인받는다. 실패한 메일만 다시 보낸다. */
const CATEGORIES = [["notice", "공지"], ["update", "업데이트"], ["maintenance", "점검"],
  ["event", "이벤트"], ["important", "중요"]];
const LEVELS = [["all", "전체 학교"], ["high", "고등학교"], ["middle", "중학교"]];
const CAT = Object.fromEntries(CATEGORIES);
const d10 = (v) => (v ? String(v).slice(0, 10) : "");

export default function DiaryNoticeAdmin() {
  const blank = { title: "", body: "", category: "notice", is_important: false,
    start_date: "", end_date: "", target_level: "all", email_enabled: false };
  const [form, setForm] = useState(blank);
  const [editing, setEditing] = useState(null);
  const [list, setList] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [logsOf, setLogsOf] = useState(null);

  const load = () => api.adminNotices().then(setList).catch((e) => setMsg({ type: "error", text: e.message }));
  useEffect(() => { load(); }, []);
  const set = (p) => setForm((f) => ({ ...f, ...p }));
  const body = () => {
    const b = { ...form, starts_at: form.start_date ? `${form.start_date}T00:00:00` : null,
      ends_at: form.end_date ? `${form.end_date}T23:59:59` : null };
    delete b.start_date; delete b.end_date;
    return b;
  };
  const reset = () => { setForm(blank); setEditing(null); setConfirmText(""); };

  const save = async (publish) => {
    if (!form.title.trim()) return setMsg({ type: "error", text: "제목을 입력해주세요." });
    if (form.start_date && form.end_date && form.end_date < form.start_date)
      return setMsg({ type: "error", text: "종료일은 시작일보다 뒤여야 합니다." });
    setMsg(null);
    if (publish && form.email_enabled && form.category !== "event" && !confirmText) {
      try {
        const p = await api.previewAdminNotice(body());
        return setConfirmText(`학교 계정 ${p.email}곳에 공지 알림 이메일이 발송됩니다.`
          + (p.opted_out ? ` · 알림을 끈 학교 ${p.opted_out}곳 제외` : "")
          + (p.inactive ? ` · 정지된 계정 ${p.inactive}곳 제외` : ""));
      } catch (e) { return setMsg({ type: "error", text: e.message }); }
    }
    setConfirmText("");
    setBusy(true);
    try {
      const b = { ...body(), publish };
      const r = editing ? await api.updateAdminNotice(editing, b) : await api.createAdminNotice(b);
      setMsg({ type: "ok", text: publish ? `게시했습니다.${r.queued ? ` 메일 ${r.queued}건 발송 중.` : ""}` : "임시저장했습니다." });
      reset(); load();
    } catch (e) { setMsg({ type: "error", text: e.message }); } finally { setBusy(false); }
  };

  const edit = (n) => {
    setEditing(n.id);
    setForm({ title: n.title, body: n.body || "", category: n.category, is_important: n.is_important,
      start_date: d10(n.starts_at), end_date: d10(n.ends_at), target_level: n.target_level || "all",
      email_enabled: n.email_enabled });
    setConfirmText(""); setMsg(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const act = async (fn, text) => {
    try { await fn(); setMsg({ type: "ok", text }); load(); }
    catch (e) { setMsg({ type: "error", text: e.message }); }
  };

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="panel">
        <h3>{editing ? "공지 고치기" : "기록해 공지 작성"}</h3>
        <p className="meta" style={{ margin: "0 0 12px", lineHeight: 1.7 }}>
          기록해 공지사항 화면에 올립니다(UDJ 공지와 별개). &lsquo;학교 계정 이메일 알림&rsquo;을 켜면 기록해 학교 계정이
          정해 둔 공지 알림 이메일로도 보냅니다. 학생·선생님 개인 계정에는 보내지 않습니다.
        </p>
        {msg && <div className={`notice notice-${msg.type}`} style={{ marginBottom: 12 }}>{msg.text}</div>}
        <div className="row" style={{ gap: 10, alignItems: "flex-end" }}>
          <label className="field" style={{ marginBottom: 0 }}>
            <span className="label">유형</span>
            <select className="input" value={form.category} onChange={(e) => set({ category: e.target.value })}>
              {CATEGORIES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </label>
          <label className="field" style={{ marginBottom: 0 }}>
            <span className="label">알림 대상 학교</span>
            <select className="input" value={form.target_level} onChange={(e) => set({ target_level: e.target.value })}>
              {LEVELS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </label>
        </div>
        <label className="field" style={{ marginTop: 10 }}>
          <span className="label">제목</span>
          <input className="input" value={form.title} maxLength={150} onChange={(e) => set({ title: e.target.value })} />
        </label>
        <label className="field">
          <span className="label">내용</span>
          <textarea className="input" rows={6} value={form.body} onChange={(e) => set({ body: e.target.value })} />
        </label>
        <div className="row" style={{ gap: 10 }}>
          <label className="field" style={{ marginBottom: 0 }}>
            <span className="label">게시 시작일 (비우면 즉시)</span>
            <input className="input" type="date" value={form.start_date} onChange={(e) => set({ start_date: e.target.value })} />
          </label>
          <label className="field" style={{ marginBottom: 0 }}>
            <span className="label">게시 종료일 (비우면 무기한)</span>
            <input className="input" type="date" value={form.end_date} onChange={(e) => set({ end_date: e.target.value })} />
          </label>
        </div>
        <div className="row" style={{ gap: 16, marginTop: 12 }}>
          <label className="row" style={{ gap: 6 }}>
            <input type="checkbox" checked={form.is_important} onChange={(e) => set({ is_important: e.target.checked })} />
            중요 공지(목록 맨 위)
          </label>
          <label className="row" style={{ gap: 6 }}>
            <input type="checkbox" checked={form.email_enabled && form.category !== "event"}
              disabled={form.category === "event"} onChange={(e) => set({ email_enabled: e.target.checked })} />
            학교 계정 이메일 알림
          </label>
        </div>
        {form.category === "event" && (
          <p className="meta" style={{ margin: "6px 0 0" }}>
            이벤트 공지는 광고성 정보가 될 수 있어 이메일로 보내지 않고 공지사항에만 올립니다.
          </p>
        )}
        {confirmText ? (
          <div className="notice" style={{ marginTop: 14 }}>
            <b>{confirmText}</b>
            <div className="row" style={{ gap: 8, marginTop: 10 }}>
              <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => save(true)}>게시하고 보내기</button>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirmText("")}>취소</button>
            </div>
          </div>
        ) : (
          <div className="row" style={{ gap: 8, marginTop: 14 }}>
            <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => save(true)}>
              {busy ? "처리 중…" : editing ? "저장하고 게시" : "게시"}
            </button>
            <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => save(false)}>임시저장</button>
            {editing && <button type="button" className="btn btn-ghost btn-sm" onClick={reset}>새로 쓰기</button>}
          </div>
        )}
      </div>

      <div className="panel">
        <h3>공지 목록 {list && `(${list.length})`}</h3>
        {!list ? <p className="meta">불러오는 중…</p> : list.length === 0 ? <p className="meta">등록된 공지가 없습니다.</p> : (
          <div style={{ overflowX: "auto" }}>
            <table className="table">
              <thead><tr><th>제목</th><th>유형</th><th>상태</th><th>작성일</th><th>게시일</th><th>알림</th><th /></tr></thead>
              <tbody>
                {list.map((n) => {
                  const s = n.send?.email || {};
                  return (
                    <Fragment key={n.id}>
                      <tr>
                        <td>{n.is_important && <span className="badge badge-danger" style={{ marginRight: 4 }}>중요</span>}<b>{n.title}</b></td>
                        <td>{CAT[n.category] || "공지"}</td>
                        <td>{n.status === "published" ? <span className="badge badge-done">게시</span> : <span className="badge">임시저장</span>}</td>
                        <td>{d10(n.created_at)}</td>
                        <td>{n.status === "published" ? d10(n.published_at) : "-"}</td>
                        <td>{!n.email_enabled ? "보내지 않음"
                          : `메일 ${s.sent || 0}${s.failed ? `·실패 ${s.failed}` : ""}${(s.pending || 0) + (s.sending || 0) ? `·대기 ${(s.pending || 0) + (s.sending || 0)}` : ""}`}</td>
                        <td style={{ whiteSpace: "nowrap" }}>
                          <button type="button" className="btn btn-ghost btn-sm" onClick={() => edit(n)}>수정</button>
                          {n.status === "published"
                            ? <button type="button" className="btn btn-ghost btn-sm" onClick={() => act(() => api.unpublishAdminNotice(n.id), "게시를 취소했습니다.")}>게시 취소</button>
                            : <button type="button" className="btn btn-ghost btn-sm" onClick={() => act(() => api.publishAdminNotice(n.id), "게시했습니다.")}>게시</button>}
                          {n.email_enabled && n.status === "published" && (
                            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setLogsOf(logsOf === n.id ? null : n.id)}>발송 결과</button>
                          )}
                          <button type="button" className="btn btn-ghost btn-sm"
                            onClick={() => window.confirm(`«${n.title}»을(를) 삭제할까요?`) && act(() => api.deleteAdminNotice(n.id), "삭제했습니다.")}>삭제</button>
                        </td>
                      </tr>
                      {logsOf === n.id && <tr><td colSpan={7}><Logs id={n.id} onChange={load} /></td></tr>}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function Logs({ id, onChange }) {
  const [rows, setRows] = useState(null);
  const [msg, setMsg] = useState("");
  const load = () => api.adminNoticeLogs(id).then(setRows).catch((e) => setMsg(e.message));
  useEffect(() => { load(); }, [id]);
  const retry = async (fn) => {
    try { await fn(); setMsg("다시 보내는 중입니다."); setTimeout(load, 1500); onChange?.(); }
    catch (e) { setMsg(e.message); }
  };
  if (!rows) return <p className="meta">불러오는 중…</p>;
  const failed = rows.filter((r) => r.status === "failed").length;
  return (
    <div>
      <div className="row" style={{ gap: 8, marginBottom: 6 }}>
        <span className="meta">발송 {rows.length}건 · 실패 {failed}건 {msg && `· ${msg}`}</span>
        <button type="button" className="btn btn-ghost btn-sm" onClick={load}>새로고침</button>
        {failed > 0 && <button type="button" className="btn btn-sm" onClick={() => retry(() => api.retryFailedNotice(id))}>실패 {failed}건 다시 보내기</button>}
      </div>
      <table className="table">
        <thead><tr><th>학교</th><th>받는 곳</th><th>결과</th><th>사유</th><th>시도</th><th /></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{r.school_name || `#${r.school_id}`}</td><td>{r.address}</td>
              <td>{r.status_label}</td><td className="meta">{r.error}</td><td>{r.attempts}</td>
              <td>{r.status === "failed" && <button type="button" className="btn btn-ghost btn-sm" onClick={() => retry(() => api.retryNotificationLog(r.id))}>다시 보내기</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
