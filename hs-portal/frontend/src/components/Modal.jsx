import { useEffect } from "react";

/** 화면 위에 띄우는 창.
 *
 * 같은 모양을 여기저기 손으로 그리다 보니 어떤 건 Esc 로 닫히고 어떤 건 안
 * 닫히는 식으로 조금씩 달라졌다. 닫는 방법은 세 가지 모두 되어야 한다 —
 * 닫기 버튼, 바깥 어두운 곳, Esc.
 *
 * z-index 는 .fab(90) 보다 위로 둔다. 아래에 두면 문의 폼 위로 버튼이
 * 튀어나와 아직 눌러야 할 것처럼 보인다.
 */
export default function Modal({ title, onClose, children, maxWidth = 520 }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // 창이 떠 있는 동안 뒤 화면이 같이 굴러다니면 어디를 만지는지 헷갈린다.
  useEffect(() => {
    const before = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = before; };
  }, []);

  return (
    <div role="dialog" aria-modal="true" aria-label={title}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{
        position: "fixed", inset: 0, zIndex: 100, background: "rgba(0,0,0,.55)",
        display: "grid", placeItems: "center", padding: 16, overflowY: "auto",
      }}>
      <div className="panel" style={{
        width: "100%", maxWidth, margin: 0,
        boxShadow: "0 12px 40px rgba(0,0,0,.35)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <h3 style={{ border: "none", padding: 0, margin: 0, flex: 1 }}>{title}</h3>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>닫기</button>
        </div>
        {children}
      </div>
    </div>
  );
}
