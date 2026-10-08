import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useSeo } from "../seo";

/** 공지사항 — 목록(/notices)과 상세(/notices/:id).
 *  중요 공지가 위에, 그다음 최신순(서버가 정렬한다). 유형으로 거를 수 있다.
 *  우리동네직업계고 공지는 고등학교 학교 계정에게만 함께 보인다(서버가 거른다). */
export default function Notices() {
  const { id } = useParams();
  return id ? <NoticeDetail id={id} /> : <NoticeList />;
}

const fmtDate = (v) => (v ? String(v).slice(0, 10).replaceAll("-", ".") : "");

function NoticeList() {
  useSeo({ title: "공지사항", description: "우리동네 직업계고 공지사항", path: "/notices" });
  const [sp, setSp] = useSearchParams();
  const category = sp.get("category") || "";
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setError("");
    api.notices({ category: category || undefined }).then(setData)
      .catch((e) => { setData({ items: [], categories: [] }); setError(e.message); });
  }, [category]);

  const pick = (k) => {
    const next = new URLSearchParams(sp);
    if (k) next.set("category", k); else next.delete("category");
    setSp(next, { replace: true });
  };

  return (
    <div className="wrap nt-page">
      <span className="label" style={{ color: "var(--signal-deep)" }}>알림</span>
      <h1 className="nt-title">공지사항</h1>

      {data?.categories?.length > 0 && (
        <div className="iv-regions" role="group" aria-label="공지 유형">
          <button type="button" className={`iv-region${category ? "" : " on"}`}
            aria-pressed={!category} onClick={() => pick("")}>전체</button>
          {data.categories.map((c) => (
            <button type="button" key={c.key} aria-pressed={category === c.key}
              className={`iv-region${category === c.key ? " on" : ""}`}
              onClick={() => pick(c.key)}>{c.label}</button>
          ))}
        </div>
      )}

      {error && <div className="notice notice-error" style={{ marginTop: 16 }}>{error}</div>}
      {!data ? (
        <div className="empty" style={{ marginTop: 20 }}><p>불러오는 중…</p></div>
      ) : data.items.length === 0 ? (
        <div className="empty" style={{ marginTop: 20 }}><p>등록된 공지가 없습니다.</p></div>
      ) : (
        <ul className="nt-list">
          {data.items.map((n) => (
            <li key={n.id}>
              <Link to={`/notices/${n.id}`} className={`nt-row${n.is_important ? " important" : ""}`}>
                <span className="nt-badges">
                  {n.is_important && <span className="badge badge-important">중요</span>}
                  <span className="badge">{n.kind === "vocational" ? "직업계고 공지" : n.category_label}</span>
                </span>
                <span className="nt-row-title">{n.title}</span>
                <span className="nt-date">{fmtDate(n.published_at)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function NoticeDetail({ id }) {
  const [n, setN] = useState(null);
  const [error, setError] = useState("");
  useSeo({ title: n ? n.title : "공지사항", description: n?.body?.slice(0, 120), path: `/notices/${id}` });

  useEffect(() => {
    setN(null); setError("");
    api.notice(id).then((d) => {
      setN(d);
      api.readNotice(d.id).catch(() => {});   // 로그인했으면 읽음으로(종 모양의 안 읽은 수)
    }).catch((e) => setError(e.message));
  }, [id]);

  return (
    <div className="wrap nt-page" style={{ maxWidth: 820 }}>
      <Link to="/notices" className="btn btn-ghost btn-sm">← 목록으로</Link>
      {error ? (
        <div className="empty" style={{ marginTop: 20 }}><p>{error}</p></div>
      ) : !n ? (
        <div className="empty" style={{ marginTop: 20 }}><p>불러오는 중…</p></div>
      ) : (
        <article className="panel nt-article">
          <div className="nt-badges">
            {n.is_important && <span className="badge badge-important">중요</span>}
            <span className="badge">{n.kind === "vocational" ? "직업계고 공지" : n.category_label}</span>
          </div>
          <h1 className="nt-article-title">{n.title}</h1>
          <p className="nt-date">등록일 {fmtDate(n.published_at)}</p>
          {n.image_url && <img src={n.image_url} alt="" className="nt-image" />}
          {n.body && <div className="prose nt-body">{n.body}</div>}
        </article>
      )}
    </div>
  );
}
