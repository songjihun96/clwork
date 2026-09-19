import { useEffect, useState } from "react";

/** 목록·상세에서 되풀이되는 조각들. 화면마다 다시 만들면 표현이 어긋난다. */

export function Note({ kind = "info", children }) {
  if (!children) return null;
  return <div className={`note ${kind}`}>{children}</div>;
}

export function Empty({ children = "해당하는 항목이 없습니다." }) {
  return <div className="empty">{children}</div>;
}

export function Masked({ value }) {
  if (!value) return <span className="muted tiny">—</span>;
  return <span className="masked">{value}</span>;
}

/** 목록 아래 페이지 이동. 총 건수를 함께 보여줘야 얼마나 남았는지 안다. */
export function Pager({ total, limit, offset, onMove }) {
  if (total <= limit) return null;
  const page = Math.floor(offset / limit) + 1;
  const last = Math.ceil(total / limit);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 14 }}>
      <button className="btn sm" disabled={offset === 0} onClick={() => onMove(offset - limit)}>
        이전
      </button>
      <span className="tiny muted">
        {page} / {last} 쪽 · 전체 {total.toLocaleString()}건
      </span>
      <button
        className="btn sm"
        disabled={offset + limit >= total}
        onClick={() => onMove(offset + limit)}
      >
        다음
      </button>
    </div>
  );
}

export function Modal({ title, sub, onClose, children, foot }) {
  // 목록으로 빠져나올 길이 항상 있어야 한다.
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="veil" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>{title}</h3>
        {sub && <p className="sub">{sub}</p>}
        {children}
        {foot && <div className="modal-foot">{foot}</div>}
      </div>
    </div>
  );
}

/** 목록을 불러오는 흐름이 어디서나 같도록 묶어둔다. */
export function useList(fetcher, deps = [], limit = 30) {
  const [data, setData] = useState({ total: 0, items: [] });
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);

  useEffect(() => {
    setOffset(0);
  }, deps);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");
    fetcher({ limit, offset })
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [...deps, offset, tick]);

  return {
    ...data,
    offset,
    limit,
    loading,
    error,
    move: setOffset,
    reload: () => setTick((t) => t + 1),
  };
}

export const fmtDate = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(
    d.getDate()
  ).padStart(2, "0")}`;
};

export const fmtDateTime = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return `${fmtDate(iso)} ${String(d.getHours()).padStart(2, "0")}:${String(
    d.getMinutes()
  ).padStart(2, "0")}`;
};

export const PLAN_LABEL = {
  free: "무료",
  basic: "베이직",
  premium: "프리미엄",
  platinum: "플래티넘",
};

export const ROLE_LABEL = {
  student: "학생·학부모",
  teacher: "교사",
  school: "학교",
  cs: "상담원",
  admin: "관리자",
};
