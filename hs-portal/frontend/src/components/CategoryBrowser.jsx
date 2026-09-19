import { useEffect, useState } from "react";

/**
 * 일지를 '핵심 키워드 · 역량 주제'별로 모아 보는 화면.
 * 학생·선생님 양쪽에서 쓰며, 데이터 가져오는 방법만 fetchData로 주입받는다.
 */
export default function CategoryBrowser({ fetchData, showSummary = false }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [topic, setTopic] = useState(null);
  const [keyword, setKeyword] = useState(null);

  useEffect(() => {
    setLoading(true);
    fetchData()
      .then((d) => {
        setData(d);
        setTopic(d.topics?.[0]?.key || null);
      })
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="empty"><p>분석 중…</p></div>;
  if (!data || (data.topics.length === 0 && data.keywords.length === 0)) {
    return <div className="empty"><p>분석할 일지가 없습니다.</p></div>;
  }

  const current = data.topics.find((t) => t.key === topic);
  // 키워드를 고르면 그 낱말이 포함된 글만 걸러 본다
  const items = (current?.items || []).filter(
    (it) => !keyword || (it.keywords || []).includes(keyword) || (it.excerpt || []).some((s) => s.includes(keyword))
  );

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div className="panel">
        <h3>핵심 키워드</h3>
        <p style={{ fontSize: 13, color: "var(--steel)", marginTop: -4 }}>
          글에서 자주 나온 낱말입니다. 누르면 그 낱말이 담긴 내용만 볼 수 있습니다.
        </p>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {data.keywords.map((k) => (
            <button
              key={k.word}
              className={`btn btn-sm ${keyword === k.word ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setKeyword(keyword === k.word ? null : k.word)}
            >
              #{k.word}{k.count > 1 ? ` ${k.count}` : ""}
            </button>
          ))}
        </div>
        {keyword && (
          <p className="label" style={{ marginTop: 8, color: "var(--signal-deep)" }}>
            «{keyword}» 로 걸러 보는 중 — 한 번 더 누르면 해제됩니다.
          </p>
        )}
      </div>

      <div className="panel">
        <h3>주제별 보기</h3>
        <p style={{ fontSize: 13, color: "var(--steel)", marginTop: -4 }}>
          내용에서 드러난 역량별로 묶었습니다. 생활기록부·자기소개서 항목과 연결해 쓰기 좋습니다.
        </p>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {data.topics.map((t) => (
            <button
              key={t.key}
              className={`btn btn-sm ${topic === t.key ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setTopic(t.key)}
            >
              {t.label} {t.count}
            </button>
          ))}
        </div>
      </div>

      <div className="panel">
        <h3>{current?.label || "내용"} ({items.length})</h3>
        {items.length === 0 ? (
          <p style={{ fontSize: 13.5, color: "var(--steel)", margin: 0 }}>
            {keyword ? "이 키워드에 해당하는 내용이 없습니다." : "해당하는 내용이 없습니다."}
          </p>
        ) : (
          <div style={{ display: "grid", gap: 10 }}>
            {items.map((it) => (
              <div key={`${it.journal_id}-${current.key}`}
                style={{ background: "var(--paper)", border: "1px solid var(--line)", borderRadius: "var(--radius)", padding: "12px 14px" }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 5 }}>
                  <span className="label" style={{ color: "var(--signal-deep)" }}>{it.entry_date}</span>
                  <span className="label" style={{ color: "var(--steel-light)" }}>{it.kind_label}</span>
                  {it.subject && <span className="label" style={{ color: "var(--steel-light)" }}>{it.subject}</span>}
                </div>
                {showSummary && it.summary && (
                  <p style={{ margin: "0 0 6px", fontSize: 13.5, fontWeight: 600 }}>{it.summary}</p>
                )}
                {(it.excerpt || []).map((line, i) => (
                  <p key={i} style={{ margin: "0 0 4px", fontSize: 14, lineHeight: 1.75 }}>· {line}</p>
                ))}
                {(it.keywords || []).length > 0 && (
                  <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 6 }}>
                    {it.keywords.map((w) => (
                      <span key={w} className="label" style={{ color: "var(--steel-light)" }}>#{w}</span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
