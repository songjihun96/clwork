import { useEffect, useState } from "react";
import { api } from "../api";

const ROWS = [
  ["계열", (s) => s.category],
  ["지역", (s) => s.region],
  ["주소", (s) => s.address],
  ["남녀공학", (s) => s.coed],
  ["기숙사", (s) => (s.dormitory === true ? "있음" : s.dormitory === false ? "없음" : "미확인")],
  ["설립", (s) => s.foundation || "—"],
  ["개교", (s) => (s.established_year ? `${s.established_year}년` : "—")],
  ["학생 수", (s) => (s.student_count != null ? `${s.student_count.toLocaleString()}명` : "—")],
  ["취업률", (s) => (s.employment_rate != null ? `${s.employment_rate}%` : "—")],
  ["학과", (s) => (s.departments.length ? s.departments.join(", ") : "—")],
  ["전화", (s) => s.phone || "—"],
];

export default function CompareTray({ items, onClear, onRemove }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState([]);

  useEffect(() => {
    if (!open) return;
    api.compare(items.map((s) => s.id)).then(setDetail).catch(() => {});
  }, [open, items]);

  return (
    <>
      <div
        style={{
          position: "fixed", bottom: 0, left: 0, right: 0, zIndex: 50,
          background: "var(--surface)", color: "var(--ink)",
          borderTop: "1px solid var(--line)",
          boxShadow: "0 -6px 24px rgba(150, 100, 80, 0.1)",
        }}
      >
        <div className="wrap" style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 0", flexWrap: "wrap" }}>
          <span className="label" style={{ color: "var(--signal-deep)" }}>비교함 {items.length}/3</span>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {items.map((s) => (
              <button
                key={s.id}
                onClick={() => onRemove(s)}
                className="badge"
                style={{ background: "var(--signal-soft)", color: "var(--signal-deep)", borderColor: "transparent", cursor: "pointer", fontWeight: 600 }}
                title="빼기"
              >
                {s.name} ✕
              </button>
            ))}
          </div>
          <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
            <button className="btn btn-signal btn-sm" onClick={() => setOpen(true)} disabled={items.length < 2}>
              나란히 비교
            </button>
            <button className="btn btn-ghost btn-sm" onClick={onClear}>
              비우기
            </button>
          </div>
        </div>
      </div>

      {open && (
        <div className="modal-backdrop" onClick={() => setOpen(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="detail-hero">
              <h2>학교 비교</h2>
              <p>같은 항목을 나란히 놓고 봅니다.</p>
            </div>
            <div className="detail-body">
              <div className="panel" style={{ overflowX: "auto" }}>
                <table className="table">
                  <thead>
                    <tr>
                      <th style={{ minWidth: 74 }}>항목</th>
                      {detail.map((s) => (
                        <th key={s.id} style={{ minWidth: 150, color: "var(--ink)", fontSize: 13, fontFamily: "var(--font-display)", textTransform: "none", letterSpacing: 0 }}>
                          {s.name}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {ROWS.map(([label, get]) => (
                      <tr key={label}>
                        <td><span className="label">{label}</span></td>
                        {detail.map((s) => (
                          <td key={s.id} style={{ fontSize: 13 }}>{get(s)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button className="btn btn-ghost" onClick={() => setOpen(false)}>닫기</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
