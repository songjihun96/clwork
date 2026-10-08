import { useEffect, useRef, useState } from "react";

// 푸터의 패밀리 사이트 선택. 링크를 나열하면 자리를 많이 차지해 드롭다운으로 둔다.
// current 로 지금 보고 있는 사이트를 알려주면 목록에서 뺀다.
export default function FamilySites({ current = "" }) {
  const [open, setOpen] = useState(false);
  const boxRef = useRef(null);

  const sites = [
    { key: "udj", name: "우리동네 직업계고", desc: "특성화고·마이스터고 찾기",
      url: "https://udjschool.ggm.kr" },
    { key: "diary", name: "기록해", desc: "학교생활일지·수업일지·자기소개서",
      url: "https://diary.ggm.kr" },
    { key: "sinmoon", name: "특성화고신문", desc: "직업계고 전문 언론",
      url: "https://www.sinmoon.net" },
  ].filter((s) => s.key !== current);

  // 바깥을 누르거나 Esc 를 누르면 닫는다.
  useEffect(() => {
    if (!open) return;
    const onDown = (e) => {
      if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={boxRef} style={{ position: "relative", display: "inline-block" }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="true"
        style={{
          display: "flex", alignItems: "center", gap: 8,
          border: "1px solid var(--line)", borderRadius: 8,
          background: "var(--surface)", color: "var(--ink-soft)",
          padding: "8px 12px", font: "inherit", fontSize: 13, fontWeight: 600,
          cursor: "pointer", minWidth: 190, textAlign: "left",
        }}
      >
        <span style={{ flex: 1 }}>패밀리 사이트</span>
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"
          style={{ transform: open ? "rotate(180deg)" : "none", transition: "transform .15s" }}>
          <path d="M2 4.5L6 8.5L10 4.5" fill="none" stroke="currentColor"
            strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div
          role="menu"
          style={{
            position: "absolute", bottom: "calc(100% + 6px)", left: 0,
            minWidth: 232, background: "var(--surface)",
            border: "1px solid var(--line)", borderRadius: 10,
            boxShadow: "0 8px 24px -12px rgba(45,42,50,.4)",
            padding: 6, zIndex: 20,
          }}
        >
          {sites.map((s) => (
            <a
              key={s.key}
              href={s.url}
              target="_blank"
              rel="noreferrer"
              role="menuitem"
              onClick={() => setOpen(false)}
              style={{
                display: "block", padding: "9px 10px", borderRadius: 6,
                color: "var(--ink)", textDecoration: "none",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "var(--paper)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            >
              <span style={{ display: "block", fontSize: 13.5, fontWeight: 700 }}>{s.name}</span>
              <span style={{ display: "block", fontSize: 12, color: "var(--steel-light)", marginTop: 1 }}>
                {s.desc}
              </span>
            </a>
          ))}
          <div style={{ padding: "8px 10px 4px", borderTop: "1px solid var(--line)",
                        marginTop: 4, fontSize: 11.5, color: "var(--steel-light)",
                        lineHeight: 1.6 }}>
            우리동네 직업계고와 기록해는 같은 계정으로 이용합니다.
          </div>
        </div>
      )}
    </div>
  );
}
