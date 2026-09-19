import { useEffect, useState } from "react";
import { api } from "../api";

/** 환불 규정. 원문은 서버에서 가져온다.
 *  화면에 하드코딩하면 규정을 고칠 때 계산 규칙과 어긋나기 쉽다. */
export default function Refund() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.refundPolicy().then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) {
    return (
      <div className="wrap page" style={{ maxWidth: 760 }}>
        <div className="notice notice-error">{error}</div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="wrap page" style={{ maxWidth: 760 }}>
        <p className="meta">불러오는 중…</p>
      </div>
    );
  }

  return (
    <div className="wrap page" style={{ maxWidth: 760 }}>
      <span className="label">환불 규정</span>
      <h1 style={{ fontSize: 26, margin: "8px 0 4px" }}>{data.service_name} 환불 규정</h1>
      <p className="meta" style={{ marginTop: 0 }}>시행일 {data.effective_date}</p>

      {data.summary?.length > 0 && (
        <div className="notice" style={{ marginTop: 18 }}>
          <b>한눈에 보기</b>
          <ul style={{ margin: "6px 0 0", paddingLeft: 18, lineHeight: 1.85 }}>
            {data.summary.map((t, i) => <li key={i}>{t}</li>)}
          </ul>
        </div>
      )}

      <div style={{ display: "grid", gap: 22, marginTop: 26 }}>
        {data.articles.map((a, i) => (
          <section key={i}>
            <h2 style={{ fontSize: 16, marginBottom: 6 }}>{a.title}</h2>
            <p style={{ margin: 0, fontSize: 14.5, lineHeight: 1.85, color: "var(--steel)" }}>
              {a.body}
            </p>
          </section>
        ))}
      </div>
    </div>
  );
}
