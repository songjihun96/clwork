import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";

/** 저장 완료 창. 일지·자기소개서를 저장하면 바로 홈으로 오고, 홈에서 이 창을 띄운다.
 *  [확인]은 닫기. [방금 쓴 … 보기]는 그 글로 돌아가 선생님께 제출하거나 더 고칠 때.
 *  kind: "journal"(기본) | "cover" */
export default function SavedDialog({ kind = "journal", count = 0, id, onClose }) {
  const cover = kind === "cover";
  const btn = useRef(null);
  useEffect(() => {
    btn.current?.focus();
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="saved-backdrop" role="presentation"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="saved-dialog" role="alertdialog" aria-modal="true"
        aria-labelledby="saved-title" aria-describedby="saved-desc">
        <div className="saved-check" aria-hidden="true">✓</div>
        <h3 id="saved-title">저장이 완료되었습니다</h3>
        <p id="saved-desc">
          {cover ? "자기소개서를 저장했습니다."
            : count > 0
              ? `자기소개서 항목 카테고리 ${count}개와 함께 저장했습니다.`
              : "일지를 저장했습니다."}
        </p>
        <div className="row" style={{ gap: 8, justifyContent: "center" }}>
          <button ref={btn} type="button" className="btn btn-primary" onClick={onClose}>확인</button>
          {id && (
            <Link className="btn btn-ghost" to={cover ? `/cover-letters/${id}` : `/journals/${id}`}>
              {cover ? "방금 쓴 자기소개서 보기" : "방금 쓴 일지 보기"}
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
