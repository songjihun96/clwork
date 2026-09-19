import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api";
import "../../research-theme.css";

export default function TeacherResearchDetail() {
  const { studentId } = useParams();
  const [detail, setDetail] = useState(null);
  const [feedback, setFeedback] = useState(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = () => {
    api.getTeacherResearchDetail(studentId).then(setDetail).catch((e) => setError(e.message));
  };
  useEffect(load, [studentId]);

  useEffect(() => {
    if (!detail?.research) return;
    api.listTeacherResearchFeedback(detail.research.id).then((r) => setFeedback(r.items)).catch(() => setFeedback([]));
  }, [detail?.research?.id]);

  const send = async () => {
    if (!text.trim()) return;
    setBusy(true); setError("");
    try {
      await api.addTeacherResearchFeedback(detail.research.id, text.trim());
      setText("");
      const r = await api.listTeacherResearchFeedback(detail.research.id);
      setFeedback(r.items);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (error) {
    return <div className="research-theme wrap page"><div className="notice notice-error">{error}</div></div>;
  }
  if (!detail) {
    return <div className="research-theme wrap page"><p>불러오는 중…</p></div>;
  }

  return (
    <div className="research-theme wrap page">
      <Link to="/research/teacher" className="label">← 연구 현황</Link>
      <h1 style={{ marginTop: 8 }}>{detail.student_name}</h1>

      {!detail.research ? (
        <div className="empty"><p>아직 시작한 연구가 없습니다.</p></div>
      ) : (
        <>
          <p style={{ fontSize: 15, color: "var(--color-text-secondary)" }}>
            {detail.research.title || detail.research.interest_keyword}
          </p>
          <div className="panel">
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, fontSize: 14 }}>
              <div>
                <span className="label">현재 단계</span>
                <div>{detail.research.stage_label || detail.research.current_stage}</div>
              </div>
              <div>
                <span className="label">진행률</span>
                <div>{detail.research.stage_progress}%</div>
              </div>
              <div>
                <span className="label">연구 기간</span>
                <div>{detail.research.duration_weeks}주</div>
              </div>
            </div>
          </div>

          <div className="panel">
            <h3>할 일</h3>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, fontSize: 13 }}>
              <div>
                <span className="label">완료</span>
                <ul style={{ margin: "4px 0", paddingLeft: 16 }}>
                  {detail.tasks.completed.length === 0 && <li style={{ color: "var(--color-text-muted)" }}>없음</li>}
                  {detail.tasks.completed.map((t, i) => <li key={i}>{t}</li>)}
                </ul>
              </div>
              <div>
                <span className="label">진행 중</span>
                <ul style={{ margin: "4px 0", paddingLeft: 16 }}>
                  {detail.tasks.in_progress.length === 0 && <li style={{ color: "var(--color-text-muted)" }}>없음</li>}
                  {detail.tasks.in_progress.map((t, i) => <li key={i}>{t}</li>)}
                </ul>
              </div>
              <div>
                <span className="label">다음</span>
                <ul style={{ margin: "4px 0", paddingLeft: 16 }}>
                  {detail.tasks.next.length === 0 && <li style={{ color: "var(--color-text-muted)" }}>없음</li>}
                  {detail.tasks.next.map((t, i) => <li key={i}>{t}</li>)}
                </ul>
              </div>
            </div>
          </div>

          {detail.last_report && (
            <div className="panel">
              <h3>최근 리포트</h3>
              <p style={{ fontSize: 13.5 }}>{detail.last_report.summary}</p>
            </div>
          )}

          <div className="panel">
            <h3>지도 피드백</h3>
            <div style={{ display: "grid", gap: 8, marginBottom: 12 }}>
              <textarea className="textarea" placeholder="이 단계에서 도움이 될 만한 조언을 남겨주세요"
                value={text} onChange={(e) => setText(e.target.value)} style={{ minHeight: 60 }} />
              {error && <div className="notice notice-error">{error}</div>}
              <button className="btn btn-sm btn-primary" onClick={send} disabled={busy} style={{ width: "fit-content" }}>
                {busy ? "남기는 중…" : "피드백 남기기"}
              </button>
            </div>
            {feedback && feedback.length > 0 && (
              <div style={{ display: "grid", gap: 8, borderTop: "1px solid var(--color-border)", paddingTop: 10 }}>
                {feedback.map((f) => (
                  <div key={f.id} style={{ borderLeft: "3px solid var(--color-secondary-accent)", paddingLeft: 10 }}>
                    <p style={{ fontSize: 13.5, margin: 0 }}>{f.content}</p>
                    <span style={{ fontSize: 11.5, color: "var(--color-text-muted)" }}>
                      {new Date(f.created_at).toLocaleDateString("ko-KR")}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
