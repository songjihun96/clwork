import { useEffect, useState } from "react";
import { api } from "../api";
import { useSeo } from "../seo";
import LecturerProfile from "../components/LecturerProfile";
import ChapterEditor from "../components/ChapterEditor";
import { errMsg, okMsg } from "../toast";

/** 온라인 직업계고설명회 관리 — 지금은 강사 프로필.
 *
 * 경력은 **한 줄에 하나씩** 적는 여러 줄 입력 하나로 받는다. 줄마다 입력칸을
 * 따로 두면 12줄을 넣는 데 12번 [추가]를 눌러야 하고, 순서를 바꾸는 것도
 * 일이 된다. 붙여넣기 한 번으로 끝나는 쪽이 낫다 — 번호(1., 2. …)는 화면이
 * 알아서 매기므로 적지 않아도 된다.
 *
 * 오른쪽에 **실제 학생 화면 그대로** 미리보기를 띄운다. 저장하기 전에 어떻게
 * 보이는지 알 수 없으면, 저장하고 페이지를 열어보고 다시 돌아오기를 반복하게 된다.
 */
export default function AdminBriefing() {
  useSeo({ title: "설명회 관리", path: "/admin/briefing" });

  const [form, setForm] = useState(null);
  const [careersText, setCareersText] = useState("");
  const [linksText, setLinksText] = useState("");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    api.lecturer()
      .then((p) => {
        setForm(p);
        setCareersText((p.careers || []).join("\n"));
        setLinksText(linksToText(p.links || []));
      })
      .catch((e) => setMsg(errMsg(e.message)));
  }, []);

  if (!form) {
    return (
      <div className="wrap" style={{ padding: 40 }}>
        <p style={{ color: "var(--steel)" }}>불러오는 중…</p>
      </div>
    );
  }

  const careers = careersText.split("\n").map((c) => c.trim()).filter(Boolean);
  const links = linksFromText(linksText);
  const preview = { ...form, careers, links };

  const set = (patch) => setForm({ ...form, ...patch });

  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const saved = await api.saveLecturer({ ...form, careers, links });
      setForm(saved);
      setCareersText((saved.careers || []).join("\n"));
      setLinksText(linksToText(saved.links || []));
      setMsg(okMsg("저장했습니다."));
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setBusy(false);
    }
  };

  const pickPhoto = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setUploading(true);
    setMsg(null);
    try {
      const r = await api.uploadLecturerPhoto(file);
      set({ photo: r.url });
      setMsg({ type: "info", text: "사진을 올렸습니다. 아래 [저장]까지 눌러야 반영됩니다." });
    } catch (err) {
      setMsg(errMsg(err.message));
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="wrap" style={{ padding: "34px 0 60px" }}>
      <span className="label">관리자</span>
      <h1 style={{ fontSize: 26, margin: "8px 0 4px" }}>설명회 관리</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 0 }}>
        온라인 직업계고설명회 페이지(<a href="/briefing">/briefing</a>)에 나가는 강사 프로필입니다.
      </p>

      {msg && <div className={`notice notice-${msg.type}`} style={{ marginTop: 12 }}>{msg.text}</div>}

      <div className="panel" style={{ marginTop: 16 }}>
        <h3>강사 프로필</h3>
        <div style={{ display: "grid", gap: 12 }}>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            <div className="field" style={{ flex: "1 1 200px" }}>
              <label className="label">이름</label>
              <input className="input" value={form.name} placeholder="강승구"
                onChange={(e) => set({ name: e.target.value })} />
            </div>
            <div className="field" style={{ flex: "2 1 260px" }}>
              <label className="label">이름 아래 한 줄 <span style={{ fontWeight: "normal", color: "var(--steel)" }}>(선택)</span></label>
              <input className="input" value={form.title} placeholder="특성화고신문 대표"
                onChange={(e) => set({ title: e.target.value })} />
            </div>
          </div>

          <div className="field">
            <label className="label">사진</label>
            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              {form.photo && (
                <img src={form.photo} alt="" style={{
                  width: 80, height: 106, objectFit: "cover", borderRadius: 8,
                  border: "1px solid var(--line)",
                }} />
              )}
              <label className="btn btn-ghost btn-sm"
                style={{ cursor: uploading ? "default" : "pointer", opacity: uploading ? .6 : 1 }}>
                {uploading ? "올리는 중…" : form.photo ? "다른 사진으로" : "사진 올리기"}
                <input type="file" accept="image/png,image/jpeg,image/webp"
                  onChange={pickPhoto} disabled={uploading} style={{ display: "none" }} />
              </label>
              {form.photo && (
                <button className="btn btn-ghost btn-sm" onClick={() => set({ photo: "" })}>
                  사진 지우기
                </button>
              )}
              <span style={{ fontSize: 12, color: "var(--steel)" }}>
                세로로 긴 사진(3:4)이 가장 잘 맞습니다 · 5MB 이하
              </span>
            </div>
          </div>

          <div className="field">
            <label className="label">경력 — 한 줄에 하나씩</label>
            <textarea className="textarea" rows={12} value={careersText}
              onChange={(e) => setCareersText(e.target.value)}
              placeholder={"국내 유일의 직업계고 전문언론 특성화고신문 강승구 대표\n現학교법인 기동학원 경기관광고등학교 홍보컨설팅 위원\n前서울시교육청 직업계고 홍보위원"} />
            <p style={{ fontSize: 12, color: "var(--steel)", margin: "6px 0 0" }}>
              번호(1. 2. 3. …)는 화면이 자동으로 붙입니다. 직접 적지 마세요 —
              중간에 한 줄을 끼워 넣으면 아래 번호를 전부 고쳐야 합니다.
              지금 {careers.length}줄입니다.
            </p>
          </div>

          <div className="field">
            <label className="label">소개 링크 — 한 줄에 하나</label>
            <textarea className="textarea" rows={3} value={linksText}
              onChange={(e) => setLinksText(e.target.value)}
              placeholder={"인스타그램 | https://instagram.com/...\n유튜브 | https://youtube.com/..."} />
            <p style={{ fontSize: 12, color: "var(--steel)", margin: "6px 0 0" }}>
              <b>이름 | 주소</b> 형식입니다. 이름을 안 적으면 주소가 그대로 보입니다.
            </p>
          </div>

          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            <div className="field" style={{ flex: "1 1 220px" }}>
              <label className="label">버튼 문구 <span style={{ fontWeight: "normal", color: "var(--steel)" }}>(비우면 버튼 안 나옴)</span></label>
              <input className="input" value={form.cta_label}
                placeholder="직업계고 3년Plan 컨설팅 신청"
                onChange={(e) => set({ cta_label: e.target.value })} />
            </div>
            <div className="field" style={{ flex: "1 1 220px" }}>
              <label className="label">버튼을 누르면 갈 곳</label>
              <input className="input" value={form.cta_url} placeholder="/consulting"
                onChange={(e) => set({ cta_url: e.target.value })} />
            </div>
          </div>

          <div>
            <button className="btn btn-signal" onClick={save} disabled={busy}>
              {busy ? "저장 중…" : "저장"}
            </button>
          </div>
        </div>
      </div>

      <ChapterEditor setMsg={setMsg} />

      <div className="panel" style={{ marginTop: 16 }}>
        <h3>미리보기 <span style={{ fontWeight: "normal", fontSize: 13, color: "var(--steel)" }}>— 학생에게 이렇게 보입니다</span></h3>
        <LecturerProfile profile={preview} />
      </div>
    </div>
  );
}

/** 링크 목록 ↔ "이름 | 주소" 여러 줄. */
function linksToText(links) {
  return links.map((l) => (l.label ? `${l.label} | ${l.url}` : l.url)).join("\n");
}

function linksFromText(text) {
  return (text || "").split("\n").map((raw) => {
    const line = raw.trim();
    if (!line) return null;
    const bar = line.indexOf("|");
    if (bar < 0) return { label: "", url: line };
    return { label: line.slice(0, bar).trim(), url: line.slice(bar + 1).trim() };
  }).filter((x) => x && x.url);
}
