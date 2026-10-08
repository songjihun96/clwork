import { Fragment, useEffect, useState } from "react";
import { api } from "../api";
import { errMsg, okMsg } from "../toast";

/** 공지 관리(관리자). kind 로 두 가지를 쓴다.
 *
 *  board      : 공지사항 게시판. 전체 공지 / 학교 지정 공지, 팝업, 학교 계정 메일 알림.
 *  vocational : 우리동네직업계고 공지. 직업계고 담당 선생님에게 메일·문자.
 *
 *  게시 버튼을 누르면 먼저 몇 곳에 나가는지 보여 주고 확인을 받는다.
 *  게시한 뒤에는 학교별 발송 결과(성공·실패·보낼 수 없음)를 보고 실패만 다시 보낸다.
 */
const CATEGORIES = [
  ["notice", "공지"], ["update", "업데이트"], ["maintenance", "점검"],
  ["event", "이벤트"], ["important", "중요"],
];
const LEVELS = [["all", "전체 학교"], ["high", "고등학교"], ["middle", "중학교"]];
const CAT_LABEL = Object.fromEntries(CATEGORIES);

const toDate = (v) => (v ? String(v).slice(0, 10) : "");

export default function NoticeManager({ kind = "board" }) {
  const voc = kind === "vocational";
  const blank = {
    kind, scope: "all", title: "", body: "", category: "notice",
    is_popup: false, is_important: false, start_date: "", end_date: "", image_url: "",
    target_level: "all", email_enabled: voc, sms_enabled: voc,
  };
  const [form, setForm] = useState(blank);
  const [editing, setEditing] = useState(null);   // 고치는 공지 id
  const [target, setTarget] = useState(null);     // 학교 지정 공지의 학교
  const [schoolQuery, setSchoolQuery] = useState("");
  const [schools, setSchools] = useState([]);
  const [list, setList] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [confirm, setConfirm] = useState(null);   // { preview, publish }
  const [logsOf, setLogsOf] = useState(null);     // 발송 결과를 펼친 공지

  const load = () => api.adminNotices(kind).then(setList).catch((e) => setMsg(errMsg(e.message)));
  useEffect(() => { load(); }, [kind]);
  const set = (patch) => setForm((f) => ({ ...f, ...patch }));

  const body = () => {
    const b = {
      ...form,
      school_id: form.scope === "school" ? target?.id || null : null,
      starts_at: form.start_date ? `${form.start_date}T00:00:00` : null,
      ends_at: form.end_date ? `${form.end_date}T23:59:59` : null,
    };
    delete b.start_date; delete b.end_date;
    return b;
  };

  const check = () => {
    if (!form.title.trim()) return "제목을 입력해주세요.";
    if (form.scope === "school" && !target) return "대상 학교를 선택해주세요.";
    if (form.start_date && form.end_date && form.end_date < form.start_date) return "종료일은 시작일보다 뒤여야 합니다.";
    if (voc && form.category !== "event" && !form.email_enabled && !form.sms_enabled) return "이메일·문자 중 하나는 켜야 담당 선생님에게 전달됩니다.";
    return "";
  };

  const noSend = form.category === "event";   // 이벤트: 게시판만(광고성 정보 발송 방지)

  const save = async (publish) => {
    const why = check();
    if (why) return setMsg(errMsg(why));
    setMsg(null);
    // 알림을 보내는 게시는 대상 수를 먼저 보여 주고 확인받는다.
    if (publish && !noSend && (form.email_enabled || form.sms_enabled) && !confirm) {
      try {
        const p = await api.previewAdminNotice(body());
        return setConfirm({ preview: p });
      } catch (e) { return setMsg(errMsg(e.message)); }
    }
    setConfirm(null);
    setBusy(true);
    try {
      const b = { ...body(), publish };
      const r = editing ? await api.updateAdminNotice(editing, b) : await api.createAdminNotice(b);
      setMsg(okMsg(publish
        ? `게시했습니다.${r.queued ? ` 알림 ${r.queued}건을 보내는 중입니다(결과는 목록의 '발송 결과').` : ""}`
        : "임시저장했습니다."));
      reset();
      load();
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally { setBusy(false); }
  };

  const reset = () => { setForm(blank); setEditing(null); setTarget(null); setSchools([]); setSchoolQuery(""); };

  const edit = (n) => {
    setEditing(n.id);
    setForm({
      kind, scope: n.scope || "all", title: n.title, body: n.body || "", category: n.category || "notice",
      is_popup: n.is_popup, is_important: n.is_important, start_date: toDate(n.starts_at),
      end_date: toDate(n.ends_at), image_url: n.image_url || "", target_level: n.target_level || "all",
      email_enabled: n.email_enabled, sms_enabled: n.sms_enabled,
    });
    setTarget(n.school_id ? { id: n.school_id, name: n.school_name } : null);
    setMsg(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const act = async (fn, ok) => {
    try { const r = await fn(); setMsg(okMsg(typeof ok === "function" ? ok(r) : ok)); load(); }
    catch (e) { setMsg(errMsg(e.message)); }
  };

  const publishSaved = async (n) => {
    try {
      const p = await api.previewAdminNoticeSaved(n.id);
      const total = p.email + (p.sms || 0);
      if (total > 0 && !window.confirm(previewText(p, voc) + "\n\n게시할까요?")) return;
    } catch { /* 미리보기 실패해도 게시는 할 수 있게 */ }
    act(() => api.publishAdminNotice(n.id), (r) => `게시했습니다.${r.queued ? ` 알림 ${r.queued}건 발송 중.` : ""}`);
  };

  const searchSchools = async () => {
    if (schoolQuery.trim().length < 2) return;
    const r = await api.schools({ name: schoolQuery.trim(), size: 8, include_hidden: true });
    setSchools(r.items || []);
  };

  const pickImage = async (file) => {
    if (!file) return;
    setUploading(true);
    try { const r = await api.uploadNoticeImage(file); set({ image_url: r.url }); }
    catch (e) { setMsg(errMsg(e.message)); }
    finally { setUploading(false); }
  };

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="panel">
        <h3>{editing ? "공지 고치기" : voc ? "우리동네직업계고 공지 작성" : "공지사항 작성"}</h3>
        <p style={{ fontSize: 13, color: "var(--steel)", marginTop: -4, lineHeight: 1.7 }}>
          {voc
            ? "노출 중인 직업계고(고등학교)마다 등록된 우리동네직업계고 담당 선생님에게 이메일·문자로 보냅니다. 중학교는 대상이 아닙니다. 담당 선생님은 학교 관리 탭에서 학교를 골라 등록합니다."
            : "공지사항 게시판에 올립니다. '학교 계정 이메일 알림'을 켜면 중·고 학교 계정이 정해 둔 공지 알림 이메일로도 알립니다(학생·개인 계정에는 보내지 않습니다)."}
        </p>
        {msg && <div className={`notice notice-${msg.type}`} style={{ marginBottom: 12 }}>{msg.text}</div>}

        {!voc && (
          <div style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap" }}>
            {[["all", "전체 공지"], ["school", "학교 지정"]].map(([v, label]) => (
              <button key={v} type="button" className={`btn btn-sm ${form.scope === v ? "btn-primary" : "btn-ghost"}`}
                onClick={() => set({ scope: v })}>{label}</button>
            ))}
          </div>
        )}

        {!voc && form.scope === "school" && (
          <div style={{ marginBottom: 12 }}>
            <label className="label">대상 학교</label>
            {target ? (
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 4 }}>
                <b>{target.name}</b>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setTarget(null)}>변경</button>
              </div>
            ) : (
              <>
                <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
                  <input className="input" value={schoolQuery} placeholder="학교명 검색"
                    onChange={(e) => setSchoolQuery(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && searchSchools()} />
                  <button type="button" className="btn btn-ghost btn-sm" onClick={searchSchools}>검색</button>
                </div>
                {schools.length > 0 && (
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
                    {schools.map((s) => (
                      <button key={s.id} type="button" className="btn btn-ghost btn-sm"
                        onClick={() => { setTarget(s); setSchools([]); }}>{s.name}</button>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        )}

        <div className="nm-grid">
          <div className="field">
            <label className="label" htmlFor={`nm-cat-${kind}`}>유형</label>
            <select id={`nm-cat-${kind}`} className="input" value={form.category}
              onChange={(e) => set({ category: e.target.value })}>
              {CATEGORIES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </div>
          {!voc && (
            <div className="field">
              <label className="label" htmlFor={`nm-lv-${kind}`}>알림 대상 학교</label>
              <select id={`nm-lv-${kind}`} className="input" value={form.target_level}
                onChange={(e) => set({ target_level: e.target.value })}>
                {LEVELS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </div>
          )}
        </div>

        <div className="field" style={{ marginTop: 10 }}>
          <label className="label" htmlFor={`nm-title-${kind}`}>제목</label>
          <input id={`nm-title-${kind}`} className="input" value={form.title} maxLength={150}
            onChange={(e) => set({ title: e.target.value })} />
        </div>
        <div className="field" style={{ marginTop: 10 }}>
          <label className="label" htmlFor={`nm-body-${kind}`}>내용</label>
          <textarea id={`nm-body-${kind}`} className="textarea" rows={6} value={form.body}
            onChange={(e) => set({ body: e.target.value })} />
        </div>

        {!voc && (
          <div className="field" style={{ marginTop: 10 }}>
            <label className="label">이미지 첨부 (선택 · 5MB 이하)</label>
            {form.image_url ? (
              <div style={{ marginTop: 6 }}>
                <img src={form.image_url} alt="첨부 이미지"
                  style={{ maxWidth: 260, width: "100%", borderRadius: 8, border: "1px solid var(--line)", display: "block" }} />
                <button type="button" className="btn btn-ghost btn-sm" style={{ marginTop: 6 }}
                  onClick={() => set({ image_url: "" })}>이미지 제거</button>
              </div>
            ) : (
              <label className="btn btn-ghost btn-sm" style={{ cursor: "pointer", marginTop: 4 }}>
                {uploading ? "올리는 중…" : "🖼 이미지 선택"}
                <input type="file" accept="image/png,image/jpeg,image/gif,image/webp" style={{ display: "none" }}
                  onChange={(e) => { pickImage(e.target.files?.[0]); e.target.value = ""; }} />
              </label>
            )}
          </div>
        )}

        <div className="nm-grid" style={{ marginTop: 10 }}>
          <div className="field">
            <label className="label">게시 시작일 (비우면 즉시)</label>
            <input className="input" type="date" value={form.start_date}
              onChange={(e) => set({ start_date: e.target.value })} />
          </div>
          <div className="field">
            <label className="label">게시 종료일 (비우면 무기한)</label>
            <input className="input" type="date" value={form.end_date}
              onChange={(e) => set({ end_date: e.target.value })} />
          </div>
        </div>

        <div className="nm-checks">
          <label><input type="checkbox" checked={form.is_important}
            onChange={(e) => set({ is_important: e.target.checked })} /> 중요 공지(목록 맨 위)</label>
          {!voc && form.scope === "all" && (
            <label><input type="checkbox" checked={form.is_popup}
              onChange={(e) => set({ is_popup: e.target.checked })} /> 접속 시 팝업으로 띄우기</label>
          )}
          <label><input type="checkbox" checked={form.email_enabled && !noSend} disabled={noSend}
            onChange={(e) => set({ email_enabled: e.target.checked })} />
            {voc ? " 담당 선생님 이메일 발송" : " 학교 계정 이메일 알림"}</label>
          {voc && (
            <label><input type="checkbox" checked={form.sms_enabled && !noSend} disabled={noSend}
              onChange={(e) => set({ sms_enabled: e.target.checked })} /> 담당 선생님 문자 발송</label>
          )}
        </div>
        {noSend && (
          <p className="adm-note" style={{ marginTop: 6 }}>
            이벤트 공지는 광고성 정보가 될 수 있어 이메일·문자로 보내지 않고 게시판에만 올립니다.
          </p>
        )}
        {voc && !noSend && (
          <p className="adm-note" style={{ marginTop: 6 }}>
            공지 수신에 동의한 담당 선생님에게만 보냅니다. 동의가 없는 담당자는 &lsquo;수신 동의 없음&rsquo;으로 기록만 남습니다.
          </p>
        )}

        {confirm && (
          <div className="notice nm-confirm" role="alertdialog" aria-label="발송 확인">
            <b>{previewText(confirm.preview, voc)}</b>
            <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
              <button type="button" className="btn btn-signal btn-sm" disabled={busy} onClick={() => save(true)}>
                게시하고 보내기
              </button>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirm(null)}>취소</button>
            </div>
          </div>
        )}

        {!confirm && (
          <div style={{ display: "flex", gap: 8, marginTop: 14, flexWrap: "wrap" }}>
            <button type="button" className="btn btn-primary btn-sm" onClick={() => save(true)} disabled={busy}>
              {busy ? "처리 중…" : editing ? "저장하고 게시" : "게시"}
            </button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => save(false)} disabled={busy}>
              임시저장
            </button>
            {editing && <button type="button" className="btn btn-ghost btn-sm" onClick={reset}>새로 쓰기</button>}
          </div>
        )}
      </div>

      <div className="panel">
        <h3>{voc ? "보낸 직업계고 공지" : "공지 목록"} {list && `(${list.length})`}</h3>
        {!list ? <p className="label">불러오는 중…</p> : list.length === 0 ? (
          <p style={{ fontSize: 13.5, color: "var(--steel)", margin: 0 }}>등록된 공지가 없습니다.</p>
        ) : (
          <div className="nm-table-wrap">
            <table className="table nm-table">
              <thead>
                <tr><th>제목</th><th>유형</th><th>상태</th><th>작성자</th><th>작성일</th><th>게시일</th><th>알림</th><th /></tr>
              </thead>
              <tbody>
                {list.map((n) => (
                  <Fragment key={n.id}>
                    <tr>
                      <td>
                        {n.is_important && <span className="badge badge-important" style={{ marginRight: 4 }}>중요</span>}
                        {n.scope === "school" && <span className="badge" style={{ marginRight: 4 }}>{n.school_name}</span>}
                        <b>{n.title}</b>
                      </td>
                      <td>{CAT_LABEL[n.category] || "공지"}</td>
                      <td>{n.status === "published" ? <span className="badge badge-done">게시</span> : <span className="badge">임시저장</span>}</td>
                      <td>{n.author_name || "-"}</td>
                      <td>{toDate(n.created_at)}</td>
                      <td>{n.status === "published" ? toDate(n.published_at) : "-"}</td>
                      <td style={{ whiteSpace: "nowrap" }}>{sendText(n)}</td>
                      <td style={{ whiteSpace: "nowrap" }}>
                        <button type="button" className="btn btn-ghost btn-sm" onClick={() => edit(n)}>수정</button>
                        {n.status === "published" ? (
                          <button type="button" className="btn btn-ghost btn-sm"
                            onClick={() => act(() => api.unpublishAdminNotice(n.id), "게시를 취소했습니다. 아직 안 나간 알림은 취소됩니다.")}>게시 취소</button>
                        ) : (
                          <button type="button" className="btn btn-ghost btn-sm" onClick={() => publishSaved(n)}>게시</button>
                        )}
                        {(n.email_enabled || n.sms_enabled) && n.status === "published" && (
                          <button type="button" className="btn btn-ghost btn-sm"
                            onClick={() => setLogsOf(logsOf === n.id ? null : n.id)}>발송 결과</button>
                        )}
                        <button type="button" className="btn btn-ghost btn-sm"
                          onClick={() => window.confirm(`«${n.title}» 공지를 삭제할까요? 발송 기록도 함께 지워집니다.`)
                            && act(() => api.deleteAdminNotice(n.id), "삭제했습니다.")}>삭제</button>
                      </td>
                    </tr>
                    {logsOf === n.id && (
                      <tr><td colSpan={8}><SendLogs noticeId={n.id} onChange={load} /></td></tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function previewText(p, voc) {
  if (voc) {
    return `총 ${p.schools}개 학교의 담당 선생님에게 이메일 ${p.email}건 / 문자 ${p.sms}건이 발송됩니다.`
      + (p.email_unreachable || p.sms_unreachable
        ? ` (주소·번호가 없거나 잘못된 ${p.email_unreachable + p.sms_unreachable}건은 보내지 못하고 기록만 남습니다)` : "")
      + (p.inactive ? ` · 비활성 담당자 ${p.inactive}명 제외` : "")
      + (p.no_consent ? ` · 수신 동의 없는 담당자 ${p.no_consent}명 제외` : "");
  }
  return `학교 계정 ${p.email}곳에 공지 알림 이메일이 발송됩니다.`
    + (p.opted_out ? ` · 알림을 끈 학교 ${p.opted_out}곳 제외` : "")
    + (p.inactive ? ` · 정지된 계정 학교 ${p.inactive}곳 제외` : "");
}

function sendText(n) {
  if (!(n.email_enabled || n.sms_enabled)) return <span className="label">보내지 않음</span>;
  const part = (ch, label) => {
    const s = n.send?.[ch];
    if (!s) return null;
    const sent = s.sent || 0, failed = s.failed || 0, wait = (s.pending || 0) + (s.sending || 0);
    return `${label} ${sent}` + (failed ? `·실패 ${failed}` : "") + (wait ? `·대기 ${wait}` : "");
  };
  const parts = [part("email", "메일"), part("sms", "문자")].filter(Boolean);
  return parts.length ? parts.join(" / ") : <span className="label">{n.status === "published" ? "대상 없음" : "게시 전"}</span>;
}

/** 공지 하나의 발송 결과(학교별). 실패한 건만 다시 보낸다. */
function SendLogs({ noticeId, onChange }) {
  const [rows, setRows] = useState(null);
  const [msg, setMsg] = useState(null);
  const load = () => api.adminNoticeLogs(noticeId).then(setRows).catch((e) => setMsg(errMsg(e.message)));
  useEffect(() => { load(); }, [noticeId]);
  const retry = async (fn) => {
    try { await fn(); setMsg(okMsg("다시 보내는 중입니다. 잠시 뒤 새로고침해 보세요.")); setTimeout(load, 1500); onChange?.(); }
    catch (e) { setMsg(errMsg(e.message)); }
  };
  if (!rows) return <p className="label">불러오는 중…</p>;
  const failed = rows.filter((r) => r.status === "failed").length;
  return (
    <div className="nm-logs">
      {msg && <div className={`notice notice-${msg.type}`} style={{ marginBottom: 8 }}>{msg.text}</div>}
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6, flexWrap: "wrap" }}>
        <span className="label">발송 {rows.length}건 · 실패 {failed}건</span>
        <button type="button" className="btn btn-ghost btn-sm" onClick={load}>새로고침</button>
        {failed > 0 && (
          <button type="button" className="btn btn-sm" onClick={() => retry(() => api.retryFailedNotice(noticeId))}>
            실패 {failed}건 다시 보내기
          </button>
        )}
      </div>
      {rows.length === 0 ? <p className="label">발송 대상이 없었습니다.</p> : (
        <table className="table">
          <thead><tr><th>학교</th><th>수단</th><th>받는 곳</th><th>결과</th><th>사유</th><th>시도</th><th /></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.school_name || "-"}</td>
                <td>{r.channel === "sms" ? "문자" : "메일"}</td>
                <td>{r.address || "-"}</td>
                <td><span className={`badge ${r.status === "sent" ? "badge-done" : r.status === "failed" ? "badge-important" : ""}`}>{r.status_label}</span></td>
                <td className="label">{r.error}</td>
                <td>{r.attempts}</td>
                <td>{r.status === "failed" && (
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => retry(() => api.retryNotificationLog(r.id))}>다시 보내기</button>
                )}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
