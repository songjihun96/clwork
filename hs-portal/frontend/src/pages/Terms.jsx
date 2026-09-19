import { useEffect, useState } from "react";
import { api } from "../api";

// 이용약관 페이지. 원문은 서버 /api/terms 에서 가져온다.
export default function Terms() {
  const [terms, setTerms] = useState(null);

  useEffect(() => {
    api.terms().then(setTerms).catch(() => {});
  }, []);

  if (!terms) {
    return (
      <div className="wrap" style={{ maxWidth: 820, padding: "40px 0 70px" }}>
        <div className="empty"><p>불러오는 중…</p></div>
      </div>
    );
  }

  return (
    <div className="wrap" style={{ maxWidth: 820, padding: "40px 0 70px" }}>
      <span className="label" style={{ color: "var(--signal-deep)" }}>이용약관</span>
      <h1 style={{ fontSize: 28, margin: "8px 0 6px" }}>{terms.service_name} 이용약관</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 0 }}>
        시행일: {terms.effective_date}
      </p>

      <div style={{ display: "grid", gap: 24, marginTop: 28, fontSize: 14.5, lineHeight: 1.75, color: "var(--ink-soft)" }}>
        {terms.articles.map((a, i) => (
          <section key={i}>
            <h2 style={{ fontSize: 17, marginBottom: 8, color: "var(--ink)" }}>{a.title}</h2>
            <p style={{ margin: 0 }}>{a.body}</p>
          </section>
        ))}
      </div>
    </div>
  );
}
