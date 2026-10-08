import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

/** 학교 홍보 인터뷰 관리.
 *
 * 영상 파일은 <영상 관리>에 롱폼으로 올리고, 여기서는 "어느 학교의 어떤
 * 인터뷰인가"만 묶는다. 영상 관리의 공개/비공개와 상관없이 **회원만** 본다 —
 * 여기 붙이는 순간 그 파일은 공개 주소(/api/media)로는 안 나간다.
 *
 * 촬영 신청은 문의 목록에 "학교 홍보 인터뷰 촬영"으로 들어온다.
 */
const EMPTY = {
  title: "", summary: "", speakers: "", school_id: null, school_name: "", region: "",
  video_id: null, thumbnail: "", filmed_on: "", is_published: false, sort_order: 0,
};

export default function AdminInterviews() {
  const [rows, setRows] = useState(null);
  const [videos, setVideos] = useState([]);
  const [editing, setEditing] = useState(null);   // null | "new" | id
  const [form, setForm] = useState(EMPTY);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = () => api.adminInterviews().then(setRows).catch((e) => setMsg({ type: "error", text: e.message }));
  useEffect(() => {
    load();
    api.adminVideos("longform").then(setVideos).catch(() => setVideos([]));
  }, []);

  const open = (row) => {
    setMsg(null);
    if (!row) {
      setEditing("new");
      setForm(EMPTY);
      return;
    }
    setEditing(row.id);
    setForm({
      title: row.title, summary: row.summary, speakers: row.speakers,
      school_id: row.school_id, school_name: row.school_id ? row.school.name : row.school_name,
      region: row.own_region || "", school_region: row.school_id ? row.school.region : "",
      video_id: row.video_id, thumbnail: row.own_thumbnail || "",
      filmed_on: row.filmed_on || "", is_published: row.is_published, sort_order: row.sort_order,
    });
  };

  const set = (patch) => setForm((f) => ({ ...f, ...patch }));

  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    const body = {
      ...form,
      school_name: form.school_id ? "" : form.school_name,
      region: form.school_id ? "" : form.region,
      filmed_on: form.filmed_on || null,
      sort_order: Number(form.sort_order) || 0,
    };
    try {
      if (editing === "new") await api.createInterview(body);
      else await api.updateInterview(editing, body);
      setMsg({ type: "success", text: "저장했습니다." });
      setEditing(null);
      load();
    } catch (err) {
      setMsg({ type: "error", text: err.message });
    } finally {
      setBusy(false);
    }
  };

  const remove = async (row) => {
    if (!confirm(`'${row.title}' 인터뷰를 지울까요?\n영상 파일은 영상 관리에 그대로 남습니다.`)) return;
    try {
      await api.deleteInterview(row.id);
      load();
    } catch (err) {
      setMsg({ type: "error", text: err.message });
    }
  };

  const uploadThumb = async (file) => {
    if (!file) return;
    try {
      const r = await api.uploadInterviewThumbnail(file);
      set({ thumbnail: r.url });
    } catch (err) {
      setMsg({ type: "error", text: err.message });
    }
  };

  return (
    <div className="wrap" style={{ padding: "34px 0 60px", maxWidth: 900 }}>
      <span className="label">특강 관리</span>
      <h1 style={{ fontSize: 24, margin: "8px 0 6px" }}>학교 홍보 인터뷰</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 0, lineHeight: 1.7 }}>
        영상은 <Link to="/admin/videos">영상 관리</Link>에 롱폼으로 먼저 올린 뒤 여기서 고르세요.
        여기에 붙인 영상은 <b>회원만</b> 볼 수 있습니다. 촬영 신청은 문의 목록에
        &lsquo;학교 홍보 인터뷰 촬영&rsquo;으로 들어옵니다.
      </p>

      {msg && <div className={`notice notice-${msg.type}`} style={{ marginBottom: 12 }}>{msg.text}</div>}

      {editing === null && (
        <button className="btn btn-signal" onClick={() => open(null)}>+ 인터뷰 추가</button>
      )}

      {editing !== null && (
        <form className="panel" onSubmit={save} style={{ display: "grid", gap: 14, marginTop: 0 }}>
          <h3 style={{ margin: 0 }}>{editing === "new" ? "새 인터뷰" : "인터뷰 고치기"}</h3>

          <AdminSchoolPicker value={form}
            onPick={(school_id, school_name, school_region = "") => set({ school_id, school_name, school_region })} />

          {/* 지역 필터에 쓰인다. 포털 학교면 학교의 지역을 그대로 쓰고, 직접 입력한 학교만 여기서 고른다. */}
          <div className="field">
            <label className="label" htmlFor="iv-region">지역</label>
            {form.school_id ? (
              <p style={{ margin: 0, fontSize: 13.5, color: "var(--steel)" }}>
                {form.school_region || "학교에 지역이 없습니다"} <small>(학교 정보의 지역을 씁니다)</small>
              </p>
            ) : (
              <select id="iv-region" className="input" value={form.region}
                onChange={(e) => set({ region: e.target.value })}>
                <option value="">지역 선택 안 함 (기타로 표시)</option>
                {IV_REGIONS.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            )}
          </div>

          <div className="field">
            <label className="label" htmlFor="iv-title">제목</label>
            <input id="iv-title" className="input" required maxLength={200} value={form.title}
              placeholder="예) 반도체 인재를 키우는 학교, 이렇게 공부해요"
              onChange={(e) => set({ title: e.target.value })} />
          </div>
          <div className="field">
            <label className="label" htmlFor="iv-sp">출연</label>
            <input id="iv-sp" className="input" maxLength={200} value={form.speakers}
              placeholder="예) 교장 선생님 · 전자과 부장 · 3학년 재학생 2명"
              onChange={(e) => set({ speakers: e.target.value })} />
          </div>
          <div className="field">
            <label className="label" htmlFor="iv-sum">소개</label>
            <textarea id="iv-sum" className="input" rows={5} maxLength={3000} value={form.summary}
              onChange={(e) => set({ summary: e.target.value })} />
          </div>

          <div className="field">
            <label className="label" htmlFor="iv-video">영상 (영상 관리의 롱폼)</label>
            <select id="iv-video" className="input" value={form.video_id || ""}
              onChange={(e) => set({ video_id: e.target.value ? Number(e.target.value) : null })}>
              <option value="">— 고르기 —</option>
              {videos.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.title}{v.file_url ? "" : " (파일 없음)"}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label className="label">썸네일 (없으면 영상 관리의 썸네일, 그것도 없으면 학교 이름)</label>
            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              {form.thumbnail && (
                <img src={form.thumbnail} alt="" style={{ width: 160, aspectRatio: "16/9",
                  objectFit: "cover", borderRadius: "var(--radius-sm)" }} />
              )}
              <input type="file" accept="image/png,image/jpeg,image/webp,image/gif"
                onChange={(e) => uploadThumb(e.target.files?.[0])} />
              {form.thumbnail && (
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => set({ thumbnail: "" })}>
                  썸네일 빼기
                </button>
              )}
            </div>
          </div>

          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div className="field">
              <label className="label" htmlFor="iv-date">촬영일</label>
              <input id="iv-date" className="input" type="date" value={form.filmed_on || ""}
                onChange={(e) => set({ filmed_on: e.target.value })} />
            </div>
            <div className="field">
              <label className="label" htmlFor="iv-sort">순서 (클수록 앞)</label>
              <input id="iv-sort" className="input" type="number" value={form.sort_order}
                onChange={(e) => set({ sort_order: e.target.value })} style={{ width: 120 }} />
            </div>
          </div>

          <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 14 }}>
            <input type="checkbox" checked={form.is_published}
              onChange={(e) => set({ is_published: e.target.checked })} />
            게시하기 (체크하면 인터뷰 목록에 나옵니다)
          </label>

          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn btn-signal" disabled={busy}>{busy ? "저장 중…" : "저장"}</button>
            <button type="button" className="btn btn-ghost" onClick={() => setEditing(null)}>취소</button>
          </div>
        </form>
      )}

      <div style={{ marginTop: 20, display: "grid", gap: 10 }}>
        {rows && rows.length === 0 && <div className="empty"><p>아직 인터뷰가 없습니다.</p></div>}
        {(rows || []).map((r) => (
          <div key={r.id} className="panel" style={{ marginTop: 0, display: "flex", gap: 14,
            alignItems: "center", flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 220 }}>
              <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                <span className={`badge ${r.is_published ? "badge-dorm" : "badge-unknown"}`}>
                  {r.is_published ? "게시 중" : "숨김"}
                </span>
                <b>{r.school?.name}</b>
              </div>
              <div style={{ marginTop: 4 }}>{r.title}</div>
              <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 2 }}>
                {r.video_title ? `영상: ${r.video_title}${r.has_file ? "" : " (파일 없음)"}` : "영상 없음"}
                {` · 조회 ${r.view_count}`}
              </div>
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              {r.is_published && <Link className="btn btn-ghost btn-sm" to={`/interviews/${r.id}`}>보기</Link>}
              <button className="btn btn-sm" onClick={() => open(r)}>고치기</button>
              <button className="btn btn-ghost btn-sm" onClick={() => remove(r)}>지우기</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

const IV_REGIONS = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
  "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"];

/** 학교 고르기. 포털에 없는 학교(분교·신설교)는 이름만 적을 수 있다. */
function AdminSchoolPicker({ value, onPick }) {
  const [q, setQ] = useState("");
  const [list, setList] = useState([]);
  const [manual, setManual] = useState(!value.school_id && !!value.school_name);
  const timer = useRef(null);

  useEffect(() => {
    if (manual || q.trim().length < 2) { setList([]); return undefined; }
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      api.schools({ name: q.trim(), size: 8 })
        .then((res) => setList(res.items || []))
        .catch(() => setList([]));
    }, 250);
    return () => clearTimeout(timer.current);
  }, [q, manual]);

  if (manual) {
    return (
      <div className="field">
        <label className="label" htmlFor="iv-sname">학교 이름 (직접 입력)</label>
        <input id="iv-sname" className="input" maxLength={80} value={value.school_name}
          onChange={(e) => onPick(null, e.target.value)} />
        <button type="button" className="btn btn-ghost btn-sm" style={{ justifySelf: "start" }}
          onClick={() => { setManual(false); onPick(null, ""); }}>목록에서 찾기</button>
      </div>
    );
  }
  return (
    <div className="field" style={{ position: "relative" }}>
      <label className="label" htmlFor="iv-sq">학교</label>
      {value.school_id ? (
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <b style={{ flex: 1 }}>{value.school_name}</b>
          <button type="button" className="btn btn-ghost btn-sm"
            onClick={() => { onPick(null, ""); setQ(""); }}>다시 고르기</button>
        </div>
      ) : (
        <>
          <input id="iv-sq" className="input" value={q} autoComplete="off"
            onChange={(e) => setQ(e.target.value)} placeholder="학교 이름 두 글자 이상" />
          {list.length > 0 && (
            <ul className="school-picker-list">
              {list.map((s) => (
                <li key={s.id}>
                  <button type="button" onClick={() => { onPick(s.id, s.name, s.region); setList([]); }}>
                    {s.name}<small>{s.region} · {s.category}</small>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <button type="button" className="btn btn-ghost btn-sm" style={{ justifySelf: "start" }}
            onClick={() => { setManual(true); onPick(null, q.trim()); }}>
            목록에 없는 학교 — 이름 직접 입력
          </button>
        </>
      )}
    </div>
  );
}
