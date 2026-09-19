import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api";
import "../../research-theme.css";

const SECTION_LABELS = [
  ["why", "왜 이 연구를 시작했나요"], ["question", "무엇이 궁금했나요"],
  ["hypothesis", "해보기 전 예상은 무엇이었나요"], ["method", "어떻게 연구했나요"],
  ["data", "어떤 데이터를 얻었나요"], ["result", "무엇을 발견했나요"],
  ["discussion", "어떻게 해석했나요"], ["limitation", "무엇이 부족했나요"],
  ["next", "다음엔 무엇을 하고 싶나요"],
];

/** 공유 링크로 보는 연구 포트폴리오. 로그인 없이 열리고 보기 전용이다. */
export default function SharedResearchPortfolio() {
  const { token } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const tag = document.createElement("meta");
    tag.name = "robots";
    tag.content = "noindex, nofollow, noarchive";
    document.head.appendChild(tag);
    return () => document.head.removeChild(tag);
  }, []);

  useEffect(() => {
    api.sharedResearchPortfolio(token).then(setData).catch((e) => setError(e.message));
  }, [token]);

  if (error) {
    return (
      <div className="research-theme wrap" style={{ maxWidth: 640, padding: "60px 20px", textAlign: "center" }}>
        <h2 style={{ marginBottom: 8 }}>포트폴리오를 볼 수 없습니다</h2>
        <p style={{ color: "var(--color-text-secondary)" }}>{error}</p>
        <p style={{ color: "var(--color-text-secondary)", marginTop: 16 }}>
          만든 학생이 공유를 껐거나, 주소가 잘못되었을 수 있습니다.
        </p>
      </div>
    );
  }
  if (!data) {
    return <div className="research-theme wrap" style={{ maxWidth: 640, padding: "60px 20px" }}>
      <p style={{ color: "var(--color-text-secondary)" }}>불러오는 중…</p>
    </div>;
  }

  return (
    <div className="research-theme wrap" style={{ maxWidth: 720, padding: "36px 20px 60px" }}>
      <div className="row" style={{ gap: 6, marginBottom: 10 }}>
        {data.student_name && <span className="research-stage-pill">{data.student_name}</span>}
      </div>
      <h1 style={{ margin: "0 0 6px" }}>{data.title || "제목 없음"}</h1>
      {data.research_question && (
        <p style={{ color: "var(--color-text-secondary)", lineHeight: 1.8 }}>{data.research_question}</p>
      )}

      <div style={{ display: "grid", gap: 24, marginTop: 30 }}>
        {SECTION_LABELS.map(([key, label]) =>
          data.sections?.[key] ? (
            <section key={key}>
              <h3 style={{ borderBottom: "2px solid var(--color-border)", paddingBottom: 8 }}>{label}</h3>
              <p style={{ whiteSpace: "pre-wrap", lineHeight: 1.85, marginTop: 12 }}>{data.sections[key]}</p>
            </section>
          ) : null
        )}
      </div>

      <p style={{ color: "var(--color-text-muted)", marginTop: 40, textAlign: "center" }}>
        기록해 · 학생 연구 포트폴리오
      </p>
    </div>
  );
}
