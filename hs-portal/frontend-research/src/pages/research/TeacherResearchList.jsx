import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import "../../research-theme.css";

export default function TeacherResearchList() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.listTeacherResearch().then((r) => setItems(r.items)).catch((e) => { setError(e.message); setItems([]); });
  }, []);

  if (error) {
    return <div className="research-theme wrap page"><div className="notice notice-error">{error}</div></div>;
  }
  if (!items) {
    return <div className="research-theme wrap page"><p>불러오는 중…</p></div>;
  }

  return (
    <div className="research-theme wrap page">
      <div className="row" style={{ alignItems: "center" }}>
        <div>
          <span className="label">담당 학급</span>
          <h1 style={{ marginTop: 4 }}>연구 현황</h1>
        </div>
        <div className="spacer" />
        <Link to="/research/teacher-external-questions" className="btn btn-sm btn-ghost">외부 학생 질문</Link>
        <Link to="/research/teacher-team-requests" className="btn btn-sm btn-ghost">팀 탈퇴 신청</Link>
      </div>
      <p style={{ fontSize: 13.5, color: "var(--color-text-secondary)" }}>
        학생들의 연구 진행 상황입니다. 평가가 아니라 현황판이에요.
      </p>

      {items.length === 0 ? (
        <div className="empty"><p>담당 학급 학생이 없습니다.</p></div>
      ) : (
        <div style={{ display: "grid", gap: 10, marginTop: 16 }}>
          {items.map((it) => (
            <Link key={it.student_id} to={`/research/teacher/${it.student_id}`} className="entry">
              <div className="row" style={{ gap: 10, alignItems: "center" }}>
                <b style={{ minWidth: 80 }}>{it.student_name}</b>
                {it.research ? (
                  <>
                    <span style={{ flex: 1, fontSize: 13.5 }}>{it.research.title}</span>
                    <span className="research-stage-pill">
                      {it.research.stage_label || it.research.current_stage}
                    </span>
                    <span style={{ fontSize: 12.5, color: "var(--color-text-muted)", minWidth: 40, textAlign: "right" }}>
                      {it.research.stage_progress}%
                    </span>
                    {it.activity_status === "inactive" && (
                      <span className="badge" style={{ background: "var(--color-attention-soft)", color: "var(--color-attention)" }}>
                        최근 활동 없음
                      </span>
                    )}
                  </>
                ) : (
                  <span style={{ flex: 1, fontSize: 13, color: "var(--color-text-muted)" }}>연구 없음</span>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
