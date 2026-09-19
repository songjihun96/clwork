import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";

/** 링크를 받은 사람이 로그인 없이 여는 화면.
 *  부모님이나 친척이 열어볼 자리라, 서비스 홍보보다 읽기 편한 것이 먼저다. */
export default function SharedJournal() {
  const { token } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  // 학생 개인 기록이다. robots.txt 로도 막지만, 링크를 타고 들어온
  // 로봇이 색인하지 않도록 화면에서도 못 박는다.
  useEffect(() => {
    const tag = document.createElement("meta");
    tag.name = "robots";
    tag.content = "noindex, nofollow, noarchive";
    document.head.appendChild(tag);
    return () => document.head.removeChild(tag);
  }, []);

  useEffect(() => {
    api
      .sharedJournal(token)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [token]);

  if (error) {
    return (
      <div className="wrap" style={{ maxWidth: 640, padding: "60px 20px", textAlign: "center" }}>
        <h2 style={{ marginBottom: 8 }}>일지를 볼 수 없습니다</h2>
        <p className="meta">{error}</p>
        <p className="meta" style={{ marginTop: 16 }}>
          작성한 학생이 공유를 끊었거나, 주소가 잘못되었을 수 있습니다.
        </p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="wrap" style={{ maxWidth: 640, padding: "60px 20px" }}>
        <p className="meta">불러오는 중…</p>
      </div>
    );
  }

  const entries = Object.entries(data.content || {}).filter(([, v]) => String(v || "").trim());

  return (
    <div className="wrap" style={{ maxWidth: 680, padding: "36px 20px 60px" }}>
      <div className="row" style={{ gap: 6, marginBottom: 10 }}>
        <span className="badge">{data.kind_label}</span>
        {data.student_name && <span className="badge badge-done">{data.student_name}</span>}
      </div>

      <h2 style={{ margin: "0 0 4px" }}>{data.title || data.subject || data.entry_date}</h2>
      <div className="meta" style={{ marginBottom: 22 }}>
        {data.entry_date}
        {data.subject && data.title ? ` · ${data.subject}` : ""}
        {data.teacher_name ? ` · ${data.teacher_name} 선생님` : ""}
      </div>

      <article className="journal-card">
        {entries.length === 0 ? (
          <p className="meta">아직 내용이 비어 있습니다.</p>
        ) : (
          entries.map(([key, value]) => (
            <div key={key} style={{ marginBottom: 18 }}>
              <div className="label">{key}</div>
              <p style={{ whiteSpace: "pre-wrap", lineHeight: 1.85, margin: "6px 0 0" }}>
                {value}
              </p>
            </div>
          ))
        )}
      </article>

      {data.feedback && (
        <div className="feedback-card" style={{ marginTop: 20 }}>
          <div className="label">선생님 한마디</div>
          <p style={{ whiteSpace: "pre-wrap", lineHeight: 1.75, margin: "6px 0 0" }}>
            {data.feedback}
          </p>
          {data.feedback_by_name && (
            <div className="meta" style={{ marginTop: 8 }}>{data.feedback_by_name} 선생님</div>
          )}
        </div>
      )}

      <p className="meta" style={{ marginTop: 30, textAlign: "center" }}>
        기록해 · 학교생활 일지
      </p>
    </div>
  );
}
