import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import MyClassBar from "../components/MyClassBar";

const KIND_LABEL = { lesson: "수업일지", diary: "학교생활일지" };
// 주소의 ?type= 값. 새로고침해도 고른 탭이 남는다.
export const TYPE_TABS = [["all", "전체보기"], ["class", "수업일지"], ["school", "학교생활일지"]];
const TYPE_KEYS = TYPE_TABS.map(([k]) => k);

export default function Journals() {
  const navigate = useNavigate();
  const [picking, setPicking] = useState(false);   // 무엇을 쓸지 고르는 창
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  const [search, setSearch] = useSearchParams();
  const type = TYPE_KEYS.includes(search.get("type")) ? search.get("type") : "all";
  const [subject, setSubject] = useState("all");

  // 탭마다 서버에서 그 종류만 받아 온다(예전 글도 저장된 종류로 정확히 갈린다).
  useEffect(() => {
    setItems(null);
    api.journals(type)
      .then(setItems)
      .catch((e) => { setError(e.message); setItems([]); });
  }, [type]);

  const pickType = (k) => {
    setSubject("all");
    setSearch(k === "all" ? {} : { type: k }, { replace: true });
  };

  if (error) {
    return (
      <div className="wrap page">
        <div className="notice notice-error">{error}</div>
      </div>
    );
  }
  const byKind = items || [];
  // 수업일지를 볼 때만 과목별로 더 좁힐 수 있다 — 학교생활일지는 과목이 없다.
  const subjects = [...new Set(byKind.filter((i) => i.kind === "lesson" && i.subject)
    .map((i) => i.subject))];
  const shown = (type === "class" && subject !== "all")
    ? byKind.filter((i) => i.subject === subject) : byKind;

  return (
    <div className="wrap page">
      <div className="row" style={{ marginBottom: 6 }}>
        <div>
          <span className="label">내 기록</span>
          <h1 style={{ marginTop: 4 }}>학교생활일지 · 수업일지</h1>
        </div>
        <div className="spacer" />
        <button className="btn btn-primary" onClick={() => setPicking(true)}>새로 쓰기</button>
      </div>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 0 }}>
        오늘 있었던 일, 수업에서 배운 것을 편하게 남겨보세요.
      </p>

      <MyClassBar />

      <div className="row" style={{ margin: "18px 0 12px", flexWrap: "wrap" }}>
        {TYPE_TABS.map(([k, label]) => (
          <button
            key={k}
            className={`btn btn-sm ${type === k ? "" : "btn-ghost"}`}
            aria-pressed={type === k}
            onClick={() => pickType(k)}
          >
            {label}
          </button>
        ))}
      </div>

      {!items && <p className="meta">불러오는 중…</p>}

      {type === "class" && subjects.length > 0 && (
        <div className="row" style={{ margin: "0 0 12px", flexWrap: "wrap", gap: 6 }}>
          <button className={`btn btn-sm ${subject === "all" ? "" : "btn-ghost"}`}
            onClick={() => setSubject("all")}>전체 과목</button>
          {subjects.map((s) => (
            <button key={s} className={`btn btn-sm ${subject === s ? "" : "btn-ghost"}`}
              onClick={() => setSubject(s)}>
              {s}
            </button>
          ))}
        </div>
      )}

      {!items ? null : shown.length === 0 ? (
        <div className="empty">
          <h3>{type === "class" ? "아직 수업일지가 없습니다"
            : type === "school" ? "아직 학교생활일지가 없습니다" : "아직 기록이 없습니다"}</h3>
          <p>오늘 있었던 일부터 한 줄 남겨보세요.</p>
          <button className="btn btn-primary" style={{ marginTop: 12 }}
            onClick={() => setPicking(true)}>
            첫 기록 쓰기
          </button>
        </div>
      ) : (
        shown.map((it) => (
          <Link key={it.id} to={`/journals/${it.id}`} className="entry">
            <div className="row" style={{ gap: 6, marginBottom: 4 }}>
              <span className="badge">{KIND_LABEL[it.kind] || it.kind}</span>
              {it.sent_at && <span className="badge badge-done">선생님께 제출함</span>}
              {/* 답글이 온 것을 목록에서 바로 알아보게 한다. 안 읽은 것만 강조. */}
              {it.feedback_unread && <span className="badge badge-new">선생님 한마디 도착</span>}
              {it.has_feedback && !it.feedback_unread && (
                <span className="badge">선생님 한마디</span>
              )}
            </div>
            <h4>{it.title || it.subject || it.entry_date}</h4>
            {it.preview && <p className="entry-preview">{it.preview}</p>}
            <div className="meta">
              {it.entry_date}
              {it.subject && it.title ? ` · ${it.subject}` : ""}
              {it.teacher_name ? ` · ${it.teacher_name} 선생님` : ""}
            </div>
          </Link>
        ))
      )}
      {picking && <KindPicker onPick={(k) => navigate(`/journals/new?kind=${k}`)}
        onClose={() => setPicking(false)} />}
    </div>
  );
}

/** 무엇을 쓸지 먼저 고른다.
 *
 * 예전에는 쓰기 화면 맨 위 드롭다운에서 골랐는데, 이미 다 쓴 뒤에 종류를
 * 바꾸면 항목이 통째로 갈리는 자리라 위험하기도 하고, 정작 새로 쓸 때는
 * 눈에 안 들어왔다. 고르는 일은 시작할 때 한 번이면 된다.
 */
function KindPicker({ onPick, onClose }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const CHOICES = [
    ["diary", "학교생활일지", "오늘 학교에서 있었던 일, 활동, 느낀 점을 남깁니다."],
    ["lesson", "수업일지", "수업에서 어려웠던 것과 그것을 어떻게 풀었는지 남깁니다."],
  ];

  return (
    <div role="dialog" aria-modal="true" aria-label="무엇을 쓸까요"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{
        position: "fixed", inset: 0, zIndex: 3000, background: "rgba(0,0,0,.5)",
        display: "grid", placeItems: "center", padding: 16, overflowY: "auto",
      }}>
      <div className="panel" style={{ width: "100%", maxWidth: 420, margin: 0 }}>
        <div className="row" style={{ marginBottom: 4 }}>
          <h3 style={{ margin: 0 }}>무엇을 쓸까요?</h3>
          <div className="spacer" />
          <button className="btn btn-sm btn-ghost" onClick={onClose}>닫기</button>
        </div>
        <div style={{ display: "grid", gap: 10, marginTop: 12 }}>
          {CHOICES.map(([k, title, desc]) => (
            <button key={k} onClick={() => onPick(k)} style={{
              display: "block", width: "100%", textAlign: "left", cursor: "pointer",
              padding: 16, borderRadius: 10, font: "inherit", color: "inherit",
              border: "1px solid var(--line)", background: "var(--surface)",
            }}>
              <div style={{ fontWeight: 700, fontSize: 16 }}>{title}</div>
              <div style={{ fontSize: 13, color: "var(--steel)", marginTop: 4, lineHeight: 1.6 }}>
                {desc}
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
