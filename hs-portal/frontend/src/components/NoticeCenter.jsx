import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, getToken } from "../api";

/** 헤더의 알림 벨 + 전체 공지 팝업.
 *  로그인 사용자는 읽음이 서버에 기록되고, 비로그인은 브라우저에만 기록한다. */
export default function NoticeCenter() {
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(false);
  const [popup, setPopup] = useState(null);
  const [hideToday, setHideToday] = useState(false);
  const [detail, setDetail] = useState(null);   // 목록에서 클릭해 펼쳐 보는 공지
  // 이번 방문에서 이미 닫은 팝업. (닫자마자 같은 팝업이 다시 뜨는 것을 막는다)
  const dismissed = useRef(new Set());

  // 오늘 날짜 (YYYY-MM-DD)
  const today = () => new Date().toISOString().slice(0, 10);

  // { 공지ID: "YYYY-MM-DD" } — 그 날짜 동안은 팝업을 띄우지 않는다
  const readHidden = () => {
    try { return JSON.parse(localStorage.getItem("notice_hide_until") || "{}"); }
    catch { return {}; }
  };

  // 로그인하지 않은 방문자의 읽음 기록 (서버에 남길 수 없으므로 브라우저에 저장)
  const localRead = () => {
    try { return JSON.parse(localStorage.getItem("notice_read") || "[]"); }
    catch { return []; }
  };

  const load = () =>
    api.notices()
      .then((raw) => {
        // 비로그인 사용자는 브라우저 기록을 읽음 상태로 합쳐준다
        const local = localRead();
        const items = (raw.items || []).map((n) => ({
          ...n,
          is_read: n.is_read || local.includes(n.id),
        }));
        const d = {
          ...raw,
          items,
          unread: items.filter((n) => !n.is_read).length,
        };
        setData(d);
        const hidden = readHidden();
        // '오늘은 그만 보기'로 가려두지 않은 팝업 공지 하나를 띄운다
        const next = (d.popups || []).find(
          (p) => hidden[p.id] !== today() && !dismissed.current.has(p.id)
        );
        setPopup(next || null);
        setHideToday(false);
      })
      .catch(() => {});

  useEffect(() => {
    load();
    const t = setInterval(load, 60000); // 1분마다 새 공지 확인
    return () => clearInterval(t);
  }, []);

  const markRead = async (id) => {
    // 브라우저에도 기록해 비로그인 상태에서도 배지가 사라지게 한다
    const local = localRead();
    if (!local.includes(id)) {
      localStorage.setItem("notice_read", JSON.stringify([...local, id]));
    }
    if (getToken()) {
      try { await api.readNotice(id); } catch { /* 무시 */ }
    }
    load();
  };

  const closePopup = async () => {
    if (!popup) return;
    if (hideToday) {
      // 오늘 하루 이 공지는 다시 띄우지 않는다
      const hidden = readHidden();
      hidden[popup.id] = today();
      localStorage.setItem("notice_hide_until", JSON.stringify(hidden));
    }
    const id = popup.id;
    dismissed.current.add(id);   // 이번 방문 동안은 다시 띄우지 않는다
    setPopup(null);
    await markRead(id);          // 알림함에서는 읽음 처리
  };

  if (!data) return null;
  const items = data.items || [];

  return (
    <>
      <div className="notice-wrap">
        <button
          className="notice-bell"
          onClick={() => setOpen((v) => !v)}
          aria-label="알림"
          title="알림"
        >
          🔔
          {data.unread > 0 && <span className="notice-badge">{data.unread}</span>}
        </button>

        {open && createPortal(
          <>
            <div className="notice-backdrop" onClick={() => setOpen(false)} />
            <div className="notice-panel">
              <div className="notice-panel-head">
                <b>알림</b>
                <span className="label" style={{ color: "var(--steel-light)" }}>
                  안 읽음 {data.unread}
                </span>
                <a href="/notices" className="label" style={{ color: "var(--signal-deep)", marginLeft: "auto" }}>
                  공지사항 전체 보기 →
                </a>
              </div>
              {items.length === 0 ? (
                <p style={{ fontSize: 13.5, color: "var(--steel)", padding: "14px" }}>
                  받은 공지가 없습니다.
                </p>
              ) : (
                <div className="notice-list">
                  {items.map((n) => (
                    <button
                      key={n.id}
                      className={`notice-item ${n.is_read ? "read" : ""}`}
                      onClick={() => { setDetail(n); setOpen(false); markRead(n.id); }}
                    >
                      <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 2 }}>
                        {!n.is_read && <span className="notice-dot" />}
                        {n.is_important && <span className="badge badge-important">중요</span>}
                        <b style={{ fontSize: 13.5 }}>{n.title}</b>
                      </div>
                      {n.image_url && (
                        <span className="label" style={{ color: "var(--signal-deep)" }}>🖼 이미지</span>
                      )}
                      {n.body && (
                        <p className="notice-item-body">{n.body}</p>
                      )}
                      <span className="label" style={{ color: "var(--steel-light)" }}>
                        {n.created_at?.slice(0, 10)}
                        {n.author_name ? ` · ${n.author_name}` : ""}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </>,
          document.body
        )}
      </div>

      {/* 전체 공지 팝업 */}
      {popup && (
        <NoticeModal
          notice={popup}
          onClose={closePopup}
          footer={
            <label style={{ display: "flex", gap: 6, alignItems: "center",
                            fontSize: 13.5, color: "var(--steel)", cursor: "pointer" }}>
              <input type="checkbox" checked={hideToday}
                onChange={(e) => setHideToday(e.target.checked)} />
              오늘은 그만 보기
            </label>
          }
        />
      )}

      {/* 알림 목록에서 클릭해 펼친 공지 */}
      {detail && <NoticeModal notice={detail} onClose={() => setDetail(null)} />}
    </>
  );
}


/** 공지 상세 모달. 이미지만 있는 공지, 글만 있는 공지, 둘 다 있는 공지를 모두 지원한다. */
function NoticeModal({ notice, onClose, footer = null }) {
  const hasText = Boolean((notice.body || "").trim());
  // 헤더에 backdrop-filter 가 있으면 position:fixed 기준이 헤더가 되어버린다.
  // 그래서 body 에 직접 그려 화면 정중앙에 오도록 한다.
  return createPortal(
    <div className="notice-modal-backdrop" onClick={onClose}>
      <div className="notice-modal" onClick={(e) => e.stopPropagation()}>
        <div className="notice-modal-body">
          <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            {notice.is_important && <span className="badge badge-important">중요</span>}
            <span className="label" style={{ color: "var(--steel-light)" }}>
              {notice.created_at?.slice(0, 10)}
              {notice.author_name ? ` · ${notice.author_name}` : ""}
            </span>
          </div>
          <h2 style={{ fontSize: 19, margin: "8px 0 12px" }}>{notice.title}</h2>

          {notice.image_url && (
            <img
              src={notice.image_url}
              alt={notice.title}
              className="notice-image"
              style={{ marginBottom: hasText ? 14 : 0 }}
            />
          )}

          {hasText && (
            <p style={{ fontSize: 14.5, lineHeight: 1.75, whiteSpace: "pre-wrap", margin: 0 }}>
              {notice.body}
            </p>
          )}
        </div>

        <div className="notice-modal-foot">
          {footer || <span />}
          <button className="btn btn-primary btn-sm" onClick={onClose}>확인</button>
        </div>
      </div>
    </div>,
    document.body
  );
}
