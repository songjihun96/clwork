import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import InquiryModal from "./InquiryModal";

/** 오른쪽 아래 동그란 버튼.
 *
 * 관리자가 정한 대로 둘 중 하나를 한다.
 *   link    — 등록한 주소를 새 탭으로 연다
 *   inquiry — 교육·컨설팅 문의 폼을 **그 자리에서** 띄운다
 *
 * 폼을 띄우는 쪽으로 만든 이유: 문의는 아무 화면을 보다가도 남기게 된다.
 * 새 탭이나 새 페이지로 보내면 문의를 그만두는 순간 처음 보던 자리로
 * 돌아오지 못한다.
 *
 * 켜짐 여부와 노출 대상(역할)은 서버가 판단해 내려준다.
 */
export default function FloatingButton() {
  const { user } = useAuth();
  const [cfg, setCfg] = useState(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    api.floatingButton()
      .then((d) => { if (alive) setCfg(d?.enabled ? d : null); })
      .catch(() => { if (alive) setCfg(null); });
    return () => { alive = false; };
  }, [user?.id, user?.role]);   // 로그인 상태가 바뀌면 다시 확인

  if (!cfg) return null;

  if (cfg.action !== "inquiry") {
    return (
      <a className="fab" href={cfg.url} target="_blank" rel="noopener noreferrer" title={cfg.label}>
        <span className="fab-label">{cfg.label}</span>
        <span className="fab-circle" aria-hidden="true">↗</span>
      </a>
    );
  }

  return (
    <>
      <button className="fab" onClick={() => setOpen(true)} title={cfg.label}
        style={{ border: "none", cursor: "pointer", font: "inherit" }}>
        <span className="fab-label">{cfg.label}</span>
        <span className="fab-circle" aria-hidden="true">↗</span>
      </button>

      {open && <InquiryModal onClose={() => setOpen(false)} />}
    </>
  );
}
