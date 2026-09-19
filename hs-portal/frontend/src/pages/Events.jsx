import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { ddayClass, ddayText } from "../dday";
import { useSeo } from "../seo";

const KIND_LABEL = { briefing: "학교 설명회", admission: "참가 행사" };

export default function Events() {
  useSeo({
    title: "학교 일정",
    description: "전국 직업계고의 학교 설명회와 참가 행사를 지역별로 모아 확인하세요.",
    path: "/events",
  });
  const navigate = useNavigate();

  const [regions, setRegions] = useState([]);
  const [region, setRegion] = useState("");
  const [kind, setKind] = useState(""); // "" | briefing | admission
  const [scope, setScope] = useState("upcoming"); // upcoming | all
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.meta().then((m) => setRegions(m.regions)).catch(() => {});
  }, []);

  useEffect(() => {
    setLoading(true);
    api
      .allEvents({ region, kind, scope })
      .then(setEvents)
      .catch(() => setEvents([]))
      .finally(() => setLoading(false));
  }, [region, kind, scope]);

  return (
    <div className="wrap" style={{ padding: "34px 0 60px" }}>
      <span className="label">전체 일정</span>
      <h1 style={{ fontSize: 26, margin: "8px 0 4px" }}>학교 일정 모아보기</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 0 }}>
        전국 직업계고의 학교 설명회와 참가 행사를 한곳에서 확인하세요.
      </p>

      {/* 필터 */}
      <div
        style={{
          display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end",
          background: "var(--surface)", border: "1px solid var(--line)",
          borderRadius: "var(--radius)", padding: "16px 18px", margin: "18px 0 22px",
        }}
      >
        <div className="field" style={{ minWidth: 160 }}>
          <label className="label" htmlFor="ev-region">지역 (시/도)</label>
          <select id="ev-region" className="select" value={region} onChange={(e) => setRegion(e.target.value)}>
            <option value="">전체 지역</option>
            {regions.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </div>

        <div className="field">
          <label className="label">종류</label>
          <div style={{ display: "flex", gap: 6 }}>
            {[["", "전체"], ["briefing", "학교 설명회"], ["admission", "참가 행사"]].map(([v, label]) => (
              <button
                key={v}
                className={`btn btn-sm ${kind === v ? "btn-primary" : "btn-ghost"}`}
                onClick={() => setKind(v)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="field">
          <label className="label">기간</label>
          <div style={{ display: "flex", gap: 6 }}>
            {[["upcoming", "다가오는 일정"], ["all", "전체(지난 일정 포함)"]].map(([v, label]) => (
              <button
                key={v}
                className={`btn btn-sm ${scope === v ? "btn-primary" : "btn-ghost"}`}
                onClick={() => setScope(v)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* 목록 */}
      {loading ? (
        <div className="empty"><p>불러오는 중…</p></div>
      ) : events.length === 0 ? (
        <div className="empty"><p>조건에 맞는 일정이 없습니다.</p></div>
      ) : (
        <>
          <p className="label" style={{ marginBottom: 10 }}>총 {events.length}건</p>
          <div style={{ display: "grid", gap: 10 }}>
            {events.map((e) => (
              <button
                key={e.id}
                onClick={() => navigate(`/schools/${e.school_id}?event=${e.id}`)}
                style={{
                  display: "flex", alignItems: "center", gap: 14, textAlign: "left", width: "100%",
                  background: "var(--surface)", border: "1px solid var(--line)",
                  borderRadius: "var(--radius)", padding: "14px 16px", cursor: "pointer",
                }}
              >
                <span className={ddayClass(e.d_day)} style={{ minWidth: 58, textAlign: "center" }}>
                  {ddayText(e.d_day)}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginBottom: 3 }}>
                    <span className={`badge ${e.kind === "briefing" ? "badge-cat" : "badge-dorm"}`}>
                      {KIND_LABEL[e.kind] || "일정"}
                    </span>
                    <span style={{ fontWeight: 600, fontSize: 15 }}>{e.title}</span>
                  </div>
                  <div style={{ fontSize: 12.5, color: "var(--steel)" }}>
                    {e.school_name} · {e.region} · {e.category}
                  </div>
                  <div style={{ fontSize: 12.5, color: "var(--steel-light)", marginTop: 2 }}>
                    {e.start_date}{e.end_date ? ` ~ ${e.end_date}` : ""}
                    {e.start_time ? ` · ${e.start_time}${e.end_time ? `~${e.end_time}` : ""}` : ""}
                    {e.location ? ` · ${e.location}` : ""}
                  </div>
                </div>
                <span style={{ color: "var(--steel-light)", fontSize: 18, flexShrink: 0 }}>›</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
