import { useEffect, useState } from "react";
import { api } from "../api";
import { useSeo } from "../seo";

// 환불 규정 페이지. 원문은 서버 /api/refund-policy 에서 가져온다.
export default function Refund() {
  useSeo({
    title: "환불 규정",
    description: "유료 플랜의 청약철회·중도 해지·환불 절차 안내입니다.",
    path: "/refund",
  });
  const [data, setData] = useState(null);

  useEffect(() => {
    api.refundPolicy().then(setData).catch(() => {});
  }, []);

  if (!data) {
    return (
      <div className="wrap" style={{ maxWidth: 820, padding: "40px 0 70px" }}>
        <div className="empty"><p>불러오는 중…</p></div>
      </div>
    );
  }

  return (
    <div className="wrap" style={{ maxWidth: 820, padding: "40px 0 70px" }}>
      <span className="label" style={{ color: "var(--signal-deep)" }}>환불 규정</span>
      <h1 style={{ fontSize: 28, margin: "8px 0 6px" }}>{data.service_name} 환불 규정</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 0 }}>
        시행일: {data.effective_date}
      </p>

      {data.summary?.length > 0 && (
        <div className="notice notice-info" style={{ marginTop: 20 }}>
          <b>요약</b>
          <ul style={{ margin: "6px 0 0", paddingLeft: 18, lineHeight: 1.8 }}>
            {data.summary.map((t, i) => <li key={i}>{t}</li>)}
          </ul>
        </div>
      )}

      <div style={{ display: "grid", gap: 24, marginTop: 28, fontSize: 14.5, lineHeight: 1.75, color: "var(--ink-soft)" }}>
        {data.articles.map((a, i) => (
          <section key={i}>
            <h2 style={{ fontSize: 17, marginBottom: 8, color: "var(--ink)" }}>{a.title}</h2>
            <p style={{ margin: 0 }}>{a.body}</p>
          </section>
        ))}
      </div>
    </div>
  );
}
