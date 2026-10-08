import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { api } from "../api";
import { useSeo } from "../seo";
import { InterviewThumb } from "./Interviews";

/** 학교 홍보 인터뷰 한 편.
 *
 * 비회원에게는 서버가 재생 주소를 안 준다(login_required). 그 자리에 썸네일과
 * 가입 버튼을 둔다 — 가입·로그인이 끝나면 이 주소로 돌아와 바로 볼 수 있다.
 */
export default function InterviewPage() {
  const { id } = useParams();
  const location = useLocation();
  const [item, setItem] = useState(null);
  const [others, setOthers] = useState([]);
  const [error, setError] = useState("");

  useSeo({
    title: item ? `${item.school?.name} 인터뷰 — ${item.title}` : "학교 홍보 인터뷰",
    description: item?.summary?.slice(0, 120) || undefined,
    path: `/interviews/${id}`,
  });

  useEffect(() => {
    setItem(null);
    setError("");
    api.interview(id).then(setItem).catch((e) => setError(e.message));
    api.interviews().then((d) => setOthers(d.items || [])).catch(() => setOthers([]));
  }, [id]);

  if (error) {
    return (
      <div className="wrap" style={{ padding: 40 }}>
        <div className="notice notice-error">{error}</div>
        <Link to="/interviews" className="btn btn-ghost btn-sm" style={{ marginTop: 12 }}>← 인터뷰 목록</Link>
      </div>
    );
  }
  if (!item) {
    return <div className="wrap" style={{ padding: 40 }}><div className="empty"><p>불러오는 중…</p></div></div>;
  }

  const next = encodeURIComponent(location.pathname);
  const rest = others.filter((o) => o.id !== item.id).slice(0, 6);

  return (
    <div className="wrap" style={{ padding: "24px 0 60px", maxWidth: 960 }}>
      <Link to="/interviews" className="btn btn-ghost btn-sm" style={{ marginBottom: 14 }}>
        ← 인터뷰 목록
      </Link>

      {item.source?.file_url ? (
        <video src={item.source.file_url} controls playsInline preload="metadata"
          controlsList="nodownload" onContextMenu={(e) => e.preventDefault()}
          poster={item.thumbnail || undefined}
          style={{ width: "100%", borderRadius: "var(--radius)", background: "#000",
            aspectRatio: "16 / 9", display: "block" }} />
      ) : item.login_required ? (
        <div className="iv-locked">
          <InterviewThumb item={item} big />
          <div className="iv-locked-over">
            <div className="members-lock-icon" aria-hidden="true">🔒</div>
            <p>학교 인터뷰는 회원만 볼 수 있어요. 가입은 무료예요.</p>
            <div className="members-lock-actions">
              <Link className="btn btn-signal" to={`/signup?next=${next}`}>무료 회원가입하고 보기</Link>
              <Link className="btn iv-login-btn" to={`/login?next=${next}`}>로그인</Link>
            </div>
          </div>
        </div>
      ) : (
        <div className="empty"><p>영상을 준비하고 있어요.</p></div>
      )}

      <div style={{ marginTop: 18 }}>
        <div className="iv-card-school" style={{ fontSize: 14 }}>
          {item.school?.id
            ? <Link to={`/schools/${item.school.id}`}>{item.school.name}</Link>
            : item.school?.name}
          {item.school?.region && <small>{item.school.region}{item.school.category ? ` · ${item.school.category}` : ""}</small>}
        </div>
        <h1 style={{ fontSize: 23, margin: "6px 0 6px", lineHeight: 1.35 }}>{item.title}</h1>
        <p style={{ color: "var(--steel)", fontSize: 13.5, margin: 0 }}>
          {[item.speakers,
            item.filmed_on ? `${item.filmed_on.replaceAll("-", ".")} 촬영` : "",
            !item.login_required ? `조회 ${(item.view_count || 0).toLocaleString()}회` : ""]
            .filter(Boolean).join(" · ")}
        </p>
        {item.summary && <p className="prose" style={{ marginTop: 14, whiteSpace: "pre-wrap" }}>{item.summary}</p>}
        {item.school?.id && (
          <Link to={`/schools/${item.school.id}`} className="btn btn-sm" style={{ marginTop: 14 }}>
            {item.school.name} 학교 정보 보기 →
          </Link>
        )}
      </div>

      {rest.length > 0 && (
        <section style={{ marginTop: 34 }}>
          <h3 style={{ fontSize: 17, margin: "0 0 12px" }}>다른 학교 인터뷰</h3>
          <div className="iv-grid" style={{ marginTop: 0 }}>
            {rest.map((it) => (
              <Link key={it.id} to={`/interviews/${it.id}`} className="iv-card">
                <InterviewThumb item={it} />
                <div className="iv-card-body">
                  <div className="iv-card-school">{it.school?.name}</div>
                  <div className="iv-card-title">{it.title}</div>
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
