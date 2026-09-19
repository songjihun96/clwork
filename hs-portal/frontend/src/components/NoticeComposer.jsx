import { useEffect, useState } from "react";
import { api } from "../api";
import { errMsg, okMsg } from "../toast";

/** 공지 작성·목록 관리. 관리자 전용이다(전체 공지 / 특정 학교 공지).
 *  학교 계정이 직접 쓰던 '선생님 공지'는 없앴다 — 문의 답변이 어차피
 *  포털 계정으로 나가는 것처럼, 학교가 따로 관리할 채널을 늘리지 않는다.
 */
export default function NoticeComposer() {
  const blank = {
    scope: "all", school_id: "", title: "", body: "",
    is_popup: false, is_important: false, start_date: "", end_date: "", image_url: "",
  };

  const [form, setForm] = useState(blank);
  const [list, setList] = useState([]);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [schoolQuery, setSchoolQuery] = useState("");
  const [schools, setSchools] = useState([]);
  const [target, setTarget] = useState(null);
  const [uploading, setUploading] = useState(false);

  const pickImage = async (file) => {
    if (!file) return;
    setUploading(true); setMsg(null);
    try {
      const r = await api.uploadNoticeImage(file);
      setForm((f) => ({ ...f, image_url: r.url }));
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally { setUploading(false); }
  };

  const load = () => api.adminNotices().then(setList).catch(() => {});
  useEffect(() => { load(); }, []);

  const searchSchools = async () => {
    if (schoolQuery.trim().length < 2) return;
    const r = await api.schools({ name: schoolQuery.trim(), size: 8, include_hidden: true });
    setSchools(r.items || []);
  };

  const submit = async () => {
    if (!form.title.trim()) return setMsg(errMsg("제목을 입력해주세요."));
    if (form.scope === "school" && !target) {
      return setMsg(errMsg("대상 학교를 선택해주세요."));
    }
    if (form.start_date && form.end_date && form.end_date < form.start_date) {
      return setMsg(errMsg("종료일은 시작일보다 뒤여야 합니다."));
    }
    setBusy(true); setMsg(null);
    try {
      const body = {
        ...form,
        school_id: target?.id || null,
        starts_at: form.start_date ? `${form.start_date}T00:00:00` : null,
        ends_at: form.end_date ? `${form.end_date}T23:59:59` : null,
      };
      delete body.start_date;
      delete body.end_date;
      await api.createAdminNotice(body);
      setMsg(okMsg("공지를 등록했습니다."));
      setForm(blank); setTarget(null); setSchools([]); setSchoolQuery("");
      load();
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally { setBusy(false); }
  };

  const remove = async (n) => {
    if (!window.confirm(`«${n.title}» 공지를 삭제할까요?`)) return;
    await api.deleteAdminNotice(n.id);
    load();
  };

  const SCOPE_LABEL = { all: "전체 공지", school: "학교 지정", teachers: "선생님 대상" };

  // 노출 기간이 지났거나 아직 시작 전이면 표시해 준다
  const periodState = (n) => {
    const now = new Date();
    if (n.starts_at && new Date(n.starts_at) > now) return "노출 예정";
    if (n.ends_at && new Date(n.ends_at) < now) return "노출 종료";
    return null;
  };

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="panel">
        <h3>공지 작성</h3>
        <p style={{ fontSize: 13, color: "var(--steel)", marginTop: -4 }}>
          전체 공지는 모든 방문자에게, 학교 지정 공지는 해당 학교 계정과 선생님에게 보입니다.
        </p>
        {msg && <div className={`notice notice-${msg.type}`} style={{ marginBottom: 12 }}>{msg.text}</div>}

        <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
          {["all", "school"].map((v) => (
            <button key={v} className={`btn btn-sm ${form.scope === v ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setForm({ ...form, scope: v })}>
              {SCOPE_LABEL[v]}
            </button>
          ))}
        </div>

        {form.scope === "school" && (
          <div style={{ marginBottom: 12 }}>
            <label className="label">대상 학교</label>
            {target ? (
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 4 }}>
                <b>{target.name}</b>
                <button className="btn btn-ghost btn-sm" onClick={() => setTarget(null)}>변경</button>
              </div>
            ) : (
              <>
                <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
                  <input className="input" value={schoolQuery} placeholder="학교명 검색"
                    onChange={(e) => setSchoolQuery(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && searchSchools()} />
                  <button className="btn btn-ghost btn-sm" onClick={searchSchools}>검색</button>
                </div>
                {schools.length > 0 && (
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
                    {schools.map((s) => (
                      <button key={s.id} className="btn btn-ghost btn-sm" onClick={() => { setTarget(s); setSchools([]); }}>
                        {s.name}
                      </button>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        )}

        <div className="field">
          <label className="label">제목</label>
          <input className="input" value={form.title} maxLength={150}
            onChange={(e) => setForm({ ...form, title: e.target.value })} />
        </div>
        <div className="field" style={{ marginTop: 10 }}>
          <label className="label">내용 (이미지만 올릴 경우 비워도 됩니다)</label>
          <textarea className="textarea" rows={4} value={form.body}
            onChange={(e) => setForm({ ...form, body: e.target.value })} />
        </div>

        <div className="field" style={{ marginTop: 10 }}>
          <label className="label">이미지 첨부 (선택 · 5MB 이하)</label>
          {form.image_url ? (
            <div style={{ marginTop: 6 }}>
              <img src={form.image_url} alt="첨부 이미지"
                style={{ maxWidth: 260, width: "100%", borderRadius: 8, border: "1px solid var(--line)", display: "block" }} />
              <button className="btn btn-ghost btn-sm" style={{ marginTop: 6 }}
                onClick={() => setForm({ ...form, image_url: "" })}>
                이미지 제거
              </button>
            </div>
          ) : (
            <label className="btn btn-ghost btn-sm" style={{ cursor: "pointer", display: "inline-block", marginTop: 4 }}>
              {uploading ? "올리는 중…" : "🖼 이미지 선택"}
              <input type="file" accept="image/png,image/jpeg,image/gif,image/webp"
                style={{ display: "none" }}
                onChange={(e) => { pickImage(e.target.files?.[0]); e.target.value = ""; }} />
            </label>
          )}
        </div>

        <div style={{ display: "flex", gap: 12, marginTop: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
          <div className="field">
            <label className="label">노출 시작일 (비우면 즉시)</label>
            <input className="input" type="date" value={form.start_date}
              onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
          </div>
          <div className="field">
            <label className="label">노출 종료일 (비우면 무기한)</label>
            <input className="input" type="date" value={form.end_date}
              onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
          </div>
          {form.end_date && form.start_date && form.end_date < form.start_date && (
            <span className="label" style={{ color: "var(--alert)" }}>
              종료일이 시작일보다 빠릅니다.
            </span>
          )}
        </div>

        <div style={{ display: "flex", gap: 16, marginTop: 10, flexWrap: "wrap" }}>
          <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13.5 }}>
            <input type="checkbox" checked={form.is_important}
              onChange={(e) => setForm({ ...form, is_important: e.target.checked })} />
            중요 표시
          </label>
          {form.scope === "all" && (
            <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13.5 }}>
              <input type="checkbox" checked={form.is_popup}
                onChange={(e) => setForm({ ...form, is_popup: e.target.checked })} />
              접속 시 팝업으로 띄우기
            </label>
          )}
        </div>

        <button className="btn btn-primary btn-sm" onClick={submit} disabled={busy} style={{ marginTop: 14 }}>
          {busy ? "등록 중…" : "공지 등록"}
        </button>
      </div>

      <div className="panel">
        <h3>등록된 공지 ({list.length})</h3>
        {list.length === 0 ? (
          <p style={{ fontSize: 13.5, color: "var(--steel)", margin: 0 }}>등록된 공지가 없습니다.</p>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {list.map((n) => (
              <div key={n.id} className="event-row" style={{ alignItems: "flex-start" }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                    <span className="badge">{SCOPE_LABEL[n.scope]}</span>
                    {n.school_name && <span className="label">{n.school_name}</span>}
                    {n.is_important && <span className="badge badge-important">중요</span>}
                    {n.is_popup && <span className="badge badge-dorm">팝업</span>}
                    <b style={{ fontSize: 14 }}>{n.title}</b>
                  </div>
                  {n.image_url && (
                    <img src={n.image_url} alt=""
                      style={{ width: 90, borderRadius: 6, border: "1px solid var(--line)", margin: "5px 0 0", display: "block" }} />
                  )}
                  {n.body && (
                    <p style={{ margin: "3px 0 0", fontSize: 12.5, color: "var(--steel)", whiteSpace: "pre-wrap" }}>
                      {n.body}
                    </p>
                  )}
                  <span className="label" style={{ color: "var(--steel-light)" }}>
                    {n.created_at?.slice(0, 10)}{n.author_name ? ` · ${n.author_name}` : ""}
                    {(n.starts_at || n.ends_at) && (
                      <> · 노출 {n.starts_at?.slice(0, 10) || "즉시"} ~ {n.ends_at?.slice(0, 10) || "무기한"}</>
                    )}
                  </span>
                  {periodState(n) && (
                    <span className="badge" style={{ marginTop: 4, display: "inline-block" }}>
                      {periodState(n)}
                    </span>
                  )}
                </div>
                <button className="btn btn-ghost btn-sm" onClick={() => remove(n)}>삭제</button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
