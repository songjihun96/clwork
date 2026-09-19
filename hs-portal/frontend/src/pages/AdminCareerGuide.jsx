import { useEffect, useState } from "react";
import { api } from "../api";
import { errMsg, okMsg } from "../toast";

/** 진로 챗봇 정보표 관리.
 *
 * 챗봇이 **사실로 말하는 것은 전부 이 표에서 나온다** — 초봉, 자격증, 되는
 * 길. AI 가 숫자를 지어내지 못하게 표에 없는 것은 말하지 말라고 못 박아
 * 두었으니, 이 표가 틀리면 챗봇도 그대로 틀린다.
 *
 * 초봉은 비워 두고 시작한다. 공식 자료가 검색해야 나오는 화면이라 한 번에
 * 가져올 수 없었고, 없는 숫자를 지어 넣을 수는 없다. 아래 링크에서 직업
 * 이름으로 찾아 **출처와 함께** 적는다 — 출처 없는 초봉은 저장되지 않는다.
 */
export default function AdminCareerGuide() {
  const [data, setData] = useState(null);
  const [group, setGroup] = useState("");
  const [jobs, setJobs] = useState([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const load = (keep) => api.adminCareerGuide().then((d) => {
    setData(d);
    const g = keep && d.guide[keep] ? keep : Object.keys(d.guide)[0];
    setGroup(g);
    setJobs(d.guide[g]?.jobs || []);
  }).catch((e) => setMsg(errMsg(e.message)));
  useEffect(() => { load(); }, []);

  if (!data) return <div className="wrap" style={{ padding: 40 }}><p>불러오는 중…</p></div>;

  const pick = (g) => { setGroup(g); setJobs(data.guide[g]?.jobs || []); setMsg(null); };
  const patch = (i, p) => setJobs(jobs.map((j, k) => (k === i ? { ...j, ...p } : j)));

  const save = async () => {
    setBusy(true);
    try {
      await api.saveCareerGuide(group, jobs);
      setMsg(okMsg(`${group} 정보를 저장했습니다.`));
      await load(group);
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally { setBusy(false); }
  };

  const missingIn = (g) => (data.guide[g]?.jobs || []).filter((j) => !(j.salary || "").trim()).length;

  return (
    <div className="wrap" style={{ padding: "34px 0 60px", maxWidth: 900 }}>
      <span className="label">관리자</span>
      <h1 style={{ fontSize: 24, margin: "8px 0 6px" }}>진로 챗봇 정보표</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 0, lineHeight: 1.75 }}>
        진로 테스트 결과의 “AI에게 물어보기”가 <b>사실로 말하는 것은 전부 이 표에서</b> 나옵니다.
        표가 틀리면 챗봇도 그대로 틀리니, 특히 <b>초봉과 자격증</b>은 확인해서 적어 주세요.
      </p>

      {!data.ai_available && (
        <div className="notice notice-error" style={{ marginBottom: 12 }}>
          서버에 ANTHROPIC_API_KEY 가 없어 <b>직접 묻기</b>가 꺼져 있습니다.
          단추 질문(되는 길·자격증·첫 월급)은 이 표로 그대로 동작합니다.
        </div>
      )}
      {data.salary_missing > 0 && (
        <div className="notice notice-info" style={{ marginBottom: 12 }}>
          초봉이 비어 있는 직업이 <b>{data.salary_missing}개</b> 있습니다. 비어 있는 동안
          챗봇은 숫자를 말하지 않고 아래 사이트를 안내합니다.
          {" "}찾아볼 곳:{" "}
          {data.salary_lookup.map((x, i) => (
            <span key={x.url}>
              {i > 0 && " · "}
              <a href={x.url} target="_blank" rel="noreferrer">{x.name}</a>
            </span>
          ))}
        </div>
      )}
      {msg && <div className={`notice notice-${msg.type}`} style={{ marginBottom: 12 }}>{msg.text}</div>}

      <div className="tabs" style={{ flexWrap: "wrap" }}>
        {Object.keys(data.guide).map((g) => (
          <button key={g} className={`tab ${g === group ? "active" : ""}`} onClick={() => pick(g)}>
            {g}{missingIn(g) > 0 && <span style={{ color: "var(--color-attention)" }}> · 초봉 {missingIn(g)}</span>}
          </button>
        ))}
      </div>

      <div style={{ display: "grid", gap: 14, marginTop: 14 }}>
        {jobs.map((j, i) => (
          <div key={i} className="panel" style={{ margin: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
              <h3 style={{ border: "none", padding: 0, margin: 0, flex: 1 }}>{j.name}</h3>
              {!(j.salary || "").trim() && (
                <span className="badge" style={{
                  background: "var(--color-attention)", color: "#fff",
                  borderColor: "var(--color-attention)",
                }}>초봉 비어 있음</span>
              )}
            </div>

            <div style={{ display: "grid", gap: 10 }}>
              <div className="field">
                <label className="label">하는 일 (한 줄, 쉬운 말)</label>
                <input className="input" value={j.easy || ""} maxLength={200}
                  onChange={(e) => patch(i, { easy: e.target.value })} />
              </div>

              <div style={{ display: "grid", gap: 10, gridTemplateColumns: "minmax(0,1fr) minmax(0,1.4fr)" }}>
                <div className="field">
                  <label className="label">첫해 연봉</label>
                  <input className="input" value={j.salary || ""} maxLength={80}
                    placeholder="예) 연 2,800만~3,200만 원"
                    onChange={(e) => patch(i, { salary: e.target.value })} />
                </div>
                <div className="field">
                  <label className="label">연봉 출처 (초봉을 적으면 필수)</label>
                  <input className="input" value={j.salary_source || ""} maxLength={200}
                    placeholder="예) 고용24 직종별 임금정보, 2026년"
                    onChange={(e) => patch(i, { salary_source: e.target.value })} />
                </div>
              </div>

              <div className="field">
                <label className="label">추천 자격증 (쉼표로 구분 — 큐넷에서 이름 확인)</label>
                <input className="input" value={(j.certs || []).join(", ")}
                  onChange={(e) => patch(i, { certs: e.target.value.split(",").map((x) => x.trim()) })} />
              </div>

              <div className="field">
                <label className="label">필요한 노력</label>
                <textarea className="textarea" rows={2} value={j.effort || ""} maxLength={300}
                  onChange={(e) => patch(i, { effort: e.target.value })} />
              </div>

              <div className="field">
                <label className="label">되는 길 (한 줄에 한 단계)</label>
                <textarea className="textarea" rows={4} value={(j.path || []).join("\n")}
                  onChange={(e) => patch(i, { path: e.target.value.split("\n") })} />
              </div>
            </div>
          </div>
        ))}
      </div>

      <div style={{ marginTop: 16 }}>
        <button className="btn btn-primary" onClick={save} disabled={busy}>
          {busy ? "저장 중…" : `${group} 저장`}
        </button>
      </div>
    </div>
  );
}
