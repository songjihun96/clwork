import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";

/** 공유 링크로 보는 포트폴리오. 로그인 없이 열리고, 보기 전용이다
 *  (수정 API는 전부 소유자 검사를 하므로 여기엔 수정 버튼 자체가 없다). */
export default function SharedPortfolio() {
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
    api.sharedPortfolio(token).then(setData).catch((e) => setError(e.message));
  }, [token]);

  if (error) {
    return (
      <div className="wrap" style={{ maxWidth: 640, padding: "60px 20px", textAlign: "center" }}>
        <h2 style={{ marginBottom: 8 }}>포트폴리오를 볼 수 없습니다</h2>
        <p className="meta">{error}</p>
        <p className="meta" style={{ marginTop: 16 }}>
          만든 학생이 공유를 껐거나, 주소가 잘못되었을 수 있습니다.
        </p>
      </div>
    );
  }
  if (!data) {
    return <div className="wrap" style={{ maxWidth: 640, padding: "60px 20px" }}><p className="meta">불러오는 중…</p></div>;
  }

  return (
    <div className="wrap" style={{ maxWidth: 720, padding: "36px 20px 60px" }}>
      <div className="row" style={{ gap: 6, marginBottom: 10 }}>
        <span className="badge">{data.theme_label}</span>
        {data.student_name && <span className="badge badge-done">{data.student_name}</span>}
      </div>
      <h1 style={{ margin: "0 0 6px" }}>{data.title || "제목 없음"}</h1>
      {data.description && (
        <p style={{ color: "var(--steel)", lineHeight: 1.8 }}>{data.description}</p>
      )}

      {(data.pages || []).map((page) => (
        <section key={page.id} style={{ marginTop: 30 }}>
          <h3 style={{ borderBottom: "2px solid var(--line)", paddingBottom: 8 }}>{page.title}</h3>
          <div style={{ display: "grid", gap: 14, marginTop: 14 }}>
            {(page.blocks || []).map((b) => <SharedBlock key={b.id} block={b} />)}
          </div>
        </section>
      ))}

      <p className="meta" style={{ marginTop: 40, textAlign: "center" }}>
        기록해 · 학생 포트폴리오
      </p>
    </div>
  );
}

function SharedBlock({ block }) {
  const text = block.content?.text || "";
  switch (block.block_type) {
    case "heading":
      return <h4 style={{ margin: 0 }}>{text}</h4>;
    case "image":
      return block.content?.url ? (
        <img src={block.content.url} alt="" style={{ maxWidth: "100%", borderRadius: 8 }} />
      ) : null;
    case "quote":
      return (
        <blockquote style={{ borderLeft: "3px solid var(--signal)", margin: 0,
                             paddingLeft: 14, color: "var(--steel)", fontStyle: "italic" }}>
          {text}
        </blockquote>
      );
    case "divider":
      return <hr style={{ border: "none", borderTop: "1px solid var(--line)" }} />;
    case "text":
    default:
      return text ? <p style={{ whiteSpace: "pre-wrap", lineHeight: 1.85, margin: 0 }}>{text}</p> : null;
  }
}
