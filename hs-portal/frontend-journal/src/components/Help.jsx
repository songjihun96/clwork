import { useEffect, useRef, useState } from "react";

/** 전문용어 옆에 붙이는 물음표 아이콘. 누르면 짧은 설명이 바로 뜬다.
 *  매뉴얼을 따로 열지 않아도 화면에서 뜻을 알 수 있게 하려고 만들었다. */
export default function Help({ text }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <span ref={ref} className="help">
      <button type="button" className="help-icon" aria-label="도움말"
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}>
        ?
      </button>
      {open && <span className="help-pop" role="tooltip">{text}</span>}
    </span>
  );
}
