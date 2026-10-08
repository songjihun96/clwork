import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";

/** 기록해 공지사항 — 목록(/notices)과 상세(/notices/:id). 로그인하지 않아도 본다.
 *  UDJ 공지와 별개다(기록해 관리자가 올린 공지만 나온다). */
export default function Notices() {
  const { id } = useParams();
  return id ? <NoticeDetail id={id} /> : <NoticeList />;
}

const fmtDate = (v) => (v ? String(v).slice(0, 10).replaceAll("-", ".") : "");

function NoticeList() {
  const [sp, setSp] = useSearchParams();
  const category = sp.get("category") || "";
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => { document.title = "공지사항 | 기록해"; }, []);
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
    <div className="wrap page" style={{ maxWidth: 900 }}>
      <span className="label">알림</span>
      <h1>공지사항</h1>
      {data?.categories?.length > 0 && (
        <div className="row" role="group" aria-label="공지 유형" style={{ gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
          <button type="button" className={`btn btn-sm ${category ? "btn-ghost" : ""}`} aria-pressed={!category}
            onClick={() => pick("")}>전체</button>
          {data.categories.map((c) => (
            <button type="button" key={c.key} className={`btn btn-sm ${category === c.key ? "" : "btn-ghost"}`}
              aria-pressed={category === c.key} onClick={() => pick(c.key)}>{c.label}</button>
          ))}
        </div>
      )}
      {error && <div className="notice notice-error" style={{ marginTop: 12 }}>{error}</div>}
      {!data ? <p className="meta">불러오는 중…</p> : data.items.length === 0 ? (
        <div className="empty"><p>등록된 공지가 없습니다.</p></div>
      ) : (
        <ul className="nt-list">
          {data.items.map((n) => (
            <li key={n.id}>
              <Link to={`/notices/${n.id}`} className={`nt-row${n.is_important ? " important" : ""}`}>
                <span className="nt-badges">
                  {n.is_important && <span className="badge badge-danger">중요</span>}
                  <span className="badge">{n.category_label}</span>
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
  useEffect(() => {
    setN(null); setError("");
    api.notice(id).then((d) => { setN(d); document.title = `${d.title} | 기록해`; })
      .catch((e) => setError(e.message));
  }, [id]);
  return (
    <div className="wrap page" style={{ maxWidth: 820 }}>
      <Link to="/notices" className="btn btn-ghost btn-sm">← 목록으로</Link>
      {error ? <div className="empty"><p>{error}</p></div> : !n ? <p className="meta">불러오는 중…</p> : (
        <article className="panel" style={{ marginTop: 14 }}>
          <div className="nt-badges">
            {n.is_important && <span className="badge badge-danger">중요</span>}
            <span className="badge">{n.category_label}</span>
          </div>
          <h1 style={{ fontSize: 22, margin: "10px 0 4px", lineHeight: 1.4 }}>{n.title}</h1>
          <p className="nt-date">등록일 {fmtDate(n.published_at)}</p>
          {n.body && <div className="nt-body">{n.body}</div>}
        </article>
      )}
    </div>
  );
}
